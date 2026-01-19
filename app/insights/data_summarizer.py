"""
Data Summarizer
Creates compact summaries of raw financial data for AI analysis.

Uses the Extractors module for reliable data extraction.
"""

from typing import Any, Optional
from datetime import date

from app.integrations.xero.extractors import Extractors


class DataSummarizer:
    """
    Summarizes raw financial data into compact format for AI insights.
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

        return {"rows": _process_rows(rows) if rows else []}

    @staticmethod
    def _count_account_types(account_type_map: dict[str, Any]) -> dict[str, int]:
        """Count accounts by type."""
        counts = {
            "total": len(account_type_map),
            "revenue": 0,
            "expense": 0,
            "cogs": 0,
            "bank": 0,
            "current": 0,
            "currliab": 0,
        }
        
        for info in account_type_map.values():
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

    @staticmethod
    def summarize(
        financial_data: dict[str, Any],
        start_date: date,
        end_date: date,
        fetcher: Any = None  # Kept for backward compatibility, not used
    ) -> dict[str, Any]:
        """
        Create compact summary of raw financial data for AI analysis.
        
        Args:
            financial_data: Complete data from XeroDataFetcher.fetch_all_data()
            start_date: Period start date
            end_date: Period end date
            fetcher: Deprecated, not used
        
        Returns:
            Compact summary for AI analysis
        """
        account_type_map = financial_data.get("account_type_map", {})
        
        # Get raw data for report structure
        balance_sheet_current = financial_data.get("balance_sheet_current", {})
        balance_sheet_prior = financial_data.get("balance_sheet_prior", {})
        profit_loss = financial_data.get("profit_loss", {})
        trial_balance = financial_data.get("trial_balance", {})
        
        # Use extracted data (from Extractors module)
        extracted = financial_data.get("extracted")
        if extracted:
            bs_data = extracted.get("balance_sheet", {})
            pnl_data = extracted.get("pnl", {})
            cash_current = bs_data.get("cash")
            trial_balance_pnl = {
                "revenue": pnl_data.get("revenue"),
                "cost_of_sales": pnl_data.get("cost_of_sales"),
                "expenses": pnl_data.get("expenses"),
            }
        else:
            # Extract if not pre-extracted
            if account_type_map and balance_sheet_current:
                bs_data = Extractors.extract_balance_sheet(balance_sheet_current, account_type_map)
                cash_current = bs_data.get("cash")
            else:
                cash_current = None
            
            if account_type_map and trial_balance:
                pnl_data = Extractors.extract_pnl(trial_balance, account_type_map)
                trial_balance_pnl = {
                    "revenue": pnl_data.get("revenue"),
                    "cost_of_sales": pnl_data.get("cost_of_sales"),
                    "expenses": pnl_data.get("expenses"),
                }
            else:
                trial_balance_pnl = financial_data.get("trial_balance_pnl", {})
        
        # Extract prior period cash
        cash_prior = None
        if balance_sheet_prior and account_type_map:
            prior_bs = Extractors.extract_balance_sheet(balance_sheet_prior, account_type_map)
            cash_prior = prior_bs.get("cash")
        
        # Get receivables/payables
        receivables = financial_data.get("invoices_receivable", {})
        payables = financial_data.get("invoices_payable", {})

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
                "revenue": trial_balance_pnl.get("revenue") if trial_balance_pnl else None,
                "cost_of_sales": trial_balance_pnl.get("cost_of_sales") if trial_balance_pnl else None,
                "expenses": trial_balance_pnl.get("expenses") if trial_balance_pnl else None,
            },
            "receivables": {
                "total": receivables.get("total", 0.0),
                "overdue_amount": receivables.get("overdue_amount", 0.0),
                "overdue_count": receivables.get("overdue_count", 0),
                "total_count": receivables.get("count", 0),
                "avg_days_overdue": receivables.get("avg_days_overdue", 0.0),
                "invoices": receivables.get("invoices", []),
            },
            "payables": {
                "total": payables.get("total", 0.0),
                "overdue_amount": payables.get("overdue_amount", 0.0),
                "overdue_count": payables.get("overdue_count", 0),
                "total_count": payables.get("count", 0),
                "avg_days_overdue": payables.get("avg_days_overdue", 0.0),
                "invoices": payables.get("invoices", []),
            },
            "account_types": DataSummarizer._count_account_types(account_type_map),
        }
