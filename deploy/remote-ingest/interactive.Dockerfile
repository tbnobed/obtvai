# Preserve the production CUDA/Torch/FFmpeg stack.
FROM obtv-efficiency-worker:verified
RUN python3 -m pip install --no-cache-dir --no-deps pyloudnorm==0.1.1 \
    && python3 -c "from chatterbox.tts_turbo import ChatterboxTurboTTS"
