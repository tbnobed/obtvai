"""Run explicitly on an idle dedicated NVIDIA training host, never an ingest worker."""
import argparse
import json
import os
import subprocess
from pathlib import Path
from common import load_dataset, prompt, adapter_hash


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("dataset")
    parser.add_argument("--output", required=True)
    parser.add_argument("--gpu", type=int, default=0)
    parser.add_argument("--dedicated-host-confirmed", action="store_true")
    parser.add_argument("--epochs", type=int, default=2, choices=range(1, 6))
    parser.add_argument("--max-length", type=int, default=2048, choices=(1024, 2048, 4096))
    args = parser.parse_args()
    if not args.dedicated_host_confirmed:
        parser.error("A dedicated idle training host must be confirmed; production GPUs are not permitted.")
    data = load_dataset(args.dataset)
    output = Path(args.output)
    if output.exists():
        parser.error("Output must be a new directory; existing adapters are immutable.")
    # Before importing torch or allocating CUDA, refuse a device with any
    # compute process. No attempt to evict inference, ComfyUI or ingest jobs.
    processes = subprocess.check_output([
        "nvidia-smi", "-i", str(args.gpu), "--query-compute-apps=pid",
        "--format=csv,noheader"], text=True).strip()
    if processes:
        raise RuntimeError("Selected GPU has active compute processes. Do not stop production to make room.")
    os.environ["CUDA_VISIBLE_DEVICES"] = str(args.gpu)
    import torch
    from transformers import AutoModelForCausalLM, AutoTokenizer, Trainer, TrainingArguments, set_seed
    from peft import LoraConfig, get_peft_model
    if not torch.cuda.is_available() or not torch.cuda.is_bf16_supported():
        raise RuntimeError("This trainer requires a dedicated CUDA GPU with BF16 support.")
    set_seed(42)
    tokenizer = AutoTokenizer.from_pretrained(data["base_model"], revision=data["base_revision"],
                                            trust_remote_code=False)
    tokenizer.pad_token = tokenizer.eos_token
    samples = []
    for row in data["train"]:  # heldout is never passed to Trainer
        messages = [{"role": "user", "content": prompt(row)}]
        prefix = tokenizer.apply_chat_template(messages, tokenize=True, add_generation_prompt=True,
                                               enable_thinking=False)
        tokens = tokenizer.apply_chat_template(messages + [{"role": "assistant", "content": row["answer"]}],
                                               tokenize=True, add_generation_prompt=False, enable_thinking=False)
        if tokens[:len(prefix)] != prefix:
            raise ValueError("Chat template prefix mismatch; cannot safely mask assistant-only loss.")
        if len(tokens) > args.max_length:
            raise ValueError(f"Example {row['id']} exceeds max length; revise it instead of truncating its answer.")
        if len(tokens) <= len(prefix):
            raise ValueError("Assistant target is empty.")
        samples.append({"input_ids": tokens, "attention_mask": [1] * len(tokens),
                        "labels": [-100] * len(prefix) + tokens[len(prefix):]})
    model = AutoModelForCausalLM.from_pretrained(
        data["base_model"], revision=data["base_revision"], torch_dtype=torch.bfloat16,
        trust_remote_code=False, attn_implementation="sdpa")
    if getattr(model.config, "quantization_config", None):
        raise ValueError("Use the unquantized original checkpoint, not an AWQ inference checkpoint.")
    model.config.use_cache = False
    model = get_peft_model(model, LoraConfig(
        task_type="CAUSAL_LM", r=16, lora_alpha=32, lora_dropout=.05,
        target_modules=["q_proj", "k_proj", "v_proj", "o_proj"], bias="none"))

    def collate(rows):
        length = max(len(r["input_ids"]) for r in rows)
        return {key: torch.tensor([r[key] + [padding] * (length - len(r[key])) for r in rows])
                for key, padding in (("input_ids", tokenizer.pad_token_id),
                                     ("attention_mask", 0), ("labels", -100))}

    trainer = Trainer(model=model, train_dataset=samples, data_collator=collate,
                      args=TrainingArguments(
                          output_dir=str(output), num_train_epochs=args.epochs,
                          per_device_train_batch_size=1, gradient_accumulation_steps=8,
                          gradient_checkpointing=True,
                          gradient_checkpointing_kwargs={"use_reentrant": False},
                          learning_rate=2e-4, bf16=True, seed=42, data_seed=42,
                          logging_steps=1, save_strategy="no", report_to="none"))
    trainer.train()
    model.save_pretrained(output, safe_serialization=True)
    tokenizer.save_pretrained(output)
    manifest = {"dataset_hash": data["dataset_hash"], "base_model": data["base_model"],
                "base_revision": data["base_revision"], "adapter_hash": adapter_hash(output),
                "train_ids": [r["id"] for r in data["train"]], "seed": 42,
                "epochs": args.epochs, "max_length": args.max_length,
                "torch_version": torch.__version__, "license_note": data["license_note"],
                "training_loss": trainer.state.log_history,
                "production_promoted": False}
    (output / "training-manifest.json").write_text(json.dumps(manifest, indent=2))
    print("Adapter saved. Evaluation and human review are required; production is unchanged.")


if __name__ == "__main__":
    main()