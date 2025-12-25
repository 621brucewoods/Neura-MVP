"""
Authentication Utilities
Password hashing, JWT token management, and security utilities.
"""

import hashlib
import re
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any

from jose import JWTError, jwt
from passlib.context import CryptContext

from app.config import settings

# Password hashing context
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def hash_password(password: str) -> str:
    """
    Hash a plain text password using bcrypt.
    
    Args:
        password: Plain text password
        
    Returns:
        Hashed password string
    """
    return pwd_context.hash(password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """
    Verify a plain text password against a hashed password.
    
    Args:
        plain_password: Plain text password to verify
        hashed_password: Hashed password to compare against
        
    Returns:
        True if password matches, False otherwise
    """
    return pwd_context.verify(plain_password, hashed_password)


def create_access_token(subject: str, extra_data: dict[str, Any] | None = None) -> str:
    """
    Create a JWT access token with JTI (JWT ID) for revocation tracking.
    
    Args:
        subject: Token subject (typically user ID)
        extra_data: Additional data to include in token payload
        
    Returns:
        Encoded JWT token string
    """
    expire = datetime.now(timezone.utc) + timedelta(minutes=settings.access_token_expire_minutes)
    jti = secrets.token_urlsafe(32)
    
    payload = {
        "sub": subject,
        "exp": expire,
        "type": "access",
        "iat": datetime.now(timezone.utc),
        "jti": jti,
    }
    
    if extra_data:
        payload.update(extra_data)
    
    return jwt.encode(payload, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)


def create_refresh_token(subject: str) -> str:
    """
    Create a JWT refresh token.
    
    Args:
        subject: Token subject (typically user ID)
        
    Returns:
        Encoded JWT refresh token string
    """
    expire = datetime.now(timezone.utc) + timedelta(days=settings.refresh_token_expire_days)
    
    payload = {
        "sub": subject,
        "exp": expire,
        "type": "refresh",
        "iat": datetime.now(timezone.utc),
    }
    
    return jwt.encode(payload, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)


def decode_token(token: str) -> dict[str, Any] | None:
    """
    Decode and validate a JWT token.
    
    Args:
        token: JWT token string
        
    Returns:
        Token payload dict if valid, None otherwise
    """
    try:
        payload = jwt.decode(
            token,
            settings.jwt_secret_key,
            algorithms=[settings.jwt_algorithm]
        )
        return payload
    except JWTError:
        return None


def normalize_email(email: str) -> str:
    return email.strip().lower()


def validate_password_strength(password: str) -> tuple[bool, str]:

    if len(password) < settings.password_min_length:
        return False, f"Password must be at least {settings.password_min_length} characters long"
    
    if settings.password_require_uppercase and not re.search(r"[A-Z]", password):
        return False, "Password must contain at least one uppercase letter"
    
    if settings.password_require_lowercase and not re.search(r"[a-z]", password):
        return False, "Password must contain at least one lowercase letter"
    
    if settings.password_require_numbers and not re.search(r"\d", password):
        return False, "Password must contain at least one number"
    
    if settings.password_require_special and not re.search(r"[!@#$%^&*(),.?\":{}|<>]", password):
        return False, "Password must contain at least one special character"
    
    return True, ""


def hash_token(token: str) -> str:
    """
    Hash a token using SHA256 for secure storage.
    
    Args:
        token: Token string to hash
        
    Returns:
        SHA256 hash of the token (hex string)
    """
    return hashlib.sha256(token.encode()).hexdigest()


def generate_jti() -> str:
    """
    Generate a unique JWT ID (JTI) for token tracking.
    
    Returns:
        URL-safe random token string
    """
    return secrets.token_urlsafe(32)

