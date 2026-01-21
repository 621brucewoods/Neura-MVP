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
    xero_org_name: Optional[str] = Field(None, description="Connected Xero organization name")


class SettingsResponse(BaseModel):
    """Complete settings response."""
    
    email: EmailStr = Field(..., description="User email address")
    organization_name: str = Field(..., description="Organization name")
    xero_integration: IntegrationStatus = Field(..., description="Xero integration status")
    last_sync_time: Optional[datetime] = Field(None, description="Last time insights were calculated")
    support_link: Optional[str] = Field(None, description="Support contact link (placeholder for MVP)")


class UpdateOrganizationRequest(BaseModel):
    """Request to update organization name."""
    
    name: str = Field(..., min_length=1, max_length=255, description="New organization name")

