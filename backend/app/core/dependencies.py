"""
Reusable FastAPI dependencies.

get_current_user  — extracts and validates JWT from Authorization header
                    raises 401 if token missing/invalid/expired
rate_limit_user   — enforces per-user request rate limit (uses Redis)
"""

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.core.database import get_db
from app.core.security import decode_token
from app.models.user import User

bearer_scheme = HTTPBearer()


async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme),
    db: AsyncSession = Depends(get_db),
) -> User:
    """
    Dependency — add to any endpoint to require authentication:
        async def my_endpoint(user: User = Depends(get_current_user)):

    Validates Bearer token from Authorization header.
    Returns the User object or raises 401.
    """
    token = credentials.credentials
    payload = decode_token(token)

    if not payload or payload.get("type") != "access":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    user_id = int(payload["sub"])
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()

    if not user or not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found or deactivated",
            headers={"WWW-Authenticate": "Bearer"},
        )

    return user


async def rate_limit_user(
    current_user: User = Depends(get_current_user),
) -> User:
    """
    Dependency — enforces per-user rate limit then returns the user.
    Drop-in replacement for get_current_user on endpoints that need rate limiting.

        async def my_endpoint(user: User = Depends(rate_limit_user)):
    """
    from app.core.rate_limit import check_rate_limit, RateLimitExceeded
    try:
        check_rate_limit(f"user:{current_user.id}")
    except RateLimitExceeded as e:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"Rate limit exceeded. Try again in {e.retry_after}s.",
            headers={"Retry-After": str(e.retry_after)},
        )
    return current_user
