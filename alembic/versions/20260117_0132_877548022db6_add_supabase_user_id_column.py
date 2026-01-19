"""add_supabase_user_id_column

Revision ID: 877548022db6
Revises: b22e01236205
Create Date: 2026-01-17 01:32:16.280686
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# Revision identifiers, used by Alembic
revision: str = '877548022db6'
down_revision: Union[str, None] = 'b22e01236205'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Apply migration: add_supabase_user_id_column"""
    # Add supabase_user_id column
    op.add_column('users', sa.Column('supabase_user_id', postgresql.UUID(as_uuid=True), nullable=True, comment='Supabase auth.users.id - links to Supabase authentication'))
    
    # Create unique index on supabase_user_id (matches model definition)
    op.create_index('ix_users_supabase_id', 'users', ['supabase_user_id'], unique=True)
    
    # Create index on is_active (from model definition)
    op.create_index('ix_users_is_active', 'users', ['is_active'], unique=False)
    
    # Update column comments
    op.alter_column('users', 'email',
               existing_type=sa.VARCHAR(length=255),
               comment='User email (synced from Supabase auth.users)',
               existing_nullable=False)
    op.alter_column('users', 'is_active',
               existing_type=sa.BOOLEAN(),
               comment='Whether the user account is active',
               existing_nullable=False)
    op.alter_column('users', 'role',
               existing_type=postgresql.ENUM('user', 'admin', name='user_role_enum'),
               server_default=None,
               existing_comment='User role: user or admin',
               existing_nullable=False)
    
    # Drop old auth-related columns (no longer needed with Supabase)
    op.drop_index('ix_users_locked_until', table_name='users', if_exists=True)
    op.drop_column('users', 'failed_login_attempts')
    op.drop_column('users', 'password_hash')
    op.drop_column('users', 'last_login_at')
    op.drop_column('users', 'is_verified')
    op.drop_column('users', 'locked_until')
    
    # Note: Insights index change removed - keep existing unique constraint if that's what you want


def downgrade() -> None:
    """Revert migration: add_supabase_user_id_column"""
    # Restore old auth columns
    op.add_column('users', sa.Column('locked_until', postgresql.TIMESTAMP(timezone=True), autoincrement=False, nullable=True, comment='Account locked until this timestamp (null if not locked)'))
    op.add_column('users', sa.Column('is_verified', sa.BOOLEAN(), autoincrement=False, nullable=False))
    op.add_column('users', sa.Column('last_login_at', postgresql.TIMESTAMP(timezone=True), autoincrement=False, nullable=True, comment='Last successful login timestamp'))
    op.add_column('users', sa.Column('password_hash', sa.VARCHAR(length=255), autoincrement=False, nullable=False))
    op.add_column('users', sa.Column('failed_login_attempts', sa.INTEGER(), autoincrement=False, nullable=False, comment='Number of consecutive failed login attempts'))
    
    # Restore column comments
    op.alter_column('users', 'email',
               existing_type=sa.VARCHAR(length=255),
               comment=None,
               existing_nullable=False)
    op.alter_column('users', 'is_active',
               existing_type=sa.BOOLEAN(),
               comment=None,
               existing_nullable=False)
    op.alter_column('users', 'role',
               existing_type=postgresql.ENUM('user', 'admin', name='user_role_enum'),
               server_default=sa.text("'user'::user_role_enum"),
               existing_nullable=False)
    
    # Drop Supabase-related indexes and column
    op.drop_index('ix_users_is_active', table_name='users', if_exists=True)
    op.drop_index('ix_users_supabase_id', table_name='users')
    op.drop_column('users', 'supabase_user_id')
    
    # Restore old index
    op.create_index('ix_users_locked_until', 'users', ['locked_until'], unique=False)

