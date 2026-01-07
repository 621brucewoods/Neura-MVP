"""
Settings Schemas
Request and response models for settings endpoints.
"""

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, EmailStr, Field


class IntegrationStatus(BaseModel):
    """Integration connection status."""
    
    is_connected: bool = Field(..., description="Whether integration is connected")
    status: str = Field(..., description="Connection status")
    connected_at: Optional[datetime] = Field(None, description="When connection was established")
    last_synced_at: Optional[datetime] = Field(None, description="Last successful data sync")
    needs_reconnect: bool = Field(False, description="Whether reconnection is needed")


class SettingsResponse(BaseModel):
    """Complete settings response."""
    
    email: EmailStr = Field(..., description="User email address")
    xero_integration: IntegrationStatus = Field(..., description="Xero integration status")
    last_sync_time: Optional[datetime] = Field(None, description="Last time insights were calculated")
    support_link: Optional[str] = Field(None, description="Support contact link (placeholder for MVP)")

