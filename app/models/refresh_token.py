"""
Refresh Token Model
Tracks active refresh tokens for rotation and revocation.
"""

import uuid
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, String, Index, ForeignKey
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.base import Base, UUIDMixin

if TYPE_CHECKING:
    from app.models.user import User


class RefreshToken(Base, UUIDMixin):
    """
    Tracks active refresh tokens for rotation and revocation.
    
    When a refresh token is used, it's marked as used and a new one is issued.
    This prevents token reuse and allows revocation of all tokens for a user.
    
    Attributes:
        id: Unique identifier (UUID)
        token_hash: SHA256 hash of the refresh token
        user_id: Foreign key to user who owns the token
        is_used: Whether this token has been used (one-time use)
        issued_at: When the token was issued
        expires_at: When the token expires
        used_at: When the token was used (if used)
        user: Related user
    """
    
    # Token identification
    token_hash: Mapped[str] = mapped_column(
        String(64),
        unique=True,
        nullable=False,
        index=True,
        comment="SHA256 hash of the refresh token",
    )
    
    # Foreign key to user
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="User who owns this token",
    )
    
    # Status
    is_used: Mapped[bool] = mapped_column(
        default=False,
        nullable=False,
        index=True,
        comment="Whether this token has been used (one-time use)",
    )
    
    # Timestamps
    issued_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        index=True,
        comment="When the token was issued",
    )
    
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
        Index("ix_refresh_token_user_expires", "user_id", "expires_at"),
        Index("ix_refresh_token_user_used", "user_id", "is_used"),
    )
    
    def __repr__(self) -> str:
        return (
            f"<RefreshToken("
            f"id={self.id}, "
            f"user_id={self.user_id}, "
            f"is_used={self.is_used}, "
            f"expires_at={self.expires_at.isoformat() if self.expires_at else 'N/A'})>"
        )

