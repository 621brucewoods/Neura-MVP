"""
Token Refresh Lock
Provides per-organization async locks to prevent token refresh race conditions.
"""

import asyncio
import logging
from typing import Optional
from uuid import UUID

logger = logging.getLogger(__name__)


class TokenRefreshLock:
    """
    Manages async locks for token refresh operations per organization.
    
    Prevents race conditions where multiple concurrent API calls trigger
    simultaneous token refreshes, causing invalid_grant errors.
    """
    
    _locks: dict[UUID, asyncio.Lock] = {}
    _lock_creation_lock = asyncio.Lock()
    
    @classmethod
    async def get_lock(cls, organization_id: UUID) -> asyncio.Lock:
        """
        Get or create an async lock for an organization.
        
        Thread-safe lock creation ensures only one lock exists per organization.
        
        Args:
            organization_id: Organization UUID
            
        Returns:
            asyncio.Lock instance for the organization
        """
        # Check if lock already exists (fast path)
        if organization_id in cls._locks:
            return cls._locks[organization_id]
        
        # Create lock with thread-safe creation
        async with cls._lock_creation_lock:
            # Double-check after acquiring creation lock
            if organization_id not in cls._locks:
                cls._locks[organization_id] = asyncio.Lock()
                logger.debug("Created token refresh lock for organization %s", organization_id)
            
            return cls._locks[organization_id]
    
    @classmethod
    def release_lock(cls, organization_id: UUID) -> None:
        """
        Release a lock for an organization (optional cleanup).
        
        Note: Locks are kept in memory for reuse. This is only needed
        if you want to explicitly clean up locks for disconnected organizations.
        
        Args:
            organization_id: Organization UUID
        """
        if organization_id in cls._locks:
            del cls._locks[organization_id]
            logger.debug("Released token refresh lock for organization %s", organization_id)

