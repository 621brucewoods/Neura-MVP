"""
Authentication Schemas
Request and response models for auth endpoints.
"""

from pydantic import BaseModel, EmailStr, Field


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


class TokenResponse(BaseModel):
    """Response containing JWT tokens."""
    
    access_token: str = Field(..., description="JWT access token")
    refresh_token: str = Field(..., description="JWT refresh token")
    token_type: str = Field(default="bearer", description="Token type")

