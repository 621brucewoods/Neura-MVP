"""
Create Admin User Script
Simple script to promote existing users to admin role.

Note: Authentication is handled by Supabase. This script only updates
the role field in the application database. Users must already exist
(have signed up via Supabase) before they can be promoted to admin.
"""

import asyncio
import sys
from pathlib import Path

# Add parent directory to path to import app modules
sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy import select

from app.auth.service import AuthService
from app.auth.utils import normalize_email
from app.database.connection import async_session_factory
from app.models.user import User, UserRole


async def list_admins() -> None:
    """List all current admin users."""
    async with async_session_factory() as session:
        # Fetch all users and filter in Python (simple approach for admin script)
        stmt = select(User).order_by(User.email)
        result = await session.execute(stmt)
        all_users = result.scalars().all()
        admins = [user for user in all_users if user.role == UserRole.ADMIN]
        
        if not admins:
            print("\n📋 No admin users found.")
        else:
            print(f"\n📋 Current Admin Users ({len(admins)}):")
            print("-" * 60)
            for admin in admins:
                status = "✓ Active" if admin.is_active else "✗ Inactive"
                print(f"  • {admin.email} ({status})")
            print("-" * 60)


async def promote_to_admin(email: str) -> None:
    """Promote an existing user to admin role."""
    async with async_session_factory() as session:
        auth_service = AuthService(session)
        normalized_email = normalize_email(email)
        
        # Check if user exists
        existing_user = await auth_service.get_user_by_email(normalized_email)
        
        if not existing_user:
            print(f"\n❌ User {normalized_email} not found.")
            print("   Users must sign up via the app first before being promoted to admin.")
            return
        
        if existing_user.role == UserRole.ADMIN:
            print(f"\n❌ User {normalized_email} is already an admin.")
            return
        
        # Promote to admin
        existing_user.role = UserRole.ADMIN
        await session.commit()
        print(f"\n✅ Promoted {normalized_email} to admin role.")


async def main() -> None:
    """Main script entry point."""
    print("=" * 60)
    print("🔐 Promote User to Admin")
    print("=" * 60)
    print("\nNote: User must have signed up via the app first.")
    print("This script only changes their role to admin.")
    
    # List current admins
    await list_admins()
    
    # Get email
    print("\n" + "=" * 60)
    email = input("📧 Enter email of user to promote: ").strip()
    
    if not email:
        print("\n❌ Email is required.")
        sys.exit(1)
    
    # Confirm
    print("\n" + "=" * 60)
    confirm = input(f"Promote '{email}' to admin? (yes/no): ").strip().lower()
    
    if confirm not in ["yes", "y"]:
        print("\n❌ Cancelled.")
        sys.exit(0)
    
    # Promote to admin
    try:
        await promote_to_admin(email)
        print("\n✅ Done!")
    except ValueError as e:
        print(f"\n❌ Error: {e}")
        sys.exit(1)
    except Exception as e:
        print(f"\n❌ Unexpected error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())

