"""Read-only CUDA face/JIT reproducer; run in an isolated worker-image container.

Expose one GPU, bind cached buffalo_l models read-only, set CUDA_CACHE_DISABLE=1
and select CPU affinity externally. No network, broker, or database is needed.
Synthetic inputs test runtime stability, not face-recognition accuracy.
"""
import argparse
import os
from pathlib import Path
import time


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--models", default="/root/.insightface/models/buffalo_l")
    parser.add_argument("--cycles", type=int, default=3)
    args = parser.parse_args()
    if not 1 <= args.cycles <= 100:
        parser.error("--cycles must be between 1 and 100")

    paths = [(Path(args.models) / (name + ".onnx"), size)
             for name, size in (("det_10g", 640), ("w600k_r50", 112))]
    for path, _ in paths:
        if not path.is_file():
            raise FileNotFoundError(f"Cached model required: {path.name}")

    import numpy as np
    import torch
    import onnxruntime as ort

    if torch.cuda.device_count() != 1:
        raise RuntimeError("Expose exactly one GPU")
    print("GPU:", torch.cuda.get_device_name(), flush=True)
    print("CPUs:", sorted(os.sched_getaffinity(0)), flush=True)
    print("Torch:", torch.__version__, "ORT:", ort.__version__, flush=True)
    ort.preload_dlls()
    options = ort.SessionOptions()
    options.intra_op_num_threads = 1
    options.inter_op_num_threads = 1
    for path, size in paths:
        started = time.monotonic()
        session = ort.InferenceSession(
            str(path), sess_options=options,
            providers=["CUDAExecutionProvider"],
        )
        if "CUDAExecutionProvider" not in session.get_providers():
            raise RuntimeError("CUDA provider unavailable; refusing CPU fallback")
        inputs = {session.get_inputs()[0].name:
                  np.ones((1, 3, size, size), dtype=np.float32)}
        for _ in range(args.cycles):
            outputs = session.run(None, inputs)
            if not all(np.isfinite(output).all() for output in outputs):
                raise RuntimeError(f"Nonfinite output: {path.name}")
        print(path.name, "PASS", args.cycles, "cycles",
              round(time.monotonic() - started, 2), "seconds", flush=True)
        del session


if __name__ == "__main__":
    main()