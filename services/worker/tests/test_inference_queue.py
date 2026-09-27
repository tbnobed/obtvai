"""Real Celery protocol/tracer tests; no live broker, database, models or GPU.

Run inside the worker image with python3. DB and model boundaries are fixtures,
but task execution, request IDs, replacement, chaining, and queue messages are
real Celery/Kombu. This catches errors hidden by mocked .delay() / .run().
"""
import importlib.util
import json
import os
from pathlib import Path
import sys
import types
import unittest
import uuid
from unittest.mock import Mock, patch

from celery import Celery, current_task
from celery.app.trace import build_tracer
from celery.exceptions import Ignore
from kombu import Queue

from tasks.inference_queue import RemoteInferenceTask, inference_queue
from tasks import llm_remote


class QueueTests(unittest.TestCase):
    def setUp(self):
        self.env = patch.dict(os.environ, {
            "REMOTE_LLM_QUEUE_ENABLED": "1", "LLM_BASE_URL": "http://llm.invalid/v1",
        })
        self.env.start()
        self.addCleanup(self.env.stop)
        self.remote_url = patch.object(llm_remote, "LLM_BASE_URL", "http://llm.invalid/v1")
        self.remote_url.start()
        self.addCleanup(self.remote_url.stop)
        self.app = Celery("queue-test-" + uuid.uuid4().hex,
                          broker="memory://", backend="cache+memory://",
                          set_as_current=False)
        self.app.conf.update(task_always_eager=False, task_track_started=True)
        self.addCleanup(self.app.close)
        self.db = Mock()
        self.db.execute.return_value.scalar.return_value = "pending"
        self.updates = Mock()
        self.modules = patch.dict(sys.modules, {
            "db": types.SimpleNamespace(get_session=lambda: self.db),
            "tasks.base": types.SimpleNamespace(
                update_job=self.updates, append_log=Mock(), create_job=Mock()),
        })
        self.modules.start()
        self.addCleanup(self.modules.stop)
        # All tests use the same named queues in memory transport; drain any
        # deliberate leftovers from a cancellation/routing test.
        with self.app.connection_for_write() as conn:
            for name in ("gpu", "llm", "cpu"):
                Queue(name, routing_key=name)(conn.default_channel).purge()

    def consume(self, queue):
        with self.app.connection_for_read() as conn:
            message = Queue(queue, routing_key=queue)(conn.default_channel).get(no_ack=True)
            self.assertIsNotNone(message, f"No message in {queue}")
            return message

    def trace(self, task, args, kwargs=None, queue="gpu", task_id="stage-request",
              retries=0, **request_options):
        task = task._get_current_object() if hasattr(task, "_get_current_object") else task
        tracer = build_tracer(task.name, task, app=self.app, eager=False)
        return tracer(task_id, args, kwargs or {}, request={
            "id": task_id, "task": task.name, "retries": retries,
            "delivery_info": {"routing_key": queue}, **request_options,
        })

    def run_message(self, message):
        args, kwargs, embed = message.payload
        return self.trace(self.app.tasks[message.headers["task"]], args, kwargs,
                          queue=message.delivery_info["routing_key"],
                          task_id=message.headers["id"],
                          retries=message.headers.get("retries", 0),
                          root_id=message.headers.get("root_id"),
                          parent_id=message.headers.get("parent_id"), **embed)

    def stage(self):
        @self.app.task(bind=True, base=RemoteInferenceTask, queue=inference_queue(),
                       name="fixture.stage." + uuid.uuid4().hex)
        def stage(task, media_id, job_id):
            task.update_state(state="PROGRESS", meta={"job_id": job_id})
            return {"request_id": task.request.id, "job_id": job_id}
        return stage

    def test_remote_and_local_modes_are_explicit(self):
        self.assertEqual(inference_queue(), "llm")
        with patch.dict(os.environ, {"REMOTE_LLM_QUEUE_ENABLED": "0"}):
            self.assertEqual(inference_queue(), "gpu")
        with patch.object(llm_remote, "LLM_BASE_URL", ""):
            self.assertEqual(inference_queue(), "gpu")

    def test_explicit_gpu_delivery_replaces_without_executing_body(self):
        stage = self.stage()
        result = self.trace(stage, ("media", "job"), retries=2)
        self.assertEqual(result.info.state, "IGNORED")
        self.updates.assert_called_once_with(self.db, "job", celery_task_id="stage-request")
        replacement = self.consume("llm")
        self.assertEqual(replacement.headers["id"], "stage-request")
        self.assertEqual(replacement.headers["retries"], 2)
        done = self.run_message(replacement)
        self.assertIsNone(done.info)
        self.assertEqual(done.retval, {"request_id": "stage-request", "job_id": "job"})
        self.assertEqual(self.app.AsyncResult("stage-request").state, "SUCCESS")

    def test_cancellation_between_hops_does_not_execute(self):
        stage = self.stage()
        self.trace(stage, ("media", "job"))
        replacement = self.consume("llm")
        self.db.execute.return_value.scalar.return_value = "cancelled"
        result = self.run_message(replacement)
        self.assertEqual(result.info.state, "IGNORED")
        self.assertNotEqual(self.app.AsyncResult("stage-request").state, "SUCCESS")

    def test_completed_redelivery_is_ignored(self):
        self.db.execute.return_value.scalar.return_value = "success"
        result = self.trace(self.stage(), ("media", "job"), queue="llm")
        self.assertEqual(result.info.state, "IGNORED")
        self.updates.assert_not_called()

    def test_disabled_remote_mode_returns_misrouted_work_to_gpu(self):
        stage = self.stage()
        with patch.object(llm_remote, "LLM_BASE_URL", ""):
            result = self.trace(stage, ("media", "job"), queue="llm")
            self.assertEqual(result.info.state, "IGNORED")
            done = self.run_message(self.consume("gpu"))
            self.assertIsNone(done.info)
            self.assertEqual(done.retval["request_id"], "stage-request")

    def test_eager_bound_identity_remains_valid(self):
        result = self.stage().apply(args=("media", "job"), task_id="eager-stage", throw=True)
        self.assertEqual(result.get()["request_id"], "eager-stage")

    def test_missing_job_fails_without_publishing(self):
        self.db.execute.return_value.scalar.return_value = None
        result = self.trace(self.stage(), ("media", "missing"))
        self.assertEqual(result.info.state, "FAILURE")
        self.assertIn("Inference job is missing", str(result.retval))

    def test_replacement_retains_chain_identity(self):
        stage = self.stage()
        followup = self.app.signature(stage.name, args=("next-media", "next-job"),
                                      immutable=True, queue="llm")
        self.trace(stage, ("media", "job"), chain=[dict(followup)], root_id="root-request")
        replacement = self.consume("llm")
        self.assertEqual(replacement.headers["root_id"], "root-request")
        self.run_message(replacement)
        child = self.consume("llm")
        self.assertEqual(child.payload[0], ["next-media", "next-job"])
        self.assertEqual(child.headers["root_id"], "root-request")

    def test_real_analysis_queues_and_executes_real_child_tasks(self):
        """Explicit-GPU API send -> handoff -> analysis -> async child stages."""
        root = Path(__file__).resolve().parents[1] / "tasks"
        loaded = {}
        for name in ("analyze", "creative", "sentiment"):
            spec = importlib.util.spec_from_file_location("tasks." + name, root / (name + ".py"))
            module = importlib.util.module_from_spec(spec)
            with patch.dict(sys.modules, {
                "app": types.SimpleNamespace(celery_app=self.app),
                "config": types.SimpleNamespace(LLM_MODEL="fixture-model"),
                **loaded,
            }):
                spec.loader.exec_module(module)
            loaded["tasks." + name] = module
        self.app.finalize()
        analysis = loaded["tasks.analyze"]
        writes = []

        def execute(sql, params=None):
            statement = str(sql)
            result = Mock()
            result.scalar.return_value = "pending"
            result.fetchone.return_value = None
            result.fetchall.return_value = []
            if "FROM transcript_segments" in statement and current_task.name == analysis.analyze_media.name:
                result.fetchall.return_value = [(0.0, "speaker", "Test transcript."), (10.0, "speaker", "The end.")]
            if "UPDATE media_assets" in statement:
                writes.append(params)
            return result

        self.db.execute.side_effect = execute
        sys.modules["tasks.base"].create_job.side_effect = lambda db, media, kind: "job-" + kind
        with patch.dict(sys.modules, loaded), \
                patch.object(analysis, "_load_llm", return_value=(None, None)), \
                patch.object(analysis, "_generate", side_effect=[
                    json.dumps({"summary": "Fixture summary", "key_moments": [], "topics": ["test"]}),
                    json.dumps({"synopsis": "Fixture synopsis", "topics": ["test"]}),
                ]) as generate:
            first = self.trace(analysis.analyze_media, ("media", "job-analysis"))
            self.assertEqual(first.info.state, "IGNORED")
            generate.assert_not_called()  # never entered model code on GPU hop
            done = self.run_message(self.consume("llm"))
            self.assertIsNone(done.info)
            self.assertEqual(writes[0]["synopsis"], "Fixture synopsis")
            self.assertEqual(generate.call_count, 2)
            children = [self.consume("llm"), self.consume("llm")]
            self.assertEqual({m.headers["task"] for m in children}, {
                "tasks.creative.creative_pass", "tasks.sentiment.sentiment_pass"})
            for child in children:
                outcome = self.run_message(child)
                self.assertIsNone(outcome.info)
                self.assertTrue(any(call.kwargs.get("celery_task_id") == child.headers["id"]
                                    for call in self.updates.call_args_list))
                self.assertEqual(self.app.AsyncResult(child.headers["id"]).state, "SUCCESS")


class WorkerGuardTests(unittest.TestCase):
    def setUp(self):
        # A failed assertion must never accidentally launch a real worker.
        self.app = Mock()
        app_patch = patch.dict(sys.modules, {"app": types.SimpleNamespace(celery_app=self.app)})
        app_patch.start()
        self.addCleanup(app_patch.stop)

    def test_remote_worker_refuses_local_fallback(self):
        from tasks.remote_inference_worker import main
        with patch.object(llm_remote, "LLM_BASE_URL", ""), \
                patch.dict(os.environ, {"REMOTE_LLM_QUEUE_ENABLED": "1"}):
            with self.assertRaisesRegex(RuntimeError, "requires"):
                main()
        self.app.worker_main.assert_not_called()

    def test_concurrency_is_bounded(self):
        from tasks.remote_inference_worker import main
        for value in ("0", "5", "100"):
            with patch.object(llm_remote, "LLM_BASE_URL", "http://llm.invalid/v1"), \
                    patch.dict(os.environ, {"LLM_BASE_URL": "http://llm.invalid/v1",
                                        "REMOTE_LLM_QUEUE_ENABLED": "1",
                                        "REMOTE_LLM_CONCURRENCY": value}):
                with self.assertRaisesRegex(ValueError, "between 1 and 4"):
                    main()
        self.app.worker_main.assert_not_called()


if __name__ == "__main__":
    unittest.main()