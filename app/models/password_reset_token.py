"""
Password Reset Token Model
Stores password reset tokens for secure password recovery.
"""

import uuid
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, String, Boolean, Index
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.base import Base, UUIDMixin

if TYPE_CHECKING:
    from app.models.user import User


class PasswordResetToken(Base, UUIDMixin):
    """
    Password reset tokens for secure password recovery.
    
    Tokens are single-use and expire after a set time (e.g., 1 hour).
    Once used, the token is marked as used and cannot be reused.
    
    Attributes:
        id: Unique identifier (UUID)
        token_hash: SHA256 hash of the reset token
        user_id: Foreign key to user requesting reset
        is_used: Whether this token has been used
        expires_at: When the token expires
        used_at: When the token was used (if used)
        user: Related user
        created_at: When the token was created
    """
    
    # Token identification
    token_hash: Mapped[str] = mapped_column(
        String(64),
        unique=True,
        nullable=False,
        index=True,
        comment="SHA256 hash of the reset token",
    )
    
    # Foreign key to user
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        nullable=False,
        index=True,
        comment="User requesting password reset",
    )
    
    # Status
    is_used: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        nullable=False,
        index=True,
        comment="Whether this token has been used",
    )
    
    # Timestamps
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        index=True,
        comment="When the token expires",
    )
    
    used_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        comment="When the token was used (if used)",
    )
    
    # Relationships
    user: Mapped["User"] = relationship(
        "User",
        foreign_keys=[user_id],
        lazy="selectin",
    )
    
    # Indexes
    __table_args__ = (
        Index("ix_password_reset_user_expires", "user_id", "expires_at"),
        Index("ix_password_reset_user_used", "user_id", "is_used"),
    )
    
    def __repr__(self) -> str:
        return (
            f"<PasswordResetToken("
            f"id={self.id}, "
            f"user_id={self.user_id}, "
            f"is_used={self.is_used}, "
            f"expires_at={self.expires_at.isoformat() if self.expires_at else 'N/A'})>"
        )

