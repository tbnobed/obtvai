import importlib.util
import os
from pathlib import Path
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location(
    "gpu_routing", Path(__file__).parents[1] / "app" / "gpu_routing.py"
)
routing = importlib.util.module_from_spec(spec)
spec.loader.exec_module(routing)


class GpuRoutingTests(unittest.TestCase):
    def test_default_preserves_existing_routes(self):
        with patch.dict(os.environ, {}, clear=True):
            for task in routing.INTERACTIVE_TASKS:
                self.assertEqual(routing.publication_queue("gpu", task), "gpu")

    def test_only_interactive_tasks_move(self):
        with patch.dict(os.environ, {"INTERACTIVE_GPU_QUEUE": "gpu-interactive"}):
            for task in routing.INTERACTIVE_TASKS:
                self.assertEqual(routing.publication_queue("gpu", task), "gpu-interactive")
            for task in ("tasks.transcribe.transcribe_audio", "tasks.analyze.analyze_media"):
                self.assertEqual(routing.publication_queue("gpu", task), "gpu")
            self.assertEqual(routing.publication_queue("graphics", "tasks.graphics.generate"), "graphics")

    def test_empty_configuration_fails_explicitly(self):
        with patch.dict(os.environ, {"INTERACTIVE_GPU_QUEUE": " "}):
            with self.assertRaises(ValueError):
                routing.publication_queue("gpu", "tasks.dub.generate_dub")


if __name__ == "__main__":
    unittest.main()
