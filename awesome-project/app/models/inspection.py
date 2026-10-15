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
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.database.base import Base, utcnow

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
        # "Which submissions have never been detected" drives the portal's
        # filter, and would otherwise scan every live row.
        Index(
            "ix_inspections_detected_at",
            "detected_at",
            postgresql_where=text("deleted_at IS NULL"),
        ),
        # Same reasoning for the AI decision step run during upload.
        Index(
            "ix_inspections_decided_at",
            "decided_at",
            postgresql_where=text("deleted_at IS NULL"),
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
    # Left null by the detector on purpose. Its measurement stage returns
    # *relative* volume from normalised camera intrinsics, and everything
    # scales off a hardcoded REFERENCE_WIDTH_METERS = 2.0 — so these stay empty
    # rather than holding dimensionless numbers in metrically-named columns.
    volume_m3: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    estimated_weight_kg: Mapped[Optional[float]] = mapped_column(Float, nullable=True)

    # ---- cargo detection (SAM + YOLO) ------------------------------------
    # JSONB, not columns: the report shape changes as the pipeline evolves.
    # Null means "never run", which is distinct from "run, found nothing" —
    # that case holds a result with `detected: false`.
    detection_result: Mapped[Optional[dict]] = mapped_column(
        JSONB, nullable=True
    )
    detected_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime, nullable=True
    )
    # The red-mask overlay the pipeline drew, if any. A refusal produces no
    # overlay, so this can be null while detection_result is populated.
    detection_overlay: Mapped[Optional[str]] = mapped_column(
        String(255), nullable=True
    )

    # ---- AI decision (OpenAI Decisions API, runs during upload) -----------
    # Same reasoning as detection_result: the answers' shape belongs to the
    # API's contract and may gain questions, so the whole verdict lives in one
    # JSONB column rather than a family of columns per answer. Null means
    # "never ran" (feature off or row predates it), which is distinct from a
    # stored `ok: false` — enabled, but the call failed and the submission
    # went to manual review anyway.
    decision_result: Mapped[Optional[dict]] = mapped_column(
        JSONB, nullable=True
    )
    decided_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime, nullable=True
    )

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
        DateTime, nullable=False, default=utcnow
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

    # ---- detection views ---------------------------------------------------

    @property
    def detection_status(self) -> str:
        """`not_run` | `detected` | `no_cargo` | `error`.

        Derived rather than stored, so it can never disagree with
        `detection_result`. Note `not_run` and `no_cargo` are different
        answers: the first means nobody has tried, the second means the
        pipeline looked and found nothing.
        """
        if self.detection_result is None:
            return "not_run"
        if not self.detection_result.get("ok", False):
            return "error"
        return "detected" if self.detection_result.get("detected") else "no_cargo"

    @property
    def cargo_object_count(self) -> int:
        """Number of cargo regions the pipeline segmented, or 0."""
        if not self.detection_result:
            return 0
        return int(self.detection_result.get("object_count") or 0)

    # ---- AI decision views -------------------------------------------------

    @property
    def decision_status(self) -> str:
        """`not_run` | `ok` | `error`.

        Derived rather than stored, mirroring `detection_status`: `not_run`
        means the step was never attempted (feature off, or the row is older
        than the integration), `error` means it was attempted and failed. In
        both cases the fallback is the ordinary manual review queue.
        """
        if self.decision_result is None:
            return "not_run"
        return "ok" if self.decision_result.get("ok") else "error"

    @property
    def ai_recommendation(self) -> Optional[str]:
        """`approve` | `review` as of upload time, or None without a verdict.

        A snapshot of the AI's opinion, deliberately not updated when a human
        later decides the other way — the audit trail keeps both.
        """
        if not self.decision_result:
            return None
        return self.decision_result.get("recommendation")

    @property
    def ai_answers(self) -> Optional[dict]:
        """The rubric answers keyed by question name, or None."""
        if not self.decision_result:
            return None
        return self.decision_result.get("answers")

    def __repr__(self) -> str:
        return f"<Inspection {self.id} {self.status}>"