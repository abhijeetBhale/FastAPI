"""Response envelope helpers.

Every endpoint returns `{ "data": …, "meta": …, "links": … }` with `error`
omitted on success. See `docs/API_CONVENTIONS.md` for the full contract.
"""

from __future__ import annotations

from typing import Any, Optional


def envelope(
    data: Any,
    *,
    meta: Optional[dict] = None,
    links: Optional[dict] = None,
) -> dict:
    """Wrap a business payload in the standard envelope.

    `meta` and `links` are omitted when empty — no empty objects, no nulls.
    `error` is never present on success.
    """
    result: dict[str, Any] = {"data": data}
    if meta:
        result["meta"] = meta
    if links:
        result["links"] = links
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
