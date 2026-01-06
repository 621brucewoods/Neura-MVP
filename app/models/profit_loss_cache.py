"""
Profit Loss Cache Model
Stores cached P&L report data for specific date ranges.
"""

import uuid
from datetime import date, datetime, timezone
from typing import TYPE_CHECKING, Optional, Any

from sqlalchemy import Date, ForeignKey, DateTime, UniqueConstraint, Index
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.base import Base, TimestampMixin, UUIDMixin

if TYPE_CHECKING:
    from app.models.organization import Organization


class ProfitLossCache(Base, UUIDMixin, TimestampMixin):
    """
    Cache for Profit & Loss report data.
    
    Stores P&L data for specific date ranges to minimize API calls.
    Uses exact match caching: only returns cache if start_date and end_date match exactly.
    
    Attributes:
        id: Unique identifier (UUID)
        organization_id: Foreign key to organization (tenant)
        start_date: P&L period start date
        end_date: P&L period end date
        profit_loss_data: Cached P&L report data (JSON)
        fetched_at: When data was fetched from Xero
        expires_at: When cache expires (TTL-based)
        organization: Related organization
        created_at: Timestamp of creation
        updated_at: Timestamp of last update
    """
    
    # Foreign key to organization (tenant isolation)
    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    
    # Date range for P&L period
    start_date: Mapped[date] = mapped_column(
        Date,
        nullable=False,
        comment="P&L period start date",
    )
    
    end_date: Mapped[date] = mapped_column(
        Date,
        nullable=False,
        comment="P&L period end date",
    )
    
    # Cached P&L data
    profit_loss_data: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        nullable=False,
        comment="Cached Profit & Loss report data",
    )
    
    # Cache timing
    fetched_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        comment="When data was fetched from Xero",
    )
    
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        comment="When cache expires (fetched_at + TTL)",
        index=True,
    )
    
    # Relationships
    organization: Mapped["Organization"] = relationship(
        "Organization",
        back_populates="profit_loss_caches",
        lazy="selectin",
    )
    
    # Constraints and indexes
    __table_args__ = (
        UniqueConstraint("organization_id", "start_date", "end_date", name="uq_profit_loss_cache_org_dates"),
        Index("ix_profit_loss_cache_org_dates", "organization_id", "start_date", "end_date"),
        Index("ix_profit_loss_cache_expires_at", "expires_at"),
    )
    
    def __repr__(self) -> str:
        return f"<ProfitLossCache(id={self.id}, org_id={self.organization_id}, {self.start_date} to {self.end_date})>"
    
    @property
    def is_expired(self) -> bool:
        """Check if cache has expired."""
        return datetime.now(timezone.utc) > self.expires_at
    
    @property
    def is_fresh(self) -> bool:
        """Check if cache is still fresh (not expired)."""
        return not self.is_expired

