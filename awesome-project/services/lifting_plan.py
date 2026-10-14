"""Lifting plan generation — one Markdown document, no persistence.

The plan is a safety document, so the rule is: the AI fills in what it
observed, the engineer fills in what only an engineer can know, and every
AI value is marked as an estimate. Nothing is stored — the document is
regenerated on every call, so re-detection is picked up for free and there
is no stale data to audit.

See `docs/LIFTING_PLAN.md` for the full design and the client's paper form
this mirrors (Part 2: load, Part 3: equipment/gears + load calculation,
Part 4: sketch).
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from api import API_PREFIX
from database import utcnow
from models.inspection import Inspection

#: Warning thresholds. Client-confirmable; defaults per LIFTING_PLAN.md §6.
WARN_ESTIMATE_USED_PCT = 75.0
WARN_ABSOLUTE_USED_PCT = 90.0
WARN_SAFETY_FACTOR = 1.5


def build_lifting_plan(
    insp: Inspection,
    *,
    ref_m: Optional[float] = None,
    ref_px: Optional[float] = None,
) -> dict:
    """Assemble the structured lifting-plan data for one submission.

    Every AI observation is included with its provenance; everything else is
    a blank for the engineer. `ref_m` / `ref_px` are one known on-site
    reference length (e.g. a container width) that calibrates the pixel box
    into metric dimensions — the honest bridge while the depth/volume stage
    (notebook cells 12–28) stays unrun.
    """
    result = insp.detection_result or {}
    cargo = insp.cargo_type_ref

    # ---- description ---------------------------------------------------
    count = int(result.get("object_count") or 0)
    label = result.get("label") or "cargo"
    if cargo:
        description = f"{count} × {label} ({cargo.label})"
    else:
        description = f"{count} × {label}"

    # ---- dimensions ----------------------------------------------------
    box = result.get("box_px") or []
    box_w_px = result.get("box_width_px")
    box_h_px = result.get("box_height_px")
    if box_w_px is None and len(box) == 4:
        box_w_px = round(float(box[2]) - float(box[0]), 1)
    if box_h_px is None and len(box) == 4:
        box_h_px = round(float(box[3]) - float(box[1]), 1)

    dims: dict = {
        "l_m": None, "w_m": None, "h_m": None,
        "source": "none", "m_per_px": None, "reference": None,
    }
    if ref_m and ref_px and box_w_px and box_h_px:
        m_per_px = ref_m / ref_px
        dims = {
            "l_m": round(box_w_px * m_per_px, 2),
            # W (depth) is never visible in one photo — always blank.
            "w_m": None,
            "h_m": round(box_h_px * m_per_px, 2),
            "source": "estimated",
            "m_per_px": round(m_per_px, 6),
            "reference": {"label": "on-site reference", "m": ref_m, "px": ref_px},
        }

    # ---- weight --------------------------------------------------------
    weight: dict = {"kg": None, "source": "none", "density_kg_m3": None}
    if cargo and cargo.density_kg_m3:
        weight["density_kg_m3"] = cargo.density_kg_m3
        if dims["l_m"] and dims["h_m"]:
            # W unknown → assume the smaller visible dimension. Flagged in
            # the document; the engineer must correct it.
            w_est = min(dims["l_m"], dims["h_m"])
            weight["kg"] = round(
                cargo.density_kg_m3 * dims["l_m"] * w_est * dims["h_m"]
            )
            weight["source"] = "estimate"

    # ---- theoretical rigging model (Option 2) --------------------------
    rigging = _theoretical_rigging(box, box_w_px, box_h_px)

    # ---- warnings ------------------------------------------------------
    warnings: list[str] = []
    if weight["source"] == "estimate" and weight["kg"]:
        warnings.append(
            "Weight is an AI estimate from box dimensions — confirm by "
            "weighing before the lift."
        )

    return {
        "inspection_id": insp.id,
        "generated_at": utcnow(),
        "detection_status": insp.detection_status,
        "description": description,
        "objects": result.get("objects") or [],
        "box_px": box,
        "box_width_px": box_w_px,
        "box_height_px": box_h_px,
        "image_width": result.get("image_width"),
        "image_height": result.get("image_height"),
        "dimensions": dims,
        "weight": weight,
        "rigging": rigging,
        "warnings": warnings,
        "overlay_url": (
            f"{API_PREFIX}/portal/submissions/{insp.id}/detection/overlay"
            if insp.detection_overlay else None
        ),
    }


def _theoretical_rigging(
    box: list, box_w_px, box_h_px
) -> dict:
    """Theoretical CoG + hook placement — a 2-leg bridle model.

    EVERY value here is derived from assumptions, not measurement. The
    model exists to give the engineer a *starting geometry* to react to,
    not a certified rigging plan. All assumptions are returned alongside
    the numbers so the document can state them inline.

    Model:
      - CoG = geometric centre of the detection box (assumes uniform
        density; bagged cargo may sit lower)
      - 2-leg bridle, slings attached at the top corners of the box
      - sling length = SLING_RATIO × load height (default 2.0)
      - hook point on the vertical axis above CoG

    Geometry (top view collapsed to the sag plane):
      w  = half box width            (horizontal offset CoG → corner)
      h  = load height
      L  = sling length = ratio × h
      r  = vertical rise = √(L² − w²)
      θ  = angle from vertical = atan(w / r)
    """
    if not box or len(box) != 4 or not box_w_px or not box_h_px:
        return {"available": False, "reason": "no detection box"}

    x1, y1, x2, y2 = [float(v) for v in box[:4]]
    w = box_w_px / 2.0
    h = float(box_h_px)
    ratio = 2.0
    L = ratio * h

    cog_x = (x1 + x2) / 2.0
    cog_y = (y1 + y2) / 2.0

    if L <= w:
        return {
            "available": False,
            "reason": (
                f"sling length ({L:.0f} px) must exceed half box width "
                f"({w:.0f} px) — increase sling length"
            ),
        }

    r = (L * L - w * w) ** 0.5
    hook_x = cog_x
    hook_y = y1 - r
    angle_from_vertical = _atan_deg(w, r)
    angle_from_horizontal = 90.0 - angle_from_vertical

    return {
        "available": True,
        "cog": {
            "x_px": round(cog_x, 1),
            "y_px": round(cog_y, 1),
            "method": "geometric_centre",
            "tag": "AI-THEORETICAL",
        },
        "hook": {
            "legs": 2,
            "attachment_points_px": [
                [round(x1, 1), round(y1, 1)],
                [round(x2, 1), round(y1, 1)],
            ],
            "hook_point_px": [round(hook_x, 1), round(hook_y, 1)],
            "sling_length_px": round(L, 1),
            "sling_length_ratio": ratio,
            "vertical_rise_px": round(r, 1),
            "angle_from_vertical_deg": round(angle_from_vertical, 1),
            "angle_from_horizontal_deg": round(angle_from_horizontal, 1),
            "tag": "AI-THEORETICAL",
        },
        "assumptions": [
            "CoG = geometric centre of detection box — assumes uniform "
            "density; bagged/netted cargo CoG is often lower. Verify by "
            "lift test.",
            "2-leg bridle with slings at the top corners of the box.",
            f"Sling length = {ratio:.1f} × load height "
            f"({L:.0f} px) — adjust to available equipment.",
            "Hook point on the vertical axis through CoG.",
            "All values are theoretical starting points for engineer "
            "review — NOT certified rigging parameters.",
        ],
    }


def _atan_deg(opposite: float, adjacent: float) -> float:
    """atan(opposite/adjacent) in degrees, handling the degenerate case."""
    import math

    if adjacent == 0:
        return 90.0
    return math.degrees(math.atan(opposite / adjacent))


def render_markdown(data: dict) -> str:
    """Render the structured data as the client's paper-form Markdown.

    AI-filled values carry an `[AI]` tag; everything else is a blank or an
    unchecked box for the engineer. The paper's ☐ checkboxes become
    `- [ ]` task lists so they render as checkboxes in a preview and stay
    editable as text.
    """
    insp_id = data["inspection_id"]
    generated = data["generated_at"].strftime("%Y-%m-%d %H:%M")
    dims = data["dimensions"]
    weight = data["weight"]
    objects = data["objects"]

    lines: list[str] = []
    a = lines.append

    a(f"# LIFTING PLAN — Submission #{insp_id}")
    a("")
    a(f"> Generated {generated} from AI detection of submission #{insp_id}.")
    a("> Fields marked [AI] are observations, not measurements.")
    a("> Not certified — requires engineer completion and sign-off.")
    a("")

    # ---- warnings ------------------------------------------------------
    for w in data["warnings"]:
        a(f"> WARNING: {w}")
    if data["warnings"]:
        a("")

    # ---- PART 2 --------------------------------------------------------
    a("## PART 2 – DETAILS OF LOAD")
    a("")
    a(f"- **Description of Load:** {data['description']} [AI]")
    a("")

    # Dimensions
    a("- **Overall Dimensions (L×W×H):**")
    if dims["source"] == "estimated":
        ref = dims["reference"]
        a(f"  - pixel box: {data['box_width_px']} × {data['box_height_px']} px [AI]")
        a(f"  - reference: {ref['m']} m = {ref['px']} px → {dims['m_per_px']} m/px")
        a(f"  - L = {dims['l_m']} m [AI-ESTIMATE]")
        a("  - W = ___ m  _(depth not visible in one photo)_")
        a(f"  - H = {dims['h_m']} m [AI-ESTIMATE]")
    else:
        a(f"  - pixel box: {data['box_width_px']} × {data['box_height_px']} px [AI]")
        a("  - L = ___ m  W = ___ m  H = ___ m  _(provide a known reference to calibrate)_")
    a("")

    # Weight
    a("- **Weight of Load:** ___ kg")
    if weight["density_kg_m3"]:
        a(f"  - density: {weight['density_kg_m3']} kg/m³ [AI]")
    if weight["kg"]:
        a(f"  - estimate: ~{weight['kg']} kg [AI-ESTIMATE] _(W assumed = smaller visible dim)_")
    a("  - [ ] Known  - [x] Estimate")
    a("")

    # ---- theoretical rigging model (Option 2) --------------------------
    rigging = data.get("rigging") or {}
    if rigging.get("available"):
        cog = rigging["cog"]
        hook = rigging["hook"]
        a("- **Centre of Gravity:**")
        a(f"  - theoretical: ({cog['x_px']}, {cog['y_px']}) px — "
          f"geometric centre of box [{cog['tag']}]")
        a("  - [ ] Obvious  - [x] Estimated  - [ ] Determined by drawing")
        a("")
        a("- **Hook Placement (theoretical 2-leg bridle):**")
        a(f"  - attachment points: {hook['attachment_points_px']} px "
          f"(top corners of box)")
        a(f"  - hook point: {hook['hook_point_px']} px")
        a(f"  - sling length: {hook['sling_length_px']} px "
          f"({hook['sling_length_ratio']:.1f} × load height)")
        a(f"  - vertical rise: {hook['vertical_rise_px']} px")
        a(f"  - sling angle from vertical: "
          f"{hook['angle_from_vertical_deg']}°")
        a(f"  - sling angle from horizontal: "
          f"{hook['angle_from_horizontal_deg']}°")
        a(f"  - [{hook['tag']}] — verify before use")
        a("")
        a("  ```")
        a("        Hook (theoretical)")
        a("           /\\")
        a("          /  \\")
        a("         /    \\  sling")
        a(f"        / {hook['angle_from_vertical_deg']}°  \\")
        a("       /________\\")
        a("      [LOAD BOX]")
        a("         CoG")
        a("  ```")
        a("")
        a("  > ASSUMPTIONS:")
        for assumption in rigging["assumptions"]:
            a(f"  > - {assumption}")
        a("")

    # Method + CoG
    a("- **Type/Method of Lifting:**")
    a("  - [ ] Single  - [ ] Tandem  - [ ] Routine  - [ ] Non-Routine (Special Lifts)")
    a("")
    a("- **Centre of Gravity:**")
    a("  - [ ] Obvious  - [x] Estimated  - [ ] Determined by drawing")
    a("")

    # ---- PART 3 --------------------------------------------------------
    a("## PART 3 – DETAILS OF LIFTING EQUIPMENT / LIFTING GEARS")
    a("")
    a("- **Type of Lifting Equipment:**")
    a("  - [ ] Mobile Crane  - [ ] Crawler Crane  - [ ] Moredc  - [ ] Others: ___")
    a("")
    a("- **Lifting Machine (LM) Number:** ___")
    a("- **Max SWL as per LM:** ___ kg")
    a("- **LM Cert Expiry:** ___")
    a("")
    a("- **Crane Configuration:**")
    a("  - Boom Length: ___ m  |  Jib Length: ___ m")
    a("  - Counterweight: ___ kg  |  Working Radius: ___ m")
    a("")

    a("### Load Calculation")
    a("")
    a("| Item | Value |")
    a("|---|---|")
    a("| (a) Lifting Capacity | ___ kg |")
    a("| (b) Cargo Weight | ___ kg |")
    a("| (c) Weight of Hook block + LG | ___ kg |")
    a("| (d) Total weight = (b) + (c) | ___ kg |")
    a("| Safety Factor (a)/(d) | ___ |")
    a("| Crane capacity used (d)/(a)×100 | ___% |")
    a("")

    a("### Lifting Gear Utilised")
    a("")
    a("| Gear | Capacity | Qty |")
    a("|---|---|---|")
    for gear in ("Webbing sling", "Wire rope", "Chain sling",
                 "Shackle / Hook", "Spreader bar"):
        a(f"| {gear} | ___ | ___ |")
    a("")

    # ---- PART 4 --------------------------------------------------------
    a("## PART 4 – LIFTING DRAWING / SKETCH")
    a("")
    if data["overlay_url"]:
        a(f"![as-observed condition]({data['overlay_url']})")
        a("")
        a("_Overlay renders inside the portal (same session). As a standalone")
        a("downloaded file it requires login. Site sketch — zone of operation,")
        a("rigging method, path of load — remains a drawing to attach._")
    else:
        a("_No overlay — nothing was detected._")
    a("")

    # ---- provenance footer ---------------------------------------------
    a("---")
    a("")
    a(f"_Detection status: {data['detection_status']}. "
       f"Objects: {len(objects)}. "
       f"Generated by the cargo detection pipeline; "
       f"see `docs/LIFTING_PLAN.md` for the design._")

    return "\n".join(lines) + "\n"
