"""
Trend analysis calculator for cash flow patterns.
"""

import logging
from datetime import date, timedelta
from statistics import mean, stdev
from statistics import StatisticsError
from typing import Any, Optional

from app.insights.utils import safe_float, safe_get, safe_list_get

logger = logging.getLogger(__name__)


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
        Excludes partial months from calculation to avoid false alarms.
        
        Args:
            historical_data: List of Executive Summary data, ordered oldest to newest
        
        Returns:
            Percentage change in expenses, or None if insufficient data or partial month
        """
        if not isinstance(historical_data, list) or len(historical_data) < 2:
            return None
        
        current_month = safe_list_get(historical_data, -1, {})
        previous_month = safe_list_get(historical_data, -2, {})
        
        if not isinstance(current_month, dict) or not isinstance(previous_month, dict):
            return None
        
        # Skip calculation if current month is partial (less than 7 days)
        current_date = safe_get(current_month, "report_date")
        if TrendAnalyzer._is_partial_month(current_date):
            logger.debug("Skipping expense acceleration calculation for partial month %s", current_date)
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
    def _is_partial_month(report_date_str: Optional[str]) -> bool:
        """
        Check if a report date represents a partial month.
        
        A month is considered partial if:
        - It's the current month and less than 7 days have elapsed
        - The report_date is not a month-end date
        
        Args:
            report_date_str: Report date as ISO string (YYYY-MM-DD)
            
        Returns:
            True if partial month, False otherwise
        """
        if not report_date_str:
            return False
        
        try:
            report_date = date.fromisoformat(report_date_str)
            today = date.today()
            
            # If it's the current month and less than 7 days have elapsed
            if report_date.year == today.year and report_date.month == today.month:
                days_elapsed = today.day
                if days_elapsed < 7:
                    return True
            
            # Check if it's a month-end date (last day of month)
            # If not month-end, it's likely partial
            if report_date.month == 12:
                expected_end = date(report_date.year, 12, 31)
            else:
                expected_end = date(report_date.year, report_date.month + 1, 1)
                expected_end = expected_end - timedelta(days=1)
            
            return report_date != expected_end
            
        except (ValueError, TypeError):
            return False
    
    @staticmethod
    def _normalize_for_partial_month(
        value: float,
        report_date_str: Optional[str]
    ) -> Optional[float]:
        """
        Normalize a value for partial month comparison.
        
        Projects the partial month value to full month equivalent for fair comparison.
        
        Args:
            value: Current month value
            report_date_str: Current month report date
            
        Returns:
            Normalized value or None if normalization not applicable
        """
        if not TrendAnalyzer._is_partial_month(report_date_str):
            return None
        
        try:
            report_date = date.fromisoformat(report_date_str)
            today = date.today()
            
            # Calculate days elapsed in current month
            if report_date.year == today.year and report_date.month == today.month:
                days_elapsed = today.day
            else:
                # For historical partial months, estimate based on report date
                days_elapsed = report_date.day
            
            # Calculate days in month
            if report_date.month == 12:
                days_in_month = 31
            else:
                next_month = date(report_date.year, report_date.month + 1, 1)
                days_in_month = (next_month - timedelta(days=1)).day
            
            if days_elapsed == 0:
                return None
            
            # Project to full month (simple linear projection)
            normalized = (value / days_elapsed) * days_in_month
            return float(normalized)
            
        except (ValueError, TypeError):
            return None
    
    @staticmethod
    def calculate_monthly_changes(
        historical_data: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        """
        Calculate month-over-month changes for all metrics.
        
        Handles partial months by normalizing values or excluding from calculations.
        
        Args:
            historical_data: List of Executive Summary data, ordered oldest to newest
        
        Returns:
            List of monthly change records with partial_month flag
        """
        if not isinstance(historical_data, list) or len(historical_data) < 2:
            return []
        
        changes = []
        for i in range(1, len(historical_data)):
            current = safe_list_get(historical_data, i, {})
            previous = safe_list_get(historical_data, i - 1, {})
            
            if not isinstance(current, dict) or not isinstance(previous, dict):
                continue
            
            current_date = safe_get(current, "report_date")
            is_partial = TrendAnalyzer._is_partial_month(current_date)
            
            current_received = safe_float(safe_get(current, "cash_received"), 0.0)
            current_spent = safe_float(safe_get(current, "cash_spent"), 0.0)
            previous_received = safe_float(safe_get(previous, "cash_received"), 0.0)
            previous_spent = safe_float(safe_get(previous, "cash_spent"), 0.0)
            
            # Normalize partial month values for fair comparison
            if is_partial:
                normalized_received = TrendAnalyzer._normalize_for_partial_month(
                    current_received, current_date
                )
                normalized_spent = TrendAnalyzer._normalize_for_partial_month(
                    current_spent, current_date
                )
                
                # Use normalized values if available, otherwise use raw (with warning)
                if normalized_received is not None:
                    current_received = normalized_received
                if normalized_spent is not None:
                    current_spent = normalized_spent
                
                logger.debug(
                    "Normalized partial month %s: received %.2f -> %.2f, spent %.2f -> %.2f",
                    current_date,
                    safe_float(safe_get(current, "cash_received"), 0.0),
                    current_received,
                    safe_float(safe_get(current, "cash_spent"), 0.0),
                    current_spent
                )
            
            cash_received_change = TrendAnalyzer.calculate_percentage_change(
                current_received,
                previous_received
            )
            
            cash_spent_change = TrendAnalyzer.calculate_percentage_change(
                current_spent,
                previous_spent
            )
            
            net_change = (current_received - current_spent) - (previous_received - previous_spent)
            
            changes.append({
                "month": current_date,
                "cash_received_change_pct": cash_received_change,
                "cash_spent_change_pct": cash_spent_change,
                "net_cash_flow_change": net_change,
                "is_partial_month": is_partial,
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

