"""
Financial Cache Model
Stores raw financial data fetched from Xero.
"""

import uuid
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Optional, Any

from sqlalchemy import ForeignKey, DateTime, Index
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.base import Base, TimestampMixin, UUIDMixin

if TYPE_CHECKING:
    from app.models.organization import Organization


class FinancialCache(Base, UUIDMixin, TimestampMixin):
    """
    Cache for raw Xero financial data.
    
    Stores fetched data to minimize API calls and improve performance.
    Data is refreshed based on TTL (default: 15 minutes).
    
    Note: Historical Executive Summary data is stored in ExecutiveSummaryCache
    (one record per month, never expires). Only current month is cached here.
    
    Attributes:
        id: Unique identifier (UUID)
        organization_id: Foreign key to organization (tenant)
        executive_summary_current: Current month Executive Summary (incomplete month)
        executive_summary_current_fetched_at: When current Executive Summary was fetched
        executive_summary_current_expires_at: When current Executive Summary expires
        invoices_receivable: Accounts receivable invoices (JSON)
        invoices_payable: Accounts payable invoices (JSON)
        profit_loss_data: Profit & Loss report data (JSON)
        fetched_at: When receivables/payables/P&L were fetched
        expires_at: When receivables/payables/P&L cache expires
        organization: Related organization
        created_at: Timestamp of creation
        updated_at: Timestamp of last update
    
    Cache Strategy:
        - TTL-based invalidation (configurable, default 15 min)
        - Manual invalidation on force refresh
        - Separate columns for each data type allows partial updates
        - Historical Executive Summary stored separately (never expires)
    """
    
    # Foreign key to organization (tenant isolation)
    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        unique=True,
        nullable=False,
    )
    
    # Current month Executive Summary (incomplete month, changes daily)
    executive_summary_current: Mapped[Optional[dict[str, Any]]] = mapped_column(
        JSONB,
        nullable=True,
        default=None,
        comment="Current month Executive Summary data (incomplete month)",
    )
    
    executive_summary_current_fetched_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        comment="When current Executive Summary was fetched",
    )
    
    executive_summary_current_expires_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        comment="When current Executive Summary expires",
    )
    
    # Cached data (JSONB for efficient querying)
    invoices_receivable: Mapped[Optional[dict[str, Any]]] = mapped_column(
        JSONB,
        nullable=True,
        default=None,
        comment="Accounts receivable (AR) invoices",
    )
    
    invoices_payable: Mapped[Optional[dict[str, Any]]] = mapped_column(
        JSONB,
        nullable=True,
        default=None,
        comment="Accounts payable (AP) invoices",
    )
    
    profit_loss_data: Mapped[Optional[dict[str, Any]]] = mapped_column(
        JSONB,
        nullable=True,
        default=None,
        comment="Profit & Loss report data",
    )
    
    # Cache timing (for receivables/payables/P&L)
    fetched_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        comment="When receivables/payables/P&L were fetched",
    )
    
    expires_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        comment="When receivables/payables/P&L cache expires",
    )
    
    # Relationships
    organization: Mapped["Organization"] = relationship(
        "Organization",
        back_populates="financial_cache",
        lazy="selectin",
    )
    
    # Indexes
    __table_args__ = (
        Index("ix_financial_caches_organization_id", "organization_id"),
        Index("ix_financial_caches_expires_at", "expires_at"),
    )
    
    def __repr__(self) -> str:
        return f"<FinancialCache(id={self.id}, org_id={self.organization_id}, expires_at={self.expires_at})>"
    
    @property
    def is_expired(self) -> bool:
        """Check if receivables/payables/P&L cache has expired."""
        if self.expires_at is None:
            return True
        return datetime.now(timezone.utc) > self.expires_at
    
    @property
    def is_fresh(self) -> bool:
        """Check if receivables/payables/P&L cache is still fresh (not expired)."""
        return not self.is_expired
    
    @property
    def is_executive_summary_current_fresh(self) -> bool:
        """Check if current Executive Summary cache is fresh."""
        if self.executive_summary_current_expires_at is None:
            return False
        return datetime.now(timezone.utc) <= self.executive_summary_current_expires_at
    
    @property
    def has_data(self) -> bool:
        """Check if any data has been cached."""
        return any([
            self.executive_summary_current,
            self.invoices_receivable,
            self.invoices_payable,
            self.profit_loss_data,
        ])

