"""
Authentication Router
API endpoints for user authentication with security features.
"""

import logging
from datetime import datetime, timedelta, timezone
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from slowapi.util import get_remote_address
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import CurrentUser
from app.auth.rate_limit import limiter
from app.auth.schemas import (
    SignupRequest,
    LoginRequest,
    RefreshRequest,
    TokenResponse,
    UserWithOrgResponse,
    ChangePasswordRequest,
)
from app.auth.service import AuthService
from app.auth.utils import (
    create_access_token,
    create_refresh_token,
    decode_token,
    validate_password_strength,
)
from app.config import settings
from app.database import get_async_session

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/auth", tags=["Authentication"])


@router.post(
    "/signup",
    response_model=TokenResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Register new user",
    description="Create a new user account with an organization.",
)
@limiter.limit("10/hour")
async def signup(
    request: Request,
    signup_data: SignupRequest,
    session: Annotated[AsyncSession, Depends(get_async_session)],
) -> TokenResponse:
    """
    Register a new user.
    
    Creates:
    - User account with hashed password
    - Organization linked to user
    - JWT access and refresh tokens
    
    Rate limited to 10 requests per hour per IP.
    """
    # Validate password strength
    is_valid, error_message = validate_password_strength(signup_data.password)
    if not is_valid:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=error_message,
        )
    
    auth_service = AuthService(session)
    
    try:
        user = await auth_service.create_user(
            email=signup_data.email,
            password=signup_data.password,
            organization_name=signup_data.organization_name,
        )
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(e),
        )
    
    # Create tokens
    access_token = create_access_token(subject=str(user.id))
    refresh_token = create_refresh_token(subject=str(user.id))
    
    # Store refresh token
    expires_at = datetime.now(timezone.utc) + timedelta(days=settings.refresh_token_expire_days)
    await auth_service.store_refresh_token(user.id, refresh_token, expires_at)
    
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
@limiter.limit("5/15minutes")
async def login(
    request: Request,
    login_data: LoginRequest,
    session: Annotated[AsyncSession, Depends(get_async_session)],
) -> TokenResponse:
    """
    Authenticate user and return tokens.
    
    Validates email and password, returns JWT tokens if valid.
    Implements account lockout after failed attempts.
    
    Rate limited to 5 requests per 15 minutes per IP.
    """
    auth_service = AuthService(session)
    ip_address = get_remote_address(request)
    
    user, is_locked = await auth_service.authenticate(
        email=login_data.email,
        password=login_data.password,
        ip_address=ip_address,
    )
    
    if is_locked:
        raise HTTPException(
            status_code=status.HTTP_423_LOCKED,
            detail="Account is temporarily locked due to too many failed login attempts",
        )
    
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password",
        )
    
    # Create tokens
    access_token = create_access_token(subject=str(user.id))
    refresh_token = create_refresh_token(subject=str(user.id))
    
    # Store refresh token
    expires_at = datetime.now(timezone.utc) + timedelta(days=settings.refresh_token_expire_days)
    await auth_service.store_refresh_token(user.id, refresh_token, expires_at)
    
    return TokenResponse(
        access_token=access_token,
        refresh_token=refresh_token,
    )


@router.post(
    "/refresh",
    response_model=TokenResponse,
    summary="Refresh access token",
    description="Get new access token using refresh token (with rotation).",
)
@limiter.limit("10/hour")
async def refresh(
    request: Request,
    refresh_data: RefreshRequest,
    session: Annotated[AsyncSession, Depends(get_async_session)],
) -> TokenResponse:
    """
    Refresh access token with token rotation.
    
    Validates refresh token, marks it as used (one-time use),
    and returns new access and refresh tokens.
    
    Rate limited to 10 requests per hour per IP.
    """
    auth_service = AuthService(session)
    
    # Validate refresh token (checks database for one-time use)
    is_valid, user_id = await auth_service.validate_refresh_token(refresh_data.refresh_token)
    
    if not is_valid or not user_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired refresh token",
        )
    
    user = await auth_service.get_user_by_id(user_id)
    
    if not user or not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found or inactive",
        )
    
    # Create new tokens (token rotation)
    access_token = create_access_token(subject=str(user.id))
    new_refresh_token = create_refresh_token(subject=str(user.id))
    
    # Store new refresh token
    expires_at = datetime.now(timezone.utc) + timedelta(days=settings.refresh_token_expire_days)
    await auth_service.store_refresh_token(user.id, new_refresh_token, expires_at)
    
    return TokenResponse(
        access_token=access_token,
        refresh_token=new_refresh_token,
    )


@router.post(
    "/logout",
    summary="Logout user",
    description="Revoke current session tokens.",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def logout(
    request: Request,
    current_user: CurrentUser,
    session: Annotated[AsyncSession, Depends(get_async_session)],
    credentials: Annotated[HTTPAuthorizationCredentials, Depends(HTTPBearer())],
) -> None:
    """
    Logout user and revoke tokens.
    
    Revokes all refresh tokens for the user and blacklists the current access token.
    """
    auth_service = AuthService(session)
    
    # Decode token to get JTI
    payload = decode_token(credentials.credentials)
    if payload and payload.get("jti"):
        expires_at = datetime.fromtimestamp(payload.get("exp"), tz=timezone.utc)
        await auth_service.blacklist_token(
            jti=payload.get("jti"),
            token=credentials.credentials,
            user_id=current_user.id,
            expires_at=expires_at,
        )
    
    # Revoke all refresh tokens
    await auth_service.revoke_user_tokens(current_user.id)
    
    logger.info(f"User logged out: {current_user.id}")


@router.post(
    "/change-password",
    summary="Change password",
    description="Change user password (requires current password).",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def change_password(
    request: Request,
    password_data: ChangePasswordRequest,
    current_user: CurrentUser,
    session: Annotated[AsyncSession, Depends(get_async_session)],
) -> None:
    """
    Change user password.
    
    Requires current password for verification.
    Validates new password strength.
    """
    # Validate new password strength
    is_valid, error_message = validate_password_strength(password_data.new_password)
    if not is_valid:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=error_message,
        )
    
    auth_service = AuthService(session)
    
    success = await auth_service.change_password(
        user_id=current_user.id,
        current_password=password_data.current_password,
        new_password=password_data.new_password,
    )
    
    if not success:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid current password",
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

