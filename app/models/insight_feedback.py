"""
Insight Feedback Model
Stores user feedback on insights (helpful/not helpful with optional comments).
"""

import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Optional

from sqlalchemy import String, Text, ForeignKey, DateTime, Boolean, Index
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.base import Base, TimestampMixin, UUIDMixin

if TYPE_CHECKING:
    from app.models.organization import Organization
    from app.models.user import User


class InsightFeedback(Base, UUIDMixin, TimestampMixin):
    """
    User feedback on insights.
    
    Stores whether users found insights helpful, with optional comments.
    Supports upsert: one feedback record per user per insight.
    
    Attributes:
        id: Unique identifier (UUID)
        organization_id: Foreign key to organization (tenant)
        user_id: Foreign key to user who provided feedback
        insight_id: Reference to insight (UUID string from insight.insight_id)
        insight_type: Type of insight (snapshot at time of feedback)
        insight_title: Title of insight (snapshot at time of feedback)
        is_helpful: Whether user found insight helpful (true) or not helpful (false)
        comment: Optional user comment (max 500 chars)
        created_at: When feedback was created
        updated_at: When feedback was last updated
        organization: Related organization
        user: User who provided feedback
    """
    
    # Foreign key to organization (tenant isolation)
    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    
    # Foreign key to user
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    
    # Insight reference (using insight_id string, not foreign key)
    insight_id: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        index=True,
        comment="Reference to insight (insight.insight_id)",
    )
    
    # Insight snapshot (captured at time of feedback)
    insight_type: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        index=True,
        comment="Type of insight (snapshot)",
    )
    
    insight_title: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        comment="Title of insight (snapshot)",
    )
    
    # Feedback data
    is_helpful: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        index=True,
        comment="Whether insight was helpful (true) or not helpful (false)",
    )
    
    comment: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True,
        comment="Optional user comment (max 500 chars)",
    )
    
    # Relationships
    organization: Mapped["Organization"] = relationship(
        "Organization",
        back_populates="insight_feedback",
        lazy="selectin",
    )
    
    user: Mapped["User"] = relationship(
        "User",
        back_populates="insight_feedback",
        lazy="selectin",
    )
    
    # Indexes
    __table_args__ = (
        Index("ix_insight_feedback_organization_id", "organization_id"),
        Index("ix_insight_feedback_user_id", "user_id"),
        Index("ix_insight_feedback_insight_id", "insight_id"),
        Index("ix_insight_feedback_insight_type", "insight_type"),
        Index("ix_insight_feedback_is_helpful", "is_helpful"),
        Index("ix_insight_feedback_user_insight", "user_id", "insight_id", unique=True),
    )
    
    def __repr__(self) -> str:
        return f"<InsightFeedback(id={self.id}, insight_id={self.insight_id}, is_helpful={self.is_helpful})>"

