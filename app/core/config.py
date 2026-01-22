from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import field_validator


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""
    
    # Application
    APP_NAME: str = "Mira AI"
    APP_VERSION: str = "0.1.0"
    DEBUG: bool = False
    
    # Logging
    LOG_LEVEL: str = "INFO"
    
    # Database
    DATABASE_URL: str = "postgresql+asyncpg://user:password@localhost:5432/mira_db"
    
    # Redis
    REDIS_URL: str = "redis://localhost:6379/0"
    
    # Celery Broker
    CELERY_BROKER_URL: str = "amqp://guest:guest@localhost:5672//"
    
    # JWT
    JWT_SECRET_KEY: str = "your-secret-key-change-in-production"
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 15
    REFRESH_TOKEN_EXPIRE_DAYS: int = 7
    
    # Security
    CORS_ORIGINS: str = "http://localhost:3000"
    MAX_LOGIN_ATTEMPTS: int = 5
    LOCKOUT_DURATION_MINUTES: int = 15
    REQUIRE_EMAIL_VERIFICATION: bool = True

     # Email
    SMTP_HOST: str = "localhost"
    SMTP_PORT: int = 587
    SMTP_USER: str = ""
    SMTP_PASSWORD: str = ""
    SMTP_TLS: bool = True
    SMTP_FROM_EMAIL: str = "noreply@mira.ai"
    SMTP_FROM_NAME: str = "Mira AI"

    # Frontend

    FRONTEND_URL: str = "https://miraproject.online"
    
    # Gemini AI
    GEMINI_API_KEY: str = ""
    GEMINI_MODEL: str = "gemini-2.5-flash"

    # Storage (MinIO/S3)
    S3_ENDPOINT: str = "http://localhost:9000"
    S3_ACCESS_KEY: str = "minioadmin"
    S3_SECRET_KEY: str = "minioadmin"
    S3_BUCKET_NAME: str = "mira-uploads"
    S3_REGION: str = "us-east-1"

    # LiveKit (Voice AI)
    LIVEKIT_URL: str = "wss://your-livekit-server.livekit.cloud"
    LIVEKIT_API_KEY: str = ""
    LIVEKIT_API_SECRET: str = ""
    GOOGLE_API_KEY: str = ""
    
    # Dev only: Automatically dispatch agent when creating a room
    ENABLE_AGENT_DISPATCH: bool = True
    
    # LiveKit SIP (Phone Calls via Twilio)
    LIVEKIT_SIP_ENABLED: bool = False
    LIVEKIT_SIP_URI: str = ""
    
    # Twilio SIP Credentials
    TWILIO_ACCOUNT_SID: str = ""
    TWILIO_AUTH_TOKEN: str = ""
    TWILIO_SIP_DOMAIN: str = "" 
    TWILIO_PHONE_NUMBER: str = "" 
    TWILIO_SIP_TRUNK_ID: str = ""  

    # Reminder Rate Limits
    MAX_SMS_PER_DAY_PER_ORG: int = 500
    MAX_VOICE_CALLS_PER_DAY_PER_ORG: int = 50
    REMINDER_RATE_LIMIT_KEY_PREFIX: str = "reminder_limit"


    @property
    def cors_origins_list(self) -> list[str]:
        """Parse CORS origins from comma-separated string."""
        return [origin.strip() for origin in self.CORS_ORIGINS.split(",")]
    

    
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="ignore",
    )


settings = Settings()

