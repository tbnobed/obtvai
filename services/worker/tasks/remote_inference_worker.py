"""CPU-only, bounded remote-inference worker; refuse implicit local fallback."""
import os


def main():
    from tasks.inference_queue import inference_queue
    if inference_queue() != "llm":
        raise RuntimeError("Remote inference worker requires REMOTE_LLM_QUEUE_ENABLED=1 and LLM_BASE_URL")
    concurrency = int(os.getenv("REMOTE_LLM_CONCURRENCY", "2"))
    if not 1 <= concurrency <= 4:
        raise ValueError("REMOTE_LLM_CONCURRENCY must be between 1 and 4")
    from app import celery_app
    celery_app.worker_main([
        "worker", "--queues=llm", f"--concurrency={concurrency}",
        "--pool=prefork", "--prefetch-multiplier=1", "--loglevel=info",
        "--hostname=worker-llm@%h",
    ])


if __name__ == "__main__":
    main()