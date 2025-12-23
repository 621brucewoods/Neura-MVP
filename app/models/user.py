"""
User Model
Represents authenticated users in the system.
"""

import uuid
from typing import TYPE_CHECKING, Optional

from sqlalchemy import String, Boolean, Index
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.base import Base, TimestampMixin, UUIDMixin

if TYPE_CHECKING:
    from app.models.organization import Organization


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
    
    # Relationships
    organization: Mapped[Optional["Organization"]] = relationship(
        "Organization",
        back_populates="user",
        uselist=False,
        lazy="selectin",
        cascade="all, delete-orphan",
    )
    
    # Table configuration
    __table_args__ = (
        Index("ix_users_email_active", "email", "is_active"),
    )
    
    def __repr__(self) -> str:
        return f"<User(id={self.id}, email={self.email!r}, is_active={self.is_active})>"

