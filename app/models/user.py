"""
User Model
Represents authenticated users in the system.
"""

import uuid
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Optional

from sqlalchemy import String, Boolean, Index, Integer, DateTime
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.base import Base, TimestampMixin, UUIDMixin

if TYPE_CHECKING:
    from app.models.organization import Organization
    from app.models.insight_feedback import InsightFeedback


class User(Base, UUIDMixin, TimestampMixin):
    """
    User model for authentication and identity.
    
    Attributes:
        id: Unique identifier (UUID)
        email: User's email address (unique, used for login)
        password_hash: Bcrypt hashed password
        is_active: Whether the user account is active
        is_verified: Whether email has been verified
        organization: Related organization (1:1 relationship)
        created_at: Timestamp of creation
        updated_at: Timestamp of last update
    
    Relationships:
        - One User has One Organization (1:1)
    
    Indexes:
        - email (unique)
        - is_active (for filtering active users)
    """
    
    # Core fields
    email: Mapped[str] = mapped_column(
        String(255),
        unique=True,
        nullable=False,
        index=True,
    )
    
    password_hash: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
    )
    
    # Account status
    is_active: Mapped[bool] = mapped_column(
        Boolean,
        default=True,
        nullable=False,
    )
    
    is_verified: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        nullable=False,
    )
    
    # Account lockout fields
    failed_login_attempts: Mapped[int] = mapped_column(
        Integer,
        default=0,
        nullable=False,
        comment="Number of consecutive failed login attempts",
    )
    
    locked_until: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        index=True,
        comment="Account locked until this timestamp (null if not locked)",
    )
    
    last_login_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        comment="Last successful login timestamp",
    )
    
    # Relationships
    organization: Mapped[Optional["Organization"]] = relationship(
        "Organization",
        back_populates="user",
        uselist=False,
        lazy="selectin",
        cascade="all, delete-orphan",
    )
    
    insight_feedback: Mapped[list["InsightFeedback"]] = relationship(
        "InsightFeedback",
        back_populates="user",
        lazy="selectin",
        cascade="all, delete-orphan",
    )
    
    # Table configuration
    __table_args__ = (
        Index("ix_users_email_active", "email", "is_active"),
    )
    
    def is_locked(self) -> bool:
        """Check if account is currently locked."""
        if not self.locked_until:
            return False
        return datetime.now(timezone.utc) < self.locked_until
    
    def __repr__(self) -> str:
        return f"<User(id={self.id}, email={self.email!r}, is_active={self.is_active})>"

