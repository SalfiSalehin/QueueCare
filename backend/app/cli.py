"""Operator CLI. Usage (inside the backend container):

    python -m app.cli create-superadmin --email admin@example.com

The password is read from the QUEUECARE_ADMIN_PASSWORD env var or prompted for;
it is never accepted as a command-line argument (it would leak into shell history).
Runs with the OWNER database URL because there is no authenticated user yet.
"""
from __future__ import annotations

import argparse
import getpass
import os
import sys

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.core.security import hash_password
from app.models import User
from app.schemas.auth import validate_password_strength


def create_superadmin(email: str, full_name: str) -> int:
    url = os.environ.get("MIGRATION_DATABASE_URL")
    if not url:
        print("MIGRATION_DATABASE_URL is required (owner role).", file=sys.stderr)
        return 2
    password = os.environ.get("QUEUECARE_ADMIN_PASSWORD") or getpass.getpass("Password: ")
    try:
        validate_password_strength(password, email=email)
    except ValueError as exc:
        print(f"Weak password: {exc}", file=sys.stderr)
        return 2
    engine = create_engine(url)
    with Session(engine) as db:
        if db.scalar(select(User).where(User.email == email.lower())):
            print("A user with that email already exists.", file=sys.stderr)
            return 1
        db.add(User(email=email.lower(), password_hash=hash_password(password), full_name=full_name,
                    platform_role="SUPER_ADMIN", email_verified=True))
        db.commit()
    print("Super administrator created.")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(prog="queuecare")
    sub = parser.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("create-superadmin")
    p.add_argument("--email", required=True)
    p.add_argument("--name", default="Platform Admin")
    args = parser.parse_args()
    return create_superadmin(args.email, args.name)


if __name__ == "__main__":
    raise SystemExit(main())
