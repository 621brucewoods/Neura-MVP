"""
Admin Schemas
Pydantic models for admin API requests and responses.

Note: Admin only sees operational data (profile, sync status).
Financial data (health scores, cash, runway) is NOT exposed to admin.
"""

from typing import Optional
from pydantic import BaseModel, Field


class OrganizationSummary(BaseModel):
    """Summary of an organization for admin view (operational data only)."""
    
    id: str = Field(..., description="Organization UUID")
    name: str = Field(..., description="Organization name")
    user_email: str = Field(..., description="Owner's email")
    created_at: str = Field(..., description="ISO timestamp of creation")
    
    # Sync status
    sync_status: str = Field(..., description="Current sync status (IDLE, IN_PROGRESS, COMPLETED, FAILED)")
    sync_step: Optional[str] = Field(None, description="Current sync step if in progress")
    last_sync_error: Optional[str] = Field(None, description="Last sync error message if failed")
    
    # Connection status
    has_xero_connection: bool = Field(..., description="Whether Xero is connected")
    last_sync_at: Optional[str] = Field(None, description="ISO timestamp of last successful sync")


class OrganizationListResponse(BaseModel):
    """Response for listing all organizations."""
    
    total: int = Field(..., description="Total number of organizations")
    organizations: list[OrganizationSummary] = Field(..., description="List of organizations")


class AdminDashboardStats(BaseModel):
    """Overall platform statistics for admin dashboard (operational only)."""
    
    total_organizations: int = Field(..., description="Total orgs on platform")
    active_xero_connections: int = Field(..., description="Orgs with active Xero connection")
    syncs_in_progress: int = Field(..., description="Number of syncs currently running")
    failed_syncs: int = Field(..., description="Number of orgs with failed sync status")


class AdminDashboardResponse(BaseModel):
    """Complete admin dashboard data."""
    
    stats: AdminDashboardStats = Field(..., description="Platform statistics")
    organizations: list[OrganizationSummary] = Field(..., description="All organizations")


class UserSummary(BaseModel):
    """User summary for admin view."""
    
    id: str = Field(..., description="User UUID")
    email: str = Field(..., description="User email")
    role: str = Field(..., description="User role (user or admin)")
    organization_name: Optional[str] = Field(None, description="Organization name")
    created_at: str = Field(..., description="ISO timestamp of creation")


class UserListResponse(BaseModel):
    """Response for listing users."""
    
    total: int = Field(..., description="Total number of users")
    users: list[UserSummary] = Field(..., description="List of users")
