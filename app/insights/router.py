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

from app.auth.dependencies import get_current_user
from app.database.connection import get_async_session
from app.integrations.xero.cache_service import CacheService
from app.integrations.xero.data_fetcher import XeroDataFetcher
from app.integrations.xero.sdk_client import create_xero_sdk_client, XeroSDKClientError
from app.models.user import User
from app.models.insight import Insight as InsightModel
from app.insights.service import InsightsService
from app.insights.schemas import InsightsResponse, Insight
from app.insights.data_summarizer import DataSummarizer
from app.insights.insight_generator import InsightGenerator
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_, desc, func

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
    start_date: Optional[date] = Query(None, description="Start date for P&L period (YYYY-MM-DD). Defaults to 30 days ago."),
    end_date: Optional[date] = Query(None, description="End date for P&L period (YYYY-MM-DD). Defaults to today."),
    force_refresh: bool = Query(default=False, description="Force refresh, bypass cache"),
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
    
    # Validate end_date is not in future
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
        financial_data = await data_fetcher.fetch_all_data(
            organization_id=current_user.organization.id,
            start_date=start_date,
            end_date=end_date,
            force_refresh=force_refresh,
        )
        
        # Commit token updates before blocking OpenAI call
        # This ensures the session is clean and prevents deadlocks
        if data_fetcher.session_manager:
            await data_fetcher.session_manager.commit_all()
        
        # Calculate insights from fetched data
        metrics = InsightsService.calculate_all_insights(financial_data, data_fetcher)
        
        # Create compact summary of raw data for AI analysis
        raw_data_summary = DataSummarizer.summarize(financial_data, start_date, end_date, data_fetcher)
        
        # Generate ranked insights using AI
        insight_generator = InsightGenerator()
        generated_insights = insight_generator.generate_insights(
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
        
        # Save insights to database
        generated_at = datetime.now(timezone.utc)
        saved_insights = []
        
        for insight_dict in generated_insights:
            # Check if insight already exists (same insight_id)
            stmt = select(InsightModel).where(
                and_(
                    InsightModel.insight_id == insight_dict["insight_id"],
                    InsightModel.organization_id == current_user.organization.id,
                )
            )
            result = await db.execute(stmt)
            existing = result.scalar_one_or_none()
            
            if existing:
                # Update existing insight (preserve engagement state)
                existing.title = insight_dict["title"]
                existing.severity = insight_dict["severity"]
                existing.confidence_level = insight_dict["confidence_level"]
                existing.summary = insight_dict["summary"]
                existing.why_it_matters = insight_dict["why_it_matters"]
                existing.recommended_actions = insight_dict["recommended_actions"]
                existing.supporting_numbers = insight_dict.get("supporting_numbers", [])
                existing.data_notes = insight_dict.get("data_notes")
                existing.generated_at = generated_at
                saved_insights.append(existing)
            else:
                # Create new insight
                new_insight = InsightModel(
                    organization_id=current_user.organization.id,
                    insight_id=insight_dict["insight_id"],
                    insight_type=insight_dict["insight_type"],
                    title=insight_dict["title"],
                    severity=insight_dict["severity"],
                    confidence_level=insight_dict["confidence_level"],
                    summary=insight_dict["summary"],
                    why_it_matters=insight_dict["why_it_matters"],
                    recommended_actions=insight_dict["recommended_actions"],
                    supporting_numbers=insight_dict.get("supporting_numbers", []),
                    data_notes=insight_dict.get("data_notes"),
                    generated_at=generated_at,
                )
                db.add(new_insight)
                saved_insights.append(new_insight)
        
        # Commit insights to database
        # Token updates were already committed before OpenAI call
        await db.commit()
        
        # Refresh insights to get updated data
        for insight in saved_insights:
            await db.refresh(insight)
        
        # Add engagement state to response
        insights_with_engagement = []
        for insight_dict in generated_insights:
            # Find matching saved insight
            saved_insight = next(
                (s for s in saved_insights if s.insight_id == insight_dict["insight_id"]),
                None,
            )
            if saved_insight:
                insight_dict["is_acknowledged"] = saved_insight.is_acknowledged
                insight_dict["is_marked_done"] = saved_insight.is_marked_done
            else:
                insight_dict["is_acknowledged"] = False
                insight_dict["is_marked_done"] = False
            insights_with_engagement.append(insight_dict)
        
        return InsightsResponse(
            cash_runway=metrics["cash_runway"],
            leading_indicators=metrics["leading_indicators"],
            cash_pressure=metrics["cash_pressure"],
            profitability=metrics["profitability"],
            upcoming_commitments=metrics["upcoming_commitments"],
            insights=insights_with_engagement,
            calculated_at=generated_at.isoformat(),
            raw_data_summary=raw_data_summary,
        )
        
    except XeroSDKClientError:
        # Global exception handler will sanitize this
        raise
    except Exception:
        # Global exception handler will sanitize this
        raise


@router.get(
    "/list",
    response_model=dict[str, Any],
    summary="List all insights",
    description="Get all stored insights with pagination and filtering.",
)
async def list_insights(
    page: int = Query(1, ge=1, description="Page number (1-based)"),
    limit: int = Query(20, ge=1, le=100, description="Items per page"),
    insight_type: Optional[str] = Query(None, description="Filter by insight type"),
    severity: Optional[str] = Query(None, description="Filter by severity (high, medium, low)"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_session),
) -> dict[str, Any]:
    """
    List all stored insights with pagination.
    
    Simple endpoint that queries the database only.
    No calculations, no date filters - just returns stored insights.
    """
    if not current_user.organization:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="User has no organization",
        )
    
    try:
        # Build query
        stmt = select(InsightModel).where(
            InsightModel.organization_id == current_user.organization.id
        )
        
        # Apply filters
        if insight_type:
            stmt = stmt.where(InsightModel.insight_type == insight_type)
        if severity:
            stmt = stmt.where(InsightModel.severity == severity)
        
        # Get total count
        count_stmt = select(func.count()).select_from(stmt.subquery())
        total_result = await db.execute(count_stmt)
        total = total_result.scalar() or 0
        
        # Apply pagination and ordering
        offset = (page - 1) * limit
        stmt = stmt.order_by(desc(InsightModel.generated_at))
        stmt = stmt.limit(limit).offset(offset)
        
        # Execute query
        result = await db.execute(stmt)
        insights = result.scalars().all()
        
        # Convert to response format
        insights_list = []
        for insight in insights:
            insights_list.append({
                "insight_id": insight.insight_id,
                "insight_type": insight.insight_type,
                "title": insight.title,
                "severity": insight.severity,
                "confidence_level": insight.confidence_level,
                "summary": insight.summary,
                "why_it_matters": insight.why_it_matters,
                "recommended_actions": insight.recommended_actions,
                "supporting_numbers": insight.supporting_numbers or [],
                "data_notes": insight.data_notes,
                "generated_at": insight.generated_at.isoformat(),
                "is_acknowledged": insight.is_acknowledged,
                "is_marked_done": insight.is_marked_done,
            })
        
        total_pages = (total + limit - 1) // limit if total > 0 else 0
        
        return {
            "total": total,
            "page": page,
            "limit": limit,
            "total_pages": total_pages,
            "insights": insights_list,
        }
        
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


@router.post(
    "/{insight_id}/acknowledge",
    summary="Acknowledge insight",
    description="Mark an insight as acknowledged (persists to database).",
)
async def acknowledge_insight(
    insight_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_session),
) -> dict[str, Any]:
    """
    Acknowledge an insight.
    
    Updates the insight record in the database to mark it as acknowledged.
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
        
        # Update acknowledgment
        now = datetime.now(timezone.utc)
        insight.is_acknowledged = True
        insight.acknowledged_at = now
        insight.acknowledged_by_user_id = current_user.id
        
        await db.commit()
        await db.refresh(insight)
        
        return {
            "success": True,
            "message": "Insight acknowledged",
            "insight_id": insight_id,
            "acknowledged_at": insight.acknowledged_at.isoformat(),
        }
        
    except HTTPException:
        raise
    except Exception:
        await db.rollback()
        # Global exception handler will sanitize this
        raise


@router.post(
    "/{insight_id}/mark-done",
    summary="Mark insight as done",
    description="Mark an insight as completed/acted upon (persists to database).",
)
async def mark_insight_done(
    insight_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_session),
) -> dict[str, Any]:
    """
    Mark an insight as done.
    
    Updates the insight record in the database to mark it as done.
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
        
        # Update marked done
        now = datetime.now(timezone.utc)
        insight.is_marked_done = True
        insight.marked_done_at = now
        insight.marked_done_by_user_id = current_user.id
        
        await db.commit()
        await db.refresh(insight)
        
        return {
            "success": True,
            "message": "Insight marked as done",
            "insight_id": insight_id,
            "marked_done_at": insight.marked_done_at.isoformat(),
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
        
    # Initialize Service
    service = SyncService(db, current_user.organization.id)
    
    # Add to background tasks
    # Note: We can't pass the 'db' session directly to background tasks if it closes after request.
    # FastAPI Depends(get_async_session) yields a session that closes.
    # We need a new session or a way to keep it open. 
    # BUT: Starlette BackgroundTasks run *after* the response is sent. 
    # Providing a session that relies on the request scope context might be risky if not handled.
    # For MVP simplicity, we will assume standard FastAPI behavior where we run the task.
    # HOWEVER: a safer way is to create a new session inside the background task wrapper.
    # Let's update SyncService to create its own session if needed, OR we trust FastAPI's design (it usually waits).
    # ACTUALLY: The safest pattern is to pass the session *factory* or manage session inside the task.
    # But for now, let's try passing the task directly. 
    # If this fails, we'll need to refactor SyncService to create a new session.
    
    # Refactor: To prevent "Session is closed" cleanup errors from FastAPI dependency injection 
    # interfering with the background task, and to ensure the background task has its own
    # independent persistent session, we instantiate a new AsyncSession within the task wrapper.
    
    from app.database.connection import async_session_factory

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



