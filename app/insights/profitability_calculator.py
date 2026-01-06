"""
Profitability calculator for P&L analysis.
"""

from typing import Any, Optional

from app.insights.utils import safe_float, safe_get, safe_list_get, safe_str_lower


class ProfitabilityCalculator:
    """
    Calculates profitability metrics from P&L data.
    
    Analyzes gross margin, profit trends, and profitability pressure.
    """
    
    @staticmethod
    def _extract_pnl_values(pnl_data: Optional[dict[str, Any]]) -> dict[str, Any]:
        """
        Extract key values from P&L report structure.
        
        Args:
            pnl_data: Raw P&L data from Xero
        
        Returns:
            Dictionary with extracted values
        """
        if not pnl_data or not pnl_data.get("raw_data"):
            return {
                "revenue": None,
                "cost_of_sales": None,
                "gross_profit": None,
                "expenses": None,
                "net_profit": None,
            }
        
        raw_data = safe_get(pnl_data, "raw_data", {})
        if not isinstance(raw_data, dict):
            raw_data = {}
        
        rows = safe_get(raw_data, "rows", [])
        if not isinstance(rows, list):
            rows = []
        
        revenue = None
        cost_of_sales = None
        gross_profit = None
        expenses = None
        net_profit = None
        
        def _find_value_in_rows(rows_list: list, search_terms: list[str]) -> Optional[float]:
            """Recursively search for value in P&L rows."""
            if not isinstance(rows_list, list):
                return None
            
            for row in rows_list:
                if not isinstance(row, dict):
                    continue
                
                # Safely get and normalize title
                title = safe_str_lower(safe_get(row, "title"), "")
                
                # Safely get cells list
                cells = safe_get(row, "cells", [])
                if not isinstance(cells, list):
                    cells = []
                
                # Search for matching term in title
                for term in search_terms:
                    if term in title:
                        # Safely access cell value
                        if len(cells) > 1:
                            cell = safe_list_get(cells, 1)
                            if isinstance(cell, dict):
                                value_str = safe_get(cell, "value", "0")
                                value = safe_float(value_str)
                                if value != 0:
                                    return value
                
                # Recursively search nested rows
                nested_rows = safe_get(row, "rows", [])
                if isinstance(nested_rows, list) and nested_rows:
                    found = _find_value_in_rows(nested_rows, search_terms)
                    if found is not None:
                        return found
            
            return None
        
        revenue = _find_value_in_rows(rows, ["revenue", "income", "sales", "total income"])
        cost_of_sales = _find_value_in_rows(rows, ["cost of sales", "cogs", "cost of goods"])
        gross_profit = _find_value_in_rows(rows, ["gross profit"])
        expenses = _find_value_in_rows(rows, ["expenses", "total expenses", "operating expenses"])
        net_profit = _find_value_in_rows(rows, ["net profit", "net income", "profit"])
        
        return {
            "revenue": revenue,
            "cost_of_sales": cost_of_sales,
            "gross_profit": gross_profit,
            "expenses": expenses,
            "net_profit": net_profit,
        }
    
    @staticmethod
    def calculate_gross_margin(
        revenue: Optional[float],
        cost_of_sales: Optional[float],
        gross_profit: Optional[float]
    ) -> Optional[float]:
        """
        Calculate gross margin percentage.
        
        Args:
            revenue: Total revenue
            cost_of_sales: Cost of sales
            gross_profit: Gross profit (if available)
        
        Returns:
            Gross margin percentage, or None if insufficient data
        """
        if gross_profit is not None and revenue is not None and revenue != 0:
            return float((gross_profit / abs(revenue)) * 100)
        
        if revenue is not None and cost_of_sales is not None and revenue != 0:
            gross = revenue - cost_of_sales
            return float((gross / abs(revenue)) * 100)
        
        return None
    
    @staticmethod
    def calculate_profit_trend(
        executive_summary_current: dict[str, Any],
        executive_summary_history: list[dict[str, Any]]
    ) -> str:
        """
        Determine profit trend from cash flow.
        
        Args:
            executive_summary_current: Current month Executive Summary
            executive_summary_history: Historical months (oldest to newest)
        
        Returns:
            Trend: "improving", "declining", or "stable"
        """
        if not isinstance(executive_summary_history, list) or len(executive_summary_history) < 2:
            return "stable"
        
        if not isinstance(executive_summary_current, dict):
            return "stable"
        
        all_data = executive_summary_history + [executive_summary_current]
        
        net_flows = []
        for month in all_data[-3:]:
            if not isinstance(month, dict):
                continue
            cash_received = safe_float(safe_get(month, "cash_received"), 0.0)
            cash_spent = safe_float(safe_get(month, "cash_spent"), 0.0)
            net_flow = cash_received - cash_spent
            net_flows.append(net_flow)
        
        if len(net_flows) < 2:
            return "stable"
        
        recent_trend = net_flows[-1] - net_flows[-2]
        
        if recent_trend > 0:
            return "improving"
        elif recent_trend < 0:
            return "declining"
        else:
            return "stable"
    
    @staticmethod
    def calculate(
        profit_loss_data: Optional[dict[str, Any]],
        executive_summary_current: dict[str, Any],
        executive_summary_history: list[dict[str, Any]]
    ) -> dict[str, Any]:
        """
        Calculate all profitability metrics.
        
        Args:
            profit_loss_data: P&L report data from XeroDataFetcher
            executive_summary_current: Current month Executive Summary
            executive_summary_history: Historical months
        
        Returns:
            Dictionary with profitability metrics
        """
        pnl_values = ProfitabilityCalculator._extract_pnl_values(profit_loss_data)
        
        gross_margin = ProfitabilityCalculator.calculate_gross_margin(
            revenue=pnl_values["revenue"],
            cost_of_sales=pnl_values["cost_of_sales"],
            gross_profit=pnl_values["gross_profit"]
        )
        
        profit_trend = ProfitabilityCalculator.calculate_profit_trend(
            executive_summary_current,
            executive_summary_history
        )
        
        risk_level = "low"
        if gross_margin is not None and gross_margin < 20:
            risk_level = "high"
        elif gross_margin is not None and gross_margin < 30:
            risk_level = "medium"
        elif profit_trend == "declining":
            risk_level = "medium"
        
        return {
            "revenue": pnl_values["revenue"],
            "cost_of_sales": pnl_values["cost_of_sales"],
            "gross_profit": pnl_values["gross_profit"],
            "gross_margin_pct": gross_margin,
            "expenses": pnl_values["expenses"],
            "net_profit": pnl_values["net_profit"],
            "profit_trend": profit_trend,
            "risk_level": risk_level,
        }

