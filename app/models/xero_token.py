"""
Xero Token Model
Stores OAuth 2.0 tokens for Xero API integration.
"""

import uuid
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import TYPE_CHECKING, Optional

from sqlalchemy import String, Text, ForeignKey, DateTime, Index, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.base import Base, TimestampMixin, UUIDMixin

if TYPE_CHECKING:
    from app.models.organization import Organization


class XeroConnectionStatus(str, Enum):
    """Status of the Xero connection."""
    
    ACTIVE = "active"
    DISCONNECTED = "disconnected"
    REFRESH_FAILED = "refresh_failed"
    EXPIRED = "expired"


class XeroToken(Base, UUIDMixin, TimestampMixin):
    """
    Xero OAuth token storage.
    
    Stores access and refresh tokens for Xero API integration.
    Tokens are rotated on each refresh (Xero requirement).
    
    Attributes:
        id: Unique identifier (UUID)
        organization_id: Foreign key to organization (tenant)
        xero_tenant_id: Xero's internal organization identifier
        access_token: Short-lived token for API calls (30 min)
        refresh_token: Long-lived token for refreshing (60 days)
        id_token: OIDC identity token (optional)
        token_type: Token type (usually "Bearer")
        scope: Granted OAuth scopes
        expires_at: When access_token expires
        status: Connection status (active, disconnected, etc.)
        last_refreshed_at: When tokens were last refreshed
        last_api_call_at: When last API call was made
        last_error: Last error message (if any)
        organization: Related organization
        created_at: Timestamp of creation
        updated_at: Timestamp of last update
    
    Security Note:
        Tokens should be encrypted at rest in production.
        Currently stored as plain text for MVP.
    """
    
    # Foreign key to organization (tenant isolation)
    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        unique=True,
        nullable=False,
    )
    
    # Xero identifiers
    xero_tenant_id: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        comment="Xero's internal organization identifier",
    )
    
    xero_org_name: Mapped[Optional[str]] = mapped_column(
        String(255),
        nullable=True,
        comment="Xero organization/company name",
    )
    
    # OAuth tokens
    access_token: Mapped[str] = mapped_column(
        Text,
        nullable=False,
    )
    
    refresh_token: Mapped[str] = mapped_column(
        Text,
        nullable=False,
    )
    
    id_token: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True,
        comment="OIDC identity token",
    )
    
    token_type: Mapped[str] = mapped_column(
        String(50),
        default="Bearer",
        nullable=False,
    )
    
    scope: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        comment="Space-separated OAuth scopes",
    )
    
    # Token expiration
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        comment="When access_token expires",
    )
    
    # Connection status
    status: Mapped[str] = mapped_column(
        String(20),
        default=XeroConnectionStatus.ACTIVE.value,
        nullable=False,
    )
    
    # Tracking
    last_refreshed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    
    last_api_call_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    
    last_error: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True,
    )
    
    # Relationships
    organization: Mapped["Organization"] = relationship(
        "Organization",
        back_populates="xero_token",
        lazy="selectin",
    )
    
    # Indexes
    __table_args__ = (
        Index("ix_xero_tokens_organization_id", "organization_id"),
        Index("ix_xero_tokens_status", "status"),
        Index("ix_xero_tokens_expires_at", "expires_at"),
    )
    
    def __repr__(self) -> str:
        return f"<XeroToken(id={self.id}, org_id={self.organization_id}, status={self.status!r})>"
    
    @property
    def is_active(self) -> bool:
        """Check if token is in active status."""
        return self.status == XeroConnectionStatus.ACTIVE.value
    
    @property
    def is_expired(self) -> bool:
        """Check if access token has expired."""
        return datetime.now(timezone.utc) > self.expires_at
    
    @property
    def needs_refresh(self) -> bool:
        """
        Check if token needs refresh (expires within 5 minutes).
        Proactive refresh prevents mid-request expiration.
        """
        buffer_time = timedelta(minutes=5)
        return datetime.now(timezone.utc) > (self.expires_at - buffer_time)

