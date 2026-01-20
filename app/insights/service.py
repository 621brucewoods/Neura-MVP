"""
Insights Service
Orchestrates calculation of financial insights from Xero data.

Uses Monthly P&L data for revenue/expenses (not Trial Balance).
"""

import logging
from datetime import date as date_type
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
from app.integrations.xero.extractors import Extractors

logger = logging.getLogger(__name__)


class InsightsService:
    """
    Service for calculating financial insights.
    
    Takes extracted data from Extractors and monthly P&L data,
    returns calculated insights for cash runway, leading indicators,
    cash pressure, profitability, and upcoming commitments.
    """
    
    @staticmethod
    def calculate_cash_pressure(cash_runway: dict[str, Any]) -> dict[str, Any]:
        """Calculate cash pressure status from runway metrics."""
        return CashPressureCalculator.calculate(
            runway_months=cash_runway.get("runway_months"),
            runway_status=cash_runway.get("status"),
            cash_position=cash_runway.get("current_cash"),
        )
    
    @staticmethod
    def _aggregate_monthly_pnl(
        monthly_pnl_data: Optional[list[dict[str, Any]]],
        num_months: int = 3
    ) -> dict[str, Optional[float]]:
        """
        Aggregate monthly P&L data into rolling totals.
        
        Args:
            monthly_pnl_data: List of monthly P&L (newest first)
            num_months: Number of months to aggregate (default 3)
            
        Returns:
            Dict with revenue, cost_of_sales, expenses (rolling sum)
        """
        if not monthly_pnl_data:
            return {"revenue": None, "cost_of_sales": None, "expenses": None}
        
        # Collect values from months that have data
        revenues = []
        cogs_list = []
        expenses_list = []
        
        for month in monthly_pnl_data[:num_months]:
            rev = month.get("revenue")
            cogs = month.get("cost_of_sales")
            exp = month.get("expenses")
            
            # Include 0 values (they're valid data), exclude None
            if rev is not None:
                revenues.append(float(rev))
            if cogs is not None:
                cogs_list.append(float(cogs))
            if exp is not None:
                expenses_list.append(float(exp))
        
        # Return sums if we have data, otherwise None
        return {
            "revenue": sum(revenues) if revenues else None,
            "cost_of_sales": sum(cogs_list) if cogs_list else None,
            "expenses": sum(expenses_list) if expenses_list else None,
        }
    
    @staticmethod
    def calculate_all_insights(
        financial_data: dict[str, Any],
        monthly_pnl_data: Optional[list[dict[str, Any]]] = None,
    ) -> dict[str, Any]:
        """
        Calculate all financial insights from Xero data.
        
        Args:
            financial_data: Complete data structure from XeroDataFetcher.fetch_all_data()
                           Must include 'extracted' key from Extractors module.
            monthly_pnl_data: List of monthly P&L data (newest first) for
                             revenue/expenses calculations.
        
        Returns:
            Dictionary with all calculated insights:
            - cash_runway
            - leading_indicators
            - cash_pressure
            - profitability
            - upcoming_commitments
        """
        # Get extracted data (required for balance sheet)
        extracted = financial_data.get("extracted")
        if not extracted:
            logger.warning("No extracted data found, attempting fallback extraction")
            balance_sheet_current = financial_data.get("balance_sheet_current", {})
            account_type_map = financial_data.get("account_type_map", {})
            
            if account_type_map:
                extracted = Extractors.extract_all(
                    balance_sheet_raw=balance_sheet_current,
                    trial_balance_raw={},  # Not used for P&L anymore
                    invoices_receivable=financial_data.get("invoices_receivable", {}),
                    invoices_payable=financial_data.get("invoices_payable", {}),
                    account_map=account_type_map,
                )
            else:
                logger.error("Cannot calculate insights: no account_type_map available")
                return {
                    "cash_runway": {"status": "unknown", "error": "missing_data"},
                    "leading_indicators": {},
                    "cash_pressure": {"status": "unknown"},
                    "profitability": {},
                    "upcoming_commitments": {},
                }
        
        # Extract Balance Sheet values
        bs_data = extracted.get("balance_sheet", {})
        cash_current = bs_data.get("cash") or 0.0
        
        # Get P&L values from monthly data (rolling 3-month sum)
        pnl_aggregated = InsightsService._aggregate_monthly_pnl(monthly_pnl_data, num_months=3)
        revenue = pnl_aggregated.get("revenue") or 0.0
        cost_of_sales = pnl_aggregated.get("cost_of_sales") or 0.0
        expenses = pnl_aggregated.get("expenses") or 0.0
        
        logger.info(
            f"P&L from monthly data (3mo): revenue={revenue:.2f}, "
            f"cogs={cost_of_sales:.2f}, expenses={expenses:.2f}"
        )
        
        # Get receivables/payables
        receivables = financial_data.get("invoices_receivable", {})
        payables = financial_data.get("invoices_payable", {})
        
        # Extract prior period cash if available
        balance_sheet_prior = financial_data.get("balance_sheet_prior", {})
        account_type_map = financial_data.get("account_type_map", {})
        
        cash_prior = 0.0
        if balance_sheet_prior and account_type_map:
            prior_bs = Extractors.extract_balance_sheet(balance_sheet_prior, account_type_map)
            cash_prior = prior_bs.get("cash") or 0.0
        
        # Calculate net profit and derive burn rate
        net_profit = revenue - cost_of_sales - expenses
        if net_profit >= 0:
            cash_spent = 0.0
            cash_received = net_profit
        else:
            cash_spent = abs(net_profit)
            cash_received = 0.0
        
        # Calculate cash runway
        cash_runway = CashRunwayCalculator.calculate(
            cash_position=cash_current,
            cash_spent=cash_spent,
            cash_received=cash_received,
        )
        cash_runway["confidence_details"] = ["burn_from_monthly_pnl"]
        
        # Set confidence level based on data availability
        runway_months = cash_runway.get("runway_months")
        status = cash_runway.get("status") or ""
        has_pnl_data = monthly_pnl_data and len(monthly_pnl_data) >= 3
        
        if has_pnl_data and (runway_months is not None or status in ("negative", "infinite")):
            cash_runway["confidence_level"] = "High"
        else:
            cash_runway["confidence_level"] = "Medium"
        
        # Build executive summary for other calculators
        executive_summary = {
            "cash_position": cash_current,
            "cash_spent": cash_spent,
            "cash_received": cash_received,
            "report_date": date_type.today(),
        }
        
        # Calculate leading indicators
        leading_indicators = LeadingIndicatorsCalculator.calculate(
            receivables=receivables,
            payables=payables,
            executive_summary_current=executive_summary,
            executive_summary_history=[],
        )
        
        # Calculate cash pressure
        cash_pressure = InsightsService.calculate_cash_pressure(cash_runway)
        cash_pressure["confidence_details"] = ["derived_from_runway"]
        
        # Calculate profitability using monthly P&L data
        profitability = ProfitabilityCalculator.calculate(
            revenue=revenue,
            cost_of_sales=cost_of_sales,
            expenses=expenses,
            executive_summary_current=executive_summary,
            executive_summary_history=[],
        )
        
        # Calculate upcoming commitments
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
