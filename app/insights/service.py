"""
Insights Service
Orchestrates calculation of financial insights from Xero data.

Uses the Extractors module for reliable data extraction.
"""

import logging
from datetime import date as date_type
from typing import Any

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
    
    Takes extracted data from Extractors and returns calculated insights
    for cash runway, leading indicators, and cash pressure.
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
    def calculate_all_insights(financial_data: dict[str, Any]) -> dict[str, Any]:
        """
        Calculate all financial insights from Xero data.
        
        Args:
            financial_data: Complete data structure from XeroDataFetcher.fetch_all_data()
                           Must include 'extracted' key from Extractors module.
        
        Returns:
            Dictionary with all calculated insights:
            - cash_runway
            - leading_indicators
            - cash_pressure
            - profitability
            - upcoming_commitments
        """
        # Get extracted data (required)
        extracted = financial_data.get("extracted")
        if not extracted:
            logger.warning("No extracted data found, attempting fallback extraction")
            # Try to extract from raw data
            balance_sheet_current = financial_data.get("balance_sheet_current", {})
            account_type_map = financial_data.get("account_type_map", {})
            trial_balance = financial_data.get("trial_balance", {})
            
            if account_type_map:
                extracted = Extractors.extract_all(
                    balance_sheet_raw=balance_sheet_current,
                    trial_balance_raw=trial_balance,
                    invoices_receivable=financial_data.get("invoices_receivable", {}),
                    invoices_payable=financial_data.get("invoices_payable", {}),
                    account_map=account_type_map,
                )
            else:
                # No account map, return empty results
                logger.error("Cannot calculate insights: no account_type_map available")
                return {
                    "cash_runway": {"status": "unknown", "error": "missing_data"},
                    "leading_indicators": {},
                    "cash_pressure": {"status": "unknown"},
                    "profitability": {},
                    "upcoming_commitments": {},
                }
        
        # Extract values from clean extracted data
        bs_data = extracted.get("balance_sheet", {})
        pnl_data = extracted.get("pnl", {})
        
        cash_current = bs_data.get("cash") or 0.0
        revenue = pnl_data.get("revenue") or 0.0
        cost_of_sales = pnl_data.get("cost_of_sales") or 0.0
        expenses = pnl_data.get("expenses") or 0.0
        
        # Get receivables/payables
        receivables = financial_data.get("invoices_receivable", {})
        payables = financial_data.get("invoices_payable", {})
        profit_loss = financial_data.get("profit_loss")
        
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
        cash_runway["confidence_details"] = ["burn_from_extracted_pnl"]
        
        # Set confidence level
        runway_months = cash_runway.get("runway_months")
        status = cash_runway.get("status") or ""
        if runway_months is not None or status in ("negative", "infinite"):
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
        
        # Calculate profitability
        trial_balance_pnl = {
            "revenue": revenue,
            "cost_of_sales": cost_of_sales,
            "expenses": expenses,
        }
        
        profitability = ProfitabilityCalculator.calculate(
            profit_loss_data=profit_loss,
            trial_balance_pnl=trial_balance_pnl,
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
