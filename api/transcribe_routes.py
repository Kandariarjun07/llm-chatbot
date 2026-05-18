"""Voice transcription endpoint using Deepgram."""

import asyncio
import logging
from typing import Any

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile

from api.auth_routes import get_current_user
from app.config import get_settings

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/transcribe", tags=["transcribe"])


@router.post("")
async def transcribe_audio(
    file: UploadFile = File(...),
    user: dict[str, Any] = Depends(get_current_user),
) -> dict[str, str]:
    """Upload an audio blob and return the transcript via Deepgram."""
    settings = get_settings()
    if not settings.deepgram_api_key:
        raise HTTPException(status_code=503, detail="Deepgram API key not configured.")

    try:
        from deepgram import DeepgramClient
    except ImportError as exc:
        logger.error("deepgram-sdk not installed: %s", exc)
        raise HTTPException(status_code=503, detail="Deepgram SDK not installed.")

    payload = await file.read()
    if not payload:
        raise HTTPException(status_code=400, detail="Empty audio file.")

    deepgram = DeepgramClient(api_key=settings.deepgram_api_key)

    def _transcribe():
        return deepgram.listen.v1.media.transcribe_file(
            request=payload,
            model="nova-3",
            language="en",
            smart_format=True,
        )

    try:
        response = await asyncio.to_thread(_transcribe)
    except Exception as exc:
        logger.error("Deepgram transcription failed: %s", exc, exc_info=True)
        raise HTTPException(status_code=502, detail=f"Deepgram error: {exc}")

    # Safely extract transcript
    try:
        transcript = (
            response.results.channels[0].alternatives[0].transcript
        )
    except (AttributeError, IndexError, TypeError):
        transcript = ""

    return {"transcript": transcript.strip()}
