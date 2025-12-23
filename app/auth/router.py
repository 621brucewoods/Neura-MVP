"""
Authentication Router
API endpoints for user authentication.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import CurrentUser
from app.auth.utils import (
    create_access_token,
    create_refresh_token,
    decode_token,
)
from app.database import get_async_session
from app.schemas import (
    SignupRequest,
    LoginRequest,
    RefreshRequest,
    TokenResponse,
    UserResponse,
)
from app.schemas.user import UserWithOrgResponse
from app.services.user_service import UserService

router = APIRouter(prefix="/auth", tags=["Authentication"])


@router.post(
    "/signup",
    response_model=TokenResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Register new user",
    description="Create a new user account with an organization.",
)
async def signup(
    request: SignupRequest,
    session: Annotated[AsyncSession, Depends(get_async_session)],
) -> TokenResponse:
    """
    Register a new user.
    
    Creates:
    - User account with hashed password
    - Organization linked to user
    - JWT access and refresh tokens
    """
    user_service = UserService(session)
    
    # Check if email already exists
    if await user_service.email_exists(request.email):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Email already registered",
        )
    
    # Create user and organization
    user = await user_service.create(
        email=request.email,
        password=request.password,
        organization_name=request.organization_name,
    )
    
    # Generate tokens
    access_token = create_access_token(subject=str(user.id))
    refresh_token = create_refresh_token(subject=str(user.id))
    
    return TokenResponse(
        access_token=access_token,
        refresh_token=refresh_token,
    )


@router.post(
    "/login",
    response_model=TokenResponse,
    summary="User login",
    description="Authenticate user and return JWT tokens.",
)
async def login(
    request: LoginRequest,
    session: Annotated[AsyncSession, Depends(get_async_session)],
) -> TokenResponse:
    """
    Authenticate user and return tokens.
    
    Validates email and password, returns JWT tokens if valid.
    """
    user_service = UserService(session)
    
    # Authenticate user
    user = await user_service.authenticate(
        email=request.email,
        password=request.password,
    )
    
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password",
        )
    
    # Generate tokens
    access_token = create_access_token(subject=str(user.id))
    refresh_token = create_refresh_token(subject=str(user.id))
    
    return TokenResponse(
        access_token=access_token,
        refresh_token=refresh_token,
    )


@router.post(
    "/refresh",
    response_model=TokenResponse,
    summary="Refresh access token",
    description="Get new access token using refresh token.",
)
async def refresh(
    request: RefreshRequest,
    session: Annotated[AsyncSession, Depends(get_async_session)],
) -> TokenResponse:
    """
    Refresh access token.
    
    Validates refresh token and returns new access token.
    Also returns new refresh token (token rotation).
    """
    # Decode refresh token
    payload = decode_token(request.refresh_token)
    
    if not payload:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired refresh token",
        )
    
    # Verify token type
    if payload.get("type") != "refresh":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token type",
        )
    
    # Get user ID
    user_id_str = payload.get("sub")
    if not user_id_str:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token payload",
        )
    
    # Verify user still exists and is active
    from uuid import UUID
    user_service = UserService(session)
    user = await user_service.get_by_id(UUID(user_id_str))
    
    if not user or not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found or inactive",
        )
    
    # Generate new tokens
    access_token = create_access_token(subject=str(user.id))
    refresh_token = create_refresh_token(subject=str(user.id))
    
    return TokenResponse(
        access_token=access_token,
        refresh_token=refresh_token,
    )


@router.get(
    "/me",
    response_model=UserWithOrgResponse,
    summary="Get current user",
    description="Get authenticated user's profile.",
)
async def get_me(current_user: CurrentUser) -> UserWithOrgResponse:
    """
    Get current authenticated user's profile.
    
    Requires valid access token in Authorization header.
    """
    return UserWithOrgResponse(
        id=current_user.id,
        email=current_user.email,
        is_active=current_user.is_active,
        is_verified=current_user.is_verified,
        created_at=current_user.created_at,
        organization_id=current_user.organization.id if current_user.organization else None,
        organization_name=current_user.organization.name if current_user.organization else None,
    )

