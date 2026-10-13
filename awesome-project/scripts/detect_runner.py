"""Headless single-image runner for the cargo detection pipeline.

Owned by ``awesome-project`` but executed by the *detection* project's
interpreter, because the two environments cannot be merged: this app's venv has
no torch, and the detection venv carries ~5.5 GB of torch/ultralytics/open3d.
The seam between them is this script — ``services/detection.py`` is the FastAPI
side that invokes it.

``CARGO_PROJECT_DIR`` overrides the detector location, which defaults to the
vendored ``detector/`` directory next to this repo's root. Set it to try an
upstream notebook without re-vendoring first.

The pipeline lives in that notebook as 31 cells sharing one global namespace —
``cell22_volume.py`` calls ``cargo_stage()`` defined ten cells earlier,
``cell26_result.py`` reads six names from cells before it. They cannot be
imported as modules. They are executed, in order, into one ``dict``, which is
exactly what ``_build/_e2e_test.py`` already does successfully on this machine.
This is a narrowing of proven code, not a new mechanism.

Three deliberate differences from the notebook:

1. **CELL 3 (the tkinter dialog) is skipped.** ``image_paths`` is assigned
   directly. Same trick the e2e test uses.
2. **``OUTPUT_DIR`` is redirected** to a per-request directory after CELL 2
   runs. The notebook hardcodes ``outputs/``, so two concurrent requests would
   overwrite each other's overlays.
3. **Cells 12-28 are not run.** Those measure depth, point cloud and volume.
   They have never been validated headlessly and their output is relative, not
   metric — so this runner covers detection and segmentation only.

Usage::

    python detect_runner.py --image path/to/img.jpg --out-dir run_123

Writes ``run_123/result.json`` and ``run_123/overlay.png``. Exit code 0 means
"the pipeline ran"; a refusal (no cargo found) is a 0 with ``detected: false``,
because refusing is a correct answer, not a failure.
"""

from __future__ import annotations

import argparse
import contextlib
import io
import json
import os
import re
import shutil
import sys
import time
import traceback
from pathlib import Path

#: The vendored detector: holds Revamping.ipynb and models/. Lives inside this
#: repo so the pipeline is a self-contained dependency, not a folder reference.
#: `CARGO_PROJECT_DIR` overrides it — useful for trying an upstream notebook
#: without re-vendoring first.
DETECTOR_DIR = Path(__file__).resolve().parent.parent / "detector"
PROJECT = Path(os.environ.get("CARGO_PROJECT_DIR") or DETECTOR_DIR).resolve()
NOTEBOOK = PROJECT / "Revamping.ipynb"

#: Cells that must run for detection + segmentation. Verified by the e2e sweep
#: (16 images, 11 pass). Cells 12+ are measurement and are deliberately absent.
SETUP_CELLS = ("CELL 2", "CELL 4")
PIPELINE_CELLS = ("CELL 7", "CELL 8", "CELL 8b", "CELL 8c", "CELL 9", "CELL 10")

#: Copied verbatim from `_build/_e2e_test.py`. CELL 10 reports its verdict to
#: stdout rather than returning it, so the log is the only source for the score
#: and the accepted class label.
ACCEPTED_RE = re.compile(
    r"Image (\d+): accepted '([^']+)' \(score ([\d.]+), box ([\d.]+)% of frame, "
    r"border leak ([\d.]+)%\)"
)
REFUSED_RE = re.compile(
    r"Image (\d+): NO CONFIDENT CARGO.*?best candidate score ([\d.]+) \(min ([\d.]+)\)"
    r".*?box ([\d.]+)% of frame \(max ([\d.]+)%\)"
    r".*?border leak ([\d.]+)% \(max ([\d.]+)%\)"
)
NO_CANDIDATE_RE = re.compile(r"Image (\d+): no candidate masks available")

#: CELL 10 prints one line per accepted object, already in full-image
#: coordinates (`tight` comes from `mask_to_full_image`). Parsing that line is
#: better than recomputing: the coordinate maths involves the ROI offset and
#: re-deriving it here would be a second implementation of the same rule, free
#: to drift from the notebook.
OBJECT_RE = re.compile(
    r"Cargo #(\d+): class=(\S+) yolo=([\d.]+) sam=([\d.]+) mask_area=(\d+)px "
    r"yolo_box=\[([^\]]*)\] sam_box=\[([^\]]*)\] tight=\[([^\]]*)\]"
)
OBJECTS_COUNT_RE = re.compile(r"\) x(\d+) object\(s\)\.")


def _floats(raw: str) -> list[float] | None:
    parts = [p.strip() for p in raw.split(",") if p.strip()]
    try:
        return [float(p) for p in parts]
    except ValueError:
        return None


def parse_objects(text: str) -> list[dict]:
    """Return every accepted cargo region, ranked as CELL 10 ranked them."""
    found: list[dict] = []
    for m in OBJECT_RE.finditer(text):
        _, label, yolo, sam, area, yolo_box, sam_box, tight = m.groups()
        found.append({
            "label": label,
            "yolo_confidence": float(yolo),
            "sam_score": float(sam),
            "mask_area_px": int(area),
            "yolo_box_px": _floats(yolo_box),
            "sam_box_px": _floats(sam_box),
            "box_px": _floats(tight),          # full-image, tight to the mask
        })
    return found


class Tee(io.TextIOBase):
    """Mirror stdout to the console while keeping a copy to parse."""

    def __init__(self, stream) -> None:
        self._stream = stream
        self._chunks: list[str] = []

    def write(self, text: str) -> int:
        self._stream.write(text)
        self._chunks.append(text)
        return len(text)

    def flush(self) -> None:
        self._stream.flush()

    @property
    def text(self) -> str:
        return "".join(self._chunks)


def strip_magics(source: str) -> str:
    """Drop IPython magics / shell escapes, honouring line continuations.

    A `%pip install` line can span several physical lines joined by a trailing
    backslash. Replacing only the first line leaves the continuation to execute
    as a syntax error, so the whole run is consumed here.
    """
    out: list[str] = []
    lines, index = source.splitlines(), 0
    while index < len(lines):
        line = lines[index]
        if line.lstrip().startswith(("%", "!")):
            while line.rstrip().endswith("\\") and index + 1 < len(lines):
                index += 1
                line = lines[index]
            out.append("pass")
        else:
            out.append(line)
        index += 1
    return "\n".join(out)


def cell_banner(source: str) -> str | None:
    """Return the cell's ``# CELL nn`` banner, or None if it has no banner.

    Only the first comment line counts. That is what stops an incidental
    mention of a cell number inside a comment from claiming another cell's slot.
    """
    for line in source.splitlines():
        stripped = line.strip()
        if not stripped.startswith("#"):
            continue
        text = stripped.lstrip("#").strip()
        if not text or set(text) <= set("=-_*~ "):
            continue                      # decorative rule, keep looking
        if text.upper().startswith("CELL "):
            return text
        return None                      # leading non-banner comment -> skip
    return None


def load_cells() -> dict[str, str]:
    """Index the notebook's pipeline cells by their ``# CELL nn`` banner."""
    if not NOTEBOOK.is_file():
        raise FileNotFoundError(
            f"No Revamping.ipynb in {PROJECT}. That folder is not a detector "
            f"project: it must hold the notebook and a models/ directory. "
            f"Either re-vendor (see detector/README.md) or point "
            f"CARGO_PROJECT_DIR at the folder containing Revamping.ipynb."
        )
    notebook = json.loads(NOTEBOOK.read_text(encoding="utf-8"))
    cells: dict[str, str] = {}
    for cell in notebook["cells"]:
        if cell.get("cell_type") != "code":
            continue
        source = "".join(cell.get("source", []))
        if not source.lstrip().startswith("#"):
            continue
        banner = cell_banner(source)
        if banner is None:
            continue
        parts = banner.split(" ")
        if len(parts) > 1 and parts[0].upper() == "CELL":
            cells[f"CELL {parts[1]}"] = strip_magics(source)

    missing = [c for c in SETUP_CELLS + PIPELINE_CELLS if c not in cells]
    if missing:
        raise RuntimeError(f"Revamping.ipynb is missing cell(s): {missing}")
    return cells


def run_cell(name: str, source: str, namespace: dict, capture=None) -> None:
    code = compile(source, f"<{name}>", "exec")
    if capture is None:
        exec(code, namespace)
    else:
        with contextlib.redirect_stdout(capture):
            exec(code, namespace)


def parse_verdict(text: str) -> dict:
    """Turn CELL 10's console verdict into a dict."""
    flat = " ".join(text.split())

    accepted = ACCEPTED_RE.search(flat)
    if accepted:
        _, label, score, box_pct, leak = accepted.groups()
        return {
            "detected": True,
            "label": label,
            "score": float(score),
            "box_fraction_of_frame": float(box_pct) / 100.0,
            "border_leak": float(leak) / 100.0,
        }

    if NO_CANDIDATE_RE.search(flat):
        return {"detected": False, "reason": "no_candidate_masks",
                "label": None, "score": None}

    refused = REFUSED_RE.search(flat)
    if refused:
        _, score, min_score, box_pct, max_box, leak, max_leak = refused.groups()
        return {
            "detected": False,
            "reason": "below_acceptance_gate",
            "label": None,
            "score": float(score),
            "min_score": float(min_score),
            "box_fraction_of_frame": float(box_pct) / 100.0,
            "max_box_fraction_of_frame": float(max_box) / 100.0,
            "border_leak": float(leak) / 100.0,
            "max_border_leak": float(max_leak) / 100.0,
        }

    return {"detected": False, "reason": "no_verdict_parsed", "label": None,
            "score": None}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="Run cargo detection on one image, headlessly.")
    parser.add_argument("--image", required=True, help="image file to analyse")
    parser.add_argument("--out-dir", required=True,
                        help="directory for result.json and overlay.png")
    args = parser.parse_args(argv)

    image = Path(args.image).resolve()
    out_dir = Path(args.out_dir).resolve()

    if not image.is_file():
        print(f"[runner] no such image: {image}", file=sys.stderr)
        return 2

    out_dir.mkdir(parents=True, exist_ok=True)

    # Matplotlib must not try to open a window, and the telemetry progress bars
    # would flood stdout that the caller is parsing.
    os.environ["MPLBACKEND"] = "Agg"
    os.environ.setdefault("CARGO_DEBUG", "0")
    os.environ.setdefault("CARGO_PROGRESS", "0")
    os.environ.setdefault("CARGO_LIVE_SAVE", "0")

    # CELL 2 anchors every path to the cwd, so the notebook must be "run" from
    # the project root regardless of where the caller invoked us.
    os.chdir(PROJECT)

    started = time.perf_counter()
    namespace: dict = {"__name__": "__main__"}
    result: dict = {
        "ok": False,
        "image": str(image),
        "error": None,
    }

    try:
        cells = load_cells()

        run_cell(SETUP_CELLS[0], cells[SETUP_CELLS[0]], namespace)

        # Redirect artefacts before anything reads OUTPUT_DIR. cell07 reads it
        # from globals(), and the telemetry helpers do too, so this one
        # assignment relocates every output the run will produce.
        run_out = out_dir / "outputs"
        run_out.mkdir(parents=True, exist_ok=True)
        namespace["OUTPUT_DIR"] = run_out

        # Pin the weights directory explicitly. CELL 7 defaults it to
        # PROJECT_DIR / "models", which is correct when PROJECT is the vendored
        # detector/ — but an explicit assignment also keeps working when
        # CARGO_PROJECT_DIR points somewhere with an unusual layout.
        namespace["MODEL_DIR"] = PROJECT / "models"

        # Stand in for CELL 3's tkinter dialog.
        namespace["image_paths"] = [str(image)]

        for name in SETUP_CELLS[1:]:
            run_cell(name, cells[name], namespace)

        images = namespace.get("images") or []
        if len(images) != 1:
            raise RuntimeError(f"CELL 4 loaded {len(images)} images, expected 1")

        height, width = images[0].shape[:2]

        tee = Tee(sys.stdout)
        for name in PIPELINE_CELLS:
            run_cell(name, cells[name], namespace,
                     capture=tee if name == "CELL 10" else None)

        verdict = parse_verdict(tee.text)
        objects = parse_objects(tee.text)
        boxes = namespace.get("selected_boxes") or []
        masks = namespace.get("selected_masks") or []
        box = boxes[0] if boxes else None
        mask = masks[0] if masks else None

        box_px = None
        if box is not None:
            box_px = [round(float(box[0]), 1), round(float(box[1]), 1),
                      round(float(box[2]), 1), round(float(box[3]), 1)]

        # mask_area_ratio: how much of the frame the segmented cargo covers.
        # Distinct from the gate's box_fraction, which measures the bounding box.
        mask_area_ratio = None
        if mask is not None:
            mask_area_ratio = round(float((mask > 0).sum()) / float(width * height), 5)

        overlay = run_out / "cargo_yolo_sam_image_1.png"
        overlay_target = out_dir / "overlay.png"
        if overlay.is_file():
            shutil.copyfile(overlay, overlay_target)

        # CELL 10 also writes a second copy of the overlay next to the project
        # (`cargo_output_visualizations/`). The canonical copy is already above,
        # so remove the duplicate — otherwise every run litters the vendored
        # directory with PNGs that can never be committed (see .gitignore).
        # Single-image only: the runner asserts exactly one image, so index 1
        # is the only file this run could have produced.
        viz_copy = PROJECT / "cargo_output_visualizations" / "cargo_yolo_sam_image_1.png"
        viz_copy.unlink(missing_ok=True)

        result.update({
            "ok": True,
            "image_width": int(width),
            "image_height": int(height),
            "detected": bool(verdict.get("detected")),
            "label": verdict.get("label"),
            "score": verdict.get("score"),
            "box_px": box_px,
            "box_width_px": round(box_px[2] - box_px[0], 1) if box_px else None,
            "box_height_px": round(box_px[3] - box_px[1], 1) if box_px else None,
            "box_fraction_of_frame": verdict.get("box_fraction_of_frame"),
            "border_leak": verdict.get("border_leak"),
            "mask_area_ratio": mask_area_ratio,
            "object_count": len(objects),
            "objects": objects,
            "reason": verdict.get("reason"),
            "detector_origin": namespace.get("CARGO_MODEL_ORIGIN"),
            "detector_weights": namespace.get("CARGO_YOLO_WEIGHTS")
            and str(namespace["CARGO_YOLO_WEIGHTS"]),
            "uses_zip_taxonomy": bool(namespace.get("USES_ZIP_TAXONOMY")),
            "overlay": str(overlay_target) if overlay_target.is_file() else None,
            "stage": "detection_and_segmentation",
        })
    except Exception as exc:                      # noqa: BLE001 - reported, not swallowed
        result["error"] = f"{type(exc).__name__}: {exc}"
        result["traceback"] = traceback.format_exc()[-2000:]

    result["elapsed_seconds"] = round(time.perf_counter() - started, 2)

    (out_dir / "result.json").write_text(json.dumps(result, indent=2),
                                         encoding="utf-8")
    # Short, parseable marker. Everything else the pipeline printed went to the
    # inherited stdout on purpose -- the notebook is chatty and a caller
    # scanning this would be reading megabytes of telemetry.
    print(f"[runner] {'OK' if result['ok'] else 'FAILED'} "
          f"detected={result.get('detected')} "
          f"elapsed={result['elapsed_seconds']}s "
          f"-> {out_dir / 'result.json'}")
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
