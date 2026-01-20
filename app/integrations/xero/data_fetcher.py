"""
Xero Data Fetcher
Facade for fetching financial data from Xero API.

Delegates to the Orchestrator for data fetching and Extractors for data extraction.
"""

import logging
from datetime import date
from typing import Any, Optional
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.integrations.xero.cache_service import CacheService
from app.integrations.xero.extractors import Extractors
from app.integrations.xero.rate_limiter import XeroRateLimiter
from app.integrations.xero.retry_handler import XeroRetryHandler
from app.integrations.xero.sdk_client import XeroSDKClient
from app.integrations.xero.session_manager import XeroSessionManager
from app.integrations.xero.orchestrator import XeroDataOrchestrator

logger = logging.getLogger(__name__)


class XeroDataFetcher:
    """
    Facade for fetching financial data from Xero.
    
    Maintains backward compatibility while delegating to specialized modules.
    """
    
    def __init__(
        self, 
        sdk_client: XeroSDKClient, 
        cache_service: Optional[CacheService] = None,
        rate_limiter: Optional[XeroRateLimiter] = None,
        retry_handler: Optional[XeroRetryHandler] = None,
        db: Optional[AsyncSession] = None,
    ):
        """
        Initialize data fetcher with SDK client and optional services.
        
        Args:
            sdk_client: Configured XeroSDKClient instance
            cache_service: Optional CacheService for caching data
            rate_limiter: Optional XeroRateLimiter for rate limiting (creates default if None)
            retry_handler: Optional XeroRetryHandler for retry logic (creates default if None)
            db: Optional database session for session manager
        """
        self.client = sdk_client
        self.api = sdk_client.accounting_api
        self.tenant_id = sdk_client.tenant_id
        self.cache_service = cache_service
        self.rate_limiter = rate_limiter or XeroRateLimiter()
        self.retry_handler = retry_handler or XeroRetryHandler()
    
        # Create session manager if DB is provided
        # Note: If db is None, we'll create a minimal session manager that just flushes
        # This maintains backward compatibility for code that doesn't pass db
        if db:
            self.session_manager = XeroSessionManager(db, sdk_client)
        else:
            # Create a dummy session manager that won't be used (for backward compat)
            # The fetchers will fall back to direct client calls
            self.session_manager = None
        
        # Create orchestrator
        self.orchestrator = XeroDataOrchestrator(
            sdk_client=sdk_client,
            session_manager=self.session_manager,
            cache_service=cache_service,
        )
    
    def extract_cash_from_balance_sheet(
        self, 
        balance_sheet: dict[str, Any],
        account_type_map: Optional[dict[str, Any]] = None
    ) -> Optional[float]:
        """
        Extract cash position from Balance Sheet using Extractors module.
        
        Args:
            balance_sheet: Balance Sheet data structure
            account_type_map: AccountID to AccountInfo mapping for extraction
            
        Returns:
            Cash position as float, or None if not found
        """
        if not account_type_map:
            logger.warning("No account_type_map provided for cash extraction")
            return None
        
        bs_data = Extractors.extract_balance_sheet(balance_sheet, account_type_map)
        return bs_data.get("cash")
    
    def extract_balance_sheet_totals(
        self,
        balance_sheet: dict[str, Any],
        account_type_map: dict[str, Any]
    ) -> dict[str, Optional[float]]:
        """
        Extract all Balance Sheet totals using Extractors module.
        
        Args:
            balance_sheet: Balance Sheet data structure
            account_type_map: AccountID to AccountInfo mapping
            
        Returns:
            Dictionary with all Balance Sheet totals
        """
        return Extractors.extract_balance_sheet(balance_sheet, account_type_map)
    
    async def fetch_all_data(
        self, 
        organization_id: Optional[UUID] = None,
        balance_sheet_date: date = None,
        force_refresh: bool = False
    ) -> dict[str, Any]:
        """
        Fetch all required financial data with parallelization.
        
        Fetches:
        - Balance Sheet (current as of balance_sheet_date, prior 30 days before)
        - Chart of Accounts (for AccountType mapping)
        - AR/AP Invoices (current outstanding)
        
        Note: P&L data is fetched separately via orchestrator.fetch_monthly_pnl_with_cache()
        
        Args:
            organization_id: Organization UUID
            balance_sheet_date: The "as of" date for Balance Sheet (typically today)
            force_refresh: If True, bypass cache and fetch fresh data
        
        Returns:
            Complete financial data structure
        """
        return await self.orchestrator.fetch_all(
            organization_id=organization_id,
            balance_sheet_date=balance_sheet_date,
            force_refresh=force_refresh,
        )
