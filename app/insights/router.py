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
from app.integrations.xero.cache_service import CacheService
from app.integrations.xero.sdk_client import create_xero_sdk_client, XeroSDKClientError
from app.integrations.xero.data_fetcher import XeroDataFetcher
from app.insights.insight_generator import InsightGenerator
from app.insights.health_score_calculator import HealthScoreCalculator

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
    description="Calculate and return the Business Health Score (0-100) with detailed breakdown.",
)
async def get_health_score(
    current_user: User = Depends(get_current_user),
    start_date: Optional[date] = Query(None, description="Start date for P&L period (YYYY-MM-DD). Defaults to 30 days ago."),
    end_date: Optional[date] = Query(None, description="End date for P&L period (YYYY-MM-DD). Defaults to today."),
    force_refresh: bool = Query(default=False, description="Force refresh, bypass cache"),
    db: AsyncSession = Depends(get_async_session),
) -> dict[str, Any]:
    """
    Calculate and return the Business Health Score v1 (0-100).
    
    The score is based on:
    - A) Cash & Runway (30 points)
    - B) Profitability & Efficiency (25 points)
    - C) Revenue Quality & Momentum (15 points) - *Requires historical data*
    - D) Working Capital & Liquidity (20 points)
    - E) Compliance & Data Confidence (10 points)
    
    Uses AccountType-based data extraction for reliability.
    Missing metrics are handled via weight redistribution.
    
    Returns:
        Complete Health Score result including:
        - score (0-100)
        - grade (A/B/C/D)
        - confidence (high/medium/low)
        - category breakdowns
        - top drivers (positive and negative)
        - all intermediate calculations
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
        
        # Fetch all data (includes extracted data from new Extractors module)
        financial_data = await data_fetcher.fetch_all_data(
            organization_id=current_user.organization.id,
            start_date=start_date,
            end_date=end_date,
            force_refresh=force_refresh,
        )
        
        # Commit token updates
        if data_fetcher.session_manager:
            await data_fetcher.session_manager.commit_all()
        
        # Use new extracted data if available (from Extractors module)
        extracted = financial_data.get("extracted")
        if extracted:
            # Use clean extracted data
            balance_sheet_totals = extracted.get("balance_sheet", {})
            pnl_data = extracted.get("pnl", {})
            trial_balance_pnl = {
                "revenue": pnl_data.get("revenue"),
                "cost_of_sales": pnl_data.get("cost_of_sales"),
                "expenses": pnl_data.get("expenses"),
            }
            invoices_receivable = financial_data.get("invoices_receivable", {})
            invoices_payable = financial_data.get("invoices_payable", {})
            logger.debug(
                "Health Score using extracted data: cash=%.2f, AR=%.2f, revenue=%.2f",
                balance_sheet_totals.get("cash") or 0,
                balance_sheet_totals.get("accounts_receivable") or 0,
                trial_balance_pnl.get("revenue") or 0,
            )
        else:
            # Fallback to old structure
            balance_sheet_totals = financial_data.get("balance_sheet_totals", {})
            trial_balance_pnl = financial_data.get("trial_balance_pnl", {})
            invoices_receivable = financial_data.get("invoices_receivable", {})
            invoices_payable = financial_data.get("invoices_payable", {})
        
        # Calculate Health Score
        health_score = HealthScoreCalculator.calculate(
            balance_sheet_totals=balance_sheet_totals,
            trial_balance_pnl=trial_balance_pnl,
            invoices_receivable=invoices_receivable,
            invoices_payable=invoices_payable,
        )
        
        # Add organization and period info
        xero_tenant_id = None
        if current_user.organization.xero_token:
            xero_tenant_id = current_user.organization.xero_token.xero_tenant_id
        
        health_score["business"] = {
            "business_id": str(current_user.organization.id),
            "business_name": current_user.organization.name or "Unknown",
            "tenant_provider": "xero",
            "tenant_id": xero_tenant_id,
            "currency": "AUD",  # Could be fetched from Xero org settings
        }
        health_score["periods"] = {
            "pnl_monthly": {
                "start_date": start_date.isoformat(),
                "end_date": end_date.isoformat(),
                "months": 1,  # Currently single month
            },
            "rolling_3m": {
                "end_date": end_date.isoformat(),
            },
            "rolling_6m": {
                "end_date": end_date.isoformat(),
            },
            "balance_sheet_asof": end_date.isoformat(),
        }
        
        logger.info(
            "Health Score calculated for org %s: score=%s, grade=%s, confidence=%s",
            current_user.organization.id,
            health_score["scorecard"]["final_score"],
            health_score["scorecard"]["grade"],
            health_score["scorecard"]["confidence"],
        )
        
        return health_score
        
    except XeroSDKClientError as e:
        logger.error("Xero SDK error while calculating health score: %s", e)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Unable to fetch financial data from Xero",
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Error calculating health score: %s", e)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to calculate health score",
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
        metrics = InsightsService.calculate_all_insights(financial_data)
        
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
    Updates organization status immediately so frontend can show progress.
    """
    if not current_user.organization:
        raise HTTPException(status_code=400, detail="User has no organization")

    # Set default dates
    today = datetime.now(timezone.utc).date()
    if end_date is None:
        end_date = today
    if start_date is None:
        start_date = today - timedelta(days=30)

    # Update organization status IMMEDIATELY before starting background task
    # This ensures the frontend modal shows "Connecting" right away
    org = current_user.organization
    org.sync_status = SyncStatus.IN_PROGRESS
    org.sync_step = SyncStep.CONNECTING
    org.last_sync_error = None
    org.updated_at = datetime.now(timezone.utc)  # Explicitly set updated_at to UTC
    await db.commit()
    
    # Refresh to get the latest updated_at timestamp after commit
    await db.refresh(org)

    async def _background_task_wrapper(org_id, start, end, refresh):
        # Create a new session specifically for this background task
        async with async_session_factory() as session:
            try:
                bg_service = SyncService(session, org_id)
                # Note: SyncService will update status as it progresses
                # It starts with CONNECTING, so we don't need to set it again
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
    
    # Return status with updated_at timestamp for frontend validation
    return {
        "message": "Insight generation started",
        "status": "IN_PROGRESS",
        "sync_status": org.sync_status.value,
        "sync_step": org.sync_step.value if org.sync_step else None,
        "updated_at": org.updated_at.isoformat() if org.updated_at else None
    }

