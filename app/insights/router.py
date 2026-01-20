"""
Insights Router
API endpoints for financial insights and calculations.
"""

import logging
from datetime import datetime, timezone
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status, BackgroundTasks
from sqlalchemy import select, and_, desc, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import get_current_user
from app.database.connection import async_session_factory, get_async_session
from app.insights.schemas import InsightsResponse, Insight, InsightUpdate
from app.insights.sync_service import SyncService
from app.models.calculated_metrics import CalculatedMetrics
from app.models.insight import Insight as InsightModel
from app.models.organization import Organization, SyncStatus, SyncStep
from app.models.user import User

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/insights", tags=["Insights"])


@router.get(
    "/",
    response_model=InsightsResponse,
    summary="Get all financial insights",
    description="Calculate and return all financial insights: cash runway, leading indicators, and cash pressure. Uses cache when available.",
)
async def get_insights(
    current_user: User = Depends(get_current_user),
    page: int = Query(1, ge=1, description="Page number (1-based)"),
    limit: int = Query(3, ge=1, le=100, description="Items per page (default 3 for dashboard)"),
    insight_type: Optional[str] = Query(None, description="Filter by insight type"),
    severity: Optional[str] = Query(None, description="Filter by severity (high, medium, low)"),
    db: AsyncSession = Depends(get_async_session),
) -> InsightsResponse:
    """
    Calculate and return all financial insights.
    
    This endpoint:
    - Uses cached data when available (exact date range match only, unless force_refresh=true)
    - Fetches financial data from Xero (or cache)
    - Calculates cash runway metrics
    - Identifies leading indicators of cash stress
    - Calculates cash pressure status
    
    Returns comprehensive insights ready for dashboard display.
    """
    if not current_user.organization:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="User has no organization",
        )
    
    try:
        # 1. Fetch Latest Metrics Snapshot (The "Scoreboard")
        stmt = select(CalculatedMetrics).where(
            CalculatedMetrics.organization_id == current_user.organization.id
        )
        result = await db.execute(stmt)
        calc_metrics = result.scalar_one_or_none()
        
        # For now, if no metrics, we can't show dashboard. 
        if not calc_metrics or not calc_metrics.metrics_payload:
            # Return empty structure if no data yet (UX: Empty Dashboard State)
            metrics_payload = {
                "cash_runway": None,
                "leading_indicators": None,
                "cash_pressure": None,
                "profitability": None,
                "upcoming_commitments": None
            }
            calculated_at_iso = None
        else:
            metrics_payload = calc_metrics.metrics_payload
            calculated_at_iso = calc_metrics.calculated_at.isoformat()
        
        
        # 2. Fetch Insights (The "Commentary")
        # Base query
        stmt = select(InsightModel).where(
            InsightModel.organization_id == current_user.organization.id
        )
        
        # Apply filters
        if insight_type:
            stmt = stmt.where(InsightModel.insight_type == insight_type)
        if severity:
            stmt = stmt.where(InsightModel.severity == severity)
            
        # Get total count (for pagination)
        count_stmt = select(func.count()).select_from(stmt.subquery())
        total_result = await db.execute(count_stmt)
        total = total_result.scalar() or 0
        
        # Apply Ordering and Pagination
        offset = (page - 1) * limit
        stmt = stmt.order_by(desc(InsightModel.generated_at)).limit(limit).offset(offset)
        
        result = await db.execute(stmt)
        saved_insights = result.scalars().all()
        
        # Calculate total pages
        total_pages = (total + limit - 1) // limit if total > 0 else 0
        
        # Format for response
        insights_with_engagement = []
        for saved_insight in saved_insights:
            insights_with_engagement.append({
                "insight_id": saved_insight.insight_id,
                "insight_type": saved_insight.insight_type,
                "title": saved_insight.title,
                "severity": saved_insight.severity,
                "confidence_level": saved_insight.confidence_level,
                "summary": saved_insight.summary,
                "why_it_matters": saved_insight.why_it_matters,
                "recommended_actions": saved_insight.recommended_actions,
                "supporting_numbers": saved_insight.supporting_numbers or [],
                "data_notes": saved_insight.data_notes,
                "generated_at": saved_insight.generated_at.isoformat(),
                "is_acknowledged": saved_insight.is_acknowledged,
                "is_marked_done": saved_insight.is_marked_done,
            })

        # In-memory ranking: severity > confidence > generated_at (desc)
        def _sev_weight(v: Optional[str]) -> int:
            m = {"high": 3, "medium": 2, "low": 1}
            return m.get((v or "").lower(), 0)

        def _conf_weight(v: Optional[str]) -> int:
            m = {"high": 3, "medium": 2, "low": 1}
            return m.get((v or "").lower(), 0)

        insights_with_engagement.sort(
            key=lambda x: (
                _sev_weight(x.get("severity")),
                _conf_weight(x.get("confidence_level")),
                x.get("generated_at", ""),
            ),
            reverse=True,
        )
        
        
        return InsightsResponse(
            cash_runway=metrics_payload["cash_runway"],
            leading_indicators=metrics_payload["leading_indicators"],
            cash_pressure=metrics_payload["cash_pressure"],
            profitability=metrics_payload["profitability"],
            upcoming_commitments=metrics_payload["upcoming_commitments"],
            insights=insights_with_engagement,
            pagination={
                "total": total,
                "page": page,
                "limit": limit,
                "total_pages": total_pages,
            },
            calculated_at=calculated_at_iso or datetime.now(timezone.utc).isoformat(),
            raw_data_summary={}, # Not storing raw summary in snapshot currently, can be added if needed
        )
        
    except Exception:
        # Global exception handler will sanitize this
        raise

@router.get(
    "/status",
    summary="Get sync status",
    description="Polls the current status of the insight generation process.",
)
async def get_sync_status(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_session),
):
    """
    Get the current sync status for the user's organization.
    """
    if not current_user.organization:
        raise HTTPException(status_code=400, detail="User has no organization")
    
    # Reload organization to get latest status
    stmt = select(Organization).where(Organization.id == current_user.organization.id)
    result = await db.execute(stmt)
    org = result.scalar_one_or_none()
    
    if not org:
        raise HTTPException(status_code=404, detail="Organization not found")
        
    return {
        "sync_status": org.sync_status,
        "sync_step": org.sync_step,
        "last_sync_error": org.last_sync_error,
        "updated_at": org.updated_at.isoformat() if org.updated_at else None
    }


@router.get(
    "/health-score",
    summary="Get Business Health Score",
    description="Return the pre-calculated Business Health Score (0-100) from the last sync.",
)
async def get_health_score(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_session),
) -> dict[str, Any]:
    """
    Return the Business Health Score v1 (0-100) from the last sync.
    
    This endpoint reads from the database (fast, no Xero API calls).
    Health Score is calculated during the sync process.
    
    To refresh the score, trigger a new sync via POST /api/insights/trigger.
    
    Returns:
        Complete Health Score result including:
        - score (0-100)
        - grade (A/B/C/D)
        - confidence (high/medium/low)
        - category breakdowns
        - top drivers (positive and negative)
    """
    if not current_user.organization:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="User has no organization",
        )
    
    try:
        # Read from database (fast, no Xero calls)
        stmt = select(CalculatedMetrics).where(
            CalculatedMetrics.organization_id == current_user.organization.id
        )
        result = await db.execute(stmt)
        calc_metrics = result.scalar_one_or_none()
        
        if not calc_metrics or not calc_metrics.health_score_payload:
            # No health score yet - return empty state with instructions
            return {
                "schema_version": "bhs.v1",
                "generated_at": None,
                "scorecard": {
                    "raw_score": 0,
                    "confidence": "low",
                    "confidence_cap": 80,
                    "final_score": 0,
                    "grade": "D",
                },
                "category_scores": {},
                "subscores": {},
                "drivers": {"top_positive": [], "top_negative": []},
                "data_quality": {
                    "signals": [{
                        "signal_id": "no_sync",
                        "severity": "warning",
                        "message": "No data yet. Please sync your Xero data first."
                    }],
                    "warnings": ["No health score calculated yet. Trigger a sync to calculate."],
                },
                "message": "Health score not yet calculated. Please trigger a sync.",
            }
        
        # Return the stored health score
        health_score = calc_metrics.health_score_payload
        
        # Add business info if not present
        if "business" not in health_score:
            xero_tenant_id = None
            if current_user.organization.xero_token:
                xero_tenant_id = current_user.organization.xero_token.xero_tenant_id
            
            health_score["business"] = {
                "business_id": str(current_user.organization.id),
                "business_name": current_user.organization.name or "Unknown",
                "tenant_provider": "xero",
                "tenant_id": xero_tenant_id,
                "currency": "AUD",
            }
        
        # Add calculated_at from the metrics record
        if "generated_at" not in health_score:
            health_score["generated_at"] = calc_metrics.calculated_at.isoformat() if calc_metrics.calculated_at else None
        
        logger.debug(
            "Health Score returned for org %s: score=%s, grade=%s",
            current_user.organization.id,
            health_score.get("scorecard", {}).get("final_score"),
            health_score.get("scorecard", {}).get("grade"),
        )
        
        return health_score
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Error retrieving health score: %s", e)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to retrieve health score",
        )


@router.get(
    "/{insight_id}",
    response_model=Insight,
    summary="Get insight details",
    description="Get full details for a specific insight by ID.",
)
async def get_insight_detail(
    insight_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_session),
) -> Insight:
    """
    Get detailed view of a specific insight.
    
    Reads from database - insights are generated and stored during sync.
    """
    if not current_user.organization:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="User has no organization",
        )
    
    try:
        # Read insight from database
        stmt = select(InsightModel).where(
            and_(
                InsightModel.insight_id == insight_id,
                InsightModel.organization_id == current_user.organization.id,
            )
        )
        result = await db.execute(stmt)
        insight = result.scalar_one_or_none()
        
        if not insight:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Insight with ID {insight_id} not found",
            )
        
        # Return insight data
        return Insight(
            insight_id=insight.insight_id,
            insight_type=insight.insight_type,
            title=insight.title,
            severity=insight.severity,
            confidence_level=insight.confidence_level,
            summary=insight.summary,
            why_it_matters=insight.why_it_matters,
            recommended_actions=insight.recommended_actions,
            supporting_numbers=insight.supporting_numbers or [],
            data_notes=insight.data_notes,
            generated_at=insight.generated_at.isoformat(),
            is_acknowledged=insight.is_acknowledged,
            is_marked_done=insight.is_marked_done,
        )
        
    except HTTPException:
        raise
    except Exception:
        raise


@router.patch(
    "/{insight_id}",
    response_model=dict[str, Any],
    summary="Update insight state",
    description="Update insight status (acknowledged or marked done).",
)
async def update_insight(
    insight_id: str,
    update_data: InsightUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_session),
) -> dict[str, Any]:
    """
    Update an insight's state (acknowledge or mark done).
    """
    if not current_user.organization:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="User has no organization",
        )
    
    try:
        # Find insight
        stmt = select(InsightModel).where(
            and_(
                InsightModel.insight_id == insight_id,
                InsightModel.organization_id == current_user.organization.id,
            )
        )
        result = await db.execute(stmt)
        insight = result.scalar_one_or_none()
        
        if not insight:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Insight with ID {insight_id} not found",
            )
        
        # Apply updates
        now = datetime.now(timezone.utc)
        
        if update_data.is_acknowledged is not None:
            insight.is_acknowledged = update_data.is_acknowledged
            if update_data.is_acknowledged:
                insight.acknowledged_at = now
                insight.acknowledged_by_user_id = current_user.id
            else:
                insight.acknowledged_at = None
                insight.acknowledged_by_user_id = None
                
        if update_data.is_marked_done is not None:
            insight.is_marked_done = update_data.is_marked_done
            if update_data.is_marked_done:
                insight.marked_done_at = now
                insight.marked_done_by_user_id = current_user.id
            else:
                insight.marked_done_at = None
                insight.marked_done_by_user_id = None
        
        await db.commit()
        await db.refresh(insight)
        
        return {
            "success": True,
            "message": "Insight updated",
            "insight_id": insight_id,
            "is_acknowledged": insight.is_acknowledged,
            "is_marked_done": insight.is_marked_done,
        }
        
    except HTTPException:
        raise
    except Exception:
        await db.rollback()
        # Global exception handler will sanitize this
        raise




@router.post(
    "/trigger",
    status_code=status.HTTP_202_ACCEPTED,
    summary="Trigger async insights generation",
    description="Starts the background process to fetch data, calculate metrics, and generate AI insights.",
)
async def trigger_insights_generation(
    background_tasks: BackgroundTasks,
    current_user: User = Depends(get_current_user),
    force_refresh: bool = Query(default=False, description="Force refresh, bypass cache"),
    db: AsyncSession = Depends(get_async_session),
):
    """
    Trigger the insights generation process in the background.
    
    Data fetching:
    - Balance Sheet: as of today
    - Monthly P&L: last 12 months (for trends and health score)
    - AR/AP: current outstanding invoices
    
    Updates organization status immediately so frontend can show progress.
    """
    if not current_user.organization:
        raise HTTPException(status_code=400, detail="User has no organization")

    # Balance sheet date is always today
    today = datetime.now(timezone.utc).date()

    # Update organization status IMMEDIATELY before starting background task
    # This ensures the frontend modal shows "Connecting" right away
    org = current_user.organization
    org.sync_status = SyncStatus.IN_PROGRESS
    org.sync_step = SyncStep.CONNECTING
    org.last_sync_error = None
    org.updated_at = datetime.now(timezone.utc)
    await db.commit()
    
    # Refresh to get the latest updated_at timestamp after commit
    await db.refresh(org)

    async def _background_task_wrapper(org_id, bs_date, refresh):
        # Create a new session specifically for this background task
        async with async_session_factory() as session:
            try:
                bg_service = SyncService(session, org_id)
                await bg_service.run_sync(bs_date, refresh)
            except Exception as e:
                import logging
                logging.getLogger(__name__).error(f"Background task failed: {e}")

    background_tasks.add_task(
        _background_task_wrapper,
        current_user.organization.id,
        today,
        force_refresh
    )
    
    # Return status with updated_at timestamp for frontend validation
    return {
        "message": "Insight generation started",
        "status": "IN_PROGRESS",
        "sync_status": org.sync_status.value,
        "sync_step": org.sync_step.value if org.sync_step else None,
        "updated_at": org.updated_at.isoformat() if org.updated_at else None
    }

