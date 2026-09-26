"""Small stdlib-only helpers shared by external training and evaluation tools."""
import hashlib
import json
from pathlib import Path


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
                                     separators=(",", ":")).encode()).hexdigest()


def load_dataset(path):
    data = json.loads(Path(path).read_text())
    expected = data.pop("dataset_hash")
    if digest(data) != expected:
        raise ValueError("Dataset checksum mismatch; use the immutable downloaded export.")
    data["dataset_hash"] = expected
    if not data.get("train") or not data.get("heldout"):
        raise ValueError("Training and held-out splits are both required.")
    if {r["group"] for r in data["train"]} & {r["group"] for r in data["heldout"]}:
        raise ValueError("Group leakage across splits.")
    if any(not r.get("rights_approved") or not r.get("reviewer")
           for r in data["train"] + data["heldout"]):
        raise ValueError("Dataset contains unapproved or uncleared examples.")
    return data


def prompt(example):
    return example["instruction"] + ("\n\nSource context:\n" + example["context"] if example["context"] else "")


def adapter_hash(directory):
    """Hash both filenames and actual bytes, excluding the self-referencing manifest."""
    root = Path(directory)
    files = sorted(p for p in root.rglob("*") if p.is_file() and p.name != "training-manifest.json")
    if not (root / "adapter_config.json").is_file() or not (root / "adapter_model.safetensors").is_file():
        raise ValueError("PEFT adapter config and safetensors weights are required.")
    hasher = hashlib.sha256()
    for path in files:
        hasher.update(path.relative_to(root).as_posix().encode() + b"\0")
        with path.open("rb") as stream:
            for block in iter(lambda: stream.read(1024 * 1024), b""):
                hasher.update(block)
    return hasher.hexdigest()