import httpx
import logging
from typing import Tuple, Optional
from app.config.settings import settings

logger = logging.getLogger(__name__)

GROQ_API_URL = "https://api.groq.com/openai/v1/audio/transcriptions"

def transcribe_audio(audio_url: str) -> Tuple[Optional[str], Optional[float]]:
    """
    Downloads audio from the given URL and transcribes it using Groq's Whisper model.
    Returns (transcription_text, confidence_score).
    """
    if not settings.GROQ_API_KEY:
        logger.error("GROQ_API_KEY is not set. Cannot transcribe audio.")
        return None, None

    try:
        # 1. Download the audio file
        logger.info(f"Downloading audio from {audio_url}")
        with httpx.Client(timeout=30.0) as client:
            audio_response = client.get(audio_url)
            audio_response.raise_for_status()
            audio_bytes = audio_response.content
            
        # 2. Send to Groq API
        logger.info("Sending audio to Groq Whisper API for transcription...")
        
        headers = {
            "Authorization": f"Bearer {settings.GROQ_API_KEY}"
        }
        
        files = {
            # Groq requires a filename. We assume standard audio formats (like m4a, ogg, or wav)
            "file": ("complaint_audio.m4a", audio_bytes, "audio/m4a")
        }
        
        data = {
            "model": "whisper-large-v3-turbo",
            "response_format": "json",
            "language": "te" # Telugu is common for JanSetu, but Whisper can auto-detect if omitted. Let's omit for auto-detection.
        }
        # Removing language to allow auto-detection
        del data["language"]
        
        with httpx.Client(timeout=60.0) as client:
            response = client.post(
                GROQ_API_URL,
                headers=headers,
                files=files,
                data=data
            )
            response.raise_for_status()
            result = response.json()
            
            transcription = result.get("text", "").strip()
            # Groq's whisper doesn't always return confidence easily in simple json format.
            # We'll assign a default high confidence if transcription succeeds.
            confidence = 0.95 if transcription else 0.0
            
            logger.info("Transcription successful.")
            return transcription, confidence

    except Exception as e:
        logger.exception(f"Failed to transcribe audio: {str(e)}")
        return None, None
