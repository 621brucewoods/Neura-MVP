"""
Business Health Score Calculator v1

Calculates a comprehensive Business Health Score (0-100) based on:
- A) Cash & Runway (30 points)
- B) Profitability & Efficiency (25 points)
- C) Revenue Quality & Momentum (15 points)
- D) Working Capital & Liquidity (20 points)
- E) Compliance & Data Confidence (10 points)

Uses AccountType-based data extraction for reliability across all organizations.
Integrates with the Extractors module for clean, typed data structures.
"""

import logging
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from decimal import Decimal
from enum import Enum
from typing import Any, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from app.integrations.xero.extracted_types import FinancialData

logger = logging.getLogger(__name__)


class Grade(str, Enum):
    """Health Score grades."""
    A = "A"  # Strong: 80-100
    B = "B"  # Stable: 65-79
    C = "C"  # Risk: 45-64
    D = "D"  # Critical: <45


class Confidence(str, Enum):
    """Data confidence levels."""
    HIGH = "high"      # E score >= 8, cap 100
    MEDIUM = "medium"  # E score 5-7, cap 90
    LOW = "low"        # E score <= 4, cap 80


class MetricStatus(str, Enum):
    """Status of a metric calculation."""
    OK = "ok"              # Calculated successfully
    MISSING = "missing"    # Data not available
    ESTIMATED = "estimated"  # Estimated from partial data


@dataclass
class SubScore:
    """Individual metric sub-score."""
    metric_id: str
    name: str
    max_points: float
    points_awarded: float
    status: MetricStatus
    value: Optional[float] = None
    formula: str = ""
    inputs_used: list[str] = field(default_factory=list)


@dataclass
class CategoryScore:
    """Category score (A, B, C, D, or E)."""
    category_id: str
    name: str
    max_points: float
    points_awarded: float
    metrics: list[str] = field(default_factory=list)


@dataclass
class Driver:
    """Score driver (positive or negative)."""
    metric_id: str
    label: str
    impact_points: float  # Positive for lift, negative for drag
    why_it_matters: str
    recommended_action: str


class HealthScoreCalculator:
    """
    Calculates Business Health Score v1 (0-100).
    
    Uses only reliable data sources:
    - Balance Sheet totals from AccountType-based parsing
    - P&L from Trial Balance AccountType summing
    - Invoice AR/AP ageing from due_date calculations
    
    Metrics that cannot be calculated (missing historical data) are marked
    as 'missing' and their weights are redistributed within the category.
    """
    
    # Score thresholds
    GRADE_THRESHOLDS = {
        Grade.A: 80,
        Grade.B: 65,
        Grade.C: 45,
        Grade.D: 0,
    }
    
    CONFIDENCE_CAPS = {
        Confidence.HIGH: 100,
        Confidence.MEDIUM: 90,
        Confidence.LOW: 80,
    }
    
    @staticmethod
    def _safe_divide(numerator: Optional[float], denominator: Optional[float], default: float = 0.0) -> Optional[float]:
        """Safe division handling None and zero."""
        if numerator is None or denominator is None:
            return None
        if denominator == 0:
            return default
        return numerator / denominator
    
    @staticmethod
    def _calculate_std_dev(values: list[float]) -> float:
        """Calculate standard deviation of a list of values."""
        if not values or len(values) < 2:
            return 0.0
        n = len(values)
        mean = sum(values) / n
        variance = sum((x - mean) ** 2 for x in values) / n
        return variance ** 0.5
    
    @staticmethod
    def _score_cash_volatility(volatility_ratio: Optional[float]) -> tuple[float, str]:
        """Score A2: Cash volatility (10 pts max)."""
        if volatility_ratio is None:
            return 0, "≤10% → 10"
        
        volatility_pct = volatility_ratio * 100
        if volatility_pct <= 10:
            return 10, "≤10% → 10"
        elif volatility_pct <= 20:
            return 8, "10-20% → 8"
        elif volatility_pct <= 35:
            return 5, "20-35% → 5"
        elif volatility_pct <= 50:
            return 2, "35-50% → 2"
        else:
            return 0, ">50% → 0"
    
    @staticmethod
    def _score_revenue_trend(growth_3v3: Optional[float]) -> tuple[float, str]:
        """Score C1: Revenue trend (10 pts max)."""
        if growth_3v3 is None:
            return 0, "≥+15% → 10"
        
        growth_pct = growth_3v3 * 100
        if growth_pct >= 15:
            return 10, "≥+15% → 10"
        elif growth_pct >= 5:
            return 8, "+5% to +14.9% → 8"
        elif growth_pct >= -5:
            return 6, "-4.9% to +4.9% → 6"
        elif growth_pct >= -15:
            return 3, "-5% to -14.9% → 3"
        else:
            return 0, "≤-15% → 0"
    
    @staticmethod
    def _score_revenue_consistency(rev_cv: Optional[float]) -> tuple[float, str]:
        """Score C2: Revenue consistency (5 pts max)."""
        if rev_cv is None:
            return 0, "≤15% → 5"
        
        cv_pct = rev_cv * 100
        if cv_pct <= 15:
            return 5, "≤15% → 5"
        elif cv_pct <= 30:
            return 3, "15-30% → 3"
        elif cv_pct <= 50:
            return 1, "30-50% → 1"
        else:
            return 0, ">50% → 0"
    
    @staticmethod
    def _score_runway_months(runway_months: Optional[float]) -> tuple[float, str]:
        """Score A1: Runway months (15 pts max)."""
        if runway_months is None:
            return 0, "≥6.0 months → 15"
        
        if runway_months >= 6.0:
            return 15, "≥6.0 months → 15"
        elif runway_months >= 3.0:
            return 12, "3.0-5.9 months → 12"
        elif runway_months >= 2.0:
            return 9, "2.0-2.9 months → 9"
        elif runway_months >= 1.0:
            return 5, "1.0-1.9 months → 5"
        else:
            return 0, "<1.0 months → 0"
    
    @staticmethod
    def _score_ar_to_cash(ar_to_cash: Optional[float]) -> tuple[float, str]:
        """Score A3: AR to Cash ratio (5 pts max)."""
        if ar_to_cash is None:
            return 0, "≤0.5 → 5"
        
        if ar_to_cash <= 0.5:
            return 5, "≤0.5 → 5"
        elif ar_to_cash <= 1.0:
            return 3, "0.5-1.0 → 3"
        elif ar_to_cash <= 2.0:
            return 1, "1.0-2.0 → 1"
        else:
            return 0, ">2.0 → 0"
    
    @staticmethod
    def _score_net_margin(net_margin_pct: Optional[float]) -> tuple[float, str]:
        """Score B1: Net profit margin (10 pts max)."""
        if net_margin_pct is None:
            return 0, "≥15% → 10"
        
        if net_margin_pct >= 15:
            return 10, "≥15% → 10"
        elif net_margin_pct >= 8:
            return 8, "8-14.9% → 8"
        elif net_margin_pct >= 3:
            return 6, "3-7.9% → 6"
        elif net_margin_pct >= 0:
            return 4, "0-2.9% → 4"
        elif net_margin_pct >= -5:
            return 2, "-0.1 to -5% → 2"
        else:
            return 0, "<-5% → 0"
    
    @staticmethod
    def _score_gross_margin(gross_margin_pct: Optional[float]) -> tuple[float, str]:
        """Score B2: Gross margin (8 pts max)."""
        if gross_margin_pct is None:
            return 0, "≥40% → 8"
        
        if gross_margin_pct >= 40:
            return 8, "≥40% → 8"
        elif gross_margin_pct >= 30:
            return 6, "30-39.9% → 6"
        elif gross_margin_pct >= 20:
            return 4, "20-29.9% → 4"
        elif gross_margin_pct >= 10:
            return 2, "10-19.9% → 2"
        else:
            return 0, "<10% → 0"
    
    @staticmethod
    def _score_opex_ratio(opex_ratio_pct: Optional[float]) -> tuple[float, str]:
        """Score B3: Operating expense ratio (7 pts max)."""
        if opex_ratio_pct is None:
            return 0, "≤55% → 7"
        
        if opex_ratio_pct <= 55:
            return 7, "≤55% → 7"
        elif opex_ratio_pct <= 70:
            return 5, "55-70% → 5"
        elif opex_ratio_pct <= 85:
            return 3, "70-85% → 3"
        elif opex_ratio_pct <= 100:
            return 1, "85-100% → 1"
        else:
            return 0, ">100% → 0"
    
    @staticmethod
    def _score_current_ratio(current_ratio: Optional[float]) -> tuple[float, str]:
        """Score D1: Current ratio (8 pts max)."""
        if current_ratio is None:
            return 0, "≥2.0 → 8"
        
        if current_ratio >= 2.0:
            return 8, "≥2.0 → 8"
        elif current_ratio >= 1.5:
            return 6, "1.5-1.99 → 6"
        elif current_ratio >= 1.2:
            return 4, "1.2-1.49 → 4"
        elif current_ratio >= 1.0:
            return 2, "1.0-1.19 → 2"
        else:
            return 0, "<1.0 → 0"
    
    @staticmethod
    def _score_quick_ratio(quick_ratio: Optional[float]) -> tuple[float, str]:
        """Score D2: Quick ratio (5 pts max)."""
        if quick_ratio is None:
            return 0, "≥1.2 → 5"
        
        if quick_ratio >= 1.2:
            return 5, "≥1.2 → 5"
        elif quick_ratio >= 1.0:
            return 4, "1.0-1.19 → 4"
        elif quick_ratio >= 0.8:
            return 2, "0.8-0.99 → 2"
        else:
            return 0, "<0.8 → 0"
    
    @staticmethod
    def _score_receivables_health(ar_over_30_pct: Optional[float], ar_over_60_pct: Optional[float]) -> tuple[float, str]:
        """Score D3: Receivables health (4 pts max)."""
        if ar_over_30_pct is None or ar_over_60_pct is None:
            return 0, ">60d ≤10% and >30d ≤35% → 4"
        
        if ar_over_60_pct <= 0.10 and ar_over_30_pct <= 0.35:
            return 4, ">60d ≤10% and >30d ≤35% → 4"
        elif ar_over_60_pct <= 0.20 and ar_over_30_pct <= 0.50:
            return 3, ">60d ≤20% and >30d ≤50% → 3"
        elif ar_over_60_pct <= 0.35 and ar_over_30_pct <= 0.65:
            return 2, ">60d ≤35% and >30d ≤65% → 2"
        else:
            return 0, "Poor receivables health → 0"
    
    @staticmethod
    def _score_payables_pressure(ap_over_60_pct: Optional[float]) -> tuple[float, str]:
        """Score D4: Payables pressure (3 pts max)."""
        if ap_over_60_pct is None:
            return 0, ">60d ≤15% → 3"
        
        if ap_over_60_pct <= 0.15:
            return 3, ">60d ≤15% → 3"
        elif ap_over_60_pct <= 0.30:
            return 2, ">60d 15-30% → 2"
        else:
            return 0, ">60d >30% → 0"
    
    @staticmethod
    def _calculate_ar_ageing_buckets(invoices: list[dict[str, Any]]) -> dict[str, float]:
        """
        Calculate AR ageing buckets from invoice data.
        
        Returns percentages of AR in each bucket:
        - current: not yet due
        - days_1_30: 1-30 days overdue
        - days_31_60: 31-60 days overdue
        - days_61_90: 61-90 days overdue
        - days_90_plus: >90 days overdue
        """
        today = date.today()
        buckets = {
            "current": Decimal("0"),
            "days_1_30": Decimal("0"),
            "days_31_60": Decimal("0"),
            "days_61_90": Decimal("0"),
            "days_90_plus": Decimal("0"),
        }
        total = Decimal("0")
        
        for inv in invoices:
            amount = Decimal(str(inv.get("amount_due", 0) or 0))
            due_date_str = inv.get("due_date")
            
            if not due_date_str or amount <= 0:
                continue
            
            try:
                if isinstance(due_date_str, date):
                    due_date = due_date_str
                else:
                    due_date = datetime.fromisoformat(due_date_str.replace("Z", "+00:00")).date()
            except (ValueError, AttributeError):
                continue
            
            total += amount
            days_overdue = (today - due_date).days
            
            if days_overdue <= 0:
                buckets["current"] += amount
            elif days_overdue <= 30:
                buckets["days_1_30"] += amount
            elif days_overdue <= 60:
                buckets["days_31_60"] += amount
            elif days_overdue <= 90:
                buckets["days_61_90"] += amount
            else:
                buckets["days_90_plus"] += amount
        
        if total == 0:
            return {k: 0.0 for k in buckets.keys()}
        
        return {k: float(v / total) for k, v in buckets.items()}
    
    @staticmethod
    def _calculate_ap_ageing_buckets(invoices: list[dict[str, Any]]) -> dict[str, float]:
        """Calculate AP ageing buckets from invoice data (same logic as AR)."""
        return HealthScoreCalculator._calculate_ar_ageing_buckets(invoices)
    
    @staticmethod
    def _get_grade(score: float) -> Grade:
        """Get grade from score."""
        if score >= 80:
            return Grade.A
        elif score >= 65:
            return Grade.B
        elif score >= 45:
            return Grade.C
        else:
            return Grade.D
    
    @staticmethod
    def _get_confidence(e_score: float) -> Confidence:
        """Get confidence level from E (Compliance) score."""
        if e_score >= 8:
            return Confidence.HIGH
        elif e_score >= 5:
            return Confidence.MEDIUM
        else:
            return Confidence.LOW
    
    @staticmethod
    def _build_data_quality_signals(
        has_monthly_data: bool,
        has_6_months: bool
    ) -> list[dict[str, str]]:
        """Build data quality signals based on actual data availability."""
        signals = []
        
        # Only add historical data warning if we don't have enough data
        if not has_6_months:
            signals.append({
                "signal_id": "DQ_MISSING_HISTORICAL",
                "severity": "warning",
                "message": "Less than 6 months of historical data. Revenue trends and consistency metrics may be limited."
            })
        elif not has_monthly_data:
            signals.append({
                "signal_id": "DQ_LIMITED_HISTORICAL",
                "severity": "info",
                "message": "Limited historical data available. Some metrics use shorter time periods."
            })
        
        # Bank reconciliation is always unavailable from Xero API (info only)
        signals.append({
            "signal_id": "DQ_MISSING_RECON",
            "severity": "info",
            "message": "Bank reconciliation status not available from API."
        })
        
        return signals
    
    @staticmethod
    def _build_data_quality_warnings(
        has_monthly_data: bool,
        missing_adjustments: list[dict[str, Any]]
    ) -> list[str]:
        """Build data quality warnings based on actual conditions."""
        warnings = []
        
        # Only warn about missing data if we actually don't have it
        if not has_monthly_data:
            warnings.append("Score may be conservative due to missing historical data.")
        
        # Only warn about redistributions if there were any
        if missing_adjustments:
            total_redistributed = sum(adj.get("points_redistributed", 0) for adj in missing_adjustments)
            if total_redistributed > 0:
                warnings.append(f"{len(missing_adjustments)} metrics ({total_redistributed} points) were redistributed due to missing data.")
        
        return warnings
    
    @staticmethod
    def calculate(
        balance_sheet_totals: dict[str, Optional[float]],
        invoices_receivable: dict[str, Any],
        invoices_payable: dict[str, Any],
        monthly_pnl_data: Optional[list[dict[str, Any]]] = None,
    ) -> dict[str, Any]:
        """
        Calculate Business Health Score v1.
        
        Args:
            balance_sheet_totals: From BalanceSheetExtractor.extract()
            invoices_receivable: From InvoicesFetcher.fetch_receivables()
            invoices_payable: From InvoicesFetcher.fetch_payables()
            monthly_pnl_data: List of monthly P&L data (newest first) with
                              keys: month_key, revenue, cost_of_sales, expenses, net_profit
                              
        Note:
            P&L metrics (revenue, expenses, COGS) are derived from monthly_pnl_data
            using a rolling 3-month sum, as per BHS spec.
        
        Returns:
            Complete Health Score result including score, grade, confidence,
            all sub-scores, drivers, and explanations.
        """
        sub_scores: dict[str, SubScore] = {}
        missing_adjustments: list[dict] = []
        
        # Extract values from Balance Sheet
        cash = balance_sheet_totals.get("cash")
        ar = balance_sheet_totals.get("accounts_receivable")
        current_assets = balance_sheet_totals.get("current_assets_total")
        current_liabilities = balance_sheet_totals.get("current_liabilities_total")
        
        # Process monthly P&L data
        monthly_pnl = monthly_pnl_data or []
        has_monthly_data = len(monthly_pnl) >= 3  # Need at least 3 months
        has_6_months = len(monthly_pnl) >= 6
        
        # Extract monthly values lists (newest first)
        # Include 0 values (valid data), exclude None (no data)
        monthly_revenues = []
        monthly_cogs = []
        monthly_expenses = []
        monthly_net_cash_proxy = []  # Revenue - Expenses (cash proxy)
        
        for month in monthly_pnl:
            rev = month.get("revenue")
            cogs = month.get("cost_of_sales")
            exp = month.get("expenses")
            # Include 0 values - they are valid data points
            if rev is not None:
                monthly_revenues.append(float(rev))
            if cogs is not None:
                monthly_cogs.append(float(cogs))
            if exp is not None:
                monthly_expenses.append(float(exp))
            if rev is not None and exp is not None:
                monthly_net_cash_proxy.append(float(rev) - float(exp))
        
        # Calculate rolling 3-month P&L totals (as per BHS spec)
        # Use available data even if less than 3 months
        revenue: Optional[float] = None
        cost_of_sales: Optional[float] = None
        expenses: Optional[float] = None
        
        if monthly_revenues:
            # Sum up to 3 months of available data
            revenue = sum(monthly_revenues[:3])
        if monthly_cogs:
            cost_of_sales = sum(monthly_cogs[:3])
        if monthly_expenses:
            expenses = sum(monthly_expenses[:3])
        
        # Calculate intermediate values
        gross_profit = None
        net_profit = None
        net_margin_pct = None
        gross_margin_pct = None
        opex_ratio_pct = None
        
        if revenue is not None and cost_of_sales is not None:
            gross_profit = revenue - cost_of_sales
        
        if gross_profit is not None and expenses is not None:
            net_profit = gross_profit - expenses
        elif revenue is not None and expenses is not None:
            net_profit = revenue - expenses
        
        if net_profit is not None and revenue is not None and revenue != 0:
            net_margin_pct = (net_profit / revenue) * 100
        
        if gross_profit is not None and revenue is not None and revenue != 0:
            gross_margin_pct = (gross_profit / revenue) * 100
        
        if expenses is not None and revenue is not None and revenue != 0:
            opex_ratio_pct = (expenses / revenue) * 100
        
        # Calculate liquidity ratios
        current_ratio = HealthScoreCalculator._safe_divide(current_assets, current_liabilities)
        
        # Quick ratio = (Cash + AR) / Current Liabilities
        quick_ratio = None
        if cash is not None and ar is not None and current_liabilities is not None and current_liabilities != 0:
            quick_ratio = (cash + ar) / current_liabilities
        
        # AR to Cash ratio
        ar_to_cash = HealthScoreCalculator._safe_divide(ar, cash)
        
        # Calculate AR/AP ageing
        ar_invoices = invoices_receivable.get("invoices", [])
        ap_invoices = invoices_payable.get("invoices", [])
        
        ar_buckets = HealthScoreCalculator._calculate_ar_ageing_buckets(ar_invoices)
        ap_buckets = HealthScoreCalculator._calculate_ap_ageing_buckets(ap_invoices)
        
        ar_over_30_pct = ar_buckets["days_31_60"] + ar_buckets["days_61_90"] + ar_buckets["days_90_plus"]
        ar_over_60_pct = ar_buckets["days_61_90"] + ar_buckets["days_90_plus"]
        ap_over_60_pct = ap_buckets["days_61_90"] + ap_buckets["days_90_plus"]
        
        # Calculate runway using average monthly outflow from P&L data
        # Runway = Cash / AvgMonthlyNetOutflow (per BHS spec)
        runway_months = None
        monthly_burn = None
        avg_monthly_revenue = None
        avg_monthly_expenses = None
        
        if has_monthly_data and len(monthly_revenues) >= 3 and len(monthly_expenses) >= 3:
            # Use average of last 3 months for burn rate calculation
            avg_monthly_revenue = sum(monthly_revenues[:3]) / 3
            avg_monthly_expenses = sum(monthly_expenses[:3]) / 3
            monthly_outflow = max(0, avg_monthly_expenses - avg_monthly_revenue)
            
            if cash is not None:
                if monthly_outflow > 0:
                    runway_months = cash / monthly_outflow
                    monthly_burn = monthly_outflow
                elif avg_monthly_revenue > avg_monthly_expenses:
                    # Profitable - infinite runway (use large number for scoring)
                    runway_months = 999  # Effectively infinite
        
        # =====================
        # CATEGORY A: Cash & Runway (30 points)
        # =====================
        
        # A1: Runway months (15 pts)
        a1_points, a1_threshold = HealthScoreCalculator._score_runway_months(runway_months)
        a1_status = MetricStatus.OK if runway_months is not None else MetricStatus.MISSING
        if not has_monthly_data:
            a1_status = MetricStatus.MISSING
        
        sub_scores["A1"] = SubScore(
            metric_id="A1",
            name="Runway Months",
            max_points=15,
            points_awarded=a1_points,
            status=a1_status,
            value=runway_months if runway_months != 999 else None,  # Don't show 999 in output
            formula="CashAvailable / AvgMonthlyNetOutflow (3mo avg)",
            inputs_used=["balance_sheet_totals.cash", "monthly_pnl_data"]
        )
        
        # A2: Cash volatility (10 pts) - uses monthly data if available
        cash_volatility_ratio = None
        a2_status = MetricStatus.MISSING
        a2_points = 0
        
        if has_monthly_data and len(monthly_net_cash_proxy) >= 3 and len(monthly_revenues) >= 3:
            # Calculate volatility: StdDev(MonthlyNetCashProxy) / AvgRevenue(3mo)
            std_dev = HealthScoreCalculator._calculate_std_dev(monthly_net_cash_proxy[:3])
            avg_revenue_3m = sum(monthly_revenues[:3]) / 3 if monthly_revenues[:3] else 1
            if avg_revenue_3m > 0:
                cash_volatility_ratio = std_dev / avg_revenue_3m
                a2_points, _ = HealthScoreCalculator._score_cash_volatility(cash_volatility_ratio)
                a2_status = MetricStatus.OK
        
        sub_scores["A2"] = SubScore(
            metric_id="A2",
            name="Cash Volatility",
            max_points=10,
            points_awarded=a2_points,
            status=a2_status,
            value=cash_volatility_ratio,
            formula="StdDev(MonthlyNetCashProxy) / AvgRevenue(3mo)",
            inputs_used=["monthly_pnl_data"] if has_monthly_data else []
        )
        
        if a2_status == MetricStatus.MISSING:
            missing_adjustments.append({
                "metric_id": "A2",
                "reason": "Historical monthly P&L data not available",
                "points_redistributed": 10,
                "redistributed_to": [{"metric_id": "A1", "points_added": 10}]
            })
        
        # A3: AR to Cash ratio (5 pts)
        a3_points, a3_threshold = HealthScoreCalculator._score_ar_to_cash(ar_to_cash)
        sub_scores["A3"] = SubScore(
            metric_id="A3",
            name="Cash Conversion Buffer",
            max_points=5,
            points_awarded=a3_points,
            status=MetricStatus.OK if ar_to_cash is not None else MetricStatus.MISSING,
            value=ar_to_cash,
            formula="TotalAR / CashAvailable",
            inputs_used=["balance_sheet_totals.accounts_receivable", "balance_sheet_totals.cash"]
        )
        
        # Redistribute A2 points to A1 (only if A2 is missing)
        if sub_scores["A2"].status == MetricStatus.MISSING:
            # Scale A1 to absorb A2's points (A1 now worth 25 out of 30)
            a1_scale = 25 / 15
            sub_scores["A1"].points_awarded = min(25, sub_scores["A1"].points_awarded * a1_scale)
            sub_scores["A1"].max_points = 25
        
        category_a_points = sum(s.points_awarded for s in [sub_scores["A1"], sub_scores["A2"], sub_scores["A3"]])
        
        # =====================
        # CATEGORY B: Profitability & Efficiency (25 points)
        # =====================
        
        # B1: Net profit margin (10 pts) - uses rolling 3-month P&L
        b1_points, b1_threshold = HealthScoreCalculator._score_net_margin(net_margin_pct)
        b1_status = MetricStatus.OK if net_margin_pct is not None else MetricStatus.MISSING
        if not has_monthly_data:
            b1_status = MetricStatus.MISSING
        
        sub_scores["B1"] = SubScore(
            metric_id="B1",
            name="Net Profit Margin",
            max_points=10,
            points_awarded=b1_points if b1_status == MetricStatus.OK else 0,
            status=b1_status,
            value=net_margin_pct,
            formula="NetProfit / Revenue * 100 (3mo rolling)",
            inputs_used=["monthly_pnl_data"] if has_monthly_data else []
        )
        
        # B2: Gross margin (8 pts) - uses rolling 3-month P&L
        b2_points, b2_threshold = HealthScoreCalculator._score_gross_margin(gross_margin_pct)
        has_cogs = cost_of_sales is not None and cost_of_sales != 0
        b2_status = MetricStatus.OK if (has_cogs and has_monthly_data) else MetricStatus.MISSING
        
        sub_scores["B2"] = SubScore(
            metric_id="B2",
            name="Gross Margin",
            max_points=8,
            points_awarded=b2_points if b2_status == MetricStatus.OK else 0,
            status=b2_status,
            value=gross_margin_pct if has_cogs else None,
            formula="(Revenue - COGS) / Revenue * 100 (3mo rolling)",
            inputs_used=["monthly_pnl_data"] if has_monthly_data else []
        )
        
        # B3: Operating expense ratio (7 pts) - uses rolling 3-month P&L
        b3_points, b3_threshold = HealthScoreCalculator._score_opex_ratio(opex_ratio_pct)
        b3_status = MetricStatus.OK if opex_ratio_pct is not None else MetricStatus.MISSING
        if not has_monthly_data:
            b3_status = MetricStatus.MISSING
        
        sub_scores["B3"] = SubScore(
            metric_id="B3",
            name="Operating Expense Load",
            max_points=7,
            points_awarded=b3_points if b3_status == MetricStatus.OK else 0,
            status=b3_status,
            value=opex_ratio_pct,
            formula="OperatingExpenses / Revenue * 100 (3mo rolling)",
            inputs_used=["monthly_pnl_data"] if has_monthly_data else []
        )
        
        # If B2 missing (no COGS), redistribute to B3
        if not has_cogs:
            missing_adjustments.append({
                "metric_id": "B2",
                "reason": "COGS/Direct Costs not used (service business)",
                "points_redistributed": 8,
                "redistributed_to": [{"metric_id": "B3", "points_added": 8}]
            })
            b3_scale = 15 / 7
            sub_scores["B3"].points_awarded = min(15, sub_scores["B3"].points_awarded * b3_scale)
            sub_scores["B3"].max_points = 15
        
        category_b_points = sum(s.points_awarded for s in [sub_scores["B1"], sub_scores["B2"], sub_scores["B3"]])
        
        # =====================
        # CATEGORY C: Revenue Quality & Momentum (15 points)
        # Uses monthly historical data when available
        # =====================
        
        # C1: Revenue Trend (10 pts) - compares last 3 months vs prior 3 months
        growth_3v3 = None
        c1_status = MetricStatus.MISSING
        c1_points = 0
        
        if len(monthly_revenues) >= 6:
            # Last 3 months (indices 0,1,2) vs prior 3 months (indices 3,4,5)
            rev_last_3 = sum(monthly_revenues[:3])
            rev_prev_3 = sum(monthly_revenues[3:6])
            if rev_prev_3 > 0:
                growth_3v3 = (rev_last_3 - rev_prev_3) / rev_prev_3
                c1_points, _ = HealthScoreCalculator._score_revenue_trend(growth_3v3)
                c1_status = MetricStatus.OK
        
        sub_scores["C1"] = SubScore(
            metric_id="C1",
            name="Revenue Trend",
            max_points=10,
            points_awarded=c1_points,
            status=c1_status,
            value=growth_3v3,
            formula="(Rev_last3 - Rev_prev3) / Rev_prev3",
            inputs_used=["monthly_pnl_data"] if c1_status == MetricStatus.OK else []
        )
        
        # C2: Revenue Consistency (5 pts) - CV of 6 months revenue
        rev_cv = None
        c2_status = MetricStatus.MISSING
        c2_points = 0
        
        if has_6_months and len(monthly_revenues) >= 6:
            avg_rev_6m = sum(monthly_revenues[:6]) / 6
            if avg_rev_6m > 0:
                std_dev_rev = HealthScoreCalculator._calculate_std_dev(monthly_revenues[:6])
                rev_cv = std_dev_rev / avg_rev_6m
                c2_points, _ = HealthScoreCalculator._score_revenue_consistency(rev_cv)
                c2_status = MetricStatus.OK
        
        sub_scores["C2"] = SubScore(
            metric_id="C2",
            name="Revenue Consistency",
            max_points=5,
            points_awarded=c2_points,
            status=c2_status,
            value=rev_cv,
            formula="StdDev(MonthlyRevenue_6mo) / Avg(MonthlyRevenue_6mo)",
            inputs_used=["monthly_pnl_data"] if c2_status == MetricStatus.OK else []
        )
        
        # Handle missing C metrics - redistribute to B and D
        c1_missing = c1_status == MetricStatus.MISSING
        c2_missing = c2_status == MetricStatus.MISSING
        
        if c1_missing:
            missing_adjustments.append({
                "metric_id": "C1",
                "reason": "Historical monthly revenue data not available (need 6 months)",
                "points_redistributed": 10,
                "redistributed_to": [{"metric_id": "B1", "points_added": 5}, {"metric_id": "D1", "points_added": 5}]
            })
            # Redistribute C1 points to B1 and D1
            sub_scores["B1"].points_awarded = min(15, sub_scores["B1"].points_awarded + 5 * (sub_scores["B1"].points_awarded / 10))
        
        if c2_missing:
            missing_adjustments.append({
                "metric_id": "C2",
                "reason": "Historical monthly revenue data not available (need 6 months)",
                "points_redistributed": 5,
                "redistributed_to": [{"metric_id": "B3", "points_added": 5}]
            })
            # Redistribute C2 points to B3
            sub_scores["B3"].points_awarded = min(12, sub_scores["B3"].points_awarded + 5 * (sub_scores["B3"].points_awarded / sub_scores["B3"].max_points))
        
        category_c_points = sub_scores["C1"].points_awarded + sub_scores["C2"].points_awarded
        
        # =====================
        # CATEGORY D: Working Capital & Liquidity (20 points)
        # =====================
        
        # D1: Current ratio (8 pts)
        d1_points, d1_threshold = HealthScoreCalculator._score_current_ratio(current_ratio)
        sub_scores["D1"] = SubScore(
            metric_id="D1",
            name="Current Ratio",
            max_points=8,
            points_awarded=d1_points,
            status=MetricStatus.OK if current_ratio is not None else MetricStatus.MISSING,
            value=current_ratio,
            formula="CurrentAssets / CurrentLiabilities",
            inputs_used=["balance_sheet_totals.current_assets_total", "balance_sheet_totals.current_liabilities_total"]
        )
        
        # Add redistributed C1 points (only if C1 is missing)
        if c1_missing:
            sub_scores["D1"].points_awarded = min(13, sub_scores["D1"].points_awarded + 5 * (d1_points / 8))
            sub_scores["D1"].max_points = 13
        
        # D2: Quick ratio (5 pts)
        d2_points, d2_threshold = HealthScoreCalculator._score_quick_ratio(quick_ratio)
        sub_scores["D2"] = SubScore(
            metric_id="D2",
            name="Quick Ratio",
            max_points=5,
            points_awarded=d2_points,
            status=MetricStatus.OK if quick_ratio is not None else MetricStatus.MISSING,
            value=quick_ratio,
            formula="(Cash + AR) / CurrentLiabilities",
            inputs_used=["balance_sheet_totals.cash", "balance_sheet_totals.accounts_receivable", "balance_sheet_totals.current_liabilities_total"]
        )
        
        # D3: Receivables health (4 pts)
        d3_points, d3_threshold = HealthScoreCalculator._score_receivables_health(ar_over_30_pct, ar_over_60_pct)
        sub_scores["D3"] = SubScore(
            metric_id="D3",
            name="Receivables Health",
            max_points=4,
            points_awarded=d3_points,
            status=MetricStatus.OK if ar_invoices else MetricStatus.MISSING,
            value=ar_over_60_pct,
            formula="% of AR >30 days and >60 days overdue",
            inputs_used=["invoices_receivable.invoices"]
        )
        
        # D4: Payables pressure (3 pts)
        d4_points, d4_threshold = HealthScoreCalculator._score_payables_pressure(ap_over_60_pct)
        sub_scores["D4"] = SubScore(
            metric_id="D4",
            name="Payables Pressure",
            max_points=3,
            points_awarded=d4_points,
            status=MetricStatus.OK if ap_invoices else MetricStatus.MISSING,
            value=ap_over_60_pct,
            formula="% of AP >60 days overdue",
            inputs_used=["invoices_payable.invoices"]
        )
        
        category_d_points = sum(s.points_awarded for s in [sub_scores["D1"], sub_scores["D2"], sub_scores["D3"], sub_scores["D4"]])
        
        # =====================
        # CATEGORY E: Compliance & Data Confidence (10 points)
        # Since E1 (bank reconciliation) and E2 (categorisation) data is not available
        # from Xero's standard API, we redistribute their points to E3.
        # This follows the BHS spec: "If data is missing, redistribute weight"
        # =====================
        
        # E1: Bank reconciliation freshness - NOT AVAILABLE from Xero API
        # Points redistributed to E3
        sub_scores["E1"] = SubScore(
            metric_id="E1",
            name="Bank Reconciliation Freshness",
            max_points=0,  # Redistributed to E3
            points_awarded=0,
            status=MetricStatus.MISSING,
            value=None,
            formula="Days since last reconciliation (not available)",
            inputs_used=[]
        )
        
        # E2: Categorisation completeness - NOT AVAILABLE from Xero API
        # Points redistributed to E3
        sub_scores["E2"] = SubScore(
            metric_id="E2",
            name="Categorisation Completeness",
            max_points=0,  # Redistributed to E3
            points_awarded=0,
            status=MetricStatus.MISSING,
            value=None,
            formula="% of transactions uncategorised (not available)",
            inputs_used=[]
        )
        
        # E3: Reporting readiness (10 pts - includes redistributed E1+E2)
        # Check what data we have available
        e3_checks = 0
        e3_max_checks = 5  # Total checks we perform
        
        # Check 1: Monthly P&L data available (at least 3 months)
        if has_monthly_data:
            e3_checks += 1
        
        # Check 2: Balance Sheet data available
        if balance_sheet_totals.get("cash") is not None:
            e3_checks += 1
        
        # Check 3: AR data available
        if ar_invoices or invoices_receivable.get("total", 0) > 0:
            e3_checks += 1
        
        # Check 4: AP data available
        if ap_invoices or invoices_payable.get("total", 0) > 0:
            e3_checks += 1
        
        # Check 5: 6+ months of P&L for trend analysis
        if has_6_months:
            e3_checks += 1
        
        # Scale to 10 points (full category)
        e3_points = round((e3_checks / e3_max_checks) * 10, 1)
        
        sub_scores["E3"] = SubScore(
            metric_id="E3",
            name="Data Completeness",
            max_points=10,  # Full category (E1+E2 redistributed here)
            points_awarded=e3_points,
            status=MetricStatus.OK,
            value=e3_checks,
            formula=f"Data availability checks: {e3_checks}/{e3_max_checks} (P&L 3mo, BS, AR, AP, P&L 6mo)",
            inputs_used=["monthly_pnl_data", "balance_sheet_totals", "invoices_receivable", "invoices_payable"]
        )
        
        category_e_points = e3_points
        
        # =====================
        # FINAL SCORE CALCULATION
        # =====================
        
        raw_score = category_a_points + category_b_points + category_c_points + category_d_points + category_e_points
        
        # Apply confidence cap
        confidence = HealthScoreCalculator._get_confidence(category_e_points)
        confidence_cap = HealthScoreCalculator.CONFIDENCE_CAPS[confidence]
        final_score = min(raw_score, confidence_cap)
        
        grade = HealthScoreCalculator._get_grade(final_score)
        
        # =====================
        # DRIVERS IDENTIFICATION
        # =====================
        
        drivers_positive: list[Driver] = []
        drivers_negative: list[Driver] = []
        
        # Sort metrics by impact (points awarded vs max)
        for metric_id, sub_score in sub_scores.items():
            if sub_score.status == MetricStatus.MISSING:
                continue
            
            impact = sub_score.points_awarded - (sub_score.max_points / 2)  # Relative to midpoint
            
            driver = Driver(
                metric_id=metric_id,
                label=sub_score.name,
                impact_points=sub_score.points_awarded,
                why_it_matters=f"{sub_score.name} affects overall financial health",
                recommended_action=f"Review and optimize {sub_score.name.lower()}"
            )
            
            if impact > 0:
                drivers_positive.append(driver)
            elif impact < 0:
                drivers_negative.append(driver)
        
        # Sort and take top 3
        drivers_positive.sort(key=lambda d: d.impact_points, reverse=True)
        drivers_negative.sort(key=lambda d: d.impact_points)
        
        return {
            "schema_version": "bhs.v1",
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "scorecard": {
                "raw_score": round(raw_score, 1),
                "confidence": confidence.value,
                "confidence_cap": confidence_cap,
                "final_score": round(final_score, 1),
                "grade": grade.value,
            },
            "category_scores": {
                "A": {
                    "category_id": "A",
                    "name": "Cash & Runway",
                    "max_points": 30,
                    "points_awarded": round(category_a_points, 1),
                    "metrics": ["A1", "A2", "A3"],
                },
                "B": {
                    "category_id": "B",
                    "name": "Profitability & Efficiency",
                    "max_points": 25,
                    "points_awarded": round(category_b_points, 1),
                    "metrics": ["B1", "B2", "B3"],
                },
                "C": {
                    "category_id": "C",
                    "name": "Revenue Quality & Momentum",
                    "max_points": 15,
                    "points_awarded": round(category_c_points, 1),
                    "metrics": ["C1", "C2"],
                },
                "D": {
                    "category_id": "D",
                    "name": "Working Capital & Liquidity",
                    "max_points": 20,
                    "points_awarded": round(category_d_points, 1),
                    "metrics": ["D1", "D2", "D3", "D4"],
                },
                "E": {
                    "category_id": "E",
                    "name": "Compliance & Data Confidence",
                    "max_points": 10,
                    "points_awarded": round(category_e_points, 1),
                    "metrics": ["E1", "E2", "E3"],
                },
            },
            "subscores": {
                metric_id: {
                    "metric_id": s.metric_id,
                    "name": s.name,
                    "max_points": s.max_points,
                    "points_awarded": round(s.points_awarded, 1),
                    "status": s.status.value,
                    "value": round(s.value, 2) if s.value is not None else None,
                    "formula": s.formula,
                    "inputs_used": s.inputs_used,
                }
                for metric_id, s in sub_scores.items()
            },
            "drivers": {
                "top_positive": [
                    {
                        "metric_id": d.metric_id,
                        "label": d.label,
                        "impact_points": round(d.impact_points, 1),
                        "why_it_matters": d.why_it_matters,
                        "recommended_action": d.recommended_action,
                    }
                    for d in drivers_positive[:3]
                ],
                "top_negative": [
                    {
                        "metric_id": d.metric_id,
                        "label": d.label,
                        "impact_points": round(d.impact_points, 1),
                        "why_it_matters": d.why_it_matters,
                        "recommended_action": d.recommended_action,
                    }
                    for d in drivers_negative[:3]
                ],
            },
            "missing_data_adjustments": missing_adjustments,
            "data_quality": {
                "signals": HealthScoreCalculator._build_data_quality_signals(has_monthly_data, has_6_months),
                "warnings": HealthScoreCalculator._build_data_quality_warnings(has_monthly_data, missing_adjustments),
            },
            "intermediates": {
                "cash_available": cash,
                "accounts_receivable": ar,
                "current_assets_total": current_assets,
                "current_liabilities_total": current_liabilities,
                "revenue_3mo": revenue,  # Rolling 3-month total
                "cost_of_sales_3mo": cost_of_sales,  # Rolling 3-month total
                "expenses_3mo": expenses,  # Rolling 3-month total
                "avg_monthly_revenue": avg_monthly_revenue,
                "avg_monthly_expenses": avg_monthly_expenses,
                "gross_profit": gross_profit,
                "net_profit": net_profit,
                "net_margin_pct": net_margin_pct,
                "gross_margin_pct": gross_margin_pct,
                "opex_ratio_pct": opex_ratio_pct,
                "current_ratio": current_ratio,
                "quick_ratio": quick_ratio,
                "ar_to_cash": ar_to_cash,
                "runway_months": runway_months if runway_months != 999 else None,
                "months_of_pnl_data": len(monthly_pnl),
                "ar_over_30_pct": ar_over_30_pct,
                "ar_over_60_pct": ar_over_60_pct,
                "ap_over_60_pct": ap_over_60_pct,
            },
        }
    
    @staticmethod
    def calculate_from_extracted(
        extracted_data: "FinancialData",
        monthly_pnl_data: Optional[list[dict[str, Any]]] = None,
    ) -> dict[str, Any]:
        """
        Calculate Business Health Score from Extractors module output.
        
        This is a convenience method that accepts the typed FinancialData
        structure from the Extractors module.
        
        Args:
            extracted_data: FinancialData from Extractors.extract_all()
            monthly_pnl_data: List of monthly P&L data (newest first)
        
        Returns:
            Complete Health Score result
        """
        balance_sheet = extracted_data.get("balance_sheet", {})
        ar_ageing = extracted_data.get("ar_ageing", {})
        ap_ageing = extracted_data.get("ap_ageing", {})
        
        # Convert to expected format
        balance_sheet_totals = {
            "cash": balance_sheet.get("cash"),
            "accounts_receivable": balance_sheet.get("accounts_receivable"),
            "current_assets_total": balance_sheet.get("current_assets_total"),
            "current_liabilities_total": balance_sheet.get("current_liabilities_total"),
            "accounts_payable": balance_sheet.get("accounts_payable"),
            "inventory": balance_sheet.get("inventory"),
        }
        
        # Convert ageing to invoices format expected by calculate()
        # The ageing data already has totals and buckets
        invoices_receivable = {
            "total": ar_ageing.get("total", 0),
            "invoices": [],  # Individual invoices not available from ageing summary
        }
        
        invoices_payable = {
            "total": ap_ageing.get("total", 0),
            "invoices": [],
        }
        
        return HealthScoreCalculator.calculate(
            balance_sheet_totals=balance_sheet_totals,
            invoices_receivable=invoices_receivable,
            invoices_payable=invoices_payable,
            monthly_pnl_data=monthly_pnl_data,
        )
