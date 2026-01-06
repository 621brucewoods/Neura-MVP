"""
Xero Data Fetcher
Fetches financial data from Xero API using the official SDK.

Primary data source: Standard Balance Sheet & Profit Loss (Deterministic).
"""

import logging
import re
from datetime import datetime, date, timedelta, timezone
from decimal import Decimal
from typing import Any, Optional
from uuid import UUID

from xero_python.exceptions import ApiException

from app.integrations.xero.sdk_client import XeroSDKClient
from app.integrations.xero.cache_service import CacheService
from app.integrations.xero.rate_limiter import XeroRateLimiter
from app.integrations.xero.retry_handler import XeroRetryHandler

logger = logging.getLogger(__name__)


def _to_json_serializable(obj: Any) -> Any:
    """
    Recursively convert any object to JSON-serializable format.
    
    Handles Xero SDK objects, enums, dates, decimals, etc.
    """
    if obj is None:
        return None
    
    # Handle dicts
    if isinstance(obj, dict):
        return {k: _to_json_serializable(v) for k, v in obj.items()}
    
    # Handle lists
    if isinstance(obj, (list, tuple)):
        return [_to_json_serializable(item) for item in obj]
    
    # Handle Xero SDK objects with to_dict method
    if hasattr(obj, "to_dict"):
        return _to_json_serializable(obj.to_dict())
    
    # Handle primitives (already serializable)
    if isinstance(obj, (str, int, float, bool)):
        return obj
    
    # Handle Decimal
    if isinstance(obj, Decimal):
        return float(obj)
    
    # Handle dates/datetimes
    if isinstance(obj, (date, datetime)):
        return obj.isoformat()
    
    # Handle enums
    if hasattr(obj, "value"):
        return _to_json_serializable(obj.value)
    
    # Fallback: convert to string
    return str(obj)


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
    Fetches financial data from Xero using Standard Reports.
    Prioritizes 'standardLayout=true' for deterministic parsing.
    """
    
    def __init__(
        self, 
        sdk_client: XeroSDKClient, 
        cache_service: Optional[CacheService] = None,
        rate_limiter: Optional[XeroRateLimiter] = None,
        retry_handler: Optional[XeroRetryHandler] = None,
    ):
        """
        Initialize data fetcher with SDK client and optional services.
        
        Args:
            sdk_client: Configured XeroSDKClient instance
            cache_service: Optional CacheService for caching data
            rate_limiter: Optional XeroRateLimiter for rate limiting (creates default if None)
            retry_handler: Optional XeroRetryHandler for retry logic (creates default if None)
        """
        self.client = sdk_client
        self.api = sdk_client.accounting_api
        self.tenant_id = sdk_client.tenant_id
        self.cache_service = cache_service
        self.rate_limiter = rate_limiter or XeroRateLimiter()
        self.retry_handler = retry_handler or XeroRetryHandler()
    
    def _parse_currency_value(self, value: Any, default: str = "0.00") -> Decimal:
        """
        Robustly parse currency values from Xero cell values.
        
        Handles:
        - Currency symbols: $, £, €, USD, EUR, GBP, etc.
        - Parentheses for negatives: (500.00) → -500.00
        - Dashes/empty for zeros: -, —, "" → 0.00
        - European format: 1.234,56 (thousands=., decimal=,)
        - US/UK format: 1,234.56 (thousands=,, decimal=.)
        - None values
        
        Args:
            value: Raw cell value (string, number, None)
            default: Default value if parsing fails
            
        Returns:
            Decimal value or default
        """
        if value is None:
            return Decimal(default)
        
        try:
            # Convert to string
            value_str = str(value).strip()
            
            # Handle empty strings, dashes, em-dashes
            if not value_str or value_str in ("-", "—", "–", ""):
                return Decimal(default)
            
            # Remove currency symbols (common ones)
            currency_symbols = ["$", "£", "€", "USD", "EUR", "GBP", "AUD", "NZD", "CAD"]
            for symbol in currency_symbols:
                value_str = value_str.replace(symbol, "").strip()
            
            # Handle parentheses for negatives: (500.00) → -500.00
            if value_str.startswith("(") and value_str.endswith(")"):
                value_str = "-" + value_str[1:-1].strip()
            
            # Detect locale format by checking for European pattern (thousands=., decimal=,)
            # European: 1.234,56 or 1.234,56
            # US/UK: 1,234.56
            has_european_thousands = re.search(r'\d{1,3}(\.\d{3})+,\d{1,2}$', value_str)
            has_us_thousands = re.search(r'\d{1,3}(,\d{3})+\.\d{1,2}$', value_str)
            
            if has_european_thousands:
                # European format: remove thousands separator (.), replace decimal (,) with (.)
                value_str = value_str.replace(".", "").replace(",", ".")
            elif has_us_thousands:
                # US/UK format: remove thousands separator (,)
                value_str = value_str.replace(",", "")
            else:
                # No thousands separator, but might have comma as decimal (European)
                # Check if last comma is decimal separator
                if "," in value_str and "." not in value_str:
                    # Likely European: 1234,56
                    value_str = value_str.replace(",", ".")
                else:
                    # Remove any remaining commas (safety)
                    value_str = value_str.replace(",", "")
            
            # Parse to Decimal
            return Decimal(value_str)
            
        except Exception as e:
            logger.warning(
                "Failed to parse currency value '%s': %s. Using default: %s",
                value,
                e,
                default
            )
            return Decimal(default)
    
    def _parse_decimal(self, value: Any, default: str = "0.00") -> Decimal:
        """
        Legacy method for backward compatibility.
        Delegates to _parse_currency_value.
        """
        return self._parse_currency_value(value, default)
    
    def _get_month_end(self, target_date: date) -> date:
        """Return the last day of the month for the given date."""
        next_month = target_date.replace(day=28) + timedelta(days=4)
        return next_month - timedelta(days=next_month.day)
    
    def _calculate_months_ago(self, target_date: date, months: int) -> date:
        """
        Calculate date that is N months ago from target date.
        
        Handles month-end edge cases (e.g., Jan 31 - 1 month = Feb 28/29).
        
        Args:
            target_date: Reference date
            months: Number of months to go back
            
        Returns:
            Date that is months months before target_date
        """
        # Calculate target year and month
        target_year = target_date.year
        target_month = target_date.month
        target_day = target_date.day
        
        # Subtract months
        result_month = target_month - months
        result_year = target_year
        
        # Handle year rollover
        while result_month <= 0:
            result_month += 12
            result_year -= 1
        
        # Handle month-end edge cases (e.g., Jan 31 - 1 month should be Dec 31, not Dec 31+)
        # Get the last day of the target month
        if result_month == 2:
            # February: check for leap year
            if result_year % 4 == 0 and (result_year % 100 != 0 or result_year % 400 == 0):
                max_day = 29
            else:
                max_day = 28
        elif result_month in [4, 6, 9, 11]:
            max_day = 30
        else:
            max_day = 31
        
        # Use the minimum of target day and max day for the result month
        result_day = min(target_day, max_day)
        
        return date(result_year, result_month, result_day)
    
    def extract_cash_from_balance_sheet(self, balance_sheet: dict[str, Any]) -> Optional[float]:
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
                                    parsed = self._parse_currency_value(value_str, "0.00")
                                    return float(parsed)
                
                # Recursively search nested rows
                nested_rows = row.get("Rows", row.get("rows", []))
                if isinstance(nested_rows, list):
                    result = _search_rows(nested_rows)
                    if result is not None:
                        return result
            
            return None
        
        return _search_rows(rows)
    
    async def fetch_balance_sheet(self, report_date: date) -> dict[str, Any]:
        """
        Fetch Standard Balance Sheet (Liquidity Source of Truth).
        Uses standardLayout=true to ignore user customizations.
        
        Args:
            report_date: Date for the balance sheet snapshot
            
        Returns:
            Serialized balance sheet report data
        """
        try:
            # Get organization_id for rate limiting
            organization_id = self.client.token.organization_id if hasattr(self.client, "token") else None
            
            # Rate limit check
            if organization_id:
                await self.rate_limiter.wait_if_needed(organization_id)
            
            # Execute API call with retry logic
            async def _fetch():
                return self.api.get_report_balance_sheet(
                    xero_tenant_id=self.tenant_id,
                    date=report_date,
                    standard_layout=True  # CRITICAL: Ensures consistent JSON structure
                )
            
            response = await self.retry_handler.execute_with_retry(_fetch)
            
            # Record API call for rate limiting
            if organization_id:
                await self.rate_limiter.record_call(organization_id)
            
            # Commit token updates (SDK may have refreshed)
            await self.client.commit_token_updates()
            
            if not response.reports or len(response.reports) == 0:
                return {}
            
            # Extract first report (Xero returns list of reports)
            report = response.reports[0]
            report_dict = _to_json_serializable(report)
            
            # Format to match expected structure for calculators (keep Xero's original key names)
            return {
                "raw_data": report_dict,  # Full report structure as Xero provides it
                "report_id": report_dict.get("ReportID") or report_dict.get("report_id"),
                "report_name": report_dict.get("ReportName") or report_dict.get("report_name", "Balance Sheet"),
                "report_date": report_dict.get("ReportDate") or report_dict.get("report_date"),
            }
        except ApiException as e:
            logger.error("Xero API Error (Balance Sheet): %s", e)
            raise XeroDataFetchError(f"Failed to fetch Balance Sheet: {e}", status_code=e.status) from e
    
    async def fetch_accounts(self) -> dict[str, str]:
        """
        Fetch all accounts and create AccountID to AccountType mapping.
        
        This mapping is used to identify account types (REVENUE, EXPENSE, COGS)
        regardless of user-defined account names.
        
        Returns:
            Dictionary mapping AccountID to AccountType (e.g., {"uuid": "REVENUE", ...})
        """
        try:
            # Get organization_id for rate limiting
            organization_id = self.client.token.organization_id if hasattr(self.client, "token") else None
            
            # Rate limit check
            if organization_id:
                await self.rate_limiter.wait_if_needed(organization_id)
            
            # Execute API call with retry logic
            async def _fetch():
                return self.api.get_accounts(xero_tenant_id=self.tenant_id)
            
            response = await self.retry_handler.execute_with_retry(_fetch)
            
            # Record API call for rate limiting
            if organization_id:
                await self.rate_limiter.record_call(organization_id)
            
            # Commit token updates (SDK may have refreshed)
            await self.client.commit_token_updates()
            
            # Build AccountID -> AccountType mapping
            account_type_map = {}
            revenue_count = 0
            expense_count = 0
            cogs_count = 0
            
            if hasattr(response, "accounts") and response.accounts:
                for account in response.accounts:
                    account_id = None
                    account_type = None
                    
                    # Extract AccountID (handle both PascalCase and lowercase)
                    if hasattr(account, "account_id"):
                        account_id = str(account.account_id)
                    elif hasattr(account, "AccountID"):
                        account_id = str(account.AccountID)
                    
                    # Extract AccountType (handle both PascalCase and lowercase)
                    if hasattr(account, "type"):
                        account_type_obj = account.type
                        if hasattr(account_type_obj, "value"):
                            account_type = str(account_type_obj.value)
                        else:
                            account_type = str(account_type_obj)
                    elif hasattr(account, "Type"):
                        account_type_obj = account.Type
                        if hasattr(account_type_obj, "value"):
                            account_type = str(account_type_obj.value)
                        else:
                            account_type = str(account_type_obj)
                    
                    if account_id and account_type:
                        account_type_map[account_id] = account_type
                        # Count by type for logging
                        if account_type.upper() == "REVENUE":
                            revenue_count += 1
                        elif account_type.upper() == "EXPENSE":
                            expense_count += 1
                        elif account_type.upper() == "COGS":
                            cogs_count += 1
            
            logger.info(
                "Fetched %s accounts: %s REVENUE, %s EXPENSE, %s COGS (total mapped: %s)",
                len(response.accounts) if hasattr(response, "accounts") and response.accounts else 0,
                revenue_count,
                expense_count,
                cogs_count,
                len(account_type_map)
            )
            return account_type_map
            
        except ApiException as e:
            logger.error("Xero API Error (Accounts): %s", e)
            raise XeroDataFetchError(f"Failed to fetch Accounts: {e}", status_code=e.status) from e
    
    async def fetch_trial_balance(self, report_date: date) -> dict[str, Any]:
        """
        Fetch Trial Balance report for a specific date.
        
        Trial Balance provides a flat list of all account balances with AccountID
        in cell attributes, allowing deterministic extraction by AccountType.
        
        Args:
            report_date: Date for the trial balance snapshot
            
        Returns:
            Serialized trial balance report data
        """
        try:
            # Get organization_id for rate limiting
            organization_id = self.client.token.organization_id if hasattr(self.client, "token") else None
            
            # Rate limit check
            if organization_id:
                await self.rate_limiter.wait_if_needed(organization_id)
            
            # Execute API call with retry logic
            async def _fetch():
                return self.api.get_report_trial_balance(
                    xero_tenant_id=self.tenant_id,
                    date=report_date
                )
            
            response = await self.retry_handler.execute_with_retry(_fetch)
            
            # Record API call for rate limiting
            if organization_id:
                await self.rate_limiter.record_call(organization_id)
            
            # Commit token updates (SDK may have refreshed)
            await self.client.commit_token_updates()
            
            if not response.reports or len(response.reports) == 0:
                return {}
            
            # Extract first report (Xero returns list of reports)
            report = response.reports[0]
            report_dict = _to_json_serializable(report)
            
            # Format to match expected structure
            return {
                "raw_data": report_dict,
                "report_id": report_dict.get("ReportID") or report_dict.get("report_id"),
                "report_name": report_dict.get("ReportName") or report_dict.get("report_name", "Trial Balance"),
                "report_date": report_dict.get("ReportDate") or report_dict.get("report_date"),
            }
        except ApiException as e:
            logger.error("Xero API Error (Trial Balance): %s", e)
            raise XeroDataFetchError(f"Failed to fetch Trial Balance: {e}", status_code=e.status) from e
    
    def extract_pnl_from_trial_balance(
        self,
        trial_balance: dict[str, Any],
        account_type_map: dict[str, str]
    ) -> dict[str, Optional[float]]:
        """
        Extract P&L values from Trial Balance using AccountType mapping.
        
        This method is deterministic - it uses fixed AccountType (REVENUE, EXPENSE, COGS)
        rather than user-defined labels, making it reliable across all organizations.
        
        Args:
            trial_balance: Trial Balance report data from fetch_trial_balance()
            account_type_map: AccountID -> AccountType mapping from fetch_accounts()
            
        Returns:
            Dictionary with extracted values: revenue, cost_of_sales, expenses
            Note: Gross Profit and Net Profit are calculated, not extracted
        """
        if not trial_balance or not trial_balance.get("raw_data"):
            return {
                "revenue": None,
                "cost_of_sales": None,
                "expenses": None,
            }
        
        raw_data = trial_balance.get("raw_data", {})
        if not isinstance(raw_data, dict):
            return {
                "revenue": None,
                "cost_of_sales": None,
                "expenses": None,
            }
        
        # Extract rows from trial balance
        rows = raw_data.get("Rows", raw_data.get("rows", []))
        if not isinstance(rows, list):
            rows = []
        
        # Initialize totals (using list to allow modification in nested function)
        totals = {
            "revenue": Decimal("0.00"),
            "cost_of_sales": Decimal("0.00"),
            "expenses": Decimal("0.00"),
        }
        
        def _process_rows(rows_list: list):
            """Recursively process rows to extract account balances."""
            if not isinstance(rows_list, list):
                return
            
            for row in rows_list:
                if not isinstance(row, dict):
                    continue
                
                row_type = row.get("RowType", row.get("row_type", ""))
                
                # Only process Row types (not Header, Section, SummaryRow)
                if row_type != "Row":
                    # Recursively process nested rows
                    nested_rows = row.get("Rows", row.get("rows", []))
                    if nested_rows:
                        _process_rows(nested_rows)
                    continue
                
                # Extract cells
                cells = row.get("Cells", row.get("cells", []))
                if not isinstance(cells, list) or len(cells) < 2:
                    continue
                
                # First cell contains account info with AccountID in attributes
                first_cell = cells[0]
                if not isinstance(first_cell, dict):
                    continue
                
                # Extract AccountID from attributes
                attributes = first_cell.get("Attributes", first_cell.get("attributes", []))
                account_id = None
                
                if isinstance(attributes, list):
                    for attr in attributes:
                        if isinstance(attr, dict):
                            attr_id = attr.get("id", attr.get("Id", ""))
                            if attr_id == "account":
                                account_id = attr.get("value", attr.get("Value", ""))
                                break
                
                if not account_id:
                    continue
                
                # Look up AccountType
                account_type = account_type_map.get(account_id)
                if not account_type:
                    continue
                
                # Extract value from second cell (balance)
                value_cell = cells[1]
                if not isinstance(value_cell, dict):
                    continue
                
                value_str = value_cell.get("Value", value_cell.get("value", "0"))
                value = self._parse_currency_value(value_str, "0.00")
                
                # Sum by AccountType (case-insensitive matching)
                account_type_upper = account_type.upper()
                if account_type_upper == "REVENUE":
                    totals["revenue"] += value
                    logger.debug("Found REVENUE account %s: %s", account_id, float(value))
                elif account_type_upper == "COGS":
                    totals["cost_of_sales"] += value
                    logger.debug("Found COGS account %s: %s", account_id, float(value))
                elif account_type_upper == "EXPENSE":
                    totals["expenses"] += value
                    logger.debug("Found EXPENSE account %s: %s", account_id, float(value))
        
        _process_rows(rows)
        
        total_revenue = totals["revenue"]
        total_cost_of_sales = totals["cost_of_sales"]
        total_expenses = totals["expenses"]
        
        logger.info(
            "Extracted from Trial Balance: Revenue=%s, Cost of Sales=%s, Expenses=%s (from %s accounts mapped)",
            float(total_revenue),
            float(total_cost_of_sales),
            float(total_expenses),
            len(account_type_map)
        )
        
        # Return values (0.0 is valid, only return None if we couldn't process)
        # If we processed rows but got 0, that's a valid result
        return {
            "revenue": float(total_revenue),
            "cost_of_sales": float(total_cost_of_sales),
            "expenses": float(total_expenses),
        }
    
    async def fetch_profit_loss(self, start_date: date, end_date: date) -> dict[str, Any]:
        """
        Fetch Profit & Loss (Performance Source of Truth).
        Uses standardLayout=true for deterministic parsing.
        
        Args:
            start_date: Start date for P&L period
            end_date: End date for P&L period
            
        Returns:
            Serialized P&L report data
        """
        try:
            # Get organization_id for rate limiting
            organization_id = self.client.token.organization_id if hasattr(self.client, "token") else None
            
            # Rate limit check
            if organization_id:
                await self.rate_limiter.wait_if_needed(organization_id)
            
            # Execute API call with retry logic
            async def _fetch():
                return self.api.get_report_profit_and_loss(
                    xero_tenant_id=self.tenant_id,
                    from_date=start_date,
                    to_date=end_date,
                    standard_layout=True  # CRITICAL: Ensures consistent JSON structure
                )
            
            response = await self.retry_handler.execute_with_retry(_fetch)
            
            # Record API call for rate limiting
            if organization_id:
                await self.rate_limiter.record_call(organization_id)
            
            # Commit token updates (SDK may have refreshed)
            await self.client.commit_token_updates()
            
            if not response.reports or len(response.reports) == 0:
                return {}
            
            # Extract first report (Xero returns list of reports)
            report = response.reports[0]
            report_dict = _to_json_serializable(report)
            
            # Format to match expected structure for calculators (keep Xero's original key names)
            return {
                "raw_data": report_dict,  # Full report structure as Xero provides it
                "report_id": report_dict.get("ReportID") or report_dict.get("report_id"),
                "report_name": report_dict.get("ReportName") or report_dict.get("report_name", "Profit and Loss"),
                "report_date": report_dict.get("ReportDate") or report_dict.get("report_date"),
            }
        except ApiException as e:
            logger.error("Xero API Error (P&L): %s", e)
            raise XeroDataFetchError(f"Failed to fetch P&L: {e}", status_code=e.status) from e
    
    async def _fetch_invoices(self, invoice_type: str) -> dict[str, Any]:
        """
        Internal method to fetch invoices (receivables or payables).
        
        Args:
            invoice_type: "ACCREC" for receivables, "ACCPAY" for payables
        
        Returns:
            Invoice summary with metrics, including truncated flag
        """
        try:
            all_invoices = []
            page = 1
            page_size = 1000  # Use maximum page size supported by Xero
            truncated = False
            
            # Get organization_id for rate limiting
            organization_id = self.client.token.organization_id if hasattr(self.client, "token") else None
            
            while True:
                # Rate limit check before each page
                if organization_id:
                    await self.rate_limiter.wait_if_needed(organization_id)
                
                # Execute API call with retry logic
                async def _fetch_page():
                    try:
                        # Try with page_size parameter (if SDK supports it)
                        return self.api.get_invoices(
                            xero_tenant_id=self.tenant_id,
                            where=f'Type=="{invoice_type}" AND Status=="AUTHORISED"',
                            page=page,
                            # Note: SDK may not support page_size parameter, will use default if not
                        )
                    except TypeError:
                        # SDK doesn't support page_size, use default (100)
                        return self.api.get_invoices(
                            xero_tenant_id=self.tenant_id,
                            where=f'Type=="{invoice_type}" AND Status=="AUTHORISED"',
                            page=page,
                        )
                
                response = await self.retry_handler.execute_with_retry(_fetch_page)
                
                # Record API call for rate limiting
                if organization_id:
                    await self.rate_limiter.record_call(organization_id)
                
                # Commit token updates after each API call
                await self.client.commit_token_updates()
                
                # Determine page size from response
                page_invoices = response.invoices if hasattr(response, "invoices") else []
                if page == 1:
                    # Use actual page size from first response
                    page_size = len(page_invoices) if page_invoices else 100
                
                page_invoices = response.invoices if hasattr(response, "invoices") else []
                
                if not page_invoices:
                    # No more invoices, pagination complete
                    break
                
                all_invoices.extend(page_invoices)
                
                # Check if we've reached the end (fewer invoices than page size)
                if len(page_invoices) < page_size:
                    # This is the last page
                    break
                
                page += 1
                
                # Safety limit: prevent infinite loops (100 pages = 100,000 invoices max)
                # This is a very high limit, but prevents runaway pagination
                if page > 100:
                    logger.warning(
                        "Reached safety limit for invoice pagination (100 pages). "
                        "Organization may have more than 100,000 invoices."
                    )
                    truncated = True
                    break
            
            total = Decimal("0.00")
            overdue_amount = Decimal("0.00")
            overdue_count = 0
            overdue_days_sum = 0
            today = datetime.now(timezone.utc).date()
            
            # Track currencies for multi-currency detection
            currencies_found = set()
            base_currency = None
            
            for invoice in all_invoices:
                # Extract currency code
                currency_code = None
                if hasattr(invoice, "currency_code") and invoice.currency_code:
                    currency_code = str(invoice.currency_code)
                elif hasattr(invoice, "currency") and invoice.currency:
                    if hasattr(invoice.currency, "code"):
                        currency_code = str(invoice.currency.code)
                    else:
                        currency_code = str(invoice.currency)
                
                if currency_code:
                    currencies_found.add(currency_code)
                    # Use first currency as base (typically organization's base currency)
                    if base_currency is None:
                        base_currency = currency_code
                
                amount_due = self._parse_decimal(
                    invoice.amount_due if hasattr(invoice, "amount_due") else 0
                )
                
                # Only sum amounts in base currency (or if no currency info, assume base)
                if currency_code is None or currency_code == base_currency:
                    total += amount_due
                else:
                    # Different currency - log warning but don't sum (would be incorrect)
                    logger.warning(
                        "Invoice %s has currency %s (base: %s), excluding from total to avoid incorrect aggregation",
                        getattr(invoice, "invoice_number", "unknown"),
                        currency_code,
                        base_currency
                    )
                
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
                
                # Only count overdue in base currency
                if due_date and due_date < today and amount_due > 0:
                    if currency_code is None or currency_code == base_currency:
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
                
                # Extract currency code for invoice
                invoice_currency = None
                if hasattr(invoice, "currency_code") and invoice.currency_code:
                    invoice_currency = str(invoice.currency_code)
                elif hasattr(invoice, "currency") and invoice.currency:
                    if hasattr(invoice.currency, "code"):
                        invoice_currency = str(invoice.currency.code)
                    else:
                        invoice_currency = str(invoice.currency)
                
                invoices.append({
                    "id": str(invoice.invoice_id) if hasattr(invoice, "invoice_id") else None,
                    "number": str(invoice.invoice_number) if hasattr(invoice, "invoice_number") else None,
                    "contact": str(invoice.contact.name) if hasattr(invoice, "contact") and invoice.contact and hasattr(invoice.contact, "name") else None,
                    "amount_due": float(invoice.amount_due) if hasattr(invoice, "amount_due") else 0,
                    "total": float(invoice.total) if hasattr(invoice, "total") else 0,
                    "due_date": str(invoice.due_date) if hasattr(invoice, "due_date") else None,
                    "status": invoice_status,
                    "currency_code": invoice_currency,
                })
            
            # Check for multi-currency issues
            multi_currency_detected = len(currencies_found) > 1
            if multi_currency_detected:
                logger.warning(
                    "Multi-currency invoices detected (%s). Only %s invoices included in totals. "
                    "Other currencies excluded to prevent incorrect aggregation.",
                    ", ".join(currencies_found),
                    base_currency or "unknown"
                )
            
            return {
                "total": float(total),
                "count": len(all_invoices),
                "overdue_amount": float(overdue_amount),
                "overdue_count": overdue_count,
                "avg_days_overdue": round(avg_days_overdue, 1),
                "invoices": invoices,
                "truncated": truncated,
                "total_fetched": len(all_invoices),
                "base_currency": base_currency,
                "multi_currency_detected": multi_currency_detected,
                "currencies_found": list(currencies_found) if currencies_found else None,
            }
        except ApiException as e:
            logger.error("Xero API Error (Invoices %s): %s", invoice_type, e)
            raise XeroDataFetchError(f"Failed to fetch {invoice_type} invoices: {e}", status_code=e.status) from e
    
    async def fetch_receivables(self) -> dict[str, Any]:
        """
        Fetch Accounts Receivable invoices.
        
        Used for leading indicators (receivables timing, overdue analysis).
        
        Returns:
            Invoice summary with metrics
        """
        return await self._fetch_invoices(invoice_type="ACCREC")
    
    async def fetch_payables(self) -> dict[str, Any]:
        """
        Fetch Accounts Payable invoices (bills).
        
        Used for leading indicators (payables timing, cash pressure signals).
        
        Returns:
            Invoice summary with metrics
        """
        return await self._fetch_invoices(invoice_type="ACCPAY")
    
    async def fetch_all_data(
        self, 
        organization_id: Optional[UUID] = None,
        months: int = 6, 
        force_refresh: bool = False
    ) -> dict[str, Any]:
        """
        Orchestrates fetching of all required financial data.
        
        Strategy:
        1. Fetch Balance Sheet for Today (Current Cash)
        2. Fetch Balance Sheet for T-30 Days (For Burn Rate Delta)
        3. Fetch P&L for specified months period (Profitability)
        4. Fetch Receivables/Payables (Leading Indicators)
        
        Args:
            organization_id: Organization UUID (required for caching, reserved for future use)
            months: Number of historical months to fetch for P&L (1-12, default: 6)
            force_refresh: If True, bypass cache and fetch fresh data (reserved for future use)
        
        Returns:
            Complete financial data structure
        """
        try:
            errors = []
            today = datetime.now(timezone.utc).date()
            
            # Note: organization_id and force_refresh are reserved for future caching implementation
            _ = organization_id, force_refresh
            
            # Use simple 30 day lookback for "Previous Month" comparison
            prior_date = today - timedelta(days=30)
            
            # 1. Fetch Balance Sheets (Current & Prior for Delta Calc)
            balance_sheet_current = None
            balance_sheet_prior = None
            
            try:
                balance_sheet_current = await self.fetch_balance_sheet(today)
            except XeroDataFetchError as e:
                errors.append(f"Balance Sheet (current): {e.message}")
                balance_sheet_current = {}
            
            try:
                balance_sheet_prior = await self.fetch_balance_sheet(prior_date)
            except XeroDataFetchError as e:
                errors.append(f"Balance Sheet (prior): {e.message}")
                balance_sheet_prior = {}
            
            # 2. Fetch P&L for specified months period
            profit_loss = None
            try:
                # Calculate date range: months months back from today
                # Example: If months=3 and today is Jan 6, 2026, fetch from Oct 6, 2025 to Jan 6, 2026
                start_date = self._calculate_months_ago(today, months)
                
                profit_loss = await self.fetch_profit_loss(
                    start_date=start_date,
                    end_date=today
                )
                logger.info(
                    "Fetched P&L for period: %s to %s (%s months)",
                    start_date,
                    today,
                    months
                )
            except XeroDataFetchError as e:
                errors.append(f"Profit & Loss: {e.message}")
                profit_loss = {}
            
            # 3. Fetch Accounts (for AccountType mapping) and Trial Balance (deterministic P&L via AccountType)
            accounts_map = {}
            trial_balance = {}
            trial_balance_pnl = {}
            try:
                accounts_map = await self.fetch_accounts()
                logger.info("Fetched %s accounts for AccountType mapping", len(accounts_map))
            except XeroDataFetchError as e:
                errors.append(f"Accounts: {e.message}")
                logger.warning("Failed to fetch accounts: %s", e.message)
                accounts_map = {}
            
            try:
                # Calculate P&L period start date
                start_date = self._calculate_months_ago(today, months)
                
                # Fetch Trial Balance for end date (period end)
                # Note: Trial Balance is a snapshot, so we get balances at end_date
                # For period-based P&L, we'd ideally need start and end, but for MVP
                # we'll use end_date snapshot which shows cumulative balances
                trial_balance = await self.fetch_trial_balance(today)
                logger.info("Fetched Trial Balance for date: %s", today)
                
                if accounts_map:
                    trial_balance_pnl = self.extract_pnl_from_trial_balance(trial_balance, accounts_map)
                    logger.info(
                        "Trial Balance P&L extraction result: revenue=%s, cost_of_sales=%s, expenses=%s",
                        trial_balance_pnl.get("revenue"),
                        trial_balance_pnl.get("cost_of_sales"),
                        trial_balance_pnl.get("expenses")
                    )
                else:
                    logger.warning("Cannot extract Trial Balance P&L: account_type_map is empty")
                    trial_balance_pnl = {}
            except XeroDataFetchError as e:
                errors.append(f"Trial Balance: {e.message}")
                logger.warning("Failed to fetch Trial Balance: %s", e.message)
                trial_balance = {}
                trial_balance_pnl = {}
            
            # 3. Fetch Invoices (Receivables/Payables)
            receivables = None
            payables = None
            
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
                    "invoices": [],
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
                    "invoices": [],
                }
            
            # Final commit to ensure all token updates are saved
            await self.client.commit_token_updates()
            
            if errors:
                logger.warning("Some data fetch operations failed: %s", ", ".join(errors))
            
            # 4. Compile Data Package
            return {
                "balance_sheet_current": balance_sheet_current,
                "balance_sheet_prior": balance_sheet_prior,
                "profit_loss": profit_loss,
                "trial_balance": trial_balance,
                "account_type_map": accounts_map,
                "trial_balance_pnl": trial_balance_pnl,
                "invoices_receivable": receivables,
                "invoices_payable": payables,
                "fetched_at": datetime.now(timezone.utc).isoformat(),
                "errors": errors if errors else None,
            }
        except XeroDataFetchError:
            # Re-raise our own errors as-is
            raise
        except Exception as e:
            logger.error("Failed to fetch all data: %s", e)
            raise XeroDataFetchError(f"Failed to fetch all data: {str(e)}") from e
