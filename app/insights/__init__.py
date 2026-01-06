"""
Insights Module
Calculates financial insights from Xero data for cash runway analysis.
"""

from app.insights.cash_calculators import CashRunwayCalculator
from app.insights.trend_analyzer import TrendAnalyzer
from app.insights.indicators_calculator import LeadingIndicatorsCalculator
from app.insights.service import InsightsService

__all__ = [
    "CashRunwayCalculator",
    "TrendAnalyzer",
    "LeadingIndicatorsCalculator",
    "InsightsService",
]

