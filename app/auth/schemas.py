"""
Authentication Schemas
Request and response models for auth endpoints.
"""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, EmailStr, Field


# =============================================================================
# Request Schemas
# =============================================================================

class SignupRequest(BaseModel):
    """Request body for user registration."""
    
    email: EmailStr = Field(..., description="User email address")
    password: str = Field(..., min_length=8, description="Password (min 8 characters)")
    organization_name: str = Field(..., min_length=1, max_length=255, description="Organization/business name")


class LoginRequest(BaseModel):
    """Request body for user login."""
    
    email: EmailStr = Field(..., description="User email address")
    password: str = Field(..., description="User password")


class RefreshRequest(BaseModel):
    """Request body for token refresh."""
    
    refresh_token: str = Field(..., description="Valid refresh token")


class ChangePasswordRequest(BaseModel):
    """Request body for password change."""
    
    current_password: str = Field(..., description="Current password for verification")
    new_password: str = Field(..., min_length=8, description="New password (min 8 characters)")


# =============================================================================
# Response Schemas
# =============================================================================

class TokenResponse(BaseModel):
    """Response containing JWT tokens."""
    
    access_token: str = Field(..., description="JWT access token")
    refresh_token: str = Field(..., description="JWT refresh token")
    token_type: str = Field(default="bearer", description="Token type")


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
    role: str = Field(default="user", description="User role (user or admin)")
    
    model_config = {"from_attributes": True}

