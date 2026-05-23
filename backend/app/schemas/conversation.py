"""Pydantic schemas for conversation and message endpoints."""

from datetime import datetime
from typing import Optional

from pydantic import BaseModel


class ConversationCreate(BaseModel):
    title: str = "New Conversation"
    document_id: Optional[str] = None


class ConversationRename(BaseModel):
    title: str


class MessageResponse(BaseModel):
    message_id: str
    role: str
    content: str
    prompt_tokens: int
    completion_tokens: int
    created_at: datetime

    model_config = {"from_attributes": True}


class ConversationResponse(BaseModel):
    conversation_id: str
    title: str
    document_id: Optional[str]
    created_at: datetime
    updated_at: datetime
    message_count: int = 0

    model_config = {"from_attributes": True}


class ConversationDetailResponse(ConversationResponse):
    messages: list[MessageResponse] = []
