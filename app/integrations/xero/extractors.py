"""
Data Extractors
===============

Single source of truth for extracting financial data from Xero API responses.

Design Principles:
1. ONE place for all extraction logic
2. AccountType-based only (no fragile label matching)
3. Handles ALL 17 Xero AccountTypes for maximum compatibility
4. Clear logging showing exactly what accounts contribute to each total
5. Returns clean typed data (see extracted_types.py)

Xero AccountTypes Handled:
- Balance Sheet: BANK, CURRENT, INVENTORY, PREPAYMENT, FIXED, NONCURRENT, 
                 DEPRECIATN, CURRLIAB, LIABILITY, TERMLIAB, EQUITY
- P&L: REVENUE, SALES, OTHERINCOME, DIRECTCOSTS, EXPENSE, OVERHEADS

Usage:
    from app.integrations.xero.extractors import Extractors
    
    # Extract all data at once
    financial_data = Extractors.extract_all(
        balance_sheet_raw=...,
        invoices_receivable=...,
        invoices_payable=...,
        account_map=...,
    )
    
    # Or extract individually
    bs_data = Extractors.extract_balance_sheet(raw_data, account_map)
    
    # Extract P&L from monthly data
    monthly_pnl = Extractors.extract_monthly_pnl_totals(monthly_data, account_map)
"""

import logging
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Optional

from app.integrations.xero.extracted_types import (
    BalanceSheetData,
    PnLData,
    InvoiceAgeingData,
    AgeingBucket,
    FinancialData,
)

logger = logging.getLogger(__name__)


# =============================================================================
# Account Map Helpers
# =============================================================================

def _get_account_type(account_map: dict, account_id: str) -> Optional[str]:
    """
    Get AccountType from account map.
    
    Supports both formats:
    - Old: {"uuid": "REVENUE"}
    - New: {"uuid": {"type": "REVENUE", "system_account": "DEBTORS"}}
    """
    info = account_map.get(account_id)
    if info is None:
        return None
    if isinstance(info, str):
        return info
    if isinstance(info, dict):
        return info.get("type")
    return None


def _get_system_account(account_map: dict, account_id: str) -> Optional[str]:
    """
    Get SystemAccount from account map (DEBTORS, CREDITORS, etc).
    
    Only available in new format.
    """
    info = account_map.get(account_id)
    if isinstance(info, dict):
        return info.get("system_account")
    return None


def _parse_value(value_str: Any) -> Decimal:
    """Parse a value string to Decimal, handling various formats."""
    if value_str is None:
        return Decimal("0")
    if isinstance(value_str, (int, float, Decimal)):
        return Decimal(str(value_str))
    
    s = str(value_str).strip()
    if not s:
        return Decimal("0")
    
    # Remove currency symbols and commas
    s = s.replace("$", "").replace(",", "").replace(" ", "")
    
    # Handle parentheses for negative
    if s.startswith("(") and s.endswith(")"):
        s = "-" + s[1:-1]
    
    try:
        return Decimal(s)
    except Exception:
        return Decimal("0")


def _extract_account_id(cell: dict) -> Optional[str]:
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


# =============================================================================
# Balance Sheet Extractor
# =============================================================================

class BalanceSheetExtractor:
    """
    Extracts Balance Sheet data using AccountType-based summing.
    
    Handles ALL Xero AccountTypes for Balance Sheet:
    - BANK → cash
    - CURRENT + DEBTORS → accounts_receivable
    - CURRENT (other) → other_current_assets
    - INVENTORY → inventory
    - PREPAYMENT → prepayments
    - FIXED → fixed_assets
    - NONCURRENT → non_current_assets
    - DEPRECIATN → accumulated_depreciation
    - CURRLIAB + CREDITORS → accounts_payable
    - CURRLIAB (other) → other_current_liabilities
    - LIABILITY → long_term_liabilities
    - TERMLIAB → long_term_liabilities
    - EQUITY → equity
    """
    
    @staticmethod
    def extract(
        raw_data: dict[str, Any],
        account_map: dict[str, Any],
    ) -> BalanceSheetData:
        """
        Extract Balance Sheet totals from raw Xero response.
        
        Args:
            raw_data: Raw balance sheet dict (should have 'raw_data' key or be raw itself)
            account_map: AccountID → AccountInfo mapping
            
        Returns:
            BalanceSheetData with all extracted totals
        """
        # Initialize accumulators for ALL AccountTypes
        totals = {
            # Current Assets
            "cash": Decimal("0"),
            "accounts_receivable": Decimal("0"),
            "other_current_assets": Decimal("0"),
            "inventory": Decimal("0"),
            "prepayments": Decimal("0"),
            # Non-Current Assets
            "fixed_assets": Decimal("0"),
            "non_current_assets": Decimal("0"),
            "accumulated_depreciation": Decimal("0"),
            # Current Liabilities
            "accounts_payable": Decimal("0"),
            "other_current_liabilities": Decimal("0"),
            # Non-Current Liabilities
            "long_term_liabilities": Decimal("0"),
            # Equity
            "equity": Decimal("0"),
        }
        
        # Track which accounts contributed (for debugging)
        account_sources: dict[str, list[str]] = {k: [] for k in totals}
        unhandled_types: dict[str, int] = {}  # Track unhandled types for logging
        has_data = False
        
        # Handle both {"raw_data": {...}} and direct raw format
        if isinstance(raw_data, dict):
            inner = raw_data.get("raw_data", raw_data)
        else:
            inner = {}
        
        rows = inner.get("Rows", inner.get("rows", []))
        if not isinstance(rows, list):
            logger.warning("Balance sheet has no valid rows")
            return BalanceSheetExtractor._empty_result()
        
        def process_rows(rows_list: list) -> None:
            nonlocal has_data
            
            for row in rows_list:
                if not isinstance(row, dict):
                    continue
                
                row_type = row.get("RowType", row.get("row_type", ""))
                
                if row_type == "Row":
                    cells = row.get("Cells", row.get("cells", []))
                    if not isinstance(cells, list) or len(cells) < 2:
                        continue
                    
                    # Get account ID from first cell
                    account_id = _extract_account_id(cells[0])
                    if not account_id:
                        continue
                    
                    # Look up account type
                    account_type = _get_account_type(account_map, account_id)
                    if not account_type:
                        continue
                    
                    system_account = _get_system_account(account_map, account_id)
                    
                    # Get value from second cell
                    value_cell = cells[1]
                    if not isinstance(value_cell, dict):
                        continue
                    
                    value_str = value_cell.get("Value", value_cell.get("value", "0"))
                    value = _parse_value(value_str)
                    
                    has_data = True
                    account_type_upper = account_type.upper()
                    system_upper = (system_account or "").upper()
                    
                    # Classify by AccountType - handle ALL Xero AccountTypes
                    if account_type_upper == "BANK":
                        totals["cash"] += value
                        account_sources["cash"].append(account_id[:8])
                    
                    elif account_type_upper == "CURRENT":
                        if system_upper == "DEBTORS":
                            totals["accounts_receivable"] += value
                            account_sources["accounts_receivable"].append(account_id[:8])
                        else:
                            totals["other_current_assets"] += value
                            account_sources["other_current_assets"].append(account_id[:8])
                    
                    elif account_type_upper == "INVENTORY":
                        totals["inventory"] += value
                        account_sources["inventory"].append(account_id[:8])
                    
                    elif account_type_upper == "PREPAYMENT":
                        totals["prepayments"] += value
                        account_sources["prepayments"].append(account_id[:8])
                    
                    elif account_type_upper == "FIXED":
                        totals["fixed_assets"] += value
                        account_sources["fixed_assets"].append(account_id[:8])
                    
                    elif account_type_upper == "NONCURRENT":
                        totals["non_current_assets"] += value
                        account_sources["non_current_assets"].append(account_id[:8])
                    
                    elif account_type_upper == "DEPRECIATN":
                        totals["accumulated_depreciation"] += value
                        account_sources["accumulated_depreciation"].append(account_id[:8])
                    
                    elif account_type_upper == "CURRLIAB":
                        if system_upper == "CREDITORS":
                            totals["accounts_payable"] += value
                            account_sources["accounts_payable"].append(account_id[:8])
                        else:
                            totals["other_current_liabilities"] += value
                            account_sources["other_current_liabilities"].append(account_id[:8])
                    
                    elif account_type_upper in ("LIABILITY", "TERMLIAB"):
                        totals["long_term_liabilities"] += value
                        account_sources["long_term_liabilities"].append(account_id[:8])
                    
                    elif account_type_upper == "EQUITY":
                        totals["equity"] += value
                        account_sources["equity"].append(account_id[:8])
                    
                    else:
                        # Track unhandled types (P&L types appearing in BS are normal)
                        # Only log truly unexpected types
                        pnl_types = {"REVENUE", "SALES", "OTHERINCOME", "DIRECTCOSTS", 
                                    "EXPENSE", "OVERHEADS", "COGS"}
                        if account_type_upper not in pnl_types:
                            unhandled_types[account_type_upper] = unhandled_types.get(account_type_upper, 0) + 1
                
                # Process nested rows
                nested = row.get("Rows", row.get("rows", []))
                if nested:
                    process_rows(nested)
        
        process_rows(rows)
        
        # Log any unhandled account types as warning
        if unhandled_types:
            logger.warning(
                "Unhandled AccountTypes in Balance Sheet (may affect totals): %s",
                unhandled_types
            )
        
        if not has_data:
            logger.warning("No account data found in balance sheet")
            return BalanceSheetExtractor._empty_result()
        
        # Calculate totals
        current_assets = (
            totals["cash"] + 
            totals["accounts_receivable"] + 
            totals["other_current_assets"] +
            totals["inventory"] +
            totals["prepayments"]
        )
        current_liabilities = totals["accounts_payable"] + totals["other_current_liabilities"]
        total_assets = (
            current_assets + 
            totals["fixed_assets"] + 
            totals["non_current_assets"] + 
            totals["accumulated_depreciation"]  # Usually negative
        )
        total_liabilities = current_liabilities + totals["long_term_liabilities"]
        
        # Log extraction summary
        logger.info(
            "Balance Sheet extracted: cash=%.2f (%d), AR=%.2f (%d), "
            "inventory=%.2f (%d), fixed=%.2f (%d), AP=%.2f (%d), "
            "equity=%.2f (%d), current_assets=%.2f, current_liab=%.2f",
            float(totals["cash"]), len(account_sources["cash"]),
            float(totals["accounts_receivable"]), len(account_sources["accounts_receivable"]),
            float(totals["inventory"]), len(account_sources["inventory"]),
            float(totals["fixed_assets"]), len(account_sources["fixed_assets"]),
            float(totals["accounts_payable"]), len(account_sources["accounts_payable"]),
            float(totals["equity"]), len(account_sources["equity"]),
            float(current_assets), float(current_liabilities)
        )
        
        return BalanceSheetData(
            cash=float(totals["cash"]),
            accounts_receivable=float(totals["accounts_receivable"]),
            other_current_assets=float(totals["other_current_assets"]),
            inventory=float(totals["inventory"]) if totals["inventory"] else None,
            prepayments=float(totals["prepayments"]) if totals["prepayments"] else None,
            current_assets_total=float(current_assets),
            fixed_assets=float(totals["fixed_assets"]),
            non_current_assets=float(totals["non_current_assets"]) if totals["non_current_assets"] else None,
            accumulated_depreciation=float(totals["accumulated_depreciation"]) if totals["accumulated_depreciation"] else None,
            total_assets=float(total_assets),
            accounts_payable=float(totals["accounts_payable"]),
            other_current_liabilities=float(totals["other_current_liabilities"]),
            current_liabilities_total=float(current_liabilities),
            long_term_liabilities=float(totals["long_term_liabilities"]) if totals["long_term_liabilities"] else None,
            total_liabilities=float(total_liabilities),
            equity=float(totals["equity"]) if totals["equity"] else None,
        )
    
    @staticmethod
    def _empty_result() -> BalanceSheetData:
        """Return empty result when no data available."""
        return BalanceSheetData(
            cash=None,
            accounts_receivable=None,
            other_current_assets=None,
            inventory=None,
            prepayments=None,
            current_assets_total=None,
            fixed_assets=None,
            non_current_assets=None,
            accumulated_depreciation=None,
            total_assets=None,
            accounts_payable=None,
            other_current_liabilities=None,
            current_liabilities_total=None,
            long_term_liabilities=None,
            total_liabilities=None,
            equity=None,
        )


# =============================================================================
# P&L Extractor
# =============================================================================

class PnLExtractor:
    """
    Extracts P&L data from any P&L-structured report using AccountType-based summing.
    
    Works with both Monthly P&L reports and any report containing P&L account data.
    The structure (Rows/Cells with AccountID attributes) is consistent across reports.
    
    AccountType mapping (all P&L types):
    - REVENUE → revenue
    - SALES → revenue  
    - OTHERINCOME → revenue
    - DIRECTCOSTS → cost_of_sales (COGS)
    - EXPENSE → expenses
    - OVERHEADS → expenses
    """
    
    @staticmethod
    def extract(
        raw_data: dict[str, Any],
        account_map: dict[str, Any],
    ) -> PnLData:
        """
        Extract P&L totals from a P&L-structured report.
        
        Args:
            raw_data: Raw P&L report dict (Monthly P&L or similar structure)
            account_map: AccountID → AccountInfo mapping
            
        Returns:
            PnLData with extracted totals and calculated profit
        """
        totals = {
            "revenue": Decimal("0"),
            "cost_of_sales": Decimal("0"),
            "expenses": Decimal("0"),
        }
        
        account_sources: dict[str, list[str]] = {k: [] for k in totals}
        unhandled_types: dict[str, int] = {}  # Track unhandled P&L types
        has_data = False
        
        # Handle both formats
        if isinstance(raw_data, dict):
            inner = raw_data.get("raw_data", raw_data)
        else:
            inner = {}
        
        rows = inner.get("Rows", inner.get("rows", []))
        if not isinstance(rows, list):
            logger.warning("P&L report has no valid rows")
            return PnLExtractor._empty_result()
        
        # AccountType to category mapping - all P&L types
        type_to_category = {
            "REVENUE": "revenue",
            "SALES": "revenue",
            "OTHERINCOME": "revenue",
            "DIRECTCOSTS": "cost_of_sales",
            "EXPENSE": "expenses",
            "OVERHEADS": "expenses",
        }
        
        # Balance sheet types that are expected to be skipped in P&L
        balance_sheet_types = {
            "BANK", "CURRENT", "INVENTORY", "PREPAYMENT", "FIXED", 
            "NONCURRENT", "DEPRECIATN", "CURRLIAB", "LIABILITY", 
            "TERMLIAB", "EQUITY"
        }
        
        def process_rows(rows_list: list) -> None:
            nonlocal has_data
            
            for row in rows_list:
                if not isinstance(row, dict):
                    continue
                
                row_type = row.get("RowType", row.get("row_type", ""))
                
                if row_type == "Row":
                    cells = row.get("Cells", row.get("cells", []))
                    if not isinstance(cells, list) or len(cells) < 2:
                        continue
                    
                    account_id = _extract_account_id(cells[0])
                    if not account_id:
                        continue
                    
                    account_type = _get_account_type(account_map, account_id)
                    if not account_type:
                        continue
                    
                    account_type_upper = account_type.upper()
                    category = type_to_category.get(account_type_upper)
                    
                    if not category:
                        # Track truly unhandled types (not BS types)
                        if account_type_upper not in balance_sheet_types:
                            unhandled_types[account_type_upper] = unhandled_types.get(account_type_upper, 0) + 1
                        continue
                    
                    value_cell = cells[1]
                    if not isinstance(value_cell, dict):
                        continue
                    
                    value_str = value_cell.get("Value", value_cell.get("value", "0"))
                    value = _parse_value(value_str)
                    
                    has_data = True
                    totals[category] += value
                    account_sources[category].append(account_id[:8])
                
                # Process nested rows
                nested = row.get("Rows", row.get("rows", []))
                if nested:
                    process_rows(nested)
        
        process_rows(rows)
        
        # Log any unhandled account types as warning
        if unhandled_types:
            logger.warning(
                "Unhandled AccountTypes in P&L (may affect totals): %s",
                unhandled_types
            )
        
        if not has_data:
            logger.warning("No P&L data found in report")
            return PnLExtractor._empty_result()
        
        # Calculate profits
        revenue = float(totals["revenue"])
        cogs = float(totals["cost_of_sales"])
        expenses = float(totals["expenses"])
        
        gross_profit = revenue - cogs
        net_profit = gross_profit - expenses
        
        logger.info(
            "P&L extracted: revenue=%.2f (%d accounts), "
            "COGS=%.2f (%d accounts), expenses=%.2f (%d accounts), net=%.2f",
            revenue, len(account_sources["revenue"]),
            cogs, len(account_sources["cost_of_sales"]),
            expenses, len(account_sources["expenses"]),
            net_profit
        )
        
        return PnLData(
            revenue=revenue,
            cost_of_sales=cogs,
            expenses=expenses,
            gross_profit=gross_profit,
            net_profit=net_profit,
        )
    
    @staticmethod
    def _empty_result() -> PnLData:
        """Return empty result when no data available."""
        return PnLData(
            revenue=None,
            cost_of_sales=None,
            expenses=None,
            gross_profit=None,
            net_profit=None,
        )


# =============================================================================
# Invoice Ageing Extractor
# =============================================================================

class InvoiceExtractor:
    """
    Extracts invoice ageing data from fetched invoices.
    
    Calculates ageing buckets based on due_date:
    - current: Not yet due
    - 1-30 days overdue
    - 31-60 days overdue
    - 61-90 days overdue
    - 90+ days overdue
    """
    
    @staticmethod
    def extract(
        invoice_data: dict[str, Any],
    ) -> InvoiceAgeingData:
        """
        Extract ageing data from invoice fetcher result.
        
        Args:
            invoice_data: Result from InvoicesFetcher.fetch_receivables/payables()
            
        Returns:
            InvoiceAgeingData with buckets and ratios
        """
        if not invoice_data or not isinstance(invoice_data, dict):
            return InvoiceExtractor._empty_result()
        
        total = float(invoice_data.get("total", 0))
        count = int(invoice_data.get("count", 0))
        overdue_total = float(invoice_data.get("overdue_amount", 0))
        overdue_count = int(invoice_data.get("overdue_count", 0))
        
        if count == 0:
            return InvoiceExtractor._empty_result()
        
        # Calculate ageing buckets from invoice list
        invoices = invoice_data.get("invoices", [])
        today = datetime.now(timezone.utc).date()
        
        buckets = {
            "current": {"amount": Decimal("0"), "count": 0},
            "days_1_30": {"amount": Decimal("0"), "count": 0},
            "days_31_60": {"amount": Decimal("0"), "count": 0},
            "days_61_90": {"amount": Decimal("0"), "count": 0},
            "days_90_plus": {"amount": Decimal("0"), "count": 0},
        }
        
        for inv in invoices:
            if not isinstance(inv, dict):
                continue
            
            amount = Decimal(str(inv.get("amount_due", 0)))
            due_date_str = inv.get("due_date")
            
            if not due_date_str:
                buckets["current"]["amount"] += amount
                buckets["current"]["count"] += 1
                continue
            
            try:
                # Parse due date
                if isinstance(due_date_str, str):
                    due_date = datetime.fromisoformat(due_date_str.replace("Z", "+00:00")).date()
                else:
                    due_date = due_date_str
                
                days_overdue = (today - due_date).days
                
                if days_overdue <= 0:
                    buckets["current"]["amount"] += amount
                    buckets["current"]["count"] += 1
                elif days_overdue <= 30:
                    buckets["days_1_30"]["amount"] += amount
                    buckets["days_1_30"]["count"] += 1
                elif days_overdue <= 60:
                    buckets["days_31_60"]["amount"] += amount
                    buckets["days_31_60"]["count"] += 1
                elif days_overdue <= 90:
                    buckets["days_61_90"]["amount"] += amount
                    buckets["days_61_90"]["count"] += 1
                else:
                    buckets["days_90_plus"]["amount"] += amount
                    buckets["days_90_plus"]["count"] += 1
                    
            except Exception:
                buckets["current"]["amount"] += amount
                buckets["current"]["count"] += 1
        
        # Convert to output format
        def make_bucket(key: str) -> AgeingBucket:
            amt = float(buckets[key]["amount"])
            cnt = buckets[key]["count"]
            pct = (amt / total * 100) if total > 0 else 0
            return AgeingBucket(amount=amt, count=cnt, percentage=round(pct, 2))
        
        # Calculate ratios
        over_30 = (
            float(buckets["days_31_60"]["amount"]) +
            float(buckets["days_61_90"]["amount"]) +
            float(buckets["days_90_plus"]["amount"])
        )
        over_60 = (
            float(buckets["days_61_90"]["amount"]) +
            float(buckets["days_90_plus"]["amount"])
        )
        
        over_30_ratio = over_30 / total if total > 0 else 0
        over_60_ratio = over_60 / total if total > 0 else 0
        
        logger.info(
            "Invoices extracted: total=%.2f, count=%d, over_30=%.1f%%, over_60=%.1f%%",
            total, count, over_30_ratio * 100, over_60_ratio * 100
        )
        
        return InvoiceAgeingData(
            total=total,
            count=count,
            overdue_total=overdue_total,
            overdue_count=overdue_count,
            current=make_bucket("current"),
            days_1_30=make_bucket("days_1_30"),
            days_31_60=make_bucket("days_31_60"),
            days_61_90=make_bucket("days_61_90"),
            days_90_plus=make_bucket("days_90_plus"),
            over_30_days_ratio=round(over_30_ratio, 4),
            over_60_days_ratio=round(over_60_ratio, 4),
        )
    
    @staticmethod
    def _empty_result() -> InvoiceAgeingData:
        """Return empty result when no data available."""
        empty_bucket = AgeingBucket(amount=0, count=0, percentage=0)
        return InvoiceAgeingData(
            total=0,
            count=0,
            overdue_total=0,
            overdue_count=0,
            current=empty_bucket,
            days_1_30=empty_bucket,
            days_31_60=empty_bucket,
            days_61_90=empty_bucket,
            days_90_plus=empty_bucket,
            over_30_days_ratio=0,
            over_60_days_ratio=0,
        )


# =============================================================================
# Main Extractor Interface
# =============================================================================

class Extractors:
    """
    Main entry point for data extraction.
    
    Provides both individual extractors and a combined extract_all() method.
    """
    
    @staticmethod
    def extract_balance_sheet(
        raw_data: dict[str, Any],
        account_map: dict[str, Any],
    ) -> BalanceSheetData:
        """Extract Balance Sheet data."""
        return BalanceSheetExtractor.extract(raw_data, account_map)
    
    @staticmethod
    def extract_receivables(invoice_data: dict[str, Any]) -> InvoiceAgeingData:
        """Extract Accounts Receivable ageing."""
        return InvoiceExtractor.extract(invoice_data)
    
    @staticmethod
    def extract_payables(invoice_data: dict[str, Any]) -> InvoiceAgeingData:
        """Extract Accounts Payable ageing."""
        return InvoiceExtractor.extract(invoice_data)
    
    @staticmethod
    def extract_monthly_pnl_totals(
        monthly_pnl_data: list[dict[str, Any]],
        account_map: dict[str, Any],
    ) -> list[dict[str, Any]]:
        """
        Extract P&L totals from monthly P&L data.
        
        Takes the raw monthly P&L data from fetcher and extracts revenue,
        expenses, etc. using AccountType-based extraction.
        
        Args:
            monthly_pnl_data: List of monthly P&L data from fetch_monthly_pnl()
            account_map: AccountID → AccountInfo mapping
            
        Returns:
            List of monthly P&L with extracted totals, sorted newest first
        """
        result = []
        
        for month_entry in monthly_pnl_data:
            month_key = month_entry.get("month_key")
            raw_data = month_entry.get("raw_data", month_entry.get("data", {}))
            
            if not raw_data:
                # No data for this month
                result.append({
                    "month_key": month_key,
                    "year": month_entry.get("year"),
                    "month": month_entry.get("month"),
                    "revenue": None,
                    "cost_of_sales": None,
                    "expenses": None,
                    "gross_profit": None,
                    "net_profit": None,
                    "has_data": False,
                })
                continue
            
            # Extract P&L using AccountType-based extraction
            pnl = PnLExtractor.extract(raw_data, account_map)
            
            result.append({
                "month_key": month_key,
                "year": month_entry.get("year"),
                "month": month_entry.get("month"),
                "revenue": pnl.get("revenue"),
                "cost_of_sales": pnl.get("cost_of_sales"),
                "expenses": pnl.get("expenses"),
                "gross_profit": pnl.get("gross_profit"),
                "net_profit": pnl.get("net_profit"),
                "has_data": pnl.get("revenue") is not None,
            })
        
        # Sort by month (newest first)
        result.sort(key=lambda x: x.get("month_key", ""), reverse=True)
        
        logger.info(
            "Extracted P&L totals for %d months: %s",
            len(result),
            [f"{m['month_key']}:${m.get('revenue') or 0:.0f}" for m in result[:3]]
        )
        
        return result
    
    @staticmethod
    def extract_all(
        balance_sheet_raw: dict[str, Any],
        invoices_receivable: dict[str, Any],
        invoices_payable: dict[str, Any],
        account_map: dict[str, Any],
        organization_id: Optional[str] = None,
        period_start: Optional[str] = None,
        period_end: Optional[str] = None,
    ) -> FinancialData:
        """
        Extract all financial data in one call.
        
        This is the primary method for downstream services.
        
        Note: P&L data is now extracted from Monthly P&L reports via
        extract_monthly_pnl_totals(), not from this method. The pnl field
        in the result will be empty - use monthly P&L data instead.
        
        Args:
            balance_sheet_raw: Raw balance sheet from Xero
            invoices_receivable: Result from fetch_receivables()
            invoices_payable: Result from fetch_payables()
            account_map: AccountID → AccountInfo mapping
            organization_id: Optional org ID for logging
            period_start: Optional period start date (ISO)
            period_end: Optional period end date (ISO)
            
        Returns:
            Complete FinancialData structure (pnl will be empty)
        """
        logger.info("Starting full data extraction for org=%s", organization_id or "unknown")
        
        # Extract each section
        balance_sheet = Extractors.extract_balance_sheet(balance_sheet_raw, account_map)
        receivables = Extractors.extract_receivables(invoices_receivable)
        payables = Extractors.extract_payables(invoices_payable)
        
        # P&L is now extracted from Monthly P&L reports, not here
        # Return empty P&L - callers should use extract_monthly_pnl_totals()
        pnl = PnLExtractor._empty_result()
        
        # Determine data availability
        has_bs = balance_sheet.get("cash") is not None
        has_ar = receivables.get("count", 0) > 0
        has_ap = payables.get("count", 0) > 0
        
        logger.info(
            "Extraction complete: has_bs=%s, has_ar=%s, has_ap=%s",
            has_bs, has_ar, has_ap
        )
        
        return FinancialData(
            balance_sheet=balance_sheet,
            pnl=pnl,
            receivables=receivables,
            payables=payables,
            extraction_timestamp=datetime.now(timezone.utc).isoformat(),
            organization_id=organization_id,
            period_start=period_start,
            period_end=period_end,
            has_balance_sheet=has_bs,
            has_pnl=False,  # P&L comes from monthly data now
            has_receivables=has_ar,
            has_payables=has_ap,
        )
