FROM debian:bookworm-slim
RUN apt-get update && apt-get install -y --no-install-recommends openssh-sftp-server python3 ca-certificates && rm -rf /var/lib/apt/lists/*
COPY gateway.py /gateway.py
CMD ["python3", "-u", "/gateway.py"]