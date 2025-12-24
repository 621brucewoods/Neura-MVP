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


class TrendMetrics(BaseModel):
    """Trend analysis metrics."""
    
    model_config = ConfigDict(extra="allow")
    
    expense_acceleration: Optional[float] = Field(None, description="Month-over-month % change in expenses")
    revenue_volatility: Optional[float] = Field(None, description="Revenue volatility (coefficient of variation)")
    net_cash_flow_trend: str = Field(..., description="Net cash flow trend: improving, declining, or stable")
    monthly_changes: list[dict[str, Any]] = Field(..., description="Month-over-month changes")


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


class InsightsResponse(BaseModel):
    """Complete insights response."""
    
    cash_runway: CashRunwayMetrics = Field(..., description="Cash runway calculations")
    trends: TrendMetrics = Field(..., description="Trend analysis")
    leading_indicators: LeadingIndicatorsMetrics = Field(..., description="Leading indicators")
    calculated_at: str = Field(..., description="ISO timestamp when insights were calculated")

