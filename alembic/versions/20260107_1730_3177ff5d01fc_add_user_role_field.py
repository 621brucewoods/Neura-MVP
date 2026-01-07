"""add_user_role_field

Revision ID: 3177ff5d01fc
Revises: 9a5a7c124b69
Create Date: 2026-01-07 17:30:05.377246
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# Revision identifiers, used by Alembic
revision: str = '3177ff5d01fc'
down_revision: Union[str, None] = '9a5a7c124b69'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Apply migration: add_user_role_field"""
    # Create enum type
    user_role_enum = postgresql.ENUM('user', 'admin', name='user_role_enum', create_type=True)
    user_role_enum.create(op.get_bind(), checkfirst=True)
    
    # Add role column with default 'user'
    op.add_column('users', sa.Column(
        'role',
        user_role_enum,
        nullable=False,
        server_default='user',
        comment="User role: user or admin"
    ))


def downgrade() -> None:
    """Revert migration: add_user_role_field"""
    # Drop column
    op.drop_column('users', 'role')
    
    # Drop enum type
    op.execute("DROP TYPE IF EXISTS user_role_enum")

