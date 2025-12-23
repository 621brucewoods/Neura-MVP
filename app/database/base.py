"""
Base Model Module
Defines the declarative base and common mixins for all models.
"""

import re
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import (
    DeclarativeBase,
    Mapped,
    declared_attr,
    mapped_column,
)


class Base(DeclarativeBase):
    """
    Base class for all SQLAlchemy models.
    
    Features:
        - Automatic table name generation from class name
        - Common __repr__ method
        - Type annotations support
    """
    
    @declared_attr.directive
    def __tablename__(cls) -> str:
        """
        Generate table name from class name.
        Converts CamelCase to snake_case and pluralizes.
        
        Examples:
            User -> users
            XeroToken -> xero_tokens
            FinancialCache -> financial_caches
            CalculatedMetrics -> calculated_metrics (no change, already plural)
        """
        # Convert CamelCase to snake_case
        name = re.sub(r"(?<!^)(?=[A-Z])", "_", cls.__name__).lower()
        
        # Simple pluralization (handles common cases)
        if name.endswith("ics") or name.endswith("sis"):
            # Words like metrics, analytics, analysis - already plural form
            return name
        elif name.endswith("s") or name.endswith("x") or name.endswith("ch") or name.endswith("sh"):
            return name + "es"
        elif name.endswith("y") and name[-2] not in "aeiou":
            return name[:-1] + "ies"
        else:
            return name + "s"
    
    def __repr__(self) -> str:
        """Generate a readable string representation."""
        class_name = self.__class__.__name__
        attrs = []
        
        # Include id if present
        if hasattr(self, "id"):
            attrs.append(f"id={self.id}")
        
        # Include other identifying attributes
        for attr in ["email", "name", "status"]:
            if hasattr(self, attr):
                value = getattr(self, attr)
                if value is not None:
                    attrs.append(f"{attr}={value!r}")
        
        return f"<{class_name}({', '.join(attrs)})>"
    
    def to_dict(self) -> dict[str, Any]:
        """
        Convert model instance to dictionary.
        Useful for serialization and debugging.
        """
        result = {}
        for column in self.__table__.columns:
            value = getattr(self, column.name)
            if isinstance(value, datetime):
                value = value.isoformat()
            elif isinstance(value, uuid.UUID):
                value = str(value)
            result[column.name] = value
        return result


class TimestampMixin:
    """
    Mixin that adds created_at and updated_at timestamps.
    
    Usage:
        class User(Base, TimestampMixin):
            ...
    """
    
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


class UUIDMixin:
    """
    Mixin that adds a UUID primary key.
    
    Usage:
        class User(Base, UUIDMixin, TimestampMixin):
            ...
    """
    
    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        nullable=False,
    )

