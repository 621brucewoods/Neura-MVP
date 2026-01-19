"""add_monthly_pnl_cache_table

Revision ID: 67b8dcacefe1
Revises: 877548022db6
Create Date: 2026-01-19 18:21:14.694012
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# Revision identifiers, used by Alembic
revision: str = '67b8dcacefe1'
down_revision: Union[str, None] = '877548022db6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Apply migration: add_monthly_pnl_cache_table"""
    # Create monthly_pnl_cache table for storing monthly P&L data
    op.create_table('monthly_pnl_cache',
        sa.Column('organization_id', sa.UUID(), nullable=False),
        sa.Column('month_key', sa.String(length=7), nullable=False, comment='Month identifier in YYYY-MM format'),
        sa.Column('year', sa.Integer(), nullable=False, comment='Year (e.g., 2025)'),
        sa.Column('month', sa.Integer(), nullable=False, comment='Month (1-12)'),
        sa.Column('revenue', sa.Numeric(), nullable=True, comment='Total revenue for the month'),
        sa.Column('cost_of_sales', sa.Numeric(), nullable=True, comment='Total COGS for the month'),
        sa.Column('expenses', sa.Numeric(), nullable=True, comment='Total operating expenses'),
        sa.Column('net_profit', sa.Numeric(), nullable=True, comment='Net profit (revenue - cogs - expenses)'),
        sa.Column('raw_data', postgresql.JSONB(astext_type=sa.Text()), nullable=False, comment='Full P&L report data from Xero'),
        sa.Column('fetched_at', sa.DateTime(timezone=True), nullable=False, comment='When data was fetched from Xero'),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=True, comment='When cache expires (None = never)'),
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['organization_id'], ['organizations.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('organization_id', 'month_key', name='uq_monthly_pnl_cache_org_month')
    )
    
    # Create indexes for efficient lookups
    op.create_index('ix_monthly_pnl_cache_organization_id', 'monthly_pnl_cache', ['organization_id'], unique=False)
    op.create_index('ix_monthly_pnl_cache_expires_at', 'monthly_pnl_cache', ['expires_at'], unique=False)
    op.create_index('ix_monthly_pnl_cache_org_month', 'monthly_pnl_cache', ['organization_id', 'month_key'], unique=False)
    op.create_index('ix_monthly_pnl_cache_org_year_month', 'monthly_pnl_cache', ['organization_id', 'year', 'month'], unique=False)


def downgrade() -> None:
    """Revert migration: add_monthly_pnl_cache_table"""
    # Drop indexes
    op.drop_index('ix_monthly_pnl_cache_org_year_month', table_name='monthly_pnl_cache')
    op.drop_index('ix_monthly_pnl_cache_org_month', table_name='monthly_pnl_cache')
    op.drop_index('ix_monthly_pnl_cache_expires_at', table_name='monthly_pnl_cache')
    op.drop_index('ix_monthly_pnl_cache_organization_id', table_name='monthly_pnl_cache')
    
    # Drop table
    op.drop_table('monthly_pnl_cache')
