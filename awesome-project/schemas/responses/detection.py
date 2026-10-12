"""Detection response shapes.

The pipeline's own report is stored and returned verbatim — it is the detector's
contract, not this API's, and re-modelling it here would mean a migration every
time a field is added. These schemas wrap it with the metadata the caller
actually needs to make a decision.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, Field


class DetectedObject(BaseModel):
    """One cargo region the pipeline segmented.

    `box_px` is `[x1, y1, x2, y2]` in full-image pixels — CELL 10 lifts the
    ROI-local mask back to the frame before measuring, so these need no
    translation to overlay on the original image.
    """

    label: str
    yolo_confidence: float
    sam_score: float
    mask_area_px: int
    box_px: Optional[list[float]] = None
    yolo_box_px: Optional[list[float]] = None
    sam_box_px: Optional[list[float]] = None

    model_config = {"from_attributes": True}


class DetectionReport(BaseModel):
    """One detection run's outcome.

    `detected: false` is a successful run that found no cargo, not a failure —
    a hazy night frame genuinely may contain nothing, and the caller needs to
    tell that apart from the pipeline being broken. `ok` carries the latter.
    """

    ok: bool
    detected: bool
    status: str = Field(
        description="not_run | detected | no_cargo | error — derived, not stored"
    )
    reason: Optional[str] = Field(
        default=None,
        description=(
            "Why nothing was accepted: no_candidate_masks, "
            "below_acceptance_gate, or no_verdict_parsed"
        ),
    )

    # ---- what the detector found -----------------------------------------
    label: Optional[str] = Field(
        default=None, description="Winning class, e.g. 'Cargo-Box'"
    )
    score: Optional[float] = Field(
        default=None,
        description=(
            "CELL 10 selection score. Higher is better; the acceptance "
            "threshold is 6.0, so a value just above it is a weak accept."
        ),
    )
    object_count: int = 0
    objects: list[DetectedObject] = Field(default_factory=list)

    # ---- geometry, in pixels ---------------------------------------------
    box_px: Optional[list[float]] = Field(
        default=None, description="Winning box [x1,y1,x2,y2], full-image pixels"
    )
    box_width_px: Optional[float] = None
    box_height_px: Optional[float] = None
    box_fraction_of_frame: Optional[float] = Field(
        default=None,
        description="0-1. CELL 10's gate rejects anything above 0.60.",
    )
    mask_area_ratio: Optional[float] = Field(
        default=None,
        description=(
            "Segmented cargo as a 0-1 share of the frame. Measured on the "
            "mask, so it is smaller than box_fraction_of_frame."
        ),
    )
    border_leak: Optional[float] = Field(
        default=None,
        description=(
            "0-1 share of the frame's 3px border ring covered by the mask. "
            "Sky and water masks glue to the border; suspended cargo does not. "
            "The gate rejects above 0.12."
        ),
    )
    image_width: Optional[int] = None
    image_height: Optional[int] = None

    # ---- provenance ------------------------------------------------------
    detector_origin: Optional[str] = Field(
        default=None,
        description=(
            "zip_trained_obb | custom_yolo11 | coco_pretrained_fallback. "
            "Only zip_trained_obb has class-aware net/hook suppression."
        ),
    )
    uses_zip_taxonomy: bool = False
    stage: str = "detection_and_segmentation"

    # ---- run bookkeeping -------------------------------------------------
    error: Optional[str] = None
    timed_out: bool = False
    elapsed_seconds: Optional[float] = None
    has_overlay: bool = False
    overlay_url: Optional[str] = None
    detected_at: Optional[datetime] = None
    inspection_id: Optional[int] = None

    model_config = {"from_attributes": True}


class DetectionAvailability(BaseModel):
    """Whether the detector can be used, and why not if it cannot."""

    enabled: bool
    available: bool
    reason: str
    timeout_seconds: Optional[int] = None
    supports_measurement: bool = Field(
        default=False,
        description=(
            "Always false. The pipeline's depth/volume/weight stage is not run: "
            "its output is relative, not metric."
        ),
    )


class DetectionLog(BaseModel):
    """Tail of the detector's stdout. For diagnosing a failed run."""

    inspection_id: int
    returncode: int
    stdout_tail: str
