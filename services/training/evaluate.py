"""Compare actual outputs from separate baseline/candidate OpenAI-compatible endpoints."""
import argparse
import json
import os
import urllib.request
from pathlib import Path
from common import load_dataset, prompt, adapter_hash


def generate(url, model, row, key):
    body = {"model": model, "messages": [{"role": "user", "content": prompt(row)}],
            "temperature": 0, "max_tokens": 1024, "chat_template_kwargs": {"enable_thinking": False}}
    headers = {"Content-Type": "application/json"}
    if key:
        headers["Authorization"] = "Bearer " + key
    request = urllib.request.Request(url.rstrip("/") + "/chat/completions",
                                     data=json.dumps(body).encode(), headers=headers)
    with urllib.request.urlopen(request, timeout=300) as response:
        result = json.load(response)
    choice = result["choices"][0]
    if choice.get("finish_reason") != "stop" or not choice["message"].get("content", "").strip():
        raise ValueError("Incomplete/truncated inference output; evaluation is not valid.")
    return {"answer": choice["message"]["content"], "served_model": result.get("model"),
            "finish_reason": choice["finish_reason"]}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("dataset")
    parser.add_argument("--adapter", required=True)
    parser.add_argument("--baseline-url", required=True, help="OpenAI-compatible base URL including /v1")
    parser.add_argument("--candidate-url", required=True)
    parser.add_argument("--baseline-model", required=True)
    parser.add_argument("--candidate-model", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    if args.baseline_url == args.candidate_url and args.baseline_model == args.candidate_model:
        parser.error("Baseline and candidate must be distinct deployments/model IDs.")
    if Path(args.output).exists():
        parser.error("Do not overwrite an existing evaluation.")
    data = load_dataset(args.dataset)
    adapter = json.loads((Path(args.adapter) / "training-manifest.json").read_text())
    for field in ("dataset_hash", "base_model", "base_revision"):
        if adapter[field] != data[field]:
            raise ValueError("Adapter provenance does not match this evaluation dataset.")
    if adapter_hash(args.adapter) != adapter["adapter_hash"]:
        raise ValueError("Adapter files changed after training.")
    rows = []
    for row in data["heldout"]:
        baseline = generate(args.baseline_url, args.baseline_model, row, os.getenv("BASELINE_API_KEY"))
        candidate = generate(args.candidate_url, args.candidate_model, row, os.getenv("CANDIDATE_API_KEY"))
        rows.append({"id": row["id"], "baseline": baseline, "candidate": candidate})
    report = {key: adapter[key] for key in ("dataset_hash", "base_model", "base_revision", "adapter_hash")}
    report.update({"schema_version": 1, "baseline_model": args.baseline_model,
                   "candidate_model": args.candidate_model, "results": rows,
                   "requires_human_review": True,
                   "deployment_attestation": "Operator must verify endpoint checkpoint/revision and loaded adapter."})
    Path(args.output).write_text(json.dumps(report, ensure_ascii=False, indent=2))
    print("Actual paired outputs saved; no automatic quality pass or production promotion.")


if __name__ == "__main__":
    main()