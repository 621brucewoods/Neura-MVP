"""
Profitability calculator for P&L analysis.

Uses Monthly P&L data (aggregated revenue/expenses) passed directly.
"""

import logging
from typing import Any, Optional

from app.insights.utils import safe_float, safe_get

logger = logging.getLogger(__name__)


class ProfitabilityCalculator:
    """
    Calculates profitability metrics from P&L data.
    
    Accepts pre-aggregated revenue, cost_of_sales, and expenses
    from monthly P&L data (rolling 3-month sum).
    """

    @staticmethod
    def calculate_gross_margin(
        revenue: Optional[float],
        cost_of_sales: Optional[float],
        gross_profit: Optional[float]
    ) -> Optional[float]:
        """
        Calculate gross margin percentage.
        
        Uses actual revenue value (not abs) to preserve sign for negative revenue.
        """
        if gross_profit is not None and revenue is not None and revenue != 0:
            return float((gross_profit / revenue) * 100)

        if revenue is not None and cost_of_sales is not None and revenue != 0:
            gross = revenue - cost_of_sales
            return float((gross / revenue) * 100)

        return None

    @staticmethod
    def calculate_profit_trend(
        executive_summary_current: dict[str, Any],
        executive_summary_history: list[dict[str, Any]]
    ) -> str:
        """Determine profit trend from cash flow: improving, declining, or stable."""
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
            net_flows.append(cash_received - cash_spent)

        if len(net_flows) < 2:
            return "stable"

        recent_trend = net_flows[-1] - net_flows[-2]

        if recent_trend > 0:
            return "improving"
        elif recent_trend < 0:
            return "declining"
        return "stable"

    @staticmethod
    def _determine_risk_level(
        gross_margin: Optional[float],
        net_profit: Optional[float],
        profit_trend: str
    ) -> str:
        """Determine profitability risk level: low, medium, or high."""
        risk_level = "low"

        if gross_margin is not None:
            if gross_margin < 20:
                risk_level = "high"
            elif gross_margin < 30:
                risk_level = "medium"

        if net_profit is not None and net_profit < 0:
            risk_level = "high"
        elif profit_trend == "declining" and risk_level == "low":
            risk_level = "medium"

        return risk_level

    @staticmethod
    def calculate(
        revenue: Optional[float],
        cost_of_sales: Optional[float],
        expenses: Optional[float],
        executive_summary_current: dict[str, Any],
        executive_summary_history: list[dict[str, Any]]
    ) -> dict[str, Any]:
        """
        Calculate all profitability metrics.
        
        Args:
            revenue: Total revenue (from monthly P&L, rolling 3-month sum)
            cost_of_sales: Total COGS (from monthly P&L, rolling 3-month sum)
            expenses: Total expenses (from monthly P&L, rolling 3-month sum)
            executive_summary_current: Current period cash flow summary
            executive_summary_history: Historical cash flow summaries
            
        Returns:
            Profitability metrics including gross margin, net profit, trend, risk level
        """
        # Calculate gross_profit
        gross_profit = None
        if revenue is not None and cost_of_sales is not None:
            gross_profit = revenue - cost_of_sales

        # Calculate net_profit
        net_profit = None
        if gross_profit is not None and expenses is not None:
            net_profit = gross_profit - expenses
        elif revenue is not None and expenses is not None:
            net_profit = revenue - expenses

        gross_margin = ProfitabilityCalculator.calculate_gross_margin(
            revenue=revenue,
            cost_of_sales=cost_of_sales,
            gross_profit=gross_profit
        )

        profit_trend = ProfitabilityCalculator.calculate_profit_trend(
            executive_summary_current,
            executive_summary_history
        )

        risk_level = ProfitabilityCalculator._determine_risk_level(
            gross_margin,
            net_profit,
            profit_trend
        )

        return {
            "revenue": revenue,
            "cost_of_sales": cost_of_sales,
            "gross_profit": gross_profit,
            "gross_margin_pct": gross_margin,
            "expenses": expenses,
            "net_profit": net_profit,
            "profit_trend": profit_trend,
            "risk_level": risk_level,
        }
