"""
Xero Data Orchestrator
Coordinates parallel fetching of all Xero financial data.

Uses the Extractors module for all data extraction (single source of truth).

Data Flow:
- Balance Sheet data: Fetched here, extracted by Extractors
- P&L data: Fetched via fetch_monthly_pnl_with_cache(), extracted by Extractors
- AR/AP data: Fetched here, extracted by Extractors
"""

import asyncio
import logging
from datetime import date, datetime, timedelta, timezone
from typing import Any, Optional
from uuid import UUID

from app.integrations.xero.cache_service import CacheService
from app.integrations.xero.exceptions import XeroDataFetchError
from app.integrations.xero.extractors import Extractors
from app.integrations.xero.fetchers.accounts import AccountsFetcher
from app.integrations.xero.fetchers.balance_sheet import BalanceSheetFetcher
from app.integrations.xero.fetchers.invoices import InvoicesFetcher
from app.integrations.xero.fetchers.profit_loss import ProfitLossFetcher
from app.integrations.xero.sdk_client import XeroSDKClient
from app.integrations.xero.session_manager import XeroSessionManager

logger = logging.getLogger(__name__)


class XeroDataOrchestrator:
    """
    Orchestrates fetching of all required financial data with parallelization.
    
    Strategy:
    - Group 1 (parallel): Balance Sheets (current + prior), Accounts
    - Group 2 (parallel): Receivables, Payables
    
    Note: P&L data is fetched separately via fetch_monthly_pnl_with_cache()
    to get monthly breakdowns for trend analysis.
    """
    
    def __init__(
        self,
        sdk_client: XeroSDKClient,
        session_manager: Optional[XeroSessionManager],
        cache_service: Optional[CacheService] = None,
    ):
        """
        Initialize orchestrator.
        
        Args:
            sdk_client: Xero SDK client
            session_manager: Optional session manager for DB operations
            cache_service: Optional cache service
        """
        self.sdk_client = sdk_client
        self.session_manager = session_manager
        self.cache_service = cache_service
        
        # Initialize fetchers
        self.balance_sheet_fetcher = BalanceSheetFetcher(sdk_client, session_manager)
        self.profit_loss_fetcher = ProfitLossFetcher(sdk_client, session_manager)
        self.accounts_fetcher = AccountsFetcher(sdk_client, session_manager)
        self.invoices_fetcher = InvoicesFetcher(sdk_client, session_manager)
    
    async def _fetch_balance_sheet_with_error_handling(
        self, report_date: date, label: str
    ) -> tuple[dict[str, Any], Optional[str]]:
        """Fetch balance sheet with error handling."""
        try:
            balance_sheet = await self.balance_sheet_fetcher.fetch(report_date)
            return balance_sheet, None
        except XeroDataFetchError as e:
            error_msg = f"Balance Sheet ({label}): {e.message}"
            logger.warning(error_msg)
            return {}, error_msg
    
    async def _fetch_accounts_with_error_handling(
        self,
    ) -> tuple[dict[str, str], Optional[str]]:
        """Fetch accounts with error handling."""
        try:
            accounts_map = await self.accounts_fetcher.fetch()
            return accounts_map, None
        except XeroDataFetchError as e:
            error_msg = f"Accounts: {e.message}"
            logger.warning(error_msg)
            return {}, error_msg
    
    async def _fetch_receivables_with_error_handling(
        self,
    ) -> tuple[dict[str, Any], Optional[str]]:
        """Fetch receivables with error handling."""
        try:
            receivables = await self.invoices_fetcher.fetch_receivables()
            return receivables, None
        except XeroDataFetchError as e:
            error_msg = f"Receivables: {e.message}"
            logger.warning(error_msg)
            return {
                "total": 0.0,
                "count": 0,
                "overdue_amount": 0.0,
                "overdue_count": 0,
                "avg_days_overdue": 0.0,
                "invoices": [],
            }, error_msg
    
    async def _fetch_payables_with_error_handling(
        self,
    ) -> tuple[dict[str, Any], Optional[str]]:
        """Fetch payables with error handling."""
        try:
            payables = await self.invoices_fetcher.fetch_payables()
            return payables, None
        except XeroDataFetchError as e:
            error_msg = f"Payables: {e.message}"
            logger.warning(error_msg)
            return {
                "total": 0.0,
                "count": 0,
                "overdue_amount": 0.0,
                "overdue_count": 0,
                "avg_days_overdue": 0.0,
                "invoices": [],
            }, error_msg
    
    async def fetch_all(
        self,
        organization_id: Optional[UUID] = None,
        balance_sheet_date: date = None,
        force_refresh: bool = False
    ) -> dict[str, Any]:
        """
        Orchestrates fetching of all required financial data with parallelization.
        
        Strategy:
        - Group 1 (parallel): Balance Sheets (current + prior), Accounts
        - Group 2 (parallel): Receivables, Payables
        
        Note: P&L data should be fetched separately via fetch_monthly_pnl_with_cache()
        to get monthly breakdowns for trend analysis and health score calculations.
        
        Args:
            organization_id: Organization UUID
            balance_sheet_date: The "as of" date for Balance Sheet (typically today)
            force_refresh: If True, bypass cache and fetch fresh data
        
        Returns:
            Complete financial data structure (excluding P&L - use monthly P&L)
        """
        try:
            errors = []
            
            if not balance_sheet_date:
                raise ValueError("balance_sheet_date is required")
            
            prior_date = balance_sheet_date - timedelta(days=30)
            
            # Group 1: Fetch independent data in parallel
            (
                (balance_sheet_current, error_current),
                (balance_sheet_prior, error_prior),
                (accounts_map, error_accounts),
            ) = await asyncio.gather(
                self._fetch_balance_sheet_with_error_handling(balance_sheet_date, "current"),
                self._fetch_balance_sheet_with_error_handling(prior_date, "prior"),
                self._fetch_accounts_with_error_handling(),
            )
            
            if error_current:
                errors.append(error_current)
            if error_prior:
                errors.append(error_prior)
            if error_accounts:
                errors.append(error_accounts)
            
            # Group 2: Fetch receivables/payables in parallel
            (
                (receivables_raw, error_receivables),
                (payables_raw, error_payables),
            ) = await asyncio.gather(
                self._fetch_receivables_with_error_handling(),
                self._fetch_payables_with_error_handling(),
            )
            
            if error_receivables:
                errors.append(error_receivables)
            if error_payables:
                errors.append(error_payables)
            
            if errors:
                logger.warning("Some data fetch operations failed: %s", ", ".join(errors))
            
            # =================================================================
            # EXTRACTION: Use Extractors module (single source of truth)
            # =================================================================
            
            # Extract Balance Sheet and AR/AP data
            # Note: P&L is extracted from monthly data via extract_monthly_pnl_totals()
            extracted = Extractors.extract_all(
                balance_sheet_raw=balance_sheet_current,
                invoices_receivable=receivables_raw,
                invoices_payable=payables_raw,
                account_map=accounts_map,
                organization_id=str(organization_id) if organization_id else None,
                period_end=balance_sheet_date.isoformat() if balance_sheet_date else None,
            )
            
            # Log extraction summary
            bs = extracted["balance_sheet"]
            logger.info(
                "Extraction complete: cash=%.2f, AR=%.2f, AP=%.2f, "
                "inventory=%.2f, fixed_assets=%.2f, equity=%.2f",
                bs.get("cash") or 0,
                bs.get("accounts_receivable") or 0,
                bs.get("accounts_payable") or 0,
                bs.get("inventory") or 0,
                bs.get("fixed_assets") or 0,
                bs.get("equity") or 0,
            )
            
            # Return data structure
            # Note: P&L data should come from monthly P&L fetch, not here
            return {
                # Raw data (for any code that needs it)
                "balance_sheet_current": balance_sheet_current,
                "balance_sheet_prior": balance_sheet_prior,
                "account_type_map": accounts_map,
                "invoices_receivable": receivables_raw,
                "invoices_payable": payables_raw,
                
                # Clean extracted data (primary interface)
                "extracted": extracted,
                
                # Backward compatible alias
                "balance_sheet_totals": extracted["balance_sheet"],
                
                # Metadata
                "fetched_at": datetime.now(timezone.utc).isoformat(),
                "errors": errors if errors else None,
            }
        except XeroDataFetchError:
            raise
        except Exception as e:
            logger.error("Failed to fetch all data: %s", e)
            raise XeroDataFetchError(f"Failed to fetch all data: {str(e)}") from e
    
    async def fetch_monthly_pnl_with_cache(
        self,
        organization_id: UUID,
        num_months: int = 12,
        force_refresh: bool = False,
    ) -> list[dict[str, Any]]:
        """
        Fetch monthly P&L data with intelligent caching.
        
        Caching Strategy:
        - Current month: Always re-fetch (1 hour TTL)
        - Last month: Re-fetch if expired (24 hour TTL)
        - Historical months: Use cache if available (never expires)
        
        Args:
            organization_id: Organization UUID
            num_months: Number of months to fetch (default 12)
            force_refresh: If True, bypass cache and fetch all months
            
        Returns:
            List of monthly P&L data, sorted newest to oldest
        """
        cached_month_keys: set[str] = set()
        cached_data: dict[str, dict[str, Any]] = {}
        
        # Get cached data (unless force refresh)
        if not force_refresh and self.cache_service:
            cached_data, cached_month_keys = await self.cache_service.get_cached_monthly_pnl(
                organization_id, num_months
            )
            logger.info(
                "Monthly P&L cache: %d months cached for org %s",
                len(cached_month_keys),
                organization_id,
            )
        
        # Fetch missing/expired months
        fetched_data = await self.profit_loss_fetcher.fetch_monthly_pnl(
            num_months=num_months,
            cached_months=cached_month_keys if not force_refresh else None,
        )
        
        # Save newly fetched data to cache
        if fetched_data and self.cache_service:
            await self.cache_service.save_monthly_pnl_cache(
                organization_id, fetched_data
            )
        
        # Merge cached and fetched data
        # Fetched data takes priority (it's fresher)
        all_data = {}
        
        # Add cached data first
        for month_key, data in cached_data.items():
            all_data[month_key] = data
        
        # Override with freshly fetched data
        for entry in fetched_data:
            if "error" not in entry:
                all_data[entry["month_key"]] = {
                    "month_key": entry["month_key"],
                    "year": entry["year"],
                    "month": entry["month"],
                    "raw_data": entry.get("data", {}),
                    # P&L totals will be extracted later by Extractors
                    "revenue": None,
                    "cost_of_sales": None,
                    "expenses": None,
                    "net_profit": None,
                    "is_fresh": True,
                }
        
        # Sort by month (newest first) and return as list
        sorted_months = sorted(all_data.keys(), reverse=True)
        result = [all_data[k] for k in sorted_months]
        
        logger.info(
            "Monthly P&L complete for org %s: %d months available",
            organization_id,
            len(result),
        )
        
        return result

