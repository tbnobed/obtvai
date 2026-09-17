"""Bounded, local-only short speech transcription.

This service deliberately does not persist an upload.  The caller owns the
temporary compressed input file and this module only keeps the bounded,
decoded PCM in memory while the model runs.
"""

import asyncio
import logging
import math
import multiprocessing
import tempfile
import threading
from array import array
from typing import Any

logger = logging.getLogger(__name__)

MAX_AUDIO_BYTES = 8 * 1024 * 1024
MAX_DURATION_SECONDS = 60.0
DECODE_LIMIT_SECONDS = 61.0
SAMPLE_RATE = 16_000
MAX_PCM_SAMPLES = int(MAX_DURATION_SECONDS * SAMPLE_RATE)
FFMPEG_TIMEOUT_SECONDS = 15.0
MODEL_TIMEOUT_SECONDS = 120.0


class SpeechInputError(ValueError):
    """The request did not contain usable, non-silent speech audio."""


class SpeechBusyError(RuntimeError):
    """The singleton CPU transcription job is already occupied."""


class SpeechUnavailableError(RuntimeError):
    """The local transcription engine could not be loaded or run."""


_job_slot = threading.Lock()
_model: Any = None
_model_lock = threading.Lock()
_worker_process: Any = None
_worker_connection: Any = None


def _load_model() -> Any:
    """Load the pinned small multilingual model once, in the process cache.

    faster-whisper uses the existing Hugging Face cache (HF_HOME/HF_HUB_CACHE)
    without introducing a cloud or alternate engine.
    """
    global _model
    if _model is not None:
        return _model
    with _model_lock:
        if _model is None:
            try:
                from faster_whisper import WhisperModel

                _model = WhisperModel(
                    "small",
                    device="cpu",
                    compute_type="int8",
                    cpu_threads=4,
                    num_workers=1,
                )
            except Exception as exc:
                logger.exception("Local speech model failed to load")
                raise SpeechUnavailableError("Local transcription is unavailable") from exc
    return _model


async def _decode_audio(path: str) -> tuple[bytes, float]:
    """Decode one temporary input to bounded mono 16 kHz signed PCM."""
    try:
        proc = await asyncio.create_subprocess_exec(
            "ffmpeg",
            "-nostdin",
            "-hide_banner",
            "-loglevel",
            "error",
            # The upload is untrusted.  Never allow concat/M3U/HLS or other
            # demuxers to resolve network URLs or local files referenced by a
            # playlist; only these ordinary single-file audio containers are
            # accepted.
            "-protocol_whitelist",
            "file,pipe",
            "-format_whitelist",
            "matroska,webm,mov,mp4,m4a,3gp,3g2,mj2,ogg,wav,mp3,flac,aac",
            "-i",
            path,
            "-t",
            str(DECODE_LIMIT_SECONDS),
            "-vn",
            "-sn",
            "-dn",
            "-ac",
            "1",
            "-ar",
            str(SAMPLE_RATE),
            "-f",
            "s16le",
            "pipe:1",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
    except (FileNotFoundError, OSError) as exc:
        logger.exception("ffmpeg is unavailable for speech decoding")
        raise SpeechUnavailableError("Local transcription is unavailable") from exc

    try:
        pcm, _stderr = await asyncio.wait_for(
            proc.communicate(), timeout=FFMPEG_TIMEOUT_SECONDS
        )
    except asyncio.TimeoutError as exc:
        if proc.returncode is None:
            proc.kill()
        await proc.wait()
        raise SpeechInputError("Audio decoding timed out") from exc
    except asyncio.CancelledError:
        if proc.returncode is None:
            proc.kill()
        await proc.wait()
        raise

    if proc.returncode != 0 or not pcm or len(pcm) % 2:
        raise SpeechInputError("Audio is empty or not decodable")

    samples = len(pcm) // 2
    if samples == 0:
        raise SpeechInputError("Audio is empty or not decodable")
    if samples > MAX_PCM_SAMPLES:
        raise SpeechInputError("Audio must be 60 seconds or shorter")

    duration = samples / SAMPLE_RATE
    values = array("h")
    values.frombytes(pcm)
    # Reject genuine silence before Whisper has an opportunity to hallucinate.
    peak = max(abs(value) for value in values)
    rms = math.sqrt(sum(value * value for value in values) / len(values))
    if peak < 128 or rms < 32:
        raise SpeechInputError("Audio contains no detectable speech")
    return pcm, duration


def _transcribe_pcm(pcm: bytes) -> tuple[str, str | None]:
    """Run one inference in the spawned worker process."""
    try:
        import numpy as np

        audio = np.frombuffer(pcm, dtype=np.int16).astype(np.float32) / 32768.0
        model = _load_model()
        segments, info = model.transcribe(
            audio,
            language=None,
            beam_size=5,
            vad_filter=True,
            condition_on_previous_text=False,
        )
        text = " ".join(
            segment.text.strip() for segment in segments if segment.text.strip()
        ).strip()
        if not text:
            raise SpeechInputError("Audio contains no detectable speech")
        return text, getattr(info, "language", None) or None
    except (SpeechInputError, SpeechUnavailableError):
        raise
    except Exception as exc:
        logger.exception("Local speech model failed during transcription")
        raise SpeechUnavailableError("Local transcription is unavailable") from exc


def _speech_worker_main(connection: Any) -> None:
    """Top-level spawn target; caches the model without inheriting API state."""
    try:
        while True:
            message = connection.recv()
            if message is None:
                return
            try:
                text, language = _transcribe_pcm(message)
                connection.send(("ok", text, language))
            except SpeechInputError:
                connection.send(("input",))
            except Exception:
                # Never send exception text, paths, or model configuration to
                # the API process or its client.
                connection.send(("unavailable",))
    except (EOFError, OSError):
        return
    finally:
        try:
            connection.close()
        except OSError:
            pass


def _ensure_worker() -> tuple[Any, Any]:
    global _worker_process, _worker_connection
    if (
        _worker_process is not None
        and _worker_process.is_alive()
        and _worker_connection is not None
    ):
        return _worker_process, _worker_connection

    if _worker_process is not None or _worker_connection is not None:
        _stop_worker()
    ctx = multiprocessing.get_context("spawn")
    parent, child = ctx.Pipe()
    process = ctx.Process(target=_speech_worker_main, args=(child,), daemon=True)
    process.start()
    child.close()
    _worker_process = process
    _worker_connection = parent
    return process, parent


def _stop_worker() -> None:
    """Terminate and reap a stuck worker, then clear the reusable cache."""
    global _worker_process, _worker_connection
    process, connection = _worker_process, _worker_connection
    _worker_process = None
    _worker_connection = None
    if connection is not None:
        try:
            connection.close()
        except OSError:
            pass
    if process is None:
        return
    try:
        if process.is_alive():
            process.terminate()
        process.join(timeout=5)
        if process.is_alive():
            process.kill()
            process.join(timeout=5)
    except (OSError, AssertionError):
        logger.exception("Speech worker cleanup failed")


async def _transcribe_in_worker(pcm: bytes) -> tuple[str, str | None]:
    process, connection = _ensure_worker()
    try:
        connection.send(pcm)
        while True:
            if connection.poll():
                response = connection.recv()
                if response[0] == "ok":
                    return response[1], response[2]
                if response[0] == "input":
                    raise SpeechInputError("Audio contains no detectable speech")
                raise SpeechUnavailableError("Local transcription is unavailable")
            if not process.is_alive():
                raise SpeechUnavailableError("Local transcription is unavailable")
            await asyncio.sleep(0.05)
    except (BrokenPipeError, EOFError, OSError) as exc:
        raise SpeechUnavailableError("Local transcription is unavailable") from exc


async def transcribe_file(path: str) -> tuple[str, str | None, float]:
    """Transcribe a temporary file, with exactly one bounded model job."""
    if not _job_slot.acquire(blocking=False):
        raise SpeechBusyError("Speech transcription is busy")

    try:
        pcm, duration = await _decode_audio(path)
        try:
            text, language = await asyncio.wait_for(
                _transcribe_in_worker(pcm),
                timeout=MODEL_TIMEOUT_SECONDS,
            )
        except asyncio.TimeoutError as exc:
            _stop_worker()
            raise SpeechUnavailableError("Local transcription timed out") from exc
        except asyncio.CancelledError:
            _stop_worker()
            raise
        except SpeechUnavailableError:
            _stop_worker()
            raise
        return text, language, duration
    finally:
        # On timeout/cancellation the worker was synchronously terminated and
        # reaped above; on success the child has replied.  Either way the
        # process is no longer executing this request before the slot opens.
        _job_slot.release()


def make_temp_audio_file() -> tuple[int, str]:
    return tempfile.mkstemp(prefix=".speech-", suffix=".audio")