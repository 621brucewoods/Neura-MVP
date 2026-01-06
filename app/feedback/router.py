"""
Feedback Router
API endpoints for insight feedback.
"""

import logging
from datetime import datetime, timezone
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import get_current_user
from app.database.connection import get_async_session
from app.feedback.schemas import (
    FeedbackItem,
    FeedbackListResponse,
    FeedbackResponse,
    FeedbackSubmitRequest,
    FeedbackSummaryItem,
    FeedbackSummaryResponse,
    OverallStats,
    UserFeedbackResponse,
)
from app.models.insight_feedback import InsightFeedback
from app.models.user import User

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/feedback", tags=["Feedback"])


@router.post(
    "/",
    response_model=FeedbackResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Submit feedback",
    description="Submit feedback on an insight (helpful/not helpful with optional comment).",
)
async def submit_feedback(
    request: FeedbackSubmitRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_session),
) -> FeedbackResponse:
    """
    Submit feedback on an insight.
    
    If feedback already exists for this user + insight, it will be updated.
    Otherwise, a new feedback record is created.
    """
    if not current_user.organization:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="User has no organization",
        )
    
    try:
        # Check if feedback already exists
        stmt = select(InsightFeedback).where(
            and_(
                InsightFeedback.user_id == current_user.id,
                InsightFeedback.insight_id == request.insight_id,
            )
        )
        result = await db.execute(stmt)
        existing_feedback = result.scalar_one_or_none()
        
        now = datetime.now(timezone.utc)
        
        if existing_feedback:
            # Update existing feedback
            existing_feedback.is_helpful = request.is_helpful
            existing_feedback.comment = request.comment
            existing_feedback.insight_type = request.insight_type
            existing_feedback.insight_title = request.insight_title
            existing_feedback.updated_at = now
            await db.commit()
            await db.refresh(existing_feedback)
            
            return FeedbackResponse(
                id=str(existing_feedback.id),
                message="Feedback updated successfully",
                created_at=existing_feedback.created_at.isoformat(),
                updated_at=existing_feedback.updated_at.isoformat() if existing_feedback.updated_at else None,
            )
        else:
            # Create new feedback
            feedback = InsightFeedback(
                organization_id=current_user.organization.id,
                user_id=current_user.id,
                insight_id=request.insight_id,
                insight_type=request.insight_type,
                insight_title=request.insight_title,
                is_helpful=request.is_helpful,
                comment=request.comment,
            )
            db.add(feedback)
            await db.commit()
            await db.refresh(feedback)
            
            return FeedbackResponse(
                id=str(feedback.id),
                message="Feedback submitted successfully",
                created_at=feedback.created_at.isoformat(),
                updated_at=None,
            )
            
    except Exception as e:
        await db.rollback()
        logger.error("Error submitting feedback: %s", e, exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to submit feedback: {str(e)}",
        )


@router.get(
    "/",
    response_model=UserFeedbackResponse,
    summary="Get user's feedback",
    description="Get user's feedback for a specific insight.",
)
async def get_user_feedback(
    insight_id: str = Query(..., description="Insight ID"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_session),
) -> UserFeedbackResponse:
    """Get user's feedback for a specific insight."""
    try:
        stmt = select(InsightFeedback).where(
            and_(
                InsightFeedback.user_id == current_user.id,
                InsightFeedback.insight_id == insight_id,
            )
        )
        result = await db.execute(stmt)
        feedback = result.scalar_one_or_none()
        
        if not feedback:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Feedback not found",
            )
        
        return UserFeedbackResponse(
            insight_id=feedback.insight_id,
            is_helpful=feedback.is_helpful,
            comment=feedback.comment,
            submitted_at=feedback.created_at.isoformat(),
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Error fetching feedback: %s", e, exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to fetch feedback: {str(e)}",
        )


@router.get(
    "/admin",
    response_model=FeedbackListResponse,
    summary="Get all feedback (admin)",
    description="Get all feedback with filtering and pagination (admin only).",
)
async def get_all_feedback(
    insight_type: Optional[str] = Query(None, description="Filter by insight type"),
    is_helpful: Optional[bool] = Query(None, description="Filter by helpful/not helpful"),
    start_date: Optional[datetime] = Query(None, description="Filter by start date"),
    end_date: Optional[datetime] = Query(None, description="Filter by end date"),
    limit: int = Query(100, ge=1, le=1000, description="Pagination limit"),
    offset: int = Query(0, ge=0, description="Pagination offset"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_session),
) -> FeedbackListResponse:
    """
    Get all feedback with filtering and pagination.
    
    Note: In MVP, this is accessible to all authenticated users.
    Future: Add admin role check.
    """
    try:
        # Build query
        stmt = select(InsightFeedback)
        
        # Apply filters
        if insight_type:
            stmt = stmt.where(InsightFeedback.insight_type == insight_type)
        if is_helpful is not None:
            stmt = stmt.where(InsightFeedback.is_helpful == is_helpful)
        if start_date:
            stmt = stmt.where(InsightFeedback.created_at >= start_date)
        if end_date:
            stmt = stmt.where(InsightFeedback.created_at <= end_date)
        
        # Get total count
        count_stmt = select(func.count()).select_from(stmt.subquery())
        total_result = await db.execute(count_stmt)
        total = total_result.scalar() or 0
        
        # Apply pagination
        stmt = stmt.order_by(InsightFeedback.created_at.desc())
        stmt = stmt.limit(limit).offset(offset)
        
        # Execute query
        result = await db.execute(stmt)
        feedback_items = result.scalars().all()
        
        # Convert to response
        feedback_list = [
            FeedbackItem(
                id=str(f.id),
                insight_id=f.insight_id,
                insight_type=f.insight_type,
                insight_title=f.insight_title,
                is_helpful=f.is_helpful,
                comment=f.comment,
                user_id=str(f.user_id),
                organization_id=str(f.organization_id),
                created_at=f.created_at.isoformat(),
            )
            for f in feedback_items
        ]
        
        return FeedbackListResponse(
            total=total,
            feedback=feedback_list,
        )
        
    except Exception as e:
        logger.error("Error fetching all feedback: %s", e, exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to fetch feedback: {str(e)}",
        )


@router.get(
    "/admin/summary",
    response_model=FeedbackSummaryResponse,
    summary="Get feedback summary (admin)",
    description="Get aggregated feedback summary by insight (admin only).",
)
async def get_feedback_summary(
    insight_type: Optional[str] = Query(None, description="Filter by insight type"),
    start_date: Optional[datetime] = Query(None, description="Filter by start date"),
    end_date: Optional[datetime] = Query(None, description="Filter by end date"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_session),
) -> FeedbackSummaryResponse:
    """
    Get aggregated feedback summary.
    
    Groups feedback by insight_type and insight_title, calculating
    helpful percentages and including sample comments.
    
    Note: In MVP, this is accessible to all authenticated users.
    Future: Add admin role check.
    """
    try:
        # Build base query
        stmt = select(InsightFeedback)
        
        # Apply filters
        if insight_type:
            stmt = stmt.where(InsightFeedback.insight_type == insight_type)
        if start_date:
            stmt = stmt.where(InsightFeedback.created_at >= start_date)
        if end_date:
            stmt = stmt.where(InsightFeedback.created_at <= end_date)
        
        # Execute query
        result = await db.execute(stmt)
        all_feedback = result.scalars().all()
        
        # Aggregate by insight_type and insight_title
        summary_dict: dict[tuple[str, str], dict] = {}
        
        for feedback in all_feedback:
            key = (feedback.insight_type, feedback.insight_title)
            
            if key not in summary_dict:
                summary_dict[key] = {
                    "insight_type": feedback.insight_type,
                    "insight_title": feedback.insight_title,
                    "total_feedback": 0,
                    "helpful_count": 0,
                    "not_helpful_count": 0,
                    "comments": [],
                }
            
            summary_dict[key]["total_feedback"] += 1
            if feedback.is_helpful:
                summary_dict[key]["helpful_count"] += 1
            else:
                summary_dict[key]["not_helpful_count"] += 1
            
            # Collect comments (up to 10 per insight)
            if feedback.comment and len(summary_dict[key]["comments"]) < 10:
                summary_dict[key]["comments"].append({
                    "comment": feedback.comment,
                    "is_helpful": feedback.is_helpful,
                    "created_at": feedback.created_at.isoformat(),
                })
        
        # Convert to response format
        summary_items = []
        total_helpful = 0
        total_not_helpful = 0
        
        for key, data in summary_dict.items():
            helpful_pct = (
                (data["helpful_count"] / data["total_feedback"] * 100)
                if data["total_feedback"] > 0
                else 0.0
            )
            
            summary_items.append(
                FeedbackSummaryItem(
                    insight_type=data["insight_type"],
                    insight_title=data["insight_title"],
                    total_feedback=data["total_feedback"],
                    helpful_count=data["helpful_count"],
                    not_helpful_count=data["not_helpful_count"],
                    helpful_percentage=round(helpful_pct, 1),
                    comments=data["comments"],
                )
            )
            
            total_helpful += data["helpful_count"]
            total_not_helpful += data["not_helpful_count"]
        
        # Calculate overall stats
        total_feedback = total_helpful + total_not_helpful
        overall_helpful_pct = (
            (total_helpful / total_feedback * 100) if total_feedback > 0 else 0.0
        )
        
        return FeedbackSummaryResponse(
            summary=summary_items,
            overall_stats=OverallStats(
                total_feedback=total_feedback,
                helpful_count=total_helpful,
                not_helpful_count=total_not_helpful,
                helpful_percentage=round(overall_helpful_pct, 1),
            ),
        )
        
    except Exception as e:
        logger.error("Error fetching feedback summary: %s", e, exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to fetch feedback summary: {str(e)}",
        )

