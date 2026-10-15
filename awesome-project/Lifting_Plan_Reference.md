# Lifting Plan Reference — HSE-F003 Analysis & System Mapping

> **Sources analysed:**
> 1. *Lifting of 40FT Container & Other Cargo by using M3 Crane (MSW).pdf* (5 pages)
> 2. *Lifting Plan rev.0 Lifting of Boom lift 12 Ton M1 & M2 Crane (MSW).pdf* (7 pages)
>
> Screenshots of page 1 of each are in `images/`. This document explains the
> form section by section, extracts the real values and calculations, and maps
> every field to what this platform fills, estimates, or must leave blank. It
> is the companion to [`Complete.md`](Complete.md) §16.

---

## 1. What these documents are

Both are filled instances of **HSE-F003 "Lifting Plan"**:

- Issued by **Swift Total Logistics Pte Ltd**, Revision 0, effective 1 September 2024.
- Prepared for the project *"2-Year Term Contract to Provide and Perform Lifting Operations at Pt & MSW"*.
- Work location: **Marina South Wharves**. Both plans are dated **21 October 2025**.

A lifting plan is the safety document that must be prepared, assessed and
approved **before** a crane lift. It records what is being lifted, how heavy it
is, which crane and gear are used, whether the crane has enough capacity
(safety factor), the site conditions, and who signs off.

| | Plan A — Container | Plan B — Boom lift |
|---|---|---|
| Load | 40 ft container & other cargo | Boom lift & other cargo |
| Crane | **M3** crane, LM **889808P** | **M1 & M2** mobile cranes, LM **596596N & 596596V** |
| Pages | 5 | 7 |
| Rigging gallery pages | 2 | 4 |
| Load chart page | p.4 | p.6 |

---

## 2. Form structure (section by section)

| Part | Title on form | Fields |
|---|---|---|
| Header | HSE-F003 LIFTING PLAN | Company logo, revision, effective date, page x of y |
| **Part 1** | General Information | Contractor name, Permit No., Date & time, Location of work, Project |
| **Part 2** | Details of Load | Description; Overall dimensions (L × W × H); Weight + ☐ Known / ☐ Estimate; Method ☐ Single ☐ Tandem ☐ Routine ☐ Non-Routine (special lifts); Centre of gravity ☐ Obvious ☐ Estimated ☐ Determined by drawing |
| **Part 3** | Details of Lifting Equipment / Lifting Gears | Equipment type ☐ Mobile ☐ Crawler ☐ Mordec ☐ Others; LM number; Max SWL per LM cert; LM expiry; **Crane configuration**: boom length, jib length, counterweight, boom length (as rigged), working radius; **Lifting gear utilised**: webbing sling, wire rope, chain sling, shackle/hook, spreader bar (capacity + qty each); **Load calculation**: (a) to (d), SF, % used |
| **Part 4** | Lifting Drawing / Sketch (where engineering drawing not available) | Crane side-view (boom length, load radius) + rigging sketch with labelled gear and weights |
| Gallery | *(unnumbered pages)* | Rigging illustrations for other cargo the crane may handle |
| Chart | "MSW-Mx Crane (LM …) Lifting Calculation" | Manufacturer rated-capacity table with the selected cell highlighted |
| **Part 5** | Means of Communications | Operator visibility ☐ Clear ☐ Blind; ☐ Hand signal ☐ Radio ☐ Other |
| **Part 5** *(sic)* | Personnel Involved in Lifting Operation | Name / Designation / Signature (pre-filled "STL Lifting Team" × 5) |
| **Part 7** | Physical & Environmental Considerations | Yes/No/NA + remark for ground, outriggers, underground services, overhead obstacles, nearby structures, lighting, demarcation; "do not proceed" checklist: thunderstorm, strong wind, sea state, other |
| **Part 8** | Signatures | **Prepared by** (lifting supervisor/engineer) · **Assessed by** (safety assessor/WSHC/WSHO) · **Approved by** (authorised person/project manager) |

> **Form numbering quirk:** "Part 5" is used twice, and there is no Part 6.

---

## 3. Extracted values

### 3.1 Part 2 — Load

| Field | Plan A (Container) | Plan B (Boom lift) |
|---|---|---|
| Description | Lifting of 40FT Container & Other Cargo by using **M3 Crane** | Lifting of Boom lift & Other cargo by using M01, M02, **Mobile Crane** |
| Dimensions | L 12.19 m × W 2.43 m × H 2.59 m | L 11.9 m × W 2.49 m × H 3.85 m |
| Weight | 6,000 kg | 12,000 kg |
| Known / Estimate | ☐ / ☐ (neither ticked) | ☐ / ☐ (neither ticked) |
| Method / CoG ticks | none ticked | none ticked |

### 3.2 Part 3 — Equipment and crane configuration

| Field | Plan A | Plan B |
|---|---|---|
| Equipment type | none ticked | none ticked |
| LM number | 889808P | 596596N & 596596V |
| Max SWL (LM cert) | 30,000 kg | 43,700 kg |
| LM expiry | "Refer to the attachment" | "Refer to the attachment" |
| Boom length (max) | 30.5 m | 43 m |
| Jib length | N/A | N/A |
| Counterweight | 13,990 kg | 25.95 t |
| Boom length (as rigged) | 23.45 m | 27.0 m |
| Working radius | 8 m | 7.5 m |

### 3.3 Part 3 — Lifting gear

| Gear | Plan A | Plan B |
|---|---|---|
| Webbing sling | — | **10 t × 4** |
| Wire rope | — | — |
| Chain sling | **17 t × 1** (4-legged, 8 mm × 12 ft) | — |
| Shackle / hook | — | **8.5 t × 4** |
| Spreader bar | — | — |

### 3.4 Part 3 — Load calculation

| Line | Plan A | Plan B |
|---|---|---|
| (a) Lifting capacity (from chart) | 9,650 kg | 18,000 kg |
| (b) Cargo weight | 6,000 kg | 12,000 kg |
| (c) Hook block + lifting gear | 500 kg | 500 kg |
| (d) Total = (b) + (c) | 6,500 kg | 12,500 kg |
| **Safety factor = (a) ÷ (d)** | **1.48** | **1.44** |
| **Crane capacity used = (d) ÷ (a) × 100** | **67.3 %** | **69.4 %** |

**Arithmetic check:**

| | Safety factor | Capacity used |
|---|---|---|
| Plan A | 9650 ÷ 6500 = 1.4846 → 1.48 ✓ | 6500 ÷ 9650 = 67.36 % → written 67.3 % (truncated, not rounded) |
| Plan B | 18000 ÷ 12500 = 1.44 ✓ | 12500 ÷ 18000 = 69.44 % → 69.4 % ✓ |

### 3.5 Load charts — where (a) comes from

| | Plan A — M3 (LM 889808P) | Plan B — M1/M2 (LM 596595N & 596596V) |
|---|---|---|
| Chart | "Rated Lifting Capacity, 9.35 m – 30.5 m boom", ISO 4305, metric tons | "Lifting Capacities, 11.0 m – 43.0 m boom", ISO 4305, "not exceed 75% of static tipping loads" |
| Outrigger mode | Fully extended (6.6 m), 360° | Fully extended with front jack, 360° |
| Lookup | 23.45 m boom × **8.0 m radius → 9.65 t** (highlighted) | 27.0 m boom × **7.5 m radius → 18.00 t** (highlighted) |
| Standard hook (chart) | 30 t hook, 250 kg | 20 t hook, 320 kg (27 m boom column) |
| Hook + gear used on form | 500 kg (main block 0.5 t per sketch) | 500 kg |

The procedure an engineer follows is therefore:

1. Read the **boom length** and **working radius** from the crane configuration.
2. Look up the rated capacity **(a)** in the manufacturer chart for that
   outrigger setting.
3. Add the **hook block and gear** weight **(c)** to the **cargo** weight
   **(b)** to get **(d)**.
4. Compute **SF = a / d** and **utilisation = d / a**.

### 3.6 Part 4 — Sketch annotations

| Plan A | Plan B |
|---|---|
| Boom length 23.45 m; **load radius 9 m**; main block with safety ledge 0.5 t; 17 t 8 mm × 12 ft 4-legged chain sling; container 20 ft/40 ft, 3–6 t | Boom length 27 m; load radius 7.5 m; main block 0.5 t; webbing sling 10 t × 4 supplied from boat; shackles × 4, 8.5 t, supplied from boat; 2 points on each side; boom lift 12 t |

---

## 4. Observations and discrepancies in the source plans

These are factual differences found while reading. They are worth raising
with the client because they show where an automated cross-check would help.

| # | Plan | Observation |
|---|---|---|
| 1 | A | Part 3 says **working radius 8 m**, but the Part 4 sketch says **load radius 9 m**. On the chart, 23.45 m boom at 9.0 m gives **8.65 t**. That would mean SF = 8650 / 6500 = **1.33** and utilisation = **75.2 %**, not 1.48 / 67.3 % |
| 2 | A | Capacity used is written as 67.3 %; the exact value 67.36 % rounds to 67.4 % |
| 3 | A | Cargo weight 6,000 kg is the upper bound of the "3–6 ton" container range in the sketch. Neither "Known" nor "Estimate" is ticked |
| 4 | B | The form says LM **596596N** & 596596V; the chart title says LM **596595N** & 596596V and "M1&M1" |
| 5 | A, B | "Boom length" appears twice: max boom and as-rigged boom. The second is the one used for the chart lookup |
| 6 | A, B | No checkboxes are ticked anywhere (weight basis, method, CoG, equipment type) |
| 7 | A, B | Hook block + gear is taken as 500 kg, more conservative than the chart's standard hook mass (250 / 320 kg) |
| 8 | A, B | Both safety factors (1.48, 1.44) are below **1.5**, the value of the codebase's unused constant `WARN_SAFETY_FACTOR`. Utilisation (67–69 %) is below the 75 % warning threshold, and Plan B's chart note limits the rated capacities themselves to 75 % of the static tipping load |
| 9 | A, B | Part 5 appears twice; Part 6 does not exist |

---

## 5. Rigging gallery — cargo catalogue from the plans

The extra pages illustrate other cargo routinely lifted at MSW and the gear
used for each. Together they form a ready-made **cargo catalogue** with
typical weight ranges.

| Cargo | Typical weight | Gear shown | In plan |
|---|---|---|---|
| Container 20 ft / 40 ft | 3 – 6 t | 17 t 4-legged chain sling, main block 0.5 t | A, B |
| Boom lift | 12 t | 10 t webbing × 4, 8.5 t shackles × 4 | B |
| Wire drum | 2 – 6 t | 2 t 6 m webbing (choker hitch, 3- or 4-point) + 4 t 2-legged chain | A, B |
| Cargo net (supply from boat) | 1.5 – 2 t | 4 t chain sling with safety latch | A, B |
| Cylinder cage | 350 kg – 1 t | 2 t webbing (basket) + 4 t chain; anchoring/eye points with SWL tags | A, B |
| Metal storage bin, scrap metal | 1.2 t | 4 t chain + 2 t 6 m webbing (basket) | A, B |
| Rescue boat (25-person) | 4 – 5 t | 10 t 2-legged chain sling to anchoring/eye points | A, B |
| Palletised cargo | 1.5 – 2 t | 4 t chain sling (+ net) | A, B |
| Pallet / provision cargo | 0.5 – 1.5 t | 4 t chain + 2 t webbing | A, B |
| Pipes / bundle of pipes | 0.5 – 2 t | 4 t chain + 2 t 6 m webbing | A, B |
| Generator set | 2.5 – 6 t | 7 t 2-legged chain to eye point | A, B |
| Empty IBC | 0.5 – 1 t | 4 t chain + 2 t webbing | B |
| Loaded bin | 1,000 kg | 4 t chain + hooks + 2 t webbing | B |
| Grab | 6 – 8 t | Main block 0.5 t + master ring | B |
| Lube oil drums | 200 kg each | 2 t drum hooks on a 4-leg chain | B |
| "Linear" (3.5 t) | 3.5 t | 4 t chain + hooks + 2 t webbing | B |
| Fender | 0.5 – 3.5 t | 4 t chain + 2 t webbing + tag line | B |

---

## 6. How the plans map to this platform

The platform's lifting plan endpoint
(`GET /api/v1/portal/submissions/{id}/lifting-plan`) produces a **draft** in the
HSE-F003 layout. The table below maps each form field to its category:

- **A:** observed in the photo
- **B:** estimated from a stated assumption
- **B2:** theoretical geometry
- **C:** engineering judgement, always left blank

The last column says what the system does today.

| Form field | Category | System today |
|---|---|---|
| **Part 1** contractor, permit, date, location, project | Admin data | ❌ Not rendered (could come from user/site profile) |
| Description of load | A | ✅ `"{count} × {label} ({cargo type})"` `[AI]` |
| Overall dimensions L | B | ✅ If `ref_m`/`ref_px` given: `box_w_px × ref_m/ref_px` `[AI-ESTIMATE]` |
| Overall dimensions H | B | ✅ Same, from box height `[AI-ESTIMATE]` |
| Overall dimensions W | C (not visible) | ⚪ Always blank (single photo has no depth) |
| Weight of load | B | ✅ `density × L × min(L,H) × H` `[AI-ESTIMATE]` only if the cargo type has a density. ⚠️ See below |
| Known / Estimate weight | — | ⚪ Blank; any AI weight is by definition an *estimate* |
| Method: single / tandem / routine / non-routine | C | ⚪ Blank |
| Centre of gravity | B2 | ✅ Box centre, assumes uniform mass `[AI-THEORETICAL]`; the "Estimated" box is the honest tick |
| Equipment type, LM no., SWL, expiry | C | ⚪ Blank |
| Boom, jib, counterweight, radius | C | ⚪ Blank |
| Lifting gear (type, capacity, qty) | C | ⚪ Blank table |
| Load calc (a) capacity | C (from chart) | ⚪ Blank |
| (b) cargo weight | B | Estimate shown in Part 2; (b) itself left blank |
| (c) hook + gear | C | ⚪ Blank |
| (d), SF, % used | Derived | ⚪ Blank (could be auto-computed once a, b, c are entered; see §7) |
| **Part 4** sketch | A + B2 | ✅ Link to detection overlay + ASCII 2-leg bridle sketch (hook point, sling angle, in pixels) |
| Part 5 communication / personnel | C | ❌ Not rendered |
| Part 7 site & environment | C | ❌ Not rendered |
| Part 8 signatures | C | ❌ Not rendered (system never signs) |

### Key gaps revealed by the real plans

1. **Cargo catalogue mismatch.** The system seeds bulk materials:
   scrap-steel, thermal-coal, construction-gravel, agricultural-grain and
   other. Real MSW lifts are mostly **manufactured units**: containers, boom
   lifts, gen sets, drums, IBCs, nets, rescue boats. For these, weight comes
   from the **manifest, nameplate or typical range**, not volume × density.
   A container's bounding-box volume × density would be meaningless. The
   catalogue needs a `typical_weight_min_kg` / `typical_weight_max_kg` (and a
   "weight basis") alongside density.
2. **Detector taxonomy vs cargo.**
   - The YOLO classes (`Cargo-Box`, `Wooden-Plate`, plus the exclusions
     `Net`, `Strap`, `Chain`, `Hook`, `Crane`) match the *rigging* seen in
     the gallery well. That is useful for separating gear from load.
   - They do not distinguish container from gen set from boom lift.
   - The proposal's "material/type identification" step (a CNN classifier)
     is not yet implemented.
3. **Reference scale.** A 40 ft container is a perfect built-in ruler
   (12.19 × 2.44 × 2.59 m, ISO standard). If the detector recognised
   containers, `ref_m` could be filled automatically.
4. **Parts 1, 5, 7, 8 missing.** The draft is not a complete form yet.
   Rendering these as blank sections would let the engineer complete one
   document.

---

## 7. Load-calculation rules for the system

The form's arithmetic is deterministic and can be checked by software without
making any safety decision. The proposed helper validates and computes; it
never fills (a) or (c) on its own.

```text
Inputs (engineer-entered):  a = rated capacity from chart (kg)
                            b = cargo weight (kg)  [known or estimate, must be ticked]
                            c = hook block + lifting gear (kg)
Derived:                    d  = b + c
                            SF = a / d          (2 dp)
                            U% = d / a × 100    (1 dp, rounded)
Warnings (constants already in app/services/lifting_plan.py, currently unused):
   SF  < 1.5                       → WARN_SAFETY_FACTOR
   U%  > 75 and b is an ESTIMATE   → WARN_ESTIMATE_USED_PCT
   U%  > 90                        → WARN_ABSOLUTE_USED_PCT
Cross-checks:
   working radius in Part 3 == load radius in Part 4 sketch
   LM number in Part 3 == LM number on the load chart
   b within the cargo type's typical weight range
   exactly one of Known / Estimate ticked
```

Applied to the two reference plans:

| Check | Plan A | Plan B |
|---|---|---|
| d = b + c | 6,500 ✓ | 12,500 ✓ |
| SF | 1.48 → ⚠️ < 1.5 | 1.44 → ⚠️ < 1.5 |
| U% | 67.4 % (form: 67.3 %) | 69.4 % ✓ |
| Radius consistency | ❌ 8 m vs 9 m | ✓ 7.5 m |
| LM consistency | ✓ | ❌ 596596N vs 596595N |
| Weight basis ticked | ❌ | ❌ |

> Whether SF 1.44–1.48 is acceptable is a site/engineering policy decision.
> Plan B's chart is already limited to 75 % of the static tipping load. The
> warning only flags the value for the engineer; it does not reject the plan.

---

## 8. End-to-end: from photo to signed HSE-F003

```mermaid
flowchart LR
    P[Photo of suspended load] --> D[Detection: YOLO-OBB + SAM<br/>load separated from net/sling/hook]
    D --> R[Reference size ref_m/ref_px<br/>e.g. container length 12.19 m]
    R --> L[Draft lifting plan<br/>Part 2 estimates + Part 4 overlay & CoG sketch]
    L --> E[Lifting engineer<br/>Part 1, crane config, gear, chart lookup a, c]
    E --> C[Load calc: d, SF, %used + warnings]
    C --> S[Part 5/7 site checks]
    S --> G[Part 8: Prepared → Assessed → Approved]
```

| Who | Does what |
|---|---|
| System | Observes, estimates with labels, sketches theory, checks the arithmetic |
| Engineer | Chooses crane, gear and method; reads the chart; ticks the boxes |
| Safety assessor and authorised person | Assess and approve; sign |

---

*End of Lifting_Plan_Reference.md — companion to Complete.md*
