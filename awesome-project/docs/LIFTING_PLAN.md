# LIFTING_PLAN.md â€” Lifting Plan as a single Markdown file (draft v2)

One endpoint. Zero new tables. The UI calls it, gets a `.md` document back,
renders a preview, offers download. The engineer completes it on paper or in
any markdown editor. No CRUD, no review workflow, no PDF pipeline.

A lifting plan is a **safety document**. The Markdown fills in what the AI
observed, leaves blanks for what only an engineer knows, and marks every
AI value as estimate. Reference: the client's paper form (Part 2: load,
Part 3: equipment/gears + load calculation, Part 4: sketch).

---

## 1. The endpoint

```text
GET /api/v1/portal/submissions/{id}/lifting-plan?ref_m=&ref_px=&format=
```

| Param | Meaning |
|---|---|
| (none) | full Markdown, pixel boxes + blanks |
| `ref_m=2.43&ref_px=410` | one known on-site reference â†’ metric dimensions + weight estimate computed live |
| `format=json` | same content as structured data, for the UI to render (not a second endpoint â€” one route, content negotiation) |

- Response: `text/markdown; charset=utf-8`, downloadable as
  `lifting-plan-{id}.md`.
- 404 someone else's submission (same ownership rule as everything else).
- 422 when `detection_status` is `not_run` ("run detection first"),
  `no_cargo` ("nothing to lift"), or `error`.
- No persistence: regenerate any time; re-detection is picked up for free.

## 2. What fills vs what stays blank

| Markdown section | Auto-filled from detection | Blank for the engineer |
|---|---|---|
| Description | `"2 Ã— Cargo-Box (scrap steel)"` (count + label + cargo type) | â€” |
| Dimensions | pixel box WxH; metric L/H if `ref_*` given (tagged estimate) | W (depth never visible), reference itself |
| Weight (b) | density from `cargo_types` + computed estimate if dims known | known figure (weighbridge/CSC plate) |
| Known / Estimate | Estimate pre-ticked when AI-derived | Known ticked by human assertion |
| Method, CoG | CoG defaults Estimated | Single/Tandem, Routine/Non-Routine, CoG override |
| Crane, boom, radius, gears | â€” | all manual (site reality) |
| (a)(b)(c)(d), SF, used-% | formulas + whatever computes | the rest, computed live in the doc where inputs exist |
| Part 4 evidence | overlay image link (see Â§5) | site sketch (still a drawing) |

The paper form's â˜ checkboxes become Markdown `- [ ]` task lists â€” they
render as checkboxes in the UI preview and stay editable as text.

## 3. Dimensions without the measurement stage

Cells 12â€“28 are not run (`DETECTION.md` Â§8), so no metric volume exists.
The box gives exact **proportions**; one site-known reference calibrates:

```text
m_per_px = ref_m / ref_px
L = box_w_px Ã— m_per_px,  H = box_h_px Ã— m_per_px,  W left blank
```

No `ref_*` params â†’ the doc shows pixel values + blank metre fields. W is
never visible in one photo: always blank, never invented.

## 4. Weight without a scale

```text
cargo_weight â‰ˆ density(cargo_type) Ã— (L Ã— W Ã— H box approx)
```

Shown only when dims are known; always tagged estimate; `cargo_type = other`
(null density) forces manual entry â€” the doc says so in place. The engineer
overwrites with a weighed figure and ticks Known.

## 5. The overlay link (and its honest limit)

```markdown
![as-observed condition](../submissions/28/detection/overlay)
```

Relative link â€” renders inside the UI preview (same session, cookie sent).
As a standalone downloaded file it renders only while logged in elsewhere;
the doc footnotes this. (Alternative: base64-embed the ~350 KB PNG for a
fully self-contained file â€” one param away if the client wants it, but it
turns the working document into an uneditable blob. Link by default.)

## 6. Inline warnings instead of gates

No persistence means no finalize to block â€” so the checks render as
warnings inside the document wherever they compute:

```markdown
> WARNING: estimated weight with capacity used above 75% â€” confirm by weighing.
> WARNING: safety factor below 1.5 â€” review crane selection.
```

Thresholds stay settings for the client to confirm (defaults 75 % / 90 % /
SF 1.5, per the v1 draft).

## 7. UI: one button

Per submission, next to Detect: **"Lifting plan (.md)"** â†’ fetches the
endpoint â†’ preview pane (rendered markdown) + Download button. Optional
reference inputs (two small fields: "known length (m)" + "its pixel span")
append `ref_m`/`ref_px`. ~30 lines of JS. No form state, no admin queue.

## 8. What the AI explicitly does NOT do

Unchanged from v1: no crane/radius/gear choice, no CoG determination, no
lift-method context, no certification. The doc header states it on every
generation:

```markdown
> Generated {date} from AI detection of submission {id}.
> Fields marked AI-ESTIMATE are observations, not measurements.
> Not certified â€” requires engineer completion and sign-off.
```

## 9. Effort

One route + one template function + UI button + ~8 tests. No migration, no
models, no new tables. If the client later wants persistence/review/PDF,
that is a separate follow-up design - the template functions here become
its report generators.

## 10. Open questions for the client (shortened)

1. Confirm warning thresholds (75 % / 90 %, SF floor).
2. Link or embed the overlay? (default: link)
3. Replicate their paper layout exactly, or clean generated structure?

---

