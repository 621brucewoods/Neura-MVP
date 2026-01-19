"""
Data Summarizer
Creates compact summaries of raw financial data for AI analysis.

Includes actual data structures with labels, not just metrics.
Limits depth and removes repetitive parts to keep it compact.
"""

from typing import Any, Union, Optional
from datetime import date


def _get_account_type_from_map(account_type_map: dict[str, Any], account_id: str) -> Optional[str]:
    """
    Get AccountType from account_type_map, supporting both old and new structures.
    
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


class DataSummarizer:
    """
    Summarizes raw financial data into compact format for AI insights.
    
    Strategy: Include actual data structures with labels, limit depth to avoid excessive nesting.
    """

    @staticmethod
    def _extract_report_structure(report_data: dict[str, Any], max_depth: int = 3) -> dict[str, Any]:
        """Extract report structure with labels, limiting depth."""
        if not report_data or not report_data.get("raw_data"):
            return {}

        raw_data = report_data.get("raw_data", {})
        rows = raw_data.get("Rows", raw_data.get("rows", []))

        def _process_rows(rows_list: list, depth: int = 0) -> list[dict[str, Any]]:
            """Process rows recursively, limiting depth."""
            if not isinstance(rows_list, list) or depth > max_depth:
                return []

            result = []
            for row in rows_list[:20]:  # Limit to first 20 rows per level
                if not isinstance(row, dict):
                    continue

                row_type = row.get("RowType", row.get("row_type", ""))
                cells = row.get("Cells", row.get("cells", []))

                row_data = {
                    "type": row_type,
                    "label": None,
                    "value": None,
                }

                if cells and isinstance(cells, list):
                    if len(cells) > 0:
                        first_cell = cells[0]
                        if isinstance(first_cell, dict):
                            row_data["label"] = first_cell.get("Value", first_cell.get("value", ""))

                    if len(cells) > 1:
                        value_cell = cells[1]
                        if isinstance(value_cell, dict):
                            value_str = value_cell.get("Value", value_cell.get("value", ""))
                            try:
                                row_data["value"] = float(value_str.replace(",", "").replace("$", "").strip())
                            except (ValueError, AttributeError):
                                row_data["value"] = value_str

                nested_rows = row.get("Rows", row.get("rows", []))
                if nested_rows and depth < max_depth:
                    nested = _process_rows(nested_rows, depth + 1)
                    if nested:
                        row_data["rows"] = nested

                result.append(row_data)

            return result

        return {
            "rows": _process_rows(rows) if rows else [],
        }

    @staticmethod
    def _extract_accounts_from_trial_balance(trial_balance: dict[str, Any], account_type_map: dict[str, Any]) -> list[dict[str, Any]]:
        """Extract account list with names and types from Trial Balance."""
        accounts = []
        
        if not trial_balance or not trial_balance.get("raw_data"):
            return accounts

        raw_data = trial_balance.get("raw_data", {})
        rows = raw_data.get("Rows", raw_data.get("rows", []))

        def _extract_accounts_from_rows(rows_list: list, seen_ids: set) -> None:
            """Extract accounts from Trial Balance rows."""
            if not isinstance(rows_list, list):
                return

            for row in rows_list:
                if not isinstance(row, dict):
                    continue

                row_type = row.get("RowType", row.get("row_type", ""))
                if row_type != "Row":
                    nested_rows = row.get("Rows", row.get("rows", []))
                    if nested_rows:
                        _extract_accounts_from_rows(nested_rows, seen_ids)
                    continue

                cells = row.get("Cells", row.get("cells", []))
                if not isinstance(cells, list) or len(cells) < 2:
                    continue

                first_cell = cells[0]
                if not isinstance(first_cell, dict):
                    continue

                attributes = first_cell.get("Attributes", first_cell.get("attributes", []))
                account_id = None

                if isinstance(attributes, list):
                    for attr in attributes:
                        if isinstance(attr, dict):
                            attr_id = attr.get("id", attr.get("Id", ""))
                            if attr_id == "account":
                                account_id = attr.get("value", attr.get("Value", ""))
                                break

                if not account_id or account_id in seen_ids:
                    continue

                seen_ids.add(account_id)
                # Use helper function to support both old and new structures
                account_type = _get_account_type_from_map(account_type_map, account_id)
                label = first_cell.get("Value", first_cell.get("value", ""))

                value_cell = cells[1] if len(cells) > 1 else {}
                value = None
                if isinstance(value_cell, dict):
                    value_str = value_cell.get("Value", value_cell.get("value", "0"))
                    try:
                        value = float(value_str.replace(",", "").replace("$", "").strip())
                    except (ValueError, AttributeError):
                        pass

                accounts.append({
                    "id": account_id,
                    "name": label,
                    "type": account_type,
                    "balance": value,
                })

                if len(accounts) >= 100:  # Limit to 100 accounts
                    return

        seen_ids = set()
        _extract_accounts_from_rows(rows, seen_ids)
        return accounts

    @staticmethod
    def summarize(
        financial_data: dict[str, Any],
        start_date: date,
        end_date: date,
        fetcher: Any
    ) -> dict[str, Any]:
        """
        Create compact summary of raw financial data for AI analysis.
        
        Includes actual data structures with labels, not just metrics.
        Limits depth and size to keep it compact.
        """
        # Account type map (needed for reliable extraction)
        account_type_map = financial_data.get("account_type_map", {})
        
        # Extract cash positions - use account_type_map for reliable extraction
        balance_sheet_current = financial_data.get("balance_sheet_current", {})
        balance_sheet_prior = financial_data.get("balance_sheet_prior", {})
        
        # Use balance_sheet_totals if available (already extracted reliably by orchestrator)
        balance_sheet_totals = financial_data.get("balance_sheet_totals", {})
        if balance_sheet_totals and "cash" in balance_sheet_totals:
            cash_current = balance_sheet_totals.get("cash")
        else:
            # Fallback to fetcher with account_type_map for reliable extraction
            cash_current = fetcher.extract_cash_from_balance_sheet(
                balance_sheet_current, 
                account_type_map=account_type_map if account_type_map else None
            )
        
        # Prior period - still need to extract (no pre-computed totals for prior)
        cash_prior = fetcher.extract_cash_from_balance_sheet(
            balance_sheet_prior,
            account_type_map=account_type_map if account_type_map else None
        )
        
        # Trial Balance P&L (already extracted)
        trial_balance_pnl = financial_data.get("trial_balance_pnl", {})
        
        # Invoices (already calculated, include all)
        receivables = financial_data.get("invoices_receivable", {})
        payables = financial_data.get("invoices_payable", {})
        
        # Profit & Loss report structure
        profit_loss = financial_data.get("profit_loss", {})
        
        # Trial Balance structure
        trial_balance = financial_data.get("trial_balance", {})

        return {
            "period": {
                "start_date": str(start_date),
                "end_date": str(end_date),
            },
            "cash": {
                "current": float(cash_current) if cash_current is not None else None,
                "prior": float(cash_prior) if cash_prior is not None else None,
                "change": float(cash_current - cash_prior) if cash_current is not None and cash_prior is not None else None,
            },
            "balance_sheet_current": DataSummarizer._extract_report_structure(balance_sheet_current),
            "balance_sheet_prior": DataSummarizer._extract_report_structure(balance_sheet_prior),
            "profit_loss": DataSummarizer._extract_report_structure(profit_loss),
            "trial_balance": DataSummarizer._extract_report_structure(trial_balance),
            "profitability": {
                "revenue": trial_balance_pnl.get("revenue"),
                "cost_of_sales": trial_balance_pnl.get("cost_of_sales"),
                "expenses": trial_balance_pnl.get("expenses"),
            },
            "receivables": {
                "total": receivables.get("total", 0.0),
                "overdue_amount": receivables.get("overdue_amount", 0.0),
                "overdue_count": receivables.get("overdue_count", 0),
                "total_count": receivables.get("count", 0),
                "avg_days_overdue": receivables.get("avg_days_overdue", 0.0),
                "invoices": receivables.get("invoices", []),  # All invoices with details
            },
            "payables": {
                "total": payables.get("total", 0.0),
                "overdue_amount": payables.get("overdue_amount", 0.0),
                "overdue_count": payables.get("overdue_count", 0),
                "total_count": payables.get("count", 0),
                "avg_days_overdue": payables.get("avg_days_overdue", 0.0),
                "invoices": payables.get("invoices", []),  # All invoices with details
            },
            "accounts": DataSummarizer._extract_accounts_from_trial_balance(trial_balance, account_type_map),
            "account_types": DataSummarizer._count_account_types(account_type_map),
        }
    
    @staticmethod
    def _count_account_types(account_type_map: dict[str, Any]) -> dict[str, int]:
        """
        Count accounts by type, supporting both old and new structures.
        
        Old structure: {"uuid": "REVENUE"}
        New structure: {"uuid": {"type": "REVENUE", "system_account": None}}
        """
        counts = {
            "total": len(account_type_map),
            "revenue": 0,
            "expense": 0,
            "cogs": 0,
            "bank": 0,
            "current": 0,
            "currliab": 0,
        }
        
        for account_id, info in account_type_map.items():
            # Get type from either structure
            if isinstance(info, str):
                account_type = info
            elif isinstance(info, dict):
                account_type = info.get("type", "")
            else:
                continue
            
            if not account_type:
                continue
            
            account_type_upper = account_type.upper()
            
            if account_type_upper == "REVENUE":
                counts["revenue"] += 1
            elif account_type_upper == "EXPENSE":
                counts["expense"] += 1
            elif account_type_upper in ("COGS", "DIRECTCOSTS"):
                counts["cogs"] += 1
            elif account_type_upper == "BANK":
                counts["bank"] += 1
            elif account_type_upper == "CURRENT":
                counts["current"] += 1
            elif account_type_upper == "CURRLIAB":
                counts["currliab"] += 1
        
        return counts
