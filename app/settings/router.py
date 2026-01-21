"""
Settings Router
API endpoints for user settings and account management.
"""

import logging
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from fastapi import APIRouter, Depends, HTTPException

from app.auth.dependencies import get_current_user
from app.database import get_async_session
from app.integrations.xero.schemas import XeroConnectionStatus
from app.integrations.xero.service import XeroService
from app.models.calculated_metrics import CalculatedMetrics
from app.models.user import User
from app.settings.schemas import SettingsResponse, IntegrationStatus, UpdateOrganizationRequest

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/settings", tags=["Settings"])


@router.get(
    "/",
    response_model=SettingsResponse,
    summary="Get user settings",
    description="Get aggregated settings information including account details, integration status, and sync information.",
)
async def get_settings(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_session),
) -> SettingsResponse:
    """
    Get user settings and account information.
    
    Aggregates:
    - User email
    - Xero integration connection status (validated in real-time with Xero API)
    - Last sync/calculation time
    - Support link (placeholder for MVP)
    """
    xero_service = XeroService(db)
    org = current_user.organization
    
    # Get validated Xero connection status (uses shared validation logic)
    if not org:
        xero_integration = IntegrationStatus(
            is_connected=False,
            status="no_organization",
            connected_at=None,
            last_synced_at=None,
            needs_reconnect=False,
            xero_org_name=None,
        )
        org_name = "Unknown"
    else:
        xero_status: XeroConnectionStatus = await xero_service.get_connection_status(org.id)
        xero_org_name = org.xero_token.xero_org_name if org.xero_token else None
        
        xero_integration = IntegrationStatus(
            is_connected=xero_status.is_connected,
            status=xero_status.status,
            connected_at=xero_status.connected_at,
            last_synced_at=xero_status.last_refreshed_at,
            needs_reconnect=xero_status.needs_reconnect,
            xero_org_name=xero_org_name,
        )
        org_name = org.name
    
    # Get last sync time from calculated metrics
    last_sync_time = None
    if org:
        stmt = select(CalculatedMetrics).where(CalculatedMetrics.organization_id == org.id)
        result = await db.execute(stmt)
        calc_metrics = result.scalar_one_or_none()
        if calc_metrics and calc_metrics.calculated_at:
            last_sync_time = calc_metrics.calculated_at
    
    return SettingsResponse(
        email=current_user.email,
        organization_name=org_name,
        xero_integration=xero_integration,
        last_sync_time=last_sync_time,
        support_link=None,
    )


@router.patch(
    "/organization",
    response_model=SettingsResponse,
    summary="Update organization",
)
async def update_organization(
    request: UpdateOrganizationRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_session),
) -> SettingsResponse:
    """Update the organization name."""
    if not current_user.organization:
        raise HTTPException(status_code=400, detail="No organization found")
    
    current_user.organization.name = request.name
    await db.commit()
    
    # Return updated settings
    return await get_settings(current_user, db)

