"""
Xero Data Fetcher
Fetches financial data from Xero API using the official SDK.
"""

import logging
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any, Optional

from xero_python.exceptions import ApiException

from app.integrations.xero.sdk_client import XeroSDKClient

logger = logging.getLogger(__name__)


class XeroDataFetchError(Exception):
    """Exception for data fetching errors."""
    
    def __init__(
        self, 
        message: str, 
        status_code: Optional[int] = None, 
        endpoint: Optional[str] = None
    ):
        self.message = message
        self.status_code = status_code
        self.endpoint = endpoint
        super().__init__(self.message)


class XeroDataFetcher:
    """
    Fetches financial data from Xero using the official SDK.
    
    Provides clean, normalized data structures for cash runway calculations:
    - Bank account balances (from Bank Summary Report + Accounts API)
    - Bank transactions (cash flow history)
    - Accounts Receivable invoices
    - Accounts Payable invoices
    - Profit & Loss (optional, graceful failure)
    """
    
    def __init__(self, sdk_client: XeroSDKClient):
        """
        Initialize data fetcher with SDK client.
        
        Args:
            sdk_client: Configured XeroSDKClient instance
        """
        self.client = sdk_client
        self.api = sdk_client.accounting_api
        self.tenant_id = sdk_client.tenant_id
    
    def _parse_decimal(self, value: Any, default: str = "0.00") -> Decimal:
        """Safely parse a value to Decimal."""
        if value is None:
            return Decimal(default)
        try:
            return Decimal(str(value).replace(",", ""))
        except Exception:
            return Decimal(default)
    
    async def fetch_bank_accounts(self) -> dict[str, Any]:
        """
        Fetch bank account balances.
        
        Uses Accounts API for metadata and Bank Summary Report for actual balances.
        
        Returns:
            {
                "accounts": [
                    {"id": "...", "name": "...", "balance": 0.0, "currency": "..."}
                ],
                "total_balance": 0.0,
                "currency": "NZD"
            }
        """
        try:
            accounts_response = self.api.get_accounts(
                xero_tenant_id=self.tenant_id,
                where='Status=="ACTIVE" AND Type=="BANK"',
                order="Name ASC",
            )
            
            accounts_list = accounts_response.accounts if hasattr(accounts_response, "accounts") else []
            
            if not accounts_list:
                logger.warning("No active bank accounts found")
                return {"accounts": [], "total_balance": 0.0, "currency": "NZD"}
            
            report_response = self.api.get_report_bank_summary(
                xero_tenant_id=self.tenant_id,
            )
            
            report = report_response.reports[0] if hasattr(report_response, "reports") and report_response.reports else None
            
            balances_by_name = {}
            if report and hasattr(report, "rows"):
                for row in report.rows:
                    row_type_str = str(row.row_type) if hasattr(row, "row_type") else ""
                    
                    if "SECTION" in row_type_str.upper() and hasattr(row, "rows") and row.rows:
                        for nested_row in row.rows:
                            nested_row_type_str = str(nested_row.row_type) if hasattr(nested_row, "row_type") else ""
                            
                            if "ROW" in nested_row_type_str.upper() and "SUMMARY" not in nested_row_type_str.upper():
                                if hasattr(nested_row, "cells") and nested_row.cells and len(nested_row.cells) >= 5:
                                    account_name = nested_row.cells[0].value if hasattr(nested_row.cells[0], "value") else str(nested_row.cells[0])
                                    balance_str = nested_row.cells[4].value if hasattr(nested_row.cells[4], "value") else str(nested_row.cells[4])
                                    
                                    balance = self._parse_decimal(balance_str)
                                    balances_by_name[account_name] = balance
            
            accounts = []
            total_balance = Decimal("0.00")
            currency = "NZD"
            
            for account in accounts_list:
                account_name = str(account.name) if hasattr(account, "name") else "Unknown"
                balance = balances_by_name.get(account_name, Decimal("0.00"))
                
                account_currency = currency
                if hasattr(account, "currency_code") and account.currency_code:
                    currency_code_obj = account.currency_code
                    if hasattr(currency_code_obj, "value"):
                        account_currency = currency_code_obj.value
                    elif hasattr(currency_code_obj, "name"):
                        account_currency = currency_code_obj.name
                    else:
                        account_currency = str(currency_code_obj).split(".")[-1] if "." in str(currency_code_obj) else str(currency_code_obj)
                
                if currency == "NZD" and account_currency:
                    currency = account_currency
                
                account_id = str(account.account_id) if hasattr(account, "account_id") else None
                
                accounts.append({
                    "id": account_id,
                    "name": account_name,
                    "balance": float(balance),
                    "currency": account_currency or currency,
                })
                
                total_balance += balance
            
            return {
                "accounts": accounts,
                "total_balance": float(total_balance),
                "currency": currency,
            }
            
        except ApiException as e:
            logger.error("SDK error fetching bank accounts: %s", e)
            raise XeroDataFetchError(
                f"Failed to fetch bank accounts: {str(e)}",
                status_code=e.status if hasattr(e, "status") else None,
                endpoint="BankAccounts"
            ) from e
        except Exception as e:
            logger.error("Error fetching bank accounts: %s", e, exc_info=True)
            raise XeroDataFetchError(
                f"Failed to fetch bank accounts: {str(e)}",
                endpoint="BankAccounts"
            ) from e
    
    async def fetch_bank_transactions(self, months: int = 3) -> dict[str, Any]:
        """
        Fetch bank transactions for the last N months.
        
        Args:
            months: Number of months of history
            
        Returns:
            {
                "transactions": [...],
                "monthly_summary": [
                    {"month": "YYYY-MM", "inflow": 0.0, "outflow": 0.0, "net": 0.0, "count": 0}
                ],
                "total_transactions": 0
            }
        """
        try:
            end_date = datetime.now(timezone.utc)
            start_date = end_date - timedelta(days=months * 31)
            
            all_transactions = []
            page = 1
            
            while True:
                where_clause = f'Date >= DateTime({start_date.year},{start_date.month},{start_date.day}) AND Status == "AUTHORISED"'
                
                response = self.api.get_bank_transactions(
                    xero_tenant_id=self.tenant_id,
                    where=where_clause,
                    order="Date DESC",
                    page=page,
                )
                
                page_transactions = response.bank_transactions if hasattr(response, "bank_transactions") else []
                
                if not page_transactions:
                    break
                
                all_transactions.extend(page_transactions)
                
                if len(page_transactions) < 100:
                    break
                
                page += 1
                if page > 10:
                    logger.warning("Reached page limit for bank transactions")
                    break
            
            monthly_data: dict[str, dict] = {}
            
            for transaction in all_transactions:
                transaction_date = None
                if hasattr(transaction, "date") and transaction.date:
                    transaction_date = transaction.date
                    if isinstance(transaction_date, datetime):
                        pass
                    elif hasattr(transaction_date, "date"):
                        transaction_date = datetime.combine(transaction_date.date(), datetime.min.time()).replace(tzinfo=timezone.utc)
                    else:
                        try:
                            transaction_date = datetime.fromisoformat(str(transaction_date).replace("Z", "+00:00"))
                        except Exception:
                            continue
                
                if not transaction_date:
                    continue
                
                month_key = transaction_date.strftime("%Y-%m")
                
                if month_key not in monthly_data:
                    monthly_data[month_key] = {
                        "month": month_key,
                        "inflow": Decimal("0.00"),
                        "outflow": Decimal("0.00"),
                        "count": 0,
                    }
                
                amount = self._parse_decimal(transaction.total if hasattr(transaction, "total") else 0)
                transaction_type_str = ""
                if hasattr(transaction, "type") and transaction.type:
                    type_obj = transaction.type
                    if hasattr(type_obj, "value"):
                        transaction_type_str = type_obj.value
                    elif hasattr(type_obj, "name"):
                        transaction_type_str = type_obj.name
                    else:
                        transaction_type_str = str(type_obj).split(".")[-1] if "." in str(type_obj) else str(type_obj)
                
                if transaction_type_str == "RECEIVE":
                    monthly_data[month_key]["inflow"] += amount
                elif transaction_type_str == "SPEND":
                    monthly_data[month_key]["outflow"] += amount
                
                monthly_data[month_key]["count"] += 1
            
            monthly_summary = []
            for month_data in sorted(monthly_data.values(), key=lambda x: x["month"]):
                monthly_summary.append({
                    "month": month_data["month"],
                    "inflow": float(month_data["inflow"]),
                    "outflow": float(month_data["outflow"]),
                    "net": float(month_data["inflow"] - month_data["outflow"]),
                    "count": month_data["count"],
                })
            
            transactions = []
            for transaction in all_transactions[:50]:
                transaction_type = None
                if hasattr(transaction, "type") and transaction.type:
                    type_obj = transaction.type
                    if hasattr(type_obj, "value"):
                        transaction_type = type_obj.value
                    elif hasattr(type_obj, "name"):
                        transaction_type = type_obj.name
                    else:
                        transaction_type = str(type_obj).split(".")[-1] if "." in str(type_obj) else str(type_obj)
                
                transaction_status = None
                if hasattr(transaction, "status") and transaction.status:
                    status_obj = transaction.status
                    if hasattr(status_obj, "value"):
                        transaction_status = status_obj.value
                    elif hasattr(status_obj, "name"):
                        transaction_status = status_obj.name
                    else:
                        transaction_status = str(status_obj).split(".")[-1] if "." in str(status_obj) else str(status_obj)
                
                reference = None
                if hasattr(transaction, "reference") and transaction.reference:
                    ref_str = str(transaction.reference).strip()
                    reference = ref_str if ref_str and ref_str.lower() != "none" else None
                
                transactions.append({
                    "id": str(transaction.bank_transaction_id) if hasattr(transaction, "bank_transaction_id") else None,
                    "date": str(transaction.date) if hasattr(transaction, "date") else None,
                    "type": transaction_type,
                    "total": float(transaction.total) if hasattr(transaction, "total") else 0,
                    "status": transaction_status,
                    "reference": reference,
                })
            
            return {
                "transactions": transactions,
                "monthly_summary": monthly_summary,
                "total_transactions": len(all_transactions),
            }
            
        except ApiException as e:
            logger.error("SDK error fetching bank transactions: %s", e)
            raise XeroDataFetchError(
                f"Failed to fetch bank transactions: {str(e)}",
                status_code=e.status if hasattr(e, "status") else None,
                endpoint="BankTransactions"
            ) from e
        except Exception as e:
            logger.error("Error fetching bank transactions: %s", e, exc_info=True)
            raise XeroDataFetchError(
                f"Failed to fetch bank transactions: {str(e)}",
                endpoint="BankTransactions"
            ) from e
    
    async def fetch_receivables(self) -> dict[str, Any]:
        """
        Fetch Accounts Receivable invoices.
        
        Returns:
            {
                "total": 0.0,
                "count": 0,
                "overdue_amount": 0.0,
                "overdue_count": 0,
                "avg_days_overdue": 0.0,
                "invoices": [...]
            }
        """
        return await self._fetch_invoices(invoice_type="ACCREC")
    
    async def fetch_payables(self) -> dict[str, Any]:
        """
        Fetch Accounts Payable invoices (bills).
        
        Returns:
            {
                "total": 0.0,
                "count": 0,
                "overdue_amount": 0.0,
                "overdue_count": 0,
                "avg_days_overdue": 0.0,
                "invoices": [...]
            }
        """
        return await self._fetch_invoices(invoice_type="ACCPAY")
    
    async def _fetch_invoices(self, invoice_type: str) -> dict[str, Any]:
        """
        Internal method to fetch invoices (receivables or payables).
        
        Args:
            invoice_type: "ACCREC" for receivables, "ACCPAY" for payables
            
        Returns:
            Invoice summary with metrics
        """
        try:
            all_invoices = []
            page = 1
            
            while True:
                # Fetch via SDK
                response = self.api.get_invoices(
                    xero_tenant_id=self.tenant_id,
                    where=f'Type=="{invoice_type}" AND Status=="AUTHORISED"',
                    page=page,
                )
                
                page_invoices = response.invoices if hasattr(response, "invoices") else []
                
                if not page_invoices:
                    break
                
                all_invoices.extend(page_invoices)
                
                if len(page_invoices) < 100:
                    break
                
                page += 1
                if page > 10:
                    logger.warning("Reached page limit for invoices")
                    break
            
            total = Decimal("0.00")
            overdue_amount = Decimal("0.00")
            overdue_count = 0
            overdue_days_sum = 0
            today = datetime.now(timezone.utc).date()
            
            for invoice in all_invoices:
                amount_due = self._parse_decimal(
                    invoice.amount_due if hasattr(invoice, "amount_due") else 0
                )
                total += amount_due
                
                due_date = None
                if hasattr(invoice, "due_date") and invoice.due_date:
                    due_date_obj = invoice.due_date
                    if isinstance(due_date_obj, datetime):
                        due_date = due_date_obj.date()
                    elif hasattr(due_date_obj, "date"):
                        due_date = due_date_obj.date()
                    else:
                        try:
                            due_date = datetime.fromisoformat(str(due_date_obj).replace("Z", "+00:00")).date()
                        except Exception:
                            pass
                
                if due_date and due_date < today and amount_due > 0:
                    overdue_amount += amount_due
                    overdue_count += 1
                    days_overdue = (today - due_date).days
                    overdue_days_sum += days_overdue
            
            avg_days_overdue = overdue_days_sum / overdue_count if overdue_count > 0 else 0.0
            
            invoices = []
            for invoice in all_invoices[:50]:
                invoice_status = None
                if hasattr(invoice, "status") and invoice.status:
                    status_obj = invoice.status
                    if hasattr(status_obj, "value"):
                        invoice_status = status_obj.value
                    elif hasattr(status_obj, "name"):
                        invoice_status = status_obj.name
                    else:
                        invoice_status = str(status_obj).split(".")[-1] if "." in str(status_obj) else str(status_obj)
                
                invoices.append({
                    "id": str(invoice.invoice_id) if hasattr(invoice, "invoice_id") else None,
                    "number": str(invoice.invoice_number) if hasattr(invoice, "invoice_number") else None,
                    "contact": str(invoice.contact.name) if hasattr(invoice, "contact") and invoice.contact and hasattr(invoice.contact, "name") else None,
                    "amount_due": float(invoice.amount_due) if hasattr(invoice, "amount_due") else 0,
                    "total": float(invoice.total) if hasattr(invoice, "total") else 0,
                    "due_date": str(invoice.due_date) if hasattr(invoice, "due_date") else None,
                    "status": invoice_status,
                })
            
            return {
                "total": float(total),
                "count": len(all_invoices),
                "overdue_amount": float(overdue_amount),
                "overdue_count": overdue_count,
                "avg_days_overdue": round(avg_days_overdue, 1),
                "invoices": invoices,
            }
            
        except ApiException as e:
            logger.error("SDK error fetching invoices (%s): %s", invoice_type, e)
            raise XeroDataFetchError(
                f"Failed to fetch {invoice_type} invoices: {str(e)}",
                status_code=e.status if hasattr(e, "status") else None,
                endpoint="Invoices"
            ) from e
        except Exception as e:
            logger.error("Error fetching invoices (%s): %s", invoice_type, e, exc_info=True)
            raise XeroDataFetchError(
                f"Failed to fetch {invoice_type} invoices: {str(e)}",
                endpoint="Invoices"
            ) from e
    
    async def fetch_profit_loss(self, months: int = 3) -> dict[str, Any]:
        """
        Fetch Profit & Loss report.
        
        Args:
            months: Number of months of history
            
        Returns:
            P&L structure with periods and summary
        """
        return {
            "periods": [],
            "summary": {"total_revenue": 0.0, "total_expenses": 0.0, "net_income": 0.0},
        }
    
    async def fetch_all_data(self, months: int = 3) -> dict[str, Any]:
        """
        Fetch all financial data required for cash runway calculations.
        
        Args:
            months: Number of months of historical data
            
        Returns:
            Complete financial data structure
        """
        try:
            bank_accounts = None
            bank_transactions = None
            receivables = None
            payables = None
            profit_loss = None
            errors = []
            
            try:
                bank_accounts = await self.fetch_bank_accounts()
            except XeroDataFetchError as e:
                errors.append(f"Bank accounts: {e.message}")
                bank_accounts = {"accounts": [], "total_balance": 0.0, "currency": "NZD"}
            
            try:
                bank_transactions = await self.fetch_bank_transactions(months)
            except XeroDataFetchError as e:
                errors.append(f"Bank transactions: {e.message}")
                bank_transactions = {"transactions": [], "monthly_summary": [], "total_transactions": 0}
            
            try:
                receivables = await self.fetch_receivables()
            except XeroDataFetchError as e:
                errors.append(f"Receivables: {e.message}")
                receivables = {
                    "total": 0.0, 
                    "count": 0, 
                    "overdue_amount": 0.0, 
                    "overdue_count": 0, 
                    "avg_days_overdue": 0.0, 
                    "invoices": []
                }
            
            try:
                payables = await self.fetch_payables()
            except XeroDataFetchError as e:
                errors.append(f"Payables: {e.message}")
                payables = {
                    "total": 0.0, 
                    "count": 0, 
                    "overdue_amount": 0.0, 
                    "overdue_count": 0, 
                    "avg_days_overdue": 0.0, 
                    "invoices": []
                }
            
            profit_loss = await self.fetch_profit_loss(months)
            
            if errors:
                logger.warning("Some data fetch operations failed: %s", ", ".join(errors))
            
            # Commit any token updates from SDK refresh
            await self.client.commit_token_updates()
            
            return {
                "bank_accounts": bank_accounts,
                "bank_transactions": bank_transactions,
                "invoices_receivable": receivables,
                "invoices_payable": payables,
                "profit_loss": profit_loss,
                "fetched_at": datetime.now(timezone.utc).isoformat(),
                "errors": errors if errors else None,
            }
            
        except Exception as e:
            logger.error("Error fetching all data: %s", e, exc_info=True)
            raise XeroDataFetchError(f"Failed to fetch financial data: {str(e)}") from e
