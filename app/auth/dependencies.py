"""
Authentication Dependencies
FastAPI dependencies for route protection.
"""

from typing import Annotated
from uuid import UUID

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.service import AuthService
from app.auth.utils import decode_token
from app.database import get_async_session
from app.models import User

# Security scheme for Swagger UI
security = HTTPBearer()


async def get_current_user(
    credentials: Annotated[HTTPAuthorizationCredentials, Depends(security)],
    session: Annotated[AsyncSession, Depends(get_async_session)],
) -> User:
    """
    Dependency that validates JWT token and returns current user.
    
    Usage:
        @app.get("/protected")
        async def protected_route(user: User = Depends(get_current_user)):
            return {"user_id": user.id}
    
    Args:
        credentials: Bearer token from Authorization header
        session: Database session
        
    Returns:
        Authenticated User instance
        
    Raises:
        HTTPException: If token is invalid or user not found
    """
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid or expired token",
        headers={"WWW-Authenticate": "Bearer"},
    )
    
    payload = decode_token(credentials.credentials)
    if not payload:
        raise credentials_exception
    
    if payload.get("type") != "access":
        raise credentials_exception
    
    # Check if token is blacklisted
    auth_service = AuthService(session)
    jti = payload.get("jti")
    if jti and await auth_service.is_token_blacklisted(jti):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token has been revoked",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    user_id_str = payload.get("sub")
    if not user_id_str:
        raise credentials_exception
    
    try:
        user_id = UUID(user_id_str)
    except ValueError:
        raise credentials_exception
    
    user = await auth_service.get_user_by_id(user_id)
    
    if not user:
        raise credentials_exception
    
    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User account is deactivated",
        )
    
    # Check if account is locked
    if user.is_locked():
        raise HTTPException(
            status_code=status.HTTP_423_LOCKED,
            detail="Account is temporarily locked",
        )
    
    return user


# Type alias for cleaner route signatures
CurrentUser = Annotated[User, Depends(get_current_user)]


async def get_admin_user(
    current_user: User = Depends(get_current_user),
) -> User:
    """
    Dependency that ensures user has admin role.
    
    Usage:
        @app.get("/admin-only")
        async def admin_route(admin: User = Depends(get_admin_user)):
            return {"message": "Admin access"}
    
    Args:
        current_user: Authenticated user from get_current_user
        
    Returns:
        User instance (guaranteed to be admin)
        
    Raises:
        HTTPException: If user is not an admin
    """
    if not current_user.is_admin():
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin access required",
        )
    return current_user


# Type alias for admin routes
AdminUser = Annotated[User, Depends(get_admin_user)]
