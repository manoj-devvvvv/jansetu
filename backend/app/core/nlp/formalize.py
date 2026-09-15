import httpx
import logging
import json
from typing import Tuple, Optional
from app.config.settings import settings

logger = logging.getLogger(__name__)

def formalize_text(raw_text: str) -> Tuple[Optional[str], Optional[str]]:
    """
    Formalizes the raw complaint text and detects its original language using Gemini API.
    Returns (formalized_text_in_english, detected_language_code).
    """
    if not settings.GEMINI_API_KEY:
        logger.error("GEMINI_API_KEY is not set. Cannot formalize text.")
        return None, None

    GEMINI_API_URL = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent?key={settings.GEMINI_API_KEY}"
    
    prompt = f"""
    You are an expert civic grievance assistant. Your task is to process a raw complaint from a citizen.
    
    1. Detect the language of the original text.
    2. Translate it to English if it is not already in English.
    3. Formalize the text to be clear, professional, and actionable for government officers.
       - Remove filler words and emotions.
       - Highlight the core issue clearly.
    
    RAW TEXT: "{raw_text}"
    
    Return the response STRICTLY in the following JSON format without any markdown blocks or extra text:
    {{
        "detected_language": "en",  // 2-letter ISO code (e.g., en, te, hi)
        "formalized_text": "The formalized and translated text here."
    }}
    """
    
    payload = {
        "contents": [
            {
                "parts": [{"text": prompt}]
            }
        ],
        "generationConfig": {
            "temperature": 0.1,
            "responseMimeType": "application/json"
        }
    }
    
    headers = {
        "Content-Type": "application/json"
    }

    try:
        logger.info("Sending text to Gemini API for formalization...")
        with httpx.Client(timeout=30.0) as client:
            response = client.post(GEMINI_API_URL, json=payload, headers=headers)
            response.raise_for_status()
            
            data = response.json()
            # Parse Gemini response structure
            text_response = data.get("candidates", [{}])[0].get("content", {}).get("parts", [{}])[0].get("text", "{}")
            
            # Clean up markdown formatting if Gemini returns it
            text_response = text_response.strip()
            if text_response.startswith("```json"):
                text_response = text_response[7:]
            if text_response.startswith("```"):
                text_response = text_response[3:]
            if text_response.endswith("```"):
                text_response = text_response[:-3]
            
            result = json.loads(text_response.strip())
            
            formalized_text = result.get("formalized_text", "").strip()
            detected_lang = result.get("detected_language", "").strip().lower()
            
            logger.info(f"Formalization successful. Detected language: {detected_lang}")
            return formalized_text, detected_lang

    except Exception as e:
        logger.exception(f"Failed to formalize text: {str(e)}")
        return None, None
