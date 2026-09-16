FROM python:3.11-slim

WORKDIR /watcher

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY watcher.py .
COPY healthcheck.py .

ENV PYTHONUNBUFFERED=1

HEALTHCHECK --interval=30s --timeout=5s --start-period=120s --retries=3 \
    CMD ["python", "healthcheck.py"]

CMD ["python", "watcher.py"]
