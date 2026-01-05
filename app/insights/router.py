"""
Insights Router
API endpoints for financial insights and calculations.
"""

import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status

from app.auth.dependencies import get_current_user
from app.database.connection import get_async_session
from app.integrations.xero.cache_service import CacheService
from app.integrations.xero.data_fetcher import XeroDataFetcher
from app.integrations.xero.sdk_client import create_xero_sdk_client, XeroSDKClientError
from app.models.user import User
from app.insights.service import InsightsService
from app.insights.schemas import InsightsResponse
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/insights", tags=["Insights"])


@router.get(
    "/",
    response_model=InsightsResponse,
    summary="Get all financial insights",
    description="Calculate and return all financial insights: cash runway, trends, and leading indicators. Uses cache when available.",
)
async def get_insights(
    current_user: User = Depends(get_current_user),
    months: int = 6,
    force_refresh: bool = False,
    db: AsyncSession = Depends(get_async_session),
) -> InsightsResponse:
    """
    Calculate and return all financial insights.
    
    This endpoint:
    - Uses cached data when available (unless force_refresh=true)
    - Fetches financial data from Xero (or cache)
    - Calculates cash runway metrics
    - Analyzes cash flow trends
    - Identifies leading indicators of cash stress
    
    Returns comprehensive insights ready for dashboard display.
    """
    if not current_user.organization:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="User has no organization",
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
            months=months,
            force_refresh=force_refresh,
        )
        
        # Calculate insights from fetched data
        insights = InsightsService.calculate_all_insights(financial_data)
        
        return InsightsResponse(
            cash_runway=insights["cash_runway"],
            trends=insights["trends"],
            leading_indicators=insights["leading_indicators"],
            cash_pressure=insights["cash_pressure"],
            profitability=insights["profitability"],
            upcoming_commitments=insights["upcoming_commitments"],
            calculated_at=datetime.now(timezone.utc).isoformat(),
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

