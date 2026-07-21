"""Lip-sync pass for dubbed videos (Wav2Lip-GAN inference, vendored).

Why Wav2Lip and not MuseTalk/LatentSync: those ship as research repos with
mmlab/torch-pin dependency stacks that conflict with our pinned torch 2.8
(+cu128). Wav2Lip's inference needs only torch + opencv + librosa + a face
detector, all of which are already in this image. The engine seam is
`apply_lipsync()` — a future engine only has to honor that signature.

Weights: `wav2lip_gan.pth` fetched from HuggingFace on first run (env
LIPSYNC_MODEL_REPO / LIPSYNC_MODEL_FILE, or LIPSYNC_MODEL_PATH for a local
file). Face tracking reuses the cached InsightFace SCRFD detector.

Only frames inside dubbed speech segments are touched; everything else
passes through untouched, so cutaways/b-roll/profiles keep the original
footage (which is also where lip-sync looks worst).
"""
import os
import math
import subprocess

MEL_STEP = 16          # mel frames the model sees per video frame
IMG_SIZE = 96          # Wav2Lip face crop size
PADS = (0, 12, 0, 0)   # y1, y2, x1, x2 crop padding (extra chin)
BATCH = 64


# ── Vendored Wav2Lip architecture ────────────────────────────────────────────

def _build_model():
    import torch
    from torch import nn

    class Conv2d(nn.Module):
        def __init__(self, cin, cout, kernel_size, stride, padding, residual=False):
            super().__init__()
            self.conv_block = nn.Sequential(
                nn.Conv2d(cin, cout, kernel_size, stride, padding),
                nn.BatchNorm2d(cout),
            )
            self.act = nn.ReLU()
            self.residual = residual

        def forward(self, x):
            out = self.conv_block(x)
            if self.residual:
                out += x
            return self.act(out)

    class Conv2dTranspose(nn.Module):
        def __init__(self, cin, cout, kernel_size, stride, padding, output_padding=0):
            super().__init__()
            self.conv_block = nn.Sequential(
                nn.ConvTranspose2d(cin, cout, kernel_size, stride, padding, output_padding),
                nn.BatchNorm2d(cout),
            )
            self.act = nn.ReLU()

        def forward(self, x):
            return self.act(self.conv_block(x))

    class Wav2Lip(nn.Module):
        def __init__(self):
            super().__init__()
            self.face_encoder_blocks = nn.ModuleList([
                nn.Sequential(Conv2d(6, 16, 7, 1, 3)),
                nn.Sequential(Conv2d(16, 32, 3, 2, 1),
                              Conv2d(32, 32, 3, 1, 1, residual=True),
                              Conv2d(32, 32, 3, 1, 1, residual=True)),
                nn.Sequential(Conv2d(32, 64, 3, 2, 1),
                              Conv2d(64, 64, 3, 1, 1, residual=True),
                              Conv2d(64, 64, 3, 1, 1, residual=True),
                              Conv2d(64, 64, 3, 1, 1, residual=True)),
                nn.Sequential(Conv2d(64, 128, 3, 2, 1),
                              Conv2d(128, 128, 3, 1, 1, residual=True),
                              Conv2d(128, 128, 3, 1, 1, residual=True)),
                nn.Sequential(Conv2d(128, 256, 3, 2, 1),
                              Conv2d(256, 256, 3, 1, 1, residual=True),
                              Conv2d(256, 256, 3, 1, 1, residual=True)),
                nn.Sequential(Conv2d(256, 512, 3, 2, 1),
                              Conv2d(512, 512, 3, 1, 1, residual=True)),
                nn.Sequential(Conv2d(512, 512, 3, 1, 0),
                              Conv2d(512, 512, 1, 1, 0)),
            ])
            self.audio_encoder = nn.Sequential(
                Conv2d(1, 32, 3, 1, 1),
                Conv2d(32, 32, 3, 1, 1, residual=True),
                Conv2d(32, 32, 3, 1, 1, residual=True),
                Conv2d(32, 64, 3, (3, 1), 1),
                Conv2d(64, 64, 3, 1, 1, residual=True),
                Conv2d(64, 64, 3, 1, 1, residual=True),
                Conv2d(64, 128, 3, 3, 1),
                Conv2d(128, 128, 3, 1, 1, residual=True),
                Conv2d(128, 128, 3, 1, 1, residual=True),
                Conv2d(128, 256, 3, (3, 2), 1),
                Conv2d(256, 256, 3, 1, 1, residual=True),
                Conv2d(256, 512, 3, 1, 0),
                Conv2d(512, 512, 1, 1, 0),
            )
            self.face_decoder_blocks = nn.ModuleList([
                nn.Sequential(Conv2d(512, 512, 1, 1, 0)),
                nn.Sequential(Conv2dTranspose(1024, 512, 3, 1, 0),
                              Conv2d(512, 512, 3, 1, 1, residual=True)),
                nn.Sequential(Conv2dTranspose(1024, 512, 3, 2, 1, 1),
                              Conv2d(512, 512, 3, 1, 1, residual=True),
                              Conv2d(512, 512, 3, 1, 1, residual=True)),
                nn.Sequential(Conv2dTranspose(768, 384, 3, 2, 1, 1),
                              Conv2d(384, 384, 3, 1, 1, residual=True),
                              Conv2d(384, 384, 3, 1, 1, residual=True)),
                nn.Sequential(Conv2dTranspose(512, 256, 3, 2, 1, 1),
                              Conv2d(256, 256, 3, 1, 1, residual=True),
                              Conv2d(256, 256, 3, 1, 1, residual=True)),
                nn.Sequential(Conv2dTranspose(320, 128, 3, 2, 1, 1),
                              Conv2d(128, 128, 3, 1, 1, residual=True),
                              Conv2d(128, 128, 3, 1, 1, residual=True)),
                nn.Sequential(Conv2dTranspose(160, 64, 3, 2, 1, 1),
                              Conv2d(64, 64, 3, 1, 1, residual=True),
                              Conv2d(64, 64, 3, 1, 1, residual=True)),
            ])
            self.output_block = nn.Sequential(
                Conv2d(80, 32, 3, 1, 1),
                nn.Conv2d(32, 3, 1, 1, 0),
                nn.Sigmoid(),
            )

        def forward(self, audio_sequences, face_sequences):
            feats = []
            x = face_sequences
            for f in self.face_encoder_blocks:
                x = f(x)
                feats.append(x)
            x = self.audio_encoder(audio_sequences)
            for f in self.face_decoder_blocks:
                x = f(x)
                x = torch.cat((x, feats[-1]), dim=1)
                feats.pop()
            return self.output_block(x)

    return Wav2Lip()


_model_cache = {}


def _weights_path() -> str:
    local = os.getenv("LIPSYNC_MODEL_PATH", "")
    if local:
        if not os.path.exists(local):
            raise RuntimeError(f"LIPSYNC_MODEL_PATH set but missing: {local}")
        return local
    from huggingface_hub import hf_hub_download
    repo = os.getenv("LIPSYNC_MODEL_REPO", "camenduru/Wav2Lip")
    fname = os.getenv("LIPSYNC_MODEL_FILE", "checkpoints/wav2lip_gan.pth")
    return hf_hub_download(repo_id=repo, filename=fname)


def _load_model():
    if "m" in _model_cache:
        return _model_cache["m"]
    import torch
    device = "cuda" if torch.cuda.is_available() else "cpu"
    ckpt = torch.load(_weights_path(), map_location=device, weights_only=False)
    state = ckpt.get("state_dict", ckpt)
    state = {k.replace("module.", ""): v for k, v in state.items()}
    model = _build_model()
    model.load_state_dict(state)
    model = model.to(device).eval()
    _model_cache["m"] = (model, device)
    return _model_cache["m"]


# torch is imported lazily; forward passes run only inside apply_lipsync,
# which imports it into this module-level name first.
torch = None


# ── Audio → mel (matches Wav2Lip training hparams) ───────────────────────────

def _melspectrogram(wav_path: str):
    import numpy as np
    import librosa
    y, _ = librosa.load(wav_path, sr=16000)
    y = np.append(y[0], y[1:] - 0.97 * y[:-1])  # preemphasis
    D = librosa.stft(y=y, n_fft=800, hop_length=200, win_length=800)
    mel_basis = librosa.filters.mel(sr=16000, n_fft=800, n_mels=80, fmin=55, fmax=7600)
    S = np.dot(mel_basis, np.abs(D))
    S = 20 * np.log10(np.maximum(1e-5, S)) - 20  # amp→db, ref 20
    S = np.clip(8.0 * ((S + 100) / 100) - 4.0, -4.0, 4.0)  # symmetric norm
    return S.astype(np.float32)


def _smooth_boxes(boxes, window=5):
    smoothed = []
    for i in range(len(boxes)):
        chunk = [b for b in boxes[max(0, i - window // 2): i + window // 2 + 1] if b is not None]
        if boxes[i] is None or not chunk:
            smoothed.append(boxes[i])
        else:
            import numpy as np
            smoothed.append(tuple(np.mean(np.array(chunk), axis=0).astype(int)))
    return smoothed


def apply_lipsync(video_path: str, speech_wav: str, segments, out_path: str,
                  progress=None, log=None) -> dict:
    """Re-render `video_path` with mouths matched to `speech_wav`.

    segments: [(start_s, end_s)] dubbed speech windows — only these frames
    are modified, and only when a face is confidently detected.
    Returns {"synced_frames": int, "total_frames": int}.
    """
    import numpy as np
    import cv2
    global torch
    import torch as _torch
    torch = _torch

    def _log(msg):
        if log:
            log(msg)

    model, device = _load_model()
    from tasks.face_detect import _load_face_app
    face_app = _load_face_app()

    mel = _melspectrogram(speech_wav)
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        raise RuntimeError(f"Cannot open video: {video_path}")
    fps = cap.get(cv2.CAP_PROP_FPS) or 25.0
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
    w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    mel_per_frame = 80.0 / fps  # mel hop = 200 @16k → 80 mel frames/sec

    tmp_avi = out_path + ".tmp.avi"
    writer = cv2.VideoWriter(tmp_avi, cv2.VideoWriter_fourcc(*"MJPG"), fps, (w, h))
    if not writer.isOpened():
        cap.release()
        raise RuntimeError("Cannot open video writer")

    spans = [(float(s), float(e)) for s, e in segments
             if math.isfinite(float(s)) and math.isfinite(float(e))]

    def in_speech(t):
        return any(s - 0.05 <= t <= e + 0.05 for s, e in spans)

    y1p, y2p, x1p, x2p = PADS
    synced = 0
    frame_idx = 0
    # Batches of (frame, box, mel_chunk); flushed at BATCH or when a
    # passthrough frame breaks the run (writer order must match input order).
    pend_frames, pend_boxes, pend_mels = [], [], []

    def flush():
        nonlocal synced
        if not pend_frames:
            return
        boxes = _smooth_boxes(pend_boxes)
        img_batch, mel_batch, metas = [], [], []
        for idx, (f, box, m) in enumerate(zip(pend_frames, boxes, pend_mels)):
            if box is None:
                continue
            x1, y1, x2, y2 = box
            y1 = max(0, y1 - y1p); y2 = min(h, y2 + y2p)
            x1 = max(0, x1 - x1p); x2 = min(w, x2 + x2p)
            if x2 - x1 < 16 or y2 - y1 < 16:
                continue
            face = cv2.resize(f[y1:y2, x1:x2], (IMG_SIZE, IMG_SIZE))
            masked = face.copy()
            masked[IMG_SIZE // 2:] = 0
            img_batch.append(np.concatenate((masked, face), axis=2))
            mel_batch.append(m)
            metas.append((idx, (x1, y1, x2, y2)))
        if img_batch:
            ib = torch.FloatTensor(np.transpose(np.asarray(img_batch), (0, 3, 1, 2))).to(device) / 255.0
            mb = torch.FloatTensor(np.asarray(mel_batch)).unsqueeze(1).to(device)
            with torch.no_grad():
                pred = model(mb, ib)
            pred = (pred.cpu().numpy().transpose(0, 2, 3, 1) * 255.0).astype(np.uint8)
            # Patch mouths in place; frames are written strictly in input
            # order below, so interleaved no-face frames never reorder output.
            for p, (idx, (x1, y1, x2, y2)) in zip(pred, metas):
                patch = cv2.resize(p, (x2 - x1, y2 - y1))
                pend_frames[idx][y1:y2, x1:x2] = patch
                synced += 1
        for f in pend_frames:
            writer.write(f)
        pend_frames.clear(); pend_boxes.clear(); pend_mels.clear()

    while True:
        ok, frame = cap.read()
        if not ok:
            break
        t = frame_idx / fps
        mel_start = int(t * 16000 / 200)  # hop-aligned mel index
        chunk = None
        if in_speech(t) and mel_start + MEL_STEP <= mel.shape[1]:
            chunk = mel[:, mel_start: mel_start + MEL_STEP]
        if chunk is None:
            flush()
            writer.write(frame)
        else:
            faces = face_app.get(frame)
            box = None
            if faces:
                best = max(faces, key=lambda fc: (fc.bbox[2] - fc.bbox[0]) * (fc.bbox[3] - fc.bbox[1]))
                if getattr(best, "det_score", 1.0) >= 0.55:
                    box = tuple(int(v) for v in best.bbox)
            pend_frames.append(frame)
            pend_boxes.append(box)
            pend_mels.append(chunk)
            if len(pend_frames) >= BATCH:
                flush()
        frame_idx += 1
        if progress and total_frames and frame_idx % 100 == 0:
            progress(frame_idx / total_frames)
    flush()
    cap.release()
    writer.release()

    _log(f"Lip-synced {synced}/{frame_idx} frames — encoding")
    # Re-encode + carry over the dubbed audio from the input video.
    result = subprocess.run(
        ["ffmpeg", "-y", "-i", tmp_avi, "-i", video_path,
         "-map", "0:v:0", "-map", "1:a:0",
         "-c:v", "libx264", "-crf", "18", "-preset", "fast",
         "-pix_fmt", "yuv420p", "-c:a", "copy",
         "-movflags", "+faststart", out_path],
        capture_output=True, text=True, timeout=7200,
    )
    try:
        os.remove(tmp_avi)
    except OSError:
        pass
    if result.returncode != 0 or not os.path.exists(out_path):
        raise RuntimeError(f"Lip-sync encode failed: {result.stderr[-300:]}")
    return {"synced_frames": synced, "total_frames": frame_idx}
