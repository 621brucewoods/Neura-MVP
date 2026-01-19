"""
Monthly P&L Cache Model
Stores cached monthly P&L data for historical analysis.

Uses month-based caching with different TTLs:
- Historical months (>1 month old): Never expires
- Last month: 24 hour TTL (late entries possible)
- Current month: 1 hour TTL (data changes frequently)
"""

import uuid
from datetime import date, datetime, timezone, timedelta
from typing import TYPE_CHECKING, Any, Optional
from decimal import Decimal

from sqlalchemy import String, Integer, ForeignKey, DateTime, UniqueConstraint, Index
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.base import Base, TimestampMixin, UUIDMixin

if TYPE_CHECKING:
    from app.models.organization import Organization


class MonthlyPnLCache(Base, UUIDMixin, TimestampMixin):
    """
    Cache for monthly Profit & Loss data.
    
    Stores P&L summaries by month for historical trend analysis.
    Uses month_key (YYYY-MM) for easy lookup.
    
    Attributes:
        id: Unique identifier (UUID)
        organization_id: Foreign key to organization
        month_key: Month identifier in YYYY-MM format (e.g., "2025-01")
        year: Year (e.g., 2025)
        month: Month (1-12)
        revenue: Total revenue for the month
        cost_of_sales: Total COGS for the month
        expenses: Total operating expenses
        net_profit: Calculated net profit (revenue - cogs - expenses)
        raw_data: Full P&L report data (JSON) for detailed analysis
        fetched_at: When data was fetched from Xero
        expires_at: When cache expires (None = never expires)
    """
    
    __tablename__ = "monthly_pnl_cache"
    
    # Foreign key to organization (tenant isolation)
    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    
    # Month identifier
    month_key: Mapped[str] = mapped_column(
        String(7),  # "YYYY-MM"
        nullable=False,
        comment="Month identifier in YYYY-MM format",
    )
    
    year: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        comment="Year (e.g., 2025)",
    )
    
    month: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        comment="Month (1-12)",
    )
    
    # Extracted P&L totals (for quick access without parsing raw_data)
    revenue: Mapped[Optional[Decimal]] = mapped_column(
        nullable=True,
        comment="Total revenue for the month",
    )
    
    cost_of_sales: Mapped[Optional[Decimal]] = mapped_column(
        nullable=True,
        comment="Total COGS for the month",
    )
    
    expenses: Mapped[Optional[Decimal]] = mapped_column(
        nullable=True,
        comment="Total operating expenses",
    )
    
    net_profit: Mapped[Optional[Decimal]] = mapped_column(
        nullable=True,
        comment="Net profit (revenue - cogs - expenses)",
    )
    
    # Full P&L data for detailed analysis
    raw_data: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        nullable=False,
        default=dict,
        comment="Full P&L report data from Xero",
    )
    
    # Cache timing
    fetched_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        comment="When data was fetched from Xero",
    )
    
    expires_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,  # None = never expires (historical months)
        comment="When cache expires (None = never)",
        index=True,
    )
    
    # Relationships
    organization: Mapped["Organization"] = relationship(
        "Organization",
        back_populates="monthly_pnl_caches",
        lazy="selectin",
    )
    
    # Constraints and indexes
    __table_args__ = (
        UniqueConstraint("organization_id", "month_key", name="uq_monthly_pnl_cache_org_month"),
        Index("ix_monthly_pnl_cache_org_month", "organization_id", "month_key"),
        Index("ix_monthly_pnl_cache_org_year_month", "organization_id", "year", "month"),
    )
    
    def __repr__(self) -> str:
        return f"<MonthlyPnLCache(id={self.id}, org_id={self.organization_id}, {self.month_key})>"
    
    @property
    def is_expired(self) -> bool:
        """Check if cache has expired."""
        if self.expires_at is None:
            return False  # Never expires
        return datetime.now(timezone.utc) > self.expires_at
    
    @property
    def is_fresh(self) -> bool:
        """Check if cache is still fresh (not expired)."""
        return not self.is_expired
    
    @property
    def is_current_month(self) -> bool:
        """Check if this is the current month."""
        today = date.today()
        return self.year == today.year and self.month == today.month
    
    @property
    def is_last_month(self) -> bool:
        """Check if this is last month."""
        today = date.today()
        last_month = (today.replace(day=1) - timedelta(days=1))
        return self.year == last_month.year and self.month == last_month.month
    
    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for API responses."""
        return {
            "month_key": self.month_key,
            "year": self.year,
            "month": self.month,
            "revenue": float(self.revenue) if self.revenue else None,
            "cost_of_sales": float(self.cost_of_sales) if self.cost_of_sales else None,
            "expenses": float(self.expenses) if self.expenses else None,
            "net_profit": float(self.net_profit) if self.net_profit else None,
            "fetched_at": self.fetched_at.isoformat() if self.fetched_at else None,
            "is_fresh": self.is_fresh,
        }
