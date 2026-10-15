"""OpenAI Decisions API client — the AI judgement step of the upload path.

`POST /v1/decisions` evaluates text and images against a developer-defined
rubric and returns typed answers with probabilities: a *predicate* (is this
true? → probability), a *choice* (which of these? → one of your values plus a
distribution) or a *score* (rate against ordered levels). It is roughly 10×
faster than the Responses API and priced on input tokens only — which is what
makes calling it inline while `POST /portal/submissions` is still handling the
upload viable: no queue, no second round trip, and the upload response already
carries the verdict.

Three things this module is careful about:

1. **The upload never fails because of it.** `decide()` raises `DecisionError`
   on any problem (network, 429 after retries, 5xx, malformed body); the
   caller stores the failure in `decision_result` and the submission keeps its
   status — the fallback path is the ordinary manual review queue.

2. **The rubric is versioned, and static.** `RUBRIC_VERSION` travels with
   every stored result, so an answer produced by an older rubric is
   recognisable as such. Per-request facts (the declared cargo type) go into
   the *input text*, never into the questions — one rubric serves every upload.

3. **Retries are bounded.** One retry, only for failures that are plausibly
   transient (429/5xx/connect), honouring `Retry-After` up to a small cap.

Reference: docs/openai_decision_api.md and
https://developers.openai.com/api/docs/guides/decisions
"""

from __future__ import annotations

import base64
import logging
import time
from dataclasses import dataclass
from typing import Any, Optional

import httpx

from app.core.config import get_settings
logger = logging.getLogger("app.decision")

#: The dedicated endpoint. Not the Responses API — no `temperature`, no
#: `response_format`: the rubric IS the schema.
API_URL = "https://api.openai.com/v1/decisions"

#: Bumped whenever `RUBRIC` changes shape or wording. Stored with every result.
RUBRIC_VERSION = "1"

#: Initial + one retry. Two attempts total keeps the upload path bounded.
MAX_ATTEMPTS = 2

#: Only these statuses are worth retrying — a 422 will fail identically again.
RETRYABLE_STATUS = frozenset({429, 500, 502, 503, 504})

BACKOFF_SECONDS = 0.5
#: Cap for `Retry-After`: respect the server, but not for minutes.
MAX_RETRY_DELAY = 2.0

#: The predicates the auto-approve gate reads (see `recommend`).
GATE_QUESTIONS = ("cargo_present", "matches_declaration")

#: Fixed set for the `cargo_type` choice — the API only ever picks from these.
CARGO_CHOICES = ("containers", "bulk", "hazardous", "other", "none")

#: The rubric, kept versioned and next to the code that sends it. Questions
#: state *observable* criteria only; facts about a particular upload belong in
#: the input text (`build_payload`).
RUBRIC: dict[str, list[dict[str, Any]]] = {
    "questions": [
        {
            "type": "predicate",
            "name": "cargo_present",
            "instructions": (
                "Is there visible cargo in this image — freight, goods, "
                "containers, or bulk material being handled or stored?"
            ),
        },
        {
            "type": "choice",
            "name": "cargo_type",
            "instructions": (
                "What is the primary type of cargo visible in this image? "
                "Choose 'none' when no cargo is visible."
            ),
            "choices": [{"value": value} for value in CARGO_CHOICES],
        },
        {
            "type": "predicate",
            "name": "matches_declaration",
            "instructions": (
                "Does the visible cargo match the declared cargo type given "
                "in the text? If no cargo is visible, this is false."
            ),
        },
    ],
}


class DecisionError(RuntimeError):
    """The Decisions API could not be reached, or answered unusably.

    Always caught by the caller on the upload path — see
    `InspectionService._apply_ai_decision`.
    """


@dataclass(frozen=True)
class DecisionOutcome:
    """One successful call, normalised for storage."""

    model: str
    rubric_version: str
    answers: dict[str, Any]
    usage: Optional[dict[str, Any]]
    recommendation: str

    def as_result(self, *, auto_approved: bool, threshold: float) -> dict[str, Any]:
        """The JSONB document stored in `Inspection.decision_result`."""
        return {
            "ok": True,
            "model": self.model,
            "rubric_version": self.rubric_version,
            "recommendation": self.recommendation,
            "auto_approved": auto_approved,
            "threshold": threshold,
            "answers": self.answers,
            "usage": self.usage,
        }


def failure_result(error: str) -> dict[str, Any]:
    """The document stored when no verdict exists.

    Mirrors detection's contract: a failure is stored, not silently dropped,
    so `decision_status == "error"` is inspectable from the API rather than
    only from server logs.
    """
    return {
        "ok": False,
        "rubric_version": RUBRIC_VERSION,
        "error": str(error)[:500],
    }


def is_available() -> tuple[bool, str]:
    """Return `(usable, reason)`. `reason` explains a False verdict."""
    settings = get_settings()
    if not settings.openai_decision_enabled:
        return False, "OpenAI decision step is disabled (OPENAI_DECISION_ENABLED=false)."
    if not settings.openai_api_key.strip():
        return False, "OPENAI_API_KEY is not set."
    return True, "ok"


def recommend(answers: dict[str, Any], *, threshold: float) -> str:
    """`"approve"` only when every gate predicate clears `threshold`.

    A missing answer, a refusal, or a non-predicate answer is NOT a pass:
    the model declining to answer means we know less, not that the condition
    holds. Anything short of confidence → `"review"`, i.e. the human queue.
    """
    for name in GATE_QUESTIONS:
        answer = answers.get(name)
        if not isinstance(answer, dict) or answer.get("type") != "predicate":
            return "review"
        try:
            probability = float(answer["probability"])
        except (KeyError, TypeError, ValueError):
            return "review"
        if probability < threshold:
            return "review"
    return "approve"


def build_payload(
    *,
    image_bytes: bytes,
    content_type: str,
    declared_type: Optional[str] = None,
) -> dict[str, Any]:
    """Assemble the `/v1/decisions` request body.

    The image travels as a base64 data URL inside a user message — the input
    shape the API accepts (`role`/`type`/`content` with `input_text` +
    `input_image` parts). The declared type is *input text*, so the rubric
    stays identical across uploads.
    """
    settings = get_settings()
    encoded = base64.b64encode(image_bytes).decode("ascii")
    text = "Photo uploaded to a cargo inspection portal."
    if declared_type:
        text += f" Declared cargo type: {declared_type}."
    return {
        "model": settings.openai_decision_model,
        "input": [
            {
                "role": "user",
                "type": "message",
                "content": [
                    {"type": "input_text", "text": text},
                    {
                        "type": "input_image",
                        "image_url": f"data:{content_type};base64,{encoded}",
                    },
                ],
            }
        ],
        "questions": RUBRIC["questions"],
    }


def decide(
    *,
    image_bytes: bytes,
    content_type: str,
    declared_type: Optional[str] = None,
) -> DecisionOutcome:
    """Evaluate one uploaded image. Raises `DecisionError` on any failure.

    Never called directly from a route: `InspectionService` wraps it so an
    outage degrades to manual review instead of a failed upload.
    """
    settings = get_settings()
    payload = build_payload(
        image_bytes=image_bytes,
        content_type=content_type,
        declared_type=declared_type,
    )
    timeout = httpx.Timeout(float(settings.openai_decision_timeout), connect=5.0)
    headers = {"Authorization": f"Bearer {settings.openai_api_key}"}

    with httpx.Client(timeout=timeout, headers=headers) as client:
        for attempt in range(1, MAX_ATTEMPTS + 1):
            try:
                response = client.post(API_URL, json=payload)
            except (httpx.ConnectError, httpx.ConnectTimeout) as exc:
                # Transient (DNS, refused, SYN timeout) — worth one retry.
                if attempt < MAX_ATTEMPTS:
                    logger.warning("decision: connect error, retrying: %s", exc)
                    time.sleep(BACKOFF_SECONDS * attempt)
                    continue
                raise DecisionError(f"cannot reach the Decisions API: {exc}") from exc
            except httpx.HTTPError as exc:
                # Read timeout / transport mid-flight: retrying a slow call
                # would only double the upload's wait, so this fails fast.
                raise DecisionError(f"Decisions API request failed: {exc}") from exc

            if response.status_code == 200:
                return _parse_response(response)

            detail = response.text.strip()[:300] or response.reason_phrase
            if response.status_code in RETRYABLE_STATUS and attempt < MAX_ATTEMPTS:
                delay = min(MAX_RETRY_DELAY, _retry_delay(response))
                logger.warning(
                    "decision: HTTP %s, retrying in %.1fs",
                    response.status_code,
                    delay,
                )
                time.sleep(delay)
                continue
            raise DecisionError(
                f"Decisions API returned HTTP {response.status_code}: {detail}"
            )

    raise DecisionError("Decisions API call did not complete.")  # pragma: no cover


def _retry_delay(response: httpx.Response) -> float:
    """`Retry-After` if the server sent one, else linear backoff."""
    header = response.headers.get("Retry-After", "")
    try:
        return max(0.0, float(header))
    except ValueError:
        return BACKOFF_SECONDS


def _parse_response(response: httpx.Response) -> DecisionOutcome:
    """Normalise the API's `answers` array into a name-keyed dict."""
    try:
        data = response.json()
    except ValueError as exc:
        raise DecisionError("Decisions API returned malformed JSON.") from exc

    if not isinstance(data, dict) or not isinstance(data.get("answers"), list):
        raise DecisionError("Decisions API response has no answers array.")

    answers: dict[str, Any] = {}
    for index, item in enumerate(data["answers"]):
        if not isinstance(item, dict):
            continue
        # The API echoes the question's `name`; refusals carry it too (or
        # null for an unnamed question), so numbering is the last resort.
        name = item.get("name") or f"question_{index + 1}"
        answers[str(name)] = item

    settings = get_settings()
    usage = data.get("usage")
    return DecisionOutcome(
        model=str(data.get("model") or settings.openai_decision_model),
        rubric_version=RUBRIC_VERSION,
        answers=answers,
        usage=usage if isinstance(usage, dict) else None,
        recommendation=recommend(
            answers, threshold=settings.openai_decision_min_confidence
        ),
    )