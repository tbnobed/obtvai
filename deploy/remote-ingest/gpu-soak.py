"""Read-only mixed inference soak. Run only in an isolated GPU worker image.

Uses existing completed media, ephemeral /tmp outputs, and cached models.
Never invokes Celery tasks or writes application records.
"""
import argparse
import faulthandler
import gc
import os
from pathlib import Path
import subprocess
import sys
import time


def prepare():
    from db import get_session
    from sqlalchemy import text
    db = get_session()
    try:
        rows = db.execute(text(
            "SELECT m.id,m.proxy_path,(f.appearances->0->>'start_time')::float "
            "FROM media_assets m JOIN face_clusters f ON f.media_id=m.id "
            "WHERE m.status='ready' AND jsonb_array_length(f.appearances)>0 "
            "AND m.duration_seconds BETWEEN 30 AND 600 ORDER BY m.created_at DESC LIMIT 100"
        )).all()
    finally:
        db.close()
    for media_id, proxy, face_time in rows:
        audio = Path("/artifacts/audio") / (str(media_id) + ".wav")
        if audio.is_file() and proxy and Path(proxy).is_file():
            for source, args in (
                (str(audio), ["-t", "30", "-ar", "16000", "-ac", "1", "/tmp/soak.wav"]),
                (proxy, ["-frames:v", "1", "/tmp/soak.jpg"]),
            ):
                subprocess.run(
                    ["ffmpeg", "-v", "error", "-y", "-ss",
                     str(float(face_time) + 0.25) if source == proxy else "5", "-i", source, *args],
                    check=True, timeout=60, stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
            return
    raise RuntimeError("No completed shared audio/proxy pair available")


def stage(name):
    import torch
    import numpy as np
    assert torch.cuda.device_count() == 1, "Expose exactly one GPU"
    assert os.getenv("SOAK_EXPECT_GPU", "4500") in torch.cuda.get_device_name(), "Wrong GPU"
    assert not ({10, 11} & os.sched_getaffinity(0)), "CPU containment missing"
    if name == "compute":
        for _ in range(100):
            x = torch.randn(2048, 2048, device="cuda", dtype=torch.float16)
            assert torch.isfinite(x @ x).all().item()
        torch.cuda.synchronize()
    elif name == "face":
        import cv2
        import onnxruntime as ort
        ort.preload_dlls()
        from insightface.app import FaceAnalysis
        app = FaceAnalysis(name="buffalo_l", providers=["CUDAExecutionProvider",
                                                       "CPUExecutionProvider"])
        app.prepare(ctx_id=0, det_size=(640, 640))
        for model in app.models.values():
            assert "CUDAExecutionProvider" in model.session.get_providers()
        # Log the model boundary, never media content, for native crash diagnosis.
        def traced(label, call):
            def run(*args, **kwargs):
                print("MODEL_BEGIN", label, flush=True)
                result = call(*args, **kwargs)
                print("MODEL_PASS", label, flush=True)
                return result
            return run
        app.det_model.detect = traced("detection", app.det_model.detect)
        for model_name, model in app.models.items():
            if model_name != "detection":
                model.get = traced(model_name, model.get)
        image = cv2.imread("/tmp/soak.jpg")
        assert image is not None
        for _ in range(10):
            faces = app.get(image)
            assert len(faces) > 0, "Sample has no faces; full face-model coverage not established"
            feat = app.models["recognition"].get_feat(cv2.resize(image, (112, 112)))
            assert np.isfinite(feat).all()
    elif name == "embed":
        from transformers import AutoModel, AutoProcessor
        from config import VISION_MODEL
        from PIL import Image
        model = AutoModel.from_pretrained(VISION_MODEL, local_files_only=True).to("cuda").eval()
        processor = AutoProcessor.from_pretrained(VISION_MODEL, local_files_only=True)
        inputs = processor(images=Image.open("/tmp/soak.jpg").convert("RGB"), return_tensors="pt").to("cuda")
        with torch.inference_mode():
            for _ in range(3):
                features = model.get_image_features(**inputs)
                assert torch.isfinite(features).all().item()
    elif name == "whisper":
        from faster_whisper import WhisperModel
        model = WhisperModel(os.getenv("WHISPER_MODEL", "large-v3"),
                             device="cuda", compute_type="float16", local_files_only=True)
        segments, _ = model.transcribe("/tmp/soak.wav", vad_filter=True,
                                       condition_on_previous_text=False)
        for _ in segments:
            pass
        del model
    elif name == "diarize":
        from pyannote.audio import Pipeline
        original = torch.load

        def load(*args, **kwargs):
            kwargs["weights_only"] = False
            return original(*args, **kwargs)

        torch.load = load
        try:
            model = os.getenv("DIARIZATION_MODEL", "pyannote/speaker-diarization-community-1")
            try:
                pipeline = Pipeline.from_pretrained(model, token=os.getenv("HF_TOKEN") or None)
            except TypeError:
                pipeline = Pipeline.from_pretrained(model, use_auth_token=os.getenv("HF_TOKEN", ""))
        finally:
            torch.load = original
        assert pipeline is not None
        pipeline.to(torch.device("cuda"))
        import soundfile as sf
        waveform, sample_rate = sf.read("/tmp/soak.wav", dtype="float32", always_2d=True)
        result = pipeline({"waveform": torch.from_numpy(waveform.T.copy()),
                           "sample_rate": sample_rate})
        annotation = getattr(result, "speaker_diarization", result)
        for turn, _, _ in annotation.itertracks(yield_label=True):
            assert np.isfinite(turn.start) and np.isfinite(turn.end)
        del pipeline
    gc.collect()
    print("STAGE_PASS", name, flush=True)


def main():
    faulthandler.enable()
    parser = argparse.ArgumentParser()
    parser.add_argument("--minutes", type=int, default=15)
    parser.add_argument("--stage", choices=["compute", "face", "embed", "whisper", "diarize"])
    parser.add_argument("--diagnose-face", action="store_true")
    args = parser.parse_args()
    if args.stage:
        stage(args.stage)
        return
    if not 1 <= args.minutes <= 60:
        parser.error("--minutes must be 1–60")
    prepare()
    if args.diagnose_face:
        stage("face")
        return
    start = time.monotonic()
    cycles = 0
    while time.monotonic() - start < args.minutes * 60:
        for name in ("compute", "face", "embed", "whisper", "diarize"):
            # Fresh processes repeatedly exercise model initialization/JIT paths.
            subprocess.run([sys.executable, "-u", __file__, "--stage", name],
                           check=True, timeout=180)
        cycles += 1
        print("CYCLE_PASS", cycles, "elapsed_seconds", round(time.monotonic() - start),
              flush=True)
    print("SOAK_PASS", cycles, "cycles", round(time.monotonic() - start), "seconds",
          flush=True)


if __name__ == "__main__":
    main()