# LIFTING_PLAN_AI_SCOPE.md — What the AI fills, what it must not

Companion to `LIFTING_PLAN.md`. This document answers one question: **which
fields in the lifting plan can the AI populate, and which must stay blank?**

**Decision (2026-10-13): the client chose Option 2** — theoretical CoG and
hook placement with every assumption stated inline. Built and tested; see
§3.7. The fields that remain blank are the ones the AI genuinely cannot
know (§4).

The governing rule: the AI fills what it *observed* and what it can
*compute from stated assumptions*. It must not invent what requires
*engineering judgment, site context, or a crane catalog*. The line between
those is the liability boundary of the whole feature.

---

## 1. Why this document exists

The client's paper form has ~25 fields. The first Markdown draft auto-filled
about 5 of them and left the rest blank. The reaction: *"most of the things
are empty — the AI should also fill dimensions, weight, method, centre of
gravity, hook angles, counterweights, working radius."*

Some of that is right. Some of it is dangerous. This document separates the
two, records the decision, and specifies exactly what was built.

---

## 2. The categories

Every field in the plan falls into one of these:

### Category A — AI observation (safe to auto-fill)

The AI saw this in the image. Filling it is reporting, not guessing.

| Field | Source | Status |
|---|---|---|
| Description of load | `object_count` × `label` × cargo type | ✅ filled |
| Object count | detection result | ✅ filled |
| Per-object boxes (px) | detection result | ✅ filled |
| Detection confidence (score) | detection result | ✅ filled |
| Fill ratio (cargo vs netting) | mask area / box area | ✅ filled |
| Border leak (load touches frame edge?) | detection result | ✅ filled |
| Pixel dimensions (W×H) | detection result | ✅ filled |

### Category B — AI inference (safe with a reference + clear tagging)

The AI cannot measure this directly, but computes a *clearly-tagged
estimate* when the engineer supplies one known value.

| Field | What's needed | Status |
|---|---|---|
| Metric dimensions (L, H) | one on-site reference length | ✅ filled when `ref_m`/`ref_px` given |
| Weight estimate | density × L×W×H | ✅ filled when dims known; W assumed = smaller visible dim |
| Density | `cargo_types` table | ✅ filled |

Always tagged `[AI-ESTIMATE]`, always carrying the assumption in the text.

### Category B2 — Theoretical rigging model (Option 2, built)

The AI cannot *measure* CoG or hook angles, but can compute a **theoretical
geometry** from stated assumptions. Every value is tagged
`[AI-THEORETICAL]` and every assumption is written into the document next to
the number it qualifies.

| Field | Model | Status |
|---|---|---|
| Centre of Gravity | geometric centre of the detection box | ✅ theoretical, assumptions stated |
| Hook placement (2-leg bridle) | attachment at top corners, sling = 2.0 × load height, hook on CoG axis | ✅ theoretical, assumptions stated |
| Sling angles (from vertical / horizontal) | `atan(half_width / vertical_rise)` | ✅ computed from the model |

The full model specification and its five assumptions are in §3.7. The
short version: these are *starting points for engineer review*, not
certified rigging parameters, and the document says so on every line.

### Category C — engineering judgment (must stay blank)

The AI cannot know these. Filling them would be **fabrication** — a
plausible-looking number with no basis in observation. On a safety
document, that is worse than a blank.

| Field | Why the AI can't know it |
|---|---|
| Type/Method (Single/Tandem) | A *site plan* decision. The camera shows a load; it can't tell you if the lift plan calls for one crane or two. |
| Routine / Non-Routine | A *classification* decision based on company procedure and risk assessment. |
| Counterweights | A property of the specific crane model. The AI has no crane catalog. |
| Working radius | A *site decision* — where the crane stands relative to the load. Not in the image. |
| Boom / jib length | Crane model + site decision. |
| Lifting capacity (a) | Requires the crane's load chart at a specific boom/radius. |
| Gear selection | Depends on available inventory + rigging method + the (estimated) weight. |
| Safety factor, capacity % | Computed from (a) and (d) — both blank until the engineer acts. |

**The rule:** A is reported. B is estimated and tagged. B2 is computed
from stated assumptions and tagged. C is the engineer's domain.

---

## 3. What the AI adds to the document

### 3.1 Per-object detail

Every detected object with its own box and confidence, not just the winner:

```markdown
| # | Class | Confidence | Box (px) | Mask area |
|---|---|---|---|---|
| 1 | Cargo-Box | 0.83 | [52, 287, 196, 459] | 17,051 px |
| 2 | Cargo-Box | 0.44 | [260, 215, 444, 439] | 29,188 px |
```

### 3.2 Detection confidence

The selection score, so the engineer knows how much to trust the box:

```markdown
- Detection confidence: 16.3 (acceptance threshold 6.0) [AI]
```

### 3.3 Fill ratio

How much of the bounding box is actual cargo vs netting — you rig the cargo,
not the net:

```markdown
- Fill ratio: 6.8% of frame is segmented cargo [AI]
```

### 3.4 Border leak

Whether the load touches the frame edge — relevant for clearance and for
trusting the box:

```markdown
- Border leak: 0.0% (load is clear of all frame edges) [AI]
```

### 3.5 AI notes — hints, not determinations

```markdown
> AI OBSERVATIONS — hints for the engineer, not determinations
> - Load appears compact and symmetric; single-point lift may suffice. Confirm with rigger.
> - CoG likely near geometric center; for bagged cargo, possibly lower. Verify by lift test.
> - No cargo detected above the load band — rigging points appear clear of the net.
```

### 3.6 Suggested starting point

A clearly-labeled *hypothesis* for the engineer to react to:

```markdown
> SUGGESTED STARTING POINT — not certified, verify before use
> - Estimated weight: ~5,770 kg → consider 2-leg chain sling, 10t capacity per leg
> - Load appears compact → single-point lift may suffice
> - CoG: assume geometric center until verified by lift test
```

### 3.7 Theoretical rigging model (Option 2 — the built feature)

This is the section the client specifically asked for: **CoG and hook
placement.** It is a computed geometry, not a measurement.

**Model.** A 2-leg bridle:

```text
CoG        = geometric centre of the detection box
attachments = top-left and top-right corners of the box
sling      = 2.0 × load height (adjustable to available equipment)
hook       = on the vertical axis through CoG, above the attachments
```

**Geometry** (sag plane, in pixels):

```text
w  = half box width                  (horizontal offset CoG → corner)
h  = load height
L  = sling length = 2.0 × h
r  = vertical rise = √(L² − w²)
θ  = angle from vertical = atan(w / r)
```

**Worked example** — box `[52, 287, 196, 459]` (144 × 172 px):

```text
CoG              = (124.0, 373.0) px
attachments      = (52, 287) and (196, 287) px
sling length     = 344.0 px   (2.0 × 172)
vertical rise    = 336.4 px
hook point       = (124.0, −49.4) px
angle from vert. = 12.1°
angle from horiz.= 77.9°
```

**The five assumptions** (rendered into the document under every
theoretical value):

1. CoG = geometric centre of detection box — assumes uniform density;
   bagged/netted cargo CoG is often lower. Verify by lift test.
2. 2-leg bridle with slings at the top corners of the box.
3. Sling length = 2.0 × load height — adjust to available equipment.
4. Hook point on the vertical axis through CoG.
5. All values are theoretical starting points for engineer review —
   NOT certified rigging parameters.

**What the engineer does with it:** react to the geometry, set the sling
length to equipment actually available, recompute the angle. The model
turns "fill in the blank" into "confirm or correct the hypothesis."

---

## 4. What the AI will never fill, and why

### Counterweights, working radius, boom length

Properties of the **specific crane** and the **specific site**. The AI has
no crane catalog and cannot see the crane position. Lookup + site
measurement, not inference. Blank until the engineer selects the crane and
measures the radius.

### Type/Method, Routine/Non-Routine

Lift-execution and classification decisions. The camera shows a load; it
cannot see the lift plan or the company's risk procedure. Blank.

### Gear selection, lifting capacity, safety factor

All downstream of the crane choice and the (still-blank) radius. The
document provides the formula structure and the blanks; the engineer
provides the inputs.

### Why not "just estimate" these too?

A theoretical CoG is safe because its assumptions are *visible and
checkable* — the engineer can see "geometric centre, assumes uniform
density" and correct it in one line. A theoretical counterweight is not:
it would look like a crane specification, and no engineer can verify it
from the document alone. The line is drawn where assumptions end and
invention begins.

---

## 5. Decision record

| Date | Decision |
|---|---|
| 2026-10-13 | Client reviewed Options 1–3, chose **Option 2**: theoretical CoG + hook placement with stated assumptions. |
| 2026-10-13 | Built: `_theoretical_rigging()` in `app/services/services/lifting_plan.py`, rendered in the Markdown with an ASCII rigging diagram and the assumptions block. 24 lifting-plan tests, full suite 248 passed. |

Options as originally presented, for the record:

- **Option 1** — observation-rich, judgment-blank. (Superseded by 2.)
- **Option 2** — add theoretical CoG + hook angle with stated assumptions.
  **(Chosen.)**
- **Option 3** — full auto-fill from a crane catalog and defaults.
  Not recommended: a document that looks complete but is mostly
  assumption is worse than one honestly blank.

---

## 6. Remaining open questions for the client

1. Confirm the sling-length ratio (currently 2.0 × load height).
2. Link or embed the overlay image? (Current default: link.)
3. Replicate the paper form layout exactly, or the cleaner generated
   structure now in place?
4. Do the AI notes (§3.5) match the level of detail the engineers want,
   or should they be pared back?
