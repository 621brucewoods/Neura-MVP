"""
Xero Integration Router
API endpoints for Xero OAuth 2.0 flow and data fetching.
"""

from datetime import date, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import get_current_user
from app.database import get_async_session
from app.integrations.xero.oauth import XeroOAuth, XeroOAuthError, xero_oauth
from app.integrations.xero.data_fetcher import XeroDataFetcher
from app.integrations.xero.exceptions import XeroDataFetchError
from app.integrations.xero.sdk_client import create_xero_sdk_client, XeroSDKClientError
from app.integrations.xero.cache_service import CacheService
from app.integrations.xero.schemas import (
    XeroAuthURLResponse,
    XeroCallbackResponse,
    XeroConnectionStatus,
    XeroDisconnectResponse,
    XeroRefreshResponse,
    XeroSyncResponse,
    XeroTokenData,
)
from app.integrations.xero.service import XeroService
from app.integrations.xero.state_store import oauth_state_store
from app.models.organization import Organization
from app.models.user import User
from app.models.xero_token import XeroConnectionStatus as TokenStatusEnum


router = APIRouter(prefix="/integrations/xero", tags=["Xero Integration"])


# =============================================================================
# Dependencies
# =============================================================================

async def get_xero_service(
    db: AsyncSession = Depends(get_async_session),
) -> XeroService:
    """Dependency to get XeroService instance."""
    return XeroService(db)


# =============================================================================
# Endpoints
# =============================================================================

@router.get(
    "/connect",
    response_model=XeroAuthURLResponse,
    summary="Start Xero OAuth flow",
    description="Generate authorization URL to redirect user to Xero for consent.",
)
async def connect_xero(
    current_user: User = Depends(get_current_user),
) -> XeroAuthURLResponse:
    """
    Initiate Xero OAuth 2.0 authorization flow.
    
    Returns authorization URL and state token.
    Frontend should redirect user to authorization_url.
    """
    # Ensure user has an organization
    if not current_user.organization:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="User must have an organization to connect Xero",
        )
    
    # Generate state for CSRF protection
    state = XeroOAuth.generate_state()
    
    # Store state → organization mapping for callback
    oauth_state_store.save_state(state, current_user.organization.id)
    
    # Generate authorization URL
    authorization_url = xero_oauth.get_authorization_url(state)
    
    return XeroAuthURLResponse(
        authorization_url=authorization_url,
        state=state,
    )


@router.get(
    "/callback",
    response_model=XeroCallbackResponse,
    summary="Handle Xero OAuth callback",
    description="Process Xero OAuth callback, exchange code for tokens.",
)
async def xero_callback(
    code: str = Query(..., description="Authorization code from Xero"),
    state: str = Query(..., description="State token for CSRF validation"),
    db: AsyncSession = Depends(get_async_session),
) -> XeroCallbackResponse:
    """
    Handle OAuth 2.0 callback from Xero.
    
    This endpoint is called by Xero's redirect (no auth required).
    The state parameter identifies the organization.
    """
    # Look up organization by state (and consume it - one-time use)
    organization_id = oauth_state_store.consume_state(state)
    
    if not organization_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid or expired state token. Please restart the connection flow.",
        )
    
    # Get organization from database
    result = await db.execute(
        select(Organization).where(Organization.id == organization_id)
    )
    organization = result.scalar_one_or_none()
    
    if not organization:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Organization not found",
        )
    
    xero_service = XeroService(db)
    
    try:
        # Exchange code for tokens
        token_response = await xero_oauth.exchange_code_for_tokens(code)
        
        # Get Xero tenant ID (required for API calls)
        connections = await xero_oauth.get_connections(token_response["access_token"])
        
        if not connections:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="No Xero organizations authorized",
            )
        
        # Use first connection (user can have multiple orgs in Xero)
        # For MVP, we support one Xero org per user org
        xero_connection = connections[0]
        xero_tenant_id = xero_connection["tenantId"]
        xero_org_name = xero_connection.get("tenantName")
        
        # Save tokens to database
        await xero_service.save_tokens_from_callback(
            organization_id=organization.id,
            token_response=token_response,
            xero_tenant_id=xero_tenant_id,
        )
        
        return XeroCallbackResponse(
            success=True,
            message="Xero connected successfully",
            xero_tenant_id=xero_tenant_id,
            organization_name=xero_org_name,
        )
        
    except XeroOAuthError:
        # Global exception handler will sanitize this
        raise


@router.get(
    "/status",
    response_model=XeroConnectionStatus,
    summary="Get Xero connection status",
    description="Check if Xero is connected and get connection details. Validates token with Xero API.",
)
async def get_xero_status(
    current_user: User = Depends(get_current_user),
    xero_service: XeroService = Depends(get_xero_service),
) -> XeroConnectionStatus:
    """
    Get current Xero connection status for the user's organization.
    
    Actually validates the token with Xero API to ensure accuracy.
    """
    if not current_user.organization:
        return XeroConnectionStatus(
            is_connected=False,
            status="no_organization",
            needs_refresh=False,
            needs_reconnect=False,
        )
    
    token = await xero_service.get_token_by_organization(
        current_user.organization.id
    )
    
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
    
    # Validate token by attempting a refresh or checking connections
    # This ensures we return accurate status, not just database state
    try:
        # Try to refresh the token to validate it's still valid
        # This is the most reliable way to check if refresh_token is valid
        token_response = await xero_oauth.refresh_tokens(token.refresh_token)
        
        # Refresh succeeded - token is valid
        # Update token in database with new values
        token_data = XeroTokenData(
            access_token=token_response["access_token"],
            refresh_token=token_response["refresh_token"],
            expires_at=XeroOAuth.calculate_expiry(token_response["expires_in"]),
            xero_tenant_id=token.xero_tenant_id,
            scope=token_response.get("scope", token.scope),
            id_token=token_response.get("id_token"),
        )
        updated_token = await xero_service.update_token(token, token_data)
        
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
        # Check if it's invalid_grant (token expired/revoked) vs other error
        if e.error_code == "invalid_grant":
            # Mark token as invalid in database
            token.status = TokenStatusEnum.REFRESH_FAILED.value
            token.last_error = e.message
            await xero_service.db.commit()
            
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
            # Other error (network, etc.) - don't mark as invalid, just return current status
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


@router.post(
    "/disconnect",
    response_model=XeroDisconnectResponse,
    summary="Disconnect Xero",
    description="Revoke tokens and remove Xero connection.",
)
async def disconnect_xero(
    current_user: User = Depends(get_current_user),
    xero_service: XeroService = Depends(get_xero_service),
) -> XeroDisconnectResponse:
    """
    Disconnect Xero integration.
    
    Revokes tokens at Xero and removes local records.
    """
    if not current_user.organization:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="User has no organization",
        )
    
    success = await xero_service.disconnect(current_user.organization.id)
    
    if not success:
        return XeroDisconnectResponse(
            success=False,
            message="No Xero connection to disconnect",
        )
    
    return XeroDisconnectResponse(
        success=True,
        message="Xero disconnected successfully",
    )


@router.post(
    "/refresh",
    response_model=XeroRefreshResponse,
    summary="Manually refresh Xero tokens",
    description="Force refresh of Xero access tokens.",
)
async def refresh_xero_tokens(
    current_user: User = Depends(get_current_user),
    xero_service: XeroService = Depends(get_xero_service),
) -> XeroRefreshResponse:
    """
    Manually refresh Xero tokens.
    
    Normally tokens are refreshed automatically before API calls.
    This endpoint allows manual refresh if needed.
    """
    if not current_user.organization:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="User has no organization",
        )
    
    token = await xero_service.get_token_by_organization(
        current_user.organization.id
    )
    
    if not token:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No Xero connection found",
        )
    
    try:
        # Force refresh
        token_response = await xero_oauth.refresh_tokens(token.refresh_token)
        
        # Update stored tokens
        token_data = XeroTokenData(
            access_token=token_response["access_token"],
            refresh_token=token_response["refresh_token"],
            expires_at=XeroOAuth.calculate_expiry(token_response["expires_in"]),
            xero_tenant_id=token.xero_tenant_id,
            scope=token_response.get("scope", token.scope),
            id_token=token_response.get("id_token"),
        )
        
        updated_token = await xero_service.update_token(token, token_data)
        
        return XeroRefreshResponse(
            success=True,
            message="Tokens refreshed successfully",
            expires_at=updated_token.expires_at,
        )
        
    except XeroOAuthError:
        # Global exception handler will sanitize this
        raise


@router.get(
    "/sync",
    response_model=XeroSyncResponse,
    summary="Sync financial data from Xero",
    description="Fetch and return financial data from Xero API using official SDK. Uses cache when available.",
)
async def sync_xero_data(
    current_user: User = Depends(get_current_user),
    start_date: date = Query(..., description="Start date for P&L period (YYYY-MM-DD)"),
    end_date: date = Query(..., description="End date for P&L period (YYYY-MM-DD)"),
    force_refresh: bool = Query(
        default=False,
        description="If true, bypass cache and fetch fresh data from Xero"
    ),
    db: AsyncSession = Depends(get_async_session),
) -> XeroSyncResponse:
    """
    Fetch financial data from Xero API using official SDK.
    
    This endpoint:
    - Uses cache when available (exact date range match only, unless force_refresh=true)
    - Fetches Balance Sheets for current and prior dates
    - Fetches P&L report for specified date range
    - Fetches Accounts Receivable invoices (for leading indicators)
    - Fetches Accounts Payable invoices (for leading indicators)
    - Fetches Trial Balance for end_date (deterministic P&L via AccountType)
    
    Returns normalized data structure ready for cash runway calculations.
    """
    if not current_user.organization:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="User has no organization",
        )
    
    # Validate date range
    if start_date >= end_date:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="start_date must be before end_date",
        )
    
    today = date.today()
    if end_date > today:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="end_date cannot be in the future",
        )
    
    try:
        # Create cache service
        cache_service = CacheService(db)
        
        # Create SDK client (handles token validation and refresh)
        sdk_client = await create_xero_sdk_client(
            organization_id=current_user.organization.id,
            db=db,
        )
        
        # Create data fetcher with SDK client, cache service, and DB session
        data_fetcher = XeroDataFetcher(sdk_client, cache_service=cache_service, db=db)
        
        # Fetch all data (with caching)
        data = await data_fetcher.fetch_all_data(
            organization_id=current_user.organization.id,
            start_date=start_date,
            end_date=end_date,
            force_refresh=force_refresh,
        )
        
        # Note: Token updates are flushed automatically by fetchers
        # FastAPI will auto-commit everything at the end
        
        # Calculate period description
        days_diff = (end_date - start_date).days
        period_description = f"{days_diff} days" if days_diff < 30 else f"{days_diff // 30} months"
        
        return XeroSyncResponse(
            success=True,
            message=f"Successfully fetched financial data for period: {start_date} to {end_date} ({period_description})",
            data=data,
            fetched_at=data.get("fetched_at", ""),
        )
        
    except XeroSDKClientError:
        # Global exception handler will sanitize this
        raise
    except XeroDataFetchError:
        # Global exception handler will sanitize this
        raise
    except Exception:
        # Global exception handler will sanitize this
        raise
