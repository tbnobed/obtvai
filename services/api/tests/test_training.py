import copy
import hashlib
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from app.training_service import prepare_dataset, validate_report

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "services" / "training"))
from common import load_dataset, adapter_hash


def examples():
    return [SimpleNamespace(id=str(i), status="approved", author="editor", reviewer="reviewer",
                            data={"instruction": f"Summarize approved source {i}",
                                  "context": hashlib.sha256(f"source{i}".encode()).hexdigest(),
                                  "answer": hashlib.sha256(f"answer{i}".encode()).hexdigest(),
                                  "source_ref": f"asset-{i // 2}", "group": f"episode-{i // 2}",
                                  "rights_approved": True, "required_terms": ["evidence"]})
            for i in range(10)]


def freeze(rows=None):
    return prepare_dataset(rows or examples(), model="example/base", revision="a" * 40,
                           license_note="Operator verified rights and base license.")


class TrainingTests(unittest.TestCase):
    def test_group_split_is_immutable_deterministic_and_disjoint(self):
        first = freeze()
        self.assertEqual(first, freeze(list(reversed(examples()))))
        self.assertEqual((len(first["train"]), len(first["heldout"])), (8, 2))
        self.assertFalse({r["group"] for r in first["train"]} & {r["group"] for r in first["heldout"]})

    def test_drafts_and_uncleared_never_export(self):
        rows = examples()
        rows[0].status = "draft"
        with self.assertRaises(ValueError): freeze(rows)
        rows[0].status = "approved"
        rows[0].data["rights_approved"] = False
        with self.assertRaises(ValueError): freeze(rows)

    def test_exact_duplicate_rejected(self):
        rows = examples()
        for key in ("instruction", "context", "answer"): rows[1].data[key] = rows[0].data[key]
        with self.assertRaisesRegex(ValueError, "Duplicate"): freeze(rows)

    def test_same_source_cannot_be_split_into_multiple_groups(self):
        rows = examples()
        rows[0].data["group"] = "another-group"
        with self.assertRaisesRegex(ValueError, "multiple split groups"): freeze(rows)

    def test_near_duplicate_rejected_across_splits(self):
        data = freeze()
        rows = examples()
        a, b = int(data["train"][0]["id"]), int(data["heldout"][0]["id"])
        rows[b].data["answer"] = rows[a].data["answer"] + "!"
        with self.assertRaisesRegex(ValueError, "Near-duplicate"): freeze(rows)

    def test_revision_must_be_frozen(self):
        with self.assertRaises(ValueError):
            prepare_dataset(examples(), model="example/base", revision="main", license_note="License verified")

    def test_report_requires_complete_actual_paired_outputs(self):
        data = freeze()
        report = {k: data[k] for k in ("dataset_hash", "base_model", "base_revision")}
        report["adapter_hash"] = "f" * 64
        report["results"] = [{"id": r["id"], "baseline": {"answer": "No keyword"}, "candidate": {"answer": "Evidence from the source"}}
                             for r in data["heldout"]]
        checked = validate_report(data, report)
        self.assertFalse(checked["results"][0]["baseline"]["required_terms_pass"])
        self.assertTrue(checked["results"][0]["candidate"]["required_terms_pass"])
        data["heldout"][0]["expected_format"] = "json"
        self.assertFalse(validate_report(data, report)["results"][0]["candidate"]["format_pass"])
        for mutation in ("missing", "empty", "wrong_dataset", "wrong_adapter"):
            bad = copy.deepcopy(report)
            if mutation == "missing": bad["results"].pop()
            if mutation == "empty": bad["results"][0]["candidate"]["answer"] = ""
            if mutation == "wrong_dataset": bad["dataset_hash"] = "0" * 64
            if mutation == "wrong_adapter": bad["adapter_hash"] = "unverified"
            with self.assertRaises(ValueError): validate_report(data, bad)

    def test_export_tamper_detected(self):
        import json
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "dataset.json"
            data = freeze()
            path.write_text(json.dumps(data))
            self.assertEqual(load_dataset(path)["dataset_hash"], data["dataset_hash"])
            data["train"][0]["answer"] = "changed"
            path.write_text(json.dumps(data))
            with self.assertRaisesRegex(ValueError, "checksum"): load_dataset(path)

    def test_adapter_requires_weights_and_hashes_bytes(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            with self.assertRaises(ValueError): adapter_hash(path)
            (path / "adapter_config.json").write_text("{}")
            (path / "adapter_model.safetensors").write_bytes(b"test-only")
            before = adapter_hash(path)
            (path / "adapter_model.safetensors").write_bytes(b"changed")
            self.assertNotEqual(before, adapter_hash(path))


if __name__ == "__main__":
    unittest.main()