"""Bounded, read-only workload probe. Run separately with each GPU exposed."""
import gc
import os
import subprocess
import time
import torch
from sqlalchemy import text
from db import get_session
from faster_whisper import WhisperModel
from catalog_storage import require_archive_storage

assert torch.cuda.device_count() == 1, "Expose exactly one GPU for isolation"
require_archive_storage()
print("GPU:", torch.cuda.get_device_name(), flush=True)
deadline = time.monotonic() + 30
cycles = 0
while time.monotonic() < deadline:
    a = torch.randn(4096, 4096, device="cuda", dtype=torch.float16)
    b = a @ a
    assert torch.isfinite(b).all().item()
    torch.cuda.synchronize()
    del a, b
    torch.cuda.empty_cache()
    cycles += 1
print("Allocation/compute cycles:", cycles, flush=True)
db = get_session()
try:
    ids = db.execute(text(
        "SELECT id FROM media_assets WHERE duration_seconds BETWEEN 5 AND 90 "
        "AND status='ready' ORDER BY created_at DESC LIMIT 30"
    )).scalars().all()
finally:
    db.close()
source = next((os.path.join("/artifacts/audio", i + ".wav") for i in ids
               if os.path.isfile(os.path.join("/artifacts/audio", i + ".wav"))), None)
if source is None:
    raise RuntimeError("No short completed source available for the inference probe")
subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", source, "-t", "15",
                "-ar", "16000", "-ac", "1", "/tmp/obtv-gpu-check.wav"],
               check=True, timeout=30)
for iteration in range(2):
    model = WhisperModel(os.environ.get("WHISPER_MODEL", "large-v3"),
                         device="cuda", compute_type="float16", local_files_only=True)
    segments, _ = model.transcribe("/tmp/obtv-gpu-check.wav", vad_filter=True,
                                   condition_on_previous_text=False)
    count = sum(1 for _ in segments)
    del model
    gc.collect()
    print("Whisper load/inference/release:", iteration + 1, "segments:", count, flush=True)
print("PASS (bounded test, not a long-duration stability guarantee)", flush=True)