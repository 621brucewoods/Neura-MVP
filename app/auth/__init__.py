"""
Authentication Package - Supabase Integration
Handles user authentication via Supabase and authorization.
"""

from app.auth.dependencies import CurrentUser, get_current_user, get_admin_user, AdminUser
from app.auth.schemas import UserResponse, UserWithOrgResponse
from app.auth.service import AuthService

__all__ = [
    # Dependencies
    "CurrentUser",
    "get_current_user",
    "get_admin_user",
    "AdminUser",
    # Schemas
    "UserResponse",
    "UserWithOrgResponse",
    # Service
    "AuthService",
]
