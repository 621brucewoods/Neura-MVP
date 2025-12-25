"""
Email Verification Token Model
Stores email verification tokens for account verification.
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


class EmailVerificationToken(Base, UUIDMixin):
    """
    Email verification tokens for account verification.
    
    Tokens are single-use and expire after a set time (e.g., 24 hours).
    Once used, the token is marked as used and the user's email is verified.
    
    Attributes:
        id: Unique identifier (UUID)
        token_hash: SHA256 hash of the verification token
        user_id: Foreign key to user to verify
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
        comment="SHA256 hash of the verification token",
    )
    
    # Foreign key to user
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        nullable=False,
        unique=True,
        index=True,
        comment="User to verify (one active token per user)",
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
        Index("ix_email_verification_user_expires", "user_id", "expires_at"),
        Index("ix_email_verification_user_used", "user_id", "is_used"),
    )
    
    def __repr__(self) -> str:
        return (
            f"<EmailVerificationToken("
            f"id={self.id}, "
            f"user_id={self.user_id}, "
            f"is_used={self.is_used}, "
            f"expires_at={self.expires_at.isoformat() if self.expires_at else 'N/A'})>"
        )

