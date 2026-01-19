"""
Authentication Router - Supabase Integration
Minimal auth endpoints (most auth handled by Supabase).
"""

import logging
from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import CurrentUser
from app.auth.schemas import UserWithOrgResponse
from app.database import get_async_session

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/auth", tags=["Authentication"])


@router.get(
    "/me",
    response_model=UserWithOrgResponse,
    summary="Get current user",
    description="Get authenticated user's profile from Supabase session.",
)
async def get_me(
    current_user: CurrentUser,
) -> UserWithOrgResponse:
    """
    Get current authenticated user's profile.
    
    Requires valid Supabase JWT token in Authorization header.
    """
    return UserWithOrgResponse(
        id=current_user.id,
        email=current_user.email,
        is_active=current_user.is_active,
        is_verified=True,  # Supabase handles verification
        created_at=current_user.created_at,
        organization_id=current_user.organization.id if current_user.organization else None,
        organization_name=current_user.organization.name if current_user.organization else None,
    )
