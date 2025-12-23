"""
Xero OAuth 2.0 Utilities
Handles authorization URL generation, token exchange, and refresh.
"""

import base64
import secrets
from datetime import datetime, timedelta, timezone
from typing import Optional
from urllib.parse import urlencode

import httpx

from app.config import settings


class XeroOAuthError(Exception):
    """Custom exception for Xero OAuth errors."""
    
    def __init__(self, message: str, error_code: Optional[str] = None):
        self.message = message
        self.error_code = error_code
        super().__init__(self.message)


class XeroOAuth:
    """
    Xero OAuth 2.0 client.
    
    Handles:
    - Authorization URL generation
    - Authorization code exchange for tokens
    - Token refresh
    - Token revocation
    - Connection management
    """
    
    # Xero OAuth 2.0 endpoints
    AUTHORIZATION_URL = "https://login.xero.com/identity/connect/authorize"
    TOKEN_URL = "https://identity.xero.com/connect/token"
    CONNECTIONS_URL = "https://api.xero.com/connections"
    REVOCATION_URL = "https://identity.xero.com/connect/revocation"
    
    def __init__(self):
        self.client_id = settings.xero_client_id
        self.client_secret = settings.xero_client_secret
        self.redirect_uri = settings.xero_redirect_uri
        self.scopes = settings.xero_scopes
    
    @staticmethod
    def generate_state() -> str:
        """Generate a cryptographically secure state parameter."""
        return secrets.token_urlsafe(32)
    
    def get_authorization_url(self, state: str) -> str:
        """
        Generate the Xero authorization URL.
        
        Args:
            state: CSRF protection token (store in session/db)
            
        Returns:
            Full authorization URL to redirect user to
        """
        params = {
            "response_type": "code",
            "client_id": self.client_id,
            "redirect_uri": self.redirect_uri,
            "scope": self.scopes,
            "state": state,
        }
        # Use urlencode for proper URL encoding of special characters
        query_string = urlencode(params)
        return f"{self.AUTHORIZATION_URL}?{query_string}"
    
    def _get_auth_header(self) -> str:
        """Generate Basic auth header for token requests."""
        credentials = f"{self.client_id}:{self.client_secret}"
        encoded = base64.b64encode(credentials.encode()).decode()
        return f"Basic {encoded}"
    
    async def exchange_code_for_tokens(self, code: str) -> dict:
        """
        Exchange authorization code for access and refresh tokens.
        
        Args:
            code: Authorization code from Xero callback
            
        Returns:
            Token response containing:
            - access_token
            - refresh_token
            - expires_in (seconds)
            - token_type
            - scope
            - id_token (optional)
            
        Raises:
            XeroOAuthError: If token exchange fails
        """
        async with httpx.AsyncClient() as client:
            response = await client.post(
                self.TOKEN_URL,
                headers={
                    "Authorization": self._get_auth_header(),
                    "Content-Type": "application/x-www-form-urlencoded",
                },
                data={
                    "grant_type": "authorization_code",
                    "code": code,
                    "redirect_uri": self.redirect_uri,
                },
            )
            
            if response.status_code != 200:
                error_data = response.json() if response.content else {}
                raise XeroOAuthError(
                    message=error_data.get("error_description", "Token exchange failed"),
                    error_code=error_data.get("error", "unknown_error"),
                )
            
            return response.json()
    
    async def refresh_tokens(self, refresh_token: str) -> dict:
        """
        Refresh access token using refresh token.
        
        Xero rotates both tokens on each refresh (security feature).
        
        Args:
            refresh_token: Current refresh token
            
        Returns:
            New token response with fresh access and refresh tokens
            
        Raises:
            XeroOAuthError: If refresh fails
        """
        async with httpx.AsyncClient() as client:
            response = await client.post(
                self.TOKEN_URL,
                headers={
                    "Authorization": self._get_auth_header(),
                    "Content-Type": "application/x-www-form-urlencoded",
                },
                data={
                    "grant_type": "refresh_token",
                    "refresh_token": refresh_token,
                },
            )
            
            if response.status_code != 200:
                error_data = response.json() if response.content else {}
                raise XeroOAuthError(
                    message=error_data.get("error_description", "Token refresh failed"),
                    error_code=error_data.get("error", "unknown_error"),
                )
            
            return response.json()
    
    async def get_connections(self, access_token: str) -> list[dict]:
        """
        Get list of authorized Xero tenants (organizations).
        
        After OAuth, user may have authorized access to multiple orgs.
        We need the tenant_id to make API calls.
        
        Args:
            access_token: Valid access token
            
        Returns:
            List of connection objects with tenant IDs
            
        Raises:
            XeroOAuthError: If request fails
        """
        async with httpx.AsyncClient() as client:
            response = await client.get(
                self.CONNECTIONS_URL,
                headers={
                    "Authorization": f"Bearer {access_token}",
                    "Content-Type": "application/json",
                },
            )
            
            if response.status_code != 200:
                raise XeroOAuthError(
                    message="Failed to fetch Xero connections",
                    error_code="connection_error",
                )
            
            return response.json()
    
    async def revoke_token(self, token: str) -> bool:
        """
        Revoke a token (access or refresh).
        
        Args:
            token: Token to revoke
            
        Returns:
            True if successful
            
        Raises:
            XeroOAuthError: If revocation fails
        """
        async with httpx.AsyncClient() as client:
            response = await client.post(
                self.REVOCATION_URL,
                headers={
                    "Authorization": self._get_auth_header(),
                    "Content-Type": "application/x-www-form-urlencoded",
                },
                data={"token": token},
            )
            
            # Xero returns 200 even if token is already revoked
            if response.status_code not in (200, 204):
                raise XeroOAuthError(
                    message="Token revocation failed",
                    error_code="revocation_error",
                )
            
            return True
    
    @staticmethod
    def calculate_expiry(expires_in: int) -> datetime:
        """
        Calculate token expiry datetime from expires_in seconds.
        
        Args:
            expires_in: Token lifetime in seconds
            
        Returns:
            Timezone-aware expiry datetime
        """
        return datetime.now(timezone.utc) + timedelta(seconds=expires_in)


# Singleton instance for convenience
xero_oauth = XeroOAuth()

