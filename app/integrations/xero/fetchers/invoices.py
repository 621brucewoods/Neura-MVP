"""
Invoices Fetcher
Fetches invoices (receivables and payables) from Xero.
"""

import logging
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any
import asyncio
from xero_python.exceptions import ApiException

from app.integrations.xero.exceptions import XeroDataFetchError
from app.integrations.xero.fetchers.base import BaseFetcher
from app.integrations.xero.utils import parse_decimal

logger = logging.getLogger(__name__)


class InvoicesFetcher(BaseFetcher):
    """Fetcher for Invoices (Receivables and Payables)."""
    
    async def fetch(self, invoice_type: str) -> dict[str, Any]:
        """
        Fetch invoices (receivables or payables).
        
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
            
            organization_id = self.organization_id
            
            while True:
                # Rate limit check before each page
                if organization_id:
                    await self.rate_limiter.wait_if_needed(organization_id)
                
                # Execute API call with retry logic
                # Execute API call with retry logic
                
                async def _fetch_page():
                    loop = asyncio.get_running_loop()
                    def _do_sync_request():
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
                    return await loop.run_in_executor(None, _do_sync_request)
                
                response = await self.retry_handler.execute_with_retry(_fetch_page)
                
                # Record API call for rate limiting
                if organization_id:
                    await self.rate_limiter.record_call(organization_id)
                
                # Flush token updates (will be committed by endpoint/FastAPI)
                await self._flush_token_updates()
                
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
                
                amount_due = parse_decimal(
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
        return await self.fetch(invoice_type="ACCREC")
    
    async def fetch_payables(self) -> dict[str, Any]:
        """
        Fetch Accounts Payable invoices.
        
        Used for upcoming commitments analysis.
        
        Returns:
            Invoice summary with metrics
        """
        return await self.fetch(invoice_type="ACCPAY")

