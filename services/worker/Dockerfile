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
    g++ \
    libsndfile1 \
    sox \
    xz-utils \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# NVENC on Blackwell (RTX 5090) is driver-version sensitive in BOTH directions:
# - Old ffmpeg (apt 4.4) is built against an NVENC SDK too old for Blackwell.
# - R580+ drivers (CUDA 13) drop the older NVENC API generations, so ffmpeg 7.1
#   (SDK 12.x headers) ALSO fails with "OpenEncodeSessionEx failed: unsupported
#   device (2)". ffmpeg 8.x is built against NVENC SDK 13 headers and matches
#   R580-era drivers. Install the static 8.x build into /usr/local/bin so it
#   shadows the apt ffmpeg on PATH; the apt package stays for its shared libs
#   (torchaudio etc.).
ADD https://github.com/BtbN/FFmpeg-Builds/releases/download/latest/ffmpeg-n8.1-latest-linux64-gpl-8.1.tar.xz /tmp/ffmpeg.tar.xz
RUN tar -xf /tmp/ffmpeg.tar.xz -C /tmp \
    && cp /tmp/ffmpeg-n8.1-latest-linux64-gpl-8.1/bin/ffmpeg /usr/local/bin/ffmpeg \
    && cp /tmp/ffmpeg-n8.1-latest-linux64-gpl-8.1/bin/ffprobe /usr/local/bin/ffprobe \
    && chmod +x /usr/local/bin/ffmpeg /usr/local/bin/ffprobe \
    && rm -rf /tmp/ffmpeg.tar.xz /tmp/ffmpeg-n8.1-latest-linux64-gpl-8.1 \
    && /usr/local/bin/ffmpeg -hide_banner -encoders | grep -q h264_nvenc

RUN ln -s /usr/bin/python3.11 /usr/bin/python

WORKDIR /worker

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
RUN pip install --no-cache-dir requests

# chatterbox-tts pins older torch/transformers versions; install without deps
# (torch 2.7.1+cu128 and transformers already present) plus its light deps.
RUN pip install --no-cache-dir --no-deps chatterbox-tts==0.1.4 \
    && pip install --no-cache-dir librosa==0.11.0 s3tokenizer resemble-perth conformer==0.3.2 diffusers==0.29.0 pykakasi

COPY . .

ENV PYTHONPATH=/worker
ENV PYTHONUNBUFFERED=1

# Default: run GPU queue. Override CMD in docker-compose for CPU workers.
CMD ["celery", "-A", "app", "worker", "--queues=gpu,cpu,ingest", "--concurrency=1", "--loglevel=info"]
