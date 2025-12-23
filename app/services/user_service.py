"""
User Service
Handles user and organization CRUD operations.
"""

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.auth.utils import hash_password, verify_password
from app.models import User, Organization


class UserService:
    """Service for user-related database operations."""
    
    def __init__(self, session: AsyncSession):
        self.session = session
    
    async def get_by_id(self, user_id: UUID) -> User | None:
        """
        Get user by ID.
        
        Args:
            user_id: User UUID
            
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
    
    async def get_by_email(self, email: str) -> User | None:
        """
        Get user by email address.
        
        Args:
            email: User email
            
        Returns:
            User if found, None otherwise
        """
        query = (
            select(User)
            .options(selectinload(User.organization))
            .where(User.email == email)
        )
        result = await self.session.execute(query)
        return result.scalar_one_or_none()
    
    async def create(self, email: str, password: str, organization_name: str) -> User:
        """
        Create a new user with organization.
        
        Args:
            email: User email
            password: Plain text password (will be hashed)
            organization_name: Name for the user's organization
            
        Returns:
            Created User instance
        """
        # Create user
        user = User(
            email=email,
            password_hash=hash_password(password),
            is_active=True,
            is_verified=False,
        )
        self.session.add(user)
        await self.session.flush()  # Get user ID
        
        # Create organization
        organization = Organization(
            name=organization_name,
            user_id=user.id,
        )
        self.session.add(organization)
        await self.session.flush()
        
        # Refresh to load relationships
        await self.session.refresh(user, ["organization"])
        
        return user
    
    async def authenticate(self, email: str, password: str) -> User | None:
        """
        Authenticate user by email and password.
        
        Args:
            email: User email
            password: Plain text password
            
        Returns:
            User if credentials valid, None otherwise
        """
        user = await self.get_by_email(email)
        
        if not user:
            return None
        
        if not user.is_active:
            return None
        
        if not verify_password(password, user.password_hash):
            return None
        
        return user
    
    async def email_exists(self, email: str) -> bool:
        """
        Check if email is already registered.
        
        Args:
            email: Email to check
            
        Returns:
            True if email exists, False otherwise
        """
        query = select(User.id).where(User.email == email)
        result = await self.session.execute(query)
        return result.scalar_one_or_none() is not None

