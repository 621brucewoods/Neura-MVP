"""
Trend analysis calculator for cash flow patterns.
"""

from typing import Any, Optional
from statistics import mean, stdev
from statistics import StatisticsError

from app.insights.utils import safe_float, safe_get, safe_list_get


class TrendAnalyzer:
    """
    Analyzes trends in cash flow over time.
    
    Calculates expense acceleration, revenue volatility, and cash flow trends.
    """
    
    @staticmethod
    def calculate_percentage_change(current: float, previous: float) -> Optional[float]:
        """
        Calculate percentage change between two values.
        
        Args:
            current: Current period value
            previous: Previous period value
        
        Returns:
            Percentage change, or None if previous is zero
        """
        if previous == 0:
            return None
        
        change = ((current - previous) / abs(previous)) * 100
        return float(change)
    
    @staticmethod
    def calculate_expense_acceleration(
        historical_data: list[dict[str, Any]]
    ) -> Optional[float]:
        """
        Calculate expense acceleration (rate of change in cash spent).
        
        Uses the most recent month-over-month change.
        
        Args:
            historical_data: List of Executive Summary data, ordered oldest to newest
        
        Returns:
            Percentage change in expenses, or None if insufficient data
        """
        if not isinstance(historical_data, list) or len(historical_data) < 2:
            return None
        
        current_month = safe_list_get(historical_data, -1, {})
        previous_month = safe_list_get(historical_data, -2, {})
        
        if not isinstance(current_month, dict) or not isinstance(previous_month, dict):
            return None
        
        current_spent = safe_float(safe_get(current_month, "cash_spent"), 0.0)
        previous_spent = safe_float(safe_get(previous_month, "cash_spent"), 0.0)
        
        return TrendAnalyzer.calculate_percentage_change(current_spent, previous_spent)
    
    @staticmethod
    def calculate_revenue_volatility(
        historical_data: list[dict[str, Any]]
    ) -> Optional[float]:
        """
        Calculate revenue volatility (coefficient of variation).
        
        Measures how much cash received varies month-to-month.
        
        Args:
            historical_data: List of Executive Summary data
        
        Returns:
            Coefficient of variation (0-100+), or None if insufficient data
        """
        if not isinstance(historical_data, list) or len(historical_data) < 2:
            return None
        
        cash_received_values = []
        for month in historical_data:
            if isinstance(month, dict):
                value = safe_float(safe_get(month, "cash_received"), 0.0)
                cash_received_values.append(value)
        
        if not cash_received_values or len(cash_received_values) < 2:
            return None
        
        try:
            mean_value = mean(cash_received_values)
            if mean_value == 0:
                return None
            std_dev = stdev(cash_received_values)
            coefficient_of_variation = (std_dev / abs(mean_value)) * 100
            return float(coefficient_of_variation)
        except (ValueError, TypeError, ZeroDivisionError, StatisticsError):
            return None
    
    @staticmethod
    def calculate_net_cash_flow_trend(
        historical_data: list[dict[str, Any]]
    ) -> str:
        """
        Determine net cash flow trend direction.
        
        Args:
            historical_data: List of Executive Summary data, ordered oldest to newest
        
        Returns:
            Trend direction: "improving", "declining", or "stable"
        """
        if not isinstance(historical_data, list) or len(historical_data) < 2:
            return "stable"
        
        net_flows = []
        for month in historical_data:
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
    def calculate_monthly_changes(
        historical_data: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        """
        Calculate month-over-month changes for all metrics.
        
        Args:
            historical_data: List of Executive Summary data, ordered oldest to newest
        
        Returns:
            List of monthly change records
        """
        if not isinstance(historical_data, list) or len(historical_data) < 2:
            return []
        
        changes = []
        for i in range(1, len(historical_data)):
            current = safe_list_get(historical_data, i, {})
            previous = safe_list_get(historical_data, i - 1, {})
            
            if not isinstance(current, dict) or not isinstance(previous, dict):
                continue
            
            cash_received_change = TrendAnalyzer.calculate_percentage_change(
                safe_float(safe_get(current, "cash_received"), 0.0),
                safe_float(safe_get(previous, "cash_received"), 0.0)
            )
            
            cash_spent_change = TrendAnalyzer.calculate_percentage_change(
                safe_float(safe_get(current, "cash_spent"), 0.0),
                safe_float(safe_get(previous, "cash_spent"), 0.0)
            )
            
            net_change = (
                safe_float(safe_get(current, "cash_received"), 0.0) - 
                safe_float(safe_get(current, "cash_spent"), 0.0)
            ) - (
                safe_float(safe_get(previous, "cash_received"), 0.0) - 
                safe_float(safe_get(previous, "cash_spent"), 0.0)
            )
            
            changes.append({
                "month": safe_get(current, "report_date"),
                "cash_received_change_pct": cash_received_change,
                "cash_spent_change_pct": cash_spent_change,
                "net_cash_flow_change": net_change,
            })
        
        return changes
    
    @staticmethod
    def calculate(
        executive_summary_current: dict[str, Any],
        executive_summary_history: list[dict[str, Any]]
    ) -> dict[str, Any]:
        """
        Calculate all trend metrics.
        
        Args:
            executive_summary_current: Current month Executive Summary
            executive_summary_history: Historical months (oldest to newest)
        
        Returns:
            Dictionary with all trend metrics
        """
        all_data = executive_summary_history + [executive_summary_current]
        
        expense_acceleration = TrendAnalyzer.calculate_expense_acceleration(all_data)
        revenue_volatility = TrendAnalyzer.calculate_revenue_volatility(all_data)
        net_cash_flow_trend = TrendAnalyzer.calculate_net_cash_flow_trend(all_data)
        monthly_changes = TrendAnalyzer.calculate_monthly_changes(all_data)
        
        return {
            "expense_acceleration": expense_acceleration,
            "revenue_volatility": revenue_volatility,
            "net_cash_flow_trend": net_cash_flow_trend,
            "monthly_changes": monthly_changes,
        }

