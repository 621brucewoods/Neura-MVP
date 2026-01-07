"""
Settings Router
API endpoints for user settings and account management.
"""

import logging
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from fastapi import APIRouter, Depends

from app.auth.dependencies import get_current_user
from app.database import get_async_session
from app.integrations.xero.schemas import XeroConnectionStatus
from app.integrations.xero.service import XeroService
from app.models.calculated_metrics import CalculatedMetrics
from app.models.user import User
from app.settings.schemas import SettingsResponse, IntegrationStatus

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
    
    # Get validated Xero connection status (uses shared validation logic)
    if not current_user.organization:
        xero_status = None
        xero_integration = IntegrationStatus(
            is_connected=False,
            status="no_organization",
            connected_at=None,
            last_synced_at=None,
            needs_reconnect=False,
        )
    else:
        xero_status: XeroConnectionStatus = await xero_service.get_connection_status(
            current_user.organization.id
        )
        
        # Convert XeroConnectionStatus to IntegrationStatus
        xero_integration = IntegrationStatus(
            is_connected=xero_status.is_connected,
            status=xero_status.status,
            connected_at=xero_status.connected_at,
            last_synced_at=xero_status.last_refreshed_at,
            needs_reconnect=xero_status.needs_reconnect,
        )
    
    # Get last sync time from calculated metrics
    last_sync_time = None
    if current_user.organization:
        stmt = select(CalculatedMetrics).where(
            CalculatedMetrics.organization_id == current_user.organization.id
        )
        result = await db.execute(stmt)
        calc_metrics = result.scalar_one_or_none()
        if calc_metrics and calc_metrics.calculated_at:
            last_sync_time = calc_metrics.calculated_at
    
    return SettingsResponse(
        email=current_user.email,
        xero_integration=xero_integration,
        last_sync_time=last_sync_time,
        support_link=None,  # Placeholder for MVP
    )

