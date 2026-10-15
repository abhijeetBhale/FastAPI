"""JSON-safe rendering of Pydantic validation errors.

`ValidationError.errors()` may contain arbitrary Python objects under `ctx` —
notably the raised `ValueError` from an `AfterValidator`. Passing that straight
to `HTTPException(detail=...)` makes Starlette's `json.dumps` fail with
`TypeError: Object of type ValueError is not JSON serializable`, so a client
error turns into a 500.

This strips the non-serialisable parts and keeps the useful fields.
"""

from __future__ import annotations

from typing import Any

from pydantic import ValidationError


def jsonable_errors(exc: ValidationError) -> list[dict[str, Any]]:
    """Return a detail list that is guaranteed safe to serialise to JSON."""
    safe: list[dict[str, Any]] = []
    for err in exc.errors():
        item = {
            "type": err.get("type"),
            "loc": list(err.get("loc", ())),
            "msg": err.get("msg"),
            "input": _safe(err.get("input")),
        }
        # `ctx` is where the raw exception lives - re-stringify it instead.
        ctx = err.get("ctx")
        if ctx:
            item["ctx"] = {k: str(v) for k, v in ctx.items()}
        safe.append(item)
    return safe


def _safe(value: Any) -> Any:
    """Coerce anything exotic to a string; JSON has no other option."""
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return str(value)