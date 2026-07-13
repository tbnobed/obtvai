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
    xz-utils \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Blackwell GPUs (RTX 5090) reject NVENC sessions opened via the old NVENC SDK that
# Ubuntu 22.04's ffmpeg 4.4 was built against — h264_nvenc fails with "unsupported
# device" and encodes fall back to CPU libx264. ffmpeg >= 7.1 (built against modern
# nv-codec-headers) is required for NVENC on RTX 50-series. Install a static 7.1
# build into /usr/local/bin so it shadows the apt ffmpeg on PATH; the apt package
# stays for its shared libs (torchaudio etc.).
ADD https://github.com/BtbN/FFmpeg-Builds/releases/download/latest/ffmpeg-n7.1-latest-linux64-gpl-7.1.tar.xz /tmp/ffmpeg.tar.xz
RUN tar -xf /tmp/ffmpeg.tar.xz -C /tmp \
    && cp /tmp/ffmpeg-n7.1-latest-linux64-gpl-7.1/bin/ffmpeg /usr/local/bin/ffmpeg \
    && cp /tmp/ffmpeg-n7.1-latest-linux64-gpl-7.1/bin/ffprobe /usr/local/bin/ffprobe \
    && chmod +x /usr/local/bin/ffmpeg /usr/local/bin/ffprobe \
    && rm -rf /tmp/ffmpeg.tar.xz /tmp/ffmpeg-n7.1-latest-linux64-gpl-7.1 \
    && /usr/local/bin/ffmpeg -hide_banner -encoders | grep -q h264_nvenc

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
