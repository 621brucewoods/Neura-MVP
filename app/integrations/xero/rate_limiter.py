"""
Xero Rate Limiter
Enforces Xero's API rate limits (60 calls/minute per organization).
"""

import asyncio
import logging
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Optional
from uuid import UUID

from app.config import settings

logger = logging.getLogger(__name__)


class XeroRateLimiter:
    """
    Rate limiter for Xero API calls.
    
    Enforces 60 calls per minute per organization limit.
    Tracks call timestamps and waits if limit would be exceeded.
    """
    
    def __init__(self, calls_per_minute: int = 60):
        """
        Initialize rate limiter.
        
        Args:
            calls_per_minute: Maximum calls per minute (default: 60, Xero's limit)
        """
        self.calls_per_minute = calls_per_minute
        self._call_timestamps: dict[UUID, list[datetime]] = defaultdict(list)
        self._lock = asyncio.Lock()
    
    async def wait_if_needed(self, organization_id: UUID) -> None:
        """
        Wait if necessary to respect rate limit.
        
        Checks if making a call would exceed the rate limit.
        If so, waits until the oldest call in the current window expires.
        
        Args:
            organization_id: Organization UUID
        """
        async with self._lock:
            now = datetime.now(timezone.utc)
            cutoff_time = now - timedelta(minutes=1)
            
            # Get call timestamps for this organization
            timestamps = self._call_timestamps[organization_id]
            
            # Remove timestamps older than 1 minute
            timestamps[:] = [ts for ts in timestamps if ts > cutoff_time]
            
            # Check if we're at the limit
            if len(timestamps) >= self.calls_per_minute:
                # Wait until the oldest call expires
                oldest_call = min(timestamps)
                wait_until = oldest_call + timedelta(minutes=1)
                wait_seconds = (wait_until - now).total_seconds()
                
                if wait_seconds > 0:
                    logger.info(
                        "Rate limit reached for org %s. Waiting %.1f seconds...",
                        organization_id,
                        wait_seconds
                    )
                    await asyncio.sleep(wait_seconds)
    
    async def record_call(self, organization_id: UUID) -> None:
        """
        Record an API call for rate limiting.
        
        Args:
            organization_id: Organization UUID
        """
        async with self._lock:
            now = datetime.now(timezone.utc)
            self._call_timestamps[organization_id].append(now)
            
            # Clean up old timestamps (older than 2 minutes)
            cutoff_time = now - timedelta(minutes=2)
            timestamps = self._call_timestamps[organization_id]
            timestamps[:] = [ts for ts in timestamps if ts > cutoff_time]

