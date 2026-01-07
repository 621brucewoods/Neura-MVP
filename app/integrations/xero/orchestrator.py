"""
Xero Data Orchestrator
Coordinates parallel fetching of all Xero financial data.
"""

import asyncio
import logging
from datetime import date, datetime, timedelta, timezone
from typing import Any, Optional
from uuid import UUID

from app.integrations.xero.cache_service import CacheService
from app.integrations.xero.exceptions import XeroDataFetchError
from app.integrations.xero.fetchers.accounts import AccountsFetcher
from app.integrations.xero.fetchers.balance_sheet import BalanceSheetFetcher
from app.integrations.xero.fetchers.invoices import InvoicesFetcher
from app.integrations.xero.fetchers.profit_loss import ProfitLossFetcher
from app.integrations.xero.fetchers.trial_balance import TrialBalanceFetcher
from app.integrations.xero.parsers import TrialBalanceParser
from app.integrations.xero.sdk_client import XeroSDKClient
from app.integrations.xero.session_manager import XeroSessionManager

logger = logging.getLogger(__name__)


class XeroDataOrchestrator:
    """
    Orchestrates fetching of all required financial data with parallelization.
    
    Strategy:
    - Group 1 (parallel): Balance Sheets, P&L, Accounts (all independent)
    - Group 2 (parallel): Trial Balance, Receivables, Payables (after Accounts)
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
        self.trial_balance_fetcher = TrialBalanceFetcher(sdk_client, session_manager)
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
    
    async def _fetch_profit_loss_with_cache(
        self,
        organization_id: Optional[UUID],
        start_date: date,
        end_date: date,
        force_refresh: bool,
    ) -> tuple[dict[str, Any], Optional[str]]:
        """Fetch P&L with cache logic."""
        try:
            if not force_refresh and self.cache_service:
                cached_pnl = await self.cache_service.get_cached_profit_loss(
                    organization_id, start_date, end_date
                )
                if cached_pnl:
                    logger.info(
                        "Using cached P&L for period: %s to %s",
                        start_date,
                        end_date
                    )
                    return cached_pnl, None
            
            profit_loss = await self.profit_loss_fetcher.fetch(
                start_date=start_date,
                end_date=end_date
            )
            
            if self.cache_service and not force_refresh:
                await self.cache_service.save_profit_loss_cache(
                    organization_id, start_date, end_date, profit_loss
                )
            
            logger.info(
                "Fetched P&L for period: %s to %s",
                start_date,
                end_date
            )
            return profit_loss, None
        except XeroDataFetchError as e:
            error_msg = f"Profit & Loss: {e.message}"
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
    
    async def _fetch_trial_balance_with_error_handling(
        self,
        end_date: date,
        accounts_map: dict[str, str],
    ) -> tuple[dict[str, Any], dict[str, Any], Optional[str]]:
        """Fetch trial balance and extract P&L with error handling."""
        try:
            trial_balance = await self.trial_balance_fetcher.fetch(end_date)
            
            if accounts_map:
                trial_balance_pnl = TrialBalanceParser.extract_pnl(
                    trial_balance, accounts_map
                )
            else:
                logger.warning("Cannot extract Trial Balance P&L: account_type_map is empty")
                trial_balance_pnl = {}
            
            return trial_balance, trial_balance_pnl, None
        except XeroDataFetchError as e:
            error_msg = f"Trial Balance: {e.message}"
            logger.warning(error_msg)
            return {}, {}, error_msg
    
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
        start_date: date = None,
        end_date: date = None,
        force_refresh: bool = False
    ) -> dict[str, Any]:
        """
        Orchestrates fetching of all required financial data with parallelization.
        
        Strategy:
        - Group 1 (parallel): Balance Sheets, P&L, Accounts (all independent)
        - Group 2 (parallel): Trial Balance, Receivables, Payables (after Accounts)
        
        Args:
            organization_id: Organization UUID
            start_date: P&L period start date
            end_date: P&L period end date
            force_refresh: If True, bypass cache and fetch fresh data
        
        Returns:
            Complete financial data structure
        """
        try:
            errors = []
            
            if not start_date or not end_date:
                raise ValueError("start_date and end_date are required")
            
            if start_date >= end_date:
                raise ValueError("start_date must be before end_date")
            
            prior_date = end_date - timedelta(days=30)
            
            # Group 1: Fetch independent data in parallel
            (
                (balance_sheet_current, error_current),
                (balance_sheet_prior, error_prior),
                (profit_loss, error_pnl),
                (accounts_map, error_accounts),
            ) = await asyncio.gather(
                self._fetch_balance_sheet_with_error_handling(end_date, "current"),
                self._fetch_balance_sheet_with_error_handling(prior_date, "prior"),
                self._fetch_profit_loss_with_cache(
                    organization_id, start_date, end_date, force_refresh
                ),
                self._fetch_accounts_with_error_handling(),
            )
            
            if error_current:
                errors.append(error_current)
            if error_prior:
                errors.append(error_prior)
            if error_pnl:
                errors.append(error_pnl)
            if error_accounts:
                errors.append(error_accounts)
            
            # Group 2: Fetch dependent data in parallel (after Accounts is available)
            (
                (trial_balance, trial_balance_pnl, error_trial),
                (receivables, error_receivables),
                (payables, error_payables),
            ) = await asyncio.gather(
                self._fetch_trial_balance_with_error_handling(end_date, accounts_map),
                self._fetch_receivables_with_error_handling(),
                self._fetch_payables_with_error_handling(),
            )
            
            if error_trial:
                errors.append(error_trial)
            if error_receivables:
                errors.append(error_receivables)
            if error_payables:
                errors.append(error_payables)
            
            if errors:
                logger.warning("Some data fetch operations failed: %s", ", ".join(errors))
            
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
            raise
        except Exception as e:
            logger.error("Failed to fetch all data: %s", e)
            raise XeroDataFetchError(f"Failed to fetch all data: {str(e)}") from e

