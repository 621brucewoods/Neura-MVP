"""
Base Fetcher
Common functionality for all Xero data fetchers.
"""

import logging
from typing import Optional
from uuid import UUID

from app.integrations.xero.rate_limiter import XeroRateLimiter
from app.integrations.xero.retry_handler import XeroRetryHandler
from app.integrations.xero.sdk_client import XeroSDKClient
from app.integrations.xero.session_manager import XeroSessionManager
from typing import Optional

logger = logging.getLogger(__name__)


class BaseFetcher:
    """Base class for all Xero data fetchers."""
    
    def __init__(
        self,
        sdk_client: XeroSDKClient,
        session_manager: Optional[XeroSessionManager] = None,
        rate_limiter: Optional[XeroRateLimiter] = None,
        retry_handler: Optional[XeroRetryHandler] = None,
    ):
        """
        Initialize base fetcher.
        
        Args:
            sdk_client: Xero SDK client
            session_manager: Optional session manager for DB operations
            rate_limiter: Optional rate limiter (creates default if None)
            retry_handler: Optional retry handler (creates default if None)
        """
        self.client = sdk_client
        self.api = sdk_client.accounting_api
        self.tenant_id = sdk_client.tenant_id
        self.session_manager = session_manager
        self.rate_limiter = rate_limiter or XeroRateLimiter()
        self.retry_handler = retry_handler or XeroRetryHandler()
    
    @property
    def organization_id(self) -> Optional[UUID]:
        """Get organization ID from token."""
        if hasattr(self.client, "token") and self.client.token:
            return self.client.token.organization_id
        return None
    
    async def _flush_token_updates(self) -> None:
        """Flush token updates (no commit)."""
        if self.session_manager:
            await self.session_manager.flush_token_updates()
        else:
            # Fallback to direct call if no session manager
            await self.client.commit_token_updates(skip_commit=True)

