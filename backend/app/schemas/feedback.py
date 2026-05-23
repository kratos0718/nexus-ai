from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel


class FeedbackCreate(BaseModel):
    conversation_id: Optional[str] = None
    question: str
    answer: str
    rating: Literal[1, -1]
    comment: Optional[str] = None
    retrieval_mode: str = "standard"


class FeedbackResponse(BaseModel):
    id: int
    rating: int
    created_at: datetime
    model_config = {"from_attributes": True}


class FeedbackStats(BaseModel):
    total: int
    positive: int
    negative: int
    positive_rate: float
