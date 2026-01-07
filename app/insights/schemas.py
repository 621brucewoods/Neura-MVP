"""
Insights Schemas
Pydantic models for insights API requests and responses.
"""

from typing import Any, Optional
from pydantic import BaseModel, Field, ConfigDict


class CashRunwayMetrics(BaseModel):
    """Cash runway calculation metrics."""
    
    model_config = ConfigDict(extra="allow")
    
    current_cash: float = Field(..., description="Current cash balance")
    monthly_burn_rate: float = Field(..., description="Monthly net burn rate (positive = burning cash)")
    runway_months: Optional[float] = Field(None, description="Cash runway in months (None if profitable or infinite)")
    runway_weeks: Optional[float] = Field(None, description="Cash runway in weeks (None if profitable or infinite)")
    status: str = Field(..., description="Runway status: healthy, warning, critical, negative, or infinite")


class ReceivablesHealth(BaseModel):
    """Receivables health metrics."""
    
    model_config = ConfigDict(extra="allow")
    
    total: float = Field(..., description="Total receivables amount")
    overdue_amount: float = Field(..., description="Total overdue receivables")
    overdue_percentage: float = Field(..., description="Percentage of receivables that are overdue")
    overdue_count: int = Field(..., description="Number of overdue invoices")
    overdue_count_percentage: float = Field(..., description="Percentage of invoices that are overdue")
    avg_days_overdue: float = Field(..., description="Average days overdue")
    timing_risk: str = Field(..., description="Timing risk level: low, medium, or high")
    risk_level: str = Field(..., description="Overall risk level: low, medium, or high")


class PayablesPressure(BaseModel):
    """Payables pressure metrics."""
    
    model_config = ConfigDict(extra="allow")
    
    total: float = Field(..., description="Total payables amount")
    overdue_amount: float = Field(..., description="Total overdue payables")
    overdue_percentage: float = Field(..., description="Percentage of payables that are overdue")
    overdue_count: int = Field(..., description="Number of overdue bills")
    overdue_count_percentage: float = Field(..., description="Percentage of bills that are overdue")
    avg_days_overdue: float = Field(..., description="Average days overdue")
    risk_level: str = Field(..., description="Risk level: low, medium, or high")


class LeadingIndicatorsMetrics(BaseModel):
    """Leading indicators of cash stress."""
    
    model_config = ConfigDict(extra="allow")
    
    receivables_health: ReceivablesHealth = Field(..., description="Receivables health analysis")
    payables_pressure: PayablesPressure = Field(..., description="Payables pressure analysis")
    cash_stress_signals: list[str] = Field(..., description="List of identified cash stress signals")


class CashPressureMetrics(BaseModel):
    """Cash pressure status metrics."""
    
    model_config = ConfigDict(extra="allow")
    
    status: str = Field(..., description="Cash pressure status: GREEN, AMBER, or RED")
    confidence: str = Field(..., description="Confidence level: high, medium, or low")


class ProfitabilityMetrics(BaseModel):
    """Profitability analysis metrics."""
    
    model_config = ConfigDict(extra="allow")
    
    revenue: Optional[float] = Field(None, description="Total revenue")
    cost_of_sales: Optional[float] = Field(None, description="Cost of sales")
    gross_profit: Optional[float] = Field(None, description="Gross profit")
    gross_margin_pct: Optional[float] = Field(None, description="Gross margin percentage")
    expenses: Optional[float] = Field(None, description="Total expenses")
    net_profit: Optional[float] = Field(None, description="Net profit")
    profit_trend: str = Field(..., description="Profit trend: improving, declining, or stable")
    risk_level: str = Field(..., description="Risk level: low, medium, or high")


class UpcomingCommitmentsMetrics(BaseModel):
    """Upcoming cash commitments metrics."""
    
    model_config = ConfigDict(extra="allow")
    
    upcoming_amount: float = Field(..., description="Total amount due in next 30 days")
    upcoming_count: int = Field(..., description="Number of bills due in next 30 days")
    days_ahead: int = Field(..., description="Number of days analyzed")
    large_upcoming_bills: list[dict[str, Any]] = Field(..., description="Large upcoming bills (>= $1000)")
    squeeze_risk: str = Field(..., description="Cash squeeze risk: low, medium, or high")


class Insight(BaseModel):
    """Single financial insight."""
    
    model_config = ConfigDict(extra="allow")
    
    insight_id: str = Field(..., description="Unique identifier for this insight")
    insight_type: str = Field(..., description="Type of insight (cash_runway_risk, upcoming_cash_squeeze, etc.)")
    title: str = Field(..., description="Plain-English headline")
    severity: str = Field(..., description="Severity level: high, medium, or low")
    confidence_level: str = Field(..., description="Confidence level: high, medium, or low")
    summary: str = Field(..., description="1-2 sentence summary of what's happening")
    why_it_matters: str = Field(..., description="Short paragraph explaining why this matters now")
    recommended_actions: list[str] = Field(..., description="List of actionable steps (3-5 items)")
    supporting_numbers: list[dict[str, Any]] = Field(default_factory=list, description="Key numbers supporting the insight")
    data_notes: Optional[str] = Field(None, description="Optional notes about data quality or limitations")
    generated_at: str = Field(..., description="ISO timestamp when insight was generated")
    is_acknowledged: bool = Field(default=False, description="Whether insight has been acknowledged")
    is_acknowledged: bool = Field(default=False, description="Whether insight has been acknowledged")
    is_marked_done: bool = Field(default=False, description="Whether insight has been marked as done")


class InsightUpdate(BaseModel):
    """Body for updating an insight's state."""
    
    model_config = ConfigDict(extra="forbid")
    
    is_acknowledged: Optional[bool] = Field(None, description="Set acknowledgment status")
    is_marked_done: Optional[bool] = Field(None, description="Set completion status")


class InsightsResponse(BaseModel):
    """Complete insights response."""
    
    cash_runway: CashRunwayMetrics = Field(..., description="Cash runway calculations")
    leading_indicators: LeadingIndicatorsMetrics = Field(..., description="Leading indicators")
    cash_pressure: CashPressureMetrics = Field(..., description="Cash pressure status")
    profitability: ProfitabilityMetrics = Field(..., description="Profitability analysis")
    upcoming_commitments: UpcomingCommitmentsMetrics = Field(..., description="Upcoming cash commitments")
    insights: list[Insight] = Field(default_factory=list, description="Paginated list of insights")
    pagination: dict[str, int] = Field(
        default_factory=lambda: {"total": 0, "page": 1, "limit": 20, "total_pages": 0},
        description="Pagination metadata"
    )
    calculated_at: str = Field(..., description="ISO timestamp when insights were calculated")
    raw_data_summary: dict[str, Any] = Field(..., description="Compact summary of raw financial data for AI analysis")

