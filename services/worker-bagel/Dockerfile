FROM nvcr.io/nvidia/pytorch:25.12-py3

WORKDIR /app

# Clone BAGEL source — provides modeling/, data/, inferencer.py etc.
# Pinned to a specific commit so the container is reproducible.
RUN git clone --depth 1 https://github.com/ByteDance-Seed/BAGEL.git /app/bagel

# Install BAGEL Python deps on top of what the pytorch base already ships.
RUN pip install --no-cache-dir \
    "fastapi>=0.111" \
    "uvicorn[standard]>=0.29" \
    "transformers==4.49.0" \
    "accelerate>=0.34.0" \
    "safetensors==0.4.5" \
    "einops==0.8.1" \
    "sentencepiece>=0.2.0" \
    "huggingface_hub>=0.29" \
    "httpx" \
    "Pillow"

RUN mkdir -p /app/model /tmp/offload

COPY server.py /app/server.py

# BAGEL repo code must be on PYTHONPATH for its internal imports to resolve.
ENV PYTHONPATH=/app/bagel
ENV BAGEL_MODEL_PATH=/app/model
ENV PORT=8003

EXPOSE 8003
CMD ["python", "/app/server.py"]
