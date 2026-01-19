"""
User Model - Supabase Auth Integration
Links Supabase auth.users to application user records.
"""

from datetime import datetime, timezone
from typing import TYPE_CHECKING, Optional
from uuid import UUID

from sqlalchemy import String, Boolean, Index, Enum
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from enum import Enum as PyEnum

from app.database.base import Base, TimestampMixin, UUIDMixin

if TYPE_CHECKING:
    from app.models.organization import Organization
    from app.models.insight_feedback import InsightFeedback


class UserRole(str, PyEnum):
    """User role enumeration."""
    USER = "user"
    ADMIN = "admin"


class User(Base, UUIDMixin, TimestampMixin):
    """
    User model linked to Supabase auth.users.
    
    This model represents application users in our database.
    Authentication is handled entirely by Supabase.
    We only store business logic data here.
    
    Attributes:
        id: Application user ID (UUID)
        supabase_user_id: Supabase auth.users.id (links to Supabase)
        email: User email (synced from Supabase)
        is_active: Account active status
        role: User role (user or admin)
        organization: Related organization (1:1)
    """
    
    # Supabase link (required, unique, indexed)
    # Note: nullable=True temporarily for migration compatibility
    # Should be nullable=False after all users are migrated to Supabase
    supabase_user_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        unique=True,
        nullable=True,  # Temporarily nullable for migration
        index=True,
        comment="Supabase auth.users.id - links to Supabase authentication"
    )
    
    # Email (synced from Supabase, but stored for quick access)
    email: Mapped[str] = mapped_column(
        String(255),
        unique=True,
        nullable=False,
        index=True,
        comment="User email (synced from Supabase auth.users)"
    )
    
    # Account status
    is_active: Mapped[bool] = mapped_column(
        Boolean,
        default=True,
        nullable=False,
        index=True,
        comment="Whether the user account is active"
    )
    
    # Role (business logic)
    role: Mapped[UserRole] = mapped_column(
        Enum(UserRole, name="user_role_enum", create_type=True, values_callable=lambda x: [e.value for e in x]),
        default=UserRole.USER,
        nullable=False,
        comment="User role: user or admin"
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
    
    # Indexes
    __table_args__ = (
        Index("ix_users_supabase_id", "supabase_user_id"),
        Index("ix_users_email_active", "email", "is_active"),
    )
    
    def is_admin(self) -> bool:
        """Check if user has admin role."""
        return self.role == UserRole.ADMIN
    
    def __repr__(self) -> str:
        return (
            f"<User(id={self.id}, email={self.email!r}, "
            f"is_active={self.is_active}, role={self.role.value})>"
        )
