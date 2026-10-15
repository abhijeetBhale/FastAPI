"""Cargo detection endpoints.

Two surfaces, matching the rest of the app:

* `/api/v1/portal/submissions/{id}/detect` — a signed-in user runs detection
  on their **own** submission. This is the self-service path.
* `/api/v1/admin/...` — an admin reads any submission's result. It does not
  live in this file; see `routers/admin.py`.

Every path here is relative to `api.API_PREFIX`, applied in `main.py` rather
than on this router.

Every route follows the app's existing rule: a record that belongs to someone
else returns **404, not 403**, so ids cannot be enumerated.

Response envelope (see `schemas/responses/detection.py`):

* Success: `{ "data": …, "meta": … }` — no `error` key.
* Failure: an RFC 9457 problem document as the entire body — `type`,
  `title`, `status`, `detail` at the top level, exactly like every other
  endpoint's failures (see `errors.problem()` and docs/API_CONVENTIONS.md §4).
"""

from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import FileResponse, Response
from sqlalchemy.orm import Session

from app.api.v1 import API_PREFIX
from app.core.config import get_settings
from app.core.exceptions import problem
from app.core.security import require_current_user
from app.database.base import utcnow
from app.database.database import get_db
from app.models.inspection import Inspection
from app.models.user import User
from app.schemas.requests.detection import DetectRequest
from app.schemas.responses.detection import (
    DetectionAvailability,
    DetectionData,
    DetectionLog,
    DetectionMeta,
    DetectionResponse,
    ImageContext,
    Links,
    MaskMetrics,
    ModelBoxes,
    Rect,
)
from app.schemas.responses.envelope import envelope
from app.services import detection
from app.services.inspection_service import InspectionService, resolve_image_path
from app.services.rbac import P_SUBMISSIONS_CREATE, require_permission

logger = logging.getLogger("app.detection")

router = APIRouter(prefix="/portal", tags=["Detection"])


def _load_owned(db: Session, inspection_id: int, user: User) -> Inspection:
    """Fetch a submission the caller owns, or 404.

    404 rather than 403 on purpose: a 403 would confirm the id exists, letting
    anyone walk the id space to discover other people's submissions.
    """
    insp = InspectionService(db).get_inspection(inspection_id)
    if not insp or insp.user_id != user.id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Submission not found"
        )
    return insp


def _to_rect(box_px: list | None) -> Rect | None:
    """Convert `[x1, y1, x2, y2]` to a self-describing Rect."""
    if not box_px or len(box_px) != 4:
        return None
    x1, y1, x2, y2 = box_px
    return Rect(x=int(x1), y=int(y1), w=int(x2 - x1), h=int(y2 - y1))


def _error_response(
    http_status: int, title: str, detail: str, type_uri: str
) -> Response:
    """Build an RFC 9457 problem response.

    The problem document IS the body — `type`/`title`/`status`/`detail` at
    the top level with `Content-Type: application/problem+json`, exactly as
    the app's global handlers render every other failure (see
    `app/core/exceptions.py` and
    docs/API_CONVENTIONS.md §4). There is no envelope and no `success` flag;
    the HTTP status code carries the outcome.
    """
    return problem(http_status, detail, title=title, type_uri=type_uri)


def _to_envelope(
    insp: Inspection,
    payload: dict | None = None,
    *,
    overlay_base: str = f"{API_PREFIX}/portal/submissions",
) -> dict:
    """Assemble the `{data, meta}` envelope from a stored or fresh result.

    `payload` wins when given, so a run that just completed is reflected
    immediately rather than waiting for a re-read.

    Flat arrays become self-describing Rect objects; related fields are
    grouped; derivable fields (`ok`, `status`, `reason`, `object_count`,
    `box_fraction_of_frame`, `has_overlay`) are dropped.

    `overlay_base` is the router prefix the overlay is served from — the
    portal and admin surfaces own different routes to the same PNG.
    """
    source = payload if payload is not None else (insp.detection_result or {})
    detected = bool(source.get("detected", False))

    # ---- objects ---------------------------------------------------------
    raw_objects = source.get("objects") or []
    objects = []
    for obj in raw_objects:
        models = None
        yolo_box = _to_rect(obj.get("yolo_box_px"))
        sam_box = _to_rect(obj.get("sam_box_px"))
        if yolo_box or sam_box:
            models = ModelBoxes(yolo=yolo_box, sam=sam_box)
        objects.append({
            "label": obj.get("label", ""),
            "yolo_confidence": float(obj.get("yolo_confidence") or 0),
            "sam_score": float(obj.get("sam_score") or 0),
            "mask_area_px": int(obj.get("mask_area_px") or 0),
            "box": _to_rect(obj.get("box_px")),
            "models": models,
        })

    # ---- data ------------------------------------------------------------
    data = DetectionData(
        detected=detected,
        label=source.get("label"),
        aggregate_score=source.get("score"),
        objects=objects,
        box=_to_rect(source.get("box_px")),
        mask=MaskMetrics(
            area_ratio=source.get("mask_area_ratio"),
            border_leak=source.get("border_leak"),
        ),
        detector_origin=source.get("detector_origin"),
        uses_zip_taxonomy=bool(source.get("uses_zip_taxonomy")),
        stage=source.get("stage") or "detection_and_segmentation",
        timed_out=bool(source.get("timed_out")),
    )

    # ---- meta ------------------------------------------------------------
    image = None
    if source.get("image_width") and source.get("image_height"):
        image = ImageContext(
            width=int(source["image_width"]),
            height=int(source["image_height"]),
        )
    links = None
    if insp.detection_overlay or source.get("overlay"):
        links = Links(
            overlay=f"{overlay_base}/{insp.id}/detection/overlay"
        )
    meta = DetectionMeta(
        inspection_id=insp.id,
        detected_at=insp.detected_at,
        elapsed_seconds=source.get("elapsed_seconds"),
        image=image,
        links=links,
    )

    body = DetectionResponse(data=data, meta=meta).model_dump(mode="json")
    return envelope(body["data"], meta=body["meta"])


@router.get(
    "/detection/availability",
    summary="Whether the detector can run, and why not if it cannot",
)
def detection_availability(
    user: User = Depends(require_current_user),
):
    """Lets the UI hide the Detect button instead of offering a failing action.

    Cheaper than having a user press a button that returns 503, and it surfaces
    a misconfigured `DETECTION_PYTHON` as a sentence rather than a stack trace.
    """
    settings = get_settings()
    available, reason = detection.is_available()
    return envelope(
        DetectionAvailability(
            enabled=settings.detection_enabled,
            available=available,
            reason=reason,
            timeout_seconds=settings.detection_timeout if available else None,
        ).model_dump(mode="json")
    )


@router.post(
    "/submissions/{inspection_id}/detect",
    summary="Run cargo detection on one of the caller's submissions",
    dependencies=[Depends(require_permission(P_SUBMISSIONS_CREATE))],
)
def detect_submission(
    inspection_id: int,
    data: Optional[DetectRequest] = None,
    user: User = Depends(require_current_user),
    db: Session = Depends(get_db),
):
    """Detect and segment cargo in a submission's image.

    **This blocks for 16-45 s.** The pipeline runs SAM and YOLO on CPU; there
    is no queue and no background task, so the response arrives when the run
    finishes. `DETECTION_TIMEOUT` (default 300 s) caps it.

    **A refusal is a success.** An image with no cargo returns
    `"detected": false` with HTTP 200, because "nothing there" is a correct
    answer. Only a broken detector produces a non-200 error envelope.

    Re-running replaces the previous result rather than accumulating rows: a
    submission has at most one current detection, and `force=false` returns the
    existing one instead of burning 30 s of CPU to recompute it. The option
    comes from the JSON body (`DetectRequest`), never `?force=` — §5 keeps
    query strings for GET, and a body-less call still works.
    """
    force = bool(data.force) if data else False
    insp = _load_owned(db, inspection_id, user)

    if insp.detection_result is not None and not force:
        return _to_envelope(insp)

    usable, reason = detection.is_available()
    if not usable:
        return _error_response(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "Detection Unavailable",
            reason,
            "https://api.example.com/problems/detection-unavailable",
        )

    image_path = resolve_image_path(insp)
    if not image_path.exists():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Image file is missing, so there is nothing to analyse.",
        )

    logger.info("detection: user %s running on inspection %s", user.id, insp.id)

    try:
        run = detection.run_detection(image_path)
    except detection.DetectionTimeout as exc:
        return _error_response(
            status.HTTP_504_GATEWAY_TIMEOUT,
            "Detection Timeout",
            str(exc),
            "https://api.example.com/problems/detection-timeout",
        )
    except detection.DetectionUnavailable as exc:
        return _error_response(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "Detection Busy",
            str(exc),
            "https://api.example.com/problems/detection-busy",
        )

    # Stored whether or not the run succeeded, so a failure is inspectable
    # rather than a silently absent result.
    insp.detection_result = run.result
    insp.detected_at = utcnow()
    insp.detection_overlay = detection.persist_overlay(run, insp.id)
    insp.updated_at = utcnow()
    db.commit()
    db.refresh(insp)

    # Housekeeping on the same call. Cheap, and an unattended server has no
    # other opportunity to bound its disk usage.
    detection.cleanup_runs(keep=20)

    response = _to_envelope(insp, run.result)
    if not run.result.get("ok", False):
        # The run completed but failed. 200 would tell the caller the
        # detection worked; it did not.
        return _error_response(
            status.HTTP_502_BAD_GATEWAY,
            "Detection Failed",
            run.result.get("error") or "The detector failed.",
            "https://api.example.com/problems/detection-failed",
        )
    return response


@router.get(
    "/submissions/{inspection_id}/detection",
    summary="Read a submission's stored detection result",
)
def get_submission_detection(
    inspection_id: int,
    user: User = Depends(require_current_user),
    db: Session = Depends(get_db),
):
    """The last run's envelope. Never starts a run."""
    insp = _load_owned(db, inspection_id, user)
    return _to_envelope(insp)


@router.get(
    "/submissions/{inspection_id}/detection/log",
    summary="Detector stdout tail, for diagnosing a failed run",
)
def get_submission_detection_log(
    inspection_id: int,
    user: User = Depends(require_current_user),
    db: Session = Depends(get_db),
):
    """Tail of the detector's console output for the most recent run.

    Reads the run directory rather than the database, because the traceback
    only ever existed on stdout. Returns an empty tail if the directory has
    since been swept by `cleanup_runs`.
    """
    insp = _load_owned(db, inspection_id, user)
    run_dir = (insp.detection_result or {}).get("run_dir", "")
    return envelope(
        DetectionLog(
            inspection_id=insp.id,
            returncode=0 if insp.detection_result else 1,
            stdout_tail=detection.run_stdout_log(run_dir),
        ).model_dump(mode="json")
    )


@router.get(
    "/submissions/{inspection_id}/detection/overlay",
    summary="The annotated overlay the pipeline drew",
)
def get_submission_detection_overlay(
    inspection_id: int,
    user: User = Depends(require_current_user),
    db: Session = Depends(get_db),
):
    """PNG with the segmented cargo masked in red and its box drawn.

    A refusal produces no overlay — CELL 10 draws no box when nothing passes
    the acceptance gate — so this 404s.
    """
    insp = _load_owned(db, inspection_id, user)
    if not insp.detection_overlay:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No overlay for this submission — nothing was detected.",
        )
    try:
        path = detection.overlay_path_for(insp.detection_overlay)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail="Overlay not found") from exc
    if not path.is_file():
        raise HTTPException(status_code=404, detail="Overlay file is missing")
    return FileResponse(path, media_type="image/png")
