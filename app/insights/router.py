"""
Insights Router
API endpoints for financial insights and calculations.
"""

import logging
from datetime import date, datetime, timedelta, timezone
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status, BackgroundTasks
from app.models.organization import Organization, SyncStatus, SyncStep
from app.insights.sync_service import SyncService
from app.database.connection import async_session_factory
from app.auth.dependencies import get_current_user
from app.database.connection import get_async_session
from app.models.user import User
from app.models.insight import Insight as InsightModel
from app.insights.service import InsightsService
from app.insights.schemas import InsightsResponse, Insight, InsightUpdate
from app.insights.data_summarizer import DataSummarizer
from app.models.insight import Insight as InsightModel
from app.models.calculated_metrics import CalculatedMetrics
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_, desc, func
from app.database.connection import async_session_factory

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
    limit: int = Query(5, ge=1, le=100, description="Items per page (default 5 for dashboard)"),
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
    "/{insight_id}",
    response_model=Insight,
    summary="Get insight details",
    description="Get full details for a specific insight by ID.",
)
async def get_insight_detail(
    insight_id: str,
    current_user: User = Depends(get_current_user),
    start_date: Optional[date] = Query(None, description="Start date for P&L period (YYYY-MM-DD). Defaults to 30 days ago."),
    end_date: Optional[date] = Query(None, description="End date for P&L period (YYYY-MM-DD). Defaults to today."),
    db: AsyncSession = Depends(get_async_session),
) -> Insight:
    """
    Get detailed view of a specific insight.
    
    Regenerates insights to find the matching one by ID.
    In future, this could be cached/stored for better performance.
    """
    if not current_user.organization:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="User has no organization",
        )
    
    # Set default dates if not provided
    today = datetime.now(timezone.utc).date()
    if end_date is None:
        end_date = today
    if start_date is None:
        start_date = today - timedelta(days=30)
    
    # Validate date range
    if start_date >= end_date:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="start_date must be before end_date",
        )
    
    if end_date > today:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="end_date cannot be in the future",
        )
    
    try:
        # Create cache service
        cache_service = CacheService(db)
        
        # Create SDK client
        sdk_client = await create_xero_sdk_client(
            organization_id=current_user.organization.id,
            db=db,
        )
        
        # Create data fetcher
        data_fetcher = XeroDataFetcher(sdk_client, cache_service=cache_service, db=db)
        
        # Fetch all data
        financial_data = await data_fetcher.fetch_all_data(
            organization_id=current_user.organization.id,
            start_date=start_date,
            end_date=end_date,
            force_refresh=False,
        )
        
        # Commit token updates before blocking OpenAI call
        # This ensures the session is clean and prevents deadlocks
        if data_fetcher.session_manager:
            await data_fetcher.session_manager.commit_all()
        
        # Calculate metrics
        metrics = InsightsService.calculate_all_insights(financial_data, data_fetcher)
        
        # Create compact summary of raw data for AI analysis
        raw_data_summary = DataSummarizer.summarize(financial_data, start_date, end_date, data_fetcher)
        
        # Generate all insights using AI
        insight_generator = InsightGenerator()
        all_insights = insight_generator.generate_insights(
            metrics={
                "cash_runway": metrics["cash_runway"],
                "cash_pressure": metrics["cash_pressure"],
                "leading_indicators": metrics["leading_indicators"],
                "profitability": metrics["profitability"],
                "upcoming_commitments": metrics["upcoming_commitments"],
            },
            raw_data_summary=raw_data_summary,
            start_date=start_date.isoformat(),
            end_date=end_date.isoformat(),
        )
        
        # Find insight by ID
        for insight_dict in all_insights:
            if insight_dict.get("insight_id") == insight_id:
                return Insight(**insight_dict)
        
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Insight with ID {insight_id} not found",
        )
        
    except XeroSDKClientError:
        # Global exception handler will sanitize this
        raise
    except HTTPException:
        raise
    except Exception:
        # Global exception handler will sanitize this
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
    start_date: Optional[date] = Query(None, description="Start date (YYYY-MM-DD)"),
    end_date: Optional[date] = Query(None, description="End date (YYYY-MM-DD)"),
    force_refresh: bool = Query(default=False, description="Force refresh, bypass cache"),
    db: AsyncSession = Depends(get_async_session),
):
    """
    Trigger the insights generation process in the background.
    """
    if not current_user.organization:
        raise HTTPException(status_code=400, detail="User has no organization")

    # Set default dates
    today = datetime.now(timezone.utc).date()
    if end_date is None:
        end_date = today
    if start_date is None:
        start_date = today - timedelta(days=30)

    async def _background_task_wrapper(org_id, start, end, refresh):
        # Create a new session specifically for this background task
        async with async_session_factory() as session:
            try:
                bg_service = SyncService(session, org_id)
                await bg_service.run_sync(start, end, refresh)
            except Exception as e:
                # Catch any unhandled exceptions to ensure session closes cleanly
                # and doesn't crash the worker ungracefully (though SyncService catches most)
                import logging
                logging.getLogger(__name__).error(f"Background task failed: {e}")

    background_tasks.add_task(
        _background_task_wrapper,
        current_user.organization.id,
        start_date,
        end_date,
        force_refresh
    )
    
    return {"message": "Insight generation started", "status": "IN_PROGRESS"}



