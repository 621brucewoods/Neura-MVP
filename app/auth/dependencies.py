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
    
    user_id_str = payload.get("sub")
    if not user_id_str:
        raise credentials_exception
    
    try:
        user_id = UUID(user_id_str)
    except ValueError:
        raise credentials_exception
    
    auth_service = AuthService(session)
    user = await auth_service.get_user_by_id(user_id)
    
    if not user:
        raise credentials_exception
    
    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User account is deactivated",
        )
    
    return user


# Type alias for cleaner route signatures
CurrentUser = Annotated[User, Depends(get_current_user)]
