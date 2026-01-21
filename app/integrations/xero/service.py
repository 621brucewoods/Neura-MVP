"""
Xero Token Service
Database operations for Xero OAuth tokens.
"""

from datetime import datetime, timezone
from typing import Optional
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.integrations.xero.oauth import XeroOAuth, XeroOAuthError, xero_oauth
from app.integrations.xero.schemas import XeroConnectionStatus, XeroTokenData
from app.models.xero_token import XeroConnectionStatus as TokenStatus, XeroToken


class XeroService:
    """
    Service for Xero token management.
    
    Handles:
    - Token storage and retrieval
    - Token refresh with automatic retry
    - Connection status management
    - Token revocation and cleanup
    """
    
    def __init__(self, db: AsyncSession):
        self.db = db
        self.oauth = xero_oauth
    
    async def get_token_by_organization(
        self, organization_id: UUID
    ) -> Optional[XeroToken]:
        """
        Get Xero token for an organization.
        
        Args:
            organization_id: Organization UUID
            
        Returns:
            XeroToken if exists, None otherwise
        """
        result = await self.db.execute(
            select(XeroToken).where(XeroToken.organization_id == organization_id)
        )
        return result.scalar_one_or_none()
    
    async def create_token(
        self,
        organization_id: UUID,
        token_data: XeroTokenData,
    ) -> XeroToken:
        """
        Create a new Xero token record.
        
        Args:
            organization_id: Organization UUID
            token_data: Token data from OAuth exchange
            
        Returns:
            Created XeroToken
        """
        token = XeroToken(
            organization_id=organization_id,
            xero_tenant_id=token_data.xero_tenant_id,
            access_token=token_data.access_token,
            refresh_token=token_data.refresh_token,
            id_token=token_data.id_token,
            token_type=token_data.token_type,
            scope=token_data.scope,
            expires_at=token_data.expires_at,
            status=TokenStatus.ACTIVE.value,
            last_refreshed_at=datetime.now(timezone.utc),
        )
        
        self.db.add(token)
        await self.db.commit()
        await self.db.refresh(token)
        
        return token
    
    async def update_token(
        self,
        token: XeroToken,
        token_data: XeroTokenData,
    ) -> XeroToken:
        """
        Update existing token with new values.
        
        Used after token refresh (Xero rotates both tokens).
        
        Args:
            token: Existing XeroToken to update
            token_data: New token data
            
        Returns:
            Updated XeroToken
        """
        token.access_token = token_data.access_token
        token.refresh_token = token_data.refresh_token
        token.expires_at = token_data.expires_at
        token.scope = token_data.scope
        token.status = TokenStatus.ACTIVE.value
        token.last_refreshed_at = datetime.now(timezone.utc)
        token.last_error = None
        
        if token_data.id_token:
            token.id_token = token_data.id_token
        
        await self.db.commit()
        
        # Re-query the token to get a fresh instance after commit
        # This avoids issues with detached instances after commit
        result = await self.db.execute(
            select(XeroToken).where(XeroToken.id == token.id)
        )
        updated_token = result.scalar_one_or_none()
        
        # If query fails (shouldn't happen), return the original token
        # The attributes are already updated, so this is safe
        return updated_token if updated_token else token
    
    async def refresh_token_if_needed(
        self, token: XeroToken
    ) -> XeroToken:
        """
        Refresh token if it's expired or expiring soon.
        
        Args:
            token: XeroToken to check/refresh
        
        Returns:
            Refreshed token (or original if refresh not needed)
        
        Raises:
            XeroOAuthError: If refresh fails
        """
        if not token.needs_refresh:
            return token
        
        try:
            # Refresh via Xero API
            token_response = await self.oauth.refresh_tokens(token.refresh_token)
            
            # Convert scope to space-separated string if it's a list
            scope_value = token_response.get("scope", token.scope)
            if isinstance(scope_value, list):
                scope_str = " ".join(scope_value)
            else:
                scope_str = str(scope_value) if scope_value else ""
            
            # Update stored token
            token_data = XeroTokenData(
                access_token=token_response["access_token"],
                refresh_token=token_response["refresh_token"],
                expires_at=XeroOAuth.calculate_expiry(token_response["expires_in"]),
                xero_tenant_id=token.xero_tenant_id,
                scope=scope_str,
                id_token=token_response.get("id_token"),
            )
            
            return await self.update_token(token, token_data)
            
        except XeroOAuthError as e:
            # Mark token as failed
            token.status = TokenStatus.REFRESH_FAILED.value
            token.last_error = e.message
            await self.db.commit()
            raise
    
    async def get_valid_access_token(
        self, organization_id: UUID
    ) -> Optional[str]:
        """
        Get a valid access token, refreshing if necessary.
        
        Convenience method for API calls.
        
        Args:
            organization_id: Organization UUID
            
        Returns:
            Valid access token string, or None if no connection
            
        Raises:
            XeroOAuthError: If refresh fails
        """
        token = await self.get_token_by_organization(organization_id)
        
        if not token:
            return None
        
        if not token.is_active:
            return None
        
        # Refresh if needed
        token = await self.refresh_token_if_needed(token)
        
        # Track API call time
        token.last_api_call_at = datetime.now(timezone.utc)
        await self.db.commit()
        
        return token.access_token
    
    async def disconnect(self, organization_id: UUID) -> bool:
        """
        Disconnect Xero (revoke tokens and delete record).
        
        Args:
            organization_id: Organization UUID
            
        Returns:
            True if successful, False if no connection existed
        """
        token = await self.get_token_by_organization(organization_id)
        
        if not token:
            return False
        
        # Attempt to revoke tokens at Xero (best effort)
        try:
            await self.oauth.revoke_token(token.refresh_token)
        except XeroOAuthError:
            pass  # Continue even if revocation fails
        
        # Delete local record
        await self.db.delete(token)
        await self.db.commit()
        
        return True
    
    async def mark_token_expired(self, token: XeroToken) -> None:
        """
        Mark token as expired (e.g., when refresh token expires).
        
        Args:
            token: XeroToken to mark
        """
        token.status = TokenStatus.EXPIRED.value
        await self.db.commit()
    
    async def save_tokens_from_callback(
        self,
        organization_id: UUID,
        token_response: dict,
        xero_tenant_id: str,
        xero_org_name: str | None = None,
    ) -> XeroToken:
        """
        Save tokens received from OAuth callback.
        
        Creates new token or updates existing one.
        
        Args:
            organization_id: Organization UUID
            token_response: Raw response from Xero token endpoint
            xero_tenant_id: Xero tenant ID from connections endpoint
            xero_org_name: Xero organization name (optional)
            
        Returns:
            Created or updated XeroToken
        """
        # Convert scope to space-separated string if it's a list
        scope_value = token_response.get("scope", "")
        if isinstance(scope_value, list):
            scope_str = " ".join(scope_value)
        else:
            scope_str = str(scope_value) if scope_value else ""
        
        token_data = XeroTokenData(
            access_token=token_response["access_token"],
            refresh_token=token_response["refresh_token"],
            expires_at=XeroOAuth.calculate_expiry(token_response["expires_in"]),
            xero_tenant_id=xero_tenant_id,
            token_type=token_response.get("token_type", "Bearer"),
            scope=scope_str,
            id_token=token_response.get("id_token"),
        )
        
        # Check if token already exists
        existing_token = await self.get_token_by_organization(organization_id)
        
        if existing_token:
            # Update existing (reconnecting)
            existing_token.xero_tenant_id = xero_tenant_id
            if xero_org_name:
                existing_token.xero_org_name = xero_org_name
            return await self.update_token(existing_token, token_data)
        else:
            # Create new
            token = await self.create_token(organization_id, token_data)
            if xero_org_name:
                token.xero_org_name = xero_org_name
                await self.db.commit()
            return token
    
    async def get_connection_status(self, organization_id: UUID) -> XeroConnectionStatus:
        """
        Get and validate Xero connection status in real-time.
        
        Validates token by attempting refresh with Xero API to ensure accuracy.
        Updates database if token is valid.
        
        Args:
            organization_id: Organization UUID
            
        Returns:
            XeroConnectionStatus with validated connection information
        """
        token = await self.get_token_by_organization(organization_id)
        
        if not token:
            return XeroConnectionStatus(
                is_connected=False,
                status="disconnected",
                needs_refresh=False,
                needs_reconnect=False,
            )
        
        # If explicitly disconnected, return immediately
        if token.status == "disconnected":
            return XeroConnectionStatus(
                is_connected=False,
                status="disconnected",
                xero_tenant_id=token.xero_tenant_id,
                connected_at=token.created_at,
                expires_at=token.expires_at,
                last_refreshed_at=token.last_refreshed_at,
                needs_refresh=False,
                needs_reconnect=True,
                error_message="Xero connection was disconnected. Please reconnect.",
            )
        
        # Validate token by attempting refresh (most reliable way to check validity)
        try:
            token_response = await self.oauth.refresh_tokens(token.refresh_token)
            
            # Refresh succeeded - token is valid, update database
            scope_value = token_response.get("scope", token.scope)
            if isinstance(scope_value, list):
                scope_str = " ".join(scope_value)
            else:
                scope_str = str(scope_value) if scope_value else ""
            
            token_data = XeroTokenData(
                access_token=token_response["access_token"],
                refresh_token=token_response["refresh_token"],
                expires_at=XeroOAuth.calculate_expiry(token_response["expires_in"]),
                xero_tenant_id=token.xero_tenant_id,
                scope=scope_str,
                id_token=token_response.get("id_token"),
            )
            updated_token = await self.update_token(token, token_data)
            
            return XeroConnectionStatus(
                is_connected=True,
                status="active",
                xero_tenant_id=updated_token.xero_tenant_id,
                connected_at=updated_token.created_at,
                expires_at=updated_token.expires_at,
                last_refreshed_at=updated_token.last_refreshed_at,
                needs_refresh=updated_token.needs_refresh,
                needs_reconnect=False,
            )
            
        except XeroOAuthError as e:
            # Refresh failed - token is invalid
            if e.error_code == "invalid_grant":
                # Mark token as invalid in database
                token.status = TokenStatus.REFRESH_FAILED.value
                token.last_error = e.message
                await self.db.commit()
                
                return XeroConnectionStatus(
                    is_connected=False,
                    status="invalid_token",
                    xero_tenant_id=token.xero_tenant_id,
                    connected_at=token.created_at,
                    expires_at=token.expires_at,
                    last_refreshed_at=token.last_refreshed_at,
                    needs_refresh=False,
                    needs_reconnect=True,
                    error_message="Xero connection token is invalid. Please reconnect your Xero account.",
                )
            else:
                # Other error (network, etc.) - don't mark as invalid, return current status
                return XeroConnectionStatus(
                    is_connected=token.is_active,
                    status=token.status,
                    xero_tenant_id=token.xero_tenant_id,
                    connected_at=token.created_at,
                    expires_at=token.expires_at,
                    last_refreshed_at=token.last_refreshed_at,
                    needs_refresh=token.needs_refresh,
                    needs_reconnect=False,
                    error_message=f"Unable to validate connection: {e.message}",
                )

