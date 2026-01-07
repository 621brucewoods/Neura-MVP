"""
Create Admin User Script
Simple script to create admin users from command line.
"""

import asyncio
import sys
from pathlib import Path

# Add parent directory to path to import app modules
sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy import select

from app.auth.service import AuthService
from app.auth.utils import hash_password, normalize_email
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


async def create_admin(email: str, password: str) -> None:
    """Create a new admin user or upgrade existing user to admin."""
    async with async_session_factory() as session:
        auth_service = AuthService(session)
        normalized_email = normalize_email(email)
        
        # Check if user already exists
        existing_user = await auth_service.get_user_by_email(normalized_email)
        
        if existing_user:
            # Update existing user to admin
            if existing_user.role == UserRole.ADMIN:
                print(f"\n❌ User {normalized_email} is already an admin.")
                return
            
            existing_user.role = UserRole.ADMIN
            # Update password if provided
            existing_user.password_hash = hash_password(password)
            await session.commit()
            print(f"\n✅ Updated user {normalized_email} to admin role.")
        else:
            # Create new admin user (without organization - admins don't need one)
            user = User(
                email=normalized_email,
                password_hash=hash_password(password),
                is_active=True,
                is_verified=True,
                role=UserRole.ADMIN,
            )
            session.add(user)
            await session.commit()
            await session.refresh(user)
            print(f"\n✅ Created new admin user: {normalized_email}")


async def main() -> None:
    """Main script entry point."""
    print("=" * 60)
    print("🔐 Create Admin User")
    print("=" * 60)
    
    # List current admins
    await list_admins()
    
    # Get email
    print("\n" + "=" * 60)
    email = input("📧 Enter email address: ").strip()
    
    if not email:
        print("\n❌ Email is required.")
        sys.exit(1)
    
    # Get password
    import getpass
    password = getpass.getpass("🔑 Enter password: ").strip()
    
    if not password:
        print("\n❌ Password is required.")
        sys.exit(1)
    
    # Confirm
    print("\n" + "=" * 60)
    confirm = input(f"Create admin user '{email}'? (yes/no): ").strip().lower()
    
    if confirm not in ["yes", "y"]:
        print("\n❌ Cancelled.")
        sys.exit(0)
    
    # Create admin
    try:
        await create_admin(email, password)
        print("\n✅ Done!")
    except ValueError as e:
        print(f"\n❌ Error: {e}")
        sys.exit(1)
    except Exception as e:
        print(f"\n❌ Unexpected error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())

