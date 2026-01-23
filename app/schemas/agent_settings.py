from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field


# Gemini voices: Puck, Charon, Kore, Fenrir, Aoede
VOICE_STYLES = Literal["professional", "casual", "warm", "energetic", "calm"]

# Mapping from user-friendly names to Gemini voice names
VOICE_STYLE_TO_GEMINI = {
    "professional": "Charon",   
    "casual": "Puck",           
    "warm": "Kore",             
    "energetic": "Fenrir",     
    "calm": "Aoede",            
}
DEFAULT_AGENT_NAME = "MIRA"
DEFAULT_VOICE_STYLE = "professional"
DEFAULT_LANGUAGE = "en"
DEFAULT_GREETING = "Hello, I am MIRA, your AI healthcare assistant. How can I help you today?"


class AgentSettingsRequest(BaseModel):
    """Request to update AI agent settings."""
    enabled: Optional[bool] = True
    agent_name: Optional[str] = Field(None, max_length=50)
    greeting: Optional[str] = Field(None, max_length=500)
    voice_style: Optional[VOICE_STYLES] = None
    language: Optional[str] = Field(None, max_length=10)
    
    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "agent_name": "MIRA",
                "greeting": "Hello! I'm MIRA, your healthcare assistant.",
                "voice_style": "professional",
            }
        }
    )


class AgentSettingsResponse(BaseModel):
    """AI agent settings response."""
    enabled: bool = True
    agent_name: str = DEFAULT_AGENT_NAME
    greeting: str = DEFAULT_GREETING
    voice_style: str = DEFAULT_VOICE_STYLE
    language: str = DEFAULT_LANGUAGE
    
    # Available options for the frontend
    available_voice_styles: list[str] = list(VOICE_STYLE_TO_GEMINI.keys())


class AgentSettingsResetResponse(BaseModel):
    """Response after resetting agent settings."""
    success: bool
    message: str
    settings: AgentSettingsResponse
