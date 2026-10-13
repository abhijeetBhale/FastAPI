# Working.md — AI-Driven Cargo Detection & Segmentation System

> Cell-by-cell logic, end-to-end working explanation, and the full technology / library
> stack used to make sure the pipeline runs. Based on `Revamping.ipynb` (31 notebook
> cells, internally labelled **CELL 1 – CELL 28**), the helper scripts, and the
> `.venv` environment of this repository.

---

## 1. What The Project Does (One-Line Overview)

An **input-independent computer-vision inspection pipeline** that detects a suspended
cargo load in port/crane images, segments **only the solid cargo body** (excluding the
net, straps, chain, hook and crane), then measures it: 2D size → depth → 3D point
cloud → volume → density lookup → **estimated weight**, saved as a JSON inspection
report.

### End-to-end flow

```
Select images
   │
   ▼
Quality check / preprocessing ─────────────── Cells 1–5 (nb idx 0–4)
   │
   ▼
Load models: SAM ViT-B + cargo YOLO ───────── Cell 7   (nb idx 6)
   │
   ▼
YOLO detection (zip taxonomy / COCO / saliency fallback) ── Cell 8b (nb idx 8)
   │  payload boxes │ envelope boxes │ exclusion boxes
   ▼
Build SAM prompts (box + pos/neg points) ───── Cell 8c  (nb idx 9)
   │
   ▼
SAM multimask predict → rank → clean mask ─── Cell 9   (nb idx 10)
   │  exclusion subtraction, band guard, largest CC, morph close, tight AABB/OBB
   ▼
Score candidates → overlay viz → dashboard ── Cell 10  (nb idx 12)
   │
   ▼
Geometry (px) → auto pixel-to-meter calibration ── Cells 12–15 (nb idx 14–17)
   │
   ▼
Depth Anything depth map → cargo-only depth ── Cells 17–19 (nb idx 19–21)
   │
   ▼
Open3D point cloud → volume ───────────────── Cells 20–22 (nb idx 22–24)
   │
   ▼
Cargo type → density → weight → JSON report ─ Cells 23–28 (nb idx 25–30)
```

---

## 2. Technology & Library Stack (verified against `.venv`)

| Layer | Technology | Version in `.venv` | Role in this project |
|---|---|---|---|
| Language | Python | 3.x (venv) | All notebook + script logic |
| Notebook | Jupyter / ipykernel | 7.3.0 | Runs `Revamping.ipynb` cell-by-cell |
| Deep Learning | **PyTorch** | 2.14.0 | Backend for SAM, YOLO, Depth Anything |
| DL acceleration | torchvision | 0.29.0 | Torch vision utilities |
| Object Detection | **Ultralytics (YOLO)** | 8.4.161 | YOLOv8-OBB / YOLO11x detection & training |
| Segmentation | **segment-anything (SAM)** | 1.0 (Facebook AI) | `SamPredictor`, `SamAutomaticMaskGenerator`, ViT-B checkpoint |
| Depth Estimation | **transformers (Hugging Face)** | 5.17.0 | `pipeline("depth-estimation")` with `LiheYoung/depth-anything-small-hf` |
| 3D | **Open3D** | 0.20.0 | Point cloud creation, axis-aligned bbox → volume |
| Image ops | **opencv-python** | 5.0.0.93 | Color conversion, Canny, contours, morphology, overlays |
| Arrays | NumPy | 2.5.3 | Mask arithmetic, geometry math |
| Plotting | Matplotlib | 3.11.2 | In-notebook image / mask / depth visualization |
| Interactive 3D | Plotly | 7.1.0 | Rotatable 3D point-cloud viewer in VS Code |
| Telemetry | **ipywidgets** (via `tqdm.auto` + IPython events) | 8.1.9 | Live whole-run progress bar; auto per-cell timing hooks |
| IO / utils | Pillow 12.3.0, tqdm 4.70.1, requests 2.34.2, scipy 1.18.1, scikit-image 0.26.0, shapely 2.1.2 | — | Image loading, progress bars, checkpoint download, science helpers |
| GUI picker | tkinter (stdlib) | — | File dialog for selecting 1–3 cargo images |
| Dataset prep | `cargo_dataset_from_zip.py` (stdlib zipfile/random/shutil) | — | Repairs the Roboflow zip into a trainable split |
| Training | `train_cargo_obb.py`, `train_yolo_optimized.py` | — | Fine-tune OBB / YOLO11x cargo detectors |
| Model weights (repo) | `yolov8n-obb.pt`, `yolo11x.pt`, `yolo11m.pt`, `yolov8m.pt`, `yolov8s.pt`, `yolov8n.pt`, `yolo11n-seg.pt` | — | Pretrained / fine-tuned checkpoints |
| Configs | `cargo_obb_data.yaml` (8 zip classes), `cargo_auto_data.yaml` (3 self-train classes) | — | Dataset taxonomies |

**Key model artifacts**

- `models/sam_vit_b_01ec64.pth` — SAM ViT-B checkpoint (auto-downloaded from
  `dl.fbaipublicfiles.com` if missing).
- `models/cargo_obb_best.pt` — cargo-specific OBB detector produced by
  `train_cargo_obb.py --promote`. **Optional**: without it the pipeline degrades
  gracefully to `yolo11x.pt` (COCO) + saliency fallback.

**Dataset**: Roboflow `Cargo-Detection.v3i.yolov8-obb.zip`, 8 classes:
`Cargo-Box`(0), `Cargo-Detection`(1), `Chain`(2), `Crane`(3), `Hook`(4), `Net`(5),
`Strap`(6), `Wooden-Plate`(7) — grouped into three roles:

- **TARGETS** (segment these): `Cargo-Box`, `Wooden-Plate`
- **ENVELOPE** (fallback prompt): `Cargo-Detection` (whole net + load)
- **EXCLUSIONS** (suppress): `Net`, `Strap`, `Chain`, `Crane`, `Hook`

---

## 3. Cell-by-Cell Working Logic

`Revamping.ipynb` contains **31 code cells (index 0–30)**. Each header below shows the
**notebook index** and the **internal CELL label** used inside the cell comment.

### 3.1 Telemetry — Per-Cell Times, Per-Step Logs & Live Progress Bars

The notebook is instrumented end-to-end by a single block in **Cell 2** (notebook
index 1). It is purely observational: no detection, segmentation, geometry or
weighting logic is touched, and every helper is a safe no-op outside IPython, so
the headless harness (`_build/_e2e_test.py`) keeps working unchanged.

**Switches** (read once, from the environment; all default **ON**)

| Env var | Effect |
|---|---|
| `CARGO_DEBUG=0` | silence the per-step log lines — timings are still recorded |
| `CARGO_PROGRESS=0` | hide the live progress bars (console text disappears too) |
| `CARGO_LIVE_SAVE=0` | save `outputs/timings.*` only at Cell 10 / 28, not after every cell |

**Helpers**

| Helper | Purpose |
|---|---|
| `cargo_note(msg)` | one timestamped `[HH:MM:SS]` debug line |
| `cargo_step(msg)` / `cargo_done(msg, t0, **fields)` | open/close a step manually |
| `with cargo_timer("name", **fields) as t:` | timed block; `t.note = {...}` adds fields |
| `for x in cargo_stage("name", total=n, unit="image"):` | **live progress bar** for a known-length loop; `.set_note()` updates the label |
| `cargo_timing_report(partial=False)` | prints the per-cell and per-step timing tables |
| `cargo_save_timings(label=..., announce=...)` | **persists** the run's timings to `outputs/` (below); already called for you after every cell |
| `cargo_compare_timings()` | per-cell delta table vs the previous run of the same kind |

**Durable timing artefacts (`outputs/`).** The on-screen tables die with the
kernel, so `cargo_save_timings()` also persists them next to the other run
artifacts:

| File | Content |
|---|---|
| `outputs/timings.json` | full structured record of the latest run — per-cell rows (with the parsed cell number and phase), every logged step with its fields, run totals, the `hooks_active` flag, Cell 9's own `roi_timings_by_image`, and a `schema_version` |
| `outputs/timing_report.md` | human-readable Markdown — per-cell table, per-phase roll-up (Setup / Detect+Segment / Measurement), 20 slowest steps, per-object ROI timings |
| `outputs/timing_history.csv` | one row per cell per run (`run_id, run_label, generated_utc, cell_index, cell, phase, seconds, status`) — the file to open in Excel to compare runs |

**Written after every cell (live).** The CELL 2 `post_run_cell` hook calls
`cargo_save_timings()` as soon as each cell finishes, so the three files above
are always current. Nothing has to reach Cell 10 or Cell 28 first, and a run that
is interrupted — or stopped at Cell 10 — still leaves a usable profile. The
hook saves silently; the on-screen `[HH:MM:SS] [ok] CELL nn` line is the signal.

Within one run the history CSV is **re-written, not duplicated**: rows are keyed
on a per-session `run_id`, so a live save replaces the rows it already wrote.
A genuinely new run appends. Set `CARGO_LIVE_SAVE=0` to fall back to saving only
at Cells 10 / 28.

Two explicit call sites remain, for the deliberate end-of-stage saves and the
`run_label` the comparison uses:

- **Cell 10** — `cargo_timing_report(partial=True)` only: a PARTIAL profile.
  Cells 11–28 have not run yet, so the report is explicitly marked
  *(partial — run to CELL 28 for the full profile)*. The hook has already saved
  this run's timings by the time the cell ends.
- **Cell 28** — `cargo_save_timings(label="full run")`, the last cell, so the
  saved profile covers the whole pipeline and carries the authoritative label.

`label` is optional: omitted, a save labels itself `full run` once the run has
reached Cell 28 and `live (n cells)` otherwise, so a part-way run is never
mislabelled as complete.

`cargo_compare_timings()` then prints a per-cell delta (`PREV / NOW / DELTA / %`)
against the previous run. Live saving overwrites `timings.json` after every cell,
so the baseline is snapshotted once in memory before this run's first save. It
compares **only same-kind runs** — a partial run is never diffed against a full
one, and the guard applies even if a baseline is passed in explicitly.

`cargo_save_timings()` never raises: a telemetry write is wrapped in
`try/except` and degrades to a single `[!!] timing save failed: …` line, so it
can never break a working pipeline.

**Per-cell execution times (automatic, no per-cell edits).**
`_cargo_install_hooks()` registers IPython's `pre_run_cell` / `post_run_cell`
events. Each cell's `# CELL nn — TITLE` banner is parsed out of
`ExecutionInfo.raw_cell`, so every one of the 31 cells is timed and logged as it
finishes, and the result lands in `CARGO_CELL_TIMINGS`. Without an IPython
shell the registration is skipped (`CARGO_HOOKS_ACTIVE == False`) and the
notebook still runs — only the automatic per-cell numbers are missing.

**Live whole-run progress bar.**
One `ipywidgets.HTML` element is created in Cell 2 and re-rendered in place by
the `post_run_cell` hook, showing `cells done / 31`, the current cell and the
cumulative elapsed time. It lives in the kernel namespace, so it survives
across cell executions.

**Per-step progress logs.** `cargo_timer` / `cargo_done` mark the real work
boundaries, and `cargo_stage` wraps the multi-item loops:

- **Cell 7** — checkpoint download, SAM build, zip-dataset split copy (bar over
  files), weight resolution
- **Cell 8b** — YOLO detector load
- **Cell 9** — outer bar over images × inner bar over candidate objects, with
  per-object timers for crop/upscale → SAM encode → SAM predict → rank →
  clean mask → tight box/OBB
- **Cell 10** — outer bar over images, plus rank/gate and score/draw timers
- **Cells 3/4/5, 17–25** — image staging, decode, quality metrics, depth-model
  load, depth maps, point clouds, volume and weight

`cargo_timing_report(partial=True)` runs at the end of Cell 10 and prints an
**EXECUTION TIME PER CELL** table (plus the 15 slowest steps); Cell 28 saves the
complete profile to disk.

**Console safety.** The log glyphs are deliberately ASCII (`>>`, `[ok]`,
`[!!]`) because the default Windows console codec (cp1252) raises
`UnicodeEncodeError` on characters such as `▶`/`✔`. The richer glyphs survive
only inside the HTML bar, which is rendered by the browser.

**Verification.** `colab_cells/_verify_telemetry.py` executes Cell 2 in a bare
namespace and asserts the helpers record timings, that a failing block is logged
as `error:...` without swallowing the exception, and that the IPython hook
degrades to a no-op. Run it with
`.venv\Scripts\python.exe colab_cells\_verify_telemetry.py`.

### Setup Phase

#### Cell 0 — *CELL 1: Install Dependencies*
- `%pip install` for the base stack: `opencv-python, numpy, matplotlib, pillow, scipy,
  scikit-image, open3d, shapely, tqdm, requests, torch, torchvision, plotly`.
- **Why**: one-shot environment bootstrap so every later cell can import what it needs.

#### Cell 1 — *CELL 2: Imports, Configuration & Telemetry Bootstrap*
- Imports core libs (`cv2`, `numpy`, `matplotlib`, `PIL`, `pathlib`, `tqdm`).
- Creates the project skeleton directories:
  - `images/` (input copies), `outputs/` (visualizations + JSON), `models/`
    (checkpoints). All created with `mkdir(parents=True, exist_ok=True)` → idempotent.
- `PROJECT_DIR = Path.cwd()` anchors every path to the notebook's working directory.
- Also defines the **CARGO telemetry layer** (see §3.1) used by every later cell.
  It changes no pipeline behaviour — timing/logging only.

#### Cell 2 — *CELL 3: Select Local Cargo Images*
- Opens a **tkinter file dialog** to pick 1–3 images (from `Cargo Detection PoC/` by
  default); copies them into `images/` and builds `image_paths`.
- **Headless override**: env var `CARGO_IMAGES="a.png;b.jpg"` skips the GUI dialog —
  this is what the automated end-to-end test uses.
- Raises `RuntimeError` if nothing is selected; warns above 3 images.

#### Cell 3 — *CELL 4: Visualize Input Images*
- `load_image()` reads with `cv2.imread` and converts **BGR → RGB** (critical: OpenCV
  reads BGR, Matplotlib displays RGB — skipping this swaps colors everywhere).
- Plots all selected images side-by-side with filenames as titles.

#### Cell 4 — *CELL 5: Image Quality Check*
- `image_quality_report()` computes per image:
  - **Blur score** = variance of Laplacian (low = blurry → poor segmentation risk),
  - **Brightness** = mean gray value (detects over/under-exposed frames),
  - **Resolution** = width × height.
- Purely diagnostic — no image is modified.

#### Cell 5 — *CELL 6: Install Segment Anything*
- `%pip install git+https://github.com/facebookresearch/segment-anything.git` — installs
  the `segment_anything` package directly from source.

### Model Loading Phase

#### Cell 6 — *CELL 7: Load Models — SAM ViT-B + Cargo-Specific YOLO* (8.2 KB, the setup hub)
Four sub-blocks:
1. **7a — SAM checkpoint**: downloads `sam_vit_b_01ec64.pth` (with `tqdm` progress) into
   `models/` if absent, then `sam_model_registry["vit_b"]` loads it; moved to
   `cuda` if available, otherwise **CPU-optimized** (`torch.set_num_threads(4)`,
   MKL-DNN enabled, `channels_last` memory format). Wraps it in `SamPredictor`.
2. **7b — Class taxonomy**: defines `CARGO_CLASS_NAMES` and the three role tuples
   (TARGETS / ENVELOPE / EXCLUSIONS) mirroring the zip's `data.yaml`.
3. **7c — Dataset repair**: `prepare_cargo_zip_dataset()` extracts
   `Cargo-Detection.v3i.yolov8-obb.zip` (idempotent), builds a reproducible
   `images|labels/{train,val}` split (80/20, seed 42) and writes `cargo_obb_data.yaml`.
   Failures are caught → `cargo_dataset_info = None` (pipeline continues).
4. **7d — Weight resolution**:
   - `models/cargo_obb_best.pt` exists → `CARGO_YOLO_WEIGHTS` = it, origin
     `zip_trained_obb` (class-aware net/hook suppression available);
   - otherwise → `yolo11x.pt`, origin `coco_pretrained_fallback`.
   - `AUTO_TRAIN_FROM_ZIP = False` switch can fine-tune `yolov8n-obb.pt` in-notebook.

#### Cell 7 — *CELL 8: Clean Configuration for Auto-Generated Box Training*
- `ROI_NORMALIZED_BOXES = {"LOAD": None, "CARGO": None}` — **all hardcoded ROI
  coordinates removed**; only the `FULL` image ROI is produced by `get_roi_boxes()`.
- `clip_box()` clamps any box to image bounds and returns `None` for degenerate boxes.
- **Why**: guarantees *input independence* — no per-image pixel prompts.

---

### Detection & Segmentation Core

#### Cell 8 — *CELL 8b: Cargo-Specific YOLO Detection + Exclusion Zones* (14.3 KB — detection brain)
- `%pip install ultralytics`, loads `yolo_model = YOLO(CARGO_YOLO_WEIGHTS)` and detects
  the taxonomy: `USES_ZIP_TAXONOMY = all(name in model.names for name in
  CARGO_CLASS_NAMES)`.
- Thresholds: `conf=0.30` for the zip model, `conf=0.15` for COCO fallback
  (`iou=0.45`), plus a **two-pass recall path**: when the confident gate finds **zero
  payload boxes**, `detect_cargo_regions()` retries once at `LOW_CONF_RETRY = 0.18`
  (a lower gate is a superset of the first pass, so its guarded results replace the
  first pass wholesale). Recall improves on hard/night/distant-cargo frames without
  lowering precision on easy ones — the geometry/plausibility guards still discard
  slivers and hallucinations.
- **`detect_hanging_cargo_saliency()`** — classical-CV fallback: crops the vertical band
  `[0.10h, 0.85h]`, Canny edges → dilate → contours, then filters candidates by:
  area 1–70 % of frame, aspect ≤ 4.5, not touching the bottom (ground), not wall-wide
  (≤ 90 % width / 78 % height), not a thin border-pinned sliver, **solidity ≥ 0.35** of
  non-bright pixels; score = `area × solidity × elevation` (prefers mid-frame, below the
  hook). If nothing passes, returns a conservative lower-middle default box
  (0.18–0.82 w, 0.30–0.88 h, conf 0.60).
- **`_extract_detections()`** — flattens an Ultralytics `Results` object; prefers the
  **OBB rotated quad** (`result.obb.xyxy`, tighter) and falls back to `result.boxes`.
- **Plausibility guard `_plausible_payload_box()`** — rejects payload boxes smaller than
  `MIN_CARGO_BOX_PX=40` px, under `MIN_CARGO_AREA_FRACTION=2.5 %` of frame, or slivers
  (`PAYLOAD_MIN_ASPECT=0.15`), so rope knots / door frames never poison the pipeline.
- **`detect_cargo_regions()`** — the single detection entry point. Applies geometry
  sanity guards (skip ≤ 2 px boxes, > 92 % height / 98 % width boxes, ground-parked
  boxes with `y2 > 0.97h` and `h > 0.30h`), then splits detections into three groups:
  - `payload_boxes` — `Cargo-Box` / `Wooden-Plate` (zip) or COCO proxies
    (box, crate, suitcase, container…),
  - `envelope_boxes` — `Cargo-Detection` (whole net+load), ranked by confidence,
  - `exclusion_boxes` — `Net/Strap/Chain/Crane/Hook`, clipped to frame.
  Payloads are ranked by area (biggest solid load first).
  **If nothing found** → engages the saliency fallback and marks
  `source="SALIENCY_FALLBACK"`.
- `yolo_detect()` — legacy 4-tuple wrapper for older cells.

#### Cell 9 — *CELL 8c: Dynamic Load Region Estimator & Cargo Prompt Engine* (6.5 KB)
- `USE_MANUAL_OVERRIDE = False` — hardcoded debug prompts exist but are disabled
  (input independence).
- **`estimate_cargo_load_region(net_box, image)`** — row-by-row solid-pixel density
  inside the central 70 % column of the net box. Background separation is
  **scene-adaptive** (replaces the old fixed `gray < 240`, which marked *every* pixel
  solid at night and exploded the prompt box to the whole envelope):
  - background brightness = **median of the 4-px image border ring** (works for white
    backdrops *and* dark night sky/water),
  - OR a **Sobel texture term** (`grad > 40`) so flat cargo faces matching the
    background luminance still count as solid,
  - rows above 30 % of the max row count define `y_cargo_start … y_cargo_end`,
  - **sanity cap**: the band may never exceed **65 % of the frame height** — if it
    does, only the *lower* portion (where a hanging load lives) is kept.
  Emits 3 positive points at mid-height and 1 negative point in the empty upper
  net.
- **`build_cargo_prompts(payload, envelope, exclusion, image)`** — priority chain:
  1. **`ZIP_CARGO_BOX`** — union of payload boxes, positive points at each box centre
     plus two interior probes (35 % / 70 % height);
  2. **`DENSITY_ENVELOPE`** — only the net envelope known → density estimator derives
     the solid band;
  3. **`GLOBAL_FALLBACK`** — nothing detected → mid-lower band
     `[0.10w, 0.30h, 0.90w, 0.95h]`.
- **Negative points** come from exclusion detections sitting *above* the load band
  (`by2 <= y_cargo_start`) plus two deterministic probes just above the prompt box —
  actively steering SAM away from the webbing/rigging. All points clamped to image
  bounds.

#### Cell 10 — *CELL 9: Tight Cargo Bounding Box & Exclusion-Aware Mask Filter* (15.2 KB — segmentation brain)
- Builds a `SamAutomaticMaskGenerator` fallback (12 pts/side, `pred_iou 0.82`,
  `stability 0.88`, `min_mask_region_area 500`).
- Constants: `MASK_BG_CUTOFF=242`, ranking weights `5/4/2/3`,
  `OBB_TIGHTNESS_RATIO=0.92`, `CONTAINMENT_PAD=0.12`.
- Helpers: `boxes_to_mask()` (rasterise exclusion boxes), `box_iou()`.
- **`clean_cargo_mask()` — 4-stage cleanup**:
  1. subtract exclusion zones (net/strap/chain/hook/crane pixels → 0),
  2. clip to a vertical band `[by1 − 0.6·band, by2 + 0.25·band]` around the cargo box,
     2b. photometric suppression `gray < 242` when no exclusion zones exist,
     2c. contain the mask inside the prompt box + 12 % pad (stops the mask "walking"
     across similar texture and swallowing the scene),
     2d. **scene background subtraction** via `scene_background_mask()` — pixels that
     BOTH match the border-ring colour (±40 RGB distance) AND are locally smooth
     (σ < 12), keeping only components **connected to the frame border**. One rule
     handles white backdrops, night skies and water; interior cargo pixels are never
     removed because they are not border-connected,
  3. keep only the **largest connected component**,
  4. morphological **CLOSE** (9×9 ellipse ×2, seals net stripes) → **OPEN** (3×3, drops
     rope spurs) → contour fill (holes become solid).
- **Main loop** (per image × per ROI):
  1. run `detect_cargo_regions()` (or manual prompts),
  2. `predictor.set_image(roi)` (SAM image embedding, timed),
  3. `build_cargo_prompts()` → `prompt_box`, `pos_points`, `neg_points`,
  4. `predictor.predict(box, points, labels, multimask_output=True)` → 3 candidate masks,
  5. **rank candidates**:
     `rank = 5·SAM + 4·IoU(cand, cargo box) + 2·fill − 3·exclusion_bleed − 0.5·above`,
  6. `clean_cargo_mask()` on the winner (retry without exclusion mask if it empties),
  7. **tight AABB** from the cleaned mask + **rotated OBB** via `cv2.minAreaRect` kept
     only when ≥ 8 % tighter *and* its envelope stays ≤ 1.15× the AABB,
  8. **box floor**: if the prompt was `ZIP_CARGO_BOX`, the reported box is unioned with
     the prompt box so SAM under-segmentation cannot shrink the result below the
     detector's validated localization (the mask still marks only SAM-confirmed pixels),
  9. ROI → full-image coordinate offsets applied; results stored as 6-tuples
     `(mask, box, label, conf, sam_score, roi)` in `all_masks`, OBBs in
     `cargo_obb_by_image`, timings in `roi_timings_by_image`.

#### Cell 11 — *CELL 9b: High-Precision Self-Training Engine (YOLO11x @ 1024px)* (optional)
- **Disabled by default** (`CARGO_SELF_TRAIN=0`): the cell prints a DISABLED notice and
  skips the training loop entirely. Rationale — it trains a **1-class** detector on
  `./self_train_cargo_dataset`, built from only the 1–3 selected images (14 train / 5 val
  files in practice), and Cell 7 **never loads those weights** (it loads
  `CARGO_YOLO_WEIGHTS`, the zip-trained scene-grouped OBB model). An interrupted run also
  reports `mAP50 = 0`, which says nothing about the real detector. Set
  `CARGO_SELF_TRAIN=1` to run it as an experiment; its weights are never promoted.
- Compiles the produced masks into `./self_train_cargo_dataset` with an 80/20
  train/val split (seed 42); each mask becomes a YOLO label for **class 2
  (`suspended_cargo_in_net`)** in normalized `cx cy w h` format; guarantees a non-empty
  val folder (copies one train image over if needed).
- Trains `YOLO("yolo11x.pt")` for **30 epochs** (CPU-friendly; was 100 — `patience=10`
  early-stops before that when val mAP stalls) @ 1024 px, batch 2, `workers=0`
  (in-process dataloader so the PC stays responsive), AdamW, `lr0=0.001`,
  mosaic/mixup/copy-paste augmentation (`close_mosaic=5`), loss weights
  `box=8.5 cls=0.5 dfl=2.0`, `warmup_epochs=3`. Drop `imgsz` to 640 for ~2.6×
  faster epochs if CPU training still lags.
- Reloads the **resolved** `CARGO_YOLO_WEIGHTS` (not a stale run path) so the
  zip-taxonomy stays intact. `train_yolo_optimized.py` is the standalone equivalent.
- **Skip this cell for a normal run** (it is a training loop, not required for
  inference).

---

### Measurement / Output Phase

#### Cell 12 — *CELL 10: Candidate Scoring, Cargo-Only Visualization & Dashboard* (7.9 KB)
- `candidate_selection_score()` picks the final mask among all ROI candidates:

  ```
  score = 8·SAM_quality + 6·fill_ratio + 4·detector_conf + 2·area_score
          − 10·floor_penalty − 2·top_penalty − 8·oversize − 3·undersize
          − 6·border_leak − 2·fallback_penalty
  ```
  - `fill_ratio` is measured against the **mask's own extent** (so a floor-widened box
    doesn't read as hollow),
  - `area_score` peaks when the mask covers ~25 % of the frame and is forced to 0 below
    3 % (sliver ⇒ undersize penalty),
  - `floor_penalty=10` when the box touches the bottom (dock/ground),
    `top_penalty=2` at the very top (crane/sky),
    `oversize = 8·max(0, ratio−0.40)` (tightened from `5·(ratio−0.55)`),
    `undersize = 3·max(0, (0.03−ratio)/0.03)`,
  - `border_leak = 6·max(0, leak−0.05)` where `leak` = share of the 3-px frame-border
    ring covered by the mask (sky/water masks are glued to the border; suspended
    cargo isn't),
  - `fallback_penalty=2` for candidates with no real payload detection behind them
    (label `cargo_payload`, conf 0.50) — genuine YOLO localisations win ties.
- **Acceptance gate — no vague boxes.** The top-ranked candidate must also pass:
  `score ≥ MIN_ACCEPT_SCORE (6.0)`, box area ≤ `MAX_ACCEPT_BOX_FRACTION (60 %)` of the
  frame, and border leak ≤ `MAX_ACCEPT_BORDER_LEAK (12 %)`. If it fails, **no box is
  drawn** — the image is reported as `NO CONFIDENT CARGO` with the failing metrics and
  the plain overlay is saved instead (an honest miss beats a red rectangle).
- `mask_to_full_image()` lifts the ROI-local mask back to full-frame coordinates.
- Draws: semi-transparent **red mask on cargo pixels only**, thick red AABB, optional
  **amber OBB**, and a label `class | Conf | SAM | ROI`; saves PNG to `outputs/` and
  `cargo_output_visualizations/`.
- Prints the **performance dashboard**: per-ROI object count, detection/prompt source
  and total processing time, plus final cargo box extents per image.

#### Cell 13 — *CELL 11: Visualize Selected Cargo Mask*
- Green 50 % overlay of `selected_masks[i]` on each image — a clean, annotation-free
  view of exactly the segmented cargo pixels.

#### Cell 14 — *CELL 12: Extract Cargo Geometry*
- From each selected mask: `x_min/x_max/y_min/y_max`, `width_px`, `height_px`,
  `area_px` → `cargo_geometry` (feeds the metric stage).

#### Cell 15 — *CELL 13: Reference Scale*
- Sets `REFERENCE_WIDTH_METERS = 2.0` — the only physical assumption in the pipeline
  (the known width of the reference structure, e.g. the lifting net).

#### Cell 16 — *CELL 14: Fully Automatic Pixel-to-Meter Calibration*
- `find_reference_width_pixels()` scans all candidate masks and accepts **both** the
  pipeline 6-tuples and legacy SAM dicts (`{"segmentation":…}` — a compatibility fix that
  previously caused `TypeError: tuple indices must be integers`).
- A reference candidate must be a large structure: width ≥ 35 % of image, height ≥ 25 %,
  area 5–90 % of frame; scored by
  `0.45·width_ratio + 0.20·height_score + 0.10·fill_score + 0.15·stability + 0.10·IoU`.
- Fallback: 65 % of image width (approximate but keeps the run automatic).
- Computes `meters_per_pixel = 2.0 / reference_pixel_width` (and the inverse).

#### Cell 17 — *CELL 15: Estimate Real-World 2D Dimensions*
- `width_m = width_px · meters_per_pixel`, `height_m = height_px · meters_per_pixel`
  for image 1 — the physical size of the cargo.

#### Cell 18 — *CELL 16: Install Depth Dependencies*
- `%pip install transformers` (Hugging Face).

#### Cell 19 — *CELL 17: Load Depth Model*
- `pipeline(task="depth-estimation", model="LiheYoung/depth-anything-small-hf")` —
  Depth-Anything Small: monocular relative-depth estimation.

#### Cell 20 — *CELL 18: Generate Depth Map*
- For each image: RGB array → PIL → pipeline → `result["depth"]` array; visualized with
  the `plasma` colormap + colorbar.

#### Cell 21 — *CELL 19: Extract Cargo Depth*
- Resizes the cargo mask to the depth-map shape (`INTER_NEAREST` to preserve binary
  edges) and zeroes out everything outside the mask → `cargo_depth_maps` (depth of the
  cargo region only).

#### Cell 22 — *CELL 20: Create Initial 3D Point Cloud*
- `depth_to_point_cloud()` uses a normalized pinhole camera (`fx=fy=w`,
  `cx=w/2, cy=h/2`): `X=(x−cx)·Z/fx`, `Y=(y−cy)·Z/fy`, `Z=depth`, restricted to masked
  pixels, colors from the RGB image → `open3d.geometry.PointCloud`.

#### Cell 23 — *CELL 21: Visualize 3D Point Cloud in VS Code*
- Plotly `Scatter3d` with per-point RGB colors, `aspectmode="data"` — interactive
  rotation/zoom inside VS Code's plot viewer.

#### Cell 24 — *CELL 22: Initial 3D Volume Estimation*
- `pcd.get_axis_aligned_bounding_box().get_extent()` → `volume = ex·ey·ez`
  (relative metric volume in the normalized camera scale).

#### Cell 25 — *CELL 23: Cargo Classification*
- Prints the 4 PoC categories (Scrap Steel / Thermal Coal / Construction Gravel /
  Agricultural Grain) and prompts for a choice.
- **Headless override**: env var `CARGO_TYPE="3"` answers automatically.

#### Cell 26 — *CELL 24: Density Database*
- Static lookup (kg/m³): scrap steel 7850, thermal coal 800, construction gravel 1700,
  agricultural grain 750. Accepts menu numbers (`1–4`) or full names via an alias map;
  unknown input → `density = None` (weight stage then degrades gracefully).

#### Cell 27 — *CELL 25: Weight Estimation*
- `estimated_weight = relative_volume × density` (kg); prints explicit messages when
  density or volume is unavailable instead of crashing.

#### Cell 28 — *CELL 26: Final Inspection Result*
- Assembles the report dict: `inspection_status`, `cargo_type`, `volume`,
  `density_kg_m3`, `estimated_weight_kg`, `number_of_images`, and the toolchain used
  (`segmentation: SAM`, `depth_estimation: Depth Anything`, `3d_processing: Open3D`).

#### Cell 29 — *CELL 27: Save Inspection Result*
- Writes `outputs/inspection_result.json` (pretty-printed, indent 4).

#### Cell 30 — *CELL 28: Inspection Result Location*
- Prints the absolute path of the saved JSON.

---

## 4. Supporting Scripts (run outside the notebook)

### `cargo_dataset_from_zip.py` — dataset repair
The Roboflow zip ships 90 images in one flat `train/` folder while its `data.yaml`
points at non-existent `valid/`/`test/`, so Ultralytics refuses to train directly.
The script: **extract zip (idempotent) → copy into `images|labels/{train,val}`
(scene-grouped split, seed 42) → write `cargo_obb_data.yaml`** with the 8-class
taxonomy.

**The split is grouped by source scene.** Roboflow exports ~5 augmented variants of
each photo as `<original>.rf.<hash>.jpg`, so the 90 files are really only **18 unique
scenes**. Shuffling the flat file list (the original behaviour) put near-identical
twins on both sides of the boundary — **all 18 val images had an augmented sibling in
train**, so validation mAP measured memorisation rather than generalisation. The
script now groups by everything before the first `.rf.` and splits on **scenes**,
yielding **65 train / 25 val images (13 / 5 scenes)** at `--val-ratio 0.30`. A
post-split guard raises if any scene ever lands on both sides. Cell 7
(`prepare_cargo_zip_dataset`) implements the same grouping and guard.

```bash
python cargo_dataset_from_zip.py --val-ratio 0.20
```

### `train_cargo_obb.py` — train the cargo OBB detector
Fine-tunes `yolov8n-obb.pt` on the scene-grouped dataset (AdamW, mosaic +
HSV/rotate/scale augmentation, loss weights `box=8.5 cls=0.6 dfl=2.0`), then with
`--promote` copies `best.pt` → `models/cargo_obb_best.pt`, which **Cell 7 loads
automatically** — this is the single step that unlocks class-aware suppression of
net/straps/chain/crane/hook.

```bash
# quick run (CPU-friendly; matches the promoted baseline)
python train_cargo_obb.py --epochs 25 --imgsz 512 --batch 4 --force-dataset --promote

# longer run for a better model (~2.4x the compute)
python train_cargo_obb.py --epochs 60 --imgsz 640 --batch 4 --promote
```

`--val-ratio` (default **0.30**) is the fraction of **source scenes** held out, not of
files. Use `--force-dataset` when changing it: `build_train_val_split()` is a no-op once
a split already exists on disk.

### `train_yolo_optimized.py` — self-training variant
Standalone version of Cell 9b: auto-builds `self_train_cargo_dataset`, trains
`yolo11x.pt` **30 epochs** (patience=10 early-stop, `workers=0`) on
`cargo_auto_data.yaml` (3 classes: `cargo_container`, `lifting_net_assembly`,
`suspended_cargo_in_net`).

> ⚠️ **Its reported mAP is not meaningful and its weights are unused.** When a label
> file is missing it writes a hardcoded placeholder box (`2 0.5 0.7 0.4 0.4`,
> `train_yolo_optimized.py:46-55`). In the runs on disk 12 of 19 label files were that
> one constant, classes 0/1 had **zero** instances, and the only class present in val
> was class 2 — training on constants collapses to `precision 0 / recall 0 / mAP50 0`
> from epoch 2. Cell 7 never loads the result; it loads `CARGO_YOLO_WEIGHTS`.

---

## 5. How To Run & Verify

```powershell
# 1) (recommended) train + promote the cargo detector
#    --force-dataset: build_train_val_split() no-ops if a split already exists
.venv\Scripts\python.exe cargo_dataset_from_zip.py --force
.venv\Scripts\python.exe train_cargo_obb.py --epochs 25 --imgsz 512 --batch 4 --force-dataset --promote

# 2) open the notebook in VS Code / Jupyter and run cells in order:
#    0-5 setup -> 6 (models) -> 7, 8, 9, 10 (detect+segment) -> 12 (score/viz)
#    -> 14-17 (calibration) -> 19-24 (depth/3D/volume) -> 25-30 (weight/report)
#    Cell 11 (self-training) is OPTIONAL and disabled by default — see CARGO_SELF_TRAIN.
```

Headless (no GUI dialog / no input prompt):

```powershell
$env:CARGO_IMAGES = "C:\path\to\img1.png;C:\path\to\img2.jpg"
$env:CARGO_TYPE = "1"
```

Telemetry on/off (all default ON — see §3.1):

```powershell
$env:CARGO_DEBUG = "0"      # no per-step log lines (timings still recorded)
$env:CARGO_PROGRESS = "0"   # no live progress bars
```

Cell 9b self-training (off by default — see §3, Cell 11):

```powershell
$env:CARGO_SELF_TRAIN = "1"   # opt in to the 1-class self-training experiment
```

**Outputs**
- `outputs/cargo_yolo_sam_image_N.png` and
  `cargo_output_visualizations/cargo_yolo_sam_image_N.png` — red cargo-only mask +
  tight box (+ amber OBB) overlay;
- `outputs/inspection_result.json` — final report (type, volume, density, weight);
- Performance dashboard printed by Cell 10 (objects, source, timing per ROI);
- `outputs/timings.json`, `outputs/timing_report.md`, `outputs/timing_history.csv` —
  the run's timing profile (per cell, per phase, per step), written by Cell 10
  (partial) and Cell 28 (full) — see §3.1.

**Graceful degradation (by design)**

| Missing piece | Behaviour |
|---|---|
| `models/cargo_obb_best.pt` | falls back to `yolo11x.pt` COCO + saliency; no class-aware net/hook suppression |
| Roboflow zip absent | Cell 7 warns, `cargo_dataset_info=None`, inference continues |
| YOLO finds nothing | `detect_hanging_cargo_saliency()` provides an envelope box |
| SAM predict error | caught per-ROI; timing entry `SAM_ERROR`, run continues |
| Unknown cargo type | `density=None` → weight prints "unavailable", JSON gets `null` |
| No reference structure | calibration falls back to 65 % of image width |

---

## 6. Assumptions & Limitations

1. `REFERENCE_WIDTH_METERS = 2.0` (Cell 15) is a hard assumption — all metric outputs
   (size, volume, weight) scale linearly with it.
2. Camera intrinsics are normalized (`fx = fy = width`), so **volume is relative**, not
   metrically exact; weight inherits that approximation.
3. Depth is *relative* monocular depth (Depth Anything), not metrically calibrated.
4. The pipeline processes 1–3 images; index-based results (`volumes[0]`,
   `cargo_geometry[0]`) report on the **first** image.
5. Cell 11 (self-training) and `AUTO_TRAIN_FROM_ZIP` are optional/long-running training
   paths, not needed for inference.
6. Weights are reported in kg from `volume × density` without net-tare subtraction.

---

## 7. Notebook Recovery Log — 28 Sep 2026

**Incident:** `Revamping.ipynb` was overwritten at 12:04:45 PM with an old copy of the
notebook (stale editor buffer), silently reverting Cell 7 / 8b / 8c / 9 / 10 (accuracy
fixes) **and** Cell 9b (CPU training budget: `epochs=30`, `workers=0`, `patience=10`).
Symptom: `_build/_e2e_test.py` failed with `KeyError: 'selected_boxes'` and the console
printed the old cell banners (`Multi-class YOLO & dynamic cargo detector`,
`Dynamic load region estimator active`).

**Authoritative sources (Cells 7–10 are generated — never hand-edit them):**

| Content | Source of truth |
|---|---|
| Cells 7, 8b, 8c, 9, 10 | `_build/cell07_load_models.py`, `cell08b_detect.py`, `cell08c_prompts.py`, `cell09_segment.py`, `cell10_visualize.py` via `python _build/_apply_notebook_updates.py` |
| Cell 9b training budget | `_build/verify_cpu_train_settings.py` validates it (epochs=30, workers=0, patience=10, warmup_epochs=3, close_mosaic=5) |
| Other 26 cells | `Revamping_executed.ipynb` (executed 25 Sep copy, 31 cells) — sources reusable |
| CLI training path | `train_yolo_optimized.py` (already carries the CPU settings) |

**Restore procedure (verified working):**
1. Rebuild `Revamping.ipynb` from `Revamping_executed.ipynb` sources (clear outputs).
2. `python _build/_apply_notebook_updates.py` → restores Cells 7/8b/8c/9/10 with the fixes.
3. Re-apply the Cell 9b patch (`epochs=30`, `workers=0`, `patience=10`, `warmup_epochs=3`, `close_mosaic=5`).
4. Validate: `python _build/verify_cpu_train_settings.py` (ALL CHECKS PASSED), then
   `python _build/_e2e_test.py` (expect `[PASS]` plus `accepted 'Cargo-Box' (score …, box …% of frame, border leak …)`).
5. The overwritten file is archived at `_build/Revamping.ipynb.old_20260928_1204.bak`.

**Post-restore verification (28 Sep 2026):** e2e `[PASS]`, detector `zip_trained_obb`,
image 1 box 210×140 px (11.8% of frame), image 2 box 146×77 px (4.3%), border leakage
0.0% on both; `verify_cpu_train_settings.py` ALL CHECKS PASSED.

**Prevention:** close the notebook tab before regenerating it; if VS Code reports
"file changed on disk", choose *Revert/Reload from disk* — never save the old buffer.
Commit the notebook and `_build/` sources to git after every verified run.

