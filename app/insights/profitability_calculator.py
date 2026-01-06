"""
Profitability calculator for P&L analysis.
"""

import logging
from typing import Any, Optional

from app.insights.utils import safe_float, safe_get, safe_list_get, safe_str_lower

logger = logging.getLogger(__name__)

# Synonym map for financial concepts across different locales and terminologies
FINANCIAL_SYNONYMS = {
    "revenue": [
        "revenue", "income", "sales", "turnover", "total income", "trading income",
        "total revenue", "total sales", "income total", "revenue total",
        "ventes", "chiffre d'affaires", "recettes"  # French
    ],
    "cost_of_sales": [
        "cost of sales", "cogs", "cost of goods", "cost of goods sold",
        "total cost of sales", "direct costs", "cost of revenue"
    ],
    "gross_profit": [
        "gross profit", "gross margin", "total gross profit", "gross income"
    ],
    "expenses": [
        "expenses", "operating expenses", "overheads", "costs", "total expenses",
        "total operating expenses", "operating costs", "operating expenditure"
    ],
    "net_profit": [
        "net profit", "net income", "profit", "total profit", "total net profit",
        "net profit after tax", "profit (loss)", "surplus (deficit)", "net result"
    ],
}


class ProfitabilityCalculator:
    """
    Calculates profitability metrics from P&L data.
    
    Analyzes gross margin, profit trends, and profitability pressure.
    """
    
    @staticmethod
    def _identify_row_intent(label: str) -> Optional[str]:
        """
        Identify the financial concept from a label using synonym matching.
        
        Args:
            label: Row label (e.g., "Total Revenue", "Turnover", "Ventes")
            
        Returns:
            Standardized key (e.g., "revenue", "expenses") or None if no match
        """
        if not label:
            return None
        
        clean_label = safe_str_lower(label, "").strip()
        
        for key, synonyms in FINANCIAL_SYNONYMS.items():
            for synonym in synonyms:
                if synonym in clean_label or clean_label in synonym:
                    return key
        
        return None
    
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
            
            row_type = safe_get(row, "row_type", "")
            if row_type != "Header":
                continue
            
            cells = safe_get(row, "cells", [])
            if not isinstance(cells, list) or len(cells) < 2:
                continue
            
            # Look for the first data column (skip empty first column)
            # Typically: Column 0 = empty/label, Column 1 = current period
            for i in range(1, len(cells)):
                cell = safe_list_get(cells, i)
                if isinstance(cell, dict):
                    value = safe_get(cell, "value", "")
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
        
        raw_data = safe_get(pnl_data, "raw_data", {})
        if not isinstance(raw_data, dict):
            raw_data = {}
        
        rows = safe_get(raw_data, "rows", [])
        if not isinstance(rows, list):
            rows = []
        
        # Find target column index from header
        target_col_index = ProfitabilityCalculator._find_target_column_index(rows)
        
        revenue = None
        cost_of_sales = None
        gross_profit = None
        expenses = None
        net_profit = None
        
        def _find_value_in_rows(rows_list: list, target_key: str, prefer_total: bool = True) -> Optional[float]:
            """
            Recursively search for value in P&L rows using semantic matching.
            
            Collects ALL matching values, then returns the best one based on priority:
            1. SummaryRow (always preferred when prefer_total=True)
            2. Row with "total" in label
            3. Any other matching Row
            
            Args:
                rows_list: List of row dictionaries
                target_key: Target financial concept key (e.g., "revenue", "expenses")
                prefer_total: If True, prefer SummaryRow (totals) over individual rows
            """
            if not isinstance(rows_list, list):
                return None
            
            found_values = []
            
            for row in rows_list:
                if not isinstance(row, dict):
                    continue
                
                row_type = safe_get(row, "row_type", "")
                cells = safe_get(row, "cells", [])
                if not isinstance(cells, list):
                    cells = []
                
                # Get label from appropriate location based on row_type
                label = ""
                if row_type == "Section":
                    # Section rows have label in title
                    label = safe_str_lower(safe_get(row, "title"), "")
                elif row_type in ["SummaryRow", "Row"]:
                    # SummaryRow/Row have label in first cell
                    if len(cells) > 0:
                        label_cell = safe_list_get(cells, 0)
                        if isinstance(label_cell, dict):
                            label = safe_str_lower(safe_get(label_cell, "value", ""), "")
                else:
                    # Fallback: try both title and first cell (handles empty-title sections)
                    title_label = safe_str_lower(safe_get(row, "title"), "")
                    cell_label = ""
                    if len(cells) > 0:
                        label_cell = safe_list_get(cells, 0)
                        if isinstance(label_cell, dict):
                            cell_label = safe_str_lower(safe_get(label_cell, "value", ""), "")
                    label = title_label or cell_label
                
                # Use semantic matching to identify if this row itself matches target
                row_intent = ProfitabilityCalculator._identify_row_intent(label)
                
                # Check if this row itself matches (only for non-Section rows, Sections are containers)
                if row_intent == target_key and row_type != "Section":
                    # Extract value from target column (not hard-coded index 1)
                    if len(cells) > target_col_index:
                        value_cell = safe_list_get(cells, target_col_index)
                        if isinstance(value_cell, dict):
                            value_str = safe_get(value_cell, "value", "0")
                            value = safe_float(value_str)
                            # Accept zero values (they're valid)
                            if value is not None:
                                # Determine priority: SummaryRow is ALWAYS highest priority
                                is_summary_row = (row_type == "SummaryRow")
                                has_total_in_label = ("total" in label)
                                # Priority: 2 = SummaryRow, 1 = has "total", 0 = regular row
                                priority = 2 if is_summary_row else (1 if has_total_in_label else 0)
                                found_values.append((value, priority))
                
                # ALWAYS search nested rows (even if current row doesn't match)
                # This handles empty-title Sections and ensures we find all matches
                nested_rows = safe_get(row, "rows", [])
                if isinstance(nested_rows, list) and nested_rows:
                    # Process nested rows directly (not recursive call) to maintain priority information
                    for nested_row in nested_rows:
                        if not isinstance(nested_row, dict):
                            continue
                        
                        nested_row_type = safe_get(nested_row, "row_type", "")
                        nested_cells = safe_get(nested_row, "cells", [])
                        if not isinstance(nested_cells, list):
                            nested_cells = []
                        
                        # Get nested row label
                        nested_label = ""
                        if nested_row_type in ["SummaryRow", "Row"]:
                            if len(nested_cells) > 0:
                                nested_label_cell = safe_list_get(nested_cells, 0)
                                if isinstance(nested_label_cell, dict):
                                    nested_label = safe_str_lower(safe_get(nested_label_cell, "value", ""), "")
                        
                        # Check if nested row matches
                        nested_intent = ProfitabilityCalculator._identify_row_intent(nested_label)
                        if nested_intent == target_key:
                            # Extract value from nested row
                            if len(nested_cells) > target_col_index:
                                nested_value_cell = safe_list_get(nested_cells, target_col_index)
                                if isinstance(nested_value_cell, dict):
                                    nested_value_str = safe_get(nested_value_cell, "value", "0")
                                    nested_value = safe_float(nested_value_str)
                                    if nested_value is not None:
                                        # Determine priority: SummaryRow is ALWAYS highest
                                        is_summary = (nested_row_type == "SummaryRow")
                                        has_total = ("total" in nested_label)
                                        priority = 2 if is_summary else (1 if has_total else 0)
                                        found_values.append((nested_value, priority))
                        
                        # Recursively search deeper nested rows (for multi-level nesting)
                        deeper_nested = safe_get(nested_row, "rows", [])
                        if isinstance(deeper_nested, list) and deeper_nested:
                            # Recursive call for deeper nesting - collect all matches
                            for deeper_row in deeper_nested:
                                if not isinstance(deeper_row, dict):
                                    continue
                                
                                deeper_row_type = safe_get(deeper_row, "row_type", "")
                                deeper_cells = safe_get(deeper_row, "cells", [])
                                if not isinstance(deeper_cells, list):
                                    deeper_cells = []
                                
                                deeper_label = ""
                                if deeper_row_type in ["SummaryRow", "Row"]:
                                    if len(deeper_cells) > 0:
                                        deeper_label_cell = safe_list_get(deeper_cells, 0)
                                        if isinstance(deeper_label_cell, dict):
                                            deeper_label = safe_str_lower(safe_get(deeper_label_cell, "value", ""), "")
                                
                                deeper_intent = ProfitabilityCalculator._identify_row_intent(deeper_label)
                                if deeper_intent == target_key:
                                    if len(deeper_cells) > target_col_index:
                                        deeper_value_cell = safe_list_get(deeper_cells, target_col_index)
                                        if isinstance(deeper_value_cell, dict):
                                            deeper_value_str = safe_get(deeper_value_cell, "value", "0")
                                            deeper_value = safe_float(deeper_value_str)
                                            if deeper_value is not None:
                                                is_deeper_summary = (deeper_row_type == "SummaryRow")
                                                has_deeper_total = ("total" in deeper_label)
                                                deeper_priority = 2 if is_deeper_summary else (1 if has_deeper_total else 0)
                                                found_values.append((deeper_value, deeper_priority))
            
            if not found_values:
                return None
            
            # Sort by priority (highest first): SummaryRow > "total" in label > regular row
            found_values.sort(key=lambda x: x[1], reverse=True)
            
            # If prefer_total, return the highest priority value (SummaryRow if available)
            if prefer_total:
                # Return the highest priority value (SummaryRow preferred)
                return found_values[0][0]
            
            # Return the first value found (already sorted by priority)
            return found_values[0][0]
        
        # Use semantic matching with synonym map (handles different locales and terminologies)
        revenue = _find_value_in_rows(rows, "revenue", prefer_total=True)
        cost_of_sales = _find_value_in_rows(rows, "cost_of_sales", prefer_total=True)
        gross_profit = _find_value_in_rows(rows, "gross_profit", prefer_total=True)
        expenses = _find_value_in_rows(rows, "expenses", prefer_total=True)
        net_profit = _find_value_in_rows(rows, "net_profit", prefer_total=True)
        
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

