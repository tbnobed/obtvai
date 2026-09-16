import json
import tempfile
import unittest
from pathlib import Path

from healthcheck import check


class HealthCheckTests(unittest.TestCase):
    def test_heartbeat(self):
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / "health.json"
            self.assertFalse(check(str(path), now=200))
            for state, expected in [
                ({"updated_at": 190, "healthy": True}, True),
                ({"updated_at": 190, "healthy": False}, False),
                ({"updated_at": 1, "healthy": True}, False),
                ({"updated_at": 210, "healthy": True}, False),
                ({"updated_at": "nan", "healthy": True}, False),
                ({}, False),
                ([], False),
            ]:
                path.write_text(json.dumps(state))
                self.assertEqual(check(str(path), now=200), expected)
            path.write_text("partial")
            self.assertFalse(check(str(path), now=200))


if __name__ == "__main__":
    unittest.main()