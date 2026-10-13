"""Cargo detection integration.

The real detector takes 16-45 s per image and lives in a 5.5 GB second
virtualenv, so these tests never run it. They pin everything around it: the
subprocess contract, the HTTP semantics, and the authorisation rules — all of
which are where a regression would actually hurt.

`run_detection` is monkeypatched throughout. The seam is narrow and deliberate:
if you change how the runner is invoked, `TestRunnerContract` is the test that
should fail.

The split that matters:

* a **refusal** (`detected: false`) is a *success* — 200, result stored;
* a **broken detector** is a *failure* — 502, and nothing claims it worked;
* **disabled or misconfigured** is *unavailable* — 503, before any work starts.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from services import detection


# ---- fakes ---------------------------------------------------------------
DETECTED_RESULT = {
    "ok": True,
    "detected": True,
    "label": "Cargo-Box",
    "score": 16.3,
    "box_px": [52.0, 287.0, 196.0, 459.0],
    "box_width_px": 144.0,
    "box_height_px": 172.0,
    "box_fraction_of_frame": 0.10,
    "border_leak": 0.0,
    "mask_area_ratio": 0.068,
    "object_count": 2,
    "objects": [
        {
            "label": "Cargo-Box",
            "yolo_confidence": 0.83,
            "sam_score": 0.93,
            "mask_area_px": 17051,
            "box_px": [52.0, 287.0, 196.0, 459.0],
        },
        {
            "label": "Cargo-Box",
            "yolo_confidence": 0.44,
            "sam_score": 0.94,
            "mask_area_px": 29188,
            "box_px": [260.0, 215.0, 444.0, 439.0],
        },
    ],
    "image_width": 500,
    "image_height": 500,
    "detector_origin": "zip_trained_obb",
    "uses_zip_taxonomy": True,
    "overlay": "somewhere/overlay.png",
    "stage": "detection_and_segmentation",
    "elapsed_seconds": 24.4,
}

REFUSED_RESULT = {
    "ok": True,
    "detected": False,
    "reason": "below_acceptance_gate",
    "label": None,
    "score": 3.3,
    "object_count": 0,
    "objects": [],
    "elapsed_seconds": 18.1,
}

FAILED_RESULT = {
    "ok": False,
    "detected": False,
    "error": "AttributeError: 'NoneType' object has no attribute 'shape'",
    "elapsed_seconds": 3.2,
}


@pytest.fixture
def authed(client):
    """A signed-in plain user. The `client` fixture starts signed *out*."""
    client.post("/auth/register", json={"name": "Ana", "email": "ana@example.com",
                                        "password": "quay-crane-42"})
    return client


@pytest.fixture(autouse=True)
def _isolated_work_root(tmp_path, monkeypatch):
    """Redirect the detector's working directory into a temp folder.

    Without this, the suite writes overlays and `run_*` directories into the
    real `storage/detection/`, so a test run would leave files that the next
    `cleanup_runs` then deletes — and could serve someone else's stored overlay.
    """
    root = tmp_path / "detection"
    root.mkdir()
    monkeypatch.setattr(detection, "WORK_ROOT", root)
    return root


@pytest.fixture
def submission(client, png_bytes):
    """A submission owned by the signed-in client."""
    client.post("/auth/register", json={"name": "Ana", "email": "ana@example.com",
                                        "password": "quay-crane-42"})
    r = client.post("/portal/submissions", data={"cargo_type": "scrap-steel"},
                    files={"image": ("c.png", png_bytes(), "image/png")})
    assert r.status_code == 201, r.text
    return r.json()


@pytest.fixture
def fake_run(monkeypatch):
    """Replace the subprocess bridge with a stub returning `result`.

    Defaults to a successful detection. Pass `overlay=None` for a refusal —
    CELL 10 draws no box when nothing passes the gate.
    """
    def _install(result=None, *, overlay=True, returncode=0):
        result = DETECTED_RESULT if result is None else result
        calls: list[dict] = []

        def fake(image_path: Path, **kwargs):
            calls.append({"image": Path(image_path), **kwargs})
            overlay_path = None
            if overlay:
                run_dir = detection.WORK_ROOT / "run_fake"
                run_dir.mkdir(parents=True, exist_ok=True)
                overlay_path = run_dir / "overlay.png"
                overlay_path.write_bytes(b"\x89PNG\r\n\x1a\nfake")
            return detection.DetectionRun(
                result=dict(result),
                overlay_path=overlay_path,
                run_dir=detection.WORK_ROOT / "run_fake",
                stdout_tail="[runner] OK",
                returncode=returncode,
            )

        monkeypatch.setattr(detection, "run_detection", fake)
        return calls

    return _install


@pytest.fixture
def enabled(monkeypatch):
    """Pretend the detector is configured and present."""
    monkeypatch.setattr(detection, "is_available", lambda: (True, "ready"))
    monkeypatch.setattr(
        detection, "persist_overlay",
        lambda run, insp_id: (f"inspection_{insp_id}_abc12345.png" if run.overlay_path
                              else None),
    )


def as_other_user(client):
    client.post("/auth/logout")
    client.cookies.clear()
    client.post("/auth/register", json={"name": "Bo", "email": "bo@example.com",
                                        "password": "quay-crane-42"})


# ---- availability --------------------------------------------------------
class TestAvailability:
    def test_disabled_is_reported_as_such(self, authed, monkeypatch):
        """Must not assert on whatever `.env` happens to say — the test controls
        the setting, so it means the same thing on every machine."""
        from config import get_settings

        monkeypatch.setattr(get_settings(), "detection_enabled", False)
        r = authed.get("/portal/detection/availability")
        assert r.status_code == 200
        assert r.json()["enabled"] is False
        assert r.json()["available"] is False
        assert "DETECTION_ENABLED" in r.json()["reason"]

    def test_the_default_is_off(self):
        """A fresh install must not change the upload path until someone opts
        in, so the shipped default matters."""
        from config import Settings

        assert Settings(_env_file=None).detection_enabled is False

    def test_availability_needs_a_session(self, client):
        client.cookies.clear()
        assert client.get("/portal/detection/availability").status_code == 401

    def test_measurement_is_advertised_as_unavailable(self, authed, monkeypatch):
        """The volume/weight columns stay null; the API must say so rather than
        letting a caller assume they are coming."""
        monkeypatch.setattr(detection, "is_available", lambda: (True, "ready"))
        body = authed.get("/portal/detection/availability").json()
        assert body["available"] is True
        assert body["supports_measurement"] is False

    def test_a_missing_interpreter_is_explained(self, monkeypatch):
        from config import get_settings

        settings = get_settings()
        monkeypatch.setattr(settings, "detection_enabled", True)
        monkeypatch.setattr(settings, "detection_python", r"Z:\nope\python.exe")
        ok, why = detection.is_available()
        assert ok is False
        assert "Detector interpreter not found" in why

    def test_a_missing_notebook_is_explained(self, monkeypatch):
        from config import get_settings

        settings = get_settings()
        monkeypatch.setattr(settings, "detection_enabled", True)
        monkeypatch.setattr(settings, "detection_project_dir", r"Z:\nope")
        ok, why = detection.is_available()
        assert ok is False
        assert "Revamping.ipynb" in why


# ---- running detection ---------------------------------------------------
class TestDetect:
    def test_detect_stores_and_returns_the_report(self, client, submission,
                                                  fake_run, enabled):
        fake_run()
        r = client.post(f"/portal/submissions/{submission['id']}/detect")

        assert r.status_code == 200, r.text
        body = r.json()
        assert body["ok"] is True
        assert body["detected"] is True
        assert body["status"] == "detected"
        assert body["label"] == "Cargo-Box"
        assert body["object_count"] == 2
        assert len(body["objects"]) == 2
        assert body["objects"][0]["yolo_confidence"] == 0.83
        assert body["inspection_id"] == submission["id"]

    def test_the_report_is_persisted(self, client, submission, fake_run, enabled,
                                     db):
        """The result must survive the request — a GET has to find it."""
        from models.inspection import Inspection

        fake_run()
        client.post(f"/portal/submissions/{submission['id']}/detect")

        insp = db.get(Inspection, submission["id"])
        assert insp.detection_result is not None
        assert insp.detected_at is not None
        assert insp.detection_overlay is not None
        assert insp.detection_result["label"] == "Cargo-Box"

    def test_measurement_columns_stay_null(self, client, submission, fake_run,
                                           enabled, db):
        """The pipeline's volume is relative, not metric. Writing it into a
        column named `volume_m3` would be a silent lie."""
        from models.inspection import Inspection

        fake_run()
        client.post(f"/portal/submissions/{submission['id']}/detect")
        insp = db.get(Inspection, submission["id"])
        assert insp.volume_m3 is None
        assert insp.estimated_weight_kg is None

    def test_a_refusal_is_a_success(self, client, submission, fake_run, enabled):
        """'No cargo here' is a correct answer, so it is 200 with detected:false
        — not an error the caller has to special-case."""
        fake_run(REFUSED_RESULT, overlay=False)
        r = client.post(f"/portal/submissions/{submission['id']}/detect")

        assert r.status_code == 200, r.text
        body = r.json()
        assert body["ok"] is True
        assert body["detected"] is False
        assert body["status"] == "no_cargo"
        assert body["reason"] == "below_acceptance_gate"
        assert body["has_overlay"] is False
        assert body["overlay_url"] is None

    def test_a_refusal_is_still_persisted(self, client, submission, fake_run,
                                           enabled, db):
        """'Ran, found nothing' must not be mistaken for 'never ran'."""
        from models.inspection import Inspection

        fake_run(REFUSED_RESULT, overlay=False)
        client.post(f"/portal/submissions/{submission['id']}/detect")
        insp = db.get(Inspection, submission["id"])
        assert insp.detection_result is not None
        assert insp.detected_at is not None

    def test_a_broken_detector_is_502_and_still_recorded(self, client, submission,
                                                         fake_run, enabled, db):
        """A 200 here would tell the caller the detection worked. It did not."""
        from models.inspection import Inspection

        fake_run(FAILED_RESULT, overlay=False)
        r = client.post(f"/portal/submissions/{submission['id']}/detect")

        assert r.status_code == 502
        detail = r.json()["detail"]
        assert detail["code"] == "detection_failed"
        # The failure is kept, so it can be inspected rather than vanishing.
        insp = db.get(Inspection, submission["id"])
        assert insp.detection_result is not None
        assert insp.detection_result["ok"] is False

    def test_unavailable_is_503_before_any_work(self, client, submission,
                                                monkeypatch):
        """Must not depend on the local `.env`, and must never reach the
        subprocess: a disabled detector has to fail before spawning anything."""
        calls: list = []
        monkeypatch.setattr(
            detection, "is_available",
            lambda: (False, "Detection is disabled. Set DETECTION_ENABLED=true "
                            "in .env."),
        )
        monkeypatch.setattr(detection, "run_detection",
                            lambda *a, **k: calls.append(a))

        r = client.post(f"/portal/submissions/{submission['id']}/detect")
        assert r.status_code == 503
        assert r.json()["detail"]["code"] == "detection_unavailable"
        assert "DETECTION_ENABLED" in r.json()["detail"]["message"]
        assert calls == [], "a disabled detector must not be invoked"

    def test_a_second_run_is_cached(self, client, submission, fake_run, enabled):
        """Re-running costs 30 s of CPU to recompute an unchanged answer."""
        calls = fake_run()
        client.post(f"/portal/submissions/{submission['id']}/detect")
        client.post(f"/portal/submissions/{submission['id']}/detect")
        assert len(calls) == 1

    def test_force_reruns(self, client, submission, fake_run, enabled):
        """Needed after the weights or the notebook change."""
        calls = fake_run()
        client.post(f"/portal/submissions/{submission['id']}/detect")
        client.post(f"/portal/submissions/{submission['id']}/detect?force=true")
        assert len(calls) == 2

    def test_a_timeout_is_504(self, client, submission, monkeypatch, enabled):
        def boom(image_path, **kwargs):
            raise detection.DetectionTimeout("Detection exceeded 300s")

        monkeypatch.setattr(detection, "run_detection", boom)
        r = client.post(f"/portal/submissions/{submission['id']}/detect")
        assert r.status_code == 504
        assert r.json()["detail"]["code"] == "detection_timeout"

    def test_a_busy_detector_is_503(self, client, submission, monkeypatch, enabled):
        """The notebook is not reentrant, so overlap must be refused not raced."""
        def busy(image_path, **kwargs):
            raise detection.DetectionUnavailable("A detection run is already "
                                                 "in progress.")

        monkeypatch.setattr(detection, "run_detection", busy)
        r = client.post(f"/portal/submissions/{submission['id']}/detect")
        assert r.status_code == 503
        assert r.json()["detail"]["code"] == "detection_busy"

    def test_a_missing_image_file_is_404(self, client, submission, fake_run,
                                         enabled, db):
        """The row exists but the bytes are gone — not worth a 30 s run."""
        from models.inspection import Inspection
        from services.inspection_service import resolve_image_path

        insp = db.get(Inspection, submission["id"])
        calls = fake_run()
        resolve_image_path(insp).unlink()

        r = client.post(f"/portal/submissions/{submission['id']}/detect")
        assert r.status_code == 404
        assert len(calls) == 0

    def test_an_unknown_submission_is_404(self, client, submission, fake_run,
                                          enabled):
        fake_run()
        assert client.post("/portal/submissions/99999/detect").status_code == 404


# ---- reading results -----------------------------------------------------
class TestReadDetection:
    def test_get_before_any_run_is_not_run(self, client, submission):
        r = client.get(f"/portal/submissions/{submission['id']}/detection")
        assert r.status_code == 200
        body = r.json()
        assert body["status"] == "not_run"
        assert body["ok"] is False
        assert body["object_count"] == 0

    def test_get_never_starts_a_run(self, client, submission, fake_run, enabled):
        """Reading a result must be cheap; only POST may burn CPU."""
        calls = fake_run()
        client.get(f"/portal/submissions/{submission['id']}/detection")
        assert len(calls) == 0

    def test_get_after_a_run_returns_it(self, client, submission, fake_run,
                                        enabled):
        fake_run()
        client.post(f"/portal/submissions/{submission['id']}/detect")
        body = client.get(
            f"/portal/submissions/{submission['id']}/detection").json()
        assert body["status"] == "detected"
        assert body["label"] == "Cargo-Box"

    def test_the_list_view_carries_the_detection_state(self, client, submission,
                                                       fake_run, enabled):
        """The card grid must show 'not analysed' without a second request."""
        fake_run()
        client.post(f"/portal/submissions/{submission['id']}/detect")

        items = client.get("/portal/submissions").json()["items"]
        assert items[0]["detection_status"] == "detected"
        assert items[0]["cargo_object_count"] == 2
        assert items[0]["detected_at"] is not None

    def test_a_refusal_shows_no_cargo_not_not_run(self, client, submission,
                                                  fake_run, enabled):
        """These are different facts and the UI must be able to tell them."""
        fake_run(REFUSED_RESULT, overlay=False)
        client.post(f"/portal/submissions/{submission['id']}/detect")
        items = client.get("/portal/submissions").json()["items"]
        assert items[0]["detection_status"] == "no_cargo"
        assert items[0]["cargo_object_count"] == 0

    def test_the_list_omits_the_bulk_report(self, client, submission, fake_run,
                                            enabled):
        """A report can hold dozens of boxes; it would bloat every list call."""
        fake_run()
        client.post(f"/portal/submissions/{submission['id']}/detect")
        items = client.get("/portal/submissions").json()["items"]
        assert "objects" not in items[0]
        assert "detection_result" not in items[0]


# ---- overlay -------------------------------------------------------------
class TestOverlay:
    def test_overlay_is_served_when_detection_succeeded(self, client, submission,
                                                        fake_run, enabled,
                                                        monkeypatch):
        """The stored overlay must actually be servable, not just recorded."""
        overlays = detection.WORK_ROOT / "overlays"
        overlays.mkdir(parents=True, exist_ok=True)
        # `persist_overlay` is stubbed by the `enabled` fixture and derives the
        # name from the real inspection id, so the file on disk must use that
        # same id — hardcoding one here would 404 for every id but 1.
        name = f"inspection_{submission['id']}_abc12345.png"
        (overlays / name).write_bytes(b"\x89PNG\r\n\x1a\noverlay")
        monkeypatch.setattr(
            detection, "overlay_path_for", lambda filename: overlays / filename
        )

        fake_run()
        body = client.post(
            f"/portal/submissions/{submission['id']}/detect").json()
        assert body["has_overlay"] is True
        assert body["overlay_url"].endswith("/detection/overlay")

        png = client.get(body["overlay_url"])
        assert png.status_code == 200, png.text
        assert png.headers["content-type"] == "image/png"

    def test_no_overlay_for_a_refusal(self, client, submission, fake_run, enabled):
        """CELL 10 draws no box when the gate rejects everything, so there is
        nothing to serve."""
        fake_run(REFUSED_RESULT, overlay=False)
        client.post(f"/portal/submissions/{submission['id']}/detect")
        r = client.get(
            f"/portal/submissions/{submission['id']}/detection/overlay")
        assert r.status_code == 404

    def test_path_traversal_is_refused(self):
        """`filename` comes from the database, so it is one `..` away from
        reading any file the app can."""
        for bad in ("../../../../etc/passwd", "..\\..\\secret.png"):
            with pytest.raises(ValueError):
                detection.overlay_path_for(bad)

    def test_run_stdout_log_rejects_a_traversal(self):
        for bad in ("../../secrets", "..\\..\\secrets"):
            assert detection.run_stdout_log(bad) == ""


# ---- authorisation -------------------------------------------------------
class TestAuthorisation:
    def test_detect_requires_a_session(self, client, submission):
        client.cookies.clear()
        assert client.post(
            f"/portal/submissions/{submission['id']}/detect").status_code == 401

    def test_another_users_submission_is_404_not_403(self, client, submission,
                                                      fake_run, enabled):
        """403 would confirm the id exists, letting anyone walk the id space."""
        fake_run()
        as_other_user(client)
        r = client.post(f"/portal/submissions/{submission['id']}/detect")
        assert r.status_code == 404

    def test_another_user_cannot_read_the_result(self, client, submission,
                                                 fake_run, enabled):
        fake_run()
        client.post(f"/portal/submissions/{submission['id']}/detect")
        as_other_user(client)
        assert client.get(
            f"/portal/submissions/{submission['id']}/detection").status_code == 404

    def test_another_user_cannot_read_the_overlay(self, client, submission,
                                                  fake_run, enabled):
        fake_run()
        client.post(f"/portal/submissions/{submission['id']}/detect")
        as_other_user(client)
        assert client.get(
            f"/portal/submissions/{submission['id']}/detection/overlay"
        ).status_code == 404

    def test_another_user_cannot_read_the_log(self, client, submission,
                                              fake_run, enabled):
        fake_run()
        client.post(f"/portal/submissions/{submission['id']}/detect")
        as_other_user(client)
        assert client.get(
            f"/portal/submissions/{submission['id']}/detection/log"
        ).status_code == 404

    def test_an_admin_can_read_any_result(self, client, admin_client,
                                          submission, fake_run, enabled):
        """Admins review a queue, so they must see what the detector said."""
        fake_run()
        client.post(f"/portal/submissions/{submission['id']}/detect")

        r = admin_client.get(
            f"/admin/submissions/{submission['id']}/detection")
        assert r.status_code == 200, r.text
        assert r.json()["status"] == "detected"

    def test_a_non_admin_cannot_use_the_admin_route(self, client, submission,
                                                    fake_run, enabled):
        fake_run()
        client.post(f"/portal/submissions/{submission['id']}/detect")
        assert client.get(
            f"/admin/submissions/{submission['id']}/detection").status_code == 403

    def test_the_admin_route_never_starts_a_run(self, client, admin_client,
                                                submission, fake_run, enabled):
        """Read-only by design: an admin working a queue must not be able to
        spend 30 s of CPU per row."""
        calls = fake_run()
        client.post(f"/portal/submissions/{submission['id']}/detect")
        before = len(calls)
        admin_client.get(f"/admin/submissions/{submission['id']}/detection")
        assert len(calls) == before

    def test_the_admin_route_reports_not_run_rather_than_404(self, client,
                                                             admin_client,
                                                             submission):
        """The submission exists; it simply has no result. Conflating those
        would suggest the submission is missing."""
        r = admin_client.get(
            f"/admin/submissions/{submission['id']}/detection")
        assert r.status_code == 200
        assert r.json()["status"] == "not_run"


# ---- the subprocess contract --------------------------------------------
class TestRunnerContract:
    """What `services/detection.py` expects of the runner subprocess.

    These guard the seam between the two repositories. If the runner's output
    contract changes, these fail first — before a 30-second pipeline run has to
    be repeated to discover it.
    """

    def test_the_runner_script_exists(self):
        assert detection.RUNNER_SCRIPT.is_file(), (
            f"missing {detection.RUNNER_SCRIPT}")

    def test_the_vendored_detector_is_present(self):
        """Option A: the pipeline ships inside this repo, not as a folder
        reference. If someone deletes detector/ thinking it is generated, the
        detector silently stops working — this fails first."""
        root = detection.DETECTOR_DIR
        assert (root / "Revamping.ipynb").is_file(), (
            f"missing {root / 'Revamping.ipynb'} — re-vendor per detector/README.md")
        assert (root / "models" / "cargo_obb_best.pt").is_file(), (
            f"missing {root / 'models' / 'cargo_obb_best.pt'} — re-vendor per "
            f"detector/README.md")

    def test_an_empty_project_dir_resolves_to_the_vendored_copy(self, monkeypatch):
        """The normal case: DETECTION_PROJECT_DIR empty means 'use our own'."""
        from config import get_settings

        monkeypatch.setattr(get_settings(), "detection_project_dir", "")
        assert detection.resolve_project_dir() == detection.DETECTOR_DIR

    def test_an_explicit_project_dir_still_wins(self, monkeypatch):
        """The escape hatch for trying an upstream checkout stays working."""
        from config import get_settings

        monkeypatch.setattr(get_settings(), "detection_project_dir",
                            r"C:\somewhere\else")
        assert str(detection.resolve_project_dir()) == r"C:\somewhere\else"

    def test_the_runner_points_at_a_notebook(self, monkeypatch):
        """`CARGO_PROJECT_DIR` is how the runner finds Revamping.ipynb."""
        src = detection.RUNNER_SCRIPT.read_text(encoding="utf-8")
        assert "CARGO_PROJECT_DIR" in src
        assert "Revamping.ipynb" in src

    def test_the_runner_runs_only_detection_cells(self):
        """Cells 12+ are the unvalidated measurement stage. If someone adds them,
        the numbers would be relative volume stored as cubic metres."""
        src = detection.RUNNER_SCRIPT.read_text(encoding="utf-8")
        assert 'PIPELINE_CELLS = ("CELL 7", "CELL 8", "CELL 8b", "CELL 8c", "CELL 9", "CELL 10")' in src
        for measurement_cell in ("CELL 20", "CELL 22", "CELL 25", "CELL 26"):
            assert measurement_cell not in src, (
                f"{measurement_cell} produces relative, not metric, values")

    def test_the_runner_parses_the_verdict_from_the_log(self):
        """CELL 10 reports to stdout rather than returning; the runner depends
        on that wording, so a notebook edit could silently break it."""
        src = detection.RUNNER_SCRIPT.read_text(encoding="utf-8")
        assert "accepted '" in src and "NO CONFIDENT CARGO" in src

    def test_the_runner_writes_a_result_even_on_failure(self):
        """Otherwise a crashed pipeline is indistinguishable from a crash."""
        src = detection.RUNNER_SCRIPT.read_text(encoding="utf-8")
        assert "result.json" in src
        assert "traceback" in src

    def test_a_missing_result_file_becomes_a_reported_error(self, client,
                                                            submission, monkeypatch,
                                                            enabled):
        """The runner writes result.json even on internal failure, so its
        absence means the interpreter died before it could."""
        def no_result(image_path, **kwargs):
            return detection.DetectionRun(
                result={"ok": False, "error": "Detector exited with code 1 "
                                               "without a result."},
                overlay_path=None,
                run_dir=detection.WORK_ROOT,
                stdout_tail="",
                returncode=1,
            )

        monkeypatch.setattr(detection, "run_detection", no_result)
        r = client.post(f"/portal/submissions/{submission['id']}/detect")
        assert r.status_code == 502


# ---- docs ----------------------------------------------------------------
class TestOpenAPI:
    @pytest.mark.parametrize(
        "path, method",
        [
            ("/portal/submissions/{inspection_id}/detect", "post"),
            ("/portal/submissions/{inspection_id}/detection", "get"),
            ("/portal/submissions/{inspection_id}/detection/overlay", "get"),
            ("/portal/detection/availability", "get"),
            ("/admin/submissions/{inspection_id}/detection", "get"),
        ],
    )
    def test_detection_routes_are_documented_and_locked(self, client, path,
                                                       method):
        op = client.get("/openapi.json").json()["paths"][path][method]
        assert op.get("security"), f"{method.upper()} {path} has no lock icon"
        assert op.get("summary"), f"{method.upper()} {path} has no summary"
        assert op.get("description") or op.get("summary")

    def test_detect_documents_that_it_blocks(self, client):
        """A 30-second synchronous call must say so, or every caller is
        surprised by it."""
        op = client.get("/openapi.json").json()["paths"][
            "/portal/submissions/{inspection_id}/detect"]["post"]
        assert "16-45" in op["description"] or "blocks" in op["description"]
