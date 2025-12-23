"""
Authentication Package
Handles user authentication, JWT tokens, and authorization.
"""

from app.auth.dependencies import CurrentUser, get_current_user
from app.auth.schemas import (
    LoginRequest,
    RefreshRequest,
    SignupRequest,
    TokenResponse,
    UserResponse,
    UserWithOrgResponse,
)
from app.auth.service import AuthService
from app.auth.utils import (
    create_access_token,
    create_refresh_token,
    decode_token,
    hash_password,
    verify_password,
)

__all__ = [
    # Dependencies
    "CurrentUser",
    "get_current_user",
    # Schemas
    "LoginRequest",
    "RefreshRequest",
    "SignupRequest",
    "TokenResponse",
    "UserResponse",
    "UserWithOrgResponse",
    # Service
    "AuthService",
    # Utils
    "create_access_token",
    "create_refresh_token",
    "decode_token",
    "hash_password",
    "verify_password",
]
