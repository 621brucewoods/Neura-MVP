"""
Organization Model
Represents a business entity in the multi-tenant system.
"""

import uuid
from typing import TYPE_CHECKING, Optional

from sqlalchemy import String, ForeignKey, Index
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.base import Base, TimestampMixin, UUIDMixin

if TYPE_CHECKING:
    from app.models.user import User
    from app.models.xero_token import XeroToken
    from app.models.financial_cache import FinancialCache
    from app.models.calculated_metrics import CalculatedMetrics
    from app.models.executive_summary_cache import ExecutiveSummaryCache


class Organization(Base, UUIDMixin, TimestampMixin):
    """
    Organization model for multi-tenancy.
    
    Each user belongs to exactly one organization.
    All financial data is scoped to an organization.
    
    Attributes:
        id: Unique identifier (UUID)
        name: Organization/business name
        user_id: Foreign key to the owning user
        user: Related user (1:1 relationship)
        xero_token: Related Xero OAuth tokens
        financial_cache: Cached financial data
        calculated_metrics: Calculated financial metrics
        created_at: Timestamp of creation
        updated_at: Timestamp of last update
    
    Relationships:
        - One Organization belongs to One User (1:1)
        - One Organization has One XeroToken (1:1)
        - One Organization has One FinancialCache (1:1)
        - One Organization has One CalculatedMetrics (1:1)
        - One Organization has Many ExecutiveSummaryCache (1:N, one per month)
    
    Note:
        This is the tenant isolation boundary.
        All data queries should filter by organization_id.
    """
    
    # Organization details
    name: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
    )
    
    # Foreign keys
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        unique=True,
        nullable=False,
    )
    
    # Relationships - Parent
    user: Mapped["User"] = relationship(
        "User",
        back_populates="organization",
        lazy="selectin",
    )
    
    # Relationships - Children (all use cascade delete)
    xero_token: Mapped[Optional["XeroToken"]] = relationship(
        "XeroToken",
        back_populates="organization",
        uselist=False,
        lazy="selectin",
        cascade="all, delete-orphan",
    )
    
    financial_cache: Mapped[Optional["FinancialCache"]] = relationship(
        "FinancialCache",
        back_populates="organization",
        uselist=False,
        lazy="selectin",
        cascade="all, delete-orphan",
    )
    
    calculated_metrics: Mapped[Optional["CalculatedMetrics"]] = relationship(
        "CalculatedMetrics",
        back_populates="organization",
        uselist=False,
        lazy="selectin",
        cascade="all, delete-orphan",
    )
    
    executive_summary_cache: Mapped[list["ExecutiveSummaryCache"]] = relationship(
        "ExecutiveSummaryCache",
        back_populates="organization",
        lazy="selectin",
        cascade="all, delete-orphan",
    )
    
    # Table configuration
    __table_args__ = (
        Index("ix_organizations_user_id", "user_id"),
    )
    
    def __repr__(self) -> str:
        return f"<Organization(id={self.id}, name={self.name!r})>"
    
    @property
    def has_xero_connection(self) -> bool:
        """Check if organization has an active Xero connection."""
        return self.xero_token is not None and self.xero_token.is_active

