"""
Xero Data Parsers
Extract and parse data from Xero API responses.

Uses AccountType-based parsing for reliability across all organizations.
AccountType is a fixed Xero enum that doesn't change per org.
"""

import logging
from decimal import Decimal
from typing import Any, Optional, TypedDict, Union

from app.integrations.xero.utils import parse_currency_value

logger = logging.getLogger(__name__)


class AccountInfo(TypedDict):
    """Account information structure from accounts fetcher."""
    type: str  # AccountType: BANK, CURRENT, CURRLIAB, REVENUE, EXPENSE, etc.
    system_account: Optional[str]  # SystemAccount: DEBTORS, CREDITORS, etc. or None


class BalanceSheetTotals(TypedDict):
    """Balance Sheet totals by AccountType."""
    cash: Optional[float]  # Sum of BANK accounts
    accounts_receivable: Optional[float]  # CURRENT with SystemAccount=DEBTORS
    other_current_assets: Optional[float]  # CURRENT without DEBTORS
    current_assets_total: Optional[float]  # BANK + all CURRENT
    inventory: Optional[float]  # Estimated from CURRENT (not DEBTORS)
    fixed_assets: Optional[float]  # Sum of FIXED accounts
    accounts_payable: Optional[float]  # CURRLIAB with SystemAccount=CREDITORS
    other_current_liabilities: Optional[float]  # CURRLIAB without CREDITORS
    current_liabilities_total: Optional[float]  # Sum of all CURRLIAB


# Type alias for backward compatibility and new structure
AccountTypeMap = dict[str, Union[str, AccountInfo]]


def get_account_type(account_type_map: AccountTypeMap, account_id: str) -> Optional[str]:
    """
    Get AccountType from account_type_map, supporting both old and new structure.
    
    Old structure: {"uuid": "REVENUE"}
    New structure: {"uuid": {"type": "REVENUE", "system_account": None}}
    """
    info = account_type_map.get(account_id)
    if info is None:
        return None
    if isinstance(info, str):
        return info  # Old structure
    if isinstance(info, dict):
        return info.get("type")  # New structure
    return None


def get_system_account(account_type_map: AccountTypeMap, account_id: str) -> Optional[str]:
    """
    Get SystemAccount from account_type_map (new structure only).
    
    Returns None for old structure or if not a system account.
    """
    info = account_type_map.get(account_id)
    if info is None:
        return None
    if isinstance(info, dict):
        return info.get("system_account")
    return None  # Old structure has no system_account


class BalanceSheetAccountTypeParser:
    """
    Parse Balance Sheet by AccountType summing (reliable method).
    
    Works across all organizations regardless of Chart of Accounts customization.
    Uses Xero's fixed AccountType enum and SystemAccount field.
    """
    
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
    def extract_totals(
        balance_sheet: dict[str, Any],
        account_type_map: AccountTypeMap
    ) -> BalanceSheetTotals:
        """
        Sum Balance Sheet accounts by AccountType.
        
        This method iterates through individual Row entries (not SummaryRows),
        extracts the AccountID from attributes, looks up the AccountType,
        and sums values accordingly.
        
        Args:
            balance_sheet: Balance Sheet data structure with raw_data
            account_type_map: AccountID to AccountInfo mapping
            
        Returns:
            BalanceSheetTotals with all calculated totals
        """
        # Initialize totals using Decimal for precision
        totals = {
            "cash": Decimal("0"),
            "accounts_receivable": Decimal("0"),
            "other_current_assets": Decimal("0"),
            "current_assets_total": Decimal("0"),
            "inventory": Decimal("0"),
            "fixed_assets": Decimal("0"),
            "accounts_payable": Decimal("0"),
            "other_current_liabilities": Decimal("0"),
            "current_liabilities_total": Decimal("0"),
        }
        
        has_data = False
        
        if not balance_sheet or not isinstance(balance_sheet, dict):
            return {k: None for k in totals.keys()}
        
        raw_data = balance_sheet.get("raw_data", {})
        if not isinstance(raw_data, dict):
            return {k: None for k in totals.keys()}
        
        rows = raw_data.get("Rows", raw_data.get("rows", []))
        if not isinstance(rows, list):
            return {k: None for k in totals.keys()}
        
        def _process_rows(rows_list: list) -> None:
            nonlocal has_data
            
            for row in rows_list:
                if not isinstance(row, dict):
                    continue
                
                row_type = row.get("RowType", row.get("row_type", ""))
                
                # Only process Row entries (skip Section, SummaryRow, Header)
                if row_type == "Row":
                    cells = row.get("Cells", row.get("cells", []))
                    if not isinstance(cells, list) or len(cells) < 2:
                        continue
                    
                    # Extract AccountID from first cell attributes
                    account_id = BalanceSheetAccountTypeParser.extract_account_id(cells[0])
                    if not account_id:
                        continue
                    
                    # Look up account type and system account
                    account_type = get_account_type(account_type_map, account_id)
                    if not account_type:
                        continue
                    
                    system_account = get_system_account(account_type_map, account_id)
                    
                    # Extract value from second cell (first data column)
                    value_cell = cells[1]
                    if not isinstance(value_cell, dict):
                        continue
                    
                    value_str = value_cell.get("Value", value_cell.get("value", "0"))
                    value = parse_currency_value(value_str, "0.00")
                    
                    has_data = True
                    account_type_upper = account_type.upper()
                    system_account_upper = system_account.upper() if system_account else ""
                    
                    # Sum by AccountType
                    if account_type_upper == "BANK":
                        totals["cash"] += value
                        totals["current_assets_total"] += value
                    
                    elif account_type_upper == "CURRENT":
                        totals["current_assets_total"] += value
                        if system_account_upper == "DEBTORS":
                            totals["accounts_receivable"] += value
                        else:
                            totals["other_current_assets"] += value
                    
                    elif account_type_upper == "FIXED":
                        totals["fixed_assets"] += value
                    
                    elif account_type_upper == "CURRLIAB":
                        totals["current_liabilities_total"] += value
                        if system_account_upper == "CREDITORS":
                            totals["accounts_payable"] += value
                        else:
                            totals["other_current_liabilities"] += value
                
                # Recursively process nested rows
                nested_rows = row.get("Rows", row.get("rows", []))
                if nested_rows:
                    _process_rows(nested_rows)
        
        _process_rows(rows)
        
        if not has_data:
            return {k: None for k in totals.keys()}
        
        # Convert Decimal to float for JSON serialization
        return {k: float(v) for k, v in totals.items()}


class BalanceSheetParser:
    """
    Parser for Balance Sheet data.
    
    Note: extract_cash() now uses AccountType-based method when account_type_map
    is provided. Falls back to label-based search for backward compatibility.
    """
    
    @staticmethod
    def extract_cash(
        balance_sheet: dict[str, Any],
        account_type_map: Optional[AccountTypeMap] = None
    ) -> Optional[float]:
        """
        Extract cash position from Balance Sheet.
        
        Primary method: Sum all BANK AccountType accounts (reliable).
        Fallback method: Search for "Total Cash" SummaryRow label (fragile).
        
        Args:
            balance_sheet: Balance Sheet data structure
            account_type_map: Optional AccountID to AccountInfo mapping for reliable extraction
            
        Returns:
            Cash position as float, or None if not found
        """
        # Primary method: AccountType-based (reliable)
        if account_type_map:
            totals = BalanceSheetAccountTypeParser.extract_totals(balance_sheet, account_type_map)
            cash = totals.get("cash")
            if cash is not None:
                logger.debug("Extracted cash using AccountType method: %s", cash)
                return cash
            # Fall through to fallback if AccountType method returned None
        
        # Fallback method: Label-based search (fragile, for backward compatibility)
        logger.warning("Using fallback label-based cash extraction (less reliable)")
        
        if not balance_sheet or not isinstance(balance_sheet, dict):
            return None
        
        raw_data = balance_sheet.get("raw_data", {})
        if not isinstance(raw_data, dict):
            return None
        
        rows = raw_data.get("Rows", raw_data.get("rows", []))
        if not isinstance(rows, list):
            return None
        
        def _search_rows(rows_list: list) -> Optional[float]:
            for row in rows_list:
                if not isinstance(row, dict):
                    continue
                
                row_type = row.get("RowType", row.get("row_type", ""))
                
                if row_type == "SummaryRow":
                    cells = row.get("Cells", row.get("cells", []))
                    if isinstance(cells, list) and len(cells) >= 2:
                        first_cell = cells[0]
                        if isinstance(first_cell, dict):
                            label = str(first_cell.get("Value", first_cell.get("value", ""))).lower()
                            if "total" in label and "cash" in label:
                                value_cell = cells[1]
                                if isinstance(value_cell, dict):
                                    value_str = value_cell.get("Value", value_cell.get("value", ""))
                                    parsed = parse_currency_value(value_str, "0.00")
                                    return float(parsed)
                
                nested_rows = row.get("Rows", row.get("rows", []))
                if isinstance(nested_rows, list):
                    result = _search_rows(nested_rows)
                    if result is not None:
                        return result
            
            return None
        
        return _search_rows(rows)


class TrialBalanceParser:
    """
    Parser for Trial Balance data.
    
    Uses AccountType-based extraction for deterministic P&L calculation.
    Supports both old (string) and new (dict) account_type_map structures.
    """
    
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
        account_type_map: AccountTypeMap,
        totals: dict[str, Decimal]
    ) -> None:
        """
        Recursively process Trial Balance rows to extract account balances by AccountType.
        
        Supports both old and new account_type_map structures:
        - Old: {"uuid": "REVENUE"}
        - New: {"uuid": {"type": "REVENUE", "system_account": None}}
        """
        if not isinstance(rows_list, list):
            return

        account_type_to_key = {
            "REVENUE": "revenue",
            "SALES": "revenue",  # Some orgs use SALES instead of REVENUE
            "OTHERINCOME": "revenue",  # Other income also counts as revenue
            "COGS": "cost_of_sales",
            "DIRECTCOSTS": "cost_of_sales",  # Xero uses DIRECTCOSTS for COGS
            "EXPENSE": "expenses",
            "OVERHEADS": "expenses",  # Overheads are also expenses
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

            # Use helper function to support both old and new structures
            account_type = get_account_type(account_type_map, account_id)
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
        account_type_map: AccountTypeMap
    ) -> dict[str, Optional[float]]:
        """
        Extract P&L values from Trial Balance using AccountType mapping.
        
        Deterministic method using fixed AccountType (REVENUE, EXPENSE, COGS).
        Gross profit and net profit are calculated, not extracted.
        
        Supports both old and new account_type_map structures.
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

