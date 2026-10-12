from datetime import datetime
from typing import TYPE_CHECKING, Any, Optional

from sqlalchemy import (
    String,
    Integer,
    Float,
    DateTime,
    ForeignKey,
    CheckConstraint,
    Index,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship
from database import Base

if TYPE_CHECKING:  # avoids circular imports at runtime
    from .cargo_type import CargoType
    from .tag import Tag
    from .user import User

#: Allowed workflow states.
STATUS_DRAFT = "draft"
STATUS_SUBMITTED = "submitted"
STATUS_APPROVED = "approved"
STATUS_REJECTED = "rejected"
INSPECTION_STATUSES = (
    STATUS_DRAFT,
    STATUS_SUBMITTED,
    STATUS_APPROVED,
    STATUS_REJECTED,
)


class Inspection(Base):
    __tablename__ = "inspections"
    __table_args__ = (
        CheckConstraint(
            "status IN ('draft','submitted','approved','rejected')",
            name="ck_inspections_status",
        ),
        # Partial index: soft-deleted rows are never filtered on.
        Index(
            "ix_inspections_created_at_live",
            "created_at",
            postgresql_where=text("deleted_at IS NULL"),
        ),
        # Declared so autogenerate keeps them; created in migration 0008.
        Index("ix_inspections_created_at", "created_at"),
        # The review queue: submitted and not yet deleted, oldest first.
        Index(
            "ix_inspections_pending_review",
            "created_at",
            postgresql_where=text("status = 'submitted' AND deleted_at IS NULL"),
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)

    # ---- who submitted this ---------------------------------------------
    # Name, email and phone live on `users`; this is the single source of truth.
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id"), nullable=False, index=True
    )

    # ---- review -----------------------------------------------------------
    # Who made the approve/reject decision, and when. Set by an admin; a user
    # can never populate these.
    reviewed_by: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id"), nullable=True, index=True
    )
    reviewed_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    cargo_type_id: Mapped[int] = mapped_column(
        ForeignKey("cargo_types.id"), nullable=False, index=True
    )

    # `foreign_keys` disambiguates the two paths to `users`: this relationship
    # is the submitter, not the reviewer (see `reviewer` below).
    user: Mapped["User"] = relationship(
        lazy="selectin", foreign_keys=[user_id], back_populates="inspections"
    )
    reviewer: Mapped[Optional["User"]] = relationship(
        lazy="selectin", foreign_keys=[reviewed_by]
    )
    # Named `cargo_type_ref` because `cargo_type` is a property returning the
    # slug; a relationship of the same name would be shadowed.
    cargo_type_ref: Mapped["CargoType"] = relationship(
        lazy="selectin", viewonly=True
    )

    # ---- workflow --------------------------------------------------------
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default=STATUS_SUBMITTED, index=True
    )
    status_note: Mapped[Optional[str]] = mapped_column(String(300), nullable=True)

    notes: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)

    # ---- measurement (populated by the detection pipeline) ---------------
    volume_m3: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    estimated_weight_kg: Mapped[Optional[float]] = mapped_column(Float, nullable=True)

    # ---- stored image metadata (the file itself lives on disk) -----------
    image_filename: Mapped[str] = mapped_column(String(255), nullable=False)
    image_original_name: Mapped[str] = mapped_column(String(255), nullable=False)
    image_content_type: Mapped[str] = mapped_column(String(50), nullable=False)
    image_size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    image_width: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    image_height: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    # Indexed via the partial `ix_inspections_created_at_live` below, plus the
    # full-column index created in migration 0008 for non-soft-deleted queries.
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=lambda: datetime.now()
    )
    updated_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    # Soft delete: rows are hidden, not destroyed.
    deleted_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime, nullable=True, index=True
    )

    # ---- many-to-many tags ----------------------------------------------
    tags: Mapped[list["Tag"]] = relationship(
        secondary="inspection_tags",
        back_populates="inspections",
        lazy="selectin",
    )

    # ---- flattened views for the response schema -------------------------
    # Properties, not columns, so the API returns a flat shape without
    # duplicating user or cargo data here.

    @property
    def name(self) -> str | None:
        return self.user.name if self.user else None

    @property
    def email(self) -> str | None:
        return self.user.email if self.user else None

    @property
    def phone(self) -> str | None:
        return self.user.phone if self.user else None

    @property
    def image_url(self) -> str:
        return f"/inspections/{self.id}/image"

    @property
    def cargo_type(self) -> str | None:
        """The slug, so the API shape stays a plain string.

        The attribute name deliberately shadows the relationship: callers and
        Pydantic both expect a scalar here, not a CargoType instance.
        """
        return self.cargo_type_ref.slug if self.cargo_type_ref else None

    @property
    def cargo_label(self) -> str | None:
        return self.cargo_type_ref.label if self.cargo_type_ref else None

    @property
    def density_kg_m3(self) -> float | None:
        return self.cargo_type_ref.density_kg_m3 if self.cargo_type_ref else None

    @property
    def is_deleted(self) -> bool:
        return self.deleted_at is not None

    def __repr__(self) -> str:
        return f"<Inspection {self.id} {self.status}>"