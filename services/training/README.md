# Curated local LoRA pilot

This is a real, externally executed trainer, not a background production job.
It must run on a dedicated idle NVIDIA host. Nothing here changes inference
configuration, loads an adapter into production, or schedules work on ingest GPUs.
Start with ten or more human-authored, rights-cleared examples across at least five
independent episode/source groups in **Admin → Model Training**. Ten is a smoke-test
minimum, not evidence of training sufficiency. Hundreds of reviewed examples and a
representative held-out set are preferable before any production consideration.

## Prepare

Enter instruction, source context, desired answer, source reference, and a group
shared by all examples from the same asset/episode. Check rights clearance and
explicitly approve each example. Editing returns an example to draft. Freeze an
immutable dataset with the **original unquantized base model**, its exact 40-character
Hugging Face revision, and license/rights notes. Do not substitute an AWQ checkpoint
or assume the model configured in a default environment is the model being served.
Record and verify the actual serving checkpoint before selecting a training base.

Exports include private source text. Keep them on access-controlled local storage;
do not publish datasets or adapters without checking both media and base-model rights.
Deleting a curation example does not remove it from older exports. Retire those
exports/adapters separately when rights change.

## Train on a separate host

Python 3.11 and a compatible CUDA driver are required. Create an isolated venv,
install requirements.txt there (never in the API/worker image), then run:

```bash
python train.py training-DATASET.json --output ./adapter-v1 --gpu 0 --dedicated-host-confirmed
```

The selected GPU must have no compute processes. No processes are killed or evicted.
BF16 unquantized training is the initial supported path, not QLoRA; sufficient VRAM
for the exact base model is required. The shared production host and a Spark already
serving other models are not implicitly available training capacity. A remote
OpenAI inference endpoint is not a trainer.

Training uses only the train split, masks prompt tokens, preserves the model chat
template/assistant terminator, and rejects oversized examples rather than silently
truncating targets. Checkpoint, dataset, adapter bytes, seed, settings, and actual
loss history are recorded in training-manifest.json. Held-out examples are never
used for gradient updates. Do not repeatedly tune against the same held-out set.

## Evaluate and review

Serve the frozen unmodified base and candidate adapter on isolated, access-controlled
OpenAI-compatible test endpoints. This tool does not start servers or reconfigure
production. Verify endpoint base revision/tokenizer and candidate adapter checksum
against training-manifest.json; an OpenAI model name alone cannot prove weight identity.
Baseline must use the same base revision as training, not a larger production model.
Use BASELINE_API_KEY / CANDIDATE_API_KEY environment secrets if needed.

```bash
python evaluate.py training-DATASET.json --adapter ./adapter-v1 \
  --baseline-url http://BASELINE:8000/v1 --baseline-model BASE_MODEL \
  --candidate-url http://CANDIDATE:8000/v1 --candidate-model ADAPTER_MODEL \
  --output evaluation-v1.json
```

Only complete real paired inference outputs are accepted. Import the report on the
dataset card. The API validates immutable lineage, complete held-out coverage, and
recomputes required-term checks. Required-term presence is **not** a measure of
truthfulness: review every baseline/candidate answer for grounding, editorial style,
refusals, and citation correctness. Imported reports are operator-supplied evidence,
not cryptographically authenticated proof of endpoint weights or quality.

Record human approval/rejection with rationale. Approval means eligible for a
separate manual trial, **not** deployed or trained-on-production. Keep existing model
configuration and rollback available; never replace live inference just because
training loss decreases. There is intentionally no automatic promotion API.