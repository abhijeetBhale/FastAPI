#!/usr/bin/env python
"""Create the first administrator, or promote an existing account.

RBAC has a bootstrap problem: `/admin/users/{id}/role` needs an admin to call
it, but nobody is an admin yet. This script breaks the cycle.

    # create a new admin
    .venv\\Scripts\\python.exe scripts\\create_admin.py \\
        --email boss@example.com --name "Site Owner" --password "quay-crane-42"

    # promote someone who already registered
    .venv\\Scripts\\python.exe scripts\\create_admin.py --email existing@example.com

    # list the current admins
    .venv\\Scripts\\python.exe scripts\\create_admin.py --list

Passwords are validated by the same rules the API uses, so a weak one is
refused here rather than silently accepted.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from sqlalchemy import select

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from database import SessionLocal  # noqa: E402
from models.user import User  # noqa: E402
from services.audit_service import AuditService  # noqa: E402
from services.rbac import Role  # noqa: E402
from services.security import hash_password, password_problems  # noqa: E402


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--email", help="Account to create or promote")
    p.add_argument("--name", help="Name, when creating a new account")
    p.add_argument("--password", help="Password, when creating a new account")
    p.add_argument("--role", default=Role.ADMIN.value, choices=[r.value for r in Role])
    p.add_argument("--demote", action="store_true", help="Set the role to 'user' instead")
    p.add_argument("--list", action="store_true", help="List accounts by role")
    args = p.parse_args()

    db = SessionLocal()
    try:
        if args.list:
            rows = db.execute(
                select(User).order_by(User.role, User.id)
            ).scalars().all()
            if not rows:
                print("No users yet.")
                return 0
            print(f"{'id':>4}  {'role':<6} {'active':<7} {'has pwd':<8} email")
            for u in rows:
                print(f"{u.id:>4}  {u.role:<6} {str(u.is_active):<7} "
                      f"{'yes' if u.password_hash else 'no':<8} {u.email}")
            return 0

        if not args.email:
            p.error("--email is required (or use --list)")

        email = args.email.strip().lower()
        target_role = Role.USER.value if args.demote else args.role
        user = db.execute(
            select(User).where(User.email == email)
        ).scalar_one_or_none()

        if user is None:
            if not args.password or not args.name:
                print("Creating a new account needs both --name and --password.")
                return 1
            problems = password_problems(args.password)
            if problems:
                print(f"Password {' and '.join(problems)}.")
                return 1
            user = User(
                name=args.name.strip(),
                email=email,
                password_hash=hash_password(args.password),
                role=target_role,
                is_active=True,
            )
            db.add(user)
            action = "created"
        else:
            action = "demoted" if args.demote else "promoted"
            if args.password:
                problems = password_problems(args.password)
                if problems:
                    print(f"Password {' and '.join(problems)}.")
                    return 1
                user.password_hash = hash_password(args.password)
            user.role = target_role

        db.flush()
        AuditService(db).record(
            action=action, entity_type="user", entity_id=user.id,
            actor_user_id=user.id, detail={"role": target_role},
        )
        db.commit()

        print(f"{action}: {user.email} -> role '{user.role}' (id {user.id})")
        return 0
    except Exception as exc:
        db.rollback()
        print(f"FAILED: {type(exc).__name__}: {exc}")
        return 1
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())