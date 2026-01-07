"""
Xero Data Parsers
Extract and parse data from Xero API responses.
"""

import logging
from decimal import Decimal
from typing import Any, Optional

from app.integrations.xero.utils import parse_currency_value

logger = logging.getLogger(__name__)


class BalanceSheetParser:
    """Parser for Balance Sheet data."""
    
    @staticmethod
    def extract_cash(balance_sheet: dict[str, Any]) -> Optional[float]:
        """
        Extract cash position from Balance Sheet.
        
        Looks for "Total Cash and Cash Equivalents" SummaryRow in the Balance Sheet.
        Uses the first data column (typically index 1).
        
        Args:
            balance_sheet: Balance Sheet data structure
            
        Returns:
            Cash position as float, or None if not found
        """
        if not balance_sheet or not isinstance(balance_sheet, dict):
            return None
        
        raw_data = balance_sheet.get("raw_data", {})
        if not isinstance(raw_data, dict):
            return None
        
        # Xero API uses "Rows" (PascalCase), try both for compatibility
        rows = raw_data.get("Rows", raw_data.get("rows", []))
        if not isinstance(rows, list):
            return None
        
        # Recursively search for "Total Cash and Cash Equivalents" SummaryRow
        def _search_rows(rows_list: list) -> Optional[float]:
            for row in rows_list:
                if not isinstance(row, dict):
                    continue
                
                # Xero API uses PascalCase (RowType, Title, Rows, Cells, Value), try both
                row_type = row.get("RowType", row.get("row_type", ""))
                
                # Check if this is a SummaryRow with "Total Cash" in label
                if row_type == "SummaryRow":
                    cells = row.get("Cells", row.get("cells", []))
                    if isinstance(cells, list) and len(cells) >= 2:
                        first_cell = cells[0]
                        if isinstance(first_cell, dict):
                            label = str(first_cell.get("Value", first_cell.get("value", ""))).lower()
                            if "total" in label and "cash" in label:
                                # Found it! Extract value from second cell (index 1)
                                value_cell = cells[1]
                                if isinstance(value_cell, dict):
                                    value_str = value_cell.get("Value", value_cell.get("value", ""))
                                    parsed = parse_currency_value(value_str, "0.00")
                                    return float(parsed)
                
                # Recursively search nested rows
                nested_rows = row.get("Rows", row.get("rows", []))
                if isinstance(nested_rows, list):
                    result = _search_rows(nested_rows)
                    if result is not None:
                        return result
            
            return None
        
        return _search_rows(rows)


class TrialBalanceParser:
    """Parser for Trial Balance data."""
    
    @staticmethod
    def extract_account_id(cell: dict) -> Optional[str]:
        """Extract AccountID from cell attributes."""
        if not isinstance(cell, dict):
            return None

        attributes = cell.get("Attributes", cell.get("attributes", []))
        if not isinstance(attributes, list):
            return None

        for attr in attributes:
            if not isinstance(attr, dict):
                continue
            attr_id = attr.get("id", attr.get("Id", ""))
            if attr_id == "account":
                return attr.get("value", attr.get("Value", ""))

        return None
    
    @staticmethod
    def process_rows(
        rows_list: list,
        account_type_map: dict[str, str],
        totals: dict[str, Decimal]
    ) -> None:
        """Recursively process Trial Balance rows to extract account balances by AccountType."""
        if not isinstance(rows_list, list):
            return

        account_type_to_key = {
            "REVENUE": "revenue",
            "COGS": "cost_of_sales",
            "EXPENSE": "expenses",
        }

        for row in rows_list:
            if not isinstance(row, dict):
                continue

            row_type = row.get("RowType", row.get("row_type", ""))
            if row_type != "Row":
                nested_rows = row.get("Rows", row.get("rows", []))
                if nested_rows:
                    TrialBalanceParser.process_rows(nested_rows, account_type_map, totals)
                continue

            cells = row.get("Cells", row.get("cells", []))
            if not isinstance(cells, list) or len(cells) < 2:
                continue

            account_id = TrialBalanceParser.extract_account_id(cells[0])
            if not account_id:
                continue

            account_type = account_type_map.get(account_id)
            if not account_type:
                continue

            value_cell = cells[1]
            if not isinstance(value_cell, dict):
                continue

            value_str = value_cell.get("Value", value_cell.get("value", "0"))
            value = parse_currency_value(value_str, "0.00")

            account_type_key = account_type_to_key.get(account_type.upper())
            if account_type_key:
                totals[account_type_key] += value
    
    @staticmethod
    def extract_pnl(
        trial_balance: dict[str, Any],
        account_type_map: dict[str, str]
    ) -> dict[str, Optional[float]]:
        """
        Extract P&L values from Trial Balance using AccountType mapping.
        
        Deterministic method using fixed AccountType (REVENUE, EXPENSE, COGS).
        Gross profit and net profit are calculated, not extracted.
        """
        if not trial_balance or not trial_balance.get("raw_data"):
            return {"revenue": None, "cost_of_sales": None, "expenses": None}

        raw_data = trial_balance.get("raw_data", {})
        if not isinstance(raw_data, dict):
            return {"revenue": None, "cost_of_sales": None, "expenses": None}

        rows = raw_data.get("Rows", raw_data.get("rows", []))
        if not isinstance(rows, list):
            rows = []

        totals = {
            "revenue": Decimal("0.00"),
            "cost_of_sales": Decimal("0.00"),
            "expenses": Decimal("0.00"),
        }

        TrialBalanceParser.process_rows(rows, account_type_map, totals)

        return {
            "revenue": float(totals["revenue"]),
            "cost_of_sales": float(totals["cost_of_sales"]),
            "expenses": float(totals["expenses"]),
        }

