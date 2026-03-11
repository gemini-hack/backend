import asyncio

from google import genai
from typing import Any, Dict, Optional
import json
from app.core.config import settings
from app.utils.logger import logger

# Default timeout for Gemini API calls (seconds)
DEFAULT_TIMEOUT = 30


class GeminiService:
    """Service for interacting with the Google GenAI SDK."""

    def __init__(self):
        if not settings.GEMINI_API_KEY:
            logger.warning("GEMINI_API_KEY not set. AI features will be limited/mocked.")
            self.client = None
            return

        self.client = genai.Client(api_key=settings.GEMINI_API_KEY)
        self.model_name = settings.GEMINI_MODEL

    async def generate_response(
        self,
        prompt: str,
        system_instruction: Optional[str] = None,
        json_mode: bool = False,
        timeout: int = DEFAULT_TIMEOUT
    ) -> str:
        """Generate a response from Gemini with a timeout guard."""
        if not self.client:
            return "AI service not configured."

        try:
            config = {}
            if system_instruction:
                config["system_instruction"] = system_instruction

            if json_mode:
                config["response_mime_type"] = "application/json"

            response = await asyncio.wait_for(
                self.client.aio.models.generate_content(
                    model=self.model_name,
                    contents=prompt,
                    config=config
                ),
                timeout=timeout
            )
            return response.text
        except asyncio.TimeoutError:
            logger.error(f"Gemini API call timed out after {timeout}s")
            raise
        except Exception as e:
            error_msg = str(e)
            if "RESOURCE_EXHAUSTED" in error_msg:
                logger.error(f"GEMINI QUOTA EXHAUSTED: {error_msg}. Check if billing is enabled or if using a restricted model like 2.5-pro on Free Tier.")
            else:
                logger.error(f"Gemini API call failed: {error_msg}")
            raise

    async def get_structured_response(
        self,
        prompt: str,
        system_instruction: Optional[str] = None,
        timeout: int = DEFAULT_TIMEOUT
    ) -> Dict[str, Any]:
        """Generate a structured JSON response from Gemini."""
        response_text = await self.generate_response(
            prompt,
            system_instruction,
            json_mode=True,
            timeout=timeout
        )
        try:
            return json.loads(response_text)
        except json.JSONDecodeError:
            logger.error(f"Failed to parse JSON from Gemini response: {response_text[:200]}")
            return {"error": "Invalid JSON response", "raw_text": response_text}


# Global singleton
gemini_service = GeminiService()
