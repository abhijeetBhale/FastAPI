"""The versioned base path for every API route.

One definition, imported wherever a route or a URL is built. The prefix is
*applied* once, in `main.py`, at `include_router()` time; this module exists so
the two dozen places that **build** a URL (`links.self`, `Location`,
`image_url`, pagination links, the lifting-plan document's overlay link) do not
each re-type the version. That is what keeps `/api/v1` from half-applying.

Why the version is in the path rather than negotiated through a header: the
browser portal, the Swagger document and plain `curl` all read it with no extra
work, and it is the form every reader already knows. A future v2 is a second
`include_router(prefix=...)` call and a second router set, not a rename.

Deliberately **outside** the prefix — `/` (human entry point), `/health` and
`/health/ready` (probe configuration, not an API contract worth versioning),
`/docs`, `/redoc`, `/openapi.json` (tooling) and `/ui` (static client). See
`docs/API_VERSIONING_PLAN.md` §3.
"""

from __future__ import annotations

#: Prefix for every API resource route, e.g. `/api/v1/portal/submissions`.
API_PREFIX = "/api/v1"
