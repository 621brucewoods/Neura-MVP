"""
Authentication Service - Supabase Integration
Handles user synchronization between Supabase and application database.
"""

import logging
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models import User, Organization

logger = logging.getLogger(__name__)


def normalize_email(email: str) -> str:
    """Normalize email address."""
    return email.strip().lower()


class AuthService:
    """Service for user management with Supabase integration."""
    
    def __init__(self, session: AsyncSession):
        self.session = session
    
    async def get_user_by_id(self, user_id: UUID) -> User | None:
        """
        Get user by application user ID.
        
        Args:
            user_id: Application user UUID
            
        Returns:
            User if found, None otherwise
        """
        query = (
            select(User)
            .options(selectinload(User.organization))
            .where(User.id == user_id)
        )
        result = await self.session.execute(query)
        return result.scalar_one_or_none()
    
    async def get_user_by_supabase_id(self, supabase_user_id: UUID) -> User | None:
        """
        Get user by Supabase user ID.
        
        Args:
            supabase_user_id: Supabase auth.users.id
            
        Returns:
            User if found, None otherwise
        """
        query = (
            select(User)
            .options(selectinload(User.organization))
            .where(User.supabase_user_id == supabase_user_id)
        )
        result = await self.session.execute(query)
        return result.scalar_one_or_none()
    
    async def get_user_by_email(self, email: str) -> User | None:
        """
        Get user by email address.
        
        Args:
            email: User email
            
        Returns:
            User if found, None otherwise
        """
        normalized_email = normalize_email(email)
        query = (
            select(User)
            .options(selectinload(User.organization))
            .where(User.email == normalized_email)
        )
        result = await self.session.execute(query)
        return result.scalar_one_or_none()
    
    async def get_or_create_user(
        self,
        supabase_user_id: UUID,
        email: str,
        organization_name: str | None = None,
    ) -> User:
        """
        Get existing user or create new one with organization.
        
        This is called when a user first accesses the backend after
        signing up in Supabase. It ensures we have a User record
        linked to their Supabase account.
        
        Args:
            supabase_user_id: Supabase auth.users.id
            email: User email (from Supabase)
            organization_name: Optional organization name (for new users)
            
        Returns:
            User instance (existing or newly created)
        """
        # Check if user already exists
        user = await self.get_user_by_supabase_id(supabase_user_id)
        
        if user:
            # Update email if it changed in Supabase
            normalized_email = normalize_email(email)
            if user.email != normalized_email:
                user.email = normalized_email
                await self.session.commit()
            return user
        
        # Create new user with organization
        normalized_email = normalize_email(email)
        default_org_name = organization_name or f"{normalized_email.split('@')[0]}'s Organization"
        
        try:
            # Create user
            user = User(
                supabase_user_id=supabase_user_id,
                email=normalized_email,
                is_active=True,
            )
            self.session.add(user)
            await self.session.flush()
            
            # Create organization
            organization = Organization(
                name=default_org_name,
                user_id=user.id,
            )
            self.session.add(organization)
            await self.session.flush()
            
            # Commit transaction
            await self.session.commit()
            
            # Refresh to load relationships
            await self.session.refresh(user, ["organization"])
            
            logger.info(
                f"User created: {user.id} ({normalized_email}) "
                f"linked to Supabase user {supabase_user_id}"
            )
            
            return user
            
        except Exception as e:
            await self.session.rollback()
            logger.error(f"Failed to create user: {e}")
            raise
