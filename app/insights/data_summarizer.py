"""
Data Summarizer
Creates compact summaries of raw financial data for AI analysis.

Uses Monthly P&L data for profitability (not Trial Balance).
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
    def _aggregate_monthly_pnl(
        monthly_pnl_data: Optional[list[dict[str, Any]]],
        num_months: int = 3
    ) -> dict[str, Optional[float]]:
        """
        Aggregate monthly P&L data into rolling totals.
        
        Args:
            monthly_pnl_data: List of monthly P&L (newest first)
            num_months: Number of months to aggregate (default 3)
            
        Returns:
            Dict with revenue, cost_of_sales, expenses (rolling sum)
        """
        if not monthly_pnl_data:
            return {"revenue": None, "cost_of_sales": None, "expenses": None}
        
        revenues = []
        cogs_list = []
        expenses_list = []
        
        for month in monthly_pnl_data[:num_months]:
            rev = month.get("revenue")
            cogs = month.get("cost_of_sales")
            exp = month.get("expenses")
            
            if rev is not None:
                revenues.append(float(rev))
            if cogs is not None:
                cogs_list.append(float(cogs))
            if exp is not None:
                expenses_list.append(float(exp))
        
        return {
            "revenue": sum(revenues) if revenues else None,
            "cost_of_sales": sum(cogs_list) if cogs_list else None,
            "expenses": sum(expenses_list) if expenses_list else None,
        }

    @staticmethod
    def summarize(
        financial_data: dict[str, Any],
        balance_sheet_date: date,
        monthly_pnl_data: Optional[list[dict[str, Any]]] = None,
    ) -> dict[str, Any]:
        """
        Create compact summary of raw financial data for AI analysis.
        
        Args:
            financial_data: Complete data from XeroDataFetcher.fetch_all_data()
            balance_sheet_date: Balance sheet as-of date
            monthly_pnl_data: Monthly P&L data for profitability (newest first)
        
        Returns:
            Compact summary for AI analysis
        """
        account_type_map = financial_data.get("account_type_map", {})
        
        # Get raw data for report structure
        balance_sheet_current = financial_data.get("balance_sheet_current", {})
        balance_sheet_prior = financial_data.get("balance_sheet_prior", {})
        profit_loss = financial_data.get("profit_loss", {})
        
        # Use extracted data for balance sheet
        extracted = financial_data.get("extracted")
        if extracted:
            bs_data = extracted.get("balance_sheet", {})
            cash_current = bs_data.get("cash")
        else:
            if account_type_map and balance_sheet_current:
                bs_data = Extractors.extract_balance_sheet(balance_sheet_current, account_type_map)
                cash_current = bs_data.get("cash")
            else:
                cash_current = None
        
        # Get P&L from monthly data (rolling 3-month sum)
        pnl_aggregated = DataSummarizer._aggregate_monthly_pnl(monthly_pnl_data, num_months=3)
        
        # Extract prior period cash
        cash_prior = None
        if balance_sheet_prior and account_type_map:
            prior_bs = Extractors.extract_balance_sheet(balance_sheet_prior, account_type_map)
            cash_prior = prior_bs.get("cash")
        
        # Get receivables/payables
        receivables = financial_data.get("invoices_receivable", {})
        payables = financial_data.get("invoices_payable", {})

        # Get period info from monthly P&L data
        months_with_data = [m for m in (monthly_pnl_data or []) if m.get("has_data")]
        
        return {
            "period": {
                "balance_sheet_asof": str(balance_sheet_date),
                "pnl_months_available": len(months_with_data),
            },
            "cash": {
                "current": float(cash_current) if cash_current is not None else None,
                "prior": float(cash_prior) if cash_prior is not None else None,
                "change": float(cash_current - cash_prior) if cash_current is not None and cash_prior is not None else None,
            },
            "balance_sheet_current": DataSummarizer._extract_report_structure(balance_sheet_current),
            "balance_sheet_prior": DataSummarizer._extract_report_structure(balance_sheet_prior),
            "profit_loss": DataSummarizer._extract_report_structure(profit_loss),
            "profitability": {
                "revenue": pnl_aggregated.get("revenue"),
                "cost_of_sales": pnl_aggregated.get("cost_of_sales"),
                "expenses": pnl_aggregated.get("expenses"),
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
