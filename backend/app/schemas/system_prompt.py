from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


class SystemPromptCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    description: Optional[str] = Field(None, max_length=500)
    content: str = Field(..., min_length=10, max_length=4000)


class SystemPromptUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=100)
    description: Optional[str] = Field(None, max_length=500)
    content: Optional[str] = Field(None, min_length=10, max_length=4000)


class SystemPromptResponse(BaseModel):
    id: int
    name: str
    description: Optional[str]
    content: str
    created_at: datetime
    model_config = {"from_attributes": True}
