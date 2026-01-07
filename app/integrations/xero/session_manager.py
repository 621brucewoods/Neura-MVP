"""
Xero Session Manager
Manages database session lifecycle for Xero operations.

Centralizes commit logic to prevent session conflicts.
"""

import logging

from sqlalchemy.ext.asyncio import AsyncSession

from app.integrations.xero.sdk_client import XeroSDKClient

logger = logging.getLogger(__name__)


class XeroSessionManager:
    """
    Manages DB session lifecycle for Xero operations.
    
    Prevents session conflicts by centralizing commit logic.
    All fetch operations should flush only, then commit once at the end.
    """
    
    def __init__(self, db: AsyncSession, sdk_client: XeroSDKClient):
        """
        Initialize session manager.
        
        Args:
            db: Database session
            sdk_client: Xero SDK client for token operations
        """
        self.db = db
        self.sdk_client = sdk_client
        self._token_updated = False
    
    async def flush_token_updates(self) -> None:
        """
        Flush token updates without committing.
        
        Use this during fetch operations. Token updates will be
        committed later via commit_all().
        """
        await self.sdk_client.commit_token_updates(skip_commit=True)
        self._token_updated = True
        logger.debug("Flushed token updates (pending commit)")
    
    async def commit_all(self) -> None:
        """
        Commit all pending changes (tokens + data).
        
        This should be called once at the endpoint level after
        all fetch operations and data saves are complete.
        """
        if self._token_updated:
            # Commit token updates first (if any)
            await self.sdk_client.commit_token_updates(skip_commit=False)
            logger.debug("Committed token updates")
        
        # Commit all other changes (insights, etc.)
        await self.db.commit()
        logger.debug("Committed all database changes")
    
    async def rollback(self) -> None:
        """Rollback all pending changes."""
        await self.db.rollback()
        self._token_updated = False
        logger.debug("Rolled back all database changes")

