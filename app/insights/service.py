"""
Insights Service
Orchestrates calculation of financial insights from Xero data.
"""

import logging
from typing import Any

from app.insights.calculator import (
    CashRunwayCalculator,
    TrendAnalyzer,
    LeadingIndicatorsCalculator,
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
        """
        executive_summary_current = financial_data.get("executive_summary_current", {})
        executive_summary_history = financial_data.get("executive_summary_history", [])
        receivables = financial_data.get("invoices_receivable", {})
        payables = financial_data.get("invoices_payable", {})
        
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
        
        return {
            "cash_runway": cash_runway,
            "trends": trends,
            "leading_indicators": leading_indicators,
        }

