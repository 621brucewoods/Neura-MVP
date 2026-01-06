"""
Feedback Schemas
Pydantic models for feedback API requests and responses.
"""

from typing import Optional
from pydantic import BaseModel, Field, ConfigDict, field_validator


class FeedbackSubmitRequest(BaseModel):
    """Request to submit feedback on an insight."""
    
    insight_id: str = Field(..., description="Unique identifier of the insight")
    insight_type: str = Field(..., description="Type of insight")
    insight_title: str = Field(..., description="Title of the insight")
    is_helpful: bool = Field(..., description="Whether the insight was helpful (true) or not helpful (false)")
    comment: Optional[str] = Field(None, max_length=500, description="Optional comment (max 500 characters)")
    
    @field_validator("comment")
    @classmethod
    def validate_comment(cls, v: Optional[str]) -> Optional[str]:
        """Validate comment length."""
        if v is not None and len(v) > 500:
            raise ValueError("Comment must be 500 characters or less")
        return v


class FeedbackResponse(BaseModel):
    """Response after submitting feedback."""
    
    id: str = Field(..., description="Feedback ID")
    message: str = Field(..., description="Success message")
    created_at: str = Field(..., description="ISO timestamp when feedback was created")
    updated_at: Optional[str] = Field(None, description="ISO timestamp when feedback was updated (if updated)")


class UserFeedbackResponse(BaseModel):
    """User's feedback for a specific insight."""
    
    insight_id: str = Field(..., description="Insight ID")
    is_helpful: bool = Field(..., description="Whether insight was helpful")
    comment: Optional[str] = Field(None, description="User comment")
    submitted_at: str = Field(..., description="ISO timestamp when feedback was submitted")


class FeedbackItem(BaseModel):
    """Single feedback item (for admin endpoints)."""
    
    model_config = ConfigDict(extra="allow")
    
    id: str = Field(..., description="Feedback ID")
    insight_id: str = Field(..., description="Insight ID")
    insight_type: str = Field(..., description="Type of insight")
    insight_title: str = Field(..., description="Title of insight")
    is_helpful: bool = Field(..., description="Whether insight was helpful")
    comment: Optional[str] = Field(None, description="User comment")
    user_id: str = Field(..., description="User ID who provided feedback")
    organization_id: str = Field(..., description="Organization ID")
    created_at: str = Field(..., description="ISO timestamp")


class FeedbackListResponse(BaseModel):
    """List of feedback items with pagination."""
    
    total: int = Field(..., description="Total number of feedback items")
    feedback: list[FeedbackItem] = Field(..., description="List of feedback items")


class FeedbackSummaryItem(BaseModel):
    """Summary item for aggregated feedback."""
    
    model_config = ConfigDict(extra="allow")
    
    insight_type: str = Field(..., description="Type of insight")
    insight_title: str = Field(..., description="Title of insight")
    total_feedback: int = Field(..., description="Total number of feedback items")
    helpful_count: int = Field(..., description="Number of helpful feedbacks")
    not_helpful_count: int = Field(..., description="Number of not helpful feedbacks")
    helpful_percentage: float = Field(..., description="Percentage of helpful feedbacks")
    comments: list[dict] = Field(default_factory=list, description="Sample comments")


class OverallStats(BaseModel):
    """Overall feedback statistics."""
    
    total_feedback: int = Field(..., description="Total feedback count")
    helpful_count: int = Field(..., description="Helpful feedback count")
    not_helpful_count: int = Field(..., description="Not helpful feedback count")
    helpful_percentage: float = Field(..., description="Helpful percentage")


class FeedbackSummaryResponse(BaseModel):
    """Aggregated feedback summary."""
    
    summary: list[FeedbackSummaryItem] = Field(..., description="Summary by insight")
    overall_stats: OverallStats = Field(..., description="Overall statistics")

