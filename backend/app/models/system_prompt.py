from datetime import datetime
from sqlalchemy import String, Integer, Text, DateTime, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class SystemPrompt(Base):
    __tablename__ = "system_prompts"

    id: Mapped[int]              = mapped_column(primary_key=True, autoincrement=True)
    user_id: Mapped[int]         = mapped_column(Integer, ForeignKey("users.id"), index=True)
    name: Mapped[str]            = mapped_column(String(100))
    description: Mapped[str | None] = mapped_column(String(500), nullable=True)
    content: Mapped[str]         = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
