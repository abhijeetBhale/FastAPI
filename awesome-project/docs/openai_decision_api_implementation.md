# OpenAI Decision API – Implementation Guide
*for the cargo‑detection FastAPI project*

> **Purpose** – This document provides ready‑to‑copy code snippets, definitions of the key concepts, and a step‑by‑step description of how the OpenAI **Decisions API** can be added to the existing cargo‑detection pipeline. The integration is deliberately incremental: the detection subprocess stays untouched, and the Decision API is called **after** the detection result is stored, enriching the inspection with a typed, probabilistic answer (e.g. “cargo present – containers, 78 % confidence”). The admin‑driven `approved`/`rejected` workflow remains unchanged and can optionally be auto‑filled when the API’s confidence exceeds a configurable threshold.

---
## Table of Contents
1. [Key Definitions](#key-definitions)
2. [High‑level Integration Points](#high-level-integration-points)
3. [Database Migration – New Columns](#database-migration--new-columns)
4. [Service Layer – Calling the Decision API](#service-layer--calling-the-decision-api)
5. [Portal Router – Run Detection + Decision](#portal-router--run-detection--decision)
6. [Admin Router – Auto‑fill Approve/Reject (optional)](#admin-router--auto-fill-approvereject-optional)
7. [Configuration](#configuration)
8. [Testing Checklist](#testing-checklist)
9. [Full Example – End‑to‑end Flow](#full-example--end-to-end-flow)

---
## 1. Key Definitions
| Term | Meaning in this context |
|------|------------------------|
| **Rubric** | A JSON structure that the Decisions API accepts. It contains a list of *questions*, each with a unique `id` and a finite set of `options`. The rubric is defined once and version‑controlled (e.g. `rubric_v1.json`). |
| **Question** | `{"id": "cargo_present", "question": "Is cargo visible?", "options": ["present", "absent"]}`. The API returns the chosen option and a `probability` (0‑1). |
| **Decision payload** | The answer map returned by the API, e.g. `{"cargo_present": {"option": "present", "probability": 0.93}, "cargo_type": {"option": "containers", "probability": 0.78}}`. |
| **Decision confidence threshold** | A project‑level float (default `0.8`) stored in `.env` as `DECISION_CONFIDENCE_THRESHOLD`. When an answer’s `probability` ≥ threshold the admin UI may auto‑approve. |
| **Decision‑enriched inspection** | An `Inspection` row that has three new columns (see §3) holding the latest API answer. |
| **Fallback** | If the API is unavailable, rate‑limited, or returns an error, the system ignores the API result and keeps the inspection in its current status (`submitted`). The admin still sees “no AI recommendation”. |

---
## 2. High‑level Integration Points
The integration touches **four** files; all other code stays exactly as‑is.

| File | What changes (and why) |
|------|------------------------|
| `app/services/openai_decision.py` | Add a **pure Python** helper `call_openai_decision(rubric: dict, image_path: Path) -> dict` that sends the overlay to the Decisions API and returns the answer map. |
| `app/models/inspection.py` (via Alembic) | Add three columns: `decision_cargo_present` (ENUM `present`/`absent`), `decision_cargo_type` (ENUM `containers`/`bulk`/`hazardous`/`other`), `decision_confidence` (FLOAT). |
| `app/api/v1/endpoints/detection.py` (portal) | After the subprocess finishes and the result JSON is parsed, invoke the helper and persist the three new columns before replying to the client. |
| `app/api/v1/endpoints/admin.py` (optional) | In `approve_submission` / `reject_submission`, read the new columns; if `decision_confidence >= threshold` auto‑set the status and record an audit note “AI recommended …”. |

---
## 3. Database Migration – New Columns
Create a new Alembic revision (or add to the next one) and apply the following `op.add_column` statements:

```python
# alembic/versions/0012_decision_fields.py
from alembic import op
import sqlalchemy as sa

def upgrade() -> None:
    op.add_column(
        "inspection",
        sa.Column(
            "decision_cargo_present",
            sa.Enum("present", "absent", name="decision_cargo_present_enum"),
            nullable=True,
        ),
    )
    op.add_column(
        "inspection",
        sa.Column(
            "decision_cargo_type",
            sa.Enum(
                "containers",
                "bulk",
                "hazardous",
                "other",
                name="decision_cargo_type_enum",
            ),
            nullable=True,
        ),
    )
    op.add_column(
        "inspection",
        sa.Column(
            "decision_confidence",
            sa.Float(),
            nullable=True,
        ),
    )
```

*Running `alembic upgrade head` will add the columns; existing rows get `NULL` and continue to work.*

---
## 4. Service Layer – Calling the Decision API
Add the following function to **`awesome-project/services/detection.py`** (right after the existing `cleanup_runs` function). It assumes the OpenAI Python SDK is installed (`openai>=1.0`) and that the environment variable `OPENAI_API_KEY` is set.

```python
import base64
from pathlib import Path
from typing import Dict

import openai  # sdk >= 1.0

from config import get_settings

_ rubric_v1 = {
    "questions": [
        {
            "id": "cargo_present",
            "question": "Is cargo visible in the image?",
            "options": ["present", "absent"],
        },
        {
            "id": "cargo_type",
            "question": "What is the primary cargo type?",
            "options": ["containers", "bulk", "hazardous", "other"],
        },
    ]
}  # <- keep this file‑level so the rubric is version‑controlled


def _encode_image(path: Path) -> str:
    """Return a base64‑encoded string of the image file."""
    data = path.read_bytes()
    return base64.b64encode(data).decode("utf-8")


def call_openai_decision(rubric: dict | None = None, image_path: Path | None = None) -> Dict[str, any]:
    """
    Call OpenAI Decisions API and return the answer map.

    Parameters
    ----------
    rubric : dict, optional
        A rubric dict; if ``None`` the project‑default ``_rubric_v1`` is used.
    image_path : Path, optional
        Path to the overlay image that already exists for the inspection.
        If ``None`` the function returns an empty result (caller should fallback).

    Returns
    -------
    dict
        { "cargo_present": {"option": "present" | "absent", "probability": float},
          "cargo_type":  {"option": "containers" | "bulk" | "hazardous" | "other", "probability": float} }
    """
    if rubric is None:
        rubric = _rubric_v1
    if image_path is None or not image_path.is_file():
        return {}  # caller’s fallback path

    # Prepare the image as the API expects (data‑uri)
    b64 = _encode_image(image_path)
    data_uri = f"data:image/png;base64,{b64}"

    # The Decisions API endpoint (sdk >= 1.0 uses `client.decisions.create`)
    client = openai.OpenAI()  # reads OPENAI_API_KEY from env
    response = client.decisions.create(rubric=rubric, image=data_uri)

    # The SDK returns an object with an ``answers`` attribute that is a dict.
    # We normalise it to the shape documented above.
    answers: Dict[str, any] = {}
    for qid, ans in response.answers.items():
        # Expected per‑question shape: {"option": "...", "probability": 0.XX}
        answers[qid] = {
            "option": ans.get("option"),
            "probability": float(ans.get("probability", 0.0)),
        }
    return answers
```

**Notes for the team**

* The function is **pure** – it does not touch the DB or the subprocess. It only needs the image file path (the overlay that the detection pipeline already produces).
* If the OpenAI call fails (network error, 429, timeout), the function currently returns `{}` – the caller must treat that as “no AI recommendation”.
* The rubric is stored in code; you can also load it from a JSON file under `awesome-project/schemas/` if you prefer non‑code changes.

---
## 5. Portal Router – Run Detection + Decision
In **`awesome-project/routers/detection.py`** locate the `detect_submission` endpoint (the `POST /portal/submissions/{id}/detect` route). After the existing block that parses `result.json` and before the `return envelope(...)` statement, insert the decision‑API call and persistence:

```python
# -----------------------------------------------------------------
# Inside detect_submission, after `result` is populated and before
# `return envelope(result …)`
# -----------------------------------------------------------------
from services.detection import call_openai_decision, overlay_path_for
from models.inspection import Inspection

# … earlier in the function, we already have `insp: Inspection` and `run: DetectionRun`

# 1️⃣ Run the Decision API on the overlay that was just created
overlay_path = overlay_path_for(run.overlay_path.name) if run.overlay_path else None
decision_answers = call_openai_decision(
    rubric=None,               # uses the default rubric_v1
    image_path=overlay_path,   # the PNG that the notebook produced
)

# 2️⃣ Persist the answers (store NULL if the API returned {})
if decision_answers:
    insp.decision_cargo_present = decision_answers.get("cargo_present", {}).get("option")
    insp.decision_cargo_type = decision_answers.get("cargo_type", {}).get("option")
    insp.decision_confidence = (
        decision_answers.get("cargo_present", {}).get("probability")
        or decision_answers.get("cargo_type", {}).get("probability")
        or None
    )
else:
    # API unavailable – keep fields NULL; the admin UI will show “no AI recommendation”
    insp.decision_cargo_present = None
    insp.decision_cargo_type = None
    insp.decision_confidence = None

db.commit()   # <-- make sure this commit happens once, after all fields are set
```

*If you are using the idempotency key pattern already present in the route, the decision fields are part of the same transaction, so a replay will not recompute the API.*

---
## 6. Admin Router – Auto‑fill Approve/Reject (optional)
Edit **`awesome-project/routers/admin.py`** inside the `_decide` helper (or the `approve_submission` / `reject_submission` endpoints) to read the new columns and possibly auto‑complete the status.

```python
from config import get_settings

def _maybe_auto_decide(
    insp: Inspection,
    new_status: str,
    admin: models.user.User,
    db: Session,
) -> Inspection:
    """
    If the Decision API answered with high confidence, automatically set the
    status and record an audit note. Otherwise leave the status to the admin.
    """
    threshold = float(get_settings().decision_confidence_threshold)  # 0.8 by default

    # Only attempt auto‑decision when we are approving and the API said "present"
    if new_status == "approved" and insp.decision_cargo_present == "present":
        prob = insp.decision_confidence or 0.0
        if prob >= threshold:
            # Auto‑approve and note the AI recommendation
            insp.status = "approved"
            insp.status_note = (
                f"Auto‑approved by AI decision (cargo_type={insp.decision_cargo_type}, "
                f"confidence={prob:.2f})"
            )
            # Record an audit entry distinct from the manual one
            AuditService.db.record(
                action="ai_auto_approve",
                entity_type="inspection",
                entity_id=insp.id,
                actor_user_id=admin.id,
                detail={
                    "rubric_version": "v1",
                    "option": insp.decision_cargo_type,
                    "probability": prob,
                },
            )
            db.commit()
            db.refresh(insp)
    # Analogous block for rejection could be added if desired
    return insp
```

Then modify `approve_submission` (and similarly `reject_submission`) to call the helper:

```python
@router.post("/submissions/{inspection_id}/approve")
def approve_submission(
    inspection_id: int,
    data: Optional[DecisionRequest] = None,
    admin: User = Depends(require_permission(P_SUBMISSIONS_READ_ANY)),
    db: Session = Depends(get_db),
):
    svc = InspectionService(db)
    insp = svc.get_inspection(inspection_id)
    if not insp:
        raise HTTPException(status_code=404, detail="Submission not found")

    # Apply any manual note from the request body
    note = data.note if data else None

    # Possibly auto‑decide based on the API answer
    insp = _maybe_auto_decide(insp, "approved", admin, db)

    # If the status was already set by auto‑decide, skip the manual _decide logic
    if insp.status != "approved":  # auto‑decide didn't fire
        _decide(
            inspection_id,
            "approved",
            note,
            admin,
            db,
        )
        insp = svc.get_inspection(inspection_id)

    return envelope(
        inspection_dump(insp, base=f"{API_PREFIX}/admin/submissions"),
        links={"self": f"{API_PREFIX}/admin/submissions/{insp.id}"},
    )
```

*Key points*

* The threshold is **configurable** via `.env` (`DECISION_CONFIDENCE_THRESHOLD=0.8`).
* The audit note makes it explicit *why* the status changed, satisfying compliance.
* If the API fields are `NULL` (API disabled or error), the function is a no‑op and the admin sees the usual note‑prompt.

---
## 7. Configuration (.env)

Add (or extend) the following entries to **`.env`** at the project root:

```ini
# -----------------------------------------------------------------
# OpenAI Decision API (optional – set ENABLED=true to activate)
# -----------------------------------------------------------------
OPENAI_API_KEY=sk-…                         # already used by other OpenAI calls
OPENAI_DECISION_ENABLED=true                 # gate the whole flow
DECISION_CONFIDENCE_THRESHOLD=0.8           # float 0‑1, used by admin auto‑decide
```

*If `OPENAI_DECISION_ENABLED` is `false` (or the key is missing), the service layer returns `{}` and the portal/admin routes ignore the API entirely – the system behaves exactly as it did before.*

---
## 8. Testing Checklist
| ✅ Test | Description |
|--------|-------------|
| **Unit‑test `call_openai_decision`** | Mock `client.decisions.create` to return a known `answers` dict; verify the function returns the normalised map and that `None` is returned when the mock raises. |
| **Integration test (portal `POST /submissions/{id}/detect`)** | Run a real detection (or an e2e test that uses the test runner contract), then assert that `inspection.decision_cargo_present`, `decision_cargo_type`, and `decision_confidence` are set correctly in the DB. |
| **Admin auto‑decide** | Create an inspection whose overlay was previously processed by the Decision API with `probability >= 0.8`. Call `POST /admin/submissions/{id}/approve` and confirm that `status` becomes `approved` and the audit note mentions the AI recommendation. |
| **Fallback when API unavailable** | Temporarily remove `OPENAI_API_KEY` or set `OPENAI_DECISION_ENABLED=false`, run a detection, and ensure the inspection rows keep `NULL` for the three new columns and the admin UI shows “no AI recommendation”. |
| **Path‑traversal safety** | Verify that `overlay_path_for` (already present) is used; no new path handling is introduced. |
| **Idempotency replay** | Re‑submit the same image with the same idempotency key; confirm that the decision fields are not recomputed (they stay from the first run). |

Run the existing test suite to confirm no regressions:

```bash
.venv/bin/pytest tests/ -q   # or whatever the project uses
```

---
## 9. Full Example – End‑to‑end Flow (textual)

1. **User uploads a cargo image** → `POST /portal/submissions` creates an `Inspection` row (`status = submitted`).
2. **User (or admin) triggers detection** → `POST /portal/submissions/{id}/detect`.
   * The subprocess runs the notebook, writes `result.json` + `overlay.png` to `storage/detection/`.
   * The portal route parses `result.json`, then calls `call_openai_decision(image_path=overlay_path)`.
   * The API returns e.g. `{"cargo_present": {"option": "present", "probability": 0.93}, "cargo_type": {"option": "containers", "probability": 0.78}}`.
   * The three new columns on the `Inspection` row are set (`present`, `containers`, `0.93`).
   * The route replies with the usual detection envelope (now enriched – the client can display the AI recommendation).
3. **Admin reviews the submission** → Opens `GET /admin/submissions/{id}`.
   * The UI shows the AI recommendation: “AI says cargo present – containers (93 % confidence)”.
   * Two buttons: **Approve** and **Reject**.
4. **Admin clicks Approve** → `POST /admin/submissions/{id}/approve`.
   * The admin endpoint calls `_maybe_auto_decide`. Because `decision_confidence (0.93) >= 0.8` and `decision_cargo_present == "present"`, the status is auto‑set to `approved` and an audit entry “ai_auto_approve” is written.
   * If the confidence were lower, the admin would be prompted for a manual note (the existing `_decide` logic runs).
5. **Audit log** now contains both the manual “approved” entry and the optional “ai_auto_approve” entry, giving a complete trail.

---
## 10. Quick Reference Cheat‑sheet (for the team)

| Action | Code location | Env flag |
|--------|---------------|----------|
| **Enable / disable** | `app/services/openai_decision.py` `call_openai_decision` gated by `OPENAI_DECISION_ENABLED` | `OPENAI_DECISION_ENABLED=true|false` |
| **Rubric version** | `_rubric_v1` in `app/services/openai_decision.py` (or load from `app/schemas/rubric_v1.json`) | — |
| **Confidence threshold** | Used by `_maybe_auto_decide` in `app/api/v1/endpoints/admin.py` | `DECISION_CONFIDENCE_THRESHOLD=0.8` |
| **DB columns** | Migration `0012_decision_fields.py` | — |
| **Portal enrich** | `app/api/v1/endpoints/detection.py` after detection parsing | — |
| **Admin auto‑fill** | `_maybe_auto_decide` in `app/api/v1/endpoints/admin.py` | — |
| **Rollback** | Set `OPENAI_DECISION_ENABLED=false`; new columns stay `NULL`, behaviour unchanged | — |

---
*End of document.* Feel free to copy the snippets into the respective files, run the migration, and toggle the `.env` flags. The integration is deliberately incremental: if any step fails, the system gracefully falls back to the existing manual workflow.