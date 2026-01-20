"""add_health_score_payload_column

Revision ID: 6a7ebff30f7e
Revises: 67b8dcacefe1
Create Date: 2026-01-19 22:22:46.893339
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# Revision identifiers, used by Alembic
revision: str = '6a7ebff30f7e'
down_revision: Union[str, None] = '67b8dcacefe1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Apply migration: add_health_score_payload_column"""
    op.add_column(
        'calculated_metrics',
        sa.Column(
            'health_score_payload',
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
            comment='Full JSON payload of Business Health Score (0-100)'
        )
    )


def downgrade() -> None:
    """Revert migration: add_health_score_payload_column"""
    op.drop_column('calculated_metrics', 'health_score_payload')
