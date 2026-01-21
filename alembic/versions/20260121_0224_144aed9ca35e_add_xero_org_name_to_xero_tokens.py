"""add xero_org_name to xero_tokens

Revision ID: 144aed9ca35e
Revises: 6a7ebff30f7e
Create Date: 2026-01-21 02:24:43.244047
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# Revision identifiers, used by Alembic
revision: str = '144aed9ca35e'
down_revision: Union[str, None] = '6a7ebff30f7e'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Apply migration: add xero_org_name to xero_tokens"""
    op.add_column('xero_tokens', sa.Column('xero_org_name', sa.String(length=255), nullable=True, comment='Xero organization/company name'))


def downgrade() -> None:
    """Revert migration: add xero_org_name to xero_tokens"""
    op.drop_column('xero_tokens', 'xero_org_name')

