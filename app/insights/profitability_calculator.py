"""
Profitability calculator for P&L analysis.

Primary source: Trial Balance (deterministic by AccountType).
Fallback: P&L report structure-based extraction (only if Trial Balance unavailable).
"""

import logging
from typing import Any, Optional

from app.insights.utils import safe_float, safe_get, safe_list_get

logger = logging.getLogger(__name__)


class ProfitabilityCalculator:
    """
    Calculates profitability metrics from financial data.
    
    Strategy: Trial Balance is primary (deterministic), P&L report is fallback only.
    Gross profit and net profit are always calculated, never extracted.
    """

    @staticmethod
    def _get_value(data: dict, *keys) -> Any:
        """Get value with PascalCase/lowercase fallback."""
        for key in keys:
            value = data.get(key) or data.get(key.lower())
            if value is not None:
                return value
        return None

    @staticmethod
    def _get_row_type(row: dict) -> str:
        """Get row type with fallback."""
        return ProfitabilityCalculator._get_value(row, "RowType", "row_type") or ""

    @staticmethod
    def _get_cells(row: dict) -> list:
        """Get cells list with fallback."""
        cells = ProfitabilityCalculator._get_value(row, "Cells", "cells") or []
        return cells if isinstance(cells, list) else []

    @staticmethod
    def _get_cell_value(cell: dict, default: str = "") -> str:
        """Get cell value with fallback."""
        return ProfitabilityCalculator._get_value(cell, "Value", "value") or default

    @staticmethod
    def _get_nested_rows(row: dict) -> list:
        """Get nested rows with fallback."""
        nested = ProfitabilityCalculator._get_value(row, "Rows", "rows") or []
        return nested if isinstance(nested, list) else []

    @staticmethod
    def _get_summary_row(section: dict) -> Optional[dict]:
        """Extract SummaryRow from a Section."""
        summary = ProfitabilityCalculator._get_value(section, "SummaryRow", "summary_row")
        return summary if isinstance(summary, dict) else None

    @staticmethod
    def _find_target_column_index(rows: list) -> int:
        """Find column index containing current period data. Defaults to 1."""
        if not isinstance(rows, list):
            return 1

        for row in rows:
            if not isinstance(row, dict):
                continue

            if ProfitabilityCalculator._get_row_type(row) != "Header":
                continue

            cells = ProfitabilityCalculator._get_cells(row)
            if len(cells) < 2:
                continue

            for i in range(1, len(cells)):
                cell = safe_list_get(cells, i)
                if isinstance(cell, dict):
                    value = ProfitabilityCalculator._get_cell_value(cell)
                    if value and value.strip():
                        return i

        return 1

    @staticmethod
    def _extract_section_value(section: dict, target_col_index: int) -> Optional[float]:
        """Extract value from section's SummaryRow at target column."""
        summary_row = ProfitabilityCalculator._get_summary_row(section)
        if not summary_row:
            return None

        cells = ProfitabilityCalculator._get_cells(summary_row)
        if len(cells) <= target_col_index:
            return None

        value_cell = safe_list_get(cells, target_col_index)
        if not isinstance(value_cell, dict):
            return None

        value_str = ProfitabilityCalculator._get_cell_value(value_cell, "0")
        return safe_float(value_str)

    @staticmethod
    def _extract_pnl_values(pnl_data: Optional[dict[str, Any]]) -> dict[str, Any]:
        """
        Extract revenue, cost_of_sales, expenses from P&L report (fallback only).
        
        Uses structure-based parsing: first/second/third Section SummaryRow.
        Gross profit and net profit are NOT extracted (always calculated).
        """
        if not pnl_data or not pnl_data.get("raw_data"):
            return {"revenue": None, "cost_of_sales": None, "expenses": None}

        raw_data = safe_get(pnl_data, "raw_data", {})
        if not isinstance(raw_data, dict):
            return {"revenue": None, "cost_of_sales": None, "expenses": None}

        rows = ProfitabilityCalculator._get_value(raw_data, "Rows", "rows") or []
        if not isinstance(rows, list):
            rows = []

        target_col_index = ProfitabilityCalculator._find_target_column_index(rows)
        sections = []

        def _collect_sections(rows_list: list):
            """Recursively collect Sections from report structure."""
            if not isinstance(rows_list, list):
                return

            for row in rows_list:
                if not isinstance(row, dict):
                    continue

                if ProfitabilityCalculator._get_row_type(row) == "Section":
                    sections.append(row)

                nested_rows = ProfitabilityCalculator._get_nested_rows(row)
                if nested_rows:
                    _collect_sections(nested_rows)

        _collect_sections(rows)

        revenue = ProfitabilityCalculator._extract_section_value(sections[0], target_col_index) if len(sections) >= 1 else None
        cost_of_sales = ProfitabilityCalculator._extract_section_value(sections[1], target_col_index) if len(sections) >= 2 else None
        expenses = ProfitabilityCalculator._extract_section_value(sections[2], target_col_index) if len(sections) >= 3 else None

        return {
            "revenue": revenue,
            "cost_of_sales": cost_of_sales,
            "expenses": expenses,
        }

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
        profit_loss_data: Optional[dict[str, Any]],
        trial_balance_pnl: Optional[dict[str, Any]],
        executive_summary_current: dict[str, Any],
        executive_summary_history: list[dict[str, Any]]
    ) -> dict[str, Any]:
        """
        Calculate all profitability metrics.
        
        Strategy: Trial Balance is primary source (deterministic by AccountType).
        P&L report is only used as fallback if Trial Balance unavailable.
        Gross profit and net profit are always calculated, never extracted.
        """
        pnl_values = {
            "revenue": None,
            "cost_of_sales": None,
            "expenses": None,
            "gross_profit": None,
            "net_profit": None,
        }

        # Primary source: Trial Balance (deterministic)
        if isinstance(trial_balance_pnl, dict):
            for key in ["revenue", "cost_of_sales", "expenses"]:
                if key in trial_balance_pnl:
                    pnl_values[key] = trial_balance_pnl[key]
        else:
            # Fallback: P&L report
            logger.warning("[Profitability] Trial Balance unavailable, using P&L fallback")
            pnl_extracted = ProfitabilityCalculator._extract_pnl_values(profit_loss_data)
            pnl_values["revenue"] = pnl_extracted.get("revenue")
            pnl_values["cost_of_sales"] = pnl_extracted.get("cost_of_sales")
            pnl_values["expenses"] = pnl_extracted.get("expenses")

        # Always calculate gross_profit
        if pnl_values.get("revenue") is not None and pnl_values.get("cost_of_sales") is not None:
            pnl_values["gross_profit"] = pnl_values["revenue"] - pnl_values["cost_of_sales"]

        # Always calculate net_profit
        if pnl_values.get("gross_profit") is not None and pnl_values.get("expenses") is not None:
            pnl_values["net_profit"] = pnl_values["gross_profit"] - pnl_values["expenses"]
        elif pnl_values.get("revenue") is not None and pnl_values.get("expenses") is not None:
            pnl_values["net_profit"] = pnl_values["revenue"] - pnl_values["expenses"]

        gross_margin = ProfitabilityCalculator.calculate_gross_margin(
            revenue=pnl_values["revenue"],
            cost_of_sales=pnl_values["cost_of_sales"],
            gross_profit=pnl_values["gross_profit"]
        )

        profit_trend = ProfitabilityCalculator.calculate_profit_trend(
            executive_summary_current,
            executive_summary_history
        )

        risk_level = ProfitabilityCalculator._determine_risk_level(
            gross_margin,
            pnl_values["net_profit"],
            profit_trend
        )

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
