"""
Xero Data Fetcher
Fetches financial data from Xero API using the official SDK.

Primary data source: Executive Summary Report (accurate cash flow metrics).
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
    Fetches financial data from Xero using the official SDK.
    
    Primary focus: Executive Summary Report for accurate cash flow metrics.
    Provides clean, normalized data structures for cash runway calculations.
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
    
    def _get_month_end_date(self, year: int, month: int) -> date:
        """Get the last day of a given month."""
        if month == 12:
            return date(year, 12, 31)
        else:
            next_month = date(year, month + 1, 1)
            return next_month - timedelta(days=1)
    
    def _find_report_section(
        self, 
        rows: list, 
        possible_titles: list[str],
        row_type: Optional[str] = None
    ) -> Optional[Any]:
        """
        Find a report section by semantic matching instead of exact string match.
        
        Handles:
        - Multiple language variations (Cash, Trésorerie, Efectivo, etc.)
        - Custom report layouts (user-renamed sections)
        - RowType filtering (Section, SummaryRow, etc.)
        
        Args:
            rows: List of report rows to search
            possible_titles: List of possible section titles (case-insensitive)
            row_type: Optional RowType filter (e.g., "Section")
            
        Returns:
            Matched row object or None
        """
        if not rows:
            return None
        
        possible_titles_lower = [title.lower() for title in possible_titles]
        
        for row in rows:
            if not hasattr(row, "rows") or not row.rows:
                continue
            
            # Check RowType if specified
            if row_type:
                row_type_attr = getattr(row, "RowType", None)
                if row_type_attr:
                    row_type_value = (
                        row_type_attr.value 
                        if hasattr(row_type_attr, "value") 
                        else str(row_type_attr)
                    )
                    if row_type_value != row_type:
                        continue
            
            # Get title
            row_title = ""
            if hasattr(row, "title"):
                row_title = str(row.title) if row.title else ""
            
            row_title_lower = row_title.lower()
            
            # Check if title matches any possible variation
            for possible_title in possible_titles_lower:
                if possible_title in row_title_lower or row_title_lower in possible_title:
                    return row
            
            # Also check Attributes for AccountID (semantic matching)
            if hasattr(row, "Attributes") and row.Attributes:
                for attr in row.Attributes:
                    if hasattr(attr, "Value") and attr.Value:
                        attr_value_lower = str(attr.Value).lower()
                        for possible_title in possible_titles_lower:
                            if possible_title in attr_value_lower:
                                return row
        
        return None
    
    def _extract_cash_metrics(self, cash_section: Any) -> dict[str, Decimal]:
        """
        Extract cash metrics from Cash section using flexible label matching.
        
        Handles variations:
        - "closing bank balance", "closing balance", "bank balance"
        - "cash spent", "total cash spent", "cash out"
        - "cash received", "total cash received", "cash in"
        
        Args:
            cash_section: Cash section row object
            
        Returns:
            Dict with cash_position, cash_spent, cash_received
        """
        metrics = {
            "cash_position": Decimal("0.00"),
            "cash_spent": Decimal("0.00"),
            "cash_received": Decimal("0.00"),
        }
        
        if not cash_section or not hasattr(cash_section, "rows") or not cash_section.rows:
            return metrics
        
        for nested_row in cash_section.rows:
            if not hasattr(nested_row, "cells") or not nested_row.cells or len(nested_row.cells) < 2:
                continue
            
            # Safely get label and value
            label = ""
            value_str = None
            
            if hasattr(nested_row.cells[0], "value") and nested_row.cells[0].value is not None:
                label = str(nested_row.cells[0].value)
            else:
                label = str(nested_row.cells[0]) if nested_row.cells[0] else ""
            
            if hasattr(nested_row.cells[1], "value") and nested_row.cells[1].value is not None:
                value_str = nested_row.cells[1].value
            else:
                value_str = str(nested_row.cells[1]) if nested_row.cells[1] else None
            
            label_lower = label.lower() if isinstance(label, str) else ""
            
            # Flexible matching for closing bank balance
            if any(term in label_lower for term in ["closing bank balance", "closing balance", "bank balance", "cash position"]):
                metrics["cash_position"] = self._parse_currency_value(value_str)
            # Flexible matching for cash spent
            elif any(term in label_lower for term in ["cash spent", "total cash spent", "cash out", "cash outflow"]):
                metrics["cash_spent"] = self._parse_currency_value(value_str)
            # Flexible matching for cash received
            elif any(term in label_lower for term in ["cash received", "total cash received", "cash in", "cash inflow"]):
                metrics["cash_received"] = self._parse_currency_value(value_str)
        
        return metrics
    
    def _extract_profitability_metrics(self, profitability_section: Any) -> dict[str, Decimal]:
        """
        Extract profitability metrics from Profitability section.
        
        Handles variations:
        - "expenses", "total expenses", "operating expenses"
        
        Args:
            profitability_section: Profitability section row object
            
        Returns:
            Dict with operating_expenses
        """
        metrics = {
            "operating_expenses": Decimal("0.00"),
        }
        
        if not profitability_section or not hasattr(profitability_section, "rows") or not profitability_section.rows:
            return metrics
        
        for nested_row in profitability_section.rows:
            if not hasattr(nested_row, "cells") or not nested_row.cells or len(nested_row.cells) < 2:
                continue
            
            # Safely get label and value
            label = ""
            value_str = None
            
            if hasattr(nested_row.cells[0], "value") and nested_row.cells[0].value is not None:
                label = str(nested_row.cells[0].value)
            else:
                label = str(nested_row.cells[0]) if nested_row.cells[0] else ""
            
            if hasattr(nested_row.cells[1], "value") and nested_row.cells[1].value is not None:
                value_str = nested_row.cells[1].value
            else:
                value_str = str(nested_row.cells[1]) if nested_row.cells[1] else None
            
            label_lower = label.lower() if isinstance(label, str) else ""
            
            # Flexible matching for expenses
            if any(term in label_lower for term in ["expenses", "total expenses", "operating expenses", "operating costs"]):
                metrics["operating_expenses"] = self._parse_currency_value(value_str)
        
        return metrics
    
    async def fetch_executive_summary(self, report_date: Optional[date] = None) -> dict[str, Any]:
        """
        Fetch Executive Summary report for accurate cash flow metrics.
        
        This is the primary data source for cash runway calculations.
        The report includes all cash flow sources (invoices, bills, bank feeds, etc.)
        and excludes internal transfers automatically.
        
        Args:
            report_date: Date for the report (defaults to today).
                        Use month-end dates (e.g., 2025-12-31) for historical months.
                        
                        Important: Xero always returns the FULL calendar month report,
                        regardless of the date passed. For example:
                        - If today is Dec 23, 2025 and report_date=None:
                          Returns: "For the month of December 2025" (Dec 1-31)
                          Data: Actual transactions up to Dec 23 only (not projected)
                        - If report_date=2025-11-30:
                          Returns: "For the month of November 2025" (Nov 1-30)
                          Data: Complete November data
        
        Returns:
            {
                "cash_position": 0.0,      # Closing bank balance
                "cash_spent": 0.0,         # Actual cash outflow (excludes internal transfers)
                "cash_received": 0.0,      # Actual cash inflow
                "operating_expenses": 0.0, # Total expenses from P&L
                "report_date": "YYYY-MM-DD",
                "raw_data": {...}          # Full report structure
            }
        """
        try:
            if report_date is None:
                report_date = datetime.now(timezone.utc).date()
            
            # Get organization_id for rate limiting (from token)
            organization_id = self.client.token.organization_id if hasattr(self.client, "token") else None
            
            # Rate limit check
            if organization_id:
                await self.rate_limiter.wait_if_needed(organization_id)
            
            # Execute API call with retry logic
            async def _fetch():
                return self.api.get_report_executive_summary(
                    xero_tenant_id=self.tenant_id,
                    date=report_date,
                )
            
            response = await self.retry_handler.execute_with_retry(_fetch)
            
            # Record API call for rate limiting
            if organization_id:
                await self.rate_limiter.record_call(organization_id)
            
            if not hasattr(response, "reports") or not response.reports:
                logger.warning("No reports found in Executive Summary response")
                return {
                    "cash_position": 0.0,
                    "cash_spent": 0.0,
                    "cash_received": 0.0,
                    "operating_expenses": 0.0,
                    "report_date": report_date.isoformat(),
                    "raw_data": None,
                }
            
            report = response.reports[0]
            rows = report.rows if hasattr(report, "rows") else []
            
            # Use semantic matching to find Cash section
            cash_section = self._find_report_section(
                rows,
                possible_titles=["Cash", "Trésorerie", "Efectivo", "Liquid Assets", "Bank Accounts", "Cash and Bank"],
                row_type="Section"
            )
            
            cash_metrics = self._extract_cash_metrics(cash_section) if cash_section else {
                "cash_position": Decimal("0.00"),
                "cash_spent": Decimal("0.00"),
                "cash_received": Decimal("0.00"),
            }
            
            if not cash_section:
                logger.warning(
                    "Cash section not found in Executive Summary report. "
                    "This may indicate a non-English locale or custom report layout."
                )
            
            # Use semantic matching to find Profitability section
            profitability_section = self._find_report_section(
                rows,
                possible_titles=["Profitability", "Rentabilité", "Rentabilidad", "Profit", "Performance"],
                row_type="Section"
            )
            
            profitability_metrics = self._extract_profitability_metrics(profitability_section) if profitability_section else {
                "operating_expenses": Decimal("0.00"),
            }
            
            if not profitability_section:
                logger.warning(
                    "Profitability section not found in Executive Summary report. "
                    "This may indicate a non-English locale or custom report layout."
                )
            
            cash_position = cash_metrics["cash_position"]
            cash_spent = cash_metrics["cash_spent"]
            cash_received = cash_metrics["cash_received"]
            operating_expenses = profitability_metrics["operating_expenses"]
            
            raw_data = report.to_dict() if hasattr(report, "to_dict") else None
            
            return {
                "cash_position": float(cash_position),
                "cash_spent": float(cash_spent),
                "cash_received": float(cash_received),
                "operating_expenses": float(operating_expenses),
                "report_date": report_date.isoformat(),
                "raw_data": _to_json_serializable(raw_data),
            }
            
        except ApiException as e:
            logger.error("SDK error fetching Executive Summary report: %s", e)
            raise XeroDataFetchError(
                f"Failed to fetch Executive Summary: {str(e)}",
                status_code=e.status if hasattr(e, "status") else None,
                endpoint="ExecutiveSummary"
            ) from e
        except Exception as e:
            logger.error("Error fetching Executive Summary report: %s", e, exc_info=True)
            raise XeroDataFetchError(
                f"Failed to fetch Executive Summary: {str(e)}",
                endpoint="ExecutiveSummary"
            ) from e
    
    async def fetch_executive_summary_history(self, months: int = 6) -> list[dict[str, Any]]:
        """
        Fetch Executive Summary for multiple historical months.
        
        Useful for trend analysis and historical burn rate calculations.
        
        Args:
            months: Number of historical months to fetch (default: 6)
                   Fetches: (current-1), (current-2), ..., (current-months)
                   Example: If today is Dec 23, 2025 and months=3:
                            - Nov 2025 (month-end: 2025-11-30)
                            - Oct 2025 (month-end: 2025-10-31)
                            - Sep 2025 (month-end: 2025-09-30)
        
        Returns:
            List of Executive Summary data, one per month, ordered from oldest to newest.
            Each item has the same structure as fetch_executive_summary().
        """
        history = []
        today = datetime.now(timezone.utc).date()
        current_month_start = today.replace(day=1)
        
        for i in range(1, months + 1):
            target_year = current_month_start.year
            target_month = current_month_start.month - i
            
            while target_month <= 0:
                target_month += 12
                target_year -= 1
            
            month_end = self._get_month_end_date(target_year, target_month)
            
            try:
                summary = await self.fetch_executive_summary(report_date=month_end)
                history.append(summary)
            except XeroDataFetchError as e:
                logger.warning("Failed to fetch Executive Summary for %s: %s", month_end, e.message)
                history.append({
                    "cash_position": 0.0,
                    "cash_spent": 0.0,
                    "cash_received": 0.0,
                    "operating_expenses": 0.0,
                    "report_date": month_end.isoformat(),
                    "raw_data": None,
                    "error": e.message,
                })
        
        return list(reversed(history))
    
    async def fetch_receivables(self) -> dict[str, Any]:
        """
        Fetch Accounts Receivable invoices.
        
        Used for leading indicators (receivables timing, overdue analysis).
        
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
        
        Used for leading indicators (payables timing, cash pressure signals).
        
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
        
        Used for AI narrative (expense categories, revenue trends, profit analysis).
        Returns raw P&L data for AI analysis.
        
        Args:
            months: Number of months of history
        
        Returns:
            P&L report structure (raw from Xero)
        """
        try:
            end_date = datetime.now(timezone.utc).date()
            start_date = (end_date - timedelta(days=months * 31)).replace(day=1)
            
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
                )
            
            response = await self.retry_handler.execute_with_retry(_fetch)
            
            # Record API call for rate limiting
            if organization_id:
                await self.rate_limiter.record_call(organization_id)
            
            if hasattr(response, "reports") and response.reports:
                report = response.reports[0]
                raw_data = report.to_dict() if hasattr(report, "to_dict") else None
                return {
                    "report_id": report.report_id if hasattr(report, "report_id") else None,
                    "report_name": report.report_name if hasattr(report, "report_name") else None,
                    "report_date": report.report_date if hasattr(report, "report_date") else None,
                    "raw_data": _to_json_serializable(raw_data),
                }
            
            return {
                "report_id": None,
                "report_name": "Profit and Loss",
                "report_date": None,
                "raw_data": None,
            }
            
        except ApiException as e:
            logger.warning("SDK error fetching Profit & Loss report: %s", e)
            return {
                "report_id": None,
                "report_name": "Profit and Loss",
                "report_date": None,
                "raw_data": None,
                "error": str(e),
            }
        except Exception as e:
            logger.warning("Error fetching Profit & Loss report: %s", e)
            return {
                "report_id": None,
                "report_name": "Profit and Loss",
                "report_date": None,
                "raw_data": None,
                "error": str(e),
            }
    
    async def fetch_all_data(
        self, 
        organization_id: Optional[UUID] = None,
        months: int = 6,
        force_refresh: bool = False
    ) -> dict[str, Any]:
        """
        Fetch all financial data required for cash runway calculations.
        
        Primary data source: Executive Summary Report (current + historical).
        Additional data: Receivables, Payables, P&L for context and AI narrative.
        
        Uses cache when available and not force_refresh.
        
        Args:
            organization_id: Organization UUID (required for caching)
            months: Number of historical months to fetch (default: 6)
            force_refresh: If True, bypass cache and fetch fresh data
        
        Returns:
            Complete financial data structure
        """
        try:
            errors = []
            
            # Try cache first (if cache_service and organization_id provided, and not force_refresh)
            use_cache = (
                self.cache_service is not None
                and organization_id is not None
                and not force_refresh
            )
            
            executive_summary_current = None
            executive_summary_history_cached = {}
            executive_summary_history_missing = []
            receivables = None
            payables = None
            profit_loss = None
            
            if use_cache:
                # Get cached Executive Summary
                (
                    executive_summary_current,
                    executive_summary_history_cached,
                    executive_summary_history_missing,
                ) = await self.cache_service.get_cached_executive_summary(
                    organization_id, months
                )
                
                # Get cached financial data
                cached_financial = await self.cache_service.get_cached_financial_data(
                    organization_id
                )
                if cached_financial:
                    receivables = cached_financial.get("invoices_receivable")
                    payables = cached_financial.get("invoices_payable")
                    profit_loss = cached_financial.get("profit_loss")
            
            # Fetch current Executive Summary if not cached
            if executive_summary_current is None:
                try:
                    executive_summary_current = await self.fetch_executive_summary()
                    # Commit token updates immediately after API call (SDK may have refreshed)
                    await self.client.commit_token_updates()
                except XeroDataFetchError as e:
                    errors.append(f"Executive Summary (current): {e.message}")
                    executive_summary_current = {
                        "cash_position": 0.0,
                        "cash_spent": 0.0,
                        "cash_received": 0.0,
                        "operating_expenses": 0.0,
                        "report_date": datetime.now(timezone.utc).date().isoformat(),
                        "raw_data": None,
                    }
            
            # Fetch missing historical months
            executive_summary_history_fetched = []
            if executive_summary_history_missing:
                try:
                    # Fetch only missing months
                    for missing_date in executive_summary_history_missing:
                        month_data = await self.fetch_executive_summary(report_date=missing_date)
                        executive_summary_history_fetched.append(month_data)
                        # Commit token updates after each API call
                        await self.client.commit_token_updates()
                except Exception as e:
                    errors.append(f"Executive Summary (history): {str(e)}")
            
            # Combine cached and fetched historical data
            executive_summary_history = list(executive_summary_history_cached.values())
            executive_summary_history.extend(executive_summary_history_fetched)
            # Sort by report_date (oldest first)
            executive_summary_history.sort(key=lambda x: x.get("report_date", ""))
            
            # Fetch receivables if not cached
            if receivables is None:
                try:
                    receivables = await self.fetch_receivables()
                    # Commit token updates immediately after API call
                    await self.client.commit_token_updates()
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
            
            # Fetch payables if not cached
            if payables is None:
                try:
                    payables = await self.fetch_payables()
                    # Commit token updates immediately after API call
                    await self.client.commit_token_updates()
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
            
            # Fetch P&L if not cached
            if profit_loss is None:
                try:
                    profit_loss = await self.fetch_profit_loss(months=3)
                    # Commit token updates immediately after API call
                    await self.client.commit_token_updates()
                except Exception as e:
                    # P&L is optional, log but don't fail
                    logger.warning("Failed to fetch P&L: %s", e)
                    profit_loss = {
                        "report_id": None,
                        "report_name": "Profit and Loss",
                        "report_date": None,
                        "raw_data": None,
                        "error": str(e),
                    }
            
            # Save to cache if we fetched new data
            if use_cache and organization_id:
                try:
                    # Save Executive Summary
                    if executive_summary_current or executive_summary_history_fetched:
                        await self.cache_service.save_executive_summary_cache(
                            organization_id=organization_id,
                            current=executive_summary_current,
                            historical=executive_summary_history_fetched,
                        )
                    
                    # Save financial data (if we fetched any)
                    if receivables or payables or profit_loss:
                        await self.cache_service.save_financial_data_cache(
                            organization_id=organization_id,
                            receivables=receivables,
                            payables=payables,
                            profit_loss=profit_loss,
                        )
                except Exception as e:
                    logger.warning("Failed to save to cache: %s", e)
                    # Don't fail the request if cache save fails
            
            if errors:
                logger.warning("Some data fetch operations failed: %s", ", ".join(errors))
            
            # Final commit to ensure all token updates are saved
            await self.client.commit_token_updates()
            
            return {
                "executive_summary_current": executive_summary_current,
                "executive_summary_history": executive_summary_history,
                "invoices_receivable": receivables,
                "invoices_payable": payables,
                "profit_loss": profit_loss,
                "fetched_at": datetime.now(timezone.utc).isoformat(),
                "errors": errors if errors else None,
            }
            
        except Exception as e:
            logger.error("Error fetching all data: %s", e, exc_info=True)
            raise XeroDataFetchError(f"Failed to fetch financial data: {str(e)}") from e
