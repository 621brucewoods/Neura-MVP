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
    def calculate(
        balance_sheet_totals: dict[str, Optional[float]],
        trial_balance_pnl: dict[str, Optional[float]],
        invoices_receivable: dict[str, Any],
        invoices_payable: dict[str, Any],
    ) -> dict[str, Any]:
        """
        Calculate Business Health Score v1.
        
        Args:
            balance_sheet_totals: From BalanceSheetAccountTypeParser.extract_totals()
            trial_balance_pnl: From TrialBalanceParser.extract_pnl()
            invoices_receivable: From InvoicesFetcher.fetch_receivables()
            invoices_payable: From InvoicesFetcher.fetch_payables()
        
        Returns:
            Complete Health Score result including score, grade, confidence,
            all sub-scores, drivers, and explanations.
        """
        sub_scores: dict[str, SubScore] = {}
        missing_adjustments: list[dict] = []
        
        # Extract values from inputs
        cash = balance_sheet_totals.get("cash")
        ar = balance_sheet_totals.get("accounts_receivable")
        current_assets = balance_sheet_totals.get("current_assets_total")
        current_liabilities = balance_sheet_totals.get("current_liabilities_total")
        
        revenue = trial_balance_pnl.get("revenue")
        cost_of_sales = trial_balance_pnl.get("cost_of_sales")
        expenses = trial_balance_pnl.get("expenses")
        
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
        
        # Calculate runway (simplified - using current month data)
        # Runway = Cash / AvgMonthlyNetOutflow
        # For now, use single month approximation
        runway_months = None
        monthly_burn = None
        if cash is not None and expenses is not None and revenue is not None:
            monthly_outflow = max(0, expenses - revenue)  # Net outflow
            if monthly_outflow > 0:
                runway_months = cash / monthly_outflow
                monthly_burn = monthly_outflow
            elif revenue > expenses:
                # Profitable - infinite runway
                runway_months = None  # Infinite
        
        # =====================
        # CATEGORY A: Cash & Runway (30 points)
        # =====================
        
        # A1: Runway months (15 pts)
        a1_points, a1_threshold = HealthScoreCalculator._score_runway_months(runway_months)
        sub_scores["A1"] = SubScore(
            metric_id="A1",
            name="Runway Months",
            max_points=15,
            points_awarded=a1_points,
            status=MetricStatus.OK if runway_months is not None or (revenue and revenue > (expenses or 0)) else MetricStatus.MISSING,
            value=runway_months,
            formula="CashAvailable / AvgMonthlyNetOutflow",
            inputs_used=["balance_sheet_totals.cash", "trial_balance_pnl.expenses", "trial_balance_pnl.revenue"]
        )
        
        # A2: Cash volatility (10 pts) - MISSING (needs historical data)
        sub_scores["A2"] = SubScore(
            metric_id="A2",
            name="Cash Volatility",
            max_points=10,
            points_awarded=0,
            status=MetricStatus.MISSING,
            value=None,
            formula="StdDev(MonthlyNetCashProxy) / AvgRevenue(3mo)",
            inputs_used=[]
        )
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
        
        # Redistribute A2 points to A1
        if sub_scores["A2"].status == MetricStatus.MISSING:
            # Scale A1 to absorb A2's points (A1 now worth 25 out of 30)
            a1_scale = 25 / 15
            sub_scores["A1"].points_awarded = min(25, sub_scores["A1"].points_awarded * a1_scale)
            sub_scores["A1"].max_points = 25
        
        category_a_points = sum(s.points_awarded for s in [sub_scores["A1"], sub_scores["A3"]])
        
        # =====================
        # CATEGORY B: Profitability & Efficiency (25 points)
        # =====================
        
        # B1: Net profit margin (10 pts)
        b1_points, b1_threshold = HealthScoreCalculator._score_net_margin(net_margin_pct)
        sub_scores["B1"] = SubScore(
            metric_id="B1",
            name="Net Profit Margin",
            max_points=10,
            points_awarded=b1_points,
            status=MetricStatus.OK if net_margin_pct is not None else MetricStatus.MISSING,
            value=net_margin_pct,
            formula="NetProfit / Revenue * 100",
            inputs_used=["trial_balance_pnl.revenue", "trial_balance_pnl.cost_of_sales", "trial_balance_pnl.expenses"]
        )
        
        # B2: Gross margin (8 pts)
        b2_points, b2_threshold = HealthScoreCalculator._score_gross_margin(gross_margin_pct)
        has_cogs = cost_of_sales is not None and cost_of_sales != 0
        sub_scores["B2"] = SubScore(
            metric_id="B2",
            name="Gross Margin",
            max_points=8,
            points_awarded=b2_points if has_cogs else 0,
            status=MetricStatus.OK if has_cogs else MetricStatus.MISSING,
            value=gross_margin_pct if has_cogs else None,
            formula="(Revenue - COGS) / Revenue * 100",
            inputs_used=["trial_balance_pnl.revenue", "trial_balance_pnl.cost_of_sales"]
        )
        
        # B3: Operating expense ratio (7 pts)
        b3_points, b3_threshold = HealthScoreCalculator._score_opex_ratio(opex_ratio_pct)
        sub_scores["B3"] = SubScore(
            metric_id="B3",
            name="Operating Expense Load",
            max_points=7,
            points_awarded=b3_points,
            status=MetricStatus.OK if opex_ratio_pct is not None else MetricStatus.MISSING,
            value=opex_ratio_pct,
            formula="OperatingExpenses / Revenue * 100",
            inputs_used=["trial_balance_pnl.expenses", "trial_balance_pnl.revenue"]
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
        # MISSING - needs historical data
        # =====================
        
        sub_scores["C1"] = SubScore(
            metric_id="C1",
            name="Revenue Trend",
            max_points=10,
            points_awarded=0,
            status=MetricStatus.MISSING,
            value=None,
            formula="(Rev_last3 - Rev_prev3) / Rev_prev3",
            inputs_used=[]
        )
        
        sub_scores["C2"] = SubScore(
            metric_id="C2",
            name="Revenue Consistency",
            max_points=5,
            points_awarded=0,
            status=MetricStatus.MISSING,
            value=None,
            formula="StdDev(MonthlyRevenue_6mo) / Avg(MonthlyRevenue_6mo)",
            inputs_used=[]
        )
        
        missing_adjustments.append({
            "metric_id": "C1",
            "reason": "Historical monthly revenue data not available",
            "points_redistributed": 10,
            "redistributed_to": [{"metric_id": "B1", "points_added": 5}, {"metric_id": "D1", "points_added": 5}]
        })
        missing_adjustments.append({
            "metric_id": "C2",
            "reason": "Historical monthly revenue data not available",
            "points_redistributed": 5,
            "redistributed_to": [{"metric_id": "B3", "points_added": 5}]
        })
        
        # Redistribute C points to B and D
        sub_scores["B1"].points_awarded = min(15, sub_scores["B1"].points_awarded + 5 * (sub_scores["B1"].points_awarded / 10))
        sub_scores["B3"].points_awarded = min(12, sub_scores["B3"].points_awarded + 5 * (sub_scores["B3"].points_awarded / sub_scores["B3"].max_points))
        
        category_c_points = 0  # All metrics missing
        
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
        
        # Add redistributed C1 points
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
        # =====================
        
        # E1: Bank reconciliation freshness (4 pts) - MISSING
        sub_scores["E1"] = SubScore(
            metric_id="E1",
            name="Bank Reconciliation Freshness",
            max_points=4,
            points_awarded=0,
            status=MetricStatus.MISSING,
            value=None,
            formula="Days since last reconciliation",
            inputs_used=[]
        )
        
        # E2: Categorisation completeness (3 pts) - MISSING
        sub_scores["E2"] = SubScore(
            metric_id="E2",
            name="Categorisation Completeness",
            max_points=3,
            points_awarded=0,
            status=MetricStatus.MISSING,
            value=None,
            formula="% of transactions uncategorised",
            inputs_used=[]
        )
        
        # E3: Reporting readiness (3 pts)
        e3_points = 0
        if trial_balance_pnl.get("revenue") is not None:
            e3_points += 1  # P&L available
        if balance_sheet_totals.get("cash") is not None:
            e3_points += 1  # Balance Sheet available
        if ar_invoices or invoices_receivable.get("total", 0) > 0:
            e3_points += 1  # AR available
        
        sub_scores["E3"] = SubScore(
            metric_id="E3",
            name="Reporting Readiness",
            max_points=3,
            points_awarded=e3_points,
            status=MetricStatus.OK,
            value=e3_points,
            formula="P&L + BS + AR/AP availability",
            inputs_used=["trial_balance_pnl", "balance_sheet_totals", "invoices_receivable"]
        )
        
        category_e_points = e3_points  # Only E3 is available
        
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
                "signals": [
                    {
                        "signal_id": "DQ_MISSING_HISTORICAL",
                        "severity": "warning",
                        "message": "Historical monthly data not available. Revenue trends and cash volatility cannot be calculated."
                    },
                    {
                        "signal_id": "DQ_MISSING_RECON",
                        "severity": "info",
                        "message": "Bank reconciliation status not available from API."
                    },
                ],
                "warnings": [
                    "Score may be conservative due to missing historical data.",
                    "Revenue trend metrics (15 points) were redistributed to other categories.",
                ],
            },
            "intermediates": {
                "cash_available": cash,
                "accounts_receivable": ar,
                "current_assets_total": current_assets,
                "current_liabilities_total": current_liabilities,
                "revenue": revenue,
                "cost_of_sales": cost_of_sales,
                "expenses": expenses,
                "gross_profit": gross_profit,
                "net_profit": net_profit,
                "net_margin_pct": net_margin_pct,
                "gross_margin_pct": gross_margin_pct,
                "opex_ratio_pct": opex_ratio_pct,
                "current_ratio": current_ratio,
                "quick_ratio": quick_ratio,
                "ar_to_cash": ar_to_cash,
                "runway_months": runway_months,
                "ar_over_30_pct": ar_over_30_pct,
                "ar_over_60_pct": ar_over_60_pct,
                "ap_over_60_pct": ap_over_60_pct,
            },
        }
    
    @staticmethod
    def calculate_from_extracted(
        extracted_data: "FinancialData",
    ) -> dict[str, Any]:
        """
        Calculate Business Health Score from Extractors module output.
        
        This is a convenience method that accepts the typed FinancialData
        structure from the Extractors module.
        
        Args:
            extracted_data: FinancialData from Extractors.extract_all()
        
        Returns:
            Complete Health Score result
        """
        balance_sheet = extracted_data.get("balance_sheet", {})
        pnl = extracted_data.get("pnl", {})
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
        
        trial_balance_pnl = {
            "revenue": pnl.get("revenue"),
            "cost_of_sales": pnl.get("cost_of_sales"),
            "expenses": pnl.get("expenses"),
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
            trial_balance_pnl=trial_balance_pnl,
            invoices_receivable=invoices_receivable,
            invoices_payable=invoices_payable,
        )
