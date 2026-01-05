"""
Xero SDK Client Factory
Creates configured xero-python SDK clients from stored tokens.
"""

import logging
from datetime import datetime, timezone
from typing import Optional
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from xero_python.api_client import ApiClient, Configuration
from xero_python.api_client.oauth2 import OAuth2Token
from xero_python.accounting import AccountingApi

from app.config import settings
from app.integrations.xero.service import XeroService
from app.models.xero_token import XeroConnectionStatus, XeroToken

logger = logging.getLogger(__name__)


class XeroSDKClientError(Exception):
    """Exception raised for SDK client errors."""
    
    def __init__(self, message: str, status_code: Optional[int] = None):
        self.message = message
        self.status_code = status_code
        super().__init__(self.message)


class XeroSDKClient:
    """
    Factory for creating configured Xero SDK clients.
    
    Integrates with existing token storage to:
    - Create SDK clients with database tokens
    - Handle automatic token refresh via SDK
    - Save refreshed tokens back to database
    """
    
    def __init__(
        self,
        token: XeroToken,
        xero_service: XeroService,
    ):
        """
        Initialize SDK client factory.
        
        Args:
            token: XeroToken from database
            xero_service: XeroService for token operations
        """
        self.token = token
        self.xero_service = xero_service
        self._token_dict: dict = {}
        self._api_client: Optional[ApiClient] = None
        self._accounting_api: Optional[AccountingApi] = None
    
    def _build_token_dict(self) -> dict:
        """Build token dictionary for SDK from database token."""
        return {
            "access_token": self.token.access_token,
            "refresh_token": self.token.refresh_token,
            "token_type": self.token.token_type or "Bearer",
            "scope": self.token.scope or settings.xero_scopes,
            "expires_in": 1800,  # SDK needs this
            "expires_at": self.token.expires_at.timestamp() if self.token.expires_at else 0,
        }
    
    def _get_token(self) -> dict:
        """Token getter callback for SDK."""
        if not self._token_dict:
            self._token_dict = self._build_token_dict()
        return self._token_dict
    
    def _save_token(self, new_token: dict) -> None:
        """
        Token saver callback for SDK.
        
        Note: This is called synchronously by the SDK during auto-refresh.
        We update the in-memory token dict and token object.
        Database commit must be called explicitly after SDK operations.
        """
        self._token_dict.update(new_token)
        
        # Update the token object
        self.token.access_token = new_token.get("access_token", self.token.access_token)
        self.token.refresh_token = new_token.get("refresh_token", self.token.refresh_token)
        self.token.status = XeroConnectionStatus.ACTIVE.value
        self.token.last_error = None
        
        if "scope" in new_token:
            self.token.scope = new_token["scope"]
        
        if "expires_at" in new_token:
            self.token.expires_at = datetime.fromtimestamp(
                new_token["expires_at"], 
                tz=timezone.utc
            )
        
        self.token.last_refreshed_at = datetime.now(timezone.utc)
        
        logger.info("SDK refreshed tokens - commit required after operation")
    
    def _create_api_client(self) -> ApiClient:
        """Create configured ApiClient instance."""
        # Build initial token dict
        self._token_dict = self._build_token_dict()
        
        # Create configuration with OAuth2 token
        config = Configuration(
            oauth2_token=OAuth2Token(
                client_id=settings.xero_client_id,
                client_secret=settings.xero_client_secret,
            )
        )
        
        # Create API client with token callbacks
        api_client = ApiClient(
            config,
            oauth2_token_getter=self._get_token,
            oauth2_token_saver=self._save_token,
        )
        
        return api_client
    
    @property
    def api_client(self) -> ApiClient:
        """Get or create ApiClient instance."""
        if self._api_client is None:
            self._api_client = self._create_api_client()
        return self._api_client
    
    @property
    def accounting_api(self) -> AccountingApi:
        """Get or create AccountingApi instance."""
        if self._accounting_api is None:
            self._accounting_api = AccountingApi(self.api_client)
        return self._accounting_api
    
    @property
    def tenant_id(self) -> str:
        """Get Xero tenant ID."""
        return self.token.xero_tenant_id
    
    async def commit_token_updates(self) -> None:
        """Commit any token updates to database."""
        await self.xero_service.db.commit()
        await self.xero_service.db.refresh(self.token)


async def create_xero_sdk_client(
    organization_id: UUID,
    db: AsyncSession,
) -> XeroSDKClient:
    """
    Create an SDK client for an organization.
    
    SDK will automatically refresh tokens when needed during API calls.
    
    Args:
        organization_id: Organization UUID
        db: Database session
    
    Returns:
        Configured XeroSDKClient
    
    Raises:
        XeroSDKClientError: If no valid connection exists
    """
    xero_service = XeroService(db)
    
    # Get token
    token = await xero_service.get_token_by_organization(organization_id)
    
    if not token:
        raise XeroSDKClientError(
            "No Xero connection found. Please connect your Xero account first."
        )
    
    # Only block explicitly disconnected tokens (user disconnected)
    if token.status == XeroConnectionStatus.DISCONNECTED.value:
        raise XeroSDKClientError(
            "Xero connection has been disconnected. Please reconnect your Xero account."
        )
    
    # Create SDK client - SDK will handle token refresh automatically
    return XeroSDKClient(token, xero_service)

