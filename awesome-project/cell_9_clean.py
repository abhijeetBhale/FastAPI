# ============================================================
# CELL 2 — IMPORTS, CONFIGURATION & TELEMETRY BOOTSTRAP
# ============================================================
# WHAT: shared imports, the project directory layout, and the CARGO telemetry
#   layer (per-step logs, per-cell timing, live progress bars) that every later
#   cell uses. Nothing here changes pipeline behaviour.

import os
import cv2
import json
import math
import time as _cargo_time
import numpy as np
import matplotlib.pyplot as plt

from PIL import Image
from pathlib import Path
from tqdm.auto import tqdm

print("Libraries imported successfully.")

# ------------------------------------------------------------
# Project directories
# ------------------------------------------------------------

PROJECT_DIR = Path.cwd()

IMAGE_DIR = PROJECT_DIR / "images"
OUTPUT_DIR = PROJECT_DIR / "outputs"
MODEL_DIR = PROJECT_DIR / "models"

IMAGE_DIR.mkdir(parents=True, exist_ok=True)
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
MODEL_DIR.mkdir(parents=True, exist_ok=True)

print("Project directory:", PROJECT_DIR)

# ============================================================
# CARGO TELEMETRY  (timing / progress / live bars)
# ============================================================
# HOW TO USE
#   with cargo_timer("SAM encode", image=3):      ...     # timed block
#   cargo_note("something happened")                      # one-off log line
#   for img in cargo_stage("depth map", total=3):  ...     # live progress bar
#   cargo_timing_report()                                 # print the tables
#
# Switches (both read once, here):
#   CARGO_DEBUG=0    silence every log line (timings still recorded)
#   CARGO_PROGRESS=0 hide the live progress bars
# Both default to ON. Everything degrades to a no-op outside IPython
# (_build/_e2e_test.py execs these cells in a bare namespace), so the headless
# test harness keeps working untouched.

CARGO_DEBUG = os.environ.get("CARGO_DEBUG", "1").strip().lower() not in (
    "0", "false", "no", "off",
)
CARGO_PROGRESS = os.environ.get("CARGO_PROGRESS", "1").strip().lower() not in (
    "0", "false", "no", "off",
)
#: Rewrite outputs/timings.* after EVERY cell, not only at cell 10 / 28.
CARGO_LIVE_SAVE = os.environ.get("CARGO_LIVE_SAVE", "1").strip().lower() not in (
    "0", "false", "no", "off",
)

#: Total number of code cells, used by the whole-run progress bar.
CARGO_TOTAL_CELLS = 31

#: Every finished cargo_timer block lands here (dicts with name/seconds/...).
CARGO_STEP_LOG = []

#: Per-cell records, filled in by the IPython pre/post_run_cell hook.
CARGO_CELL_TIMINGS = []

#: Monotonic start of the whole run, used for the "elapsed" column.
CARGO_RUN_START = _cargo_time.perf_counter()

#: Stable id for this kernel session. Every live save reuses it, so the history
#: CSV can replace this run's rows instead of re-appending them each time.
CARGO_RUN_ID = _cargo_time.strftime("%Y%m%dT%H%M%SZ", _cargo_time.gmtime())

#: The previous run's timings.json, snapshotted before this run overwrites it.
CARGO_PREVIOUS_RUN = None

#: True once this session has looked for a previous run. The snapshot must be
#: taken exactly once -- on the first live save -- or a later save of THIS run
#: would be mistaken for the baseline.
CARGO_PREVIOUS_CAPTURED = False

#: The last pipeline cell: a run that reaches it has a complete profile.
CARGO_LAST_CELL = 28


def _cargo_stamp():
    """Wall-clock HH:MM:SS prefix for a log line."""
    return _cargo_time.strftime("%H:%M:%S")


def cargo_note(message):
    """Print one timestamped debug line (suppressed when CARGO_DEBUG=0)."""
    if CARGO_DEBUG:
        print(f"  [{_cargo_stamp()}] {message}", flush=True)


def cargo_step(message):
    """Announce the start of a step; returns the perf_counter start value."""
    if CARGO_DEBUG:
        print(f"  [{_cargo_stamp()}] >> {message}", flush=True)
    return _cargo_time.perf_counter()


def cargo_done(message, started, status="ok", **fields):
    """
    Close a step opened by cargo_step()/cargo_timer() and record it.

    `fields` are extra key=value pairs stored alongside the timing, e.g.
    cargo_done("detect", t0, objects=3, source="zip") -> 1.204s.
    """
    seconds = _cargo_time.perf_counter() - started
    record = {"name": message, "seconds": seconds, "status": status}
    record.update(fields)
    CARGO_STEP_LOG.append(record)

    if CARGO_DEBUG:
        details = "  ".join(f"{key}={value}" for key, value in fields.items())
        mark = "[ok]" if status == "ok" else "[!!]"
        suffix = f"  [{details}]" if details else ""
        print(f"  [{_cargo_stamp()}] {mark} {message} "
              f"({seconds:.3f}s){suffix}", flush=True)
    return seconds


class cargo_timer:
    """
    Context manager that times a block and logs it:

        with cargo_timer("SAM predict", roi="FULL") as t:
            ...
            t.note = {"masks": 3}

    `t.note` is merged into the recorded/logged fields.
    """

    def __init__(self, name, **fields):
        self.name = name
        self.fields = dict(fields)
        self.note = {}

    def __enter__(self):
        self.started = cargo_step(self.name)
        return self

    def __exit__(self, exc_type, exc, tb):
        fields = dict(self.fields)
        if self.note:
            fields.update(self.note)
        status = "ok" if exc_type is None else f"error:{exc_type.__name__}"
        cargo_done(self.name, self.started, status=status, **fields)
        return False


class cargo_stage:
    """
    Thin tqdm wrapper for a known-length loop -- the "live progress bar".

        for img in cargo_stage("depth map", total=len(images)):
            ...
            stage.set_note("image 2")

    Falls back to a plain iterator when CARGO_PROGRESS=0 or tqdm is unavailable,
    so the loop body never has to care whether a bar was drawn.
    """

    def __init__(self, description, total=None, unit="it", leave=True):
        self.description = description
        self.total = total
        self.unit = unit
        self.leave = leave
        self._bar = None
        self.n = 0

    def __enter__(self):
        self.started = cargo_step(self.description)
        if CARGO_PROGRESS:
            try:
                self._bar = tqdm(total=self.total, desc=self.description,
                                 unit=self.unit, leave=self.leave,
                                 dynamic_ncols=True)
            except Exception:          # never let a bar break the pipeline
                self._bar = None
        if CARGO_DEBUG and self.total is not None:
            print(f"        ({self.total} {self.unit} to go)", flush=True)
        return self

    def __iter__(self):
        source = range(self.total) if self.total is not None else iter(())
        for item in source:
            yield item
            self.update()

    def update(self, amount=1):
        self.n += amount
        if self._bar is not None:
            self._bar.update(amount)

    def set_note(self, text):
        """Show a short status on the bar (ignored when there is no bar)."""
        if self._bar is not None:
            self._bar.set_postfix_str(str(text)[:40], refresh=True)

    def __exit__(self, exc_type, exc, tb):
        if self._bar is not None:
            self._bar.close()
        status = "ok" if exc_type is None else f"error:{exc_type.__name__}"
        cargo_done(self.description, self.started, status=status,
                   items=self.n, unit=self.unit)

# ------------------------------------------------------------
# Live whole-run progress bar + automatic per-cell timing
# ------------------------------------------------------------
# Registers IPython's pre_run_cell / post_run_cell events, so EVERY cell in the
# notebook is timed without editing it. The raw cell source carries the
# "# CELL nn - TITLE" banner, which is what gets logged.
#
# No IPython shell (headless harness) -> registration is skipped and the rest of
# the notebook still runs; only the automatic per-cell numbers are missing.

CARGO_BAR = None          # the live ipywidgets.HTML bar, or None
CARGO_RUN_BAR_CELL = 0    # cells finished so far


def _cargo_cell_title(raw_cell):
    """Pull the '# CELL nn - ...' banner out of a cell's source."""
    for line in (raw_cell or "").splitlines():
        stripped = line.strip().lstrip("#").strip()
        if stripped.upper().startswith("CELL "):
            return stripped[:70]
    return "unnamed cell"


def _cargo_render_bar(done, total, title, seconds):
    """(Re)draw the whole-run progress bar in place."""
    if CARGO_BAR is None:
        return
    try:
        from IPython.display import display
        fraction = (done / total) if total else 0.0
        minutes, secs = divmod(int(seconds), 60)
        CARGO_BAR.value = (
            f"<b>{title}</b><br>"
            f"{'█' * int(fraction * 24):<24} {done}/{total} cells "
            f"· elapsed {minutes}m {secs:02d}s"
        )
        display(CARGO_BAR, display_id=True)
    except Exception:
        CARGO_BAR = None


def _cargo_pre_run_cell(info):
    """pre_run_cell hook: stamp the start time and announce the cell."""
    info.cargo_started = _cargo_time.perf_counter()
    if CARGO_DEBUG:
        title = _cargo_cell_title(getattr(info, "raw_cell", ""))
        stamp = _cargo_stamp()
        print(f"\n[{stamp}] {'=' * 62}\n"
              f"[{stamp}] >>> {title}\n"
              f"[{stamp}] {'=' * 62}", flush=True)


def _cargo_post_run_cell(info):
    """post_run_cell hook: record + log the cell duration, advance the bar."""
    started = getattr(info, "cargo_started", None)
    if started is None:
        return

    global CARGO_RUN_BAR_CELL
    seconds = _cargo_time.perf_counter() - started
    title = _cargo_cell_title(getattr(info, "raw_cell", ""))
    error = (getattr(info, "error_before_exec", None)
             or getattr(info, "error_in_exec", None))

    CARGO_CELL_TIMINGS.append({
        "cell": title,
        "seconds": seconds,
        "status": "error" if error is not None else "ok",
        "error": f"{type(error).__name__}: {error}" if error is not None else None,
    })
    CARGO_RUN_BAR_CELL += 1

    if CARGO_DEBUG:
        mark = "[!!] ERROR" if error is not None else "[ok]"
        print(f"[{_cargo_stamp()}] {mark} {title} -- {seconds:.3f}s", flush=True)

    _cargo_render_bar(CARGO_RUN_BAR_CELL, CARGO_TOTAL_CELLS, title,
                      _cargo_time.perf_counter() - CARGO_RUN_START)

    # Persist after EVERY cell, so the artefacts on disk are always current and
    # a run stopped at CELL 10 still leaves a record. Silent on purpose -- the
    # line above is the user-facing signal. Without an IPython shell (the test
    # harness) this hook never fires and the explicit CELL 10 / 28 calls take
    # over, so no path loses its timings.
    if CARGO_LIVE_SAVE:
        try:
            cargo_save_timings(announce=False)
        except Exception:
            pass


def _cargo_install_hooks():
    """Wire the hooks + the live bar. Returns False without an IPython shell."""
    global CARGO_BAR

    try:
        from IPython import get_ipython
        shell = get_ipython()
    except Exception:
        shell = None
    if shell is None:
        return False

    if CARGO_PROGRESS:
        try:
            import ipywidgets
            from IPython.display import display
            CARGO_BAR = ipywidgets.HTML(value="<b>Cargo pipeline</b><br>starting...")
            display(CARGO_BAR)
        except Exception:
            CARGO_BAR = None

    try:
        # Re-running CELL 2 must not stack a second pair of hooks, which would
        # double every timing and every live save.
        for event, handler in (("pre_run_cell", _cargo_pre_run_cell),
                               ("post_run_cell", _cargo_post_run_cell)):
            try:
                shell.events.unregister(event, handler)
            except Exception:
                pass
            shell.events.register(event, handler)
    except Exception:
        return False
    return True


CARGO_HOOKS_ACTIVE = _cargo_install_hooks()


# ------------------------------------------------------------
# Durable timing artefacts: outputs/timings.json + .md + .csv
# ------------------------------------------------------------
# The on-screen tables live in the kernel and die with the session, so
# cargo_save_timings() persists them next to the other run artifacts:
#
#   outputs/timings.json       full structured record of the latest run
#   outputs/timing_report.md   human-readable tables (per cell / per phase)
#   outputs/timing_history.csv one row per cell per run (re-written, not
#                              duplicated, while the run is still going)
#
# It runs automatically after EVERY cell via the post_run_cell hook above, so
# the files are always current -- nothing has to reach CELL 10 or CELL 28
# first, and an interrupted run still leaves a usable record. Set
# CARGO_LIVE_SAVE=0 to fall back to saving only at CELL 10 / CELL 28.
#
# A partial run (stopped at CELL 10) and a full run (CELL 28) are labelled
# differently and never compared against each other.

#: Bumped when the JSON layout changes; readers can branch on it.
CARGO_TIMING_SCHEMA = 1

#: (label, first cell, last cell) used for the per-phase roll-up.
#: CELL 10 is the LAST cell of the detect/segment stage; CELL 11+ is the
#: measurement stage (calibration, depth, 3D, volume, weight).
CARGO_PHASES = (
    ("Setup", 1, 6),
    ("Detect + Segment", 7, 10),
    ("Measurement", 11, 999),
)


def _cargo_output_dir():
    """Directory for the timing artefacts; tolerates being called early."""
    try:
        return Path(globals().get("OUTPUT_DIR") or (PROJECT_DIR / "outputs"))
    except Exception:
        return Path.cwd() / "outputs"


def _cargo_cell_number(banner):
    """'CELL 9b - TITLE' -> 9. Returns None when the banner is not a CELL one."""
    import re
    match = re.search(r"CELL\s+(\d+)", banner or "")
    return int(match.group(1)) if match else None


def _cargo_phase_of(banner):
    number = _cargo_cell_number(banner)
    if number is None:
        return "Other"
    for label, low, high in CARGO_PHASES:
        if low <= number <= high:
            return label
    return "Other"


def cargo_timing_payload(label="full run"):
    """Build the complete structured record for the current run."""
    import time as _t
    elapsed = _t.perf_counter() - CARGO_RUN_START
    return {
        "schema_version": CARGO_TIMING_SCHEMA,
        "run_id": CARGO_RUN_ID,
        "run_label": label,
        "kind": "full" if _cargo_reached_last_cell() else "live",
        "generated_utc": _t.strftime("%Y-%m-%dT%H:%M:%SZ", _t.gmtime()),
        "hooks_active": bool(CARGO_HOOKS_ACTIVE),
        "total_seconds": round(elapsed, 4),
        "cells_timed": len(CARGO_CELL_TIMINGS),
        "cells": [
            {
                "index": index,
                "cell": record["cell"],
                "cell_number": _cargo_cell_number(record["cell"]),
                "phase": _cargo_phase_of(record["cell"]),
                "seconds": round(float(record["seconds"]), 4),
                "status": record["status"],
                "error": record.get("error"),
            }
            for index, record in enumerate(CARGO_CELL_TIMINGS, start=1)
        ],
        "steps": [
            {
                "name": record.get("name", "?"),
                "seconds": round(float(record.get("seconds", 0.0)), 4),
                "status": record.get("status", "ok"),
                "details": {
                    key: value for key, value in record.items()
                    if key not in {"name", "seconds", "status"}
                },
            }
            for record in CARGO_STEP_LOG
        ],
        # Cell 9/10's own per-object dashboard, kept alongside the new timings.
        "roi_timings": [
            {
                roi: {key: value for key, value in data.items() if key != "decode_times"}
                for roi, data in per_image.items()
            }
            for per_image in (globals().get("roi_timings_by_image") or [])
        ],
    }


def _cargo_render_markdown(payload):
    """Build the human-readable timing_report.md body."""
    lines = [
        "# Cargo pipeline — execution timing",
        "",
        f"- run id: `{payload['run_id']}`  (label: **{payload['run_label']}**)",
        f"- generated (UTC): {payload['generated_utc']}",
        f"- per-cell hook: {'active' if payload['hooks_active'] else 'inactive (no IPython shell)'}",
        f"- cells timed: {payload['cells_timed']} of {CARGO_TOTAL_CELLS}",
        f"- total: {payload['total_seconds']:.2f} s",
        "",
    ]

    if not payload["cells"]:
        lines += [
            "> No per-cell timings were recorded in this session.",
            "> Run inside Jupyter/VS Code so the CELL 2 hook can time each cell.",
            "",
        ]
    else:
        lines += ["## Time per cell", "",
                  "| # | CELL | PHASE | TIME | STATUS |",
                  "|---|------|-------|------|--------|"]
        for cell in payload["cells"]:
            lines.append(
                f"| {cell['index']} | {cell['cell'][:44]} | {cell['phase']} "
                f"| {cell['seconds']:.3f}s | {cell['status']} |")
        lines.append("")

        # --- per-phase roll-up ----------------------------------------------
        lines += ["## Time per phase", "", "| PHASE | CELLS | TOTAL | SHARE |",
                  "|---|---|---|---|"]
        for label, _low, _high in CARGO_PHASES:
            members = [c for c in payload["cells"] if c["phase"] == label]
            if not members:
                continue
            total = sum(c["seconds"] for c in members)
            share = (total / payload["total_seconds"] * 100.0) if payload["total_seconds"] else 0.0
            lines.append(f"| {label} | {len(members)} | {total:.3f}s | {share:.1f}% |")
        lines.append("")

    if payload["steps"]:
        lines += ["## Slowest steps (top 20)", "",
                  "| STEP | TIME | STATUS |", "|--------|------|--------|"]
        for step in sorted(payload["steps"], key=lambda s: -s["seconds"])[:20]:
            lines.append(
                f"| {step['name'][:44]} | {step['seconds']:.3f}s | {step['status']} |")
        lines.append("")

    if payload["roi_timings"]:
        lines += ["## Per-object ROI timings (CELL 9)", "",
                  "| IMAGE | ROI | OBJECTS | SOURCE | TOTAL |",
                  "|-------|-----|---------|--------|-------|"]
        for image_index, per_image in enumerate(payload["roi_timings"], start=1):
            for roi, data in per_image.items():
                lines.append(
                    f"| {image_index} | {roi} | {data.get('objects', 0)} "
                    f"| {str(data.get('source', '-'))[:24]} "
                    f"| {data.get('total_seconds', 0.0):.3f}s |")
        lines.append("")

    return "\n".join(lines) + "\n"


def _cargo_write_history(payload, path):
    """
    Merge this run's per-cell rows into the history CSV.

    Rows belonging to the CURRENT run are replaced (every live save re-emits the
    cells it already has) while every other run's rows are preserved, so the
    file grows once per run instead of once per save.
    """
    import csv

    fieldnames = ["run_id", "run_label", "generated_utc",
                  "cell_index", "cell", "phase", "seconds", "status"]

    kept = []
    if path.exists():
        with open(path, "r", newline="", encoding="utf-8") as handle:
            for row in csv.reader(handle):
                if not row or row[0] == "run_id":
                    continue
                if row[0] != payload["run_id"]:
                    kept.append(row)

    for cell in payload["cells"]:
        kept.append([
            payload["run_id"], payload["run_label"], payload["generated_utc"],
            str(cell["index"]), cell["cell"], cell["phase"],
            f"{cell['seconds']:.4f}", cell["status"],
        ])

    with open(path, "w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(fieldnames)
        writer.writerows(kept)


def _cargo_reached_last_cell():
    """True once the final pipeline cell (CELL 28) has been timed."""
    for record in CARGO_CELL_TIMINGS:
        number = _cargo_cell_number(record["cell"])
        if number is not None and number >= CARGO_LAST_CELL:
            return True
    return False


def cargo_auto_label(timed=None):
    """
    Honest label for a save made part-way through a run.

    Counting cells is not enough: CELL 2 installs the hook, so the notebook's
    first cell is never timed and the count can never reach CARGO_TOTAL_CELLS.
    Completion is therefore "did the run reach CELL 28?".
    """
    if _cargo_reached_last_cell():
        return "full run"
    return "live (%d cells)" % (len(CARGO_CELL_TIMINGS) if timed is None else timed)


def _cargo_run_kind(payload):
    """Coarse run class -- 'full' or 'live' -- used to gate comparisons."""
    if not payload:
        return None
    kind = payload.get("kind")
    if kind:
        return kind
    return "full" if payload.get("run_label") == "full run" else "live"


def _cargo_capture_previous():
    """
    Snapshot the PREVIOUS run's timings.json before this run overwrites it.

    Live saving rewrites timings.json after every cell, so the first save of the
    session is the last chance to keep the baseline. A file written by this same
    kernel session is not a baseline -- it is this run.
    """
    global CARGO_PREVIOUS_RUN, CARGO_PREVIOUS_CAPTURED
    if CARGO_PREVIOUS_CAPTURED:
        return
    CARGO_PREVIOUS_CAPTURED = True
    try:
        path = _cargo_output_dir() / "timings.json"
        if not path.exists():
            return
        record = json.loads(path.read_text(encoding="utf-8"))
        if record.get("run_id") == CARGO_RUN_ID:
            return
        CARGO_PREVIOUS_RUN = record
    except Exception:
        CARGO_PREVIOUS_RUN = None


def cargo_save_timings(label=None, announce=True):
    """
    Persist the run's timings to OUTPUT_DIR.

    Driven automatically by the CELL 2 post_run_cell hook, so the files on disk
    are current after EVERY cell -- nothing has to reach CELL 10 or CELL 28
    first, and a run that is interrupted still leaves a record behind.

    ``label=None`` auto-labels the save: "full run" once every cell has been
    timed, otherwise "live (n cells)". Never raises -- a telemetry write must
    not be able to break a working pipeline.
    """
    try:
        _cargo_capture_previous()
        if label is None:
            label = cargo_auto_label()
        payload = cargo_timing_payload(label)
        out_dir = _cargo_output_dir()
        out_dir.mkdir(parents=True, exist_ok=True)

        json_path = out_dir / "timings.json"
        md_path = out_dir / "timing_report.md"
        csv_path = out_dir / "timing_history.csv"

        json_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        md_path.write_text(_cargo_render_markdown(payload), encoding="utf-8")
        _cargo_write_history(payload, csv_path)

        if announce:
            print(f"  [{_cargo_stamp()}] [ok] timings saved [{label}] -> "
                  f"{json_path.name}, {md_path.name}, {csv_path.name} "
                  f"({payload['cells_timed']} cells, "
                  f"{payload['total_seconds']:.2f}s)", flush=True)
        return {
            "json": str(json_path), "markdown": str(md_path),
            "history": str(csv_path), "payload": payload,
        }
    except Exception as exc:                      # never break the pipeline
        print(f"  [!!] timing save failed: {type(exc).__name__}: {exc}", flush=True)
        return None


def cargo_compare_timings(current=None, previous=None):
    """
    Print a per-cell delta between this run and the previous one.

    Only runs of the same KIND are compared, so a partial run (stopped at
    CELL 10) is never diffed against a full one. Pass either payload
    explicitly, or omit them to use the baseline snapshotted at the start of
    this run and, failing that, the timings.json on disk.
    """
    if current is None:
        current = cargo_timing_payload()
    if previous is None:
        # Prefer the baseline snapshotted before this run's first live save: the
        # file on disk has already been overwritten by this run's own saves.
        previous = CARGO_PREVIOUS_RUN
    if previous is None:
        try:
            previous = json.loads(
                (_cargo_output_dir() / "timings.json").read_text(encoding="utf-8"))
        except Exception:
            previous = None

    # The guard applies to an explicitly passed baseline too: a run that never
    # reached the last cell must never be diffed against a complete one.
    if previous and _cargo_run_kind(previous) != _cargo_run_kind(current):
        cargo_note(f"skipping comparison: previous run is "
                   f"'{previous.get('run_label')}', current is '{current['run_label']}'")
        return False

    if not previous:
        cargo_note("no previous run with the same label to compare against")
        return False

    before = {c["cell"]: c["seconds"] for c in previous.get("cells", [])}
    rows = []
    for cell in current["cells"]:
        if cell["cell"] not in before:
            continue
        old, new = before[cell["cell"]], cell["seconds"]
        delta = new - old
        pct = (delta / old * 100.0) if old > 1e-9 else (100.0 if new > 0 else 0.0)
        rows.append((cell["cell"], old, new, delta, pct))

    print("\n" + "=" * 74)
    print(f"TIMING COMPARISON  {previous['run_id']}  ->  {current['run_id']}  "
          f"({current['run_label']})")
    print("=" * 74)
    print(f"{'CELL':<44} {'PREV':>9} {'NOW':>9} {'DELTA':>9} {'%':>8}")
    print("-" * 74)
    for name, old, new, delta, pct in rows:
        print(f"{name[:44]:<44} {old:>8.3f}s {new:>8.3f}s {delta:>+8.3f}s {pct:>+7.1f}%")
    print("-" * 74)
    old_total = sum(before.values())
    new_total = sum(c["seconds"] for c in current["cells"])
    print(f"{'TOTAL (cells only)':<44} {old_total:>8.3f}s {new_total:>8.3f}s "
          f"{new_total - old_total:>+8.3f}s")
    print("=" * 74)
    return True


def cargo_timing_report(partial=False):
    """Print the per-cell and per-step timing tables collected so far."""
    elapsed = _cargo_time.perf_counter() - CARGO_RUN_START
    minutes, seconds = divmod(int(elapsed), 60)

    print("\n" + "=" * 74)
    if partial:
        print("EXECUTION TIME PER CELL  (partial — run to CELL 28 for the full profile)")
    else:
        print("EXECUTION TIME PER CELL")
    print("=" * 74)
    print(f"{'#':>3}  {'CELL':<46} {'TIME':>10}  STATUS")
    print("-" * 74)
    for index, record in enumerate(CARGO_CELL_TIMINGS, start=1):
        print(f"{index:>3}  {record['cell'][:46]:<46} "
              f"{record['seconds']:>9.3f}s  {record['status']}")
    print("-" * 74)
    hook_note = "" if CARGO_HOOKS_ACTIVE else "   (per-cell hook inactive: no IPython shell)"
    print(f"total: {len(CARGO_CELL_TIMINGS)} cells in "
          f"{minutes}m {seconds:02d}s{hook_note}")
    print("=" * 74)

    if not CARGO_STEP_LOG:
        return

    print("\nSLOWEST STEPS (top 15)")
    print(f"{'STEP':<46} {'TIME':>10}")
    print("-" * 74)
    for record in sorted(CARGO_STEP_LOG, key=lambda r: -r["seconds"])[:15]:
        print(f"{record['name'][:46]:<46} {record['seconds']:>9.3f}s")
    print("=" * 74)


if CARGO_DEBUG:
    print(f"Telemetry: debug={CARGO_DEBUG} progress={CARGO_PROGRESS} "
          f"(set CARGO_DEBUG=0 / CARGO_PROGRESS=0 to quiet)")
    print(f"Live bar + per-cell timing: "
          f"{'ACTIVE' if CARGO_HOOKS_ACTIVE else 'unavailable (no IPython shell)'}")
