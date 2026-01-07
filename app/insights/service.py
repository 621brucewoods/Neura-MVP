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
from app.insights.profitability_calculator import ProfitabilityCalculator
from app.insights.indicators_calculator import (
    LeadingIndicatorsCalculator,
    UpcomingCommitmentsCalculator,
)
from app.integrations.xero.data_fetcher import XeroDataFetcher

logger = logging.getLogger(__name__)


class InsightsService:
    """
    Service for calculating financial insights.
    
    Takes raw data from XeroDataFetcher and returns calculated insights
    for cash runway, leading indicators, and cash pressure.
    """
    
    @staticmethod
    def _extract_cash_from_balance_sheet(balance_sheet: dict[str, Any], fetcher: XeroDataFetcher) -> float:
        """
        Extract cash position from Balance Sheet.
        
        Args:
            balance_sheet: Balance Sheet data
            fetcher: XeroDataFetcher instance with extraction method
        
        Returns:
            Cash position as float (defaults to 0.0 if not found)
        """
        cash = fetcher.extract_cash_from_balance_sheet(balance_sheet)
        return float(cash) if cash is not None else 0.0
    
    @staticmethod
    def calculate_cash_runway(
        balance_sheet_current: dict[str, Any],
        balance_sheet_prior: dict[str, Any],
        fetcher: XeroDataFetcher
    ) -> dict[str, Any]:
        """
        Calculate cash runway metrics from Balance Sheets.
        
        Args:
            balance_sheet_current: Current Balance Sheet data
            balance_sheet_prior: Prior Balance Sheet data
            fetcher: XeroDataFetcher instance
        
        Returns:
            Dictionary with cash runway metrics
        """
        cash_position = InsightsService._extract_cash_from_balance_sheet(balance_sheet_current, fetcher)
        cash_position_prior = InsightsService._extract_cash_from_balance_sheet(balance_sheet_prior, fetcher)
        
        # Calculate net cash change (current - prior)
        net_cash_change = cash_position - cash_position_prior
        
        # Approximate cash_received and cash_spent from net change
        cash_received = max(0.0, net_cash_change)
        cash_spent = abs(min(0.0, net_cash_change))
        
        return CashRunwayCalculator.calculate(
            cash_position=cash_position,
            cash_spent=cash_spent,
            cash_received=cash_received,
        )
    
    @staticmethod
    def calculate_leading_indicators(
        receivables: dict[str, Any],
        payables: dict[str, Any],
        balance_sheet_current: dict[str, Any],
        balance_sheet_prior: dict[str, Any],
        fetcher: XeroDataFetcher
    ) -> dict[str, Any]:
        """
        Calculate leading indicators of cash stress.
        
        Args:
            receivables: Receivables data from XeroDataFetcher
            payables: Payables data from XeroDataFetcher
            balance_sheet_current: Current Balance Sheet data
            balance_sheet_prior: Prior Balance Sheet data
            fetcher: XeroDataFetcher instance
        
        Returns:
            Dictionary with leading indicator metrics
        """
        from datetime import date
        
        cash_position_current = InsightsService._extract_cash_from_balance_sheet(balance_sheet_current, fetcher)
        cash_position_prior = InsightsService._extract_cash_from_balance_sheet(balance_sheet_prior, fetcher)
        
        net_cash_change = cash_position_current - cash_position_prior
        cash_received = max(0.0, net_cash_change)
        cash_spent = abs(min(0.0, net_cash_change))
        
        executive_summary_current = {
            "cash_position": cash_position_current,
            "cash_spent": cash_spent,
            "cash_received": cash_received,
            "report_date": date.today(),
        }
        
        executive_summary_history = []
        
        return LeadingIndicatorsCalculator.calculate(
            receivables=receivables,
            payables=payables,
            executive_summary_current=executive_summary_current,
            executive_summary_history=executive_summary_history,
        )
    
    @staticmethod
    def calculate_cash_pressure(
        cash_runway: dict[str, Any]
    ) -> dict[str, Any]:
        """
        Calculate cash pressure status.
        
        Args:
            cash_runway: Cash runway metrics
        
        Returns:
            Dictionary with cash pressure status
        """
        return CashPressureCalculator.calculate(
            runway_months=cash_runway.get("runway_months"),
            runway_status=cash_runway.get("status"),
            cash_position=cash_runway.get("current_cash"),
        )
    
    @staticmethod
    def calculate_profitability(
        profit_loss_data: Optional[dict[str, Any]],
        balance_sheet_current: dict[str, Any],
        balance_sheet_prior: dict[str, Any],
        fetcher: XeroDataFetcher,
        trial_balance_pnl: Optional[dict[str, Any]] = None
    ) -> dict[str, Any]:
        """
        Calculate profitability metrics.
        
        Args:
            profit_loss_data: P&L report data
            balance_sheet_current: Current Balance Sheet data
            balance_sheet_prior: Prior Balance Sheet data
            fetcher: XeroDataFetcher instance
        
        Returns:
            Dictionary with profitability metrics
        """
        from datetime import date
        
        cash_position_current = InsightsService._extract_cash_from_balance_sheet(balance_sheet_current, fetcher)
        cash_position_prior = InsightsService._extract_cash_from_balance_sheet(balance_sheet_prior, fetcher)
        
        net_cash_change = cash_position_current - cash_position_prior
        cash_received = max(0.0, net_cash_change)
        cash_spent = abs(min(0.0, net_cash_change))
        
        executive_summary_current = {
            "cash_position": cash_position_current,
            "cash_spent": cash_spent,
            "cash_received": cash_received,
            "report_date": date.today(),
        }
        
        executive_summary_history = []
        
        return ProfitabilityCalculator.calculate(
            profit_loss_data=profit_loss_data,
            trial_balance_pnl=trial_balance_pnl,
            executive_summary_current=executive_summary_current,
            executive_summary_history=executive_summary_history,
        )
    
    @staticmethod
    def calculate_upcoming_commitments(
        payables: dict[str, Any],
        balance_sheet_current: dict[str, Any],
        fetcher: XeroDataFetcher
    ) -> dict[str, Any]:
        """
        Calculate upcoming cash commitments.
        
        Args:
            payables: Payables data
            balance_sheet_current: Current Balance Sheet data
            fetcher: XeroDataFetcher instance
        
        Returns:
            Dictionary with upcoming commitments metrics
        """
        cash_position = InsightsService._extract_cash_from_balance_sheet(balance_sheet_current, fetcher)
        
        return UpcomingCommitmentsCalculator.calculate(
            payables=payables,
            cash_position=cash_position,
        )
    
    @staticmethod
    def calculate_all_insights(
        financial_data: dict[str, Any],
        fetcher: XeroDataFetcher
    ) -> dict[str, Any]:
        """
        Calculate all financial insights from raw Xero data.
        
        Args:
            financial_data: Complete data structure from XeroDataFetcher.fetch_all_data()
            fetcher: XeroDataFetcher instance for cash extraction
        
        Returns:
            Dictionary with all calculated insights:
            - cash_runway
            - leading_indicators
            - cash_pressure
            - profitability
            - upcoming_commitments
        """
        balance_sheet_current = financial_data.get("balance_sheet_current", {})
        balance_sheet_prior = financial_data.get("balance_sheet_prior", {})
        receivables = financial_data.get("invoices_receivable", {})
        payables = financial_data.get("invoices_payable", {})
        profit_loss = financial_data.get("profit_loss")
        trial_balance_pnl = financial_data.get("trial_balance_pnl")
        
        cash_runway = InsightsService.calculate_cash_runway(
            balance_sheet_current,
            balance_sheet_prior,
            fetcher
        )
        # Attach a simple runway confidence for MVP UI (High/Medium/Low)
        try:
            runway_months = cash_runway.get("runway_months")
            status = cash_runway.get("status") or ""
            if runway_months is not None:
                cash_runway["confidence_level"] = "High"
            elif status in ("negative", "infinite"):
                cash_runway["confidence_level"] = "High"
            elif status in ("healthy", "warning", "critical"):
                cash_runway["confidence_level"] = "Medium"
            else:
                cash_runway["confidence_level"] = "Medium"
        except Exception:
            # Fallback conservatively
            cash_runway["confidence_level"] = "Medium"
        
        leading_indicators = InsightsService.calculate_leading_indicators(
            receivables,
            payables,
            balance_sheet_current,
            balance_sheet_prior,
            fetcher
        )
        
        cash_pressure = InsightsService.calculate_cash_pressure(
            cash_runway
        )
        
        profitability = InsightsService.calculate_profitability(
            profit_loss,
            balance_sheet_current,
            balance_sheet_prior,
            fetcher,
            trial_balance_pnl=trial_balance_pnl
        )
        
        upcoming_commitments = InsightsService.calculate_upcoming_commitments(
            payables,
            balance_sheet_current,
            fetcher
        )
        
        return {
            "cash_runway": cash_runway,
            "leading_indicators": leading_indicators,
            "cash_pressure": cash_pressure,
            "profitability": profitability,
            "upcoming_commitments": upcoming_commitments,
        }

