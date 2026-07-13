# CUDA 12.8+ required for Blackwell GPUs (RTX 5090, RTX PRO 6000)
FROM nvidia/cuda:12.8.1-cudnn-runtime-ubuntu22.04

ENV DEBIAN_FRONTEND=noninteractive
RUN apt-get update && apt-get install -y --no-install-recommends \
    python3.11 \
    python3.11-dev \
    python3-pip \
    ffmpeg \
    libpq-dev \
    gcc \
    libsndfile1 \
    sox \
    && rm -rf /var/lib/apt/lists/*

RUN ln -s /usr/bin/python3.11 /usr/bin/python

WORKDIR /worker

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
# facenet-pytorch pins an old torch; install without deps (torch/torchvision already present)
RUN pip install --no-cache-dir --no-deps facenet-pytorch==2.6.0 && pip install --no-cache-dir requests

COPY . .

ENV PYTHONPATH=/worker
ENV PYTHONUNBUFFERED=1

# Default: run GPU queue. Override CMD in docker-compose for CPU workers.
CMD ["celery", "-A", "app", "worker", "--queues=gpu,cpu,ingest", "--concurrency=1", "--loglevel=info"]
