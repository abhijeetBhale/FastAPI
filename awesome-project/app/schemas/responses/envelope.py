"""Response envelope helpers.

Every endpoint returns `{ "data": …, "meta": …, "links": … }` with `error`
omitted on success. See `docs/API_CONVENTIONS.md` for the full contract.

Also home to the two field-convention helpers shared by every response
schema: `IsoDateTime` (ISO 8601 UTC timestamps) and the null scrubbing that
`envelope()` applies so payloads never carry explicit `null`s (§6).
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Annotated, Any, Optional

from pydantic import PlainSerializer


def iso_utc(value: datetime) -> str:
    """Render a datetime as ISO 8601 UTC with a `Z` suffix.

    Naive values are treated as already-UTC — the app writes them with
    `database.utcnow()` so that assumption holds (§6).
    """
    if value.tzinfo is not None:
        value = value.astimezone(timezone.utc).replace(tzinfo=None)
    return value.isoformat() + "Z"


#: A datetime field that serialises to `"2026-10-13T16:06:16Z"` in every mode.
#: Use this instead of bare `datetime` on response models.
IsoDateTime = Annotated[datetime, PlainSerializer(iso_utc, return_type=str)]


def scrub(value: Any) -> Any:
    """Apply §6 to an already-built payload: no explicit nulls, ISO 8601 Z.

    * `None` values are dropped from dicts and lists (an empty list/object is
      kept — `[]`/`{}` are the sanctioned replacement for `null`).
    * Anything still shaped like a `datetime` — raw rows from aggregate
      queries, audit entries, service payloads — is rendered as ISO 8601 UTC.
      Model payloads arrive here as strings already, thanks to `IsoDateTime`.
    """
    if isinstance(value, dict):
        return {k: scrub(v) for k, v in value.items() if v is not None}
    if isinstance(value, (list, tuple)):
        return [scrub(v) for v in value if v is not None]
    if isinstance(value, datetime):
        return iso_utc(value)
    return value


def envelope(
    data: Any,
    *,
    meta: Optional[dict] = None,
    links: Optional[dict] = None,
) -> dict:
    """Wrap a business payload in the standard envelope.

    `meta` and `links` are omitted when empty — no empty objects, no nulls.
    `error` is never present on success. Every payload passes through
    `scrub()` so explicit `null`s and naive datetimes cannot leak out.
    """
    result: dict[str, Any] = {"data": scrub(data)}
    # Scrubbed first: a meta/links dict holding only nulls must be omitted
    # entirely rather than emitted as `{}`.
    if meta:
        scrubbed_meta = scrub(meta)
        if scrubbed_meta:
            result["meta"] = scrubbed_meta
    if links:
        scrubbed_links = scrub(links)
        if scrubbed_links:
            result["links"] = scrubbed_links
    return result


def pagination_meta(
    *, page: int, per_page: int, total: int, total_pages: int
) -> dict:
    """The `meta.pagination` block, always present on list endpoints."""
    return {
        "pagination": {
            "page": page,
            "per_page": per_page,
            "total": total,
            "total_pages": total_pages,
        }
    }


def list_links(
    *,
    base_path: str,
    page: int,
    per_page: int,
    total_pages: int,
    query: Optional[dict] = None,
) -> dict:
    """`links` for a paginated list: self, next/prev, first/last.

    `query` carries extra query params (filters, sort) so page URLs
    preserve them. Omitted at boundaries.
    """
    def _url(p: int) -> str:
        params = {"page": p, "per_page": per_page}
        if query:
            params.update({k: v for k, v in query.items() if v is not None})
        qs = "&".join(f"{k}={v}" for k, v in params.items())
        sep = "&" if "?" in base_path else "?"
        return f"{base_path}{sep}{qs}"

    links: dict[str, str] = {"self": _url(page)}
    if page < total_pages:
        links["next"] = _url(page + 1)
    if page > 1:
        links["prev"] = _url(page - 1)
    if total_pages > 1:
        links["first"] = _url(1)
        links["last"] = _url(total_pages)
    return links
