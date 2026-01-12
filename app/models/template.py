import uuid
from sqlalchemy import String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base_model import BaseModel

class EmailTemplate(BaseModel):
    """Email template model for database-driven emails."""
    __tablename__ = "email_templates"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    slug: Mapped[str] = mapped_column(String(50), unique=True, index=True)
    subject: Mapped[str] = mapped_column(String(255))
    html_body: Mapped[str] = mapped_column(Text)
    text_body: Mapped[str | None] = mapped_column(Text)
    variables: Mapped[dict | None] = mapped_column(JSONB)