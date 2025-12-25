"""
Security Utilities
Password validation, email normalization, token hashing, and security helpers.
"""

import hashlib
import re
import secrets
from typing import Optional

from app.config import settings


def normalize_email(email: str) -> str:
    """
    Normalize email address to lowercase.
    
    Args:
        email: Email address to normalize
        
    Returns:
        Lowercase email address
    """
    return email.strip().lower()


def validate_password_strength(password: str) -> tuple[bool, Optional[str]]:
    """
    Validate password strength against requirements.
    
    Args:
        password: Password to validate
        
    Returns:
        Tuple of (is_valid, error_message)
        - is_valid: True if password meets requirements
        - error_message: Error message if invalid, None if valid
    """
    if len(password) < settings.password_min_length:
        return (
            False,
            f"Password must be at least {settings.password_min_length} characters long",
        )
    
    if settings.password_require_uppercase and not re.search(r"[A-Z]", password):
        return False, "Password must contain at least one uppercase letter"
    
    if settings.password_require_lowercase and not re.search(r"[a-z]", password):
        return False, "Password must contain at least one lowercase letter"
    
    if settings.password_require_digits and not re.search(r"\d", password):
        return False, "Password must contain at least one digit"
    
    if settings.password_require_special and not re.search(r"[!@#$%^&*(),.?\":{}|<>]", password):
        return False, "Password must contain at least one special character"
    
    return True, None


def generate_secure_token(length: int = 32) -> str:
    """
    Generate a cryptographically secure random token.
    
    Args:
        length: Length of token in bytes (default: 32)
        
    Returns:
        URL-safe base64 encoded token
    """
    return secrets.token_urlsafe(length)


def hash_token(token: str) -> str:
    """
    Hash a token using SHA256 for storage.
    
    Args:
        token: Token to hash
        
    Returns:
        SHA256 hash of the token (hex string)
    """
    return hashlib.sha256(token.encode()).hexdigest()


def generate_jti() -> str:
    """
    Generate a unique JWT ID (jti) for token tracking.
    
    Returns:
        URL-safe random string
    """
    return secrets.token_urlsafe(32)

