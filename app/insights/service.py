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
    def _extract_cash_from_balance_sheet(
        balance_sheet: dict[str, Any], 
        fetcher: XeroDataFetcher,
        account_type_map: Optional[dict[str, Any]] = None
    ) -> float:
        """
        Extract cash position from Balance Sheet.
        
        Args:
            balance_sheet: Balance Sheet data
            fetcher: XeroDataFetcher instance with extraction method
            account_type_map: Optional account ID to type mapping for reliable extraction
        
        Returns:
            Cash position as float (defaults to 0.0 if not found)
        """
        cash = fetcher.extract_cash_from_balance_sheet(balance_sheet, account_type_map=account_type_map)
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
        balance_sheet_totals = financial_data.get("balance_sheet_totals", {})
        account_type_map = financial_data.get("account_type_map", {})
        receivables = financial_data.get("invoices_receivable", {})
        payables = financial_data.get("invoices_payable", {})
        profit_loss = financial_data.get("profit_loss")
        trial_balance_pnl = financial_data.get("trial_balance_pnl")
        
        # Get cash from reliable balance_sheet_totals if available
        # Otherwise fallback to extraction with account_type_map
        if balance_sheet_totals and "cash" in balance_sheet_totals:
            cash_current = balance_sheet_totals.get("cash", 0.0)
        else:
            cash_current = InsightsService._extract_cash_from_balance_sheet(
                balance_sheet_current, fetcher, account_type_map
            )
        
        # Prior period needs extraction (no pre-computed totals)
        cash_prior = InsightsService._extract_cash_from_balance_sheet(
            balance_sheet_prior, fetcher, account_type_map
        )
        
        # Calculate net cash change and derive burn
        net_cash_change = cash_current - cash_prior
        cash_received = max(0.0, net_cash_change)
        cash_spent = abs(min(0.0, net_cash_change))
        
        cash_runway = CashRunwayCalculator.calculate(
            cash_position=cash_current,
            cash_spent=cash_spent,
            cash_received=cash_received,
        )
        # Prefer Trial Balance net profit/loss to derive burn for runway
        try:
            if isinstance(trial_balance_pnl, dict):
                rev = float(trial_balance_pnl.get("revenue") or 0)
                cogs = float(trial_balance_pnl.get("cost_of_sales") or 0)
                exp = float(trial_balance_pnl.get("expenses") or 0)
                net = rev - cogs - exp
                current_cash = cash_runway.get("current_cash", 0.0)
                if net >= 0:
                    cash_spent = 0.0
                    cash_received = net
                else:
                    cash_spent = abs(net)
                    cash_received = 0.0
                cash_runway = CashRunwayCalculator.calculate(
                    cash_position=current_cash,
                    cash_spent=cash_spent,
                    cash_received=cash_received,
                )
                # mark source
                cash_runway["confidence_details"] = ["burn_from_trial_balance"]
        except Exception:
            # if any issue, retain prior approximation
            pass
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
            # Confidence details for explainability
            details: list[str] = []
            # Input coverage checks
            if not balance_sheet_current:
                details.append("missing_balance_sheet_current")
            if not balance_sheet_prior:
                details.append("missing_balance_sheet_prior")
            # Derivation method used for burn
            if isinstance(trial_balance_pnl, dict):
                if "burn_from_trial_balance" not in details and (
                    isinstance(cash_runway.get("confidence_details"), list)
                ):
                    # preserve earlier tag if already set
                    details.extend([d for d in cash_runway.get("confidence_details") if isinstance(d, str)])
                if "burn_from_trial_balance" not in details:
                    details.append("burn_from_trial_balance")
            else:
                details.append("approx_burn_from_balance_sheet")
            # Basic plausibility check
            if cash_runway.get("current_cash") is None:
                details.append("cash_extraction_failed")
            cash_runway["confidence_details"] = details or None
        except Exception:
            # Fallback conservatively
            cash_runway["confidence_level"] = "Medium"
            cash_runway["confidence_details"] = ["confidence_estimation_error"]
        
        # Calculate leading indicators using pre-extracted cash values
        from datetime import date as date_type
        executive_summary_for_indicators = {
            "cash_position": cash_current,
            "cash_spent": cash_spent,
            "cash_received": cash_received,
            "report_date": date_type.today(),
        }
        
        leading_indicators = LeadingIndicatorsCalculator.calculate(
            receivables=receivables,
            payables=payables,
            executive_summary_current=executive_summary_for_indicators,
            executive_summary_history=[],
        )
        
        cash_pressure = InsightsService.calculate_cash_pressure(
            cash_runway
        )
        # Propagate minimal confidence details to cash pressure
        try:
            pressure_details: list[str] = ["derived_from_runway"]
            runway_conf = (cash_runway.get("confidence_level") or "").lower()
            if runway_conf in ("medium", "low"):
                pressure_details.append("low_runway_confidence")
            if cash_runway.get("confidence_details"):
                pressure_details.extend([f"runway:{d}" for d in cash_runway["confidence_details"]])
            cash_pressure["confidence_details"] = pressure_details
        except Exception:
            pass
        
        # Calculate profitability using pre-extracted cash values
        executive_summary_for_profit = {
            "cash_position": cash_current,
            "cash_spent": cash_spent,
            "cash_received": cash_received,
            "report_date": date_type.today(),
        }
        
        profitability = ProfitabilityCalculator.calculate(
            profit_loss_data=profit_loss,
            trial_balance_pnl=trial_balance_pnl,
            executive_summary_current=executive_summary_for_profit,
            executive_summary_history=[],
        )
        
        # Calculate upcoming commitments using pre-extracted cash position
        upcoming_commitments = UpcomingCommitmentsCalculator.calculate(
            payables=payables,
            cash_position=cash_current,
        )
        
        return {
            "cash_runway": cash_runway,
            "leading_indicators": leading_indicators,
            "cash_pressure": cash_pressure,
            "profitability": profitability,
            "upcoming_commitments": upcoming_commitments,
        }

