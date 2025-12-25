"""
Rate Limiting Utilities
Simple rate limiting configuration for authentication endpoints.
"""

from slowapi import Limiter
from slowapi.util import get_remote_address

# Initialize rate limiter
limiter = Limiter(key_func=get_remote_address)
