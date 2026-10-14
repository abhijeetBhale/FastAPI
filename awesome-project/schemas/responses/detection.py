"""Detection response shapes — three-part envelope.

Success: `{ "data": …, "meta": … }` — no `error` key.
Failure: an RFC 9457 problem document as the entire body, rendered by
`errors.problem()` (`type`/`title`/`status`/`detail` at the top level,
`Content-Type: application/problem+json`) — see docs/API_CONVENTIONS.md §4.

`data` holds the business result (detection outcome, objects, geometry).
`meta` holds provenance, timing, and image context. HTTP status codes
carry transport-level success; the body never needs a `success` flag.

The pipeline's own report is stored verbatim in `detection_result` — it is
the detector's contract, not this API's. These schemas wrap it with the
metadata the caller needs to make a decision.
"""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field

from schemas.responses.envelope import IsoDateTime


# ---- envelope-only models (availability/log kept below) ---------------

class Rect(BaseModel):
    """Axis-aligned rectangle in full-image pixels."""

    x: int
    y: int
    w: int
    h: int


class ModelBoxes(BaseModel):
    """Per-model boxes. Present when YOLO and SAM diverge."""

    yolo: Optional[Rect] = None
    sam: Optional[Rect] = None


class DetectedObject(BaseModel):
    """One cargo region the pipeline segmented.

    `box` is the tight AABB from the mask, in full-image pixels — CELL 10
    lifts the ROI-local mask back to the frame before measuring, so these
    need no translation to overlay on the original image.
    """

    label: str
    yolo_confidence: float
    sam_score: float
    mask_area_px: int
    box: Rect
    models: Optional[ModelBoxes] = None


class MaskMetrics(BaseModel):
    """Segmentation quality metrics."""

    area_ratio: Optional[float] = Field(
        default=None,
        description="Segmented cargo as a 0-1 share of the frame",
    )
    border_leak: Optional[float] = Field(
        default=None,
        description=(
            "Share of the frame's 3px border ring covered by the mask. "
            "Sky and water masks glue to the border; suspended cargo does "
            "not. The gate rejects above 0.12."
        ),
    )


# ---- data ------------------------------------------------------------------

class DetectionData(BaseModel):
    """The detection outcome: what was found, where, and how well."""

    detected: bool
    label: Optional[str] = Field(
        default=None, description="Winning class, e.g. 'Cargo-Box'"
    )
    aggregate_score: Optional[float] = Field(
        default=None,
        description=(
            "CELL 10 selection score. Higher is better; the acceptance "
            "threshold is 6.0, so a value just above it is a weak accept."
        ),
    )
    objects: list[DetectedObject] = Field(default_factory=list)
    box: Optional[Rect] = Field(
        default=None,
        description="Primary detection box, full-image pixels",
    )
    mask: Optional[MaskMetrics] = None
    detector_origin: Optional[str] = Field(
        default=None,
        description=(
            "zip_trained_obb | custom_yolo11 | coco_pretrained_fallback. "
            "Only zip_trained_obb has class-aware net/hook suppression."
        ),
    )
    uses_zip_taxonomy: bool = False
    stage: str = "detection_and_segmentation"
    timed_out: bool = False


# ---- meta ------------------------------------------------------------------

class ImageContext(BaseModel):
    """Frame dimensions."""

    width: Optional[int] = None
    height: Optional[int] = None


class Links(BaseModel):
    """Related resources. Keys omitted when absent."""

    overlay: Optional[str] = Field(
        default=None,
        description="Relative URL to the annotated overlay PNG",
    )


class DetectionMeta(BaseModel):
    """Provenance, timing, and image context."""

    inspection_id: int
    detected_at: Optional[IsoDateTime] = Field(
        default=None, description="ISO 8601 timestamp of detection"
    )
    elapsed_seconds: Optional[float] = Field(
        default=None, description="Pipeline wall-clock time in seconds"
    )
    image: Optional[ImageContext] = None
    links: Optional[Links] = None# ---- envelopes -------------------------------------------------------------
class DetectionResponse(BaseModel):
    """Success envelope."""

    data: DetectionData
    meta: DetectionMeta


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
