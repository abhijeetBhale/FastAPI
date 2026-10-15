"""Lifting plan endpoint — one route, one Markdown document.

No CRUD, no tables, no review workflow. The UI calls this, gets a `.md`
document back, renders a preview, offers download. The engineer completes
it on paper or in any markdown editor. See `docs/LIFTING_PLAN.md`.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response
from sqlalchemy.orm import Session

from app.api.v1 import API_PREFIX
from app.api.v1.endpoints.detection import _load_owned
from app.core.security import require_current_user
from app.database.database import get_db
from app.models.user import User
from app.schemas.responses.envelope import envelope
from app.services.lifting_plan import build_lifting_plan, render_markdown

router = APIRouter(prefix="/portal", tags=["Lifting Plan"])


@router.get(
    "/submissions/{inspection_id}/lifting-plan",
    summary="Generate a lifting plan as a Markdown document",
)
def lifting_plan(
    inspection_id: int,
    ref_m: float | None = Query(
        default=None, gt=0, description="Known on-site reference length in metres"
    ),
    ref_px: float | None = Query(
        default=None, gt=0, description="That reference's pixel span in the image"
    ),
    format: str = Query(
        default="markdown", pattern="^(markdown|json)$",
        description="markdown = the document; json = same data structured",
    ),
    user: User = Depends(require_current_user),
    db: Session = Depends(get_db),
):
    """Generate (or regenerate) the lifting plan for one of the caller's
    submissions. There is nothing to store and nothing to update: every call
    recomputes from the current detection, so re-running detection is
    reflected immediately.

    `ref_m` + `ref_px` calibrate the pixel box into metric dimensions via one
    known on-site length. Both must be given together or neither is.
    """
    if (ref_m is None) != (ref_px is None):
        raise HTTPException(
            status_code=422,
            detail="Provide both ref_m and ref_px, or neither.",
        )

    insp = _load_owned(db, inspection_id, user)

    # A plan is about a detected load. Anything else is a clear refusal
    # rather than an empty document the engineer fills from zero.
    if insp.detection_status == "not_run":
        raise HTTPException(
            status_code=422,
            detail=(
                "Run detection first: "
                f"POST {API_PREFIX}/portal/submissions/{{id}}/detect"
            ),
        )
    if insp.detection_status == "no_cargo":
        raise HTTPException(
            status_code=422, detail="Nothing to lift: no cargo was detected."
        )
    if insp.detection_status == "error":
        raise HTTPException(
            status_code=422, detail="The detector failed — resolve that first."
        )

    data = build_lifting_plan(insp, ref_m=ref_m, ref_px=ref_px)

    if format == "json":
        # §1: the plan data is the payload; `generated_at` is response
        # context, so it rides in `meta` — as ISO 8601 UTC, courtesy of
        # the envelope's scrubbing — rather than inside `data`.
        payload = dict(data)
        generated = payload.pop("generated_at", None)
        return envelope(
            payload,
            meta={"generated_at": generated} if generated else None,
        )

    return Response(
        content=render_markdown(data),
        media_type="text/markdown; charset=utf-8",
        headers={
            "Content-Disposition": (
                f'attachment; filename="lifting-plan-{inspection_id}.md"'
            )
        },
    )
