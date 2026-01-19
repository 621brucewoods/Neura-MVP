"""migrate_to_supabase_auth

Revision ID: b22e01236205
Revises: 3177ff5d01fc
Create Date: 2026-01-16 23:15:52.954833
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# Revision identifiers, used by Alembic
revision: str = 'b22e01236205'
down_revision: Union[str, None] = '3177ff5d01fc'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Apply migration: migrate_to_supabase_auth"""
    pass


def downgrade() -> None:
    """Revert migration: migrate_to_supabase_auth"""
    pass

