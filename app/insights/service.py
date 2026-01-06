"""
Insights Service
Orchestrates calculation of financial insights from Xero data.
"""

import logging
from typing import Any, Optional

from app.insights.cash_calculators import (
    CashRunwayCalculator,
    CashPressureCalculator,
)
from app.insights.trend_analyzer import TrendAnalyzer
from app.insights.profitability_calculator import ProfitabilityCalculator
from app.insights.indicators_calculator import (
    LeadingIndicatorsCalculator,
    UpcomingCommitmentsCalculator,
)

logger = logging.getLogger(__name__)


class InsightsService:
    """
    Service for calculating financial insights.
    
    Takes raw data from XeroDataFetcher and returns calculated insights
    for cash runway, trends, and leading indicators.
    """
    
    @staticmethod
    def calculate_cash_runway(
        executive_summary_current: dict[str, Any]
    ) -> dict[str, Any]:
        """
        Calculate cash runway metrics.
        
        Args:
            executive_summary_current: Current month Executive Summary data
        
        Returns:
            Dictionary with cash runway metrics
        """
        cash_position = executive_summary_current.get("cash_position", 0.0)
        cash_spent = executive_summary_current.get("cash_spent", 0.0)
        cash_received = executive_summary_current.get("cash_received", 0.0)
        
        return CashRunwayCalculator.calculate(
            cash_position=cash_position,
            cash_spent=cash_spent,
            cash_received=cash_received,
        )
    
    @staticmethod
    def calculate_trends(
        executive_summary_current: dict[str, Any],
        executive_summary_history: list[dict[str, Any]]
    ) -> dict[str, Any]:
        """
        Calculate trend analysis metrics.
        
        Args:
            executive_summary_current: Current month Executive Summary
            executive_summary_history: Historical months (oldest to newest)
        
        Returns:
            Dictionary with trend metrics
        """
        return TrendAnalyzer.calculate(
            executive_summary_current=executive_summary_current,
            executive_summary_history=executive_summary_history,
        )
    
    @staticmethod
    def calculate_leading_indicators(
        receivables: dict[str, Any],
        payables: dict[str, Any],
        executive_summary_current: dict[str, Any],
        executive_summary_history: list[dict[str, Any]]
    ) -> dict[str, Any]:
        """
        Calculate leading indicators of cash stress.
        
        Args:
            receivables: Receivables data from XeroDataFetcher
            payables: Payables data from XeroDataFetcher
            executive_summary_current: Current month Executive Summary
            executive_summary_history: Historical months
        
        Returns:
            Dictionary with leading indicator metrics
        """
        return LeadingIndicatorsCalculator.calculate(
            receivables=receivables,
            payables=payables,
            executive_summary_current=executive_summary_current,
            executive_summary_history=executive_summary_history,
        )
    
    @staticmethod
    def calculate_cash_pressure(
        cash_runway: dict[str, Any],
        trends: dict[str, Any]
    ) -> dict[str, Any]:
        """
        Calculate cash pressure status.
        
        Args:
            cash_runway: Cash runway metrics
            trends: Trend analysis metrics
        
        Returns:
            Dictionary with cash pressure status
        """
        return CashPressureCalculator.calculate(
            runway_months=cash_runway.get("runway_months"),
            runway_status=cash_runway.get("status"),
            revenue_volatility=trends.get("revenue_volatility"),
            cash_position=cash_runway.get("current_cash"),
        )
    
    @staticmethod
    def calculate_profitability(
        profit_loss_data: Optional[dict[str, Any]],
        executive_summary_current: dict[str, Any],
        executive_summary_history: list[dict[str, Any]]
    ) -> dict[str, Any]:
        """
        Calculate profitability metrics.
        
        Args:
            profit_loss_data: P&L report data
            executive_summary_current: Current month Executive Summary
            executive_summary_history: Historical months
        
        Returns:
            Dictionary with profitability metrics
        """
        return ProfitabilityCalculator.calculate(
            profit_loss_data=profit_loss_data,
            executive_summary_current=executive_summary_current,
            executive_summary_history=executive_summary_history,
        )
    
    @staticmethod
    def calculate_upcoming_commitments(
        payables: dict[str, Any],
        cash_position: float
    ) -> dict[str, Any]:
        """
        Calculate upcoming cash commitments.
        
        Args:
            payables: Payables data
            cash_position: Current cash balance
        
        Returns:
            Dictionary with upcoming commitments metrics
        """
        return UpcomingCommitmentsCalculator.calculate(
            payables=payables,
            cash_position=cash_position,
        )
    
    @staticmethod
    def calculate_all_insights(
        financial_data: dict[str, Any]
    ) -> dict[str, Any]:
        """
        Calculate all financial insights from raw Xero data.
        
        Args:
            financial_data: Complete data structure from XeroDataFetcher.fetch_all_data()
        
        Returns:
            Dictionary with all calculated insights:
            - cash_runway
            - trends
            - leading_indicators
            - cash_pressure
            - profitability
            - upcoming_commitments
        """
        executive_summary_current = financial_data.get("executive_summary_current", {})
        executive_summary_history = financial_data.get("executive_summary_history", [])
        receivables = financial_data.get("invoices_receivable", {})
        payables = financial_data.get("invoices_payable", {})
        profit_loss = financial_data.get("profit_loss")
        
        cash_runway = InsightsService.calculate_cash_runway(
            executive_summary_current
        )
        
        trends = InsightsService.calculate_trends(
            executive_summary_current,
            executive_summary_history
        )
        
        leading_indicators = InsightsService.calculate_leading_indicators(
            receivables,
            payables,
            executive_summary_current,
            executive_summary_history
        )
        
        cash_pressure = InsightsService.calculate_cash_pressure(
            cash_runway,
            trends
        )
        
        profitability = InsightsService.calculate_profitability(
            profit_loss,
            executive_summary_current,
            executive_summary_history
        )
        
        upcoming_commitments = InsightsService.calculate_upcoming_commitments(
            payables,
            executive_summary_current.get("cash_position", 0.0)
        )
        
        return {
            "cash_runway": cash_runway,
            "trends": trends,
            "leading_indicators": leading_indicators,
            "cash_pressure": cash_pressure,
            "profitability": profitability,
            "upcoming_commitments": upcoming_commitments,
        }

