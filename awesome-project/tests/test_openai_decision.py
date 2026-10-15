"""OpenAI Decisions API integration on the upload path.

The real API needs a key and costs money, so `openai_decision.decide` is
stubbed throughout. What is pinned here:

* the rubric's shape and `recommend()`'s auto-approve gate (pure functions);
* the upload endpoint runs the step, stores the verdict, and audits it;
* confidence >= threshold auto-approves a *submitted* row — never a draft;
* any failure (raised error, missing key) leaves the upload intact and the
  row in the manual review queue — the documented fallback path.

The suite pins the feature off in `tests/conftest.py`; each test that wants
it re-enables it explicitly with monkeypatch.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.api.v1 import API_PREFIX
from app.core.config import get_settings
from app.services import openai_decision

# ---- fakes -----------------------------------------------------------------

def _answers(cargo: float, matches: float) -> dict:
    return {
        "cargo_present": {
            "type": "predicate", "name": "cargo_present", "probability": cargo,
        },
        "cargo_type": {
            "type": "choice", "name": "cargo_type", "choice": "containers",
            "confidence": 0.78,
            "probabilities": [
                {"value": "containers", "probability": 0.78},
                {"value": "bulk", "probability": 0.22},
            ],
        },
        "matches_declaration": {
            "type": "predicate", "name": "matches_declaration",
            "probability": matches,
        },
    }


def _outcome(recommendation: str, *, cargo: float = 0.93, matches: float = 0.87):
    return openai_decision.DecisionOutcome(
        model="gpt-6-luna",
        rubric_version=openai_decision.RUBRIC_VERSION,
        answers=_answers(cargo, matches),
        usage={"input_tokens": 1234, "output_tokens": 0, "total_tokens": 1234},
        recommendation=recommendation,
    )


APPROVE = _outcome("approve")
REVIEW = _outcome("review", cargo=0.55, matches=0.44)


# ---- fixtures --------------------------------------------------------------

@pytest.fixture(autouse=True)
def _decision_defaults(monkeypatch):
    """State the settings every test does NOT want; enabling is one call."""
    settings = get_settings()
    monkeypatch.setattr(settings, "openai_decision_enabled", False)
    monkeypatch.setattr(settings, "openai_api_key", "")


def _enable(monkeypatch, *, key: str = "sk-test-not-a-real-key") -> None:
    settings = get_settings()
    monkeypatch.setattr(settings, "openai_decision_enabled", True)
    monkeypatch.setattr(settings, "openai_api_key", key)


@pytest.fixture
def authed(client):
    """A signed-in plain user (the `client` fixture starts signed out)."""
    client.post(API_PREFIX + "/auth/register", json={
        "name": "Ana", "email": "ana@example.com", "password": "quay-crane-42",
    })
    return client


def _upload(client, png_bytes, **form) -> dict:
    data = {"cargo_type": "scrap-steel", **form}
    r = client.post(
        API_PREFIX + "/portal/submissions",
        data=data,
        files={"image": ("c.png", png_bytes(), "image/png")},
    )
    assert r.status_code == 201, r.text
    return r.json()["data"]


# ---- rubric & payload ------------------------------------------------------

class TestRubric:
    """The rubric is a contract with the API: names, types, fixed choices."""

    def test_question_names_are_unique_and_typed(self):
        questions = openai_decision.RUBRIC["questions"]
        names = [q["name"] for q in questions]
        assert len(names) == len(set(names))
        assert set(names) == {"cargo_present", "cargo_type", "matches_declaration"}
        for q in questions:
            assert q["type"] in {"predicate", "choice", "score"}
            assert q["instructions"].strip()

    def test_choice_values_are_exactly_the_declared_set(self):
        choice = next(
            q for q in openai_decision.RUBRIC["questions"]
            if q["type"] == "choice"
        )
        assert [c["value"] for c in choice["choices"]] == list(
            openai_decision.CARGO_CHOICES
        )

    def test_payload_carries_image_and_declared_type(self):
        payload = openai_decision.build_payload(
            image_bytes=b"\x89PNG\r\n\x1a\nrest",
            content_type="image/png",
            declared_type="Scrap Steel",
        )
        assert payload["model"] == get_settings().openai_decision_model
        assert payload["questions"] == openai_decision.RUBRIC["questions"]
        parts = payload["input"][0]["content"]
        assert parts[0]["type"] == "input_text"
        assert "Scrap Steel" in parts[0]["text"]
        assert parts[1]["type"] == "input_image"
        assert parts[1]["image_url"].startswith("data:image/png;base64,")


# ---- the auto-approve gate -------------------------------------------------

class TestRecommendGate:
    """recommend() is the whole auto-approve policy — pure, so tested directly."""

    def test_confident_predicates_approve(self):
        assert openai_decision.recommend(
            _answers(0.9, 0.85), threshold=0.8
        ) == "approve"

    def test_the_threshold_is_inclusive(self):
        """The doc's rule is "confidence > 0.8"; we gate at >= so an exact
        0.80 does not silently fall to review."""
        assert openai_decision.recommend(
            _answers(0.8, 0.8), threshold=0.8
        ) == "approve"

    def test_low_cargo_probability_reviews(self):
        assert openai_decision.recommend(
            _answers(0.55, 0.9), threshold=0.8
        ) == "review"

    def test_low_declaration_match_reviews(self):
        """Cargo is visible but is NOT what the form declared → human look."""
        assert openai_decision.recommend(
            _answers(0.95, 0.3), threshold=0.8
        ) == "review"

    def test_a_missing_answer_reviews(self):
        assert openai_decision.recommend(
            {"cargo_present": _answers(0.99, 0.99)["cargo_present"]},
            threshold=0.8,
        ) == "review"

    def test_a_refusal_reviews(self):
        """A refusal is the model declining — knowledge is lower, not higher."""
        answers = _answers(0.99, 0.99)
        answers["matches_declaration"] = {
            "type": "refusal", "name": "matches_declaration",
        }
        assert openai_decision.recommend(answers, threshold=0.8) == "review"


# ---- availability ----------------------------------------------------------

class TestIsAvailable:
    def test_disabled_is_not_usable(self, monkeypatch):
        ok, reason = openai_decision.is_available()
        assert ok is False
        assert "disabled" in reason

    def test_enabled_without_a_key_is_not_usable(self, monkeypatch):
        _enable(monkeypatch, key="")
        ok, reason = openai_decision.is_available()
        assert ok is False
        assert "OPENAI_API_KEY" in reason

    def test_enabled_with_a_key_is_usable(self, monkeypatch):
        _enable(monkeypatch)
        ok, reason = openai_decision.is_available()
        assert (ok, reason) == (True, "ok")


# ---- the upload endpoint ---------------------------------------------------

class TestUploadDecision:
    def test_disabled_records_nothing(self, authed, png_bytes):
        """The default: no network call, no columns, `not_run` on the card.

        Note §6 (no explicit nulls): a field that is None is *absent* from
        the payload, not `null` — so "nothing recorded" is key absence.
        """
        data = _upload(authed, png_bytes)
        assert data["decision_status"] == "not_run"
        assert "decided_at" not in data
        assert "ai_recommendation" not in data
        assert "ai_answers" not in data

    def test_confident_upload_is_auto_approved(
        self, authed, png_bytes, monkeypatch, db
    ):
        from app.models.audit_log import AuditLog
        _enable(monkeypatch)
        seen: list[dict] = []

        def stub(**kwargs):
            seen.append(kwargs)
            return APPROVE

        monkeypatch.setattr(openai_decision, "decide", stub)
        data = _upload(authed, png_bytes)

        # The verdict rides the 201 response — no second request needed.
        assert data["status"] == "approved"
        assert data["decision_status"] == "ok"
        assert data["ai_recommendation"] == "approve"
        assert data["ai_answers"]["cargo_present"]["probability"] == pytest.approx(0.93)
        assert data["decided_at"] is not None
        assert data["reviewed_at"] is not None
        assert "reviewed_by" not in data  # scrubbed: None = no human reviewed
        assert "Auto-approved" in (data["status_note"] or "")

        # The decision ran on the uploaded bytes with the declared type.
        assert seen[0]["image_bytes"].startswith(b"\x89PNG")
        assert seen[0]["content_type"] == "image/png"
        assert seen[0]["declared_type"]

        # ...and is audited like any other write.
        entry = db.query(AuditLog).filter(AuditLog.action == "ai_decision").one()
        assert entry.entity_id == data["id"]
        assert entry.detail["auto_approved"] is True
        assert entry.detail["rubric_version"] == openai_decision.RUBRIC_VERSION

        # The list view carries it too (same derived fields, no N+1 fetch).
        items = authed.get(API_PREFIX + "/portal/submissions").json()["data"]
        assert items[0]["decision_status"] == "ok"
        assert items[0]["ai_recommendation"] == "approve"

    def test_low_confidence_stays_in_the_manual_queue(
        self, authed, png_bytes, monkeypatch
    ):
        _enable(monkeypatch)
        monkeypatch.setattr(openai_decision, "decide", lambda **kw: REVIEW)
        data = _upload(authed, png_bytes)
        assert data["status"] == "submitted"      # nothing auto-happened
        assert data["decision_status"] == "ok"
        assert data["ai_recommendation"] == "review"
        assert "reviewed_at" not in data          # §6: None is absent

    def test_a_failed_call_falls_back_to_manual_review(
        self, authed, png_bytes, monkeypatch, db
    ):
        """The doc's fallback path: API down → upload still 201, error stored,
        human queue unchanged."""
        from app.models.inspection import Inspection
        _enable(monkeypatch)

        def boom(**kw):
            raise openai_decision.DecisionError("HTTP 429: rate limited")

        monkeypatch.setattr(openai_decision, "decide", boom)
        data = _upload(authed, png_bytes)

        assert data["status"] == "submitted"
        assert data["decision_status"] == "error"
        assert "ai_recommendation" not in data    # §6: None is absent

        stored = db.get(Inspection, data["id"])
        assert stored.decision_result["ok"] is False
        assert "rate limited" in stored.decision_result["error"]
        assert stored.decided_at is not None

    def test_enabled_without_a_key_never_calls_out(
        self, authed, png_bytes, monkeypatch
    ):
        _enable(monkeypatch, key="")
        calls: list[int] = []
        monkeypatch.setattr(openai_decision, "decide", lambda **kw: calls.append(1))

        data = _upload(authed, png_bytes)
        assert calls == []
        assert data["decision_status"] == "error"
        assert data["status"] == "submitted"

    def test_a_draft_is_never_auto_approved(self, authed, png_bytes, monkeypatch):
        """`submitted` is the queue the gate acts on; a draft is untouched."""
        _enable(monkeypatch)
        monkeypatch.setattr(openai_decision, "decide", lambda **kw: APPROVE)
        data = _upload(authed, png_bytes, status="draft")
        assert data["status"] == "draft"
        assert data["decision_status"] == "ok"
        assert data["ai_recommendation"] == "approve"   # opinion recorded...
        assert "reviewed_at" not in data                # ...but no status change


# ---- the admin UI ----------------------------------------------------------

class TestUiSurface:
    def test_the_admin_card_shows_the_recommendation(self):
        """Step 5 of docs/openai_decision_api.md: surface the recommendation
        alongside the approve/reject buttons — which live in `adminCard`."""
        html = Path("static/index.html").read_text(encoding="utf-8")
        assert "ai_recommendation" in html
        assert "decision_status" in html