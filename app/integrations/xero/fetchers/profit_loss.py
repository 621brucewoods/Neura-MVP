"""
Profit & Loss Fetcher
Fetches Profit & Loss reports from Xero.

Supports both single-period and monthly P&L fetching for historical analysis.
"""

import logging
from datetime import date, timedelta
from calendar import monthrange
import asyncio
from typing import Any, Optional

from xero_python.exceptions import ApiException

from app.integrations.xero.exceptions import XeroDataFetchError
from app.integrations.xero.fetchers.base import BaseFetcher
from app.integrations.xero.utils import to_json_serializable

logger = logging.getLogger(__name__)


def get_month_date_range(year: int, month: int) -> tuple[date, date]:
    """Get the start and end dates for a given month."""
    start_date = date(year, month, 1)
    _, last_day = monthrange(year, month)
    end_date = date(year, month, last_day)
    return start_date, end_date


def get_previous_months(num_months: int, reference_date: Optional[date] = None) -> list[tuple[int, int]]:
    """
    Get list of (year, month) tuples for the previous N months.
    
    Args:
        num_months: Number of months to go back (including current month)
        reference_date: Reference date (defaults to today)
    
    Returns:
        List of (year, month) tuples, most recent first
    """
    if reference_date is None:
        reference_date = date.today()
    
    months = []
    current = reference_date.replace(day=1)
    
    for _ in range(num_months):
        months.append((current.year, current.month))
        # Go to previous month
        current = current - timedelta(days=1)
        current = current.replace(day=1)
    
    return months


class ProfitLossFetcher(BaseFetcher):
    """Fetcher for Profit & Loss reports."""
    
    async def fetch(self, start_date: date, end_date: date) -> dict[str, Any]:
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
            organization_id = self.organization_id
            
            # Rate limit check
            if organization_id:
                await self.rate_limiter.wait_if_needed(organization_id)
            
            # Execute API call with retry logic
            # Execute API call with retry logic
            
            async def _fetch():
                loop = asyncio.get_running_loop()
                return await loop.run_in_executor(None, lambda: self.api.get_report_profit_and_loss(
                    xero_tenant_id=self.tenant_id,
                    from_date=start_date,
                    to_date=end_date,
                    standard_layout=True  # CRITICAL: Ensures consistent JSON structure
                ))
            
            response = await self.retry_handler.execute_with_retry(_fetch)
            
            # Record API call for rate limiting
            if organization_id:
                await self.rate_limiter.record_call(organization_id)
            
            # Flush token updates (will be committed by endpoint/FastAPI)
            await self._flush_token_updates()
            
            if not response.reports or len(response.reports) == 0:
                return {}
            
            # Extract first report (Xero returns list of reports)
            report = response.reports[0]
            report_dict = to_json_serializable(report)
            
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
    
    async def fetch_month(self, year: int, month: int) -> dict[str, Any]:
        """
        Fetch P&L for a specific month.
        
        Args:
            year: Year (e.g., 2025)
            month: Month (1-12)
            
        Returns:
            Monthly P&L data with metadata
        """
        start_date, end_date = get_month_date_range(year, month)
        
        try:
            pnl_data = await self.fetch(start_date, end_date)
            
            return {
                "year": year,
                "month": month,
                "month_key": f"{year}-{month:02d}",  # e.g., "2025-01"
                "start_date": start_date.isoformat(),
                "end_date": end_date.isoformat(),
                "data": pnl_data,
            }
        except XeroDataFetchError as e:
            logger.warning("Failed to fetch P&L for %d-%02d: %s", year, month, e)
            return {
                "year": year,
                "month": month,
                "month_key": f"{year}-{month:02d}",
                "start_date": start_date.isoformat(),
                "end_date": end_date.isoformat(),
                "data": {},
                "error": str(e),
            }
    
    async def fetch_monthly_pnl(
        self,
        num_months: int = 12,
        reference_date: Optional[date] = None,
        cached_months: Optional[set[str]] = None,
    ) -> list[dict[str, Any]]:
        """
        Fetch P&L for multiple months in parallel.
        
        Args:
            num_months: Number of months to fetch (default 12)
            reference_date: Reference date (defaults to today)
            cached_months: Set of month_keys (e.g., {"2025-01", "2025-02"}) to skip
            
        Returns:
            List of monthly P&L data, sorted newest to oldest
        """
        months_to_fetch = get_previous_months(num_months, reference_date)
        cached_months = cached_months or set()
        
        # Filter out cached months (but always re-fetch current and last month)
        today = date.today()
        current_month_key = f"{today.year}-{today.month:02d}"
        last_month = today.replace(day=1) - timedelta(days=1)
        last_month_key = f"{last_month.year}-{last_month.month:02d}"
        
        tasks = []
        for year, month in months_to_fetch:
            month_key = f"{year}-{month:02d}"
            
            # Always fetch current and last month, skip others if cached
            if month_key in cached_months and month_key not in (current_month_key, last_month_key):
                logger.debug("Skipping cached month: %s", month_key)
                continue
            
            tasks.append(self.fetch_month(year, month))
        
        if not tasks:
            logger.info("All months cached, no fetch needed")
            return []
        
        # Fetch in parallel
        logger.info("Fetching %d months of P&L data", len(tasks))
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        # Process results
        monthly_data = []
        for result in results:
            if isinstance(result, Exception):
                logger.error("Error fetching monthly P&L: %s", result)
                continue
            monthly_data.append(result)
        
        # Sort by month (newest first)
        monthly_data.sort(key=lambda x: x["month_key"], reverse=True)
        
        logger.info(
            "Fetched %d months of P&L data: %s",
            len(monthly_data),
            [m["month_key"] for m in monthly_data]
        )
        
        return monthly_data

