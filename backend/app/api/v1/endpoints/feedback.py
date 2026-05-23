import json
from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.core.database import get_db
from app.core.dependencies import get_current_user
from app.models.user import User
from app.models.feedback import MessageFeedback
from app.schemas.feedback import FeedbackCreate, FeedbackResponse, FeedbackStats

router = APIRouter()


@router.post("/", response_model=FeedbackResponse, status_code=201)
async def submit_feedback(
    body: FeedbackCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    fb = MessageFeedback(
        user_id=current_user.id,
        conversation_id=body.conversation_id,
        question=body.question[:2000],
        answer=body.answer[:5000],
        rating=body.rating,
        comment=body.comment,
        retrieval_mode=body.retrieval_mode,
    )
    db.add(fb)
    await db.commit()
    await db.refresh(fb)
    return fb


@router.get("/stats", response_model=FeedbackStats)
async def feedback_stats(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = await db.execute(
        select(MessageFeedback).where(MessageFeedback.user_id == current_user.id)
    )
    rows = result.scalars().all()
    total = len(rows)
    positive = sum(1 for r in rows if r.rating == 1)
    negative = total - positive
    return FeedbackStats(
        total=total,
        positive=positive,
        negative=negative,
        positive_rate=round(positive / total * 100, 1) if total > 0 else 0.0,
    )


@router.get("/export")
async def export_feedback(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Export all rated responses as JSONL in OpenAI fine-tuning format.
    Each line is a JSON object with messages[] + rating + retrieval_mode.
    """
    result = await db.execute(
        select(MessageFeedback)
        .where(MessageFeedback.user_id == current_user.id)
        .order_by(MessageFeedback.created_at)
    )
    rows = result.scalars().all()

    def _generate():
        for fb in rows:
            record = {
                "messages": [
                    {"role": "user", "content": fb.question},
                    {"role": "assistant", "content": fb.answer},
                ],
                "rating": fb.rating,
                "retrieval_mode": fb.retrieval_mode,
            }
            yield json.dumps(record) + "\n"

    return StreamingResponse(
        _generate(),
        media_type="application/x-ndjson",
        headers={"Content-Disposition": "attachment; filename=feedback_export.jsonl"},
    )
