#!/usr/bin/env python3
"""
Secure, Controlled One-Time Setup Script for Migration Owner / Admin Account.
Usage:
    python backend/scripts/provision_owner.py --email user@example.com --password "Secret123!" --name "Admin User" --role ADMIN

This script provides an explicit, auditable way to provision or reset
the primary owner/admin account without hardcoding credentials in code or
auto-provisioning during login.
"""
import argparse
import asyncio
import os
import re
import sys
from pathlib import Path

# Add backend directory to sys.path
backend_dir = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(backend_dir))

from sqlalchemy import select, text
from app.core.database import AsyncSessionLocal, init_db
from app.core.security import hash_password
from app.models.models import User


_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


async def provision_owner(
    email: str,
    password: str,
    name: str,
    role: str = "ADMIN",
    cal_username: str = "",
    cal_event_slug: str = "15min",
    cal_booking_url: str = "",
    backfill_unassigned: bool = True,
):
    email = email.strip().lower()
    if not _EMAIL_RE.match(email):
        raise ValueError(f"Invalid email address: {email}")
    if len(password) < 8:
        raise ValueError("Password must be at least 8 characters long")
    if not re.search(r"[A-Za-z]", password) or not re.search(r"\d", password):
        raise ValueError("Password must contain at least one letter and one number")

    await init_db()

    async with AsyncSessionLocal() as session:
        result = await session.execute(select(User).where(User.email == email))
        user = result.scalar_one_or_none()

        pw_hash = hash_password(password)

        if user is None:
            user = User(
                name=name,
                email=email,
                password_hash=pw_hash,
                role=role.upper(),
                is_active=True,
                cal_com_username=cal_username or None,
                cal_com_event_slug=cal_event_slug or None,
                cal_com_booking_url=cal_booking_url or None,
            )
            session.add(user)
            await session.commit()
            await session.refresh(user)
            print(f"[PROVISION] Created new user: {email} (ID: {user.id}, Role: {user.role})")
        else:
            user.password_hash = pw_hash
            user.role = role.upper()
            user.is_active = True
            if name:
                user.name = name
            if cal_username:
                user.cal_com_username = cal_username
            if cal_event_slug:
                user.cal_com_event_slug = cal_event_slug
            if cal_booking_url:
                user.cal_com_booking_url = cal_booking_url
            await session.commit()
            print(f"[PROVISION] Updated existing user: {email} (ID: {user.id}, Role: {user.role})")

        if backfill_unassigned:
            # Backfill unowned sessions and contacts to this owner
            await session.execute(
                text("UPDATE user_inputs SET user_id = :uid WHERE user_id IS NULL"),
                {"uid": user.id},
            )
            await session.execute(
                text("UPDATE contacts SET user_id = :uid WHERE user_id IS NULL"),
                {"uid": user.id},
            )
            await session.commit()
            print(f"[PROVISION] Reconciled unassigned legacy rows to owner {email}")

    print("[PROVISION] Provisioning completed successfully.")


def main():
    parser = argparse.ArgumentParser(description="Provision owner/admin account")
    parser.add_argument("--email", required=True, help="User email address")
    parser.add_argument("--password", required=True, help="User password (min 8 chars, 1 letter, 1 number)")
    parser.add_argument("--name", default="Administrator", help="Full name")
    parser.add_argument("--role", default="ADMIN", choices=["ADMIN", "SALES_REPRESENTATIVE"], help="Role")
    parser.add_argument("--cal-username", default="", help="Cal.com username")
    parser.add_argument("--cal-event-slug", default="15min", help="Cal.com event slug")
    parser.add_argument("--cal-booking-url", default="", help="Cal.com booking URL")
    parser.add_argument("--no-backfill", action="store_true", help="Do not backfill unassigned records")

    args = parser.parse_args()
    asyncio.run(
        provision_owner(
            email=args.email,
            password=args.password,
            name=args.name,
            role=args.role,
            cal_username=args.cal_username,
            cal_event_slug=args.cal_event_slug,
            cal_booking_url=args.cal_booking_url,
            backfill_unassigned=not args.no_backfill,
        )
    )


if __name__ == "__main__":
    main()
