"""Lazy loader for the pinned Chatterbox V3 language packs.

The worker also has the older ``chatterbox`` package installed for existing
jobs.  V3 is deliberately kept in its own install at
``/opt/chatterbox-v3``; importing this module must therefore not import torch
or either Chatterbox package.

The model files are assembled from immutable, revision-pinned Hub downloads.
The assembled directory only contains symlinks, so a Hub snapshot is never
modified and a partially/incorrectly populated model cannot silently replace
an existing one.
"""

from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import shutil
import sys
import tempfile
from typing import Any, Callable


# These are intentionally plain constants rather than values imported from the
# runtime.  Keeping the manifest here makes cache IDs deterministic and keeps
# importing this module safe on CPU-only test runners.
CHATTERBOX_V3_RUNTIME = Path("/opt/chatterbox-v3")

ES_REPO_ID = "ResembleAI/Chatterbox-Multilingual-es-mx-latam"
ES_REVISION = "27e595bf2fe7be0533ca299d9afafcde08b7cca7"
ES_T3_FILENAME = "t3_es_mx_latam.safetensors"

BASE_REPO_ID = "ResembleAI/chatterbox"
BASE_REVISION = "5bb1f6ee58e50c3b8d408bc82a6d3740c2db6e18"
BASE_T3_FILENAME = "t3_mtl23ls_v3.safetensors"

S3GEN_FILENAME = "s3gen_v3.pt"
VE_FILENAME = "ve.pt"
TOKENIZER_FILENAME = "grapheme_mtl_merged_expanded_v1.json"

# This is the language set exposed by the official multilingual V3 tokenizer.
# Locale suffixes are normalized to their two-letter model language below
# (for example, ``zh-cn`` -> ``zh`` and ``es-MX`` -> ``es``).
SUPPORTED_LANGUAGES = frozenset(
    {
        "ar",
        "da",
        "de",
        "el",
        "en",
        "es",
        "fi",
        "fr",
        "he",
        "hi",
        "it",
        "ja",
        "ko",
        "ms",
        "nl",
        "no",
        "pl",
        "pt",
        "ru",
        "sv",
        "sw",
        "tr",
        "zh",
    }
)


@dataclass(frozen=True)
class _Variant:
    """Files and revisions needed by one immutable assembled checkpoint."""

    key: str
    repo_id: str
    revision: str
    t3_filename: str
    # ``ve.pt`` is intentionally always sourced from the base repository.  The
    # regional Spanish repository does not publish a compatible VE checkpoint.
    ve_repo_id: str = BASE_REPO_ID
    ve_revision: str = BASE_REVISION
    tokenizer_filename: str = TOKENIZER_FILENAME

    @property
    def cache_name(self) -> str:
        # Include every revision that contributes a file.  Do not shorten
        # these in the directory name: this is also useful when inspecting a
        # cache after a model update.
        return (
            f"{self.key}-t3-{self.revision}-"
            f"ve-{self.ve_revision}"
        )


_ES_VARIANT = _Variant(
    key="es-mx-latam",
    repo_id=ES_REPO_ID,
    revision=ES_REVISION,
    t3_filename=ES_T3_FILENAME,
)
_BASE_VARIANT = _Variant(
    key="mtl23",
    repo_id=BASE_REPO_ID,
    revision=BASE_REVISION,
    t3_filename=BASE_T3_FILENAME,
)


# External modules are looked up only at the point they are needed.  Besides
# keeping import-time behavior cheap, these names provide narrow seams for
# unit tests without importing torch or installing the V3 runtime.
FileLock: Any = None
hf_hub_download: Any = None
ChatterboxTTS: Any = None


def _normalize_language(lang: str) -> str:
    """Return the language ID accepted by the V3 multilingual tokenizer."""
    if not isinstance(lang, str) or not lang.strip():
        raise ValueError("Chatterbox V3 language must be a non-empty string")

    normalized = lang.strip().lower().replace("_", "-")
    # The existing dubbing API uses zh-cn while Chatterbox uses zh.  Regional
    # language IDs are otherwise reduced to the model's base language.
    if normalized == "zh-cn":
        normalized = "zh"
    elif "-" in normalized:
        normalized = normalized.split("-", 1)[0]

    if normalized not in SUPPORTED_LANGUAGES:
        supported = ", ".join(sorted(SUPPORTED_LANGUAGES))
        raise ValueError(
            f"Unsupported Chatterbox V3 language '{lang}'. "
            f"Supported languages: {supported}"
        )
    return normalized


def _variant_for_language(lang: str) -> tuple[str, _Variant]:
    normalized = _normalize_language(lang)
    # Spanish uses the regional language pack.  Every other supported language
    # uses the pinned 23-language pack.
    return normalized, _ES_VARIANT if normalized == "es" else _BASE_VARIANT


def chatterbox_variant(lang: str) -> str:
    """Return a stable model tag suitable for dub-cache invalidation.

    The language is included because it affects generated output even when
    several languages share one checkpoint.  Both the selected T3 revision
    and the shared voice-encoder revision are included so an asset update
    cannot reuse an old dub cache.
    """
    normalized, variant = _variant_for_language(lang)
    return (
        f"chatterbox-v3:{variant.key}:{normalized}:"
        f"t3@{variant.revision}:ve@{variant.ve_revision}"
    )


def _hf_home() -> Path:
    """Resolve HF_HOME at call time, allowing deployments/tests to override it."""
    configured = os.environ.get("HF_HOME")
    return Path(configured).expanduser() if configured else Path.home() / ".cache" / "huggingface"


def _cache_root() -> Path:
    return _hf_home() / "obtv-chatterbox-v3"


def _get_file_lock() -> Any:
    global FileLock
    if FileLock is None:
        from filelock import FileLock as _FileLock

        FileLock = _FileLock
    return FileLock


def _get_hf_hub_download() -> Callable[..., str]:
    global hf_hub_download
    if hf_hub_download is None:
        from huggingface_hub import hf_hub_download as _hf_hub_download

        hf_hub_download = _hf_hub_download
    return hf_hub_download


def _download_asset(repo_id: str, revision: str, filename: str) -> Path:
    """Download one exact Hub file and return its immutable cache path.

    ``hf_hub_download`` is used instead of ``snapshot_download`` and no
    ``local_dir`` is supplied.  This leaves Hugging Face's content-addressed
    snapshot untouched; the assembled model below only links to that file.
    """
    downloaded = _get_hf_hub_download()(
        repo_id=repo_id,
        filename=filename,
        revision=revision,
        repo_type="model",
        cache_dir=str(_hf_home() / "hub"),
    )
    source = Path(downloaded)
    if not source.is_file():
        raise RuntimeError(
            f"Hugging Face download did not produce a file: "
            f"{repo_id}@{revision}:{filename}"
        )
    return source


def _expected_inputs(variant: _Variant) -> tuple[tuple[str, str, str], ...]:
    """Return ``(assembled_name, repo, revision)`` entries in stable order."""
    return (
        (variant.t3_filename, variant.repo_id, variant.revision),
        (S3GEN_FILENAME, variant.repo_id, variant.revision),
        (VE_FILENAME, variant.ve_repo_id, variant.ve_revision),
        (variant.tokenizer_filename, variant.repo_id, variant.revision),
    )


def _assembled_is_complete(directory: Path, variant: _Variant) -> bool:
    """Check that an existing assembled directory is made of file symlinks."""
    if not directory.is_dir() or directory.is_symlink():
        return False
    return all(
        (directory / assembled_name).is_symlink()
        and (directory / assembled_name).resolve().is_file()
        for assembled_name, _, _ in _expected_inputs(variant)
    )


def _assemble_variant(variant: _Variant) -> Path:
    """Download and atomically assemble one immutable variant directory."""
    root = _cache_root()
    root.mkdir(parents=True, exist_ok=True)
    destination = root / variant.cache_name
    lock_path = root / ".lock"

    lock_type = _get_file_lock()
    with lock_type(str(lock_path)):
        # Existing model directories are immutable.  A complete directory is
        # reusable; an incomplete one is an explicit error rather than a
        # tempting in-place repair that could overwrite a prior snapshot.
        if destination.exists() or os.path.lexists(destination):
            if _assembled_is_complete(destination, variant):
                return destination
            raise RuntimeError(
                f"Immutable Chatterbox V3 cache is incomplete or invalid: "
                f"{destination}"
            )

        temporary = Path(
            tempfile.mkdtemp(prefix=f".{variant.cache_name}.", dir=str(root))
        )
        try:
            # Download before publishing the directory.  A failure leaves no
            # visible variant and, importantly, is not replaced by a fallback
            # model.
            for assembled_name, repo_id, revision in _expected_inputs(variant):
                source = _download_asset(repo_id, revision, assembled_name)
                os.symlink(str(source), str(temporary / assembled_name))

            # The lock makes destination creation atomic with respect to this
            # loader.  Do not use os.replace here: replacing an existing
            # immutable directory would violate the cache contract.
            temporary.rename(destination)
            return destination
        except BaseException:
            shutil.rmtree(temporary, ignore_errors=True)
            raise


def prepare_chatterbox_v3(lang: str) -> Path:
    """Ensure the pinned local checkpoint for ``lang`` exists and return it."""
    _, variant = _variant_for_language(lang)
    return _assemble_variant(variant)


def _get_chatterbox_tts() -> Any:
    """Import the official V3 class from its isolated runtime on first use."""
    global ChatterboxTTS
    if ChatterboxTTS is None:
        runtime = str(CHATTERBOX_V3_RUNTIME)
        if not (CHATTERBOX_V3_RUNTIME / "chatterbox_v3").is_dir():
            raise RuntimeError(
                "The isolated Chatterbox V3 runtime is missing: "
                f"{CHATTERBOX_V3_RUNTIME / 'chatterbox_v3'}"
            )
        if runtime not in sys.path:
            # Prepend rather than append so the official runtime wins over
            # similarly named packages in the worker environment.
            sys.path.insert(0, runtime)
        from chatterbox_v3.tts import ChatterboxTTS as _ChatterboxTTS

        ChatterboxTTS = _ChatterboxTTS
    return ChatterboxTTS


def load_chatterbox_v3(device: str, lang: str) -> Any:
    """Prepare and load a V3 model for ``lang`` on ``device``.

    The official ``from_local`` implementation loads the V3 decoder with
    ``strict=False``.  We intentionally delegate all checkpoint loading to it:
    probing the large decoder state here would read it a second time and would
    not improve compatibility diagnostics.
    """
    normalized, variant = _variant_for_language(lang)
    directory = _assemble_variant(variant)
    model_class = _get_chatterbox_tts()
    model = model_class.from_local(
        directory,
        device,
        t3_filename=variant.t3_filename,
        s3gen_filename=S3GEN_FILENAME,
    )
    model.obtv_model_id = chatterbox_variant(normalized)
    return model


__all__ = [
    "BASE_REPO_ID",
    "BASE_REVISION",
    "BASE_T3_FILENAME",
    "CHATTERBOX_V3_RUNTIME",
    "ES_REPO_ID",
    "ES_REVISION",
    "ES_T3_FILENAME",
    "S3GEN_FILENAME",
    "SUPPORTED_LANGUAGES",
    "TOKENIZER_FILENAME",
    "VE_FILENAME",
    "chatterbox_variant",
    "load_chatterbox_v3",
    "prepare_chatterbox_v3",
]