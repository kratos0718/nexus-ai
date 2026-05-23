from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class MessageFeedback(Base):
    __tablename__ = "message_feedback"

    id: Mapped[int]              = mapped_column(primary_key=True, autoincrement=True)
    user_id: Mapped[int]         = mapped_column(Integer, ForeignKey("users.id"), index=True)
    conversation_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    question: Mapped[str]        = mapped_column(Text)
    answer: Mapped[str]          = mapped_column(Text)
    rating: Mapped[int]          = mapped_column(Integer)   # 1 = positive, -1 = negative
    comment: Mapped[str | None]  = mapped_column(Text, nullable=True)
    retrieval_mode: Mapped[str]  = mapped_column(String(20), default="standard")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
