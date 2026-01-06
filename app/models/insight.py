"""
Insight Model
Stores generated financial insights and tracks user engagement.
"""

import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Optional

from sqlalchemy import String, Text, ForeignKey, DateTime, Boolean, Index, JSON
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.base import Base, TimestampMixin, UUIDMixin

if TYPE_CHECKING:
    from app.models.organization import Organization
    from app.models.user import User


class Insight(Base, UUIDMixin, TimestampMixin):
    """
    Generated financial insight with engagement tracking.
    
    Stores insights generated from financial metrics and tracks
    whether users have acknowledged or marked them as done.
    
    Attributes:
        id: Unique identifier (UUID)
        organization_id: Foreign key to organization (tenant)
        insight_type: Type of insight (cash_runway_risk, upcoming_cash_squeeze, etc.)
        title: Plain-English headline
        severity: Severity level (high, medium, low)
        confidence_level: Confidence level (high, medium, low)
        summary: 1-2 sentence summary
        why_it_matters: Short paragraph explaining why this matters
        recommended_actions: JSON array of actionable steps
        supporting_numbers: JSON array of key numbers
        data_notes: Optional notes about data quality
        is_acknowledged: Whether user has acknowledged this insight
        is_marked_done: Whether user has marked this as done
        acknowledged_at: When insight was acknowledged
        marked_done_at: When insight was marked as done
        acknowledged_by_user_id: User who acknowledged (if applicable)
        marked_done_by_user_id: User who marked as done (if applicable)
        generated_at: When insight was generated
        organization: Related organization
        acknowledged_by: User who acknowledged
        marked_done_by: User who marked as done
    """
    
    # Foreign key to organization (tenant isolation)
    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    
    # Insight identification
    insight_id: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        unique=True,
        index=True,
        comment="Unique insight identifier (UUID string from generator)",
    )
    
    insight_type: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        index=True,
        comment="Type of insight (cash_runway_risk, upcoming_cash_squeeze, etc.)",
    )
    
    # Insight content
    title: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        comment="Plain-English headline",
    )
    
    severity: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        index=True,
        comment="Severity level: high, medium, or low",
    )
    
    confidence_level: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        comment="Confidence level: high, medium, or low",
    )
    
    summary: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        comment="1-2 sentence summary of what's happening",
    )
    
    why_it_matters: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        comment="Short paragraph explaining why this matters now",
    )
    
    recommended_actions: Mapped[list[str]] = mapped_column(
        JSON,
        nullable=False,
        comment="List of actionable steps (3-5 items)",
    )
    
    supporting_numbers: Mapped[Optional[list[dict]]] = mapped_column(
        JSON,
        nullable=True,
        comment="Key numbers supporting the insight",
    )
    
    data_notes: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True,
        comment="Optional notes about data quality or limitations",
    )
    
    # Engagement tracking
    is_acknowledged: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        nullable=False,
        index=True,
        comment="Whether user has acknowledged this insight",
    )
    
    is_marked_done: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        nullable=False,
        index=True,
        comment="Whether user has marked this as done",
    )
    
    acknowledged_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        comment="When insight was acknowledged",
    )
    
    marked_done_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        comment="When insight was marked as done",
    )
    
    acknowledged_by_user_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        comment="User who acknowledged this insight",
    )
    
    marked_done_by_user_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        comment="User who marked this insight as done",
    )
    
    # Metadata
    generated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        comment="When insight was generated",
    )
    
    # Relationships
    organization: Mapped["Organization"] = relationship(
        "Organization",
        back_populates="insights",
        lazy="selectin",
    )
    
    acknowledged_by: Mapped[Optional["User"]] = relationship(
        "User",
        foreign_keys=[acknowledged_by_user_id],
        lazy="selectin",
    )
    
    marked_done_by: Mapped[Optional["User"]] = relationship(
        "User",
        foreign_keys=[marked_done_by_user_id],
        lazy="selectin",
    )
    
    # Indexes
    __table_args__ = (
        Index("ix_insights_organization_id", "organization_id"),
        Index("ix_insights_insight_id", "insight_id"),
        Index("ix_insights_insight_type", "insight_type"),
        Index("ix_insights_severity", "severity"),
        Index("ix_insights_generated_at", "generated_at"),
        Index("ix_insights_acknowledged", "is_acknowledged"),
        Index("ix_insights_marked_done", "is_marked_done"),
        Index("ix_insights_org_insight_id", "organization_id", "insight_id"),
    )
    
    def __repr__(self) -> str:
        return f"<Insight(id={self.id}, type={self.insight_type}, severity={self.severity})>"

