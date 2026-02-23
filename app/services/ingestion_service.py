import json
import uuid
from typing import Optional
from sqlalchemy.ext.asyncio import AsyncSession
import google.genai.types as types
from app.services.ai_service import GeminiService
from app.schemas.patient import PatientCreate
from app.utils.logger import logger
from app.core.config import settings

class IngestionService:
    def __init__(self, db: AsyncSession):
        self.ai = GeminiService()
        self.db = db

    async def parse_document_to_patient(self, file_content: bytes, mime_type: str) -> Optional[PatientCreate]:
        
        system_instruction = (
            "You are an expert Medical Data Extractor. "
            "Your goal is to extract structured clinical data AND capture subtle unstructured context.\n"
            
            "### STRICT FORMATTING RULES:\n"
            "1. **Dates**: MUST be YYYY-MM-DD. If unknown, use null.\n"
            "2. **Gender**: MUST be one of: 'male', 'female', 'other', 'prefer_not_to_say'.\n"
            "3. **Conditions**: MUST be one of: 'hiv', 'diabetes', 'hypertension', 'other'.\n"
            "4. **UID**: Always return null for patient_uid.\n"
            
            "### HOW TO HANDLE UNSTRUCTURED TEXT (Semantic Buckets):\n"
            "1. **Lifestyle**: Food, movement, sleep, smoking, alcohol.\n"
            "2. **Psychosocial**: Mood, money, stigma, family support.\n"
            "3. **Observations**: Physical visual clues (pale, rash, wasting).\n"
        )

        prompt = """
        Analyze the attached medical record. Extract data into this JSON structure:
        {
            "patient_uid": null,
            "first_name": "string",
            "last_name": "string",
            "date_of_birth": "YYYY-MM-DD",
            "gender": "male/female",
            "primary_condition": "hiv",
            "hiv_profile": { 
                "last_viral_load_result": 1000,
                "last_refill_date": "YYYY-MM-DD"
            },
            "lifestyle_factors": ["string"], 
            "psychosocial_context": ["string"],
            "physical_observations": ["string"],
            "medical_history": "summary of past history",
            "parsing_notes": "illegible text or warnings"
        }
        """

        try:
            content_part = types.Part.from_bytes(data=file_content, mime_type=mime_type)

            if not self.ai.client:
                raise Exception("AI Service not configured")

            response = await self.ai.client.aio.models.generate_content(
                model=settings.GEMINI_MODEL,
                contents=[content_part, prompt],
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                    system_instruction=system_instruction,
                    temperature=0.1 # Low temperature for factual extraction
                )
            )
            
            raw_text = response.text
            if raw_text.startswith("```json"):
                raw_text = raw_text.replace("```json", "").replace("```", "")
            
            data = json.loads(raw_text)
            
            if not data.get("patient_uid"):
                data["patient_uid"] = str(uuid.uuid4())

            if data.get("gender"):
                data["gender"] = data["gender"].lower()
            if data.get("primary_condition"):
                data["primary_condition"] = data["primary_condition"].lower()

            observations = []
            if data.get("lifestyle_factors"):
                observations.extend([f"Lifestyle: {x}" for x in data["lifestyle_factors"]])
            if data.get("psychosocial_context"):
                observations.extend([f"Psychosocial: {x}" for x in data["psychosocial_context"]])
            if data.get("physical_observations"):
                observations.extend([f"Observation: {x}" for x in data["physical_observations"]])
            
            current_history = data.get("medical_history") or ""
            if observations:
                data["medical_history"] = current_history + "\n\n--- AI Observations ---\n" + "\n".join(observations)


            if "hiv_profile" in data and not data["hiv_profile"]:
                del data["hiv_profile"]
            elif "hiv_profile" in data:
                 from app.schemas.conditions import HIVProfileCreate
                 data["hiv_profile"] = HIVProfileCreate(**data["hiv_profile"])

            return PatientCreate(**data)

        except Exception as e:
            logger.error(f"Ingestion Error: {e}")
            raise e