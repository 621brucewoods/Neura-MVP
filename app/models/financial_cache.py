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
    
    Attributes:
        id: Unique identifier (UUID)
        organization_id: Foreign key to organization (tenant)
        bank_accounts: Bank account balances and details (JSON)
        bank_transactions: Recent bank transactions (JSON)
        invoices_receivable: Accounts receivable invoices (JSON)
        invoices_payable: Accounts payable invoices (JSON)
        profit_loss_data: Profit & Loss report data (JSON)
        fetched_at: When data was fetched from Xero
        expires_at: When cache should be considered stale
        organization: Related organization
        created_at: Timestamp of creation
        updated_at: Timestamp of last update
    
    Cache Strategy:
        - TTL-based invalidation (configurable, default 15 min)
        - Manual invalidation on force refresh
        - Separate columns for each data type allows partial updates
    
    Data Structure (JSON):
        bank_accounts: [
            {"id": "...", "name": "...", "balance": 1234.56, "currency": "USD"}
        ]
        bank_transactions: [
            {"id": "...", "date": "...", "amount": 100.00, "type": "SPEND"}
        ]
        invoices_receivable: [
            {"id": "...", "contact": "...", "amount": 500.00, "due_date": "..."}
        ]
        invoices_payable: [
            {"id": "...", "contact": "...", "amount": 300.00, "due_date": "..."}
        ]
        profit_loss_data: {
            "periods": [...],
            "revenue": [...],
            "expenses": [...]
        }
    """
    
    # Foreign key to organization (tenant isolation)
    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        unique=True,
        nullable=False,
    )
    
    # Cached data (JSONB for efficient querying)
    bank_accounts: Mapped[Optional[dict[str, Any]]] = mapped_column(
        JSONB,
        nullable=True,
        default=None,
        comment="Bank account balances and details",
    )
    
    bank_transactions: Mapped[Optional[dict[str, Any]]] = mapped_column(
        JSONB,
        nullable=True,
        default=None,
        comment="Recent bank transactions",
    )
    
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
        """Check if cache has expired."""
        return datetime.now(timezone.utc) > self.expires_at
    
    @property
    def is_fresh(self) -> bool:
        """Check if cache is still fresh (not expired)."""
        return not self.is_expired
    
    @property
    def has_data(self) -> bool:
        """Check if any data has been cached."""
        return any([
            self.bank_accounts,
            self.bank_transactions,
            self.invoices_receivable,
            self.invoices_payable,
            self.profit_loss_data,
        ])

