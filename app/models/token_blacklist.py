"""
Token Blacklist Model
Stores revoked JWT tokens until they expire.
"""

import uuid
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, String, Index
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.base import Base, UUIDMixin

if TYPE_CHECKING:
    from app.models.user import User


class TokenBlacklist(Base, UUIDMixin):
    """
    Blacklist for revoked JWT tokens.
    
    Tokens are stored here when revoked (logout, security breach, etc.)
    and checked during token validation to prevent reuse.
    
    Attributes:
        id: Unique identifier (UUID)
        jti: JWT ID (unique token identifier)
        token_hash: SHA256 hash of the full token
        user_id: Foreign key to user who owns the token
        revoked_at: When the token was revoked
        expires_at: When the token naturally expires (from JWT exp claim)
        user: Related user
    """
    
    # Token identification
    jti: Mapped[str] = mapped_column(
        String(255),
        unique=True,
        nullable=False,
        index=True,
        comment="JWT ID (unique token identifier)",
    )
    
    token_hash: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        index=True,
        comment="SHA256 hash of the full token for quick lookup",
    )
    
    # Foreign key to user
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        nullable=False,
        index=True,
        comment="User who owns this token",
    )
    
    # Timestamps
    revoked_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        comment="When the token was revoked",
    )
    
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        index=True,
        comment="When the token naturally expires (from JWT exp claim)",
    )
    
    # Relationships
    user: Mapped["User"] = relationship(
        "User",
        foreign_keys=[user_id],
        lazy="selectin",
    )
    
    # Indexes
    __table_args__ = (
        Index("ix_token_blacklist_user_expires", "user_id", "expires_at"),
        Index("ix_token_blacklist_expires", "expires_at"),
    )
    
    def __repr__(self) -> str:
        return (
            f"<TokenBlacklist("
            f"id={self.id}, "
            f"jti={self.jti[:8]}..., "
            f"user_id={self.user_id}, "
            f"expires_at={self.expires_at.isoformat() if self.expires_at else 'N/A'})>"
        )

