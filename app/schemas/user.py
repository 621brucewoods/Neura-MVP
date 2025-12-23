"""
User Schemas
Response models for user data.
"""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, EmailStr, Field


class UserResponse(BaseModel):
    """User data returned in API responses."""
    
    id: UUID = Field(..., description="User unique identifier")
    email: EmailStr = Field(..., description="User email address")
    is_active: bool = Field(..., description="Whether user account is active")
    is_verified: bool = Field(..., description="Whether email is verified")
    created_at: datetime = Field(..., description="Account creation timestamp")
    
    model_config = {"from_attributes": True}


class UserWithOrgResponse(BaseModel):
    """User data with organization info."""
    
    id: UUID = Field(..., description="User unique identifier")
    email: EmailStr = Field(..., description="User email address")
    is_active: bool = Field(..., description="Whether user account is active")
    is_verified: bool = Field(..., description="Whether email is verified")
    created_at: datetime = Field(..., description="Account creation timestamp")
    organization_id: UUID | None = Field(None, description="Organization ID")
    organization_name: str | None = Field(None, description="Organization name")
    
    model_config = {"from_attributes": True}

