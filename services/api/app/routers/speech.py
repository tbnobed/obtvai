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


@router.post("/speech/transcribe", response_model=SpeechTranscriptionOut)
async def transcribe_speech(request: Request) -> SpeechTranscriptionOut:
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
            text, language, duration = await transcribe_file(path)
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