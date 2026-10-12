from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from models.user import User
from schemas.requests.user import UserCreate, UserUpdate
from services.audit_service import AuditService
from services.query import Page, paginate


class UserService:
    def __init__(self, db: Session):
        self.db = db
        self.audit = AuditService(db)

    def _find_by_email(self, email: str) -> User | None:
        """Case-insensitive, matching the `uq_users_email_lower` index."""
        return (
            self.db.query(User)
            .filter(func.lower(User.email) == email.strip().lower())
            .first()
        )

    def get_user(self, user_id: int) -> User | None:
        return self.db.get(User, user_id)

    def get_inspection_count(self, user_id: int) -> int:
        """A COUNT rather than loading every inspection to call len()."""
        from models.inspection import Inspection

        return self.db.execute(
            select(func.count(Inspection.id)).where(
                Inspection.user_id == user_id,
                Inspection.deleted_at.is_(None),
            )
        ).scalar_one()

    def list_users(
        self,
        *,
        skip: int = 0,
        limit: int = 20,
        is_active: bool | None = None,
        search: str | None = None,
        sort: str = "id",
    ) -> Page[User]:
        stmt = select(User)

        if is_active is not None:
            stmt = stmt.where(User.is_active.is_(is_active))
        if search:
            pattern = f"%{search.strip()}%"
            stmt = stmt.where(
                User.name.ilike(pattern) | User.email.ilike(pattern)
            )

        descending = sort.startswith("-")
        column = sort.lstrip("-")
        allowed = {"id": User.id, "name": User.name, "email": User.email,
                   "created_at": User.created_at}
        if column not in allowed:
            raise ValueError(f"Cannot sort by '{column}'")
        order_col = allowed[column]
        stmt = stmt.order_by(order_col.desc() if descending else order_col.asc())

        return paginate(self.db, stmt, skip=skip, limit=limit)

    def create_user(self, user_data: UserCreate) -> User:
        if self._find_by_email(user_data.email):
            raise ValueError(f"Email {user_data.email} already registered")

        db_user = User(**user_data.model_dump())
        self.db.add(db_user)
        try:
            self.db.flush()
            self.audit.record(
                action="create",
                entity_type="user",
                entity_id=db_user.id,
                actor_user_id=db_user.id,
            )
            self.db.commit()
        except Exception:
            self.db.rollback()
            raise
        self.db.refresh(db_user)
        return db_user

    def update_user(self, user_id: int, update_data: UserUpdate) -> User | None:
        user = self.get_user(user_id)
        if not user:
            return None

        changes = update_data.model_dump(exclude_unset=True)
        if "email" in changes and changes["email"]:
            clash = self._find_by_email(changes["email"])
            if clash and clash.id != user.id:
                raise ValueError(f"Email {changes['email']} already registered")

        for field, value in changes.items():
            setattr(user, field, value)

        self.audit.record(
            action="update",
            entity_type="user",
            entity_id=user.id,
            detail={"fields": sorted(changes)},
        )
        self.db.commit()
        self.db.refresh(user)
        return user

    def delete_user(self, user_id: int) -> bool:
        """Soft delete: deactivate rather than destroy.

        A hard delete would cascade to inspections and lose the inspection
        history, so the user is marked inactive and filtered out of most reads.
        """
        user = self.get_user(user_id)
        if not user:
            return False
        user.is_active = False
        self.audit.record(
            action="deactivate", entity_type="user", entity_id=user.id
        )
        self.db.commit()
        return True

    def hard_delete_user(self, user_id: int) -> bool:
        """Actually remove the row. Cascades to their inspections."""
        user = self.get_user(user_id)
        if not user:
            return False
        self.db.delete(user)
        self.db.commit()
        return True