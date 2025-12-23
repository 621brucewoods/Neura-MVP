"""
OAuth State Store
Temporary storage for OAuth state → organization mapping.

In production, use Redis or database table.
For MVP, using in-memory dict with expiration.
"""

from datetime import datetime, timedelta, timezone
from typing import Optional
from uuid import UUID


class OAuthStateStore:
    """
    In-memory store for OAuth state tokens.
    
    Maps state → organization_id for callback lookup.
    States expire after 10 minutes (OAuth flow timeout).
    """
    
    # State storage: {state: (organization_id, expires_at)}
    _store: dict[str, tuple[UUID, datetime]] = {}
    
    # State lifetime (10 minutes should be plenty for OAuth flow)
    STATE_LIFETIME = timedelta(minutes=10)
    
    @classmethod
    def save_state(cls, state: str, organization_id: UUID) -> None:
        """
        Save state → organization mapping.
        
        Args:
            state: OAuth state token
            organization_id: Organization UUID
        """
        expires_at = datetime.now(timezone.utc) + cls.STATE_LIFETIME
        cls._store[state] = (organization_id, expires_at)
        
        # Cleanup expired states (simple garbage collection)
        cls._cleanup_expired()
    
    @classmethod
    def get_organization_id(cls, state: str) -> Optional[UUID]:
        """
        Get organization ID for a state token.
        
        Args:
            state: OAuth state token
            
        Returns:
            Organization UUID if valid and not expired, None otherwise
        """
        if state not in cls._store:
            return None
        
        organization_id, expires_at = cls._store[state]
        
        # Check expiration
        if datetime.now(timezone.utc) > expires_at:
            del cls._store[state]
            return None
        
        return organization_id
    
    @classmethod
    def consume_state(cls, state: str) -> Optional[UUID]:
        """
        Get and remove state (one-time use).
        
        Args:
            state: OAuth state token
            
        Returns:
            Organization UUID if valid, None otherwise
        """
        organization_id = cls.get_organization_id(state)
        
        if organization_id and state in cls._store:
            del cls._store[state]
        
        return organization_id
    
    @classmethod
    def _cleanup_expired(cls) -> None:
        """Remove expired states from store."""
        now = datetime.now(timezone.utc)
        expired_states = [
            state for state, (_, expires_at) in cls._store.items()
            if now > expires_at
        ]
        for state in expired_states:
            del cls._store[state]


# Singleton instance
oauth_state_store = OAuthStateStore()

