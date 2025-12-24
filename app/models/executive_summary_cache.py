"""
Executive Summary Cache Model
Stores historical Executive Summary reports (one per month).
Historical months never expire as they represent complete, unchanging data.
"""

import uuid
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import TYPE_CHECKING, Optional, Any

from sqlalchemy import Date, ForeignKey, DateTime, Numeric, UniqueConstraint, Index
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.base import Base, TimestampMixin, UUIDMixin

if TYPE_CHECKING:
    from app.models.organization import Organization


class ExecutiveSummaryCache(Base, UUIDMixin, TimestampMixin):
    """
    Cache for historical Executive Summary reports.
    
    Each record represents one complete month of data.
    Historical months never expire (complete months don't change).
    
    Attributes:
        id: Unique identifier (UUID)
        organization_id: Foreign key to organization (tenant)
        report_date: Month-end date (e.g., 2025-11-30) - identifies the month
        cash_position: Closing bank balance for the month
        cash_spent: Total cash spent in the month
        cash_received: Total cash received in the month
        operating_expenses: Total operating expenses for the month
        raw_data: Full report structure (for debugging/analysis)
        fetched_at: When data was fetched from Xero
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
    
    # Month identifier (month-end date, e.g., 2025-11-30)
    report_date: Mapped[date] = mapped_column(
        Date,
        nullable=False,
        comment="Month-end date identifying the month (e.g., 2025-11-30)",
    )
    
    # Cached Executive Summary data
    cash_position: Mapped[Decimal] = mapped_column(
        Numeric(15, 2),
        nullable=False,
        comment="Closing bank balance for the month",
    )
    
    cash_spent: Mapped[Decimal] = mapped_column(
        Numeric(15, 2),
        nullable=False,
        comment="Total cash spent in the month",
    )
    
    cash_received: Mapped[Decimal] = mapped_column(
        Numeric(15, 2),
        nullable=False,
        comment="Total cash received in the month",
    )
    
    operating_expenses: Mapped[Decimal] = mapped_column(
        Numeric(15, 2),
        nullable=False,
        comment="Total operating expenses for the month",
    )
    
    raw_data: Mapped[Optional[dict[str, Any]]] = mapped_column(
        JSONB,
        nullable=True,
        comment="Full Executive Summary report structure (for debugging)",
    )
    
    # Metadata
    fetched_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        comment="When data was fetched from Xero",
    )
    
    # Relationships
    organization: Mapped["Organization"] = relationship(
        "Organization",
        back_populates="executive_summary_cache",
        lazy="selectin",
    )
    
    # Constraints and indexes
    __table_args__ = (
        UniqueConstraint(
            "organization_id",
            "report_date",
            name="uq_exec_summary_org_date",
        ),
        Index(
            "ix_exec_summary_org_date",
            "organization_id",
            "report_date",
        ),
    )
    
    def __repr__(self) -> str:
        return (
            f"<ExecutiveSummaryCache("
            f"id={self.id}, "
            f"org_id={self.organization_id}, "
            f"report_date={self.report_date}"
            f")>"
        )
    
    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary format matching XeroDataFetcher output."""
        return {
            "cash_position": float(self.cash_position),
            "cash_spent": float(self.cash_spent),
            "cash_received": float(self.cash_received),
            "operating_expenses": float(self.operating_expenses),
            "report_date": self.report_date.isoformat(),
            "raw_data": self.raw_data,
        }

