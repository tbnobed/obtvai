# Layer the queue change onto each host's verified CUDA image, without changing
# Torch/CUDA packages or transferring the entire model/runtime image again.
ARG WORKER_BASE=obtv-ai-worker-gpu
FROM ${WORKER_BASE}
COPY tasks/inference_queue.py tasks/remote_inference_worker.py tasks/analyze.py tasks/creative.py tasks/identify.py tasks/sentiment.py /worker/tasks/