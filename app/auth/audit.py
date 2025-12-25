"""
Security Audit Logging
Logs authentication events for security monitoring.
"""

import logging
from datetime import datetime, timezone
from typing import Optional
from uuid import UUID

logger = logging.getLogger("auth.audit")


def log_auth_event(
    event_type: str,
    user_id: Optional[UUID] = None,
    email: Optional[str] = None,
    ip_address: Optional[str] = None,
    success: bool = True,
    details: Optional[str] = None,
) -> None:
    """
    Log an authentication event for security auditing.
    
    Args:
        event_type: Type of event (e.g., "login", "signup", "logout", "password_reset")
        user_id: User ID if available
        email: Email address if available
        ip_address: IP address of the request
        success: Whether the event was successful
        details: Additional details about the event
    """
    log_data = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "event_type": event_type,
        "user_id": str(user_id) if user_id else None,
        "email": email,
        "ip_address": ip_address,
        "success": success,
        "details": details,
    }
    
    if success:
        logger.info(f"Auth event: {event_type}", extra=log_data)
    else:
        logger.warning(f"Auth event failed: {event_type}", extra=log_data)


def log_login_attempt(
    email: str,
    ip_address: str,
    success: bool,
    user_id: Optional[UUID] = None,
    reason: Optional[str] = None,
) -> None:
    """Log a login attempt."""
    log_auth_event(
        event_type="login",
        user_id=user_id,
        email=email,
        ip_address=ip_address,
        success=success,
        details=reason,
    )


def log_signup(email: str, ip_address: str, user_id: UUID) -> None:
    """Log a user signup."""
    log_auth_event(
        event_type="signup",
        user_id=user_id,
        email=email,
        ip_address=ip_address,
        success=True,
    )


def log_logout(user_id: UUID, ip_address: str) -> None:
    """Log a user logout."""
    log_auth_event(
        event_type="logout",
        user_id=user_id,
        ip_address=ip_address,
        success=True,
    )


def log_password_reset_request(email: str, ip_address: str, user_id: UUID) -> None:
    """Log a password reset request."""
    log_auth_event(
        event_type="password_reset_request",
        user_id=user_id,
        email=email,
        ip_address=ip_address,
        success=True,
    )


def log_password_reset_complete(email: str, ip_address: str, user_id: UUID) -> None:
    """Log a successful password reset."""
    log_auth_event(
        event_type="password_reset_complete",
        user_id=user_id,
        email=email,
        ip_address=ip_address,
        success=True,
    )


def log_password_change(user_id: UUID, ip_address: str) -> None:
    """Log a password change."""
    log_auth_event(
        event_type="password_change",
        user_id=user_id,
        ip_address=ip_address,
        success=True,
    )


def log_email_verification(user_id: UUID, email: str) -> None:
    """Log email verification."""
    log_auth_event(
        event_type="email_verification",
        user_id=user_id,
        email=email,
        success=True,
    )


def log_account_locked(email: str, ip_address: str, user_id: Optional[UUID] = None) -> None:
    """Log account lockout."""
    log_auth_event(
        event_type="account_locked",
        user_id=user_id,
        email=email,
        ip_address=ip_address,
        success=False,
        details="Account locked due to too many failed login attempts",
    )

