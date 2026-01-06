"""
Insight Generator
Converts financial metrics into ranked, actionable insights.
"""

import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Optional

logger = logging.getLogger(__name__)


class Insight:
    """Represents a single financial insight."""
    
    def __init__(
        self,
        insight_type: str,
        title: str,
        severity: str,
        confidence_level: str,
        summary: str,
        why_it_matters: str,
        recommended_actions: list[str],
        supporting_numbers: Optional[list[dict[str, Any]]] = None,
        data_notes: Optional[str] = None,
    ):
        self.insight_id = str(uuid.uuid4())
        self.insight_type = insight_type
        self.title = title
        self.severity = severity
        self.confidence_level = confidence_level
        self.summary = summary
        self.why_it_matters = why_it_matters
        self.recommended_actions = recommended_actions
        self.supporting_numbers = supporting_numbers or []
        self.data_notes = data_notes
        self.generated_at = datetime.now(timezone.utc).isoformat()
    
    def to_dict(self) -> dict[str, Any]:
        """Convert insight to dictionary."""
        return {
            "insight_id": self.insight_id,
            "insight_type": self.insight_type,
            "title": self.title,
            "severity": self.severity,
            "confidence_level": self.confidence_level,
            "summary": self.summary,
            "why_it_matters": self.why_it_matters,
            "recommended_actions": self.recommended_actions,
            "supporting_numbers": self.supporting_numbers,
            "data_notes": self.data_notes,
            "generated_at": self.generated_at,
        }
    
    def calculate_urgency_score(self) -> float:
        """Calculate urgency score for ranking."""
        severity_scores = {"high": 100, "medium": 50, "low": 25}
        confidence_multipliers = {"high": 1.0, "medium": 0.7, "low": 0.4}
        
        base_score = severity_scores.get(self.severity, 0)
        multiplier = confidence_multipliers.get(self.confidence_level, 0.3)
        
        return base_score * multiplier


class InsightGenerator:
    """
    Generates insights from financial metrics.
    
    Converts raw metrics into ranked, actionable insights.
    """
    
    @staticmethod
    def generate_insights(
        cash_runway: dict[str, Any],
        cash_pressure: dict[str, Any],
        leading_indicators: dict[str, Any],
        profitability: dict[str, Any],
        upcoming_commitments: dict[str, Any],
    ) -> list[dict[str, Any]]:
        """
        Generate and rank insights from all metrics.
        
        Args:
            cash_runway: Cash runway metrics
            cash_pressure: Cash pressure status
            leading_indicators: Leading indicators metrics
            profitability: Profitability metrics
            upcoming_commitments: Upcoming commitments metrics
        
        Returns:
            List of top 1-3 insights, ranked by urgency
        """
        insights = []
        
        # Generate each insight type
        runway_insight = InsightGenerator._generate_cash_runway_insight(
            cash_runway, cash_pressure
        )
        if runway_insight:
            insights.append(runway_insight)
        
        squeeze_insight = InsightGenerator._generate_squeeze_insight(
            upcoming_commitments, cash_runway
        )
        if squeeze_insight:
            insights.append(squeeze_insight)
        
        receivables_insight = InsightGenerator._generate_receivables_insight(
            leading_indicators
        )
        if receivables_insight:
            insights.append(receivables_insight)
        
        profitability_insight = InsightGenerator._generate_profitability_insight(
            profitability
        )
        if profitability_insight:
            insights.append(profitability_insight)
        
        # Rank and return top 3
        ranked = sorted(insights, key=lambda x: x.calculate_urgency_score(), reverse=True)
        return [insight.to_dict() for insight in ranked[:3]]
    
    @staticmethod
    def _generate_cash_runway_insight(
        cash_runway: dict[str, Any],
        cash_pressure: dict[str, Any],
    ) -> Optional[Insight]:
        """Generate cash runway risk insight."""
        runway_months = cash_runway.get("runway_months")
        runway_status = cash_runway.get("status")
        current_cash = cash_runway.get("current_cash", 0.0)
        confidence = cash_pressure.get("confidence", "medium")
        
        # Only generate if there's a risk
        if runway_status in ["infinite", "healthy"]:
            return None
        
        if runway_status == "critical":
            severity = "high"
            title = "Cash runway is critical"
            summary = f"You currently have {runway_months:.1f} months of cash remaining based on recent outflows."
            why_it_matters = (
                "With less than 3 months of runway, immediate action is needed to avoid cash shortage. "
                "This could impact your ability to pay suppliers, meet payroll, and maintain operations."
            )
            actions = [
                "Review and collect overdue invoices immediately",
                "Delay discretionary spending this month",
                "Monitor payroll timing closely",
                "Consider negotiating extended payment terms with suppliers",
            ]
            numbers = [
                {"label": "Current cash", "value": f"${current_cash:,.2f}"},
                {"label": "Runway remaining", "value": f"{runway_months:.1f} months"},
            ]
        
        elif runway_status == "warning":
            severity = "medium"
            title = "Cash runway is tightening"
            summary = f"You currently have {runway_months:.1f} months of cash remaining."
            why_it_matters = (
                "Your cash runway is between 3-6 months, which requires careful monitoring. "
                "If current spending continues without additional revenue, cash pressure may emerge soon."
            )
            actions = [
                "Review overdue invoices over $5,000 and send payment reminders",
                "Delay discretionary spending this month",
                "Monitor cash position weekly",
            ]
            numbers = [
                {"label": "Current cash", "value": f"${current_cash:,.2f}"},
                {"label": "Runway remaining", "value": f"{runway_months:.1f} months"},
            ]
        
        elif runway_status == "negative":
            severity = "high"
            title = "Cash position is negative"
            summary = "Your cash balance is currently negative, indicating immediate cash flow issues."
            why_it_matters = (
                "A negative cash position means you have insufficient funds to cover current obligations. "
                "This requires immediate attention to avoid operational disruption."
            )
            actions = [
                "Collect all outstanding receivables immediately",
                "Contact suppliers to negotiate payment terms",
                "Review and reduce all non-essential expenses",
                "Consider short-term financing options",
            ]
            numbers = [
                {"label": "Current cash", "value": f"${current_cash:,.2f}"},
            ]
        
        else:
            return None
        
        return Insight(
            insight_type="cash_runway_risk",
            title=title,
            severity=severity,
            confidence_level=confidence,
            summary=summary,
            why_it_matters=why_it_matters,
            recommended_actions=actions,
            supporting_numbers=numbers,
        )
    
    @staticmethod
    def _generate_squeeze_insight(
        upcoming_commitments: dict[str, Any],
        cash_runway: dict[str, Any],
    ) -> Optional[Insight]:
        """Generate upcoming cash squeeze insight."""
        squeeze_risk = upcoming_commitments.get("squeeze_risk", "low")
        upcoming_amount = upcoming_commitments.get("upcoming_amount", 0.0)
        upcoming_count = upcoming_commitments.get("upcoming_count", 0)
        large_bills = upcoming_commitments.get("large_upcoming_bills", [])
        current_cash = cash_runway.get("current_cash", 0.0)
        
        if squeeze_risk == "low":
            return None
        
        if squeeze_risk == "high":
            severity = "high"
            title = "Upcoming cash squeeze risk"
            summary = f"You have ${upcoming_amount:,.2f} due in the next 30 days from {upcoming_count} bills."
            why_it_matters = (
                "Large upcoming commitments relative to your cash position create a risk of cash shortage. "
                "If these bills come due before you receive expected payments, you may face liquidity issues."
            )
            actions = [
                "Prioritize collecting receivables before these bills are due",
                "Contact suppliers to negotiate payment terms or delays",
                "Review large upcoming bills and confirm due dates",
            ]
            if large_bills:
                actions.append(f"Focus on collecting from top {min(3, len(large_bills))} overdue invoices")
            
            numbers = [
                {"label": "Upcoming bills (30 days)", "value": f"${upcoming_amount:,.2f}"},
                {"label": "Number of bills", "value": str(upcoming_count)},
                {"label": "Current cash", "value": f"${current_cash:,.2f}"},
            ]
        
        else:  # medium
            severity = "medium"
            title = "Upcoming cash commitments to monitor"
            summary = f"You have ${upcoming_amount:,.2f} due in the next 30 days."
            why_it_matters = (
                "While manageable, these upcoming commitments require monitoring to ensure sufficient cash flow."
            )
            actions = [
                "Confirm payment timing for large upcoming bills",
                "Ensure receivables are collected before bills are due",
            ]
            numbers = [
                {"label": "Upcoming bills (30 days)", "value": f"${upcoming_amount:,.2f}"},
                {"label": "Number of bills", "value": str(upcoming_count)},
            ]
        
        return Insight(
            insight_type="upcoming_cash_squeeze",
            title=title,
            severity=severity,
            confidence_level="high",
            summary=summary,
            why_it_matters=why_it_matters,
            recommended_actions=actions,
            supporting_numbers=numbers,
        )
    
    @staticmethod
    def _generate_receivables_insight(
        leading_indicators: dict[str, Any],
    ) -> Optional[Insight]:
        """Generate receivables risk insight."""
        receivables = leading_indicators.get("receivables_health", {})
        risk_level = receivables.get("risk_level", "low")
        overdue_amount = receivables.get("overdue_amount", 0.0)
        overdue_percentage = receivables.get("overdue_percentage", 0.0)
        avg_days_overdue = receivables.get("avg_days_overdue", 0.0)
        
        if risk_level == "low":
            return None
        
        if risk_level == "high":
            severity = "high"
            title = "High receivables collection risk"
            summary = f"{overdue_percentage:.1f}% of receivables (${overdue_amount:,.2f}) are overdue, averaging {avg_days_overdue:.1f} days late."
            why_it_matters = (
                "High overdue receivables indicate cash collection issues. This delays cash inflow and "
                "increases the risk of bad debts, directly impacting your cash position."
            )
            actions = [
                "Send payment reminders to all overdue invoices",
                "Contact top 5 overdue customers directly",
                "Review credit terms for customers with frequent late payments",
                "Consider offering early payment discounts",
            ]
            numbers = [
                {"label": "Overdue amount", "value": f"${overdue_amount:,.2f}"},
                {"label": "Overdue percentage", "value": f"{overdue_percentage:.1f}%"},
                {"label": "Average days overdue", "value": f"{avg_days_overdue:.1f} days"},
            ]
        
        else:  # medium
            severity = "medium"
            title = "Receivables collection timing risk"
            summary = f"{overdue_percentage:.1f}% of receivables are overdue, averaging {avg_days_overdue:.1f} days late."
            why_it_matters = (
                "Moderate overdue receivables can impact cash flow timing. Monitoring and follow-up "
                "can help ensure timely collection."
            )
            actions = [
                "Send payment reminders to overdue invoices",
                "Review payment terms with customers showing delays",
            ]
            numbers = [
                {"label": "Overdue amount", "value": f"${overdue_amount:,.2f}"},
                {"label": "Overdue percentage", "value": f"{overdue_percentage:.1f}%"},
            ]
        
        return Insight(
            insight_type="receivables_risk",
            title=title,
            severity=severity,
            confidence_level="high",
            summary=summary,
            why_it_matters=why_it_matters,
            recommended_actions=actions,
            supporting_numbers=numbers,
        )
    
    @staticmethod
    def _generate_profitability_insight(
        profitability: dict[str, Any],
    ) -> Optional[Insight]:
        """Generate profitability pressure insight."""
        risk_level = profitability.get("risk_level", "low")
        net_profit = profitability.get("net_profit")
        gross_margin = profitability.get("gross_margin_pct")
        revenue = profitability.get("revenue")
        
        if risk_level == "low" or net_profit is None:
            return None
        
        if risk_level == "high":
            severity = "high"
            
            if net_profit < 0:
                title = "Operating at a loss"
                summary = f"Your business is currently operating at a net loss of ${abs(net_profit):,.2f}."
                why_it_matters = (
                    "Operating at a loss means expenses exceed revenue. This is unsustainable long-term "
                    "and will deplete cash reserves unless addressed."
                )
                actions = [
                    "Review and reduce operating expenses",
                    "Identify opportunities to increase revenue",
                    "Analyze cost of sales for margin improvement",
                    "Consider pricing adjustments if margins are low",
                ]
                numbers = [
                    {"label": "Net profit", "value": f"${net_profit:,.2f}"},
                    {"label": "Revenue", "value": f"${revenue:,.2f}" if revenue else "N/A"},
                ]
            else:
                title = "Low profitability margins"
                summary = f"Gross margin is {gross_margin:.1f}%, indicating tight profitability."
                why_it_matters = (
                    "Low gross margins leave little room for operating expenses and profit. "
                    "This makes the business vulnerable to cost increases or revenue declines."
                )
                actions = [
                    "Review pricing strategy for margin improvement",
                    "Analyze cost of sales for reduction opportunities",
                    "Consider value-added services to improve margins",
                ]
                numbers = [
                    {"label": "Gross margin", "value": f"{gross_margin:.1f}%"},
                    {"label": "Net profit", "value": f"${net_profit:,.2f}"},
                ]
        
        else:  # medium
            severity = "medium"
            title = "Profitability pressure emerging"
            summary = f"Profitability metrics indicate some pressure with {gross_margin:.1f}% gross margin."
            why_it_matters = (
                "Moderate profitability pressure suggests monitoring margins and expenses to maintain "
                "sustainable operations."
            )
            actions = [
                "Monitor gross margins monthly",
                "Review expense categories for optimization",
            ]
            numbers = [
                {"label": "Gross margin", "value": f"{gross_margin:.1f}%"},
                {"label": "Net profit", "value": f"${net_profit:,.2f}"},
            ]
        
        return Insight(
            insight_type="profitability_pressure",
            title=title,
            severity=severity,
            confidence_level="medium",
            summary=summary,
            why_it_matters=why_it_matters,
            recommended_actions=actions,
            supporting_numbers=numbers,
        )

