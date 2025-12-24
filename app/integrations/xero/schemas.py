"""
Xero Integration Schemas
Request/response models for Xero OAuth endpoints.
"""

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


# =============================================================================
# Response Models
# =============================================================================

class XeroAuthURLResponse(BaseModel):
    """Response containing Xero authorization URL."""
    
    authorization_url: str = Field(
        ...,
        description="URL to redirect user to for Xero authorization"
    )
    state: str = Field(
        ...,
        description="State token for CSRF protection (store securely)"
    )


class XeroConnectionStatus(BaseModel):
    """Xero connection status for an organization."""
    
    is_connected: bool = Field(
        ...,
        description="Whether Xero is connected"
    )
    status: str = Field(
        ...,
        description="Connection status (active, disconnected, expired, refresh_failed)"
    )
    xero_tenant_id: Optional[str] = Field(
        None,
        description="Xero organization identifier"
    )
    connected_at: Optional[datetime] = Field(
        None,
        description="When the connection was established"
    )
    expires_at: Optional[datetime] = Field(
        None,
        description="When the current access token expires"
    )
    last_refreshed_at: Optional[datetime] = Field(
        None,
        description="When tokens were last refreshed"
    )
    needs_refresh: bool = Field(
        False,
        description="Whether token needs refresh soon"
    )


class XeroCallbackResponse(BaseModel):
    """Response after successful OAuth callback."""
    
    success: bool = Field(
        ...,
        description="Whether connection was successful"
    )
    message: str = Field(
        ...,
        description="Status message"
    )
    xero_tenant_id: str = Field(
        ...,
        description="Connected Xero organization ID"
    )
    organization_name: Optional[str] = Field(
        None,
        description="Xero organization name"
    )


class XeroDisconnectResponse(BaseModel):
    """Response after disconnecting Xero."""
    
    success: bool = Field(
        ...,
        description="Whether disconnection was successful"
    )
    message: str = Field(
        ...,
        description="Status message"
    )


class XeroRefreshResponse(BaseModel):
    """Response after manual token refresh."""
    
    success: bool = Field(
        ...,
        description="Whether refresh was successful"
    )
    message: str = Field(
        ...,
        description="Status message"
    )
    expires_at: datetime = Field(
        ...,
        description="New token expiry time"
    )


# =============================================================================
# Internal Models (for service layer)
# =============================================================================

class XeroTokenData(BaseModel):
    """Internal model for token storage."""
    
    access_token: str
    refresh_token: str
    expires_at: datetime
    xero_tenant_id: str
    token_type: str = "Bearer"
    scope: str
    id_token: Optional[str] = None

    class Config:
        from_attributes = True


class XeroSyncResponse(BaseModel):
    """Response from data sync endpoint."""
    
    success: bool = Field(
        ...,
        description="Whether sync was successful"
    )
    message: str = Field(
        ...,
        description="Status message"
    )
    data: dict = Field(
        ...,
        description="Fetched financial data from Xero"
    )
    fetched_at: str = Field(
        ...,
        description="ISO timestamp when data was fetched"
    )

