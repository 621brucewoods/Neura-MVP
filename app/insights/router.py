"""
Insights Router
API endpoints for financial insights and calculations.
"""

import logging
from datetime import date, datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.auth.dependencies import get_current_user
from app.database.connection import get_async_session
from app.integrations.xero.cache_service import CacheService
from app.integrations.xero.data_fetcher import XeroDataFetcher
from app.integrations.xero.sdk_client import create_xero_sdk_client, XeroSDKClientError
from app.models.user import User
from app.insights.service import InsightsService
from app.insights.schemas import InsightsResponse, Insight
from app.insights.data_summarizer import DataSummarizer
from app.insights.insight_generator import InsightGenerator
from sqlalchemy.ext.asyncio import AsyncSession

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
    start_date: date = Query(..., description="Start date for P&L period (YYYY-MM-DD)"),
    end_date: date = Query(..., description="End date for P&L period (YYYY-MM-DD)"),
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
    
    # Validate date range
    if start_date >= end_date:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="start_date must be before end_date",
        )
    
    today = datetime.now(timezone.utc).date()
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
        
        # Create data fetcher with SDK client and cache service
        data_fetcher = XeroDataFetcher(sdk_client, cache_service=cache_service)
        
        # Fetch all data (with caching)
        financial_data = await data_fetcher.fetch_all_data(
            organization_id=current_user.organization.id,
            start_date=start_date,
            end_date=end_date,
            force_refresh=force_refresh,
        )
        
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
        
        return InsightsResponse(
            cash_runway=metrics["cash_runway"],
            leading_indicators=metrics["leading_indicators"],
            cash_pressure=metrics["cash_pressure"],
            profitability=metrics["profitability"],
            upcoming_commitments=metrics["upcoming_commitments"],
            insights=generated_insights,
            calculated_at=datetime.now(timezone.utc).isoformat(),
            raw_data_summary=raw_data_summary,
        )
        
    except XeroSDKClientError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=e.message,
        )
    except Exception as e:
        logger.error("Error calculating insights: %s", e, exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to calculate insights: {str(e)}",
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
    start_date: date = Query(..., description="Start date for P&L period (YYYY-MM-DD)"),
    end_date: date = Query(..., description="End date for P&L period (YYYY-MM-DD)"),
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
    
    try:
        # Create cache service
        cache_service = CacheService(db)
        
        # Create SDK client
        sdk_client = await create_xero_sdk_client(
            organization_id=current_user.organization.id,
            db=db,
        )
        
        # Create data fetcher
        data_fetcher = XeroDataFetcher(sdk_client, cache_service=cache_service)
        
        # Fetch all data
        financial_data = await data_fetcher.fetch_all_data(
            organization_id=current_user.organization.id,
            start_date=start_date,
            end_date=end_date,
            force_refresh=False,
        )
        
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
        
    except XeroSDKClientError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=e.message,
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Error fetching insight detail: %s", e, exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to fetch insight: {str(e)}",
        )


@router.post(
    "/{insight_id}/acknowledge",
    summary="Acknowledge insight",
    description="Mark an insight as acknowledged (lightweight engagement tracking).",
)
async def acknowledge_insight(
    insight_id: str,
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """
    Acknowledge an insight.
    
    In MVP, this is a lightweight action that doesn't persist state.
    Future: Store acknowledgment in database for tracking.
    """
    # For MVP, just return success
    # Future: Store in database with user_id, insight_id, acknowledged_at
    return {
        "success": True,
        "message": "Insight acknowledged",
        "insight_id": insight_id,
    }


@router.post(
    "/{insight_id}/mark-done",
    summary="Mark insight as done",
    description="Mark an insight as completed/acted upon.",
)
async def mark_insight_done(
    insight_id: str,
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """
    Mark an insight as done.
    
    In MVP, this is a lightweight action that doesn't persist state.
    Future: Store completion in database for tracking.
    """
    # For MVP, just return success
    # Future: Store in database with user_id, insight_id, marked_done_at
    return {
        "success": True,
        "message": "Insight marked as done",
        "insight_id": insight_id,
    }

