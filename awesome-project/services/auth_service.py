"""Registration, sign-in and password management."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from database import utcnow
from models.inspection import Inspection
from models.user import User
from schemas.requests.auth import RegisterRequest
from services.audit_service import AuditService
from services.security import hash_password, password_problems, verify_password


class AuthError(Exception):
    """Login/registration failure with a message safe to show the user."""


class PasswordWeak(Exception):
    def __init__(self, problems: list[str]):
        super().__init__("; ".join(problems))
        self.problems = problems


class AuthService:
    def __init__(self, db: Session):
        self.db = db
        self.audit = AuditService(db)

    def _find_by_email(self, email: str) -> User | None:
        return self.db.execute(
            select(User).where(func.lower(User.email) == email.strip().lower())
        ).scalar_one_or_none()

    def inspection_count(self, user_id: int) -> int:
        return self.db.execute(
            select(func.count(Inspection.id)).where(
                Inspection.user_id == user_id,
                Inspection.deleted_at.is_(None),
            )
        ).scalar_one()

    def register(self, data: RegisterRequest) -> User:
        """Create an account.

        The password is checked here rather than only in the schema so the
        detailed reasons reach the user.
        """
        problems = password_problems(data.password)
        if problems:
            raise PasswordWeak(problems)

        if self._find_by_email(data.email):
            raise AuthError("An account with that email already exists.")

        user = User(
            name=data.name.strip(),
            email=data.email.strip().lower(),
            phone=data.phone or None,
            password_hash=hash_password(data.password),
            password_set_at=utcnow(),
            is_active=True,
        )
        self.db.add(user)
        try:
            self.db.flush()
            self.audit.record(
                action="register",
                entity_type="user",
                entity_id=user.id,
                actor_user_id=user.id,
            )
            self.db.commit()
        except Exception:
            self.db.rollback()
            raise
        self.db.refresh(user)
        return user

    def authenticate(self, email: str, password: str) -> User:
        """Verify credentials.

        The same message is returned whether the email is unknown or the
        password is wrong — telling the two apart would let an attacker
        enumerate which addresses have accounts.
        """
        generic = "Email or password is incorrect."
        user = self._find_by_email(email)
        if user is None or not user.is_active:
            # Hash anyway so a missing account and a wrong password take
            # comparable time.
            verify_password(password, _DUMMY_HASH)
            raise AuthError(generic)

        if user.password_hash is None:
            raise AuthError(
                "This account has no password yet. Use 'Set password' first."
            )
        if not verify_password(password, user.password_hash):
            self.audit.record(
                action="login_failed",
                entity_type="user",
                entity_id=user.id,
            )
            self.db.commit()
            raise AuthError(generic)

        user.last_login_at = utcnow()
        self.audit.record(
            action="login", entity_type="user", entity_id=user.id,
            actor_user_id=user.id,
        )
        self.db.commit()
        self.db.refresh(user)
        return user

    def set_password(self, user: User, new_password: str) -> None:
        problems = password_problems(new_password)
        if problems:
            raise PasswordWeak(problems)
        user.password_hash = hash_password(new_password)
        user.password_set_at = utcnow()
        self.audit.record(
            action="set_password",
            entity_type="user",
            entity_id=user.id,
            actor_user_id=user.id,
        )
        self.db.commit()

    def change_password(
        self, user: User, current: str, new_password: str
    ) -> None:
        if not verify_password(current, user.password_hash):
            raise AuthError("Current password is incorrect.")
        self.set_password(user, new_password)


#: A valid hash of an unguessable string, used to equalise timing on lookup.
_DUMMY_HASH = (
    "pbkdf2_sha256$260000$AAAAAAAAAAAAAAAAAAAAAA==$"
    "ZG9uZS1ub3QtY29tcGFyZS1hbnl0aGluZy1iYXNlZDg0"
)