"""Extract a face embedding + crop from an uploaded reference photo.

Uses the same InsightFace stack as the worker's face_detect task (SCRFD
detector + ArcFace embedder, buffalo_l), so photo embeddings are directly
comparable to the face embeddings identify.py stores on people. Runs on CPU —
a single photo takes well under a second and the GPUs stay free for workers.
"""
import io
import threading

_lock = threading.Lock()
_app = None

MAX_PHOTO_BYTES = 15 * 1024 * 1024
MIN_DET_SCORE = 0.60


def _get_app():
    global _app
    with _lock:
        if _app is None:
            from insightface.app import FaceAnalysis

            # root under /root/.cache so the models_cache volume persists the
            # one-time buffalo_l download across container rebuilds.
            app = FaceAnalysis(
                name="buffalo_l",
                root="/root/.cache/insightface",
                providers=["CPUExecutionProvider"],
            )
            app.prepare(ctx_id=-1, det_size=(640, 640))
            _app = app
        return _app


def decode_photo(photo_bytes: bytes):
    """Decode + orient the uploaded image. Raises on unreadable input —
    callers map that to a 422, distinct from model/runtime failures."""
    from PIL import Image, ImageOps

    img = Image.open(io.BytesIO(photo_bytes))
    img = ImageOps.exif_transpose(img).convert("RGB")
    # Bound the long edge; SCRFD detects at 640px anyway and huge photos just
    # cost memory.
    if max(img.size) > 1920:
        img.thumbnail((1920, 1920))
    return img


def extract_face(img):
    """Returns (embedding_list, crop_jpeg_bytes) for the most prominent face
    in a decoded PIL image, or (None, None) if no face is confidently detected."""
    import numpy as np
    import cv2

    rgb = np.asarray(img)
    bgr = cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)
    faces = [f for f in _get_app().get(bgr) if float(f.det_score) >= MIN_DET_SCORE]
    if not faces:
        return None, None

    # Most prominent = largest box area.
    def _area(f):
        x1, y1, x2, y2 = f.bbox
        return max(0.0, float(x2 - x1)) * max(0.0, float(y2 - y1))

    face = max(faces, key=_area)
    emb = [float(v) for v in face.normed_embedding]

    x1, y1, x2, y2 = [int(v) for v in face.bbox]
    w, h = x2 - x1, y2 - y1
    mx, my = int(w * 0.35), int(h * 0.35)
    cx1, cy1 = max(0, x1 - mx), max(0, y1 - my)
    cx2, cy2 = min(img.width, x2 + mx), min(img.height, y2 + my)
    crop = img.crop((cx1, cy1, cx2, cy2))
    if max(crop.size) > 512:
        crop.thumbnail((512, 512))
    buf = io.BytesIO()
    crop.save(buf, format="JPEG", quality=88)
    return emb, buf.getvalue()
