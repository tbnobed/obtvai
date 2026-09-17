"""Dependency-light safety tests for short speech transcription."""

import asyncio
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.services import speech_transcription as speech

try:
    from app.routers import speech as speech_router
except ModuleNotFoundError:
    # The API image has FastAPI; keep the decoder safety tests runnable in the
    # dependency-light repository checkout.
    speech_router = None


class _FakeProcess:
    def __init__(self, pcm: bytes, returncode: int = 0):
        self._pcm = pcm
        self.returncode = returncode

    async def communicate(self):
        return self._pcm, b"decoder details intentionally ignored"

    async def wait(self):
        return self.returncode


class SpeechTranscriptionTests(unittest.TestCase):
    def test_ffmpeg_is_restricted_to_safe_protocols_and_audio_demuxers(self):
        captured = {}
        pcm = b"\x01\x01" * 16_000

        async def spawn(*args, **_kwargs):
            captured["args"] = args
            return _FakeProcess(pcm)

        async def run():
            with patch.object(speech.asyncio, "create_subprocess_exec", spawn):
                return await speech._decode_audio("temporary-input")

        asyncio.run(run())
        args = list(captured["args"])
        protocol = args.index("-protocol_whitelist")
        formats = args.index("-format_whitelist")
        input_arg = args.index("-i")
        self.assertLess(protocol, input_arg)
        self.assertEqual(args[protocol + 1], "file,pipe")
        self.assertLess(formats, input_arg)
        self.assertEqual(
            args[formats + 1],
            "matroska,webm,mov,mp4,m4a,3gp,3g2,mj2,ogg,wav,mp3,flac,aac",
        )
        self.assertEqual(args[args.index("-t") + 1], "61.0")
        self.assertEqual(args[args.index("-ac") + 1], "1")
        self.assertEqual(args[args.index("-ar") + 1], "16000")

    def test_decode_rejects_empty_invalid_silent_and_overlong_audio(self):
        async def run(pcm: bytes, returncode: int = 0):
            async def spawn(*_args, **_kwargs):
                return _FakeProcess(pcm, returncode)

            with patch.object(speech.asyncio, "create_subprocess_exec", spawn):
                return await speech._decode_audio("temporary-input")

        self.assertRaises(
            speech.SpeechInputError, lambda: asyncio.run(run(b"", 1))
        )
        self.assertRaises(
            speech.SpeechInputError,
            lambda: asyncio.run(run(b"\0\0" * 16_000)),
        )
        self.assertRaises(
            speech.SpeechInputError,
            lambda: asyncio.run(run(b"\x01\x01" * (speech.MAX_PCM_SAMPLES + 1))),
        )

    def test_decode_reports_bounded_duration(self):
        pcm = b"\x01\x01" * 16_000
        duration = asyncio.run(
            self._decode_with_pcm(pcm)
        )[1]
        self.assertEqual(duration, 1.0)

    async def _decode_with_pcm(self, pcm: bytes):
        async def spawn(*_args, **_kwargs):
            return _FakeProcess(pcm)

        with patch.object(speech.asyncio, "create_subprocess_exec", spawn):
            return await speech._decode_audio("temporary-input")

    def test_model_timeout_resets_worker_and_next_request_recovers(self):
        async def fake_decode(_path):
            return b"\x01\x01" * 16_000, 1.0

        async def scenario():
            async def hung_worker(_pcm):
                await asyncio.sleep(60)

            async def recovered_worker(_pcm):
                return "recovered", "en"

            with patch.object(speech, "_decode_audio", fake_decode), patch.object(
                speech, "_stop_worker"
            ) as stop_worker, patch.object(
                speech, "_transcribe_in_worker", hung_worker
            ), patch.object(speech, "MODEL_TIMEOUT_SECONDS", 0.01):
                with self.assertRaises(speech.SpeechUnavailableError):
                    await speech.transcribe_file("hung")
                stop_worker.assert_called_once()

                with patch.object(speech, "_transcribe_in_worker", recovered_worker):
                    text, language, duration = await speech.transcribe_file("next")
                self.assertEqual((text, language, duration), ("recovered", "en", 1.0))

        asyncio.run(scenario())

    def test_preview_and_viewer_auth_allowlist_are_explicit(self):
        root = Path(__file__).resolve().parents[3]
        mock_route = (root / "artifacts/api-server/src/routes/mock.ts").read_text()
        auth_route = (root / "artifacts/api-server/src/routes/auth.ts").read_text()
        production_auth = (root / "services/api/app/auth.py").read_text()
        self.assertIn('"/speech/transcribe"', mock_route)
        self.assertIn("Local transcription is not available in preview", mock_route)
        self.assertIn('"/speech/transcribe"', auth_route)
        self.assertIn('"/api/speech/transcribe"', production_auth)

    @unittest.skipIf(speech_router is None, "FastAPI is unavailable in this checkout")
    def test_streamed_request_limit_returns_413_and_removes_temp_file(self):
        fd, path = tempfile.mkstemp(prefix="speech-limit-test-")
        os.close(fd)

        class Request:
            headers = {
                "content-type": "application/octet-stream",
            }

            async def stream(self):
                yield b"x" * (speech.MAX_AUDIO_BYTES + 1)

        async def run():
            with patch.object(speech_router, "make_temp_audio_file", return_value=(os.open(path, os.O_WRONLY), path)):
                with self.assertRaises(speech_router.HTTPException) as caught:
                    await speech_router.transcribe_speech(Request())
                self.assertEqual(caught.exception.status_code, 413)

        asyncio.run(run())
        self.assertFalse(os.path.exists(path))
