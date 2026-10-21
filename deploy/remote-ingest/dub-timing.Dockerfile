# Build from repository root; preserve the qualified CUDA/Torch/model stack.
FROM obtv-interactive-worker:verified
COPY services/worker/tasks/dub.py /worker/tasks/dub.py
RUN python3 -m py_compile /worker/tasks/dub.py
