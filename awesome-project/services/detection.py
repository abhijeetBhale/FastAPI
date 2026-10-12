"""Bridge to the cargo detection pipeline.

The detector cannot be imported here. Its dependencies (torch, ultralytics,
segment-anything, transformers, Open3D) live in a second virtualenv that this
app does not have, and installing them into this one would add gigabytes to an
API that otherwise needs neither. So the pipeline runs as a subprocess and the
two sides meet at a JSON file.

    FastAPI  ──subprocess──>  scripts/detect_runner.py  ──>  awesome-project's
                                     │                      detection venv
                                     └── result.json ──────────┘

Three things this module is careful about:

1. **The notebook is not reentrant.** `scripts/detect_runner.py` redirects the
   pipeline's `OUTPUT_DIR` to a unique directory per run, but the notebook also
   writes timings to its own `outputs/`. A semaphore caps concurrent runs rather
   than letting two requests interleave into the same files.

2. **A refusal is a success.** "No cargo in this image" is a correct answer to
   the question, not an error. It comes back as `detected: false` with a 200,
   so the caller never has to distinguish "the pipeline failed" from "the
   pipeline said no".

3. **Timeouts are reported, not hidden.** A run killed at the timeout still
   writes a result file describing what happened, and that file is returned.
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
import sys
import threading
import uuid
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

from config import get_settings

logger = logging.getLogger("app.detection")

#: The runner script, resolved relative to the project root so it moves with
#: the repo rather than depending on the caller's cwd.
RUNNER_SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "detect_runner.py"

#: Working directory for one run. Overridden per call; kept module-level so the
#: location is obvious in one place.
WORK_ROOT = Path(__file__).resolve().parent.parent / "storage" / "detection"

#: Pipeline stdout is chatty (telemetry tables, warnings, progress remnants).
#: Capped so a runaway notebook cannot exhaust memory; the tail is kept because
#: that is where a traceback appears.
MAX_CAPTURED_OUTPUT = 64_000

#: One run at a time by default. The notebook's cells share module-level state
#: and write into a shared project directory, so overlapping runs would race.
_run_lock = threading.Semaphore(get_settings().detection_max_concurrency)


class DetectionUnavailable(RuntimeError):
    """The detector cannot be run — not configured, or its project is missing."""


class DetectionTimeout(RuntimeError):
    """The detector exceeded its time budget."""


@dataclass
class DetectionRun:
    """The outcome of one detection run."""

    result: dict[str, Any]
    overlay_path: Optional[Path]
    run_dir: Path
    stdout_tail: str
    returncode: int


def is_available() -> tuple[bool, str]:
    """Return `(usable, reason)`. `reason` explains a False verdict."""
    settings = get_settings()

    if not settings.detection_enabled:
        return False, "Detection is disabled. Set DETECTION_ENABLED=true in .env."

    if not Path(settings.detection_python).is_file():
        return False, (
            f"Detector interpreter not found: {settings.detection_python}. "
            f"Point DETECTION_PYTHON at the detection project's python.exe."
        )

    notebook = Path(settings.detection_project_dir) / "Revamping.ipynb"
    if not notebook.is_file():
        return False, (
            f"Detection notebook not found: {notebook}. Point "
            f"DETECTION_PROJECT_DIR at the folder containing Revamping.ipynb."
        )

    if not RUNNER_SCRIPT.is_file():
        return False, f"Runner script missing: {RUNNER_SCRIPT}"

    return True, "ready"


def run_detection(image_path: Path, *, timeout: int | None = None) -> DetectionRun:
    """Run the pipeline on one image and return its parsed result.

    Raises `DetectionUnavailable` if the detector is not configured, and
    `DetectionTimeout` if it overran. Any other failure is still returned as a
    result with `ok: false`, because the runner catches pipeline exceptions and
    writes them to disk — a broken image must surface as data, not a traceback.
    """
    settings = get_settings()
    usable, reason = is_available()
    if not usable:
        raise DetectionUnavailable(reason)

    if not Path(image_path).is_file():
        raise FileNotFoundError(f"Image not found: {image_path}")

    limit = timeout if timeout is not None else settings.detection_timeout
    run_dir = WORK_ROOT / f"run_{datetime.now():%Y%m%d_%H%M%S}_{uuid.uuid4().hex[:8]}"
    run_dir.mkdir(parents=True, exist_ok=True)

    env = dict(os.environ)
    env["CARGO_PROJECT_DIR"] = settings.detection_project_dir
    # Silences the telemetry progress bars so the captured output stays readable.
    env.setdefault("CARGO_DEBUG", "0")
    env.setdefault("CARGO_PROGRESS", "0")
    env.setdefault("MPLBACKEND", "Agg")

    cmd = [
        settings.detection_python,
        str(RUNNER_SCRIPT),
        "--image", str(image_path),
        "--out-dir", str(run_dir),
    ]

    logger.info("detection: starting run %s", run_dir.name)
    started = datetime.now()

    if not _run_lock.acquire(blocking=False):
        raise DetectionUnavailable(
            "A detection run is already in progress. This detector runs one "
            "image at a time; retry in a moment."
        )

    try:
        completed = subprocess.run(
            cmd,
            env=env,
            capture_output=True,
            text=True,
            timeout=limit,
            # The notebook anchors every relative path to its cwd.
            cwd=settings.detection_project_dir,
        )
        returncode = completed.returncode
        output = (completed.stdout or "") + (completed.stderr or "")
    except subprocess.TimeoutExpired as exc:
        # Kill is handled by subprocess.run on timeout, but the child may have
        # spawned torch worker processes that outlive it. Recording the fact is
        # more useful than pretending the run simply took longer.
        stdout = exc.stdout or ""
        if isinstance(stdout, bytes):
            stdout = stdout.decode("utf-8", "replace")
        _record_timeout(run_dir, started, limit, stdout)
        raise DetectionTimeout(
            f"Detection exceeded {limit}s and was stopped. The pipeline runs "
            f"16-45 s per image on CPU; raise DETECTION_TIMEOUT if this is normal."
        ) from exc
    except OSError as exc:
        raise DetectionUnavailable(
            f"Could not start the detector: {exc}"
        ) from exc
    finally:
        _run_lock.release()

    elapsed = (datetime.now() - started).total_seconds()
    tail = output[-MAX_CAPTURED_OUTPUT:]

    result_file = run_dir / "result.json"
    if not result_file.is_file():
        # The runner writes result.json even on internal failure, so its absence
        # means the process died before it could — most often a missing
        # dependency in the detection venv.
        logger.error("detection: no result.json in %s (rc=%s)", run_dir, returncode)
        result = {
            "ok": False,
            "error": f"Detector exited with code {returncode} without a result.",
            "elapsed_seconds": round(elapsed, 2),
        }
    else:
        try:
            result = json.loads(result_file.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            logger.error("detection: unreadable result.json in %s", run_dir)
            result = {
                "ok": False,
                "error": f"Detector wrote an unreadable result: {exc}",
                "elapsed_seconds": round(elapsed, 2),
            }

    # Recorded so the log endpoint can find this run's stdout later. The
    # directory name cannot be reconstructed from the overlay filename: both
    # draw a fresh uuid4 independently.
    result["run_dir"] = run_dir.name

    # A killed-by-timeout child can leave the lock free while still running, so
    # the outcome is only logged once the process is genuinely gone.
    logger.info(
        "detection: run %s finished ok=%s detected=%s in %.1fs",
        run_dir.name, result.get("ok"), result.get("detected"), elapsed,
    )
    if not result.get("ok"):
        logger.warning("detection: run %s error: %s", run_dir.name,
                       result.get("error"))

    overlay = run_dir / "overlay.png"

    return DetectionRun(
        result=result,
        overlay_path=overlay if overlay.is_file() else None,
        run_dir=run_dir,
        stdout_tail=tail,
        returncode=returncode,
    )


def _record_timeout(run_dir: Path, started: datetime, limit: int, stdout: str) -> None:
    """Leave a result file behind for a killed run, so nothing is lost."""
    payload = {
        "ok": False,
        "error": f"Detection timed out after {limit}s.",
        "timed_out": True,
        "detected": False,
        "elapsed_seconds": limit,
        "started_at": started.isoformat(),
        "run_dir": run_dir.name,
    }
    (run_dir / "result.json").write_text(
        json.dumps(payload, indent=2), encoding="utf-8"
    )
    if stdout:
        (run_dir / "stdout.log").write_text(
            stdout[-MAX_CAPTURED_OUTPUT:], encoding="utf-8"
        )


def run_stdout_log(run_dir_name: str) -> str:
    """Return the stdout tail for a stored run, or '' if it has been swept.

    The runner inherits stdout rather than capturing it, so the traceback for a
    failed run exists nowhere but the console — this persists it. It is only
    written for a killed run; a completed run's diagnostics live in result.json.
    """
    if not run_dir_name or Path(run_dir_name).name != run_dir_name:
        return ""      # reject anything that is not a bare directory name
    log = WORK_ROOT / run_dir_name / "stdout.log"
    if not log.is_file():
        return ""
    return log.read_text(encoding="utf-8", errors="replace")


def persist_overlay(run: DetectionRun, inspection_id: int) -> str | None:
    """Copy the run's overlay into `storage/detection/` and return its filename.

    Returns None when there is no overlay — a refusal produces the unmodified
    image, which is not worth storing a second copy of.
    """
    if run.overlay_path is None:
        return None

    storage = WORK_ROOT / "overlays"
    storage.mkdir(parents=True, exist_ok=True)
    filename = f"inspection_{inspection_id}_{uuid.uuid4().hex[:8]}.png"
    shutil.copyfile(run.overlay_path, storage / filename)
    return filename


def overlay_path_for(filename: str) -> Path:
    """Resolve a stored overlay filename to a path, refusing traversal."""
    candidate = (WORK_ROOT / "overlays" / filename).resolve()
    root = (WORK_ROOT / "overlays").resolve()
    # `filename` comes from the database, but a defence in depth costs one
    # comparison and turns a stored "../.." from a file read into a 404.
    if not candidate.is_relative_to(root):
        raise ValueError(f"Refusing path outside the overlay store: {filename}")
    return candidate


def cleanup_runs(keep: int = 20) -> int:
    """Delete the oldest run directories, keeping the newest `keep`.

    Each run holds the overlay, the redirected `outputs/` copy and the logs.
    Nothing removes them automatically, so an unattended server would otherwise
    fill the disk a few hundred uploads at a time.
    """
    if not WORK_ROOT.exists():
        return 0
    runs = sorted(
        (p for p in WORK_ROOT.glob("run_*") if p.is_dir()),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    removed = 0
    for stale in runs[keep:]:
        try:
            shutil.rmtree(stale)
            removed += 1
        except OSError as exc:
            logger.warning("detection: could not remove %s: %s", stale.name, exc)
    if removed:
        logger.info("detection: removed %d stale run directories", removed)
    return removed


if __name__ == "__main__":       # pragma: no cover - manual availability check
    ok, why = is_available()
    print(f"available: {ok}\n{why}")
    sys.exit(0 if ok else 1)
