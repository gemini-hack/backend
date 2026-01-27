import json
from typing import Optional
from sqlalchemy.ext.asyncio import AsyncSession  # <--- Added missing import
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
            
            "### HOW TO HANDLE UNSTRUCTURED TEXT:\n"
            "Do not look for specific keywords. Instead, read the entire document and categorize relevant phrases into these 'Semantic Buckets':\n"
            
            "1. **Lifestyle & Habits:** Anything related to food, movement, sleep, smoking, alcohol, or daily routine.\n"
            "   - *Examples: 'eats mostly cassava', 'sedentary job', 'insomnia'.*\n"
            "2. **Psychosocial Context:** Anything related to mood, home life, money, stigma, or support systems.\n"
            "   - *Examples: 'wife doesn't know status', 'struggling with school fees', 'looks anxious'.*\n"
            "3. **Physical Observations:** Visual clues noted by the doctor not captured in vitals.\n"
            "   - *Examples: 'looks pale', 'rash on arms', 'wasting'.*\n"
            
            "If a sentence fits a bucket, extract it verbatim."
        )

        prompt = """
        Analyze the attached medical record. Extract:
        1. Demographics (Name, DOB, Phone)
        2. Clinical Profile (Regimen, VL, CD4)
        3. **Observations**: Fill the semantic buckets defined above.

        Output JSON Structure:
        {
            "patient_uid": "generate-uuid",
            "first_name": "...",
            "last_name": "...",
            "primary_condition": "HIV",
            "hiv_profile": { ... },
            "lifestyle_factors": ["string"], 
            "psychosocial_context": ["string"],
            "physical_observations": ["string"],
            "medical_history": "parsed notes",
            "parsing_notes": "Any text that was illegible"
        }
        """

        try:
            # Create the media part
            content_part = types.Part.from_bytes(data=file_content, mime_type=mime_type)

            if not self.ai.client:
                raise Exception("AI Service not configured")

            response = await self.ai.client.aio.models.generate_content(
                model=settings.GEMINI_MODEL,
                contents=[content_part, prompt],
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                    system_instruction=system_instruction
                )
            )
            
            data = json.loads(response.text)
            
            # --- POST-PROCESSING ---
            # Aggregate the buckets into the medical history string so they show up in UI
            observations = []
            if data.get("lifestyle_factors"):
                observations.extend([f"Lifestyle: {x}" for x in data["lifestyle_factors"]])
            if data.get("psychosocial_context"):
                observations.extend([f"Psychosocial: {x}" for x in data["psychosocial_context"]])
            if data.get("physical_observations"):
                observations.extend([f"Observation: {x}" for x in data["physical_observations"]])
            
            current_history = data.get("medical_history", "")
            if not current_history: 
                current_history = ""
            
            # Append observations to history
            if observations:
                data["medical_history"] = current_history + "\n\n" + "\n".join(observations)

            # Validate Nested Models
            if "hiv_profile" in data and data["hiv_profile"]:
                from app.schemas.conditions import HIVProfileCreate
                # Ensure date fields are handled (Pydantic usually handles strings -> date)
                data["hiv_profile"] = HIVProfileCreate(**data["hiv_profile"])

            return PatientCreate(**data)

        except Exception as e:
            logger.error(f"Ingestion Error: {e}")
            # Raise exception so the API endpoint knows it failed
            raise e