"""
Login Attempt Model
Tracks login attempts for rate limiting and account lockout.
"""

import uuid
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, Boolean, String, Index
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.base import Base, UUIDMixin

if TYPE_CHECKING:
    from app.models.user import User


class LoginAttempt(Base, UUIDMixin):
    """
    Tracks login attempts for rate limiting and account lockout.
    
    Records each login attempt (successful or failed) with IP address
    and timestamp. Used to detect brute force attacks and lock accounts.
    
    Attributes:
        id: Unique identifier (UUID)
        email: Email address used in login attempt
        user_id: Foreign key to user (if user exists)
        ip_address: IP address of the login attempt
        success: Whether the login was successful
        attempted_at: When the attempt was made
        user: Related user (if user exists)
    """
    
    # Login attempt details
    email: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        index=True,
        comment="Email address used in login attempt",
    )
    
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        nullable=True,
        index=True,
        comment="User ID if user exists (null for non-existent users)",
    )
    
    ip_address: Mapped[str] = mapped_column(
        String(45),
        nullable=False,
        index=True,
        comment="IP address of the login attempt (supports IPv6)",
    )
    
    success: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        index=True,
        comment="Whether the login was successful",
    )
    
    attempted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        index=True,
        comment="When the attempt was made",
    )
    
    # Relationships
    user: Mapped["User | None"] = relationship(
        "User",
        foreign_keys=[user_id],
        lazy="selectin",
    )
    
    # Indexes
    __table_args__ = (
        Index("ix_login_attempt_email_time", "email", "attempted_at"),
        Index("ix_login_attempt_ip_time", "ip_address", "attempted_at"),
        Index("ix_login_attempt_user_time", "user_id", "attempted_at"),
    )
    
    def __repr__(self) -> str:
        return (
            f"<LoginAttempt("
            f"id={self.id}, "
            f"email={self.email}, "
            f"success={self.success}, "
            f"attempted_at={self.attempted_at.isoformat() if self.attempted_at else 'N/A'})>"
        )

