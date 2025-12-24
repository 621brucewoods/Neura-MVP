"""
Insights Module
Calculates financial insights from Xero data for cash runway analysis.
"""

from app.insights.calculator import (
    CashRunwayCalculator,
    TrendAnalyzer,
    LeadingIndicatorsCalculator,
)
from app.insights.service import InsightsService

__all__ = [
    "CashRunwayCalculator",
    "TrendAnalyzer",
    "LeadingIndicatorsCalculator",
    "InsightsService",
]

