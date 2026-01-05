"""
Financial Insights Calculator
Pure calculation functions for cash runway, trends, and leading indicators.
"""

import logging
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Any, Optional
from statistics import mean, stdev

logger = logging.getLogger(__name__)


class CashRunwayCalculator:
    """
    Calculates cash runway metrics from Executive Summary data.
    
    Cash runway = how long the business can operate at current burn rate.
    """
    
    @staticmethod
    def calculate_monthly_burn_rate(cash_spent: float, cash_received: float) -> float:
        """
        Calculate monthly net burn rate.
        
        Args:
            cash_spent: Total cash spent in the month
            cash_received: Total cash received in the month
        
        Returns:
            Monthly burn rate (positive = burning cash, negative = growing cash)
        """
        return float(Decimal(str(cash_spent)) - Decimal(str(cash_received)))
    
    @staticmethod
    def calculate_runway_months(
        cash_position: float,
        monthly_burn_rate: float
    ) -> Optional[float]:
        """
        Calculate cash runway in months.
        
        Args:
            cash_position: Current cash balance
            monthly_burn_rate: Monthly net burn rate
        
        Returns:
            Runway in months, or None if calculation not applicable
        """
        if monthly_burn_rate == 0:
            return None
        
        if monthly_burn_rate < 0:
            return None
        
        return float(Decimal(str(cash_position)) / Decimal(str(monthly_burn_rate)))
    
    @staticmethod
    def calculate_runway_weeks(runway_months: Optional[float]) -> Optional[float]:
        """
        Convert runway from months to weeks.
        
        Args:
            runway_months: Runway in months (can be None)
        
        Returns:
            Runway in weeks, or None if input is None
        """
        if runway_months is None:
            return None
        
        return float(Decimal(str(runway_months)) * Decimal("4.33"))
    
    @staticmethod
    def get_runway_status(runway_months: Optional[float]) -> str:
        """
        Determine runway status based on months remaining.
        
        Args:
            runway_months: Runway in months (can be None or negative)
        
        Returns:
            Status: "healthy", "warning", "critical", "negative", or "infinite"
        """
        if runway_months is None:
            return "infinite"
        
        if runway_months < 0:
            return "negative"
        
        if runway_months >= 6:
            return "healthy"
        elif runway_months >= 3:
            return "warning"
        else:
            return "critical"
    
    @staticmethod
    def calculate(
        cash_position: float,
        cash_spent: float,
        cash_received: float
    ) -> dict[str, Any]:
        """
        Calculate all cash runway metrics.
        
        Args:
            cash_position: Current cash balance
            cash_spent: Total cash spent in current month
            cash_received: Total cash received in current month
        
        Returns:
            Dictionary with all cash runway metrics
        """
        monthly_burn_rate = CashRunwayCalculator.calculate_monthly_burn_rate(
            cash_spent, cash_received
        )
        
        runway_months = CashRunwayCalculator.calculate_runway_months(
            cash_position, monthly_burn_rate
        )
        
        runway_weeks = CashRunwayCalculator.calculate_runway_weeks(runway_months)
        
        status = CashRunwayCalculator.get_runway_status(runway_months)
        
        return {
            "current_cash": cash_position,
            "monthly_burn_rate": monthly_burn_rate,
            "runway_months": runway_months,
            "runway_weeks": runway_weeks,
            "status": status,
        }


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
        if len(historical_data) < 2:
            return None
        
        current_month = historical_data[-1]
        previous_month = historical_data[-2]
        
        current_spent = current_month.get("cash_spent", 0.0)
        previous_spent = previous_month.get("cash_spent", 0.0)
        
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
        if len(historical_data) < 2:
            return None
        
        cash_received_values = [
            month.get("cash_received", 0.0) for month in historical_data
        ]
        
        if not cash_received_values:
            return None
        
        mean_value = mean(cash_received_values)
        
        if mean_value == 0:
            return None
        
        try:
            std_dev = stdev(cash_received_values) if len(cash_received_values) > 1 else 0.0
            coefficient_of_variation = (std_dev / abs(mean_value)) * 100
            return float(coefficient_of_variation)
        except (ValueError, TypeError, ZeroDivisionError):
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
        if len(historical_data) < 2:
            return "stable"
        
        net_flows = []
        for month in historical_data:
            cash_received = month.get("cash_received", 0.0)
            cash_spent = month.get("cash_spent", 0.0)
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
        changes = []
        
        for i in range(1, len(historical_data)):
            current = historical_data[i]
            previous = historical_data[i - 1]
            
            cash_received_change = TrendAnalyzer.calculate_percentage_change(
                current.get("cash_received", 0.0),
                previous.get("cash_received", 0.0)
            )
            
            cash_spent_change = TrendAnalyzer.calculate_percentage_change(
                current.get("cash_spent", 0.0),
                previous.get("cash_spent", 0.0)
            )
            
            net_change = (
                current.get("cash_received", 0.0) - current.get("cash_spent", 0.0)
            ) - (
                previous.get("cash_received", 0.0) - previous.get("cash_spent", 0.0)
            )
            
            changes.append({
                "month": current.get("report_date"),
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
        total = receivables.get("total", 0.0)
        overdue_amount = receivables.get("overdue_amount", 0.0)
        overdue_count = receivables.get("overdue_count", 0)
        total_count = receivables.get("count", 0)
        avg_days_overdue = receivables.get("avg_days_overdue", 0.0)
        
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
        total = payables.get("total", 0.0)
        overdue_amount = payables.get("overdue_amount", 0.0)
        overdue_count = payables.get("overdue_count", 0)
        total_count = payables.get("count", 0)
        avg_days_overdue = payables.get("avg_days_overdue", 0.0)
        
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
        
        cash_position = executive_summary_current.get("cash_position", 0.0)
        if cash_position < 0:
            signals.append("negative_cash_position")
        
        if len(executive_summary_history) >= 2:
            current_cash = executive_summary_current.get("cash_position", 0.0)
            previous_cash = executive_summary_history[-1].get("cash_position", 0.0)
            
            if current_cash < previous_cash:
                signals.append("declining_cash_position")
        
        if len(executive_summary_history) >= 2:
            current_burn = (
                executive_summary_current.get("cash_spent", 0.0) -
                executive_summary_current.get("cash_received", 0.0)
            )
            previous_burn = (
                executive_summary_history[-1].get("cash_spent", 0.0) -
                executive_summary_history[-1].get("cash_received", 0.0)
            )
            
            if current_burn > previous_burn and current_burn > 0:
                signals.append("increasing_burn_rate")
        
        if receivables_health.get("risk_level") == "high":
            signals.append("high_overdue_receivables")
        
        if receivables_health.get("avg_days_overdue", 0) > 30:
            signals.append("slow_receivables_collection")
        
        if payables_pressure.get("risk_level") == "high":
            signals.append("high_overdue_payables")
        
        if payables_pressure.get("overdue_percentage", 0) > 50:
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


class CashPressureCalculator:
    """
    Calculates cash pressure status (GREEN/AMBER/RED).
    
    Combines runway status with revenue volatility to determine overall pressure.
    """
    
    @staticmethod
    def calculate(
        runway_months: Optional[float],
        runway_status: str,
        revenue_volatility: Optional[float]
    ) -> dict[str, Any]:
        """
        Calculate cash pressure status.
        
        Args:
            runway_months: Cash runway in months (None if infinite/profitable)
            runway_status: Runway status (healthy/warning/critical/negative/infinite)
            revenue_volatility: Revenue volatility coefficient (None if insufficient data)
        
        Returns:
            Dictionary with pressure status and confidence
        """
        if runway_status == "infinite":
            return {
                "status": "GREEN",
                "confidence": "high",
            }
        
        if runway_status == "negative":
            return {
                "status": "RED",
                "confidence": "high",
            }
        
        if runway_status == "critical":
            return {
                "status": "RED",
                "confidence": "high",
            }
        
        if runway_status == "warning":
            if runway_months is not None and runway_months < 3.5:
                return {
                    "status": "AMBER",
                    "confidence": "high",
                }
            if revenue_volatility is not None and revenue_volatility > 50:
                return {
                    "status": "AMBER",
                    "confidence": "high",
                }
            return {
                "status": "AMBER",
                "confidence": "medium",
            }
        
        if runway_status == "healthy":
            if revenue_volatility is not None and revenue_volatility > 40:
                return {
                    "status": "AMBER",
                    "confidence": "medium",
                }
            return {
                "status": "GREEN",
                "confidence": "high",
            }
        
        return {
            "status": "AMBER",
            "confidence": "low",
        }


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
        
        raw_data = pnl_data.get("raw_data", {})
        rows = raw_data.get("rows", [])
        
        revenue = None
        cost_of_sales = None
        gross_profit = None
        expenses = None
        net_profit = None
        
        def _find_value_in_rows(rows_list: list, search_terms: list[str]) -> Optional[float]:
            for row in rows_list:
                if not isinstance(row, dict):
                    continue
                
                title = row.get("title", "").lower()
                cells = row.get("cells", [])
                
                for term in search_terms:
                    if term in title:
                        if cells and len(cells) > 1:
                            value_str = cells[1].get("value", "0")
                            try:
                                value = float(str(value_str).replace(",", ""))
                                if value != 0:
                                    return value
                            except (ValueError, TypeError):
                                continue
                
                nested_rows = row.get("rows", [])
                if nested_rows:
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
        if len(executive_summary_history) < 2:
            return "stable"
        
        all_data = executive_summary_history + [executive_summary_current]
        
        net_flows = []
        for month in all_data[-3:]:
            cash_received = month.get("cash_received", 0.0)
            cash_spent = month.get("cash_spent", 0.0)
            net_flow = cash_received - cash_spent
            net_flows.append(net_flow)
        
        if len(net_flows) < 2:
            return "stable"
        
        recent_trend = net_flows[-1] - net_flows[0]
        
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
        invoices = payables.get("invoices", [])
        today = date.today()
        cutoff_date = today + timedelta(days=days_ahead)
        
        upcoming_amount = 0.0
        upcoming_count = 0
        large_upcoming_bills = []
        
        for invoice in invoices:
            due_date_str = invoice.get("due_date")
            due_date = UpcomingCommitmentsCalculator._parse_due_date(due_date_str)
            
            if not due_date:
                continue
            
            if due_date > today and due_date <= cutoff_date:
                amount_due = invoice.get("amount_due", 0.0)
                if amount_due > 0:
                    upcoming_amount += amount_due
                    upcoming_count += 1
                    
                    if amount_due >= 1000:
                        large_upcoming_bills.append({
                            "invoice_number": invoice.get("number"),
                            "contact": invoice.get("contact"),
                            "amount_due": amount_due,
                            "due_date": due_date.isoformat(),
                        })
        
        squeeze_risk = "low"
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
            "large_upcoming_bills": sorted(large_upcoming_bills, key=lambda x: x["amount_due"], reverse=True)[:5],
            "squeeze_risk": squeeze_risk,
        }

