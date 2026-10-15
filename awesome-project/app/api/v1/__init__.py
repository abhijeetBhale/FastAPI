"""Version 1 of the API.

One definition, imported wherever a route or a URL is built. The prefix is
*applied* once, in `app/api/v1/api.py`, when `api_router` is built; this
module exists so
the two dozen places that **build** a URL (`links.self`, `Location`,
`image_url`, pagination links, the lifting-plan document's overlay link) do not
each re-type the version. That is what keeps `/api/v1` from half-applying.

It lives in the package's `__init__` rather than alongside the router in
`app/api/v1/api.py`, so that it can be imported without importing the routers:
`app/services/lifting_plan.py` needs the constant, and `api.py` imports that
service. A module-level constant here has no imports of its own, so that is not
a cycle.

Why the version is in the path rather than negotiated through a header: the
browser portal, the Swagger document and plain `curl` all read it with no extra
work, and it is the form every reader already knows. A future v2 is a second
`sibling package and a second `include_router(...)` call, not a rename.

Deliberately **outside** the prefix — `/` (human entry point), `/health` and
`/health/ready` (probe configuration, not an API contract worth versioning),
`/docs`, `/redoc`, `/openapi.json` (tooling) and `/ui` (static client). See
`docs/API_VERSIONING_PLAN.md` §3.
"""

from __future__ import annotations

#: Prefix for every API resource route, e.g. `/api/v1/portal/submissions`.
API_PREFIX = "/api/v1"

__all__ = ["API_PREFIX"]
