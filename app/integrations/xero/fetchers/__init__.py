"""
Xero Data Fetchers
Individual fetchers for different Xero data types.

Data Flow:
- AccountsFetcher: Fetches chart of accounts (AccountType mapping)
- BalanceSheetFetcher: Fetches Balance Sheet reports
- InvoicesFetcher: Fetches AR/AP invoices
- ProfitLossFetcher: Fetches P&L reports (monthly for trend analysis)
"""

from app.integrations.xero.fetchers.accounts import AccountsFetcher
from app.integrations.xero.fetchers.balance_sheet import BalanceSheetFetcher
from app.integrations.xero.fetchers.invoices import InvoicesFetcher
from app.integrations.xero.fetchers.profit_loss import ProfitLossFetcher

__all__ = [
    "AccountsFetcher",
    "BalanceSheetFetcher",
    "InvoicesFetcher",
    "ProfitLossFetcher",
]

