"""
Authentication Dependencies - Supabase Integration
Validates Supabase JWT tokens and returns authenticated users.
"""

from typing import Annotated
from uuid import UUID

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.service import AuthService
from app.auth.supabase_client import supabase
from app.database import get_async_session
from app.models import User

# Security scheme for Swagger UI
security = HTTPBearer()


async def get_current_user(
    credentials: Annotated[HTTPAuthorizationCredentials, Depends(security)],
    session: Annotated[AsyncSession, Depends(get_async_session)],
) -> User:
    """
    Validate Supabase JWT token and return current user.
    
    Flow:
    1. Extract token from Authorization header
    2. Validate token with Supabase
    3. Get or create User record in our database
    4. Return User instance
    
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
    token = credentials.credentials
    
    # Validate token with Supabase
    try:
        response = supabase.auth.get_user(token)
        supabase_user = response.user
        
        if not supabase_user:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid or expired token",
                headers={"WWW-Authenticate": "Bearer"},
            )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    # Get or create User record in our database
    # Extract organization_name from user metadata if available
    organization_name = None
    if supabase_user.user_metadata:
        organization_name = supabase_user.user_metadata.get("organization_name")
    
    auth_service = AuthService(session)
    user = await auth_service.get_or_create_user(
        supabase_user_id=UUID(supabase_user.id),
        email=supabase_user.email or "",
        organization_name=organization_name,
    )
    
    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User account is deactivated",
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
