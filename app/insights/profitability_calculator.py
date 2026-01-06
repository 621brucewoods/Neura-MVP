"""
Profitability calculator for P&L analysis.

Uses structure-based parsing with standardLayout=true for  reliability.
No synonym matching - relies on RowType and predictable report structure.
"""

import logging
from typing import Any, Optional

from app.insights.utils import safe_float, safe_get, safe_list_get, safe_str_lower

logger = logging.getLogger(__name__)


class ProfitabilityCalculator:
    """
    Calculates profitability metrics from P&L data.
    
    Analyzes gross margin, profit trends, and profitability pressure.
    """
    
    @staticmethod
    def _get_row_type(row: dict) -> str:
        """Get row type with PascalCase fallback."""
        return safe_get(row, "RowType", safe_get(row, "row_type", ""))
    
    @staticmethod
    def _get_cells(row: dict) -> list:
        """Get cells list with PascalCase fallback."""
        cells = safe_get(row, "Cells", safe_get(row, "cells", []))
        return cells if isinstance(cells, list) else []
    
    @staticmethod
    def _get_cell_value(cell: dict, default: str = "") -> str:
        """Get cell value with PascalCase fallback."""
        return safe_get(cell, "Value", safe_get(cell, "value", default))
    
    @staticmethod
    def _get_nested_rows(row: dict) -> list:
        """Get nested rows with PascalCase fallback."""
        nested = safe_get(row, "Rows", safe_get(row, "rows", []))
        return nested if isinstance(nested, list) else []
    
    @staticmethod
    def _get_title(row: dict) -> str:
        """Get title with PascalCase fallback."""
        return safe_get(row, "Title", safe_get(row, "title", ""))
    
    @staticmethod
    def _get_summary_row(section: dict) -> Optional[dict]:
        """Extract SummaryRow from a Section, handling PascalCase/lowercase."""
        summary = safe_get(section, "SummaryRow", safe_get(section, "summary_row"))
        return summary if isinstance(summary, dict) else None
    
    @staticmethod
    def _find_target_column_index(rows: list) -> int:
        """
        Find the column index containing the current period data.
        
        Scans Header rows to identify which column contains the target data.
        Falls back to index 1 (second column) if header not found.
        
        Args:
            rows: List of report rows
            
        Returns:
            Column index (default: 1)
        """
        if not isinstance(rows, list):
            return 1
        
        for row in rows:
            if not isinstance(row, dict):
                continue
            
            row_type = ProfitabilityCalculator._get_row_type(row)
            if row_type != "Header":
                continue
            
            cells = ProfitabilityCalculator._get_cells(row)
            if len(cells) < 2:
                continue
            
            # Look for the first data column (skip empty first column)
            # Typically: Column 0 = empty/label, Column 1 = current period
            for i in range(1, len(cells)):
                cell = safe_list_get(cells, i)
                if isinstance(cell, dict):
                    value = ProfitabilityCalculator._get_cell_value(cell)
                    if value and value.strip():
                        # Found a column with data, use it
                        return i
            
            # If no data found, default to index 1
            return 1
        
        # No header found, default to index 1
        return 1
    
    @staticmethod
    def _extract_pnl_values(pnl_data: Optional[dict[str, Any]]) -> dict[str, Any]:
        """
        Extract key values from P&L report structure using structure-based parsing.
        
        Relies on standardLayout=true to ensure predictable structure:
        - Revenue: First Section's SummaryRow
        - Cost of Sales: Second Section's SummaryRow
        - Gross Profit: Standalone SummaryRow with label "Gross Profit" (Xero hard-codes this)
        - Expenses: Third Section's SummaryRow (Operating Expenses)
        - Net Profit: Last SummaryRow in the entire report
        
        Args:
            pnl_data: Raw P&L data from Xero (must use standardLayout=true)
        
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
        
        # Xero API uses "Rows" (PascalCase), try both for compatibility
        rows = safe_get(raw_data, "Rows", safe_get(raw_data, "rows", []))
        if not isinstance(rows, list):
            rows = []
        
        # Find target column index from header
        target_col_index = ProfitabilityCalculator._find_target_column_index(rows)
        logger.info("[P&L] Target column index: %s, Total rows: %s", target_col_index, len(rows))
        
        # Initialize all values
        revenue = None
        cost_of_sales = None
        gross_profit = None
        expenses = None
        net_profit = None
        
        # Collect all Sections, SummaryRows, and Rows for structure-based parsing
        sections = []
        all_summary_rows = []
        all_rows = []  # Collect all Row types for fallback when SummaryRow doesn't exist
        
        def _collect_structure(rows_list: list, depth: int = 0):
            """Recursively collect Sections, SummaryRows, and Rows from the report structure."""
            if not isinstance(rows_list, list):
                return
            
            for row in rows_list:
                if not isinstance(row, dict):
                    continue
                
                row_type = ProfitabilityCalculator._get_row_type(row)
                
                if row_type == "Section":
                    sections.append(row)
                    # Also collect SummaryRow from this section if it exists
                    summary_row = ProfitabilityCalculator._get_summary_row(row)
                    if summary_row:
                        all_summary_rows.append(summary_row)
                
                elif row_type == "SummaryRow":
                    # Standalone SummaryRow (not nested in a Section)
                    all_summary_rows.append(row)
                
                elif row_type == "Row":
                    # Regular Row type (used when SummaryRow doesn't exist)
                    all_rows.append(row)
                
                # Recursively search nested rows
                nested_rows = ProfitabilityCalculator._get_nested_rows(row)
                if nested_rows:
                    _collect_structure(nested_rows, depth + 1)
        
        _collect_structure(rows)
        logger.info("[P&L] Found %s Sections, %s SummaryRows, and %s Rows", 
                    len(sections), len(all_summary_rows), len(all_rows))
                
        # Extract value from a row (SummaryRow or Row) at target column
        def _extract_value_from_row(row: dict) -> Optional[float]:
            """Extract numeric value from SummaryRow or Row at target column."""
            cells = ProfitabilityCalculator._get_cells(row)
            if len(cells) > target_col_index:
                value_cell = safe_list_get(cells, target_col_index)
                if isinstance(value_cell, dict):
                    value_str = ProfitabilityCalculator._get_cell_value(value_cell, "0")
                    return safe_float(value_str)
            return None
            
        # Get label from a row (for matching specific labels like "Gross Profit")
        def _get_row_label(row: dict) -> str:
            """Extract label from row's first cell."""
            cells = ProfitabilityCalculator._get_cells(row)
            if len(cells) > 0:
                label_cell = safe_list_get(cells, 0)
                if isinstance(label_cell, dict):
                    return ProfitabilityCalculator._get_cell_value(label_cell, "")
            return ""
            
        # 1. REVENUE: First Section's SummaryRow or nested Row
        if len(sections) >= 1:
            first_section = sections[0]
            # Try SummaryRow first
            first_section_summary = ProfitabilityCalculator._get_summary_row(first_section)
            if first_section_summary:
                revenue = _extract_value_from_row(first_section_summary)
                logger.info("[P&L] Revenue (1st Section SummaryRow): %s", revenue)
            else:
                # Fallback: Look for Row with "Revenue" or "Income" in label within first section
                nested_rows = ProfitabilityCalculator._get_nested_rows(first_section)
                for nested_row in nested_rows:
                    if ProfitabilityCalculator._get_row_type(nested_row) == "Row":
                        label = safe_str_lower(_get_row_label(nested_row), "")
                        if "revenue" in label or "income" in label or "sales" in label:
                            revenue = _extract_value_from_row(nested_row)
                            logger.info("[P&L] Revenue (1st Section Row with label '%s'): %s", _get_row_label(nested_row), revenue)
                            break
        
        # 2. COST OF SALES: Second Section's SummaryRow or nested Row
        if len(sections) >= 2:
            second_section = sections[1]
            # Try SummaryRow first
            second_section_summary = ProfitabilityCalculator._get_summary_row(second_section)
            if second_section_summary:
                cost_of_sales = _extract_value_from_row(second_section_summary)
                logger.info("[P&L] Cost of Sales (2nd Section SummaryRow): %s", cost_of_sales)
            else:
                # Fallback: Look for Row with "Cost" in label within second section
                nested_rows = ProfitabilityCalculator._get_nested_rows(second_section)
                for nested_row in nested_rows:
                    if ProfitabilityCalculator._get_row_type(nested_row) == "Row":
                        label = safe_str_lower(_get_row_label(nested_row), "")
                        if "cost" in label or "cogs" in label:
                            cost_of_sales = _extract_value_from_row(nested_row)
                            logger.info("[P&L] Cost of Sales (2nd Section Row with label '%s'): %s", _get_row_label(nested_row), cost_of_sales)
                            break
        
        # 3. GROSS PROFIT: SummaryRow or Row with label "Gross Profit" (Xero hard-codes this)
        # Check SummaryRows first
        for summary_row in all_summary_rows:
            label = safe_str_lower(_get_row_label(summary_row), "")
            if label == "gross profit":
                gross_profit = _extract_value_from_row(summary_row)
                logger.info("[P&L] Gross Profit (SummaryRow with label 'Gross Profit'): %s", gross_profit)
                break
        else:
            # Fallback: Check Rows if not found in SummaryRows
            for row in all_rows:
                label = safe_str_lower(_get_row_label(row), "")
                if label == "gross profit":
                    gross_profit = _extract_value_from_row(row)
                    logger.info("[P&L] Gross Profit (Row with label 'Gross Profit'): %s", gross_profit)
                    break
        
        # 4. EXPENSES: Third Section's SummaryRow or nested Row
        if len(sections) >= 3:
            third_section = sections[2]
            # Try SummaryRow first
            third_section_summary = ProfitabilityCalculator._get_summary_row(third_section)
            if third_section_summary:
                expenses = _extract_value_from_row(third_section_summary)
                logger.info("[P&L] Expenses (3rd Section SummaryRow): %s", expenses)
            else:
                # Fallback: Look for Row with "Expense" in label within third section
                nested_rows = ProfitabilityCalculator._get_nested_rows(third_section)
                for nested_row in nested_rows:
                    if ProfitabilityCalculator._get_row_type(nested_row) == "Row":
                        label = safe_str_lower(_get_row_label(nested_row), "")
                        if "expense" in label or "cost" in label:
                            expenses = _extract_value_from_row(nested_row)
                            logger.info("[P&L] Expenses (3rd Section Row with label '%s'): %s", _get_row_label(nested_row), expenses)
                            break
        
        # 5. NET PROFIT: Last SummaryRow or Row in the entire report (final total)
        # Try SummaryRows first
        if all_summary_rows:
            last_summary = all_summary_rows[-1]
            net_profit = _extract_value_from_row(last_summary)
            logger.info("[P&L] Net Profit (Last SummaryRow): %s", net_profit)
        elif all_rows:
            # Fallback: Look for "Net Income" or "Net Profit" in Rows
            for row in reversed(all_rows):  # Check from end backwards
                label = safe_str_lower(_get_row_label(row), "")
                if "net income" in label or "net profit" in label or label == "net income":
                    net_profit = _extract_value_from_row(row)
                    logger.info("[P&L] Net Profit (Row with label '%s'): %s", _get_row_label(row), net_profit)
                    break
        
        logger.info("[P&L] Extraction complete: revenue=%s, cost_of_sales=%s, gross_profit=%s, expenses=%s, net_profit=%s",
                    revenue, cost_of_sales, gross_profit, expenses, net_profit)
        
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
        trial_balance_pnl: Optional[dict[str, Any]],
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
        logger.info("[Profitability] P&L extraction result: revenue=%s, cost_of_sales=%s, gross_profit=%s, expenses=%s, net_profit=%s",
                    pnl_values.get("revenue"), pnl_values.get("cost_of_sales"), pnl_values.get("gross_profit"),
                    pnl_values.get("expenses"), pnl_values.get("net_profit"))
        
        # Merge with Trial Balance P&L if available (deterministic by AccountType)
        if isinstance(trial_balance_pnl, dict):
            logger.info("[Profitability] Trial Balance P&L available: %s", trial_balance_pnl)
            for key in ["revenue", "cost_of_sales", "expenses"]:
                tb_value = trial_balance_pnl.get(key)
                # Use Trial Balance value if it exists (including 0.0, which is valid)
                # Only skip if the key doesn't exist in the dict (None from .get() when key missing)
                if key in trial_balance_pnl:
                    pnl_values[key] = tb_value
                    logger.info("[Profitability] Using Trial Balance %s: %s (was: %s)", key, tb_value, pnl_values.get(key))
        else:
            logger.warning("[Profitability] Trial Balance P&L not available or invalid: %s", type(trial_balance_pnl))
        
        # Derive missing gross_profit and net_profit using math (deterministic)
        if pnl_values.get("gross_profit") is None:
            if pnl_values.get("revenue") is not None and pnl_values.get("cost_of_sales") is not None:
                pnl_values["gross_profit"] = pnl_values["revenue"] - pnl_values["cost_of_sales"]
        
        if pnl_values.get("net_profit") is None:
            if pnl_values.get("gross_profit") is not None and pnl_values.get("expenses") is not None:
                pnl_values["net_profit"] = pnl_values["gross_profit"] - pnl_values["expenses"]
            elif pnl_values.get("revenue") is not None and pnl_values.get("expenses") is not None:
                # Fallback: revenue minus expenses if cost_of_sales missing
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
        
        # Determine risk level based on available data
        risk_level = "low"
        if gross_margin is not None:
            if gross_margin < 20:
                risk_level = "high"
            elif gross_margin < 30:
                risk_level = "medium"
        # Consider net profit losses even if gross margin is high
        if pnl_values.get("net_profit") is not None and pnl_values["net_profit"] < 0:
            risk_level = "high"
        elif profit_trend == "declining" and risk_level == "low":
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

