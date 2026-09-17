import asyncio
import os

from fastapi import APIRouter, HTTPException, Request

from ..schemas import SpeechTranscriptionOut
from ..services.speech_transcription import (
    MAX_AUDIO_BYTES,
    SpeechBusyError,
    SpeechInputError,
    SpeechUnavailableError,
    make_temp_audio_file,
    transcribe_file,
)

router = APIRouter(tags=["speech"])


async def _cancel_task(task: asyncio.Task | None) -> None:
    """Cancel a child task and wait until its cleanup has completed."""
    if task is None:
        return
    if not task.done():
        task.cancel()
    try:
        await task
    except BaseException:
        # This helper is cleanup only; preserve the primary request result or
        # exception while still retrieving a completed child's exception.
        pass


async def _watch_disconnect(request: Request) -> None:
    """Poll after the body is read so a closed client stops model inference."""
    while True:
        if await request.is_disconnected():
            return
        await asyncio.sleep(0.2)


async def _transcribe_with_disconnect(
    request: Request, path: str, partial: bool
) -> tuple[str, str | None, float]:
    """Race inference with disconnect and always await both child tasks."""
    transcription = asyncio.create_task(transcribe_file(path, partial=partial))
    disconnect = asyncio.create_task(_watch_disconnect(request))
    try:
        done, _pending = await asyncio.wait(
            (transcription, disconnect),
            return_when=asyncio.FIRST_COMPLETED,
        )
        # If both finish at once, a completed transcription is still a valid
        # response.  Otherwise the closed connection must stop model work.
        if transcription in done:
            await _cancel_task(disconnect)
            return await transcription

        await _cancel_task(transcription)
        raise HTTPException(status_code=499, detail="Client disconnected")
    except asyncio.CancelledError:
        # Request cancellation is distinct from a disconnect notification, but
        # has the same cleanup requirement: no model task may outlive the
        # request and retain the singleton job slot.
        await _cancel_task(transcription)
        await _cancel_task(disconnect)
        raise
    except BaseException:
        await _cancel_task(transcription)
        await _cancel_task(disconnect)
        raise


@router.post("/speech/transcribe", response_model=SpeechTranscriptionOut)
async def transcribe_speech(
    request: Request, partial: bool = False
) -> SpeechTranscriptionOut:
    content_type = request.headers.get("content-type", "").split(";", 1)[0].strip().lower()
    if content_type != "application/octet-stream":
        raise HTTPException(
            status_code=415,
            detail="Content-Type must be application/octet-stream",
        )

    content_length = request.headers.get("content-length")
    if content_length is not None:
        try:
            if int(content_length) > MAX_AUDIO_BYTES:
                raise HTTPException(status_code=413, detail="Audio request exceeds 8 MiB")
        except ValueError as exc:
            raise HTTPException(status_code=400, detail="Invalid Content-Length") from exc

    fd, path = make_temp_audio_file()
    size = 0
    try:
        with os.fdopen(fd, "wb") as output:
            async for chunk in request.stream():
                if not chunk:
                    continue
                size += len(chunk)
                if size > MAX_AUDIO_BYTES:
                    raise HTTPException(status_code=413, detail="Audio request exceeds 8 MiB")
                output.write(chunk)
        if size == 0:
            raise HTTPException(status_code=422, detail="Audio request is empty")

        try:
            text, language, duration = await _transcribe_with_disconnect(
                request, path, partial
            )
        except SpeechBusyError as exc:
            raise HTTPException(status_code=429, detail=str(exc)) from exc
        except SpeechInputError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except SpeechUnavailableError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        return SpeechTranscriptionOut(
            text=text,
            language=language,
            duration_seconds=duration,
        )
    finally:
        try:
            os.unlink(path)
        except FileNotFoundError:
            pass