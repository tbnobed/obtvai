"""ComfyUI graphics generation: builtin workflow templates, custom-workflow
capability detection, and parameter injection.

KEEP IN SYNC: this file exists twice because the API and worker have separate
Docker build contexts:
  services/api/app/comfy_graphics.py
  services/worker/comfy_graphics.py
Pure data + functions only — no HTTP, no DB, no config imports.

Workflow graphs use the ComfyUI **API format** (the JSON you get from
"Export (API format)" in the ComfyUI UI): {node_id: {class_type, inputs, _meta}}.

Injection conventions (also honored for user-dropped custom workflows):
  - CLIPTextEncode node titled "prompt"   -> positive prompt text
  - CLIPTextEncode node titled "negative" -> negative prompt text
  - any "seed" / "noise_seed" input       -> seed
  - node with both "width"+"height"       -> output size (latent nodes)
  - "length" / "frames" / "num_frames"    -> video frame count
  - "steps" input                         -> sampler steps
"""
from __future__ import annotations

import copy
import math
import os
import re

MODEL_FILE_EXTS = (".safetensors", ".gguf", ".ckpt", ".pt", ".sft", ".pth", ".onnx")


# ---------------------------------------------------------------------------
# Builtin workflow graphs


def _flux_graph(unet_name: str, steps: int, guidance: float | None) -> dict:
    graph = {
        "1": {"class_type": "UNETLoader",
              "inputs": {"unet_name": unet_name, "weight_dtype": "default"}},
        "2": {"class_type": "DualCLIPLoader",
              "inputs": {"clip_name1": "t5xxl_fp8_e4m3fn.safetensors",
                         "clip_name2": "clip_l.safetensors", "type": "flux"}},
        "3": {"class_type": "VAELoader", "inputs": {"vae_name": "ae.safetensors"}},
        "4": {"class_type": "CLIPTextEncode", "_meta": {"title": "prompt"},
              "inputs": {"text": "", "clip": ["2", 0]}},
        "5": {"class_type": "CLIPTextEncode", "_meta": {"title": "negative"},
              "inputs": {"text": "", "clip": ["2", 0]}},
        "6": {"class_type": "EmptySD3LatentImage",
              "inputs": {"width": 1024, "height": 1024, "batch_size": 1}},
        "8": {"class_type": "KSampler",
              "inputs": {"model": ["1", 0], "positive": ["4", 0], "negative": ["5", 0],
                         "latent_image": ["6", 0], "seed": 0, "steps": steps, "cfg": 1.0,
                         "sampler_name": "euler", "scheduler": "simple", "denoise": 1.0}},
        "9": {"class_type": "VAEDecode", "inputs": {"samples": ["8", 0], "vae": ["3", 0]}},
        "10": {"class_type": "SaveImage",
               "inputs": {"images": ["9", 0], "filename_prefix": "obtv_gfx"}},
    }
    if guidance is not None:
        graph["7"] = {"class_type": "FluxGuidance",
                      "inputs": {"conditioning": ["4", 0], "guidance": guidance}}
        graph["8"]["inputs"]["positive"] = ["7", 0]
    return graph


def _wan22_t2v_graph() -> dict:
    # Two-stage Wan2.2 A14B (high-noise then low-noise expert), GGUF Q8_0 via
    # the ComfyUI-GGUF custom node pack. Outputs a PNG frame sequence that the
    # worker assembles into an MP4 (avoids depending on any video-save node).
    return {
        "1": {"class_type": "UnetLoaderGGUF",
              "inputs": {"unet_name": "Wan2.2-T2V-A14B-HighNoise-Q8_0.gguf"}},
        "2": {"class_type": "UnetLoaderGGUF",
              "inputs": {"unet_name": "Wan2.2-T2V-A14B-LowNoise-Q8_0.gguf"}},
        "3": {"class_type": "CLIPLoader",
              "inputs": {"clip_name": "umt5-xxl-enc-bf16.safetensors", "type": "wan"}},
        "4": {"class_type": "VAELoader", "inputs": {"vae_name": "wan_2.1_vae.safetensors"}},
        "5": {"class_type": "CLIPTextEncode", "_meta": {"title": "prompt"},
              "inputs": {"text": "", "clip": ["3", 0]}},
        "6": {"class_type": "CLIPTextEncode", "_meta": {"title": "negative"},
              "inputs": {"text": "", "clip": ["3", 0]}},
        "7": {"class_type": "EmptyHunyuanLatentVideo",
              "inputs": {"width": 1280, "height": 720, "length": 81, "batch_size": 1}},
        "8": {"class_type": "ModelSamplingSD3", "inputs": {"model": ["1", 0], "shift": 8.0}},
        "9": {"class_type": "ModelSamplingSD3", "inputs": {"model": ["2", 0], "shift": 8.0}},
        "10": {"class_type": "KSamplerAdvanced",
               "inputs": {"model": ["8", 0], "add_noise": "enable", "noise_seed": 0,
                          "steps": 20, "cfg": 3.5, "sampler_name": "euler",
                          "scheduler": "simple", "positive": ["5", 0], "negative": ["6", 0],
                          "latent_image": ["7", 0], "start_at_step": 0, "end_at_step": 10,
                          "return_with_leftover_noise": "enable"}},
        "11": {"class_type": "KSamplerAdvanced",
               "inputs": {"model": ["9", 0], "add_noise": "disable", "noise_seed": 0,
                          "steps": 20, "cfg": 3.5, "sampler_name": "euler",
                          "scheduler": "simple", "positive": ["5", 0], "negative": ["6", 0],
                          "latent_image": ["10", 0], "start_at_step": 10, "end_at_step": 10000,
                          "return_with_leftover_noise": "disable"}},
        "12": {"class_type": "VAEDecode", "inputs": {"samples": ["11", 0], "vae": ["4", 0]}},
        "13": {"class_type": "SaveImage",
               "inputs": {"images": ["12", 0], "filename_prefix": "obtv_gfx"}},
    }


def _wan22_steps(graph: dict, steps: int) -> None:
    """Wan two-stage: split the step budget at the noise boundary."""
    half = max(1, math.ceil(steps / 2))
    graph["10"]["inputs"]["steps"] = steps
    graph["11"]["inputs"]["steps"] = steps
    graph["10"]["inputs"]["end_at_step"] = half
    graph["11"]["inputs"]["start_at_step"] = half


BUILTIN_PRESETS: list[dict] = [
    {
        "id": "flux-schnell",
        "name": "FLUX Schnell — Fast Image",
        "description": "4-step image generation, seconds per image. Great for drafts and iteration.",
        "kind": "image",
        "supports_negative": False,  # schnell ignores negatives (cfg 1.0)
        "supports_size": True,
        "supports_steps": False,
        "supports_frames": False,
        "supports_seed": True,
        "default_width": 1024, "default_height": 1024,
        "default_steps": 4, "default_frames": None,
        "fps": None,
        "graph": _flux_graph("flux1-schnell.safetensors", 4, None),
    },
    {
        "id": "flux-dev",
        "name": "FLUX Dev — Quality Image",
        "description": "Full-quality FLUX.1-dev image generation. Slower, best detail.",
        "kind": "image",
        "supports_negative": False,
        "supports_size": True,
        "supports_steps": True,
        "supports_frames": False,
        "supports_seed": True,
        "default_width": 1024, "default_height": 1024,
        "default_steps": 20, "default_frames": None,
        "fps": None,
        "graph": _flux_graph("flux1-dev.safetensors", 20, 3.5),
    },
    {
        "id": "wan22-t2v",
        "name": "Wan 2.2 — Text to Video",
        "description": "Wan2.2 A14B text-to-video at 16 fps. High quality, minutes per clip.",
        "kind": "video",
        "supports_negative": True,
        "supports_size": True,
        "supports_steps": True,
        "supports_frames": True,
        "supports_seed": True,
        "default_width": 1280, "default_height": 720,
        "default_steps": 20, "default_frames": 81,
        "fps": 16,
        "graph": _wan22_t2v_graph(),
        "steps_hook": _wan22_steps,
    },
]


def builtin_preset(preset_id: str) -> dict | None:
    for p in BUILTIN_PRESETS:
        if p["id"] == preset_id:
            return p
    return None


# ---------------------------------------------------------------------------
# Custom workflow detection

CUSTOM_PRESET_PREFIX = "custom:"


def _text_encode_roles(graph: dict) -> tuple[str | None, str | None]:
    """Return (prompt_node_id, negative_node_id) for a graph."""
    encodes = {nid: n for nid, n in graph.items()
               if isinstance(n, dict) and n.get("class_type") == "CLIPTextEncode"}
    prompt_id = negative_id = None
    for nid, n in encodes.items():
        title = str(((n.get("_meta") or {}).get("title") or "")).lower()
        if "negative" in title and negative_id is None:
            negative_id = nid
        elif ("prompt" in title or "positive" in title) and prompt_id is None:
            prompt_id = nid
    if prompt_id is None:
        # Fall back to link tracing: an encode feeding any "negative" input is
        # the negative; the first remaining encode is the prompt.
        neg_targets = set()
        for n in graph.values():
            if not isinstance(n, dict):
                continue
            ref = (n.get("inputs") or {}).get("negative")
            if isinstance(ref, list) and ref:
                neg_targets.add(str(ref[0]))
        for nid in encodes:
            if nid in neg_targets:
                if negative_id is None:
                    negative_id = nid
            elif prompt_id is None:
                prompt_id = nid
    return prompt_id, negative_id


def detect_capabilities(graph: dict) -> dict:
    """Inspect an API-format workflow and report what we can inject."""
    prompt_id, negative_id = _text_encode_roles(graph)
    caps = {
        "prompt_node": prompt_id,
        "negative_node": negative_id,
        "supports_negative": negative_id is not None,
        "supports_size": False,
        "supports_steps": False,
        "supports_frames": False,
        "supports_seed": False,
        "default_width": None, "default_height": None,
        "default_steps": None, "default_frames": None,
        "kind": "image",
    }
    for n in graph.values():
        if not isinstance(n, dict):
            continue
        ins = n.get("inputs") or {}
        if isinstance(ins.get("width"), (int, float)) and isinstance(ins.get("height"), (int, float)):
            caps["supports_size"] = True
            caps["default_width"] = int(ins["width"])
            caps["default_height"] = int(ins["height"])
        if isinstance(ins.get("steps"), (int, float)):
            caps["supports_steps"] = True
            caps["default_steps"] = int(ins["steps"])
        for key in ("length", "frames", "num_frames"):
            if isinstance(ins.get(key), (int, float)) and ins[key] > 1:
                caps["supports_frames"] = True
                caps["default_frames"] = int(ins[key])
                caps["kind"] = "video"
        for key in ("seed", "noise_seed"):
            if isinstance(ins.get(key), (int, float)):
                caps["supports_seed"] = True
        if "video" in str(n.get("class_type", "")).lower():
            caps["kind"] = "video"
    return caps


# ---------------------------------------------------------------------------
# Parameter injection


def inject_params(
    graph: dict,
    *,
    prompt: str,
    negative: str | None = None,
    width: int | None = None,
    height: int | None = None,
    steps: int | None = None,
    frames: int | None = None,
    seed: int | None = None,
    steps_hook=None,
) -> dict:
    """Return a deep-copied graph with user parameters written in."""
    g = copy.deepcopy(graph)
    prompt_id, negative_id = _text_encode_roles(g)
    if prompt_id:
        g[prompt_id]["inputs"]["text"] = prompt
    if negative_id and negative is not None:
        g[negative_id]["inputs"]["text"] = negative
    for n in g.values():
        if not isinstance(n, dict):
            continue
        ins = n.get("inputs") or {}
        if width and height and isinstance(ins.get("width"), (int, float)) \
                and isinstance(ins.get("height"), (int, float)):
            ins["width"] = width
            ins["height"] = height
        if frames:
            for key in ("length", "frames", "num_frames"):
                if isinstance(ins.get(key), (int, float)) and ins[key] > 1:
                    ins[key] = frames
        if seed is not None:
            for key in ("seed", "noise_seed"):
                if isinstance(ins.get(key), (int, float)):
                    ins[key] = seed
        if steps and steps_hook is None and isinstance(ins.get("steps"), (int, float)):
            ins["steps"] = steps
    if steps and steps_hook is not None:
        steps_hook(g, steps)
    return g


# ---------------------------------------------------------------------------
# Model-file resolution: installs name the same model differently
# (t5xxl_fp8_e4m3fn vs t5xxl_fp16, Wan2.2-...-HighNoise-Q8_0 vs
# wan2.2_..._high_noise_Q5_K_M). When the exact filename a preset references
# isn't present, substitute the equivalent file this ComfyUI actually has.

# Precision / quantization / packaging suffixes that don't change WHICH model
# a file is — ignored when comparing names.
_NOISE_TOKEN_RE = re.compile(
    r"^(fp8|fp16|bf16|fp32|e4m3fn|e5m2|e4m3|scaled|enc|encoder|gguf|q\d\w*|k|s|m|v\d+)$"
)


def _name_tokens(s: str) -> list[str]:
    """Lowercased tokens with version digits merged into the preceding token,
    so 'wan_2.1_vae' -> ['wan21', 'vae'] and 'Q8_0' -> ['q80']. Keeping the
    version glued to its family token stops 2.1 files matching 2.2 files."""
    stem = os.path.splitext(os.path.basename(str(s)))[0].lower()
    merged: list[str] = []
    for t in re.split(r"[^a-z0-9]+", stem):
        if not t:
            continue
        if t.isdigit() and merged:
            merged[-1] += t
        else:
            merged.append(t)
    return merged


def _core_tokens(s: str) -> list[str]:
    toks = _name_tokens(s)
    core = [t for t in toks if not _NOISE_TOKEN_RE.match(t)]
    return core or toks


def _joins(tokens: list[str]) -> list[str]:
    """All contiguous token concatenations ('high','noise' -> 'highnoise')."""
    out = []
    for i in range(len(tokens)):
        j = ""
        for k in range(i, len(tokens)):
            j += tokens[k]
            out.append(j)
    return out


def _token_in_candidate(tok: str, cand_tokens: list[str], cand_joins: list[str]) -> bool:
    if len(tok) < 3:
        return tok in cand_tokens  # short tokens ("ae") only match exactly
    # Match only at token boundaries: 't5xxl' must not hit inside 'umt5xxl…'.
    # Prefix allowed so 'wan22' matches an unseparated 'wan22t2v…' token.
    if any(j == tok or j.startswith(tok) for j in cand_joins):
        return True
    # "a14b" should match "14b" — some repos drop the leading letter
    if tok[0].isalpha() and len(tok) > 3:
        stripped = tok[1:]
        if any(j == stripped or j.startswith(stripped) for j in cand_joins):
            return True
    return False


def find_model_file(value: str, options: list) -> str | None:
    """Exact match, else the closest equivalently-named file, else None."""
    base = os.path.basename(value)
    for o in options:
        so = str(o)
        if so == value or os.path.basename(so) == base:
            return so
    ext = os.path.splitext(value)[1].lower()
    want_core = _core_tokens(value)
    want_noise = set(_name_tokens(value)) - set(want_core)
    best: tuple | None = None
    for o in options:
        so = str(o)
        if os.path.splitext(so)[1].lower() != ext:
            continue
        cand_tokens = _name_tokens(so)
        cand_joins = _joins(cand_tokens)
        if not all(_token_in_candidate(t, cand_tokens, cand_joins) for t in want_core):
            continue
        cand_core = _core_tokens(so)
        extras = len(set(cand_core) - set(want_core))
        noise_overlap = len(want_noise & set(cand_tokens))
        score = (extras, -noise_overlap, len("".join(cand_tokens)), so)
        if best is None or score < best:
            best = score
            best_val = so
    return best_val if best is not None else None


def resolve_model_files(graph: dict, object_info: dict) -> dict:
    """Deep-copied graph with every resolvable model filename swapped for the
    file this ComfyUI install actually has. Unresolvable names are left as-is
    (check_graph reports those)."""
    g = copy.deepcopy(graph)
    for n in g.values():
        if not isinstance(n, dict):
            continue
        info = object_info.get(n.get("class_type"))
        if info is None:
            continue
        defs = _flatten_input_defs(info)
        for input_name, value in list((n.get("inputs") or {}).items()):
            if not isinstance(value, str) or not value.lower().endswith(MODEL_FILE_EXTS):
                continue
            d = defs.get(input_name)
            options = d[0] if isinstance(d, (list, tuple)) and d and isinstance(d[0], list) else None
            if not options or value in options:
                continue
            found = find_model_file(value, options)
            if found is not None:
                n["inputs"][input_name] = found
    return g


# ---------------------------------------------------------------------------
# Availability checks against ComfyUI /object_info


def _flatten_input_defs(node_info: dict) -> dict:
    merged: dict = {}
    inputs = node_info.get("input") or {}
    for section in ("required", "optional"):
        sec = inputs.get(section) or {}
        if isinstance(sec, dict):
            merged.update(sec)
    return merged


def check_graph(graph: dict, object_info: dict) -> str | None:
    """Return a human-readable reason the graph can't run, or None if it can."""
    for nid, n in graph.items():
        if not isinstance(n, dict):
            continue
        ct = n.get("class_type")
        if not ct:
            return f"node {nid} has no class_type (not an API-format export?)"
        info = object_info.get(ct)
        if info is None:
            return f"ComfyUI is missing the '{ct}' node (custom node pack not installed)"
        defs = _flatten_input_defs(info)
        for input_name, value in (n.get("inputs") or {}).items():
            if not isinstance(value, str) or not value.lower().endswith(MODEL_FILE_EXTS):
                continue
            d = defs.get(input_name)
            options = d[0] if isinstance(d, (list, tuple)) and d and isinstance(d[0], list) else None
            if options is None:
                continue
            if find_model_file(value, options) is not None:
                continue  # exact hit or an equivalently-named file we can swap in
            return f"model file '{value}' not found in ComfyUI ({ct}.{input_name})"
    return None
