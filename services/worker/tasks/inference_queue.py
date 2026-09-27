"""Opt-in remote-only inference lane, including explicitly GPU-routed callers.

No task bodies, arguments, job IDs or analysis output are changed. Celery
replacement transfers the *same* request identity instead of blocking a GPU
child on AsyncResult.get(). Existing local inference stays on the GPU queue.
"""
import os

from celery import Task
from celery.exceptions import Ignore


def inference_queue():
    from tasks.llm_remote import remote_enabled
    enabled = os.getenv("REMOTE_LLM_QUEUE_ENABLED", "0").strip().lower()
    return "llm" if enabled in ("1", "true", "yes") and remote_enabled() else "gpu"


class RemoteInferenceTask(Task):
    abstract = True

    def before_start(self, task_id, args, kwargs):
        # .apply() is an intentional synchronous operation with a real bound
        # request context, not a transport hop. No production ingestion caller
        # executes these text-only tasks eagerly (Image's GPU subtasks are not
        # members of this class). Keep eager tests/local invocations intact.
        if self.request.is_eager:
            return

        job_id = kwargs.get("job_id") or (args[1] if len(args) > 1 else None)
        if job_id:
            from sqlalchemy import text
            from db import get_session
            from tasks.base import update_job
            db = get_session()
            try:
                status = db.execute(text(
                    "SELECT status FROM processing_jobs WHERE id=:id"
                ), {"id": job_id}).scalar()
                if status is None:
                    raise RuntimeError("Inference job is missing")
                if status in ("cancelled", "success"):
                    raise Ignore()
                # Persist identity BEFORE publishing a replacement so a pending
                # handoff can be cancelled too. Never mark running/success here.
                update_job(db, job_id, celery_task_id=task_id)
            finally:
                db.close()

        target = inference_queue()
        incoming = (self.request.delivery_info or {}).get("routing_key")
        if incoming != target:
            replacement = self.signature(args=args, kwargs=kwargs).set(
                queue=target, retries=self.request.retries,
            )
            # Celery carries chain/callback/chord/root identity through replace;
            # raising Ignore leaves completion to the replacement, not this hop.
            return self.replace(replacement)
