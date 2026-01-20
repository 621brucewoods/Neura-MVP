"""
Admin Router
API endpoints for platform administration.
"""

import logging
from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.auth.dependencies import AdminUser
from app.database.connection import get_async_session
from app.models.organization import Organization, SyncStatus
from app.admin.schemas import (
    AdminDashboardResponse,
    AdminDashboardStats,
    OrganizationListResponse,
    OrganizationSummary,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/admin", tags=["Admin"])


def _build_org_summary(org: Organization) -> OrganizationSummary:
    """Build OrganizationSummary from Organization model (operational data only)."""
    # Only get last sync time - no financial data
    last_sync_at = None
    if org.calculated_metrics and org.calculated_metrics.calculated_at:
        last_sync_at = org.calculated_metrics.calculated_at.isoformat()
    
    return OrganizationSummary(
        id=str(org.id),
        name=org.name,
        user_email=org.user.email if org.user else "Unknown",
        created_at=org.created_at.isoformat() if org.created_at else "",
        sync_status=org.sync_status.value if org.sync_status else "IDLE",
        sync_step=org.sync_step.value if org.sync_step else None,
        last_sync_error=org.last_sync_error,
        has_xero_connection=org.has_xero_connection,
        last_sync_at=last_sync_at,
    )


@router.get(
    "/dashboard",
    response_model=AdminDashboardResponse,
    summary="Get admin dashboard",
    description="Get complete admin dashboard with stats and organization list.",
)
async def get_admin_dashboard(
    admin_user: AdminUser,
    db: AsyncSession = Depends(get_async_session),
) -> AdminDashboardResponse:
    """
    Get complete admin dashboard data.
    
    Includes:
    - Platform statistics
    - All organizations with their status and metrics
    """
    # Fetch all organizations with relationships
    stmt = (
        select(Organization)
        .options(
            selectinload(Organization.user),
            selectinload(Organization.xero_token),
            selectinload(Organization.calculated_metrics),
        )
        .order_by(Organization.created_at.desc())
    )
    result = await db.execute(stmt)
    organizations = result.scalars().all()
    
    # Build organization summaries
    org_summaries = [_build_org_summary(org) for org in organizations]
    
    # Calculate stats (operational only - no financial data)
    total_organizations = len(organizations)
    active_xero_connections = sum(1 for org in organizations if org.has_xero_connection)
    syncs_in_progress = sum(1 for org in organizations if org.sync_status == SyncStatus.IN_PROGRESS)
    failed_syncs = sum(1 for org in organizations if org.sync_status == SyncStatus.FAILED)
    
    stats = AdminDashboardStats(
        total_organizations=total_organizations,
        active_xero_connections=active_xero_connections,
        syncs_in_progress=syncs_in_progress,
        failed_syncs=failed_syncs,
    )
    
    return AdminDashboardResponse(
        stats=stats,
        organizations=org_summaries,
    )


@router.get(
    "/organizations",
    response_model=OrganizationListResponse,
    summary="List all organizations",
    description="Get paginated list of all organizations with their status.",
)
async def list_organizations(
    admin_user: AdminUser,
    limit: int = Query(100, ge=1, le=500, description="Pagination limit"),
    offset: int = Query(0, ge=0, description="Pagination offset"),
    sync_status: Optional[str] = Query(None, description="Filter by sync status"),
    has_xero: Optional[bool] = Query(None, description="Filter by Xero connection"),
    db: AsyncSession = Depends(get_async_session),
) -> OrganizationListResponse:
    """
    Get paginated list of all organizations.
    
    Supports filtering by:
    - sync_status: IDLE, IN_PROGRESS, COMPLETED, FAILED
    - has_xero: true/false
    """
    # Build base query
    stmt = (
        select(Organization)
        .options(
            selectinload(Organization.user),
            selectinload(Organization.xero_token),
            selectinload(Organization.calculated_metrics),
        )
    )
    
    # Apply filters
    if sync_status:
        try:
            status_enum = SyncStatus(sync_status.upper())
            stmt = stmt.where(Organization.sync_status == status_enum)
        except ValueError:
            pass  # Invalid status, ignore filter
    
    # Get total count
    count_stmt = select(func.count()).select_from(stmt.subquery())
    total_result = await db.execute(count_stmt)
    total = total_result.scalar() or 0
    
    # Apply pagination and ordering
    stmt = stmt.order_by(Organization.created_at.desc())
    stmt = stmt.limit(limit).offset(offset)
    
    # Execute query
    result = await db.execute(stmt)
    organizations = result.scalars().all()
    
    # Filter by Xero connection in Python (can't easily filter by relationship existence in SQL)
    if has_xero is not None:
        organizations = [org for org in organizations if org.has_xero_connection == has_xero]
    
    # Build summaries
    org_summaries = [_build_org_summary(org) for org in organizations]
    
    return OrganizationListResponse(
        total=total,
        organizations=org_summaries,
    )
