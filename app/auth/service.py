"""
Authentication Service
Handles user and organization CRUD operations with security features.
"""

import logging
from datetime import datetime, timedelta, timezone
from uuid import UUID

from sqlalchemy import select, and_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.auth.utils import hash_password, verify_password, normalize_email, hash_token
from app.config import settings
from app.models import User, Organization, LoginAttempt, RefreshToken, TokenBlacklist

logger = logging.getLogger(__name__)


class AuthService:
    """Service for user authentication and management with security features."""
    
    def __init__(self, session: AsyncSession):
        self.session = session
    
    async def get_user_by_id(self, user_id: UUID) -> User | None:
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
    
    async def get_user_by_email(self, email: str) -> User | None:
        """
        Get user by email address (normalized).
        
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
    
    async def create_user(self, email: str, password: str, organization_name: str) -> User:
        """
        Create a new user with organization (transaction-safe).
        
        Uses database transaction to ensure atomicity. If organization
        creation fails, user creation is rolled back.
        
        Args:
            email: User email (will be normalized)
            password: Plain text password (will be hashed)
            organization_name: Name for the user's organization
            
        Returns:
            Created User instance
            
        Raises:
            ValueError: If email already exists
        """
        normalized_email = normalize_email(email)
        
        # Check if email exists
        if await self.email_exists(normalized_email):
            raise ValueError("Email already registered")
        
        try:
            # Create user
            user = User(
                email=normalized_email,
                password_hash=hash_password(password),
                is_active=True,
                is_verified=False,
            )
            self.session.add(user)
            await self.session.flush()
            
            # Create organization
            organization = Organization(
                name=organization_name,
                user_id=user.id,
            )
            self.session.add(organization)
            await self.session.flush()
            
            # Commit transaction
            await self.session.commit()
            
            # Refresh to load relationships
            await self.session.refresh(user, ["organization"])
            
            logger.info(f"User created: {user.id} ({normalized_email})")
            
            return user
            
        except Exception as e:
            await self.session.rollback()
            logger.error(f"Failed to create user: {e}")
            raise
    
    async def authenticate(
        self,
        email: str,
        password: str,
        ip_address: str | None = None,
    ) -> tuple[User | None, bool]:
        """
        Authenticate user by email and password with account lockout protection.
        
        Args:
            email: User email
            password: Plain text password
            ip_address: IP address of login attempt (for tracking)
            
        Returns:
            Tuple of (user, is_locked)
            - user: User if credentials valid, None otherwise
            - is_locked: True if account is locked, False otherwise
        """
        normalized_email = normalize_email(email)
        user = await self.get_user_by_email(normalized_email)
        
        # Track login attempt
        if ip_address:
            await self._record_login_attempt(normalized_email, user.id if user else None, ip_address, False)
        
        if not user:
            return None, False
        
        # Check if account is locked
        if user.is_locked():
            logger.warning(f"Login attempt on locked account: {normalized_email}")
            return None, True
        
        if not user.is_active:
            return None, False
        
        # Verify password
        if not verify_password(password, user.password_hash):
            # Increment failed attempts
            await self._handle_failed_login(user, ip_address)
            return None, False
        
        # Successful login - reset failed attempts and update last login
        user.failed_login_attempts = 0
        user.locked_until = None
        user.last_login_at = datetime.now(timezone.utc)
        await self.session.commit()
        
        # Record successful login attempt
        if ip_address:
            await self._record_login_attempt(normalized_email, user.id, ip_address, True)
        
        logger.info(f"Successful login: {user.id} ({normalized_email})")
        
        return user, False
    
    async def _handle_failed_login(self, user: User, ip_address: str | None) -> None:
        """Handle failed login attempt and lock account if threshold reached."""
        user.failed_login_attempts += 1
        
        if user.failed_login_attempts >= settings.max_failed_login_attempts:
            lockout_until = datetime.now(timezone.utc) + timedelta(
                minutes=settings.account_lockout_minutes
            )
            user.locked_until = lockout_until
            logger.warning(
                f"Account locked: {user.id} ({user.email}) "
                f"until {lockout_until.isoformat()}"
            )
        
        await self.session.commit()
    
    async def _record_login_attempt(
        self,
        email: str,
        user_id: UUID | None,
        ip_address: str,
        success: bool,
    ) -> None:
        """Record login attempt for security auditing."""
        attempt = LoginAttempt(
            email=email,
            user_id=user_id,
            ip_address=ip_address,
            success=success,
        )
        self.session.add(attempt)
        await self.session.commit()
    
    async def email_exists(self, email: str) -> bool:
        """
        Check if email is already registered (normalized).
        
        Args:
            email: Email to check
            
        Returns:
            True if email exists, False otherwise
        """
        normalized_email = normalize_email(email)
        query = select(User.id).where(User.email == normalized_email)
        result = await self.session.execute(query)
        return result.scalar_one_or_none() is not None
    
    async def change_password(self, user_id: UUID, current_password: str, new_password: str) -> bool:
        """
        Change user password.
        
        Args:
            user_id: User ID
            current_password: Current password for verification
            new_password: New password to set
            
        Returns:
            True if password changed successfully, False if current password invalid
        """
        user = await self.get_user_by_id(user_id)
        if not user:
            return False
        
        if not verify_password(current_password, user.password_hash):
            logger.warning(f"Password change failed - invalid current password: {user.id}")
            return False
        
        user.password_hash = hash_password(new_password)
        user.failed_login_attempts = 0
        user.locked_until = None
        await self.session.commit()
        
        logger.info(f"Password changed: {user.id}")
        return True
    
    async def store_refresh_token(self, user_id: UUID, token: str, expires_at: datetime) -> None:
        """
        Store refresh token hash for rotation tracking.
        
        Args:
            user_id: User ID
            token: Refresh token string
            expires_at: Token expiration datetime
        """
        token_hash = hash_token(token)
        refresh_token = RefreshToken(
            token_hash=token_hash,
            user_id=user_id,
            expires_at=expires_at,
        )
        self.session.add(refresh_token)
        await self.session.commit()
    
    async def validate_refresh_token(self, token: str) -> tuple[bool, UUID | None]:
        """
        Validate refresh token and mark as used (one-time use).
        
        Args:
            token: Refresh token string
            
        Returns:
            Tuple of (is_valid, user_id)
            - is_valid: True if token is valid and unused
            - user_id: User ID if valid, None otherwise
        """
        token_hash = hash_token(token)
        now = datetime.now(timezone.utc)
        
        query = (
            select(RefreshToken)
            .where(
                and_(
                    RefreshToken.token_hash == token_hash,
                    RefreshToken.is_used == False,
                    RefreshToken.expires_at > now,
                )
            )
        )
        result = await self.session.execute(query)
        refresh_token = result.scalar_one_or_none()
        
        if not refresh_token:
            return False, None
        
        # Mark as used (one-time use)
        refresh_token.is_used = True
        refresh_token.used_at = now
        await self.session.commit()
        
        return True, refresh_token.user_id
    
    async def revoke_user_tokens(self, user_id: UUID) -> None:
        """
        Revoke all refresh tokens for a user.
        
        Args:
            user_id: User ID
        """
        query = (
            select(RefreshToken)
            .where(
                and_(
                    RefreshToken.user_id == user_id,
                    RefreshToken.is_used == False,
                    RefreshToken.expires_at > datetime.now(timezone.utc),
                )
            )
        )
        result = await self.session.execute(query)
        tokens = result.scalars().all()
        
        for token in tokens:
            token.is_used = True
            token.used_at = datetime.now(timezone.utc)
        
        await self.session.commit()
        logger.info(f"Revoked all refresh tokens for user: {user_id}")
    
    async def is_token_blacklisted(self, jti: str) -> bool:
        """
        Check if a token JTI is blacklisted.
        
        Args:
            jti: JWT ID (JTI) to check
            
        Returns:
            True if token is blacklisted, False otherwise
        """
        query = (
            select(TokenBlacklist)
            .where(
                and_(
                    TokenBlacklist.jti == jti,
                    TokenBlacklist.expires_at > datetime.now(timezone.utc),
                )
            )
        )
        result = await self.session.execute(query)
        return result.scalar_one_or_none() is not None
    
    async def blacklist_token(
        self,
        jti: str,
        token: str,
        user_id: UUID,
        expires_at: datetime,
    ) -> None:
        """
        Add token to blacklist.
        
        Args:
            jti: JWT ID (JTI)
            token: Full token string (for hash)
            user_id: User ID
            expires_at: Token expiration datetime
        """
        token_hash = hash_token(token)
        blacklist_entry = TokenBlacklist(
            jti=jti,
            token_hash=token_hash,
            user_id=user_id,
            expires_at=expires_at,
        )
        self.session.add(blacklist_entry)
        await self.session.commit()
        logger.info(f"Token blacklisted: {jti} for user {user_id}")
