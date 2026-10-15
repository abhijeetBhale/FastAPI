# API_VERSIONING_PLAN.md — One base path for every route (`/api/v1`)

**Status:** **implemented** — see §14 for what shipped, the decisions taken, and
what was deliberately left out. The sections above are kept as the plan that
was executed, not rewritten after the fact.
**Scope:** the base path of every HTTP route, and every document that currently
prints a route.
**Companion:** `docs/API_CONVENTIONS.md` defines response/request/method
standards. This document adds the missing standard — *where a route lives* —
and lists the doc changes needed to make that standard true everywhere.

---

## 1. The problem

There is no rule today for where a route lives. Each router invents its own
top-level segment (`/auth`, `/portal`, `/admin`), `health` has no segment at
all, and nothing is versioned. Three concrete consequences:

1. **No version boundary.** Adding `/api/v2` semantics later means either
   breaking every client or introducing a second, parallel namespace by hand.
2. **The unversioned namespace is shared with infrastructure.** `/health`,
   `/docs`, `/openapi.json`, `/redoc` and `/ui` sit at the root next to the
   business routes, so a future route group could shadow one of them. A single
   prefix separates "API" from "platform surface".
3. **No single place to answer "what does this API expose?"** Today the answer
   is spread over six routers and is only correct if you read all of them.

The target: **every API resource path starts with `/api/v1`**, set in one place,
with the non-API surfaces deliberately left outside it.

---

## 2. Current state (measured, not estimated)

Dumped from the live app rather than read off the source:

```bash
cd awesome-project && .venv/Scripts/python -c "
import main
spec = main.app.openapi()
for p in sorted(spec['paths']):
    print(','.join(sorted(m.upper() for m in spec['paths'][p])).ljust(16), p)
"
```

Result: **39 paths / 44 operations**, grouped by first segment (38 paths once
the role endpoint merges into `PATCH /admin/users/{id}` — see §14):

| Group | Paths | Prefix declared in | Where `/api/v1` goes |
|---|---:|---|---|
| Auth | 6 | `app/api/v1/endpoints/routers/auth.py` (`APIRouter(prefix="/auth")`) | yes |
| Portal | 11 | `app/api/v1/endpoints/routers/inspection.py`, `app/api/v1/endpoints/routers/detection.py`, `app/api/v1/endpoints/routers/lifting_plan.py` (all `prefix="/portal"`) | yes |
| Admin | 19 | `app/api/v1/endpoints/routers/admin.py` (`APIRouter(prefix="/admin")`) | yes |
| Health | 2 | `app/api/v1/endpoints/routers/health.py` (no prefix) | decision D1 |
| Root | 1 | `main.py` (`@app.get("/")`) | no — stays |
| — | — | FastAPI built-ins `/docs`, `/redoc`, `/openapi.json`, `/docs/oauth2-redirect` | no — stays |
| — | — | static mount `/ui` | no — stays |

Two notes that matter for the work below:

- The **three** portal routers share one prefix, so a single change touches
  three files if the prefix is edited per-router.
- `/health` is included last on purpose (`main.py`), so it keeps its literal
  path if a resource router later adds a `/{id}` route. Any prefix scheme must
  keep that ordering guarantee.

---

## 3. Target convention

> **Every API route is `/{version}/{group}/{resource...}`, where version is
> `/api/v1` and group is one of `auth`, `portal`, `admin`.**

Rules to write into `API_CONVENTIONS.md` (see §8):

1. **One version segment, in one place.** The prefix is applied once, in
   `main.py`, at `include_router()` time — never inside a router's own
   `APIRouter(prefix=...)`.
2. **Groups stay as they are** (`auth` / `portal` / `admin`). They already
   describe audience, which is the useful axis here.
3. **Resources are plural nouns**, segments are `kebab-case`, path parameters
   are `snake_case` (matching the JSON field names) — see D2.
4. **Non-API surfaces are not versioned** and not reachable through the prefix.
5. **`links` values stay relative** (`API_CONVENTIONS.md` §1) but now *include*
   the prefix, so a client can follow a link without re-deriving the base path.

### Surfaces that deliberately stay outside the prefix

| Surface | Path | Reason |
|---|---|---|
| Root banner | `/` | Human entry point; prints the others |
| Health | `/health`, `/health/ready` | Decision **D1** — see below |
| Swagger / ReDoc / schema | `/docs`, `/redoc`, `/openapi.json`, `/docs/oauth2-redirect` | Tooling entry points. Only the *documented operations* are versioned |
| Static UI | `/ui` | Not an API |

**D1 — do health probes move under the prefix?**
- Option A (recommended): **keep `/health` unversioned.** Load balancers and
  container probes are configured with literal paths and are re-pointed with
  more friction than app clients; probes are also not part of the API contract
  a version number protects. Then §3's rule reads "every *API* route".
- Option B: `/api/v1/health`. Uniform, but every probe config and every
  infrastructure doc changes for no contract benefit.
- Either way, add `/api/v1/health` **only if** D1 chooses B; do not serve both
  silently.

---

## 4. Path mapping (old → new)

`{inspection_id}` / `{user_id}` are unchanged. "Group" rows are the full set
from §2.

### Auth — `/auth/*` → `/api/v1/auth/*`

| Old | New | Methods |
|---|---|---|
| `/auth/register` | `/api/v1/auth/register` | POST |
| `/auth/login` | `/api/v1/auth/login` | POST |
| `/auth/logout` | `/api/v1/auth/logout` | POST |
| `/auth/me` | `/api/v1/auth/me` | GET |
| `/auth/change-password` | `/api/v1/auth/change-password` | POST |
| `/auth/set-password` | `/api/v1/auth/set-password` | POST |

### Portal — `/portal/*` → `/api/v1/portal/*`

| Old | New | Methods |
|---|---|---|
| `/portal/submissions` | `/api/v1/portal/submissions` | GET, POST |
| `/portal/submissions/{inspection_id}` | `/api/v1/portal/submissions/{inspection_id}` | GET, DELETE |
| `/portal/submissions/{inspection_id}/detect` | `/api/v1/portal/submissions/{inspection_id}/detect` | POST |
| `/portal/submissions/{inspection_id}/detection` | `/api/v1/portal/submissions/{inspection_id}/detection` | GET |
| `/portal/submissions/{inspection_id}/detection/log` | `/api/v1/portal/submissions/{inspection_id}/detection/log` | GET |
| `/portal/submissions/{inspection_id}/detection/overlay` | `/api/v1/portal/submissions/{inspection_id}/detection/overlay` | GET |
| `/portal/submissions/{inspection_id}/image` | `/api/v1/portal/submissions/{inspection_id}/image` | GET |
| `/portal/submissions/{inspection_id}/lifting_plan` | `/api/v1/portal/submissions/{inspection_id}/lifting-plan` (D2) | GET |
| `/portal/cargo-types` | `/api/v1/portal/cargo-types` | GET |
| `/portal/summary` | `/api/v1/portal/summary` | GET |
| `/portal/detection/availability` | `/api/v1/portal/detection/availability` | GET |

### Admin — `/admin/*` → `/api/v1/admin/*`

| Old | New | Methods |
|---|---|---|
| `/admin/submissions` | `/api/v1/admin/submissions` | GET, POST |
| `/admin/submissions/{inspection_id}` | `/api/v1/admin/submissions/{inspection_id}` | GET, PATCH, DELETE |
| `/admin/submissions/{inspection_id}/approve` | `/api/v1/admin/submissions/{inspection_id}/approve` | POST |
| `/admin/submissions/{inspection_id}/reject` | `/api/v1/admin/submissions/{inspection_id}/reject` | POST |
| `/admin/submissions/{inspection_id}/restore` | `/api/v1/admin/submissions/{inspection_id}/restore` | POST |
| `/admin/submissions/{inspection_id}/purge` | `/api/v1/admin/submissions/{inspection_id}/purge` | DELETE |
| `/admin/submissions/{inspection_id}/detection` | `/api/v1/admin/submissions/{inspection_id}/detection` | GET |
| `/admin/submissions/{inspection_id}/detection/overlay` | `/api/v1/admin/submissions/{inspection_id}/detection/overlay` | GET |
| `/admin/submissions/{inspection_id}/image` | `/api/v1/admin/submissions/{inspection_id}/image` | GET |
| `/admin/submissions/bulk` | `/api/v1/admin/submissions/bulk` | POST |
| `/admin/submissions/pending` | `/api/v1/admin/submissions/pending` | GET |
| `/admin/submissions/summary` | `/api/v1/admin/submissions/summary` | GET |
| `/admin/submissions/orphaned-users` | `/api/v1/admin/submissions/orphaned-users` | GET |
| `/admin/stats` | `/api/v1/admin/stats` | GET |
| `/admin/audit` | `/api/v1/admin/audit` | GET |
| `/admin/users` | `/api/v1/admin/users` | GET |
| `/admin/users/{user_id}` | `/api/v1/admin/users/{user_id}` | GET |
| `/admin/users/{user_id}/role` | `/api/v1/admin/users/{user_id}/role` | POST |
| `/admin/cargo-types` | `/api/v1/admin/cargo-types` | GET |

### Unchanged

| Path | Methods |
|---|---|
| `/` | GET |
| `/health` | GET |
| `/health/ready` | GET |
| `/docs`, `/redoc`, `/openapi.json`, `/docs/oauth2-redirect` | GET |
| `/ui/*` (static mount) | GET |

---

## 5. Naming cleanups to ride along (decisions, not defaults)

These are the other places the path "format" is not yet uniform. Each is a
small decision; bundling them with the prefix avoids a second breaking window.

| ID | Item | Today | Proposed | Impact if taken |
|---|---|---|---|---|
| **D2** | Segment casing | `/portal/submissions/{id}/lifting_plan` | `.../lifting-plan` | Breaking for that one path; alias optional (§7) |
| **D3** | Trailing slash | FastAPI defaults (redirect on `/path/`) | keep default; state it in `API_CONVENTIONS.md` | documentation only |
| **D4** | Sub-resource verb naming | mix of nouns (`/detection`) and verbs (`/detect`, `/approve`, `/purge`, `/restore`) | keep — these are state transitions, and §5 of `API_CONVENTIONS.md` already treats them as actions | none |
| **D5** | `Location` header on 201 | `/auth/me` style, unprefixed | must equal the new `links.self` (`/api/v1/auth/me`) | none beyond prefix |

If D2 is declined, `/api/v1/portal/submissions/{id}/lifting_plan` is the one
path whose final segment keeps an underscore — document the exception rather
than leaving it unexplained (and rename `links`/`image_url` consistently, since
they are generated from a base string).

---

## 6. Implementation plan (code)

### 6.1 Apply the prefix in one place — `main.py`

Set it at inclusion, not in the routers, so there are exactly six edits and the
portal's three routers cannot drift:

```python
API_PREFIX = "/api/v1"

app.include_router(auth_router, prefix=API_PREFIX)
app.include_router(portal_router, prefix=API_PREFIX, dependencies=authed)
app.include_router(detection_router, prefix=API_PREFIX, dependencies=authed)
app.include_router(lifting_plan_router, prefix=API_PREFIX, dependencies=authed)
app.include_router(admin_router, prefix=API_PREFIX, dependencies=authed)
app.include_router(health_router)          # only if D1 = B: prefix=API_PREFIX
```

- Do **not** add `prefix="/api/v1"` to the `APIRouter(...)` constructors — that
  duplicates the version in six files and defeats the "one place" rule.
- Keep `health_router` registered last (it must keep its literal path).
- Alternative considered: an aggregate `APIRouter(prefix=API_PREFIX)` that the
  six are included into. Rejected: it adds a layer whose only job is to hold a
  constant, and `include_router(prefix=...)` already does exactly that.

### 6.2 Middleware gates — **do this in the same commit**

This is the highest-risk part, because the auth middleware **fails open** for
any prefix not in its list. If the routers move and `PROTECTED_PREFIXES` does
not, anonymous requests reach `/api/v1/admin/*` and `/api/v1/portal/*` without
the middleware ever seeing them. Route-level `require_permission` dependencies
would still refuse most of it (defence in depth, and the admin router says so
in its own docstring), but the failure mode is silent and the status codes /
`X-Auth` header change.

- `app/middleware/middlewares/auth.py` — `PROTECTED_PREFIXES = ("/api/v1/portal", "/api/v1/admin")`.
- `app/middleware/middlewares/auth.py` — `PUBLIC_EXCEPTIONS` `"/admin/login-as"` →
  `"/api/v1/admin/login-as"`.
- `app/middleware/middlewares/rbac.py` — `ADMIN_PREFIXES = ("/api/v1/admin",)`.
- Tighten the matcher while we are here. `is_protected()` matches with
  `path.startswith(p)`, so `/portal-anything` is currently also protected. With
  a version prefix the loose form also captures `/api/v1/administer`. Use
  `path == p or path.startswith(p + "/")` in both `is_protected()` and
  `is_admin_path()`, and only then treat the prefix as a contract.
- Add regressions in `tests/test_rbac.py`: anonymous → 401 and authenticated
  non-admin → 403 on a representative `/api/v1/admin/*` and
  `/api/v1/portal/*` path, so a future prefix change cannot silently ungate.

### 6.3 Generated strings that contain the old paths

Every one of these is produced from a literal today and must move with the
routes, or responses will advertise dead URLs:

| Location | Count | New shape |
|---|---:|---|
| `app/api/v1/endpoints/routers/admin.py` `links={"self": f"/admin/submissions/{id}"}` | 6 | `f"/api/v1/admin/submissions/{id}"` |
| `app/api/v1/endpoints/routers/admin.py` `links={"self": f"/admin/users/{user.id}"}` | 2 | `f"/api/v1/admin/users/{user.id}"` |
| `app/api/v1/endpoints/routers/inspection.py` `links={"self": f"/portal/submissions/{id}"}` | 3 | `f"/api/v1/portal/submissions/{id}"` |
| `app/api/v1/endpoints/routers/auth.py` `links={"self": "/auth/me"}` | 3 | `"/api/v1/auth/me"` |
| `app/api/v1/endpoints/routers/auth.py` `response.headers["Location"] = "/auth/me"` | 1 | `"/api/v1/auth/me"` |
| `app/schemas/schemas/responses/inspection.py` `image_url` base (`/portal/...`, `/admin/...`) | 1 | prefixed base |
| `app/schemas/schemas/responses/envelope.py` `list_links(base_path=...)` callers | 5 | `base_path` is a literal at each call site — `app/api/v1/endpoints/routers/inspection.py:123`, `app/api/v1/endpoints/routers/admin.py:99,216,644,693` |

Prefer deriving these from the prefix constant (or `request.url.path`) over
re-typing `"/api/v1"` across the 21 literals counted above; that is exactly the
kind of drift the constant prevents.

### 6.4 Root banner and docs wiring

- `main.py` `root()` payload advertises `"ui"`, `"docs"`, `"health"`. Add the
  version base (`"api": "/api/v1"`) so a human landing on `/` can find it.
- Swagger/ReDoc keep their default URLs (`/docs`, `/openapi.json`) — they
  document versioned operations without themselves being versioned. Decide
  whether to also serve `openapi.json` under the prefix (D6, §12); default: no.
- Set `servers` in OpenAPI (`app = FastAPI(..., servers=[{"url": "/api/v1"}])`)
  **only if** the documented paths stay relative. Simpler and less ambiguous:
  leave `servers` unset and let the documented paths carry the prefix. Pick one
  — the two together double the prefix in Swagger's "Try it out".

### 6.5 Browser client — `static/index.html`

**14 path literals** need the prefix: 13 `fetch()` calls (of which 12 carry a
path literal and one uses a variable) plus the `image_url` builder.

| Surface | Lines |
|---|---|
| `/admin/*` | 301, 315, 398, 413, 426 |
| `/auth/*` | 470, 525 (the register/login ternary feeding the `fetch(url)` at 529), 547 |
| `/portal/*` | 557, 569, 588, 677, 754, and the `image_url` template at 785 |

Introduce one constant and concatenate:

```js
const API = "/api/v1";
const r = await fetch(API + "/admin/stats");
```

This is the only client in the repo; there is no separate frontend build to
update, and no generated client to regenerate.

### 6.6 Test suite

303 string literals across 8 test files reference the old paths (counted as
matches, `grep -rEo`):

| File | Path literals |
|---|---:|
| `tests/test_auth_portal.py` | 61 |
| `tests/test_detection.py` | 60 |
| `tests/test_rbac.py` | 59 |
| `tests/test_query_patterns.py` | 54 |
| `tests/test_docs_auth.py` | 28 |
| `tests/test_bug_regressions.py` | 28 |
| `tests/test_lifting_plan.py` | 12 |
| `tests/conftest.py` | 1 |

Two options:

- **A (recommended): a shared constant.** Add `API = "/api/v1"` to
  `tests/conftest.py`, expose it as a fixture or a module-level import, and
  rewrite the literals as `f"{API}/portal/submissions"`. Mechanical, but the
  next version bump is then a one-line test change.
- **B: literal search-and-replace.** Faster now, repeats the whole exercise at
  the next version boundary.

`tests/test_docs_auth.py` needs special attention: it asserts against
`client.get("/openapi.json").json()["paths"]` keys, which become the prefixed
paths, and it pins that public operations (`/auth/login`, `/auth/register`,
`/health`) declare no security requirement.

---

## 7. Rollout / compatibility options

| | Approach | Pros | Cons |
|---|---|---|---|
| **A** | **Hard cutover** — old paths 404 | Simplest; one truth in the docs and the OpenAPI document | Every existing client, curl script and saved Swagger link breaks at once |
| **B** | **Dual mount + deprecation** — include each router twice (unprefixed *and* `/api/v1`), mark the old operations `deprecated: true`, add `Deprecation: true` + `Sunset: <date>` headers, remove after the window | No client breaks; migration is observable in logs | Two paths per operation in `/openapi.json` (double the document), and generated `links.self` can only match one of them |
| **C** | **Redirect** — old paths return `308` to the new ones | Cheap for GET clients | Does not cover POST bodies reliably across clients; still leaves the old paths in the schema unless suppressed |

**Recommendation: A**, given the single in-repo browser client (§6.5) is updated
in the same commit and there is no external consumer to protect. Choose B only
if there are deployed clients outside this repository — in that case also state
the removal date in `API_CONVENTIONS.md` so "temporarily both" cannot become
permanent. This is decision **D7**.

---

## 8. API documentation changes (the deliverables)

Numbering below refers to `docs/API_CONVENTIONS.md` as it stands today.

### 8.1 Add the missing standard section

Insert a new section before the envelope (§1 today): **"Base path & versioning"**,
containing the rules from §3 of this plan, the surfaces table, the
`{/api/v1}/{group}/{resource}` shape, the D1 verdict, and the statement that
`links` are relative *and* prefixed. Renumbering later sections is optional —
a new §0 avoids a 2,400-line renumber, but pick one and be consistent.

### 8.2 Examples that carry a path (must change everywhere)

| Section | What changes |
|---|---|
| §1 Envelope | `links` example and the "relative paths" rule → `/api/v1/portal/submissions/28` |
| §2 Single resource | example `links.self`, and the `Location` = `links.self` note |
| §3 Collection / list | `links.self`/`next`, and the `?page=`/`?per_page=` examples in the table below it |
| §4 Errors | `type` URIs are opaque (no change); scanner examples in §7 do change |
| §5 Method usage | `Location`/`Idempotent-Replay` examples, anti-pattern list |
| §6 Field conventions | any path-valued field example (`image_url`) |

### 8.3 §7 Endpoint reference — headings and every example

§7.1–§7.5 are organised by group and print a literal request line for each
operation. All of them change:

| Section | New heading |
|---|---|
| 7.1 | Auth (`/api/v1/auth/*`) |
| 7.2 | Portal submissions (`/api/v1/portal/*`) |
| 7.3 | Admin (`/api/v1/admin/*`) |
| 7.4 | Health (`/health/*`) — unchanged if D1 = A; retitled if D1 = B |
| 7.5 | Root (`/`) — unchanged; add the `api` key if §6.4 adds it |

Also inside §7: the `image_url` values, the `links.self` values, the
lifting-plan `/…/lifting_plan` path (D2), and the bulk/`approved` example
payloads that echo a path.

### 8.4 §8 JSON Schemas and §9 OpenAPI 3.1

- §8 (draft 2020-12 schemas): no paths are encoded, so nothing structural
  changes — but any `examples` containing a URL must be updated, and if D2 is
  taken, the lifting-plan schema's description should match the new path.
- §9 must be regenerated against reality, not hand-patched:
  - every `paths:` key gains the `/api/v1` prefix;
  - decide `servers:` per §6.4 (prefix in `servers` **or** in `paths`, not both);
  - `operationId`s: keep the existing `<group>_<action>` convention, but note
    that FastAPI derives them from the function name + path, so check the
    generated ids after the prefix change and update §9 to match the app;
  - the `security` blocks and response `$ref`s are unaffected.

### 8.5 Other documents that print routes

Lines containing a path literal, by file:

| File | Lines | Change |
|---|---:|---|
| `docs/API_CONVENTIONS.md` | 106 | §8.1–§8.4 |
| `docs/Flow.md` | 33 | call-flow diagrams and endpoint lists |
| `docs/DETECTION.md` | 12 | the detect/detection/overlay requests and the `Availability` copy |
| `README.md` | 7 | the PowerShell `Invoke-RestMethod` snippets and the endpoint table near line 462 |
| `docs/LIFTING_PLAN.md` | 1 | the endpoint line |

`docs/ARCHITECTURE_FLOW.md` and the remaining docs mention no paths today; if
one is added later it inherits the new base.

### 8.6 Stop the docs from drifting again

The path list exists in four places (code, `API_CONVENTIONS.md` §7, §9's YAML,
and the diagrams). Add **one** machine check so this cannot silently rot:

- a test in the `test_docs_auth.py` spirit that reads §9's `paths:` keys out of
  the Markdown and asserts the set equals `app.openapi()["paths"]` keys;
- and/or a small script that writes the inventory table (a regenerated version
  of §2 above) into the docs.

Either is ~20 lines and turns "the docs are out of date" from a review skill
into a failing test.

---

## 9. Acceptance criteria (all satisfied — evidence in §14)

- [x] `GET /openapi.json` lists 38 paths (44 operations), **every API path
      starting with `/api/v1/`**; only `/`, the health paths (per D1), `/docs`,
      `/redoc`, `/openapi.json` are outside it.
- [ ] No router file contains the string `/api/v1` — the prefix appears once,
      in `main.py`.
- [ ] `PROTECTED_PREFIXES` / `ADMIN_PREFIXES` / `PUBLIC_EXCEPTIONS` cover the
      prefixed paths; anonymous on `/api/v1/admin/*` → 401, non-admin → 403.
- [ ] Every `links.self`, `Location`, pagination link and `image_url` in a
      response resolves to a live route (no 404 when followed).
- [ ] `static/index.html` issues no request to an unprefixed path.
- [ ] `docs/API_CONVENTIONS.md` §7 examples, §9 YAML, `README.md`,
      `docs/Flow.md`, `docs/DETECTION.md`, `docs/LIFTING_PLAN.md` contain no
      unprefixed API path.
- [ ] Full test suite green, including the new prefix regressions and the
      docs-vs-openapi consistency test.
- [ ] Swagger UI at `/docs` can execute a protected operation end-to-end with a
      bearer token (the `test_docs_auth.py` contract, re-verified by hand).

## 10. Verification

```bash
# 1. inventory: paths, operations, and that nothing is left unprefixed
cd awesome-project && .venv/Scripts/python -c "
import main
spec = main.app.openapi()
paths = spec['paths']
assert len(paths) == 38, len(paths)   # 39 at planning time; the role endpoint
                                       # merged into PATCH /admin/users/{id}
unversioned = {'/', '/health', '/health/ready', '/docs', '/redoc',
               '/openapi.json', '/docs/oauth2-redirect'}
bad = [p for p in paths if not p.startswith('/api/v1/') and p not in unversioned]
assert not bad, bad
print('versioned paths:', sum(p.startswith('/api/v1/') for p in paths))
print('operations:', sum(len(paths[p]) for p in paths))
"

# 2. the full suite (preserve the exit status; do not pipe it through tail alone)
cd awesome-project && .venv/Scripts/python -m pytest -q; echo "pytest exit=$?"

# 3. the auth gate on the new prefix
cd awesome-project && .venv/Scripts/python -m pytest tests/test_rbac.py tests/test_docs_auth.py -q; echo "pytest exit=$?"

# 4. no stale references outside the docs
cd awesome-project && grep -rnE '"/?(portal|admin|auth|health)/' static/ tests/ app/api/v1/endpoints/ app/schemas/ main.py | grep -v '/api/v1/' | grep -v '^Binary'
```

Step 4 should return nothing but the deliberately-unversioned health paths and
test-local helpers.

## 11. Task breakdown

| # | Task | Depends on | Touches |
|---|---|---|---|
| 1 | Decide D1 (health), D2 (lifting-plan casing), D7 (rollout) | — | — |
| 2 | Add `API_PREFIX` and pass it to `include_router` | 1 | `main.py` |
| 3 | Move the middleware gates + tighten the prefix matcher | 2 | `app/middleware/middlewares/auth.py`, `app/middleware/middlewares/rbac.py` |
| 4 | Update generated links/`Location`/`image_url` | 2 | `app/api/v1/endpoints/routers/*.py`, `app/schemas/schemas/responses/*.py` |
| 5 | Update the browser client | 2 | `static/index.html` |
| 6 | Add `API` constant to `conftest.py`; rewrite test literals | 3, 4 | `tests/*.py` |
| 7 | Add prefix regressions (401/403, links resolve, pagination links) | 6 | `tests/test_rbac.py`, `tests/test_bug_regressions.py` |
| 8 | Add the base-path section to `API_CONVENTIONS.md`; update §7 examples | 1 | `docs/API_CONVENTIONS.md` |
| 9 | Regenerate §9 YAML from `app.openapi()` | 8 | `docs/API_CONVENTIONS.md` |
| 10 | Update the other four docs + `README.md` | 8 | `README.md`, `docs/Flow.md`, `docs/DETECTION.md`, `docs/LIFTING_PLAN.md` |
| 11 | Add the docs-vs-openapi consistency test | 9, 10 | `tests/` |
| 12 | Run §10 and record the results | all | — |

Ordering note: tasks 2–4 must land together. A commit that moves the routes but
not the middleware gates, or the routes but not the generated links, is worse
than either state on its own because both failures are silent.

## 12. Open questions

| ID | Question | Blocking |
|---|---|---|
| D1 | Health probes under the prefix or not? | §6.1, §8.3 |
| D2 | `/…/lifting_plan` → `/…/lifting-plan` now, or keep the underscore? | §4, §6.3 |
| D6 | Serve `openapi.json` under `/api/v1` as well? | §6.4 |
| D7 | Hard cutover, dual mount, or redirect? | §7, §11 task 2 |
| D8 | Is `v1` in the URL the long-term scheme, or should the version also be a header/`Accept` negotiation? | §3 — header negotiation is additive later; `v1` in the path is the convention to write down now |

## 13. Risks

| Risk | Why it bites | Mitigation |
|---|---|---|
| Middleware prefixes not moved with the routes | Auth **fails open** for unlisted prefixes; the route-level permission checks mask it, so the mistake looks like a normal 403 instead of a missing gate | Task 3 in the same commit as task 2 + the 401/403 regressions |
| Generated links left unprefixed | Responses advertise 404s; a client following `links.self` breaks while the API itself looks correct | Task 4, plus a test that follows every `self` link |
| Docs updated by hand in four places | They drift again within one change | Task 11 machine check |
| Two prefixes served during migration | `links.self` can only match one; clients mix both; the deprecation never ends | Only under D7 = B, with a dated `Sunset` and a removal task |
| Prefix duplicated in six routers | The next version bump needs six edits and can half-apply | Enforce "one place" in §8.1 and check it in review |

---

## 14. What shipped (implementation record)

### Decisions taken

| ID | Question | Decision |
|---|---|---|
| D1 | Health under the prefix? | **A — stays unversioned.** `/health`, `/health/ready` keep their literal paths; probe config is not an API contract. |
| D2 | `/…/lifting_plan` casing | **Renamed** to `/…/lifting-plan`. It was the only path segment not in kebab-case. |
| D3 | Trailing slash | FastAPI default kept (redirect), now stated in `API_CONVENTIONS.md` §0. |
| D6 | `openapi.json` under the prefix? | **No.** Docs tooling stays at `/docs`, `/redoc`, `/openapi.json`. |
| D7 | Cutover strategy | **A — hard cutover.** No dual mount, no redirect: `/portal/submissions` 404s. |
| D8 | Version in path vs header | **Path.** `/api/v1`. Header negotiation stays additive later. |

### What changed

| Area | Change |
|---|---|
| Base path | New `app/api/v1/api.py` holding `API_PREFIX = "/api/v1"`; `main.py` passes it to six `include_router()` calls — the version appears **once**, not in any router |
| Route groups | `auth`, `portal`, `admin` unchanged as groups; only the version segment is new |
| Middleware gates | `PROTECTED_PREFIXES`, `ADMIN_PREFIXES`, `PUBLIC_EXCEPTIONS` moved to the prefixed paths, in the same commit as the routes; the prefix matcher tightened from `startswith(p)` to segment-aware matching (`/api/v1/administrate` is no longer treated as admin-only) |
| Generated URLs | 21 sites — `links.self`, `Location`, `image_url`, the five `list_links(base_path=…)` callers, the lifting-plan document's `overlay_url` — all build from `API_PREFIX` |
| Browser client | `static/index.html`: one `const API = "/api/v1"`, 14 call sites rewritten (the `image_url` template included) |
| Tests | `API_PREFIX` imported from the app instead of ~300 re-typed literals; new `tests/test_api_contract.py` (26 tests) |
| Documentation | `API_CONVENTIONS.md` §0 added, §7/§9 updated, §9 now regenerated by `scripts/regen_openapi.py`; `README.md`, `docs/Flow.md`, `docs/DETECTION.md`, `docs/LIFTING_PLAN.md` updated; new `docs/API_METHOD_AUDIT.md` |

### Method audit (extra scope, requested mid-implementation)

Auditing all 44 operations against §5 found four defects beyond the base path,
all fixed — the full table is in `docs/API_METHOD_AUDIT.md`:

- `POST /admin/users/{id}/role?role=` → **`PATCH /admin/users/{id}`** with a
  JSON body (partial update of a resource; the query string rule).
- `/approve` and `/reject` read their note from `?note=` while the admin UI sent
  a JSON body, so **note text was silently discarded**. Now a body
  (`DecisionRequest`).
- `POST …/detect` read `?force=` from the query string — the same class of bug
  (a mutation's input in the query string), now `{"force": true}` in the body
  (`DetectRequest`). Both bodies are optional, which is why neither was noticed:
  the failure mode was a silently ignored option, not an error.
- A `405` listed only the first matching handler's method in `Allow`
  (`POST /admin/users/{id}` answered `Allow: GET`). `errors.allowed_methods()`
  rebuilds it from the app's path table.

The result of the merge in the first bullet: **38 paths / 44 operations**.

### Anti-drift guarantees added

1. `tests/test_api_contract.py::METHOD_CONTRACT` pins every path to its methods,
   and three structural rules stop a new route from picking an odd verb
   (`PATCH` only on resource URLs, `DELETE` only removes, `POST` creates or
   names its action).
2. The same file parses §9 out of this document and fails if it disagrees with
   the served schema; the fix is `scripts/regen_openapi.py`, which is idempotent.
   It also extracts §7's endpoint headings and asserts they are *exactly* the
   served operations — that check is what found 21 endpoints still documented as
   `/{id}` while the routes declare `{inspection_id}` / `{user_id}`.
3. The gates are pinned: anonymous → 401, signed-in non-admin → 403, on the
   prefixed paths. No non-`GET` operation may declare a query parameter, which
   is the rule both query-string bugs violated.
4. Advertised links are followed in tests: `links.self`, `Location` and
   `image_url` must each resolve, so a response cannot point at a 404.

### Verification

- Full suite: **284 passed** (257 before this change).
- `app.openapi()`: 38 paths, 44 operations, no unprefixed API path.
- The drift test was proved non-vacuous by injecting a single wrong path into §9
  and watching it fail, then restoring the document.
- `scripts/regen_openapi.py` run twice on the same tree produces byte-identical
  output.

### Not done (deliberately)

- `ETag` / `If-Match` / `412` and `202 Accepted` async detection — no `PUT`
  exists, and async detection needs a queue. Reported as a known gap in
  `API_CONVENTIONS.md` §5, not implemented.
- `Idempotency-Key` same-key-different-body → 422 and in-flight → 409 still
  need a `request_hash` column on `idempotency_keys` (schema migration). The
  replay *header* was already done in an earlier pass.
- `README.md` still describes the original `/users/` + `/addresses/` scaffold in
  its architecture sections (title, tables of contents, `app/models/` + `app/schemas/`
  narrative). That is pre-existing debt unrelated to versioning; the API
  reference section itself was corrected here.
