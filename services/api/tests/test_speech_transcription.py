"""Dependency-light safety tests for short speech transcription."""

import asyncio
import inspect
import os
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
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

    def test_partial_silence_is_successful_but_empty_decoded_audio_is_invalid(self):
        silent_pcm = b"\0\0" * 16_000

        async def decode(pcm, partial=False):
            async def spawn(*_args, **_kwargs):
                return _FakeProcess(pcm)

            with patch.object(speech.asyncio, "create_subprocess_exec", spawn):
                return await speech._decode_audio("temporary-input", partial=partial)

        pcm, duration = asyncio.run(decode(silent_pcm, partial=True))
        self.assertEqual((pcm, duration), (b"", 1.0))
        with self.assertRaises(speech.SpeechInputError):
            asyncio.run(decode(b"", partial=True))

    def test_partial_silence_does_not_load_or_call_model(self):
        async def fake_decode(_path, partial=False):
            self.assertTrue(partial)
            return b"", 1.25

        async def scenario():
            with patch.object(speech, "_decode_audio", fake_decode), patch.object(
                speech, "_transcribe_in_worker"
            ) as worker:
                result = await speech.transcribe_file("silent", partial=True)
            worker.assert_not_called()
            self.assertEqual(result, ("", None, 1.25))

        asyncio.run(scenario())

    def test_partial_and_final_inference_use_distinct_beam_sizes(self):
        captured = []

        class FakeArray:
            def astype(self, _dtype):
                return self

            def __truediv__(self, _scale):
                return self

        class FakeNumpy:
            int16 = object()
            float32 = object()

            @staticmethod
            def frombuffer(_pcm, dtype=None):
                return FakeArray()

        class Model:
            def transcribe(self, _audio, **kwargs):
                captured.append(kwargs["beam_size"])
                return [SimpleNamespace(text=" words ")], SimpleNamespace(language="en")

        with patch.dict(sys.modules, {"numpy": FakeNumpy()}), patch.object(
            speech, "_load_model", return_value=Model()
        ):
            self.assertEqual(speech._transcribe_pcm(b"\x01\x01", partial=True), ("words", "en"))
            self.assertEqual(speech._transcribe_pcm(b"\x01\x01", partial=False), ("words", "en"))
        self.assertEqual(captured, [1, 5])

    def test_worker_message_carries_partial_flag(self):
        class Connection:
            def __init__(self):
                self.sent = []

            def send(self, value):
                self.sent.append(value)

            def poll(self):
                return True

            def recv(self):
                return ("ok", "words", "en")

        class Process:
            def is_alive(self):
                return True

        async def scenario():
            connection = Connection()
            with patch.object(
                speech, "_ensure_worker", return_value=(Process(), connection)
            ):
                result = await speech._transcribe_in_worker(b"pcm", partial=True)
            self.assertEqual(result, ("words", "en"))
            self.assertEqual(connection.sent, [(b"pcm", True)])

        asyncio.run(scenario())

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
    def test_partial_query_defaults_to_final_compatibility(self):
        self.assertIs(
            inspect.signature(speech_router.transcribe_speech)
            .parameters["partial"]
            .default,
            False,
        )

    @unittest.skipIf(speech_router is None, "FastAPI is unavailable in this checkout")
    def test_partial_silent_response_succeeds_but_empty_and_invalid_stay_422(self):
        class Request:
            headers = {"content-type": "application/octet-stream"}

            async def stream(self):
                yield b"valid-silent-audio"

            async def is_disconnected(self):
                return False

        class EmptyRequest(Request):
            async def stream(self):
                yield b""

        async def partial_result(_path, partial=False):
            self.assertTrue(partial)
            return "", None, 0.75

        fd, path = tempfile.mkstemp(prefix="speech-partial-test-")
        os.close(fd)
        try:
            with patch.object(
                speech_router, "make_temp_audio_file",
                return_value=(os.open(path, os.O_WRONLY), path),
            ), patch.object(speech_router, "transcribe_file", partial_result):
                result = asyncio.run(
                    speech_router.transcribe_speech(Request(), partial=True)
                )
            self.assertEqual(
                (result.text, result.language, result.duration_seconds),
                ("", None, 0.75),
            )
        finally:
            if os.path.exists(path):
                os.unlink(path)

        fd, path = tempfile.mkstemp(prefix="speech-empty-test-")
        os.close(fd)
        try:
            with patch.object(
                speech_router, "make_temp_audio_file",
                return_value=(os.open(path, os.O_WRONLY), path),
            ):
                with self.assertRaises(speech_router.HTTPException) as caught:
                    asyncio.run(
                        speech_router.transcribe_speech(EmptyRequest(), partial=True)
                    )
            self.assertEqual(caught.exception.status_code, 422)
        finally:
            if os.path.exists(path):
                os.unlink(path)

        async def malformed(_path, partial=False):
            raise speech.SpeechInputError("Audio is empty or not decodable")

        fd, path = tempfile.mkstemp(prefix="speech-invalid-test-")
        os.close(fd)
        try:
            with patch.object(
                speech_router, "make_temp_audio_file",
                return_value=(os.open(path, os.O_WRONLY), path),
            ), patch.object(speech_router, "transcribe_file", malformed):
                with self.assertRaises(speech_router.HTTPException) as caught:
                    asyncio.run(
                        speech_router.transcribe_speech(Request(), partial=True)
                    )
            self.assertEqual(caught.exception.status_code, 422)
        finally:
            if os.path.exists(path):
                os.unlink(path)

    @unittest.skipIf(speech_router is None, "FastAPI is unavailable in this checkout")
    def test_disconnect_cancels_inference_releases_slot_and_next_request_recovers(self):
        class Request:
            headers = {"content-type": "application/octet-stream"}

            def __init__(self, disconnected):
                self.disconnected = disconnected

            async def stream(self):
                yield b"audio"

            async def is_disconnected(self):
                return self.disconnected.is_set()

        async def scenario():
            disconnected = asyncio.Event()
            started = asyncio.Event()
            cancelled = asyncio.Event()

            async def hanging_transcription(_path, partial=False):
                self.assertTrue(partial)
                self.assertTrue(speech._job_slot.acquire(blocking=False))
                started.set()
                try:
                    await asyncio.Event().wait()
                except asyncio.CancelledError:
                    cancelled.set()
                    raise
                finally:
                    speech._job_slot.release()

            path = tempfile.mktemp(prefix="speech-disconnect-test-")
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC)
            request_task = None
            try:
                with patch.object(
                    speech_router, "make_temp_audio_file", return_value=(fd, path)
                ), patch.object(
                    speech_router, "transcribe_file", hanging_transcription
                ):
                    request_task = asyncio.create_task(
                        speech_router.transcribe_speech(
                            Request(disconnected), partial=True
                        )
                    )
                    await started.wait()
                    disconnected.set()
                    with self.assertRaises(speech_router.HTTPException) as caught:
                        await request_task
                self.assertEqual(caught.exception.status_code, 499)
                self.assertTrue(cancelled.is_set())
                self.assertFalse(speech._job_slot.locked())
                self.assertFalse(os.path.exists(path))
            finally:
                if request_task is not None and not request_task.done():
                    request_task.cancel()
                    await asyncio.gather(request_task, return_exceptions=True)
                if os.path.exists(path):
                    os.unlink(path)

            recovered_path = tempfile.mktemp(prefix="speech-recovered-test-")
            recovered_fd = os.open(
                recovered_path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC
            )

            async def recovered_transcription(_path, partial=False):
                self.assertTrue(speech._job_slot.acquire(blocking=False))
                speech._job_slot.release()
                return "recovered", "en", 0.5

            try:
                with patch.object(
                    speech_router,
                    "make_temp_audio_file",
                    return_value=(recovered_fd, recovered_path),
                ), patch.object(
                    speech_router, "transcribe_file", recovered_transcription
                ):
                    result = await speech_router.transcribe_speech(
                        Request(asyncio.Event()), partial=True
                    )
                self.assertEqual(
                    (result.text, result.language, result.duration_seconds),
                    ("recovered", "en", 0.5),
                )
            finally:
                if os.path.exists(recovered_path):
                    os.unlink(recovered_path)

        asyncio.run(scenario())

    @unittest.skipIf(speech_router is None, "FastAPI is unavailable in this checkout")
    def test_normal_completion_cancels_and_awaits_disconnect_watcher(self):
        class Request:
            headers = {"content-type": "application/octet-stream"}

            async def stream(self):
                yield b"audio"

            async def is_disconnected(self):
                return False

        async def scenario():
            watcher_started = asyncio.Event()
            watcher_cancelled = asyncio.Event()

            async def watcher(_request):
                watcher_started.set()
                try:
                    await asyncio.Event().wait()
                except asyncio.CancelledError:
                    watcher_cancelled.set()
                    raise

            async def completed(_path, partial=False):
                await asyncio.sleep(0)
                return "done", "en", 0.25

            path = tempfile.mktemp(prefix="speech-watcher-test-")
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC)
            try:
                with patch.object(
                    speech_router, "make_temp_audio_file", return_value=(fd, path)
                ), patch.object(
                    speech_router, "_watch_disconnect", watcher
                ), patch.object(
                    speech_router, "transcribe_file", completed
                ):
                    result = await speech_router.transcribe_speech(Request())
                self.assertEqual(result.text, "done")
                self.assertTrue(watcher_started.is_set())
                self.assertTrue(watcher_cancelled.is_set())
                self.assertFalse(os.path.exists(path))
            finally:
                if os.path.exists(path):
                    os.unlink(path)

        asyncio.run(scenario())

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

            async def is_disconnected(self):
                return False

        async def run():
            with patch.object(speech_router, "make_temp_audio_file", return_value=(os.open(path, os.O_WRONLY), path)):
                with self.assertRaises(speech_router.HTTPException) as caught:
                    await speech_router.transcribe_speech(Request())
                self.assertEqual(caught.exception.status_code, 413)

        asyncio.run(run())
        self.assertFalse(os.path.exists(path))
