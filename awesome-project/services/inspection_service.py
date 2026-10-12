"""The inspection business layer.

Query patterns worth studying here:

* `selectinload` — avoids the N+1 problem (one extra query per row otherwise)
* `joinedload` — for many-to-one, where a JOIN beats a second SELECT
* `func.count` / `func.sum` / `group_by` — aggregates in the database
* `~exists()` — "rows with no match", expressed as a correlated subquery
* soft delete — every read filters `deleted_at IS NULL`
"""

from __future__ import annotations

import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

from sqlalchemy import Select, and_, func, or_, select
from sqlalchemy.orm import Session, selectinload

from models.cargo_type import CargoType
from models.inspection import INSPECTION_STATUSES, Inspection
from models.tag import Tag
from models.user import User
from schemas.requests.inspection import InspectionCreate, InspectionUpdate
from services.audit_service import AuditService
from services.query import Page, paginate

STORAGE_DIR = Path(__file__).resolve().parent.parent / "storage" / "inspections"

MAX_IMAGE_BYTES = 10 * 1024 * 1024

ALLOWED_CONTENT_TYPES = {
    "image/png": ".png",
    "image/jpeg": ".jpg",
    "image/jpg": ".jpg",
    "image/webp": ".webp",
    "image/gif": ".gif",
}

#: Chunk size for streamed writes, so a large upload never sits fully in RAM.
WRITE_CHUNK = 64 * 1024

_JPEG_SOF = {
    0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7,
    0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF,
}


def _image_dimensions(data: bytes) -> Optional[tuple[int, int]]:
    """Best-effort (width, height) by parsing the file header.

    Deliberately dependency-free: no Pillow in this environment. Handles PNG,
    GIF, WebP and JPEG; returns None for anything it cannot read, which simply
    leaves the dimension fields null.
    """
    if len(data) < 10:
        return None

    if data[:8] == b"\x89PNG\r\n\x1a\n" and len(data) >= 24 \
            and data[12:16] == b"IHDR":
        return (
            int.from_bytes(data[16:20], "big"),
            int.from_bytes(data[20:24], "big"),
        )

    if data[:6] in (b"GIF87a", b"GIF89a"):
        return (
            int.from_bytes(data[6:8], "little"),
            int.from_bytes(data[8:10], "little"),
        )

    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        chunk = data[12:16]
        if chunk == b"VP8X" and len(data) >= 30:
            return (
                int.from_bytes(data[24:27], "little") + 1,
                int.from_bytes(data[27:30], "little") + 1,
            )
        if chunk == b"VP8 " and len(data) >= 30 and data[23:26] == b"\x9d\x01\x2a":
            return (
                int.from_bytes(data[26:28], "little") & 0x3FFF,
                int.from_bytes(data[28:30], "little") & 0x3FFF,
            )
        if chunk == b"VP8L" and len(data) >= 25:
            b0, b1, b2, b3 = data[21], data[22], data[23], data[24]
            return (
                (((b1 & 0x3F) << 8) | b0) + 1,
                (((b3 & 0x0F) << 10) | (b2 << 2) | ((b1 & 0xC0) >> 6)) + 1,
            )
        return None

    if data[:2] == b"\xff\xd8":
        i, n = 2, len(data)
        while i + 3 < n:
            if data[i] != 0xFF:
                i += 1
                continue
            marker = data[i + 1]
            if marker in (0xD8, 0x01) or 0xD0 <= marker <= 0xD7:
                i += 2
                continue
            seg_len = int.from_bytes(data[i + 2 : i + 4], "big")
            if marker in _JPEG_SOF:
                return (
                    int.from_bytes(data[i + 7 : i + 9], "big"),
                    int.from_bytes(data[i + 5 : i + 7], "big"),
                )
            i += 2 + seg_len
    return None


def resolve_image_path(insp: Inspection) -> Path:
    return STORAGE_DIR / insp.image_filename


def _write_streamed(chunks, path: Path) -> int:
    """Write in chunks instead of one `write_bytes(content)` call.

    The request handler reads the upload into a SpooledTemporaryFile, so the
    bytes are already off the socket; writing them incrementally still avoids
    building a second full copy in memory.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    written = 0
    with path.open("wb") as fh:
        while True:
            chunk = chunks.read(WRITE_CHUNK)
            if not chunk:
                break
            fh.write(chunk)
            written += len(chunk)
    return written


class InspectionService:
    def __init__(self, db: Session):
        self.db = db
        self.audit = AuditService(db)

    # ------------------------------------------------------------------ #
    # eager loading
    # ------------------------------------------------------------------ #
    @staticmethod
    def _loaded() -> Select:
        """A select with the relationships pre-loaded.

        Without `selectinload`, serialising `inspection.user.name` issues one
        extra SELECT per row — the classic N+1. `unique()` in `paginate`
        de-duplicates the joined rows these produce.
        """
        return select(Inspection).options(
            selectinload(Inspection.user),
            selectinload(Inspection.cargo_type_ref),
            selectinload(Inspection.tags),
        )

    # ------------------------------------------------------------------ #
    # resolution helpers
    # ------------------------------------------------------------------ #
    def _resolve_user(self, name: str, email: str, phone: str | None):
        """Find the user by email or create one.

        An existing user's stored name and phone are left alone — the users
        table is the source of truth, and a form submission should not silently
        rewrite someone's details.
        """
        user = (
            self.db.query(User)
            .filter(func.lower(User.email) == email.strip().lower())
            .first()
        )
        if user:
            return user, False

        user = User(name=name.strip(), email=email.strip(), phone=phone or None)
        self.db.add(user)
        self.db.flush()
        return user, True

    def _resolve_cargo_type(self, slug: str) -> CargoType:
        """Look up the cargo type, falling back to 'other'."""
        found = (
            self.db.query(CargoType)
            .filter(func.lower(CargoType.slug) == slug.strip().lower())
            .first()
        )
        if found:
            return found

        fallback = (
            self.db.query(CargoType).filter(CargoType.slug == "other").first()
        )
        if fallback:
            return fallback

        raise ValueError(f"Unknown cargo type '{slug}'")

    def _resolve_tags(self, names: list[str]) -> list[Tag]:
        """Get-or-create each tag by name."""
        tags: list[Tag] = []
        for name in names:
            tag = self.db.query(Tag).filter(Tag.name == name).first()
            if tag is None:
                tag = Tag(name=name)
                self.db.add(tag)
                self.db.flush()
            tags.append(tag)
        return tags

    # ------------------------------------------------------------------ #
    # reads
    # ------------------------------------------------------------------ #
    def get_inspection(self, inspection_id: int) -> Inspection | None:
        return self.db.execute(
            self._loaded().where(
                Inspection.id == inspection_id,
                Inspection.deleted_at.is_(None),
            )
        ).unique().scalar_one_or_none()

    def list_inspections(
        self,
        *,
        skip: int = 0,
        limit: int = 20,
        user_id: Optional[int] = None,
        cargo_type: Optional[str] = None,
        status: Optional[str] = None,
        tag: Optional[str] = None,
        search: Optional[str] = None,
        created_from: Optional[datetime] = None,
        created_to: Optional[datetime] = None,
        include_deleted: bool = False,
        sort: str = "-created_at",
    ) -> Page[Inspection]:
        """Filtered, sorted, paginated listing.

        Every filter is an AND-ed clause on one statement, so PostgreSQL can
        combine indexes instead of round-tripping per filter.
        """
        stmt = self._loaded()

        # Soft delete: hide retired rows unless explicitly requested.
        if not include_deleted:
            stmt = stmt.where(Inspection.deleted_at.is_(None))

        if user_id is not None:
            stmt = stmt.where(Inspection.user_id == user_id)
        if cargo_type:
            stmt = stmt.join(Inspection.cargo_type_ref).where(
                func.lower(CargoType.slug) == cargo_type.strip().lower()
            )
        if status:
            if status not in INSPECTION_STATUSES:
                raise ValueError(
                    f"Unknown status '{status}'. "
                    f"Expected one of: {', '.join(INSPECTION_STATUSES)}"
                )
            stmt = stmt.where(Inspection.status == status)
        if tag:
            # Many-to-many filter: join through the association table.
            stmt = stmt.join(Inspection.tags).where(Tag.name == tag)
        if created_from:
            stmt = stmt.where(Inspection.created_at >= created_from)
        if created_to:
            stmt = stmt.where(Inspection.created_at <= created_to)

        if search:
            # Case-insensitive contains, across both the notes and the
            # submitting user's name / email.
            pattern = f"%{search.strip()}%"
            stmt = (
                stmt.join(Inspection.user)
                .where(
                    or_(
                        Inspection.notes.ilike(pattern),
                        Inspection.image_original_name.ilike(pattern),
                        User.name.ilike(pattern),
                        User.email.ilike(pattern),
                    )
                )
            )

        # `sort` is whitelisted, never interpolated into SQL.
        descending = sort.startswith("-")
        column = sort.lstrip("-")
        allowed = {
            "created_at": Inspection.created_at,
            "updated_at": Inspection.updated_at,
            "status": Inspection.status,
            "id": Inspection.id,
        }
        if column not in allowed:
            raise ValueError(f"Cannot sort by '{column}'")
        order_col = allowed[column]
        stmt = stmt.order_by(order_col.desc() if descending else order_col.asc())
        # Stable tiebreaker so paging cannot repeat or skip rows.
        stmt = stmt.order_by(Inspection.id.desc())

        return paginate(self.db, stmt, skip=skip, limit=limit)

    # ------------------------------------------------------------------ #
    # writes
    # ------------------------------------------------------------------ #
    def create_inspection(
        self,
        data: InspectionCreate,
        *,
        original_name: str,
        content_type: str,
        content: bytes,
    ) -> Inspection:
        if not content:
            raise ValueError("Uploaded file is empty")
        if len(content) > MAX_IMAGE_BYTES:
            raise ValueError(
                f"Image is too large ({len(content) // 1024 // 1024} MB, "
                f"limit {MAX_IMAGE_BYTES // 1024 // 1024} MB)"
            )

        extension = ALLOWED_CONTENT_TYPES.get(content_type)
        if extension is None:
            raise ValueError(
                f"Unsupported image type '{content_type}'. "
                f"Allowed: {', '.join(sorted(ALLOWED_CONTENT_TYPES))}"
            )

        user, user_created = self._resolve_user(data.name, data.email, data.phone)
        cargo_type = self._resolve_cargo_type(data.cargo_type)
        tags = self._resolve_tags(data.tags)

        STORAGE_DIR.mkdir(parents=True, exist_ok=True)
        filename = f"{uuid.uuid4().hex}{extension}"
        (STORAGE_DIR / filename).write_bytes(content)

        dims = _image_dimensions(content)
        insp = Inspection(
            user_id=user.id,
            cargo_type_id=cargo_type.id,
            status=data.status,
            notes=data.notes,
            image_filename=filename,
            image_original_name=(original_name or filename)[:255],
            image_content_type=content_type,
            image_size_bytes=len(content),
            image_width=dims[0] if dims else None,
            image_height=dims[1] if dims else None,
            tags=tags,
        )
        self.db.add(insp)
        try:
            self.db.flush()
            now = datetime.now()
            insp.updated_at = now
            self.audit.record(
                action="create",
                entity_type="inspection",
                entity_id=insp.id,
                actor_user_id=user.id,
                detail={"cargo_type": cargo_type.slug, "created_user": user_created},
            )
            self.db.commit()
        except Exception:
            self.db.rollback()
            (STORAGE_DIR / filename).unlink(missing_ok=True)
            raise
        self.db.refresh(insp)
        return insp

    def update_inspection(
        self, inspection_id: int, data: InspectionUpdate
    ) -> Optional[Inspection]:
        insp = self.get_inspection(inspection_id)
        if not insp:
            return None

        changes: dict[str, Any] = data.model_dump(exclude_unset=True)

        if "cargo_type" in changes and changes["cargo_type"]:
            insp.cargo_type = self._resolve_cargo_type(changes.pop("cargo_type"))

        tags = changes.pop("tags", None)
        if tags is not None:
            insp.tags = self._resolve_tags(tags)

        for field, value in changes.items():
            if hasattr(insp, field):
                setattr(insp, field, value)

        insp.updated_at = datetime.now()
        self.audit.record(
            action="update",
            entity_type="inspection",
            entity_id=insp.id,
            detail={"fields": sorted(changes)},
        )
        self.db.commit()
        self.db.refresh(insp)
        return insp

    def soft_delete(self, inspection_id: int) -> bool:
        """Retire a row without destroying it.

        The image is kept too: an audit trail that points at a missing file is
        worse than useless.
        """
        insp = self.get_inspection(inspection_id)
        if not insp:
            return False
        insp.deleted_at = datetime.now()
        insp.updated_at = insp.deleted_at
        self.audit.record(
            action="soft_delete",
            entity_type="inspection",
            entity_id=insp.id,
        )
        self.db.commit()
        return True

    def hard_delete(self, inspection_id: int) -> bool:
        """Actually remove the row and its file. Used by tests and admin tools."""
        insp = (
            self.db.query(Inspection).filter(Inspection.id == inspection_id).first()
        )
        if not insp:
            return False
        path = resolve_image_path(insp)
        self.db.delete(insp)
        self.audit.record(
            action="hard_delete",
            entity_type="inspection",
            entity_id=inspection_id,
        )
        self.db.commit()
        path.unlink(missing_ok=True)
        return True

    def restore(self, inspection_id: int) -> Optional[Inspection]:
        insp = (
            self.db.query(Inspection).filter(Inspection.id == inspection_id).first()
        )
        if not insp or insp.deleted_at is None:
            return None
        insp.deleted_at = None
        insp.updated_at = datetime.now()
        self.audit.record(
            action="restore", entity_type="inspection", entity_id=insp.id
        )
        self.db.commit()
        self.db.refresh(insp)
        return insp

    # ------------------------------------------------------------------ #
    # aggregates
    # ------------------------------------------------------------------ #
    def summary_by_user(self) -> list[dict[str, Any]]:
        """Per-user totals, computed by PostgreSQL.

        `outerjoin` keeps users with zero inspections; `group_by` collapses
        them to one row each. Everything happens in one statement — loading the
        rows into Python to count them would not scale.
        """
        rows = self.db.execute(
            select(
                # Labelled to match InspectionSummary.user_id.
                User.id.label("user_id"),
                User.name,
                User.email,
                func.count(Inspection.id).label("inspection_count"),
                func.count(Inspection.id).filter(
                    Inspection.status == "approved"
                ).label("approved_count"),
                func.count(Inspection.id).filter(
                    Inspection.status == "rejected"
                ).label("rejected_count"),
                func.coalesce(func.sum(Inspection.estimated_weight_kg), 0.0).label(
                    "total_weight_kg"
                ),
                func.avg(Inspection.estimated_weight_kg).label("average_weight_kg"),
                func.max(Inspection.created_at).label("last_inspection_at"),
            )
            .select_from(User)
            .outerjoin(
                Inspection,
                and_(
                    Inspection.user_id == User.id,
                    Inspection.deleted_at.is_(None),
                ),
            )
            .group_by(User.id, User.name, User.email)
            .order_by(func.count(Inspection.id).desc())
        ).all()
        return [dict(r._mapping) for r in rows]

    def stats(self, user_id: int | None = None) -> dict[str, Any]:
        """Headline numbers, optionally scoped to one user.

        `user_id` is applied in the WHERE clause rather than by filtering in
        Python, so the aggregate stays a single database round trip.
        """
        stmt = select(
            func.count(Inspection.id),
            func.count(Inspection.id).filter(Inspection.status == "approved"),
            func.count(Inspection.id).filter(Inspection.status == "rejected"),
            func.coalesce(func.sum(Inspection.estimated_weight_kg), 0.0),
        ).where(Inspection.deleted_at.is_(None))

        if user_id is not None:
            stmt = stmt.where(Inspection.user_id == user_id)

        total, approved, rejected, weight = self.db.execute(stmt).one()
        return {
            "inspections": total,
            "approved": approved,
            "rejected": rejected,
            "pending": total - approved - rejected,
            "total_weight_kg": float(weight),
        }

    def users_without_inspections(self) -> list[User]:
        """`~exists()` — 'users with no inspections'.

        The correlated subquery replaces loading every inspection and filtering
        in Python. Note it also has to exclude soft-deleted rows, or a user whose
        only inspections were retired would wrongly appear here.
        """
        has_inspection = select(Inspection.id).where(
            and_(
                Inspection.user_id == User.id,
                Inspection.deleted_at.is_(None),
            )
        )
        return list(self.db.execute(select(User).where(~has_inspection.exists())).scalars())

    def list_cargo_types(self) -> list[CargoType]:
        return list(self.db.execute(select(CargoType).order_by(CargoType.label)).scalars())

    def list_tags(self) -> list[Tag]:
        return list(self.db.execute(select(Tag).order_by(Tag.name)).scalars())