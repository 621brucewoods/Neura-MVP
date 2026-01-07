"""
Profit & Loss Fetcher
Fetches Profit & Loss reports from Xero.
"""

import logging
from datetime import date
import asyncio
from typing import Any

from xero_python.exceptions import ApiException

from app.integrations.xero.exceptions import XeroDataFetchError
from app.integrations.xero.fetchers.base import BaseFetcher
from app.integrations.xero.utils import to_json_serializable

logger = logging.getLogger(__name__)


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

