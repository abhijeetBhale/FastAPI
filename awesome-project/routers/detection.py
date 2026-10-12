"""Cargo detection endpoints.

Two surfaces, matching the rest of the app:

* `/portal/detect/...` — a signed-in user runs detection on their **own**
  submission. This is the self-service path.
* `/admin/...` — an admin reads any submission's result. It does not live in
  this file; see `routers/admin.py`.

Every route follows the app's existing rule: a record that belongs to someone
else returns **404, not 403**, so ids cannot be enumerated.
"""

from __future__ import annotations

import logging
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from config import get_settings
from database import get_db
from models.inspection import Inspection
from models.user import User
from schemas.responses.detection import (
    DetectionAvailability,
    DetectionLog,
    DetectionReport,
)
from services import detection
from services.inspection_service import InspectionService, resolve_image_path
from services.rbac import P_SUBMISSIONS_CREATE, require_permission
from services.security import require_current_user

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


def _to_report(
    insp: Inspection, payload: dict | None = None, *, run=None
) -> DetectionReport:
    """Assemble a response from the stored result, or a fresh run's.

    `payload` wins when given, so a run that just completed is reflected
    immediately rather than waiting for a re-read.
    """
    source = payload if payload is not None else (insp.detection_result or {})
    ok = bool(source.get("ok", False))
    detected = bool(source.get("detected", False))

    if insp.detection_result is None and payload is None:
        status_str = "not_run"
    elif not ok:
        status_str = "error"
    else:
        status_str = "detected" if detected else "no_cargo"

    has_overlay = bool(insp.detection_overlay) or bool(source.get("overlay"))
    overlay_url = (
        f"/portal/submissions/{insp.id}/detection/overlay" if has_overlay else None
    )

    return DetectionReport(
        ok=ok,
        detected=detected,
        status=status_str,
        reason=source.get("reason"),
        label=source.get("label"),
        score=source.get("score"),
        object_count=int(source.get("object_count") or 0),
        objects=source.get("objects") or [],
        box_px=source.get("box_px"),
        box_width_px=source.get("box_width_px"),
        box_height_px=source.get("box_height_px"),
        box_fraction_of_frame=source.get("box_fraction_of_frame"),
        mask_area_ratio=source.get("mask_area_ratio"),
        border_leak=source.get("border_leak"),
        image_width=source.get("image_width"),
        image_height=source.get("image_height"),
        detector_origin=source.get("detector_origin"),
        uses_zip_taxonomy=bool(source.get("uses_zip_taxonomy")),
        stage=source.get("stage") or "detection_and_segmentation",
        error=source.get("error"),
        timed_out=bool(source.get("timed_out")),
        elapsed_seconds=source.get("elapsed_seconds"),
        has_overlay=has_overlay,
        overlay_url=overlay_url,
        detected_at=insp.detected_at,
        inspection_id=insp.id,
    )


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
    return DetectionAvailability(
        enabled=settings.detection_enabled,
        available=available,
        reason=reason,
        timeout_seconds=settings.detection_timeout if available else None,
    )


@router.post(
    "/submissions/{inspection_id}/detect",
    summary="Run cargo detection on one of the caller's submissions",
    dependencies=[Depends(require_permission(P_SUBMISSIONS_CREATE))],
)
def detect_submission(
    inspection_id: int,
    force: bool = Query(
        default=False,
        description=(
            "Re-run even if a result already exists. Useful after the detector "
            "or its weights change."
        ),
    ),
    user: User = Depends(require_current_user),
    db: Session = Depends(get_db),
):
    """Detect and segment cargo in a submission's image.

    **This blocks for 16-45 s.** The pipeline runs SAM and YOLO on CPU; there
    is no queue and no background task, so the response arrives when the run
    finishes. `DETECTION_TIMEOUT` (default 300 s) caps it.

    **A refusal is a success.** An image with no cargo returns
    `"detected": false` with HTTP 200, because "nothing there" is a correct
    answer. Only a broken detector produces `ok: false` or a non-200.

    Re-running replaces the previous result rather than accumulating rows: a
    submission has at most one current detection, and `force=False` returns the
    existing one instead of burning 30 s of CPU to recompute it.
    """
    insp = _load_owned(db, inspection_id, user)

    if insp.detection_result is not None and not force:
        return _to_report(insp)

    usable, reason = detection.is_available()
    if not usable:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "message": reason,
                "code": "detection_unavailable",
                "hint": (
                    "Set DETECTION_ENABLED=true in .env and point "
                    "DETECTION_PYTHON / DETECTION_PROJECT_DIR at the detection "
                    "project. See scripts/detect_runner.py."
                ),
            },
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
        raise HTTPException(
            status_code=status.HTTP_504_GATEWAY_TIMEOUT,
            detail={"message": str(exc), "code": "detection_timeout"},
        ) from exc
    except detection.DetectionUnavailable as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"message": str(exc), "code": "detection_busy"},
        ) from exc

    # Stored whether or not the run succeeded, so a failure is inspectable
    # rather than a silently absent result. A timeout raised above and never
    # reaches this point, which is deliberate: a killed run has no trustworthy
    # numbers to keep.
    insp.detection_result = run.result
    insp.detected_at = datetime.now()
    insp.detection_overlay = detection.persist_overlay(run, insp.id)
    insp.updated_at = datetime.now()
    db.commit()
    db.refresh(insp)

    # Housekeeping on the same call. Cheap, and an unattended server has no
    # other opportunity to bound its disk usage.
    detection.cleanup_runs(keep=20)

    report = _to_report(insp, run.result, run=run)
    if not report.ok:
        # The run completed but failed. 200 would tell the caller the detection
        # worked; it did not.
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail={
                "message": report.error or "The detector failed.",
                "code": "detection_failed",
                "report": report.model_dump(mode="json"),
            },
        )
    return report


@router.get(
    "/submissions/{inspection_id}/detection",
    summary="Read a submission's stored detection result",
)
def get_submission_detection(
    inspection_id: int,
    user: User = Depends(require_current_user),
    db: Session = Depends(get_db),
):
    """The last run's report. Never starts a run.

    Use `?include_log=true` when diagnosing a failure — the detector's stdout
    tail carries the traceback, which the stored JSON does not.
    """
    insp = _load_owned(db, inspection_id, user)
    return _to_report(insp)


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

    The runner inherits stdout rather than capturing it, so a traceback exists
    nowhere but the console. This returns the persisted copy, which is written
    only when a run is killed — a completed run's diagnostics are already in
    the report itself. An empty tail after `cleanup_runs` swept the directory is
    expected, not an error.
    """
    insp = _load_owned(db, inspection_id, user)
    run_dir = (insp.detection_result or {}).get("run_dir", "")
    return DetectionLog(
        inspection_id=insp.id,
        returncode=0 if insp.detection_result else 1,
        stdout_tail=detection.run_stdout_log(run_dir),
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
    the acceptance gate — so this 404s for `status: "no_cargo"`.
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
