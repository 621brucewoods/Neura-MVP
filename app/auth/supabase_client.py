"""
Supabase Client Configuration
Provides authenticated clients for token validation and admin operations.
"""

from supabase import create_client, Client
from app.config import settings

# Public client for token validation (uses anon key)
supabase: Client = create_client(
    settings.supabase_url,
    settings.supabase_anon_key
)

# Admin client for server-side operations (uses service role key)
# Only use for operations that require elevated privileges
supabase_admin: Client = create_client(
    settings.supabase_url,
    settings.supabase_service_role_key
)
