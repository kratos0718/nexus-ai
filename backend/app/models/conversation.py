"""Conversation and Message ORM models for multi-turn chat history."""

from datetime import datetime, UTC
from sqlalchemy import String, Integer, Text, DateTime, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class Conversation(Base):
    __tablename__ = "conversations"

    id: Mapped[int]          = mapped_column(primary_key=True, autoincrement=True)
    conversation_id: Mapped[str] = mapped_column(String(36), unique=True, index=True)
    user_id: Mapped[int]     = mapped_column(Integer, ForeignKey("users.id"), index=True)
    title: Mapped[str]       = mapped_column(String(500), default="New Conversation")
    document_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(UTC))
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(UTC),
                                                  onupdate=lambda: datetime.now(UTC))

    messages: Mapped[list["Message"]] = relationship("Message", back_populates="conversation",
                                                      order_by="Message.created_at")


class Message(Base):
    __tablename__ = "messages"

    id: Mapped[int]              = mapped_column(primary_key=True, autoincrement=True)
    message_id: Mapped[str]      = mapped_column(String(36), unique=True, index=True)
    conversation_id: Mapped[str] = mapped_column(String(36), ForeignKey("conversations.conversation_id"))
    role: Mapped[str]            = mapped_column(String(20))   # "user" | "assistant"
    content: Mapped[str]         = mapped_column(Text)
    sources: Mapped[str | None]  = mapped_column(Text, nullable=True)  # JSON string
    prompt_tokens: Mapped[int]   = mapped_column(Integer, default=0)
    completion_tokens: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(UTC))

    conversation: Mapped["Conversation"] = relationship("Conversation", back_populates="messages")
