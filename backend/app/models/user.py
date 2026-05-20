"""User ORM model."""

from datetime import datetime, UTC
from sqlalchemy import String, Boolean, DateTime
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class User(Base):
    __tablename__ = "users"

    id: Mapped[int]          = mapped_column(primary_key=True, autoincrement=True)
    email: Mapped[str]       = mapped_column(String(255), unique=True, index=True)
    full_name: Mapped[str]   = mapped_column(String(255))
    hashed_password: Mapped[str] = mapped_column(String(255))
    is_active: Mapped[bool]  = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(UTC))

    def __repr__(self) -> str:
        return f"<User {self.email}>"
