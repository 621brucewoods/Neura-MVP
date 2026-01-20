"""
Calculated Metrics Model
Stores pre-calculated financial metrics and AI-generated insights.
"""

import uuid
from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import TYPE_CHECKING, Optional

from sqlalchemy import String, Text, ForeignKey, DateTime, Numeric, Index
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.base import Base, TimestampMixin, UUIDMixin

if TYPE_CHECKING:
    from app.models.organization import Organization


class RiskLevel(str, Enum):
    """Risk level classification for cash flow health."""
    
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class CalculatedMetrics(Base, UUIDMixin, TimestampMixin):
    """
    Pre-calculated financial metrics and AI insights.
    
    Stores calculated values to avoid recomputation on every request.
    Updated when financial cache is refreshed.
    
    Attributes:
        id: Unique identifier (UUID)
        organization_id: Foreign key to organization (tenant)
        
        Financial Metrics:
            total_cash: Sum of all bank account balances
            total_receivables: Outstanding accounts receivable
            total_payables: Outstanding accounts payable
            burn_rate_monthly: Average monthly net loss (3-month avg)
            runway_months: Months until cash runs out
            revenue_monthly: Average monthly revenue
            expenses_monthly: Average monthly expenses
            net_income_monthly: Average monthly net income
            expense_trend_percent: Month-over-month expense change %
            revenue_trend_percent: Month-over-month revenue change %
        
        AI Insights:
            ai_summary: Plain English health summary (2 sentences)
            risk_level: Risk classification (low/medium/high/critical)
            action_item: Recommended next action
        
        Metadata:
            calculated_at: When metrics were calculated
            data_period_start: Start of data period used
            data_period_end: End of data period used
        
        organization: Related organization
        created_at: Timestamp of creation
        updated_at: Timestamp of last update
    """
    
    # Foreign key to organization (tenant isolation)
    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        unique=True,
        nullable=False,
    )
    
    # ========================================
    # Cash Position
    # ========================================
    total_cash: Mapped[Optional[Decimal]] = mapped_column(
        Numeric(15, 2),
        nullable=True,
        comment="Sum of all bank account balances",
    )
    
    total_receivables: Mapped[Optional[Decimal]] = mapped_column(
        Numeric(15, 2),
        nullable=True,
        comment="Outstanding accounts receivable (AR)",
    )
    
    total_payables: Mapped[Optional[Decimal]] = mapped_column(
        Numeric(15, 2),
        nullable=True,
        comment="Outstanding accounts payable (AP)",
    )
    
    # ========================================
    # Burn Rate & Runway
    # ========================================
    burn_rate_monthly: Mapped[Optional[Decimal]] = mapped_column(
        Numeric(15, 2),
        nullable=True,
        comment="Average monthly net loss (positive = burning cash)",
    )
    
    runway_months: Mapped[Optional[Decimal]] = mapped_column(
        Numeric(6, 2),
        nullable=True,
        comment="Months until cash runs out (null if profitable)",
    )
    
    # ========================================
    # Income Statement Metrics
    # ========================================
    revenue_monthly: Mapped[Optional[Decimal]] = mapped_column(
        Numeric(15, 2),
        nullable=True,
        comment="Average monthly revenue",
    )
    
    expenses_monthly: Mapped[Optional[Decimal]] = mapped_column(
        Numeric(15, 2),
        nullable=True,
        comment="Average monthly expenses",
    )
    
    net_income_monthly: Mapped[Optional[Decimal]] = mapped_column(
        Numeric(15, 2),
        nullable=True,
        comment="Average monthly net income (negative = loss)",
    )
    
    # ========================================
    # Trends
    # ========================================
    expense_trend_percent: Mapped[Optional[Decimal]] = mapped_column(
        Numeric(6, 2),
        nullable=True,
        comment="Month-over-month expense change percentage",
    )
    
    revenue_trend_percent: Mapped[Optional[Decimal]] = mapped_column(
        Numeric(6, 2),
        nullable=True,
        comment="Month-over-month revenue change percentage",
    )
    
    # ========================================
    # AI-Generated Insights
    # ========================================
    ai_summary: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True,
        comment="AI-generated 2-sentence health summary",
    )
    
    risk_level: Mapped[Optional[str]] = mapped_column(
        String(20),
        nullable=True,
        comment="Risk classification: low, medium, high, critical",
    )
    
    action_item: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True,
        comment="AI-generated recommended action",
    )
    
    # ========================================
    # Metadata
    # ========================================
    calculated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        comment="When metrics were calculated",
    )
    
    data_period_start: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        comment="Start of data period used for calculations",
    )
    
    data_period_end: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        comment="End of data period used for calculations",
    )
    
    metrics_payload: Mapped[Optional[dict]] = mapped_column(
        JSONB,
        nullable=True,
        comment="Full JSON payload of calculated metrics for dashboard display",
    )
    
    health_score_payload: Mapped[Optional[dict]] = mapped_column(
        JSONB,
        nullable=True,
        comment="Full JSON payload of Business Health Score (0-100)",
    )
    
    # Relationships
    organization: Mapped["Organization"] = relationship(
        "Organization",
        back_populates="calculated_metrics",
        lazy="selectin",
    )
    
    # Indexes
    __table_args__ = (
        Index("ix_calculated_metrics_organization_id", "organization_id"),
        Index("ix_calculated_metrics_risk_level", "risk_level"),
    )
    
    def __repr__(self) -> str:
        return f"<CalculatedMetrics(id={self.id}, org_id={self.organization_id}, risk={self.risk_level})>"
    
    @property
    def is_profitable(self) -> bool:
        """Check if business is profitable (positive net income)."""
        if self.net_income_monthly is None:
            return False
        return self.net_income_monthly > 0
    
    @property
    def has_runway(self) -> bool:
        """Check if runway has been calculated."""
        return self.runway_months is not None
    
    @property
    def runway_status(self) -> str:
        """Get human-readable runway status."""
        if self.is_profitable:
            return "Profitable"
        if self.runway_months is None:
            return "Unknown"
        if self.runway_months <= 0:
            return "Out of cash"
        if self.runway_months < 3:
            return "Critical"
        if self.runway_months < 6:
            return "Low"
        if self.runway_months < 12:
            return "Moderate"
        return "Healthy"

