"""
Conversation management endpoints.

POST   /conversations/            — create a new conversation
GET    /conversations/            — list all conversations for current user
GET    /conversations/{id}        — get conversation with full message history
DELETE /conversations/{id}        — delete conversation
"""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.dependencies import get_current_user
from app.models.user import User
from app.services.rag_service import rag_service
from app.schemas.conversation import (
    ConversationCreate,
    ConversationRename,
    ConversationResponse,
    ConversationDetailResponse,
    MessageResponse,
)

router = APIRouter()


@router.post("/", response_model=ConversationResponse, status_code=status.HTTP_201_CREATED)
async def create_conversation(
    body: ConversationCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    conv = await rag_service.create_conversation(
        db=db,
        user_id=current_user.id,
        title=body.title,
        document_id=body.document_id,
    )
    return ConversationResponse(
        conversation_id=conv.conversation_id,
        title=conv.title,
        document_id=conv.document_id,
        created_at=conv.created_at,
        updated_at=conv.updated_at,
        message_count=0,
    )


@router.get("/", response_model=list[ConversationResponse])
async def list_conversations(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    convs = await rag_service.list_conversations(db, current_user.id)
    return [
        ConversationResponse(
            conversation_id=c.conversation_id,
            title=c.title,
            document_id=c.document_id,
            created_at=c.created_at,
            updated_at=c.updated_at,
            message_count=len(c.messages),
        )
        for c in convs
    ]


@router.get("/{conversation_id}", response_model=ConversationDetailResponse)
async def get_conversation(
    conversation_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    conv = await rag_service.get_conversation(db, conversation_id, current_user.id)
    if not conv:
        raise HTTPException(status_code=404, detail="Conversation not found")

    return ConversationDetailResponse(
        conversation_id=conv.conversation_id,
        title=conv.title,
        document_id=conv.document_id,
        created_at=conv.created_at,
        updated_at=conv.updated_at,
        message_count=len(conv.messages),
        messages=[MessageResponse.model_validate(m) for m in conv.messages],
    )


@router.patch("/{conversation_id}/title", response_model=ConversationResponse)
async def rename_conversation(
    conversation_id: str,
    body: ConversationRename,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Rename a conversation."""
    conv = await rag_service.get_conversation(db, conversation_id, current_user.id)
    if not conv:
        raise HTTPException(status_code=404, detail="Conversation not found")
    conv.title = body.title.strip()[:80]
    await db.commit()
    await db.refresh(conv)
    return ConversationResponse(
        conversation_id=conv.conversation_id,
        title=conv.title,
        document_id=conv.document_id,
        created_at=conv.created_at,
        updated_at=conv.updated_at,
        message_count=len(conv.messages),
    )


@router.delete("/{conversation_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_conversation(
    conversation_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    deleted = await rag_service.delete_conversation(db, conversation_id, current_user.id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Conversation not found")
