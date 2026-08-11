# CUDA 12.8+ required for Blackwell GPUs (RTX 5090, RTX PRO 6000)
FROM nvidia/cuda:12.8.1-cudnn-runtime-ubuntu22.04

ENV DEBIAN_FRONTEND=noninteractive
RUN apt-get update && apt-get install -y --no-install-recommends \
    python3.11 \
    python3.11-dev \
    python3-dev \
    python3-pip \
    ffmpeg \
    libpq-dev \
    gcc \
    g++ \
    libsndfile1 \
    sox \
    xz-utils \
    ca-certificates \
    git \
    python3.10-venv \
    libgl1 \
    libglib2.0-0 \
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
    && pip install --no-cache-dir librosa==0.11.0 s3tokenizer resemble-perth conformer==0.3.2 diffusers==0.29.0 pykakasi \
    # s3tokenizer drags in the plain CPU `onnxruntime` wheel, which shadows
    # onnxruntime-gpu and silently drops InsightFace face detection (face
    # clustering AND the lip-sync face pass) to CPU. Strip it and force the
    # GPU wheel back so CUDAExecutionProvider survives.
    && pip uninstall -y onnxruntime || true

RUN pip install --no-cache-dir --force-reinstall --no-deps onnxruntime-gpu==1.22.0 \
    # verify with the interpreter pip installs into (python3 = 3.10; the bare
    # `python` symlink is 3.11 and has no site-packages from pip)
    && python3 -c "import onnxruntime as ort; assert 'CUDAExecutionProvider' in ort.get_available_providers(), ort.get_available_providers()"

# --- LatentSync (local lipsync engine) ---------------------------------------
# Isolated in its own venv: LatentSync pins torch 2.5.1 (no Blackwell/sm_120
# support) and diffusers/transformers versions that clash with the chatterbox
# stack. The venv gets the same torch 2.8.0+cu128 pin as the main env plus
# LatentSync's own deps; inference runs as a subprocess so VRAM is freed when
# each job exits. Checkpoints download at first use into the models_cache
# volume (see tasks/voice.py lipsync_video).
RUN git clone --depth 1 https://github.com/bytedance/LatentSync /opt/latentsync
# python3.10 explicitly: it's the interpreter the worker itself runs on
# (python3-pip's python3) and matches the installed python3.10-venv package.
RUN python3.10 -m venv /opt/latentsync-venv \
    && /opt/latentsync-venv/bin/pip install --no-cache-dir --upgrade pip \
    && /opt/latentsync-venv/bin/pip install --no-cache-dir \
        torch==2.8.0 torchvision==0.23.0 --index-url https://download.pytorch.org/whl/cu128 \
    && /opt/latentsync-venv/bin/pip install --no-cache-dir \
        diffusers==0.32.2 transformers==4.48.0 decord==0.6.0 accelerate==0.26.1 \
        einops==0.7.0 omegaconf==2.3.0 opencv-python==4.9.0.80 mediapipe==0.10.11 \
        python_speech_features==0.6 librosa==0.10.1 scenedetect==0.6.1 \
        ffmpeg-python==0.2.0 imageio==2.31.1 imageio-ffmpeg==0.5.1 lpips==0.1.4 \
        face-alignment==1.4.1 huggingface-hub==0.30.2 numpy==1.26.4 kornia==0.8.0 \
        insightface==0.7.3 onnxruntime-gpu==1.21.0 DeepCache==0.1.1

COPY . .

ENV PYTHONPATH=/worker
ENV PYTHONUNBUFFERED=1

# Default: run GPU queue. Override CMD in docker-compose for CPU workers.
CMD ["celery", "-A", "app", "worker", "--queues=gpu,cpu,ingest", "--concurrency=1", "--loglevel=info"]
