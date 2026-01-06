"""
Leading indicators and upcoming commitments calculators.
"""

from datetime import date, datetime, timedelta
from typing import Any, Optional

from app.insights.utils import safe_float, safe_get, safe_list_get


class LeadingIndicatorsCalculator:
    """
    Calculates leading indicators of cash stress.
    
    Analyzes receivables timing, payables pressure, and cash stress signals.
    """
    
    @staticmethod
    def calculate_receivables_health(
        receivables: dict[str, Any]
    ) -> dict[str, Any]:
        """
        Calculate receivables health metrics.
        
        Args:
            receivables: Receivables data from XeroDataFetcher
        
        Returns:
            Dictionary with receivables health metrics
        """
        if not isinstance(receivables, dict):
            receivables = {}
        
        total = safe_float(safe_get(receivables, "total"), 0.0)
        overdue_amount = safe_float(safe_get(receivables, "overdue_amount"), 0.0)
        overdue_count = int(safe_float(safe_get(receivables, "overdue_count"), 0))
        total_count = int(safe_float(safe_get(receivables, "count"), 0))
        avg_days_overdue = safe_float(safe_get(receivables, "avg_days_overdue"), 0.0)
        
        overdue_percentage = (
            (overdue_amount / total * 100) if total > 0 else 0.0
        )
        
        overdue_count_percentage = (
            (overdue_count / total_count * 100) if total_count > 0 else 0.0
        )
        
        if avg_days_overdue > 30:
            timing_risk = "high"
        elif avg_days_overdue > 15:
            timing_risk = "medium"
        else:
            timing_risk = "low"
        
        if overdue_percentage > 50 or avg_days_overdue > 30:
            overall_risk = "high"
        elif overdue_percentage > 25 or avg_days_overdue > 15:
            overall_risk = "medium"
        else:
            overall_risk = "low"
        
        return {
            "total": total,
            "overdue_amount": overdue_amount,
            "overdue_percentage": round(overdue_percentage, 1),
            "overdue_count": overdue_count,
            "overdue_count_percentage": round(overdue_count_percentage, 1),
            "avg_days_overdue": avg_days_overdue,
            "timing_risk": timing_risk,
            "risk_level": overall_risk,
        }
    
    @staticmethod
    def calculate_payables_pressure(
        payables: dict[str, Any]
    ) -> dict[str, Any]:
        """
        Calculate payables pressure metrics.
        
        Args:
            payables: Payables data from XeroDataFetcher
        
        Returns:
            Dictionary with payables pressure metrics
        """
        if not isinstance(payables, dict):
            payables = {}
        
        total = safe_float(safe_get(payables, "total"), 0.0)
        overdue_amount = safe_float(safe_get(payables, "overdue_amount"), 0.0)
        overdue_count = int(safe_float(safe_get(payables, "overdue_count"), 0))
        total_count = int(safe_float(safe_get(payables, "count"), 0))
        avg_days_overdue = safe_float(safe_get(payables, "avg_days_overdue"), 0.0)
        
        overdue_percentage = (
            (overdue_amount / total * 100) if total > 0 else 0.0
        )
        
        overdue_count_percentage = (
            (overdue_count / total_count * 100) if total_count > 0 else 0.0
        )
        
        if overdue_percentage > 50 or avg_days_overdue > 30:
            risk_level = "high"
        elif overdue_percentage > 25 or avg_days_overdue > 15:
            risk_level = "medium"
        else:
            risk_level = "low"
        
        return {
            "total": total,
            "overdue_amount": overdue_amount,
            "overdue_percentage": round(overdue_percentage, 1),
            "overdue_count": overdue_count,
            "overdue_count_percentage": round(overdue_count_percentage, 1),
            "avg_days_overdue": avg_days_overdue,
            "risk_level": risk_level,
        }
    
    @staticmethod
    def calculate_cash_stress_signals(
        executive_summary_current: dict[str, Any],
        executive_summary_history: list[dict[str, Any]],
        receivables_health: dict[str, Any],
        payables_pressure: dict[str, Any]
    ) -> list[str]:
        """
        Identify cash stress signals.
        
        Args:
            executive_summary_current: Current month Executive Summary
            executive_summary_history: Historical months
            receivables_health: Receivables health metrics
            payables_pressure: Payables pressure metrics
        
        Returns:
            List of stress signal identifiers
        """
        signals = []
        
        if not isinstance(executive_summary_current, dict):
            executive_summary_current = {}
        
        cash_position = safe_float(safe_get(executive_summary_current, "cash_position"), 0.0)
        if cash_position < 0:
            signals.append("negative_cash_position")
        
        if isinstance(executive_summary_history, list) and len(executive_summary_history) >= 1:
            current_cash = safe_float(safe_get(executive_summary_current, "cash_position"), 0.0)
            previous_month = safe_list_get(executive_summary_history, -1, {})
            if isinstance(previous_month, dict):
                previous_cash = safe_float(safe_get(previous_month, "cash_position"), 0.0)
                if current_cash < previous_cash:
                    signals.append("declining_cash_position")
        
        if isinstance(executive_summary_history, list) and len(executive_summary_history) >= 1:
            current_burn = (
                safe_float(safe_get(executive_summary_current, "cash_spent"), 0.0) -
                safe_float(safe_get(executive_summary_current, "cash_received"), 0.0)
            )
            previous_month = safe_list_get(executive_summary_history, -1, {})
            if isinstance(previous_month, dict):
                previous_burn = (
                    safe_float(safe_get(previous_month, "cash_spent"), 0.0) -
                    safe_float(safe_get(previous_month, "cash_received"), 0.0)
                )
                if current_burn > previous_burn and current_burn > 0:
                    signals.append("increasing_burn_rate")
        
        if isinstance(receivables_health, dict) and safe_get(receivables_health, "risk_level") == "high":
            signals.append("high_overdue_receivables")
        
        if isinstance(receivables_health, dict) and safe_float(safe_get(receivables_health, "avg_days_overdue"), 0) > 30:
            signals.append("slow_receivables_collection")
        
        if isinstance(payables_pressure, dict) and safe_get(payables_pressure, "risk_level") == "high":
            signals.append("high_overdue_payables")
        
        if isinstance(payables_pressure, dict) and safe_float(safe_get(payables_pressure, "overdue_percentage"), 0) > 50:
            signals.append("significant_payables_pressure")
        
        return signals
    
    @staticmethod
    def calculate(
        receivables: dict[str, Any],
        payables: dict[str, Any],
        executive_summary_current: dict[str, Any],
        executive_summary_history: list[dict[str, Any]]
    ) -> dict[str, Any]:
        """
        Calculate all leading indicator metrics.
        
        Args:
            receivables: Receivables data
            payables: Payables data
            executive_summary_current: Current month Executive Summary
            executive_summary_history: Historical months
        
        Returns:
            Dictionary with all leading indicator metrics
        """
        receivables_health = LeadingIndicatorsCalculator.calculate_receivables_health(
            receivables
        )
        
        payables_pressure = LeadingIndicatorsCalculator.calculate_payables_pressure(
            payables
        )
        
        cash_stress_signals = LeadingIndicatorsCalculator.calculate_cash_stress_signals(
            executive_summary_current,
            executive_summary_history,
            receivables_health,
            payables_pressure
        )
        
        return {
            "receivables_health": receivables_health,
            "payables_pressure": payables_pressure,
            "cash_stress_signals": cash_stress_signals,
        }


class UpcomingCommitmentsCalculator:
    """
    Calculates upcoming cash commitments and squeeze risk.
    
    Analyzes payables due dates to identify upcoming cash pressure.
    """
    
    @staticmethod
    def _parse_due_date(due_date_str: Optional[str]) -> Optional[date]:
        """
        Parse due date string to date object.
        
        Args:
            due_date_str: Due date as string (ISO format or similar)
        
        Returns:
            Date object, or None if parsing fails
        """
        if not due_date_str:
            return None
        
        try:
            if isinstance(due_date_str, date):
                return due_date_str
            
            if isinstance(due_date_str, datetime):
                return due_date_str.date()
            
            if "T" in str(due_date_str):
                return datetime.fromisoformat(str(due_date_str).replace("Z", "+00:00")).date()
            
            return datetime.strptime(str(due_date_str), "%Y-%m-%d").date()
        except (ValueError, TypeError, AttributeError):
            return None
    
    @staticmethod
    def calculate(
        payables: dict[str, Any],
        cash_position: float,
        days_ahead: int = 30
    ) -> dict[str, Any]:
        """
        Calculate upcoming cash commitments.
        
        Args:
            payables: Payables data from XeroDataFetcher
            cash_position: Current cash balance
            days_ahead: Number of days to look ahead (default: 30)
        
        Returns:
            Dictionary with upcoming commitments metrics
        """
        if not isinstance(payables, dict):
            payables = {}
        
        invoices = safe_get(payables, "invoices", [])
        if not isinstance(invoices, list):
            invoices = []
        
        today = date.today()
        cutoff_date = today + timedelta(days=days_ahead)
        
        upcoming_amount = 0.0
        upcoming_count = 0
        large_upcoming_bills = []
        
        for invoice in invoices:
            if not isinstance(invoice, dict):
                continue
            
            due_date_str = safe_get(invoice, "due_date")
            due_date = UpcomingCommitmentsCalculator._parse_due_date(due_date_str)
            
            if not due_date:
                continue
            
            if due_date > today and due_date <= cutoff_date:
                amount_due = safe_float(safe_get(invoice, "amount_due"), 0.0)
                if amount_due > 0:
                    upcoming_amount += amount_due
                    upcoming_count += 1
                    
                    if amount_due >= 1000:
                        large_upcoming_bills.append({
                            "invoice_number": safe_get(invoice, "number"),
                            "contact": safe_get(invoice, "contact"),
                            "amount_due": amount_due,
                            "due_date": due_date.isoformat(),
                        })
        
        squeeze_risk = "low"
        
        # Handle negative cash position
        if cash_position < 0:
            # If cash is already negative, any upcoming bills are high risk
            if upcoming_amount > 0:
                squeeze_risk = "high"
            elif len(large_upcoming_bills) >= 2:
                squeeze_risk = "high"
        else:
            # Normal logic for positive cash
            if upcoming_amount > cash_position * 0.5:
                squeeze_risk = "high"
            elif upcoming_amount > cash_position * 0.3:
                squeeze_risk = "medium"
            elif len(large_upcoming_bills) >= 3:
                squeeze_risk = "medium"
        
        return {
            "upcoming_amount": round(upcoming_amount, 2),
            "upcoming_count": upcoming_count,
            "days_ahead": days_ahead,
            "large_upcoming_bills": sorted(
                [bill for bill in large_upcoming_bills if isinstance(bill, dict) and "amount_due" in bill],
                key=lambda x: safe_float(safe_get(x, "amount_due"), 0.0),
                reverse=True
            )[:5],
            "squeeze_risk": squeeze_risk,
        }

