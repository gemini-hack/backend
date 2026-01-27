import asyncio
from app.services.ai_service import gemini_service
from app.utils.logger import logger

async def normalize_regimen_string(raw_text: str) -> str:
    """
    Uses Gemini Flash to convert messy doctor notes into standard codes.
    Input: "Tenofovir and Lamivudine with Dolutegravir" 
    Output: "TDF/3TC/DTG"
    """
    if not raw_text:
        return None

    # Fast check: If it looks standard, skip AI (save latency)
    if "/" in raw_text and len(raw_text) < 20:
        return raw_text.strip()

    prompt = (
        f"Standardize this HIV regimen string into standard abbreviations (e.g. TDF, 3TC, DTG, AZT, NVP, EFV).\n"
        f"Examples:\n"
        f"- 'Tenofovir/Lamivudine/Dolutegravir' -> 'TDF/3TC/DTG'\n"
        f"- 'Zidovudine + Lamivudine + Nevirapine' -> 'AZT/3TC/NVP'\n"
        f"Input: '{raw_text}'\n"
        f"Return ONLY the standardized string. If unreadable or not a regimen, return 'UNKNOWN'."
    )
    
    try:
        # Using generate_response from AI Service
        response = await gemini_service.generate_response(prompt)
        cleaned = response.strip().replace("\n", "").replace("`", "")
        return cleaned if cleaned != "UNKNOWN" else raw_text
    except Exception as e:
        logger.error(f"Regimen normalization failed: {e}")
        return raw_text