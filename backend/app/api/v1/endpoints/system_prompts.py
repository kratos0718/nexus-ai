"""
System prompt CRUD endpoints.

Users create named instruction sets ("You are a medical terminology expert") and
select one per chat session. The chosen prompt replaces the default RAG system message.
"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.core.database import get_db
from app.core.dependencies import get_current_user
from app.models.user import User
from app.models.system_prompt import SystemPrompt
from app.schemas.system_prompt import SystemPromptCreate, SystemPromptUpdate, SystemPromptResponse

router = APIRouter()


async def _get_owned(db: AsyncSession, prompt_id: int, user_id: int) -> SystemPrompt:
    result = await db.execute(
        select(SystemPrompt).where(
            SystemPrompt.id == prompt_id,
            SystemPrompt.user_id == user_id,
        )
    )
    sp = result.scalar_one_or_none()
    if not sp:
        raise HTTPException(status_code=404, detail="System prompt not found")
    return sp


@router.post("/", response_model=SystemPromptResponse, status_code=201)
async def create_prompt(
    body: SystemPromptCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    sp = SystemPrompt(
        user_id=current_user.id,
        name=body.name,
        description=body.description,
        content=body.content,
    )
    db.add(sp)
    await db.commit()
    await db.refresh(sp)
    return sp


@router.get("/", response_model=list[SystemPromptResponse])
async def list_prompts(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = await db.execute(
        select(SystemPrompt)
        .where(SystemPrompt.user_id == current_user.id)
        .order_by(SystemPrompt.created_at.desc())
    )
    return result.scalars().all()


@router.get("/{prompt_id}", response_model=SystemPromptResponse)
async def get_prompt(
    prompt_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return await _get_owned(db, prompt_id, current_user.id)


@router.put("/{prompt_id}", response_model=SystemPromptResponse)
async def update_prompt(
    prompt_id: int,
    body: SystemPromptUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    sp = await _get_owned(db, prompt_id, current_user.id)
    if body.name is not None:
        sp.name = body.name
    if body.description is not None:
        sp.description = body.description
    if body.content is not None:
        sp.content = body.content
    await db.commit()
    await db.refresh(sp)
    return sp


@router.delete("/{prompt_id}", status_code=204)
async def delete_prompt(
    prompt_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    sp = await _get_owned(db, prompt_id, current_user.id)
    await db.delete(sp)
    await db.commit()
