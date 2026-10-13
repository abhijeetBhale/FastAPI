"""Lifting plan generation.

One endpoint, no persistence — so these tests pin the document's content
and the refusal rules, not a workflow. The property that matters: every AI
value is tagged as an estimate, every engineering judgment is a blank.
"""

from __future__ import annotations

import pytest


@pytest.fixture
def submission(client, png_bytes, db):
    """A submission owned by the signed-in client, with a detected result."""
    client.post("/auth/register", json={"name": "Ana", "email": "ana@example.com",
                                        "password": "quay-crane-42"})
    r = client.post("/portal/submissions", data={"cargo_type": "scrap-steel"},
                    files={"image": ("c.png", png_bytes(), "image/png")})
    assert r.status_code == 201, r.text
    insp = r.json()["data"]

    from models.inspection import Inspection

    row = db.get(Inspection, insp["id"])
    row.detection_result = {
        "ok": True, "detected": True, "label": "Cargo-Box", "score": 16.3,
        "object_count": 2,
        "box_px": [52.0, 287.0, 196.0, 459.0],
        "box_width_px": 144.0, "box_height_px": 172.0,
        "image_width": 500, "image_height": 500,
        "detector_origin": "zip_trained_obb", "uses_zip_taxonomy": True,
        "objects": [], "elapsed_seconds": 24.4,
    }
    row.detected_at = row.created_at
    db.commit()
    return insp


@pytest.fixture
def plan_url(submission):
    return f"/portal/submissions/{submission['id']}/lifting_plan"


def _set_result(db, insp_id, result):
    from models.inspection import Inspection

    row = db.get(Inspection, insp_id)
    row.detection_result = result
    db.commit()


def _set_overlay(db, insp_id, filename):
    from models.inspection import Inspection

    row = db.get(Inspection, insp_id)
    row.detection_overlay = filename
    db.commit()


def as_other_user(client):
    client.post("/auth/logout")
    client.cookies.clear()
    client.post("/auth/register", json={"name": "Fo", "email": "fo@example.com",
                                        "password": "quay-crane-42"})


# ---- authorisation -------------------------------------------------------
class TestAuthorisation:
    def test_requires_a_session(self, client, submission):
        client.cookies.clear()
        assert client.get(
            f"/portal/submissions/{submission['id']}/lifting_plan"
        ).status_code == 401

    def test_another_users_submission_is_404(self, client, submission, plan_url):
        as_other_user(client)
        assert client.get(plan_url).status_code == 404


# ---- refusal rules -------------------------------------------------------
class TestRefusals:
    def test_not_run_is_422(self, client, submission, plan_url, db):
        _set_result(db, submission["id"], None)
        r = client.get(plan_url)
        assert r.status_code == 422
        assert "detect" in r.json()["detail"].lower()

    def test_no_cargo_is_422(self, client, submission, plan_url, db):
        _set_result(db, submission["id"],
                    {"ok": True, "detected": False, "status": "no_cargo"})
        r = client.get(plan_url)
        assert r.status_code == 422
        assert "nothing to lift" in r.json()["detail"].lower()

    def test_error_is_422(self, client, submission, plan_url, db):
        _set_result(db, submission["id"],
                    {"ok": False, "detected": False, "status": "error"})
        r = client.get(plan_url)
        assert r.status_code == 422
        assert "failed" in r.json()["detail"].lower()

    def test_partial_reference_is_422(self, client, plan_url):
        assert client.get(f"{plan_url}?ref_m=2.43").status_code == 422
        assert client.get(f"{plan_url}?ref_px=410").status_code == 422

    def test_bad_format_is_422(self, client, plan_url):
        assert client.get(f"{plan_url}?format=pdf").status_code == 422


# ---- the document --------------------------------------------------------
class TestMarkdown:
    def test_content_type_and_filename(self, client, submission, plan_url):
        r = client.get(plan_url)
        assert r.status_code == 200
        assert r.headers["content-type"].startswith("text/markdown")
        assert "attachment" in r.headers["content-disposition"]
        assert f"lifting-plan-{submission['id']}.md" in \
            r.headers["content-disposition"]

    def test_ai_fields_are_tagged(self, client, plan_url):
        body = client.get(plan_url).text
        assert "LIFTING PLAN" in body
        assert "[AI]" in body
        assert "Not certified" in body
        assert "Cargo-Box" in body
        assert "144" in body and "172" in body          # pixel box
        assert "7850" in body                            # scrap-steel density

    def test_engineering_fields_are_blank(self, client, plan_url):
        body = client.get(plan_url).text
        # Unchecked boxes for human-only decisions.
        assert "- [ ] Single" in body
        assert "- [ ] Routine" in body
        assert "- [ ] Obvious" in body
        assert "LM) Number:" in body
        assert "Boom Length:" in body
        # The load-calculation block exists but is blank.
        assert "(a) Lifting Capacity" in body
        assert "Safety Factor" in body

    def test_overlay_link_present_when_overlay_exists(self, client, submission,
                                                     plan_url, db):
        _set_overlay(db, submission["id"], "inspection_1_abc12345.png")
        body = client.get(plan_url).text
        assert "detection/overlay" in body

    def test_no_overlay_link_when_absent(self, client, plan_url):
        body = client.get(plan_url).text
        assert "detection/overlay" not in body


# ---- calibration --------------------------------------------------------
class TestCalibration:
    def test_reference_produces_metric_dimensions(self, client, plan_url):
        body = client.get(f"{plan_url}?ref_m=2.43&ref_px=410").text
        assert "0.005927" in body          # m_per_px
        assert "AI-ESTIMATE" in body
        # L = 144 px × 0.005927 = 0.85 m; H = 172 × 0.005927 = 1.02 m
        assert "0.85" in body
        assert "1.02" in body

    def test_no_reference_stays_in_pixels(self, client, plan_url):
        body = client.get(plan_url).text
        assert "pixel box" in body
        assert "AI-ESTIMATE" not in body

    def test_weight_estimate_with_density(self, client, plan_url):
        body = client.get(f"{plan_url}?ref_m=2.43&ref_px=410").text
        # density 7850 × L 0.85 × W 0.85 × H 1.02 ≈ 5,770 kg
        assert "estimate" in body
        assert "confirm by weighing" in body

    def test_other_cargo_type_has_no_weight_estimate(self, client, png_bytes, db):
        """cargo_type 'other' has null density — the API must not guess."""
        client.post("/auth/register", json={"name": "Fo", "email": "fo@example.com",
                                            "password": "quay-crane-42"})
        r = client.post("/portal/submissions",
                        data={"cargo_type": "other"},
                        files={"image": ("c.png", png_bytes(), "image/png")})
        insp = r.json()["data"]

        from models.inspection import Inspection

        row = db.get(Inspection, insp["id"])
        row.detection_result = {
            "ok": True, "detected": True, "label": "Cargo-Box", "score": 10.0,
            "object_count": 1, "box_px": [10, 10, 110, 110],
            "box_width_px": 100.0, "box_height_px": 100.0,
            "image_width": 200, "image_height": 200, "objects": [],
            "detector_origin": "zip_trained_obb", "uses_zip_taxonomy": True,
        }
        db.commit()

        body = client.get(
            f"/portal/submissions/{insp['id']}/lifting_plan").text
        # No density line, no kg estimate — the doc says to enter it manually.
        assert "kg/m³ [AI]" not in body
        assert "~" not in body


# ---- json format ---------------------------------------------------------
class TestJson:
    def test_same_data_structured(self, client, submission, plan_url):
        data = client.get(f"{plan_url}?format=json").json()
        assert data["inspection_id"] == submission["id"]
        assert data["detection_status"] == "detected"
        assert data["description"] == "2 × Cargo-Box (Scrap Steel)"
        assert data["box_width_px"] == 144.0
        assert data["weight"]["density_kg_m3"] == 7850.0
        assert data["weight"]["source"] == "none"      # no ref → no estimate

    def test_reference_computes_weight_in_json(self, client, plan_url):
        data = client.get(
            f"{plan_url}?ref_m=2.43&ref_px=410&format=json").json()
        assert data["dimensions"]["source"] == "estimated"
        assert data["dimensions"]["l_m"] == 0.85
        assert data["dimensions"]["h_m"] == 1.02
        assert data["dimensions"]["w_m"] is None
        assert data["weight"]["source"] == "estimate"
        assert data["weight"]["kg"] > 0
        assert data["warnings"]  # estimate warning present


# ---- theoretical rigging model (Option 2) --------------------------------
class TestRigging:
    def test_cog_is_geometric_centre(self, client, plan_url):
        data = client.get(f"{plan_url}?format=json").json()
        rig = data["rigging"]
        assert rig["available"] is True
        # box [52, 287, 196, 459] → centre (124, 373)
        assert rig["cog"]["x_px"] == 124.0
        assert rig["cog"]["y_px"] == 373.0
        assert rig["cog"]["method"] == "geometric_centre"
        assert rig["cog"]["tag"] == "AI-THEORETICAL"

    def test_hook_placement_geometry(self, client, plan_url):
        data = client.get(f"{plan_url}?format=json").json()
        hook = data["rigging"]["hook"]
        # w = 72, h = 172, L = 2.0 × 172 = 344
        # r = √(344² − 72²) = √(118336 − 5184) = √113152 ≈ 336.4
        # hook = (124, 287 − 336.4) = (124, −49.4)
        assert hook["legs"] == 2
        assert hook["sling_length_px"] == 344.0
        assert hook["vertical_rise_px"] == 336.4
        assert hook["hook_point_px"] == [124.0, -49.4]
        # angle from vertical = atan(72 / 336.4) ≈ 12.1°
        assert hook["angle_from_vertical_deg"] == 12.1
        assert hook["angle_from_horizontal_deg"] == 77.9
        assert hook["tag"] == "AI-THEORETICAL"

    def test_attachment_points_are_top_corners(self, client, plan_url):
        data = client.get(f"{plan_url}?format=json").json()
        pts = data["rigging"]["hook"]["attachment_points_px"]
        assert pts == [[52.0, 287.0], [196.0, 287.0]]

    def test_assumptions_are_stated(self, client, plan_url):
        data = client.get(f"{plan_url}?format=json").json()
        assumptions = data["rigging"]["assumptions"]
        assert len(assumptions) >= 4
        joined = " ".join(assumptions).lower()
        assert "geometric centre" in joined
        assert "2-leg" in joined
        assert "sling length" in joined
        assert "verify" in joined

    def test_rigging_rendered_in_markdown(self, client, plan_url):
        body = client.get(plan_url).text
        assert "AI-THEORETICAL" in body
        assert "Centre of Gravity" in body
        assert "Hook Placement" in body
        assert "sling angle" in body
        assert "ASSUMPTIONS" in body
        assert "geometric centre" in body

    def test_no_rigging_without_box(self, client, png_bytes, db):
        """A detection with no box → rigging unavailable, not fabricated."""
        client.post("/auth/register", json={"name": "Fo", "email": "fo@example.com",
                                            "password": "quay-crane-42"})
        r = client.post("/portal/submissions",
                        data={"cargo_type": "scrap-steel"},
                        files={"image": ("c.png", png_bytes(), "image/png")})
        insp = r.json()["data"]

        from models.inspection import Inspection

        row = db.get(Inspection, insp["id"])
        row.detection_result = {
            "ok": True, "detected": True, "label": "Cargo-Box", "score": 10.0,
            "object_count": 1, "box_px": None,
            "box_width_px": None, "box_height_px": None,
            "image_width": 200, "image_height": 200, "objects": [],
            "detector_origin": "zip_trained_obb", "uses_zip_taxonomy": True,
        }
        db.commit()

        data = client.get(
            f"/portal/submissions/{insp['id']}/lifting_plan?format=json"
        ).json()
        assert data["rigging"]["available"] is False
        assert "reason" in data["rigging"]
