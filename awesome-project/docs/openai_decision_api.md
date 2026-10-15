# OpenAI Decision API & cargo-detection Implementation

## OpenAI Decision API (Public Beta, Oct 2026)

The **OpenAI Decisions API** is a focused endpoint that lets a model make a judgment on a specific set of developer‑defined questions, returning a typed answer with probabilities. It is designed for cases where you want the model to choose between a finite set of predefined answers rather than generate free‑form text.

- **Purpose:** Evaluate text, images, or both against a rubric you define.
- **Output:** For each question, the API returns the most likely option together with a confidence score (probability).
- **Typical use‑cases:** Moderation, classification, routing, any scenario where a deterministic, fast decision is needed.
- **Performance:** Reportedly ~10× faster than the Responses API for the same task.
- **Docs:** <https://developers.openai.com/api/docs/guides/decisions>

### How it works

1. **Define a rubric** – a list of questions, each with a fixed set of allowed answers (options).
2. **Submit** the input (text and/or image) along with the rubric.
3. **Receive** a structured response indicating the chosen option and probability for each question.
4. The model is constrained to answer only from the provided options, which guarantees predictable, auditable outcomes.

### Example (pseudo‑code)

```python
from openai import OpenAI

client = OpenAI()

rubric = {
    "questions": [
        {
            "id": "cargo_status",
            "question": "Is there visible cargo in this image?",
            "options": ["present", "absent"]
        },
        {
            "id": "cargo_type",
            "question": "What type of cargo is detected?",
            "options": ["containers", "bulk", "hazardous", "none"]
        }
    ]
}

response = client.decisions.create(
    rubric=rubric,
    image="data:image/png;base64,..."   # or text prompt
)

print(response.answers)
# => {"cargo_status": {"option": "present", "probability": 0.93},
#      "cargo_type": {"option": "containers", "probability": 0.78}}
```

## Implementation in the cargo‑detection Project

| Aspect | Status in cargo‑detection |
|--------|---------------------------|
| **OpenAI Decisions API integration** | **Not implemented** – the codebase does not call the OpenAI Decisions API. |
| **Decision flow** | Admin‑driven `approved` / `rejected` flow via `/admin/submissions/{id}/approve` and `/reject`. Decisions are recorded in an `audit_log` with `reviewed_by` / `reviewed_at`. |
| **Detection pipeline** | Images are shipped to a separate subprocess (YOLACT‑style detector) that returns a `result.json` with `detected: true/false` and an overlay. No OpenAI involvement. |
| **Configuration** | Detector settings live in `.env` (`DETECTION_ENABLED`, `DETECTION_PYTHON`, `DETECTION_TIMEOUT`, etc.). No OpenAI keys are required. |
| **Potential integration points** | • Use the Decisions API to auto‑classify cargo status/type from the detection overlay.<br>• Replace the manual admin approve/reject with an automated decision based on the API’s probability thresholds.<br>• Store the API’s confidence scores alongside the existing `status_note`. |

### Why it isn’t used yet

- The detector already provides a reliable `detected: true/false` outcome without invoking an external LLM, keeping the API lightweight and offline‑friendly.
- The project’s current review workflow is intentionally manual (admin approval/rejection) to maintain auditability and human oversight.
- Adding an external OpenAI dependency would require API key management, rate‑limit handling, and additional latency.

### How to add OpenAI Decisions API support (future work)

1. **Obtain an OpenAI API key** and add it to the environment (e.g., `OPENAI_API_KEY`).
2. **Define a rubric** that matches the cargo‑detection use‑case, e.g.:

   ```json
   {
     "questions": [
       {
         "id": "cargo_present",
         "question": "Is cargo visible in the image?",
         "options": ["present", "absent"]
       },
       {
         "id": "cargo_type",
         "question": "What is the primary cargo type?",
         "options": ["containers", "bulk", "hazardous", "other"]
       }
     ]
   }
   ```

3. **Create a service function** (e.g., `app/services/openai_decision.py`) that:
   - Reads the image file or its overlay.
   - Calls `client.decisions.create(rubric=rubric, image=...)`.
   - Returns the chosen option(s) and probabilities.
4. **Wire the result into the inspection workflow**:
   - After detection, invoke the decision service.
   - Auto‑set `status = "approved"` if `cargo_present == "present"` and confidence > 0.8, otherwise leave it for manual review.
   - Store the decision metadata (option, probability) in the `Inspection` model or a related table.
5. **Update admin routes** (or add new portal routes) to surface the AI‑generated recommendation alongside the existing approve/reject buttons.
6. **Add unit tests** that stub the OpenAI call and verify the fallback to manual review when the API is unavailable.

### Checklist for a production‑ready integration

- [ ] API key stored securely (environment variable, secret manager).
- [ ] Rubric versioned and stored alongside code (or configurable via DB).
- [ ] Rate‑limit / retry logic (exponential back‑off, respecting `429` responses).
- [ ] Fallback path when the API returns an error or times out – revert to manual admin decision.
- [ ] Audit logging of AI‑generated decisions (who triggered it, rubric version, API response).
- [ ] Monitoring of success/failure rates and confidence distribution.
- [ ] Documentation for ops on rotating keys and updating rubrics.

---

*This file was generated on 2025‑10‑15 as part of the cargo‑detection project analysis. For the most up‑to‑date OpenAI Decisions API specifications, consult the official [OpenAI docs](https://developers.openai.com/api/docs/guides/decisions).*