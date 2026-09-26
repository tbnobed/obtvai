"""Pure dataset preparation and fail-closed evaluation validation."""
import hashlib
import json
import re


def digest(value) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
                                     separators=(",", ":")).encode()).hexdigest()


def normalized(value: str) -> str:
    return " ".join(re.findall(r"\w+", value.casefold()))


def near_duplicate(left: str, right: str) -> bool:
    """Conservative character-bigram Dice similarity; cheap enough for pilot sets."""
    a = {left[i:i + 2] for i in range(len(left) - 1)}
    b = {right[i:i + 2] for i in range(len(right) - 1)}
    return bool(a and b) and 2 * len(a & b) / (len(a) + len(b)) >= .9


def prepare_dataset(examples, *, model: str, revision: str, license_note: str) -> dict:
    if not re.fullmatch(r"[0-9a-f]{40}", revision):
        raise ValueError("Base revision must be an immutable 40-character Hugging Face commit hash.")
    approved = [e for e in examples if e.status == "approved" and e.data.get("rights_approved")]
    if len(approved) < 10:
        raise ValueError("At least 10 explicitly approved, rights-cleared examples are required.")
    if len(approved) > 2000:
        raise ValueError("This curated pilot supports up to 2,000 examples. Narrow the dataset first.")
    records = []
    seen = set()
    for e in sorted(approved, key=lambda e: e.id):
        d = e.data
        content = {k: d[k] for k in ("instruction", "context", "answer")}
        fingerprint = digest({k: normalized(v) for k, v in content.items()})
        if fingerprint in seen:
            raise ValueError("Duplicate examples found; remove duplicate content before export.")
        seen.add(fingerprint)
        records.append({"id": e.id, **d, "author": e.author, "reviewer": e.reviewer,
                        "content_hash": fingerprint})
    # A single source can never straddle groups, even if its editor supplied
    # inconsistent series/episode labels.
    source_groups = {}
    for r in records:
        if r["source_ref"] in source_groups and source_groups[r["source_ref"]] != r["group"]:
            raise ValueError("One source reference is assigned to multiple split groups.")
        source_groups[r["source_ref"]] = r["group"]
    groups = sorted({r["group"] for r in records}, key=lambda g: digest(g))
    if len(groups) < 5:
        raise ValueError("At least five independent source/episode groups are required.")
    eval_groups = set(groups[:max(1, len(groups) // 5)])
    train = [r for r in records if r["group"] not in eval_groups]
    heldout = [r for r in records if r["group"] in eval_groups]
    if len(train) < 8 or len(heldout) < 2:
        raise ValueError("Split needs at least eight training and two held-out examples; add groups/examples.")
    for a in train:
        for b in heldout:
            # Near-identical contexts or desired answers leak evaluation labels.
            for key in ("context", "answer"):
                left, right = normalized(a[key]), normalized(b[key])
                if min(len(left), len(right)) >= 40 and near_duplicate(left, right):
                    raise ValueError("Near-duplicate context/answer crosses train and held-out groups.")
    body = {"schema_version": 1, "base_model": model, "base_revision": revision,
            "license_note": license_note, "train": train, "heldout": heldout,
            "training_policy": "Human-approved examples only; no automatic production promotion."}
    return {**body, "dataset_hash": digest(body)}


def validate_report(manifest, report):
    if report.get("dataset_hash") != manifest["dataset_hash"]:
        raise ValueError("Evaluation belongs to a different immutable dataset.")
    if report.get("base_model") != manifest["base_model"] or report.get("base_revision") != manifest["base_revision"]:
        raise ValueError("Evaluation base model/revision does not match the dataset.")
    if not re.fullmatch(r"[0-9a-f]{64}", str(report.get("adapter_hash", ""))):
        raise ValueError("A trained adapter SHA-256 checksum is required.")
    rows = report.get("results")
    expected = {r["id"]: r for r in manifest["heldout"]}
    if not isinstance(rows, list) or len(rows) != len(expected) or {r.get("id") for r in rows} != set(expected):
        raise ValueError("Evaluation must include every held-out example exactly once.")
    for row in rows:
        target = expected[row["id"]]
        for kind in ("baseline", "candidate"):
            result = row.get(kind, {})
            text = result.get("answer")
            if not isinstance(text, str) or not text.strip() or len(text) > 32000:
                raise ValueError("Every baseline/candidate answer must be present and bounded.")
            # Recompute rather than trusting submitted scores.
            result["required_terms_pass"] = all(normalized(term) in normalized(text)
                                                for term in target.get("required_terms", []))
            result["has_term_checks"] = bool(target.get("required_terms"))
            result["format_pass"] = True
            if target.get("expected_format") == "json":
                try:
                    json.loads(text)
                except ValueError:
                    result["format_pass"] = False
            result["expected_format"] = target.get("expected_format", "text")
        row["reference_answer"] = target["answer"]
    return report