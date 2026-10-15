# API_CONVENTIONS.md — Global response, request & method standards

Every endpoint in this API follows the conventions below. They are the
contract between the server and every client (browser portal, Swagger UI,
curl, scripts). Where an endpoint's current behaviour diverges, this document
is the target — the divergence is a bug to fix, not a choice to preserve.

---

## 0. Base path & versioning (all endpoints)

Every API route is `{version}/{group}/{resource...}`:

```
/api/v1/portal/submissions/28/detection/overlay
  └───┬─┘ └──┬──┘ └───────────┬──────────────┘
   version  group          resource chain
```

| Rule | Detail |
|---|---|
| One version segment | `/api/v1`. A future `v2` is a second `include_router` call, not a rename |
| Applied in one place | `app/api/v1/api.py`: `api_router` carries the prefix and `main.py` includes it once. The constant lives in `app/api/v1/__init__.py` and is imported wherever a URL is built |
| Groups | `auth`, `portal`, `admin` — they describe the audience, which is the axis that matters here |
| Segments are `kebab-case` | `/lifting-plan`, not `/lifting_plan` |
| Path parameters are `snake_case` | `/submissions/{inspection_id}` — they name JSON fields |
| `links` are relative **and** prefixed | `/api/v1/portal/submissions/28`, so a client can follow one without knowing the base path |

**Outside the prefix, deliberately:**

| Surface | Path | Why |
|---|---|---|
| Root banner | `/` | Human entry point |
| Probes | `/health`, `/health/ready` | Load-balancer/container configuration, not an API contract |
| Docs & schema | `/docs`, `/redoc`, `/openapi.json` | Tooling; the *operations* they document are versioned |
| Browser UI | `/ui` | Static client, not an API |

An unprefixed API path is a bug: `GET /portal/submissions` must 404, not
redirect. The contract is pinned by `tests/test_api_contract.py`, which fails
if a path appears outside the prefix, if a method changes, or if an advertised
`links.self` does not resolve.

---

## 1. Envelope (all endpoints)

Every response uses this top-level shape:

```json
{
  "data": { },
  "meta": { },
  "links": { },
  "error": null
}
```

| Key | Contents | When omitted |
|---|---|---|
| `data` | Business payload. Object for single resources, array for collections. | Never |
| `meta` | Pagination, timing, provenance, context. | When empty |
| `links` | Related resource URLs (`self`, `overlay`, `next`/`prev` page). | When empty |
| `error` | RFC 9457 problem document (§4). | **Entirely on success** — never `null`. On failure the envelope is not used at all: the whole body *is* the problem document. |

Rules:

- `data` is the only place business fields live. No business field is ever
  hoisted to the top level.
- `meta` never contains business data — only context about the response.
- `links` values are relative paths (`/api/v1/portal/submissions/28`), never
  absolute URLs.
- On success the `error` key is **absent**, not `null`. A client checks
  `error` for presence, not truthiness.

---

## 2. Single-resource endpoints

`GET / POST / PUT / PATCH / DELETE /resource/{id}`

```json
{
  "data": {
    "id": 31,
    "status": "submitted"
  },
  "meta": {
    "created_at": "2026-10-13T16:06:16Z",
    "updated_at": "2026-10-13T16:06:16Z"
  },
  "links": {
    "self": "/api/v1/portal/submissions/31"
  }
}
```

| Method | Success | Body | Notes |
|---|---|---|---|
| `GET` | 200 | envelope | |
| `POST` | 201 | envelope | `Location` header set to the new resource's `links.self` |
| `PUT` | 200 | envelope | Full replacement; missing fields become `null` |
| `PATCH` | 200 | envelope | Partial update; only changed fields sent |
| `DELETE` | 204 | **empty** | No envelope, no body |

`DELETE` of an already-deleted resource returns **204**, not 404 — delete is
idempotent.

---

## 3. Collection / list endpoints

`GET /resources`

```json
{
  "data": [
    { "id": 1, "status": "submitted" },
    { "id": 2, "status": "approved" }
  ],
  "meta": {
    "pagination": {
      "page": 1,
      "per_page": 20,
      "total": 142,
      "total_pages": 8
    }
  },
  "links": {
    "self": "/api/v1/portal/submissions?page=1&per_page=20",
    "next": "/api/v1/portal/submissions?page=2&per_page=20"
  }
}
```

- `meta.pagination` is **always** present on list endpoints.
- `links.next` / `links.prev` omitted at boundaries (first/last page).
- `links.first` / `links.last` included when `total_pages > 1`.

### Query parameters

| Param | Applies to | Default | Max |
|---|---|---|---|
| `page` | all lists | 1 | — |
| `per_page` | all lists | 20 | 100 |
| `sort` | sortable lists | `-created_at` | — |
| `search` | searchable lists | — | — |
| `status` / `cargo_type` / `tag` / `user_id` | filtered lists | — | — |
| `include_deleted` | admin lists | `false` | — |

`per_page` above the max is rejected with 422, not silently clamped.

---

## 4. Errors (all endpoints)

On any non-2xx response the body is an RFC 9457 problem document.
`Content-Type: application/problem+json`.

```json
{
  "type": "https://api.example.com/problems/validation-error",
  "title": "Validation Error",
  "status": 422,
  "detail": "Field 'image_url' is required.",
  "errors": [
    { "field": "image_url", "message": "required" }
  ]
}
```

| Field | Required | Notes |
|---|---|---|
| `type` | ✅ | URI identifying the problem class |
| `title` | ✅ | Short human-readable summary |
| `status` | ✅ | HTTP status code |
| `detail` | ✅ | Specific failure reason |
| `errors` | optional | Field-level validation failures |

### Status codes in use

| Code | Meaning | Used for |
|---|---|---|
| 400 | Malformed | Bad request body, unknown enum value |
| 401 | Unauthenticated | Missing/invalid session |
| 403 | Forbidden | Wrong role, permission denied |
| 404 | Not found | Unknown id, or another user's resource |
| 409 | Conflict | Duplicate, already-decided, same-key-different-body |
| 412 | Precondition failed | ETag mismatch on PUT/PATCH |
| 422 | Unprocessable | Validation failure, missing required field |
| 429 | Too many requests | Rate limit exceeded |
| 500 | Server error | Unhandled exception (with `request_id`) |
| 503 | Unavailable | Detector disabled/misconfigured |

**Never** put success/failure in the JSON body. The HTTP status code is the
signal. A 200 with `"error": "…"` in the body is always a bug.

---

## 5. HTTP method usage

| Method | Purpose | Safe | Idempotent |
|---|---|:--:|:--:|
| `GET` | Retrieve a resource or collection | ✅ | ✅ |
| `POST` | Create a resource or trigger an action | ❌ | ❌ |
| `PUT` | Replace a resource entirely | ❌ | ✅ |
| `PATCH` | Partially update a resource | ❌ | ❌ |
| `DELETE` | Remove a resource | ❌ | ✅ |
| `HEAD` | Same as GET, no body | ✅ | ✅ |
| `OPTIONS` | Supported methods & headers | ✅ | ✅ |

### Rules

- **Never use GET for mutations.** No `GET /users/123/delete`, no
  `GET /cart/add?product_id=789`.
- `POST` → create a new resource or trigger a non-idempotent action (run
  detection, submit inspection, approve/reject).
- `PUT` → full replacement. Client sends complete resource state; missing
  fields become `null`.
- `PATCH` → partial update. Client sends only changed fields. Uses JSON
  Merge Patch (`application/merge-patch+json`) or plain JSON.
- `DELETE` → idempotent. Deleting an already-deleted resource returns 204.

### PUT vs POST for creation

| Pattern | Status | Notes |
|---|---|---|
| `POST /resources` (server assigns ID) | 201 + `Location` | |
| `PUT /resources/{id}` (client assigns ID) | 201 created / 200 replaced | |

### Status codes per method

| Method | Success | No body | Conflict |
|---|---|---|---|
| `GET` | 200 | — | — |
| `POST` | 201 + `Location` | 202 (async) | 409 (duplicate) |
| `PUT` | 200 | 204 | 409 |
| `PATCH` | 200 | 204 | 409, 412 (ETag mismatch) |
| `DELETE` | 204 | 204 | — |

202 Accepted for long-running async operations. Include a `Location` or
`links.status` URL for polling.

405 Method Not Allowed when the URL exists but the method isn't supported.
`Allow` must list **every** method the path supports: where a path is served by
more than one handler (`GET` + `PATCH` on `/api/v1/admin/users/{user_id}`), a partial
list is misleading. `errors.allowed_methods()` rebuilds the header from the
app's path table for exactly that reason.

### Idempotency-Key header (POST & PATCH)

```http
POST /api/v1/portal/submissions
Idempotency-Key: 550e8400-e29b-41d4-a716-446655440000
Content-Type: application/json
```

- Client generates a UUIDv4 per logical request.
- Server stores `(key → status_code, body)` for at least 24 h.
- Retry with same key + same body → cached response + `Idempotent-Replay: true`.
- Same key + different body → 422.
- Same key, first request still in-flight → 409.

### Concurrency control (PUT / PATCH)

- `ETag` on responses for mutable resources.
- Client sends `If-Match: "<etag>"` on PUT/PATCH.
- Mismatch → 412 Precondition Failed with the current ETag in the response.

### Anti-patterns to reject

| Anti-pattern | Fix |
|---|---|
| `GET /users/123/delete` | `DELETE /users/123` |
| `POST /users/123` (update) | `PUT` or `PATCH /users/123` |
| `POST /users/123/reset-password` | `PUT /users/123` with `{"password":"…"}` or `POST /users/123/password-reset` |
| Always 200 regardless of outcome | Correct status codes per table |
| 200 with `"error":"…"` in body | 4xx/5xx + RFC 9457 problem object |
| POST for every operation (RPC-style) | Map to proper CRUD methods |

### Request body rules

| Method | Body | Content-Type |
|---|---|---|
| `GET` | None (use query params) | — |
| `POST` | Required | `application/json` |
| `PUT` | Required (full resource) | `application/json` |
| `PATCH` | Required (partial resource) | `application/merge-patch+json` or `application/json` |
| `DELETE` | Optional | `application/json` |

Query params for GET filtering/sorting/pagination only. Path params for
resource identification. Headers for cross-cutting concerns:
`Authorization`, `Idempotency-Key`, `If-Match`, `Accept`, `Content-Type`.

---

## 6. Field conventions

| Rule | Example |
|---|---|
| snake_case for all keys | `box_width_px` not `boxWidthPx` |
| Geometry as object, never flat array | `{"x":0,"y":0,"w":100,"h":200}` |
| Units in key name when non-obvious | `_px`, `_ratio`, `_seconds`, `_ms` |
| ISO 8601 UTC for all timestamps | `2026-10-13T16:06:16Z` |
| Booleans as real booleans | `"detected": true` |
| Omit keys that are null unless semantically meaningful | |
| No redundant derivable fields | Don't send `count` if `data` is an array |
| Group related fields into sub-objects | `box: {x,y,w,h}`, `mask: {area_ratio, border_leak}` |
| No top-level `success`/`ok`/`status` flags | HTTP status code is the signal |

---

## 7. Endpoint reference

### 7.1 Auth (`/api/v1/auth/*`)

#### `POST /api/v1/auth/register` — 201

Creates an account and signs in immediately.

**Request** (`application/json`):

```json
{
  "name": "Ana",
  "email": "ana@example.com",
  "phone": "+919876543210",
  "password": "quay-crane-42"
}
```

**Response 201**:

```json
{
  "data": {
    "message": "Signed in",
    "user": {
      "id": 7,
      "name": "Ana",
      "email": "ana@example.com",
      "phone": "+919876543210",
      "role": "user",
      "created_at": "2026-10-13T16:06:16Z",
      "inspection_count": 0,
      "has_password": true
    },
    "expires_in_hours": 12
  },
  "links": {
    "self": "/api/v1/auth/me"
  }
}
```

| Field | Type | Required | Description | Example |
|---|---|:--:|---|---|
| `data.user.id` | int | ✅ | New user id | `7` |
| `data.user.name` | string | ✅ | Display name | `"Ana"` |
| `data.user.email` | string | ✅ | Lowercased email | `"ana@example.com"` |
| `data.user.phone` | string | ❌ | Digits-only, 10–15; omitted if unset | `"+919876543210"` |
| `data.user.role` | string | ✅ | Always `"user"` on register | `"user"` |
| `data.user.created_at` | string | ✅ | ISO 8601 UTC | `"2026-10-13T16:06:16Z"` |
| `data.user.inspection_count` | int | ✅ | Always `0` on register | `0` |
| `data.user.has_password` | bool | ✅ | Always `true` on register | `true` |
| `data.expires_in_hours` | int | ✅ | Session lifetime | `12` |
| `links.self` | string | ✅ | | `"/api/v1/auth/me"` |

**Error 409** (duplicate email) — the problem document is the entire body
(`Content-Type: application/problem+json`), with no envelope and no wrapper:

```json
{
  "type": "https://api.example.com/problems/conflict",
  "title": "Conflict",
  "status": 409,
  "detail": "An account with that email already exists.",
  "code": "duplicate_email"
}
```

---

#### `POST /api/v1/auth/login` — 200

Exchanges credentials for a session cookie.

**Request** (`application/json`):

```json
{ "email": "ana@example.com", "password": "quay-crane-42" }
```

**Response 200**:

```json
{
  "data": {
    "message": "Signed in",
    "user": {
      "id": 7,
      "name": "Ana",
      "email": "ana@example.com",
      "role": "user"
    },
    "expires_in_hours": 12
  },
  "links": {
    "self": "/api/v1/auth/me"
  }
}
```

Session delivered as `Set-Cookie: session_token=…; HttpOnly; SameSite=Strict`.
The token is never in the body.

**Error 401**:

```json
{
  "type": "https://api.example.com/problems/authentication-required",
  "title": "Authentication Required",
  "status": 401,
  "detail": "Email or password is incorrect."
}
```

---

#### `POST /api/v1/auth/logout` — 200

Clears the session cookie.

```json
{ "data": { "detail": "Signed out" } }
```

---

#### `GET /api/v1/auth/me` — 200

Bootstrap: the signed-in user and their permission list.

```json
{
  "data": {
    "user": {
      "id": 7,
      "name": "Ana",
      "email": "ana@example.com",
      "phone": "+919876543210",
      "role": "user",
      "created_at": "2026-10-13T16:06:16Z",
      "inspection_count": 1,
      "has_password": true
    },
    "permissions": [
      "submissions:create",
      "submissions:read:own",
      "submissions:update:own",
      "submissions:withdraw:own",
      "users:read:own"
    ],
    "is_admin": false
  },
  "links": {
    "self": "/api/v1/auth/me"
  }
}
```

| Field | Type | Required | Description | Example |
|---|---|:--:|---|---|
| `data.user.id` | int | ✅ | User id | `7` |
| `data.user.name` | string | ✅ | | `"Ana"` |
| `data.user.email` | string | ✅ | | `"ana@example.com"` |
| `data.user.phone` | string | ❌ | Omitted if unset | |
| `data.user.role` | string | ✅ | `user` or `admin` | `"user"` |
| `data.is_admin` | bool | ✅ | Convenience over `role` | `false` |
| `data.permissions` | array | ✅ | Permission strings | |

---

#### `POST /api/v1/auth/change-password` — 200

**Request** (`application/json`):

```json
{
  "current_password": "quay-crane-42",
  "new_password": "new-password-99"
}
```

**Response 200**: `{ "data": { "detail": "Password updated" } }`

A wrong `current_password` is a 400; a weak `new_password` is a 422 with
per-field `errors[]`.

---

#### `POST /api/v1/auth/set-password` — 200

First password for an account that has none.

**Request** (`application/json`): `{ "password": "quay-crane-42" }`

**Response 200**: `{ "data": { "detail": "Password set" } }`

400 if the account already has a password — use `change-password`.

---

### 7.2 Portal submissions (`/api/v1/portal/*`)

#### `GET /api/v1/portal/submissions` — 200

The caller's own submissions, paginated.

```json
{
  "data": [
    {
      "id": 28,
      "user_id": 7,
      "name": "Ana",
      "email": "ana@example.com",
      "cargo_type": "scrap-steel",
      "cargo_label": "Scrap Steel",
      "density_kg_m3": 7850.0,
      "status": "submitted",
      "image_url": "/api/v1/portal/submissions/28/image",
      "detection_status": "detected",
      "cargo_object_count": 2,
      "created_at": "2026-10-13T13:35:32Z"
    }
  ],
  "meta": {
    "pagination": {
      "page": 1,
      "per_page": 6,
      "total": 1,
      "total_pages": 1
    }
  },
  "links": {
    "self": "/api/v1/portal/submissions?page=1&per_page=6"
  }
}
```

| Field | Type | Required | Description | Example |
|---|---|:--:|---|---|
| `data[].id` | int | ✅ | Submission id | `28` |
| `data[].cargo_type` | string | ✅ | Slug | `"scrap-steel"` |
| `data[].cargo_label` | string | ✅ | Human label | `"Scrap Steel"` |
| `data[].density_kg_m3` | float | ❌ | Omitted if cargo type has null density | |
| `data[].status` | string | ✅ | `draft`/`submitted`/`approved`/`rejected` | `"submitted"` |
| `data[].image_url` | string | ✅ | Owner-scoped image path | `"/api/v1/portal/submissions/28/image"` |
| `data[].detection_status` | string | ✅ | `not_run`/`detected`/`no_cargo`/`error` | `"detected"` |
| `data[].cargo_object_count` | int | ✅ | Detected regions | `2` |
| `data[].created_at` | string | ✅ | ISO 8601 UTC | |
| `meta.pagination.page` | int | ✅ | Current page | `1` |
| `meta.pagination.per_page` | int | ✅ | Page size | `6` |
| `meta.pagination.total` | int | ✅ | Total rows | `1` |
| `meta.pagination.total_pages` | int | ✅ | | `1` |

Query: `page`, `per_page`, `status`, `cargo_type`, `tag`, `search`, `sort`.

---

#### `POST /api/v1/portal/submissions` — 201

Upload a new submission. `multipart/form-data`.

**Form fields**: `cargo_type`, `status` (default `submitted`), `notes`,
`tags` (comma-separated), `image` (file), `Idempotency-Key` (header).

**Response 201**:

```json
{
  "data": {
    "id": 29,
    "user_id": 7,
    "cargo_type": "scrap-steel",
    "cargo_label": "Scrap Steel",
    "density_kg_m3": 7850.0,
    "status": "submitted",
    "image_url": "/api/v1/portal/submissions/29/image",
    "detection_status": "not_run",
    "cargo_object_count": 0,
    "created_at": "2026-10-13T16:06:16Z"
  },
  "links": {
    "self": "/api/v1/portal/submissions/29"
  }
}
```

**Error 403** (self-approving):

```json
{
  "type": "https://api.example.com/problems/forbidden",
  "title": "Forbidden",
  "status": 403,
  "detail": "You cannot set status 'approved'. Choose one of: draft, submitted. Approval is done by an administrator."
}
```

---

#### `GET /api/v1/portal/submissions/{inspection_id}` — 200

Single submission. Full field set including `tags`, `notes`, `reviewed_by`,
`reviewed_at`, `volume_m3`, `estimated_weight_kg`, `detection_status`,
`detected_at`, `cargo_object_count`.

---

#### `DELETE /api/v1/portal/submissions/{inspection_id}` — 204

Withdraw (soft-delete). Empty body — no envelope, not even `null`.
Idempotent: repeating the delete is still 204, not 404.

---

#### `GET /api/v1/portal/submissions/{inspection_id}/image` — 200

Image bytes. `Content-Type` from stored metadata.

---

#### `POST /api/v1/portal/submissions/{inspection_id}/detect` — 200

Run detection. Blocks 16–45 s. Returns the detection envelope (see §7.3).

**Request** (`application/json`, optional):

```json
{ "force": true }
```

`force` re-runs even when a stored result exists — needed after the detector or
its weights change. It is a *body* field, not `?force=`: §5 keeps query
parameters for `GET`, and this is a mutation's only input. The body is optional,
so a bare `POST` runs (or returns the cached) detection.

**Error 502**:

```json
{
  "type": "https://api.example.com/problems/detection-failed",
  "title": "Detection Failed",
  "status": 502,
  "detail": "Detector exited with code 1 without a result."
}
```

---

#### `GET /api/v1/portal/submissions/{inspection_id}/detection` — 200

```json
{
  "data": {
    "detected": true,
    "label": "Cargo-Box",
    "aggregate_score": 16.5,
    "objects": [
      {
        "label": "Cargo-Box",
        "yolo_confidence": 0.84,
        "sam_score": 0.96,
        "mask_area_px": 20379,
        "box": { "x": 663, "y": 95, "w": 121, "h": 181 },
        "models": {
          "yolo": { "x": 664, "y": 103, "w": 120, "h": 160 },
          "sam":  { "x": 664, "y": 103, "w": 120, "h": 160 }
        }
      }
    ],
    "box": { "x": 663, "y": 95, "w": 121, "h": 181 },
    "mask": {
      "area_ratio": 0.03876,
      "border_leak": 0.0
    },
    "detector_origin": "zip_trained_obb",
    "uses_zip_taxonomy": true,
    "stage": "detection_and_segmentation",
    "timed_out": false
  },
  "meta": {
    "inspection_id": 28,
    "detected_at": "2026-10-13T13:35:32.926Z",
    "elapsed_seconds": 24.64,
    "image": { "width": 848, "height": 620 },
    "links": {
      "overlay": "/api/v1/portal/submissions/28/detection/overlay"
    }
  }
}
```

| Field | Type | Required | Description | Example |
|---|---|:--:|---|---|
| `data.detected` | bool | ✅ | Cargo found | `true` |
| `data.label` | string | ❌ | Winning class | `"Cargo-Box"` |
| `data.aggregate_score` | float | ❌ | Selection score | `16.5` |
| `data.objects` | array | ✅ | Detected regions | |
| `data.objects[].box` | rect | ✅ | Tight AABB px | `{"x":663,"y":95,"w":121,"h":181}` |
| `data.objects[].models` | object | ❌ | Per-model boxes | |
| `data.box` | rect | ✅ | Primary box px | |
| `data.mask.area_ratio` | float | ❌ | Cargo fraction of frame | `0.03876` |
| `data.mask.border_leak` | float | ❌ | Border coverage | `0.0` |
| `data.detector_origin` | string | ❌ | Weights used | `"zip_trained_obb"` |
| `meta.inspection_id` | int | ✅ | | `28` |
| `meta.detected_at` | string | ✅ | ISO 8601 | |
| `meta.elapsed_seconds` | float | ❌ | Wall-clock | `24.64` |
| `meta.image` | object | ❌ | Frame dims | `{"width":848,"height":620}` |
| `meta.links.overlay` | string | ❌ | Omitted if no overlay | |

---

#### `GET /api/v1/portal/submissions/{inspection_id}/detection/log` — 200

Detector stdout tail for the most recent run — for diagnosing a failed one.

```json
{
  "data": { "inspection_id": 28, "returncode": 0, "stdout_tail": "[runner] OK" }
}
```

`returncode` is `0` once a run exists and `1` before any run; the tail is
empty when the run directory has since been swept by `cleanup_runs`.

---

#### `GET /api/v1/portal/submissions/{inspection_id}/detection/overlay` — 200

PNG bytes. 404 when nothing was detected.

---

#### `GET /api/v1/portal/submissions/{inspection_id}/lifting-plan` — 200

Markdown document. `Content-Type: text/markdown; charset=utf-8`.
`Content-Disposition: attachment; filename="lifting-plan-28.md"`.

Query: `ref_m`, `ref_px`, `format` (`markdown`|`json`).

With `format=json` the same data comes back enveloped, with `generated_at`
moved to `meta` as ISO 8601 UTC:

```json
{
  "data": { "inspection_id": 28, "detection_status": "detected", "…": "…" },
  "meta": { "generated_at": "2026-10-13T16:06:16Z" }
}
```

---

#### `GET /api/v1/portal/detection/availability` — 200

```json
{
  "data": {
    "enabled": true,
    "available": true,
    "reason": "ready",
    "timeout_seconds": 300,
    "supports_measurement": false
  }
}
```

---

#### `GET /api/v1/portal/cargo-types` — 200

```json
{
  "data": [
    {
      "id": 1,
      "slug": "scrap-steel",
      "label": "Scrap Steel",
      "density_kg_m3": 7850.0,
      "description": "Ferrous scrap metal"
    }
  ]
}
```

---

#### `GET /api/v1/portal/summary` — 200

```json
{
  "data": {
    "total": 1,
    "stats": {
      "inspections": 1,
      "approved": 0,
      "rejected": 0,
      "pending": 1,
      "total_weight_kg": 0.0
    },
    "cargo_types": [
      { "slug": "scrap-steel", "label": "Scrap Steel", "density_kg_m3": 7850.0 }
    ],
    "has_any": true
  }
}
```

---

### 7.3 Admin (`/api/v1/admin/*`)

All admin endpoints require `role == admin` (middleware + dependency).
Another user's resource → 404, never 403.

#### `GET /api/v1/admin/submissions` — 200

Cross-user list. Same shape as portal list. Query: `page`, `per_page`,
`user_id`, `cargo_type`, `status`, `tag`, `search`, `include_deleted`, `sort`.

---

#### `POST /api/v1/admin/submissions` — 201

Create on behalf of any user. `multipart/form-data` with `name`, `email`,
`cargo_type`, `phone`, `notes`, `status`, `tags`, `image`.

---

#### `GET /api/v1/admin/submissions/pending` — 200

Review queue. `status=submitted`, oldest first.

---

#### `GET /api/v1/admin/submissions/summary` — 200

Per-user aggregates.

```json
{
  "data": [
    {
      "user_id": 7,
      "name": "Ana",
      "email": "ana@example.com",
      "inspection_count": 1,
      "approved_count": 0,
      "rejected_count": 0,
      "total_weight_kg": 0.0,
      "last_inspection_at": "2026-10-13T13:35:32Z"
    }
  ]
}
```

`average_weight_kg` is omitted while no weights exist — nulls are never
emitted (§6).

---

#### `GET /api/v1/admin/submissions/orphaned-users` — 200

Users with zero inspections.

```json
{
  "data": [
    { "id": 9, "name": "Nobody", "email": "nobody@example.com" }
  ]
}
```

---

#### `GET /api/v1/admin/submissions/{inspection_id}` — 200

Any submission, including soft-deleted (`include_deleted=true`).

---

#### `PATCH /api/v1/admin/submissions/{inspection_id}` — 200

Partial update. Body: `application/merge-patch+json` or `application/json`.

---

#### `DELETE /api/v1/admin/submissions/{inspection_id}` — 204

Withdraw (soft-delete). Idempotent: repeating the delete is still 204.

---

#### `DELETE /api/v1/admin/submissions/{inspection_id}/purge` — 204

Hard delete.

---

#### `POST /api/v1/admin/submissions/{inspection_id}/approve` — 200

`POST` because approving is a non-idempotent state transition (§5), like
`/detect` and `/login`. Sets `status=approved`, `reviewed_by`, `reviewed_at`.

**Request** (`application/json`, optional):

```json
{ "note": "looks correct" }
```

The note is a *body*, not `?note=`: §5 reserves query parameters for GET
filtering/sorting/pagination, and the admin UI already sent it in the body — a
query-only parameter silently dropped it.

**Error 409** (already decided):

```json
{
  "type": "https://api.example.com/problems/conflict",
  "title": "Conflict",
  "status": 409,
  "detail": "Already approved."
}
```

---

#### `POST /api/v1/admin/submissions/{inspection_id}/reject` — 200

Same body contract as approve: `{ "note": "blurry image" }` (optional). Sets
`status=rejected`.

---

#### `POST /api/v1/admin/submissions/{inspection_id}/restore` — 200

Un-withdraw a soft-deleted submission.

---

#### `POST /api/v1/admin/submissions/bulk` — 200

**Request** (`application/json`):

```json
{ "ids": [1, 2, 3], "action": "approve", "note": "batch review" }
```

**Response 200**:

```json
{
  "data": {
    "processed": 3,
    "results": [
      { "id": 1, "ok": true, "status": "approved" },
      { "id": 2, "ok": false, "reason": "Already approved." }
    ]
  }
}
```

---

#### `GET /api/v1/admin/submissions/{inspection_id}/detection` — 200

Same envelope as portal detection. Read-only.

---

#### `GET /api/v1/admin/submissions/{inspection_id}/detection/overlay` — 200

PNG bytes.

---

#### `GET /api/v1/admin/submissions/{inspection_id}/image` — 200

Original upload bytes.

---

#### `GET /api/v1/admin/stats` — 200

```json
{
  "data": {
    "stats": {
      "inspections": 142,
      "approved": 80,
      "rejected": 12,
      "pending": 50,
      "total_weight_kg": 0.0
    },
    "by_status": { "submitted": 50, "approved": 80, "rejected": 12 },
    "by_cargo": [
      { "slug": "scrap-steel", "label": "Scrap Steel", "count": 90 }
    ],
    "users": 12,
    "admins": 2
  }
}
```

---

#### `GET /api/v1/admin/audit` — 200

```json
{
  "data": [
    {
      "id": 45,
      "action": "approved",
      "entity_type": "inspection",
      "entity_id": 28,
      "actor_user_id": 4,
      "detail": { "note": "looks fine" },
      "created_at": "2026-10-13T14:00:00Z"
    }
  ],
  "meta": {
    "pagination": { "page": 1, "per_page": 20, "total": 45, "total_pages": 3 }
  },
  "links": {
    "self": "/api/v1/admin/audit?page=1&per_page=20",
    "next": "/api/v1/admin/audit?page=2&per_page=20"
  }
}
```

Query: `page`, `per_page`, `entity_type`, `action`.

---

#### `GET /api/v1/admin/users` — 200

```json
{
  "data": [
    {
      "id": 7,
      "name": "Ana",
      "email": "ana@example.com",
      "role": "user",
      "created_at": "2026-10-13T16:06:16Z"
    }
  ],
  "meta": {
    "pagination": { "page": 1, "per_page": 100, "total": 12, "total_pages": 1 }
  },
  "links": {
    "self": "/api/v1/admin/users?page=1&per_page=100"
  }
}
```

---

#### `GET /api/v1/admin/users/{user_id}` — 200

```json
{
  "data": {
    "id": 7,
    "name": "Ana",
    "email": "ana@example.com",
    "phone": "+919876543210",
    "role": "user",
    "is_active": true,
    "created_at": "2026-10-13T16:06:16Z",
    "inspection_count": 1
  },
  "links": {
    "self": "/api/v1/admin/users/7"
  }
}
```

---

#### `PATCH /api/v1/admin/users/{user_id}` — 200

Changes one user's role. `PATCH` on the user rather than `POST` on a `/role`
sub-path: this is a partial update of an existing resource, and §5 rejects
POST-for-update. The value rides in the body, never in the query string.

**Request** (`application/json`):

```json
{ "role": "admin" }
```

A missing or unknown `role` is 422 — validation, not a hand-rolled check.

**Error 400** (self-demotion):

```json
{
  "type": "https://api.example.com/problems/bad-request",
  "title": "Bad Request",
  "status": 400,
  "detail": "You cannot remove your own administrator role."
}
```

---

#### `GET /api/v1/admin/cargo-types` — 200

Same as portal cargo-types.

---

### 7.4 Health (`/health/*`)

#### `GET /health` — 200

```json
{
  "data": {
    "status": "ok",
    "service": "Cargo Inspection API",
    "version": "2.0.0",
    "timestamp": "2026-10-13T16:06:16Z"
  }
}
```

---

#### `GET /health/ready` — 200 / 503

```json
{
  "data": {
    "status": "ok",
    "database": "up",
    "latency_ms": 0.7
  }
}
```

503 when the database check fails — a problem document, not an envelope:

```json
{
  "type": "https://api.example.com/problems/service-unavailable",
  "title": "Service Unavailable",
  "status": 503,
  "detail": "psycopg: connection refused"
}
```

---

### 7.5 Root (`/`)

#### `GET /` — 200

```json
{
  "data": {
    "message": "API is running",
    "ui": "/ui/",
    "docs": "/docs",
    "health": "/health"
  }
}
```

---

## 8. JSON Schemas (draft 2020-12)

### 8.1 Envelope

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "https://api.example.com/schemas/envelope.json",
  "title": "Response Envelope",
  "type": "object",
  "required": ["data"],
  "properties": {
    "data": {},
    "meta": { "$ref": "#/$defs/meta" },
    "links": { "$ref": "#/$defs/links" },
    "error": { "$ref": "#/$defs/problem" }
  },
  "$defs": {
    "meta": {
      "type": "object",
      "properties": {
        "pagination": { "$ref": "#/$defs/pagination" },
        "inspection_id": { "type": "integer" },
        "detected_at": { "type": "string", "format": "date-time" },
        "elapsed_seconds": { "type": "number" },
        "image": { "$ref": "#/$defs/image" },
        "expires_in_hours": { "type": "integer" }
      }
    },
    "pagination": {
      "type": "object",
      "required": ["page", "per_page", "total", "total_pages"],
      "properties": {
        "page": { "type": "integer", "minimum": 1 },
        "per_page": { "type": "integer", "minimum": 1, "maximum": 100 },
        "total": { "type": "integer", "minimum": 0 },
        "total_pages": { "type": "integer", "minimum": 0 }
      }
    },
    "image": {
      "type": "object",
      "required": ["width", "height"],
      "properties": {
        "width": { "type": "integer" },
        "height": { "type": "integer" }
      }
    },
    "links": {
      "type": "object",
      "properties": {
        "self": { "type": "string" },
        "overlay": { "type": "string" },
        "next": { "type": "string" },
        "prev": { "type": "string" },
        "first": { "type": "string" },
        "last": { "type": "string" }
      }
    },
    "problem": {
      "type": "object",
      "required": ["type", "title", "status", "detail"],
      "properties": {
        "type": { "type": "string", "format": "uri" },
        "title": { "type": "string" },
        "status": { "type": "integer" },
        "detail": { "type": "string" },
        "errors": {
          "type": "array",
          "items": {
            "type": "object",
            "required": ["field", "message"],
            "properties": {
              "field": { "type": "string" },
              "message": { "type": "string" }
            }
          }
        }
      }
    }
  }
}
```

### 8.2 Rect (geometry)

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "https://api.example.com/schemas/rect.json",
  "title": "Rectangle",
  "type": "object",
  "required": ["x", "y", "w", "h"],
  "properties": {
    "x": { "type": "integer", "description": "Left edge, pixels" },
    "y": { "type": "integer", "description": "Top edge, pixels" },
    "w": { "type": "integer", "description": "Width, pixels" },
    "h": { "type": "integer", "description": "Height, pixels" }
  }
}
```

### 8.3 Detection data

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "https://api.example.com/schemas/detection-data.json",
  "title": "Detection Data",
  "type": "object",
  "required": ["detected"],
  "properties": {
    "detected": { "type": "boolean" },
    "label": { "type": "string" },
    "aggregate_score": { "type": "number" },
    "objects": {
      "type": "array",
      "items": { "$ref": "#/$defs/detectedObject" }
    },
    "box": { "$ref": "https://api.example.com/schemas/rect.json" },
    "mask": {
      "type": "object",
      "properties": {
        "area_ratio": { "type": "number" },
        "border_leak": { "type": "number" }
      }
    },
    "detector_origin": { "type": "string" },
    "uses_zip_taxonomy": { "type": "boolean" },
    "stage": { "type": "string" },
    "timed_out": { "type": "boolean" }
  },
  "$defs": {
    "detectedObject": {
      "type": "object",
      "required": ["label", "yolo_confidence", "sam_score", "mask_area_px", "box"],
      "properties": {
        "label": { "type": "string" },
        "yolo_confidence": { "type": "number" },
        "sam_score": { "type": "number" },
        "mask_area_px": { "type": "integer" },
        "box": { "$ref": "https://api.example.com/schemas/rect.json" },
        "models": {
          "type": "object",
          "properties": {
            "yolo": { "$ref": "https://api.example.com/schemas/rect.json" },
            "sam": { "$ref": "https://api.example.com/schemas/rect.json" }
          }
        }
      }
    }
  }
}
```

### 8.4 Submission (single)

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "https://api.example.com/schemas/submission.json",
  "title": "Submission",
  "type": "object",
  "required": ["id", "user_id", "cargo_type", "status", "image_url", "detection_status", "created_at"],
  "properties": {
    "id": { "type": "integer" },
    "user_id": { "type": "integer" },
    "name": { "type": "string" },
    "email": { "type": "string" },
    "phone": { "type": "string" },
    "cargo_type": { "type": "string" },
    "cargo_label": { "type": "string" },
    "density_kg_m3": { "type": "number" },
    "status": { "type": "string", "enum": ["draft", "submitted", "approved", "rejected"] },
    "status_note": { "type": "string" },
    "notes": { "type": "string" },
    "reviewed_by": { "type": "integer" },
    "reviewed_at": { "type": "string", "format": "date-time" },
    "volume_m3": { "type": "number" },
    "estimated_weight_kg": { "type": "number" },
    "image_filename": { "type": "string" },
    "image_url": { "type": "string" },
    "image_width": { "type": "integer" },
    "image_height": { "type": "integer" },
    "tags": {
      "type": "array",
      "items": {
        "type": "object",
        "required": ["id", "name"],
        "properties": {
          "id": { "type": "integer" },
          "name": { "type": "string" },
          "colour": { "type": "string" }
        }
      }
    },
    "detection_status": { "type": "string", "enum": ["not_run", "detected", "no_cargo", "error"] },
    "detected_at": { "type": "string", "format": "date-time" },
    "cargo_object_count": { "type": "integer" },
    "created_at": { "type": "string", "format": "date-time" },
    "updated_at": { "type": "string", "format": "date-time" }
  }
}
```

### 8.5 User

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "https://api.example.com/schemas/user.json",
  "title": "User",
  "type": "object",
  "required": ["id", "name", "email", "role", "created_at"],
  "properties": {
    "id": { "type": "integer" },
    "name": { "type": "string" },
    "email": { "type": "string" },
    "phone": { "type": "string" },
    "role": { "type": "string", "enum": ["user", "admin"] },
    "is_active": { "type": "boolean" },
    "is_admin": { "type": "boolean" },
    "created_at": { "type": "string", "format": "date-time" },
    "inspection_count": { "type": "integer" },
    "has_password": { "type": "boolean" }
  }
}
```

### 8.6 Cargo type

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "https://api.example.com/schemas/cargo-type.json",
  "title": "Cargo Type",
  "type": "object",
  "required": ["id", "slug", "label"],
  "properties": {
    "id": { "type": "integer" },
    "slug": { "type": "string" },
    "label": { "type": "string" },
    "density_kg_m3": { "type": "number" },
    "description": { "type": "string" }
  }
}
```

### 8.7 Audit entry

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "https://api.example.com/schemas/audit-entry.json",
  "title": "Audit Entry",
  "type": "object",
  "required": ["id", "action", "entity_type", "entity_id", "created_at"],
  "properties": {
    "id": { "type": "integer" },
    "action": { "type": "string" },
    "entity_type": { "type": "string" },
    "entity_id": { "type": "integer" },
    "actor_user_id": { "type": "integer" },
    "detail": { "type": "object" },
    "created_at": { "type": "string", "format": "date-time" }
  }
}
```

---

## 9. OpenAPI 3.1 document

Generated from the running app — `scripts_regen_openapi.py` rewrites this
block from `app.openapi()`, so it cannot drift from the code. No `servers`
block is emitted: every documented path already carries the `/api/v1`
prefix, and a `servers` entry on top of that would double it in Swagger's
"Try it out".

```yaml
openapi: 3.1.0
info:
  title: Cargo Inspection API
  description: Cargo inspection API. Inspections belong to a user; cargo types come from a
    lookup table with density values.
  version: 2.0.0
paths:
  /api/v1/auth/register:
    post:
      tags:
      - Auth
      summary: Create an account and sign in
      operationId: register_api_v1_auth_register_post
      requestBody:
        content:
          application/json:
            schema:
              $ref: '#/components/schemas/RegisterRequest'
        required: true
      responses:
        '201':
          description: Successful Response
          content:
            application/json:
              schema: {}
        '422':
          description: Validation Error
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/HTTPValidationError'
  /api/v1/auth/login:
    post:
      tags:
      - Auth
      summary: Sign in
      operationId: login_api_v1_auth_login_post
      requestBody:
        content:
          application/json:
            schema:
              $ref: '#/components/schemas/LoginRequest'
        required: true
      responses:
        '200':
          description: Successful Response
          content:
            application/json:
              schema: {}
        '422':
          description: Validation Error
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/HTTPValidationError'
  /api/v1/auth/logout:
    post:
      tags:
      - Auth
      summary: Sign out
      operationId: logout_api_v1_auth_logout_post
      responses:
        '200':
          description: Successful Response
          content:
            application/json:
              schema: {}
  /api/v1/auth/me:
    get:
      tags:
      - Auth
      summary: The signed-in user and their permissions (portal bootstrap)
      description: 'Called on page load. A 401 here is how the portal knows to show the

        sign-in screen rather than the dashboard.


        The permission list drives which controls the UI renders.'
      operationId: me_api_v1_auth_me_get
      security:
      - HTTPBearer: []
      parameters:
      - name: session_token
        in: cookie
        required: false
        schema:
          anyOf:
          - type: string
          - type: 'null'
          title: Session Token
      responses:
        '200':
          description: Successful Response
          content:
            application/json:
              schema: {}
        '422':
          description: Validation Error
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/HTTPValidationError'
  /api/v1/auth/set-password:
    post:
      tags:
      - Auth
      summary: Set a password on an account that has none
      description: Bootstrap for the pre-portal accounts, which have no password yet.
      operationId: set_password_api_v1_auth_set_password_post
      security:
      - HTTPBearer: []
      parameters:
      - name: session_token
        in: cookie
        required: false
        schema:
          anyOf:
          - type: string
          - type: 'null'
          title: Session Token
      requestBody:
        required: true
        content:
          application/json:
            schema:
              $ref: '#/components/schemas/SetPasswordRequest'
      responses:
        '200':
          description: Successful Response
          content:
            application/json:
              schema: {}
        '422':
          description: Validation Error
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/HTTPValidationError'
  /api/v1/auth/change-password:
    post:
      tags:
      - Auth
      summary: Change your password
      operationId: change_password_api_v1_auth_change_password_post
      security:
      - HTTPBearer: []
      parameters:
      - name: session_token
        in: cookie
        required: false
        schema:
          anyOf:
          - type: string
          - type: 'null'
          title: Session Token
      requestBody:
        required: true
        content:
          application/json:
            schema:
              $ref: '#/components/schemas/ChangePasswordRequest'
      responses:
        '200':
          description: Successful Response
          content:
            application/json:
              schema: {}
        '422':
          description: Validation Error
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/HTTPValidationError'
  /api/v1/portal/cargo-types:
    get:
      tags:
      - Portal
      summary: Cargo lookup table (reference data, needed by the upload form)
      description: 'Exposed on the portal as well as for admins.


        Cargo slugs and densities are reference data, not sensitive, and the upload

        form cannot render its dropdown without them — so a signed-in user needs

        this even though they hold no admin permission.'
      operationId: portal_cargo_types_api_v1_portal_cargo_types_get
      security:
      - HTTPBearer: []
      parameters:
      - name: session_token
        in: cookie
        required: false
        schema:
          anyOf:
          - type: string
          - type: 'null'
          title: Session Token
      responses:
        '200':
          description: Successful Response
          content:
            application/json:
              schema: {}
        '422':
          description: Validation Error
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/HTTPValidationError'
  /api/v1/portal/summary:
    get:
      tags:
      - Portal
      summary: Counts the dashboard needs (scoped to the signed-in user)
      operationId: portal_summary_api_v1_portal_summary_get
      security:
      - HTTPBearer: []
      parameters:
      - name: session_token
        in: cookie
        required: false
        schema:
          anyOf:
          - type: string
          - type: 'null'
          title: Session Token
      responses:
        '200':
          description: Successful Response
          content:
            application/json:
              schema: {}
        '422':
          description: Validation Error
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/HTTPValidationError'
  /api/v1/portal/submissions:
    get:
      tags:
      - Portal
      summary: My submissions, paginated
      operationId: portal_submissions_api_v1_portal_submissions_get
      security:
      - HTTPBearer: []
      parameters:
      - name: page
        in: query
        required: false
        schema:
          type: integer
          minimum: 1
          default: 1
          title: Page
      - name: per_page
        in: query
        required: false
        schema:
          type: integer
          maximum: 100
          minimum: 1
          description: Cards per page
          default: 6
          title: Per Page
        description: Cards per page
      - name: cargo_type
        in: query
        required: false
        schema:
          anyOf:
          - type: string
          - type: 'null'
          title: Cargo Type
      - name: status
        in: query
        required: false
        schema:
          anyOf:
          - type: string
          - type: 'null'
          title: Status
      - name: tag
        in: query
        required: false
        schema:
          anyOf:
          - type: string
          - type: 'null'
          title: Tag
      - name: search
        in: query
        required: false
        schema:
          anyOf:
          - type: string
          - type: 'null'
          title: Search
      - name: sort
        in: query
        required: false
        schema:
          type: string
          default: -created_at
          title: Sort
      - name: session_token
        in: cookie
        required: false
        schema:
          anyOf:
          - type: string
          - type: 'null'
          title: Session Token
      responses:
        '200':
          description: Successful Response
          content:
            application/json:
              schema: {}
        '422':
          description: Validation Error
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/HTTPValidationError'
    post:
      tags:
      - Portal
      summary: Upload a new submission
      description: 'Upload without re-typing details.


        Name, email and phone come from the signed-in account, so the portal form

        cannot create a duplicate user or attribute a load to someone else.


        `status` is restricted to the self-assignable set: a user choosing

        ''approved'' on their own submission would be approving their own work.'
      operationId: portal_create_submission_api_v1_portal_submissions_post
      security:
      - HTTPBearer: []
      parameters:
      - name: Idempotency-Key
        in: header
        required: false
        schema:
          anyOf:
          - type: string
          - type: 'null'
          title: Idempotency-Key
      - name: session_token
        in: cookie
        required: false
        schema:
          anyOf:
          - type: string
          - type: 'null'
          title: Session Token
      requestBody:
        required: true
        content:
          multipart/form-data:
            schema:
              $ref: '#/components/schemas/Body_portal_create_submission_api_v1_portal_submissions_post'
      responses:
        '201':
          description: Successful Response
          content:
            application/json:
              schema: {}
        '422':
          description: Validation Error
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/HTTPValidationError'
  /api/v1/portal/submissions/{inspection_id}:
    get:
      tags:
      - Portal
      summary: One of the caller's submissions
      operationId: portal_submission_detail_api_v1_portal_submissions__inspection_id__get
      security:
      - HTTPBearer: []
      parameters:
      - name: inspection_id
        in: path
        required: true
        schema:
          type: integer
          title: Inspection Id
      - name: session_token
        in: cookie
        required: false
        schema:
          anyOf:
          - type: string
          - type: 'null'
          title: Session Token
      responses:
        '200':
          description: Successful Response
          content:
            application/json:
              schema: {}
        '422':
          description: Validation Error
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/HTTPValidationError'
    delete:
      tags:
      - Portal
      summary: Withdraw (soft-delete) the caller's submission
      operationId: portal_withdraw_submission_api_v1_portal_submissions__inspection_id__delete
      security:
      - HTTPBearer: []
      parameters:
      - name: inspection_id
        in: path
        required: true
        schema:
          type: integer
          title: Inspection Id
      - name: session_token
        in: cookie
        required: false
        schema:
          anyOf:
          - type: string
          - type: 'null'
          title: Session Token
      responses:
        '204':
          description: Successful Response
        '422':
          description: Validation Error
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/HTTPValidationError'
  /api/v1/portal/submissions/{inspection_id}/image:
    get:
      tags:
      - Portal
      summary: Serve an image the caller owns
      description: 'Image bytes for the caller''s own submission.


        The cross-user `/inspections/{id}/image` route requires the admin

        permission, so the portal needs its own copy — otherwise a signed-in user

        cannot see the thumbnails of their own list.'
      operationId: portal_submission_image_api_v1_portal_submissions__inspection_id__image_get
      security:
      - HTTPBearer: []
      parameters:
      - name: inspection_id
        in: path
        required: true
        schema:
          type: integer
          title: Inspection Id
      - name: session_token
        in: cookie
        required: false
        schema:
          anyOf:
          - type: string
          - type: 'null'
          title: Session Token
      responses:
        '200':
          description: Successful Response
          content:
            application/json:
              schema: {}
        '422':
          description: Validation Error
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/HTTPValidationError'
  /api/v1/portal/detection/availability:
    get:
      tags:
      - Detection
      summary: Whether the detector can run, and why not if it cannot
      description: 'Lets the UI hide the Detect button instead of offering a failing action.


        Cheaper than having a user press a button that returns 503, and it surfaces

        a misconfigured `DETECTION_PYTHON` as a sentence rather than a stack trace.'
      operationId: detection_availability_api_v1_portal_detection_availability_get
      security:
      - HTTPBearer: []
      parameters:
      - name: session_token
        in: cookie
        required: false
        schema:
          anyOf:
          - type: string
          - type: 'null'
          title: Session Token
      responses:
        '200':
          description: Successful Response
          content:
            application/json:
              schema: {}
        '422':
          description: Validation Error
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/HTTPValidationError'
  /api/v1/portal/submissions/{inspection_id}/detect:
    post:
      tags:
      - Detection
      summary: Run cargo detection on one of the caller's submissions
      description: 'Detect and segment cargo in a submission''s image.


        **This blocks for 16-45 s.** The pipeline runs SAM and YOLO on CPU; there

        is no queue and no background task, so the response arrives when the run

        finishes. `DETECTION_TIMEOUT` (default 300 s) caps it.


        **A refusal is a success.** An image with no cargo returns

        `"detected": false` with HTTP 200, because "nothing there" is a correct

        answer. Only a broken detector produces a non-200 error envelope.


        Re-running replaces the previous result rather than accumulating rows: a

        submission has at most one current detection, and `force=false` returns the

        existing one instead of burning 30 s of CPU to recompute it. The option

        comes from the JSON body (`DetectRequest`), never `?force=` — §5 keeps

        query strings for GET, and a body-less call still works.'
      operationId: detect_submission_api_v1_portal_submissions__inspection_id__detect_post
      security:
      - HTTPBearer: []
      parameters:
      - name: inspection_id
        in: path
        required: true
        schema:
          type: integer
          title: Inspection Id
      - name: session_token
        in: cookie
        required: false
        schema:
          anyOf:
          - type: string
          - type: 'null'
          title: Session Token
      requestBody:
        content:
          application/json:
            schema:
              anyOf:
              - $ref: '#/components/schemas/DetectRequest'
              - type: 'null'
              title: Data
      responses:
        '200':
          description: Successful Response
          content:
            application/json:
              schema: {}
        '422':
          description: Validation Error
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/HTTPValidationError'
  /api/v1/portal/submissions/{inspection_id}/detection:
    get:
      tags:
      - Detection
      summary: Read a submission's stored detection result
      description: The last run's envelope. Never starts a run.
      operationId: get_submission_detection_api_v1_portal_submissions__inspection_id__detection_get
      security:
      - HTTPBearer: []
      parameters:
      - name: inspection_id
        in: path
        required: true
        schema:
          type: integer
          title: Inspection Id
      - name: session_token
        in: cookie
        required: false
        schema:
          anyOf:
          - type: string
          - type: 'null'
          title: Session Token
      responses:
        '200':
          description: Successful Response
          content:
            application/json:
              schema: {}
        '422':
          description: Validation Error
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/HTTPValidationError'
  /api/v1/portal/submissions/{inspection_id}/detection/log:
    get:
      tags:
      - Detection
      summary: Detector stdout tail, for diagnosing a failed run
      description: 'Tail of the detector''s console output for the most recent run.


        Reads the run directory rather than the database, because the traceback

        only ever existed on stdout. Returns an empty tail if the directory has

        since been swept by `cleanup_runs`.'
      operationId: get_submission_detection_log_api_v1_portal_submissions__inspection_id__detection_log_get
      security:
      - HTTPBearer: []
      parameters:
      - name: inspection_id
        in: path
        required: true
        schema:
          type: integer
          title: Inspection Id
      - name: session_token
        in: cookie
        required: false
        schema:
          anyOf:
          - type: string
          - type: 'null'
          title: Session Token
      responses:
        '200':
          description: Successful Response
          content:
            application/json:
              schema: {}
        '422':
          description: Validation Error
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/HTTPValidationError'
  /api/v1/portal/submissions/{inspection_id}/detection/overlay:
    get:
      tags:
      - Detection
      summary: The annotated overlay the pipeline drew
      description: 'PNG with the segmented cargo masked in red and its box drawn.


        A refusal produces no overlay — CELL 10 draws no box when nothing passes

        the acceptance gate — so this 404s.'
      operationId: get_submission_detection_overlay_api_v1_portal_submissions__inspection_id__detection_overlay_get
      security:
      - HTTPBearer: []
      parameters:
      - name: inspection_id
        in: path
        required: true
        schema:
          type: integer
          title: Inspection Id
      - name: session_token
        in: cookie
        required: false
        schema:
          anyOf:
          - type: string
          - type: 'null'
          title: Session Token
      responses:
        '200':
          description: Successful Response
          content:
            application/json:
              schema: {}
        '422':
          description: Validation Error
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/HTTPValidationError'
  /api/v1/portal/submissions/{inspection_id}/lifting-plan:
    get:
      tags:
      - Lifting Plan
      summary: Generate a lifting plan as a Markdown document
      description: 'Generate (or regenerate) the lifting plan for one of the caller''s

        submissions. There is nothing to store and nothing to update: every call

        recomputes from the current detection, so re-running detection is

        reflected immediately.


        `ref_m` + `ref_px` calibrate the pixel box into metric dimensions via one

        known on-site length. Both must be given together or neither is.'
      operationId: lifting_plan_api_v1_portal_submissions__inspection_id__lifting_plan_get
      security:
      - HTTPBearer: []
      parameters:
      - name: inspection_id
        in: path
        required: true
        schema:
          type: integer
          title: Inspection Id
      - name: ref_m
        in: query
        required: false
        schema:
          anyOf:
          - type: number
            exclusiveMinimum: 0
          - type: 'null'
          description: Known on-site reference length in metres
          title: Ref M
        description: Known on-site reference length in metres
      - name: ref_px
        in: query
        required: false
        schema:
          anyOf:
          - type: number
            exclusiveMinimum: 0
          - type: 'null'
          description: That reference's pixel span in the image
          title: Ref Px
        description: That reference's pixel span in the image
      - name: format
        in: query
        required: false
        schema:
          type: string
          pattern: ^(markdown|json)$
          description: markdown = the document; json = same data structured
          default: markdown
          title: Format
        description: markdown = the document; json = same data structured
      - name: session_token
        in: cookie
        required: false
        schema:
          anyOf:
          - type: string
          - type: 'null'
          title: Session Token
      responses:
        '200':
          description: Successful Response
          content:
            application/json:
              schema: {}
        '422':
          description: Validation Error
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/HTTPValidationError'
  /api/v1/admin/submissions:
    get:
      tags:
      - Admin
      summary: Every submission, across all users
      description: No `user_id` is forced here — the whole point is to see everyone.
      operationId: list_all_submissions_api_v1_admin_submissions_get
      security:
      - HTTPBearer: []
      parameters:
      - name: page
        in: query
        required: false
        schema:
          type: integer
          minimum: 1
          default: 1
          title: Page
      - name: per_page
        in: query
        required: false
        schema:
          type: integer
          maximum: 100
          minimum: 1
          default: 20
          title: Per Page
      - name: user_id
        in: query
        required: false
        schema:
          anyOf:
          - type: integer
            minimum: 1
          - type: 'null'
          title: User Id
      - name: cargo_type
        in: query
        required: false
        schema:
          anyOf:
          - type: string
          - type: 'null'
          title: Cargo Type
      - name: status
        in: query
        required: false
        schema:
          anyOf:
          - type: string
          - type: 'null'
          title: Status
      - name: tag
        in: query
        required: false
        schema:
          anyOf:
          - type: string
          - type: 'null'
          title: Tag
      - name: search
        in: query
        required: false
        schema:
          anyOf:
          - type: string
          - type: 'null'
          title: Search
      - name: include_deleted
        in: query
        required: false
        schema:
          type: boolean
          default: false
          title: Include Deleted
      - name: sort
        in: query
        required: false
        schema:
          type: string
          default: -created_at
          title: Sort
      - name: session_token
        in: cookie
        required: false
        schema:
          anyOf:
          - type: string
          - type: 'null'
          title: Session Token
      responses:
        '200':
          description: Successful Response
          content:
            application/json:
              schema: {}
        '422':
          description: Validation Error
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/HTTPValidationError'
    post:
      tags:
      - Admin
      summary: Create a submission on behalf of any user (admin only)
      description: 'Create an inspection on behalf of any user.


        Unlike the portal upload (which derives user from the session), the admin

        supplies the owner''s name/email explicitly. The user is created if needed.'
      operationId: create_submission_admin_api_v1_admin_submissions_post
      security:
      - HTTPBearer: []
      parameters:
      - name: Idempotency-Key
        in: header
        required: false
        schema:
          anyOf:
          - type: string
          - type: 'null'
          title: Idempotency-Key
      - name: session_token
        in: cookie
        required: false
        schema:
          anyOf:
          - type: string
          - type: 'null'
          title: Session Token
      requestBody:
        required: true
        content:
          multipart/form-data:
            schema:
              $ref: '#/components/schemas/Body_create_submission_admin_api_v1_admin_submissions_post'
      responses:
        '201':
          description: Successful Response
          content:
            application/json:
              schema: {}
        '422':
          description: Validation Error
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/HTTPValidationError'
  /api/v1/admin/submissions/pending:
    get:
      tags:
      - Admin
      summary: The review queue
      description: Submitted, not yet decided, oldest first — the work queue.
      operationId: pending_submissions_api_v1_admin_submissions_pending_get
      security:
      - HTTPBearer: []
      parameters:
      - name: page
        in: query
        required: false
        schema:
          type: integer
          minimum: 1
          default: 1
          title: Page
      - name: per_page
        in: query
        required: false
        schema:
          type: integer
          maximum: 100
          minimum: 1
          default: 20
          title: Per Page
      - name: session_token
        in: cookie
        required: false
        schema:
          anyOf:
          - type: string
          - type: 'null'
          title: Session Token
      responses:
        '200':
          description: Successful Response
          content:
            application/json:
              schema: {}
        '422':
          description: Validation Error
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/HTTPValidationError'
  /api/v1/admin/submissions/summary:
    get:
      tags:
      - Admin
      summary: Per-user aggregates
      operationId: summary_admin_api_v1_admin_submissions_summary_get
      security:
      - HTTPBearer: []
      parameters:
      - name: session_token
        in: cookie
        required: false
        schema:
          anyOf:
          - type: string
          - type: 'null'
          title: Session Token
      responses:
        '200':
          description: Successful Response
          content:
            application/json:
              schema: {}
        '422':
          description: Validation Error
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/HTTPValidationError'
  /api/v1/admin/submissions/orphaned-users:
    get:
      tags:
      - Admin
      summary: Users with no inspections (correlated NOT EXISTS)
      description: Users who exist but have never submitted — the onboarding-funnel query.
      operationId: orphaned_users_admin_api_v1_admin_submissions_orphaned_users_get
      security:
      - HTTPBearer: []
      parameters:
      - name: session_token
        in: cookie
        required: false
        schema:
          anyOf:
          - type: string
          - type: 'null'
          title: Session Token
      responses:
        '200':
          description: Successful Response
          content:
            application/json:
              schema: {}
        '422':
          description: Validation Error
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/HTTPValidationError'
  /api/v1/admin/submissions/{inspection_id}:
    get:
      tags:
      - Admin
      summary: Get Any Submission
      description: 'Read any submission, including one an owner has withdrawn.


        Admins need the withdrawn rows to audit a dispute, so `include_deleted`

        is honoured here rather than filtering them out unconditionally.'
      operationId: get_any_submission_api_v1_admin_submissions__inspection_id__get
      security:
      - HTTPBearer: []
      parameters:
      - name: inspection_id
        in: path
        required: true
        schema:
          type: integer
          title: Inspection Id
      - name: include_deleted
        in: query
        required: false
        schema:
          type: boolean
          default: false
          title: Include Deleted
      - name: session_token
        in: cookie
        required: false
        schema:
          anyOf:
          - type: string
          - type: 'null'
          title: Session Token
      responses:
        '200':
          description: Successful Response
          content:
            application/json:
              schema: {}
        '422':
          description: Validation Error
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/HTTPValidationError'
    patch:
      tags:
      - Admin
      summary: Partial update (admin only)
      description: 'Admin partial update: change status, notes, tags, cargo_type, etc.


        The portal restricts users to `SELF_ASSIGNABLE_STATUSES`; admins can set any

        valid status. Use the approve/reject endpoints for the review workflow

        (they also record `reviewed_by`/`reviewed_at` and write an audit entry).'
      operationId: patch_submission_api_v1_admin_submissions__inspection_id__patch
      security:
      - HTTPBearer: []
      parameters:
      - name: inspection_id
        in: path
        required: true
        schema:
          type: integer
          title: Inspection Id
      - name: session_token
        in: cookie
        required: false
        schema:
          anyOf:
          - type: string
          - type: 'null'
          title: Session Token
      requestBody:
        required: true
        content:
          application/json:
            schema:
              $ref: '#/components/schemas/InspectionUpdate'
      responses:
        '200':
          description: Successful Response
          content:
            application/json:
              schema: {}
        '422':
          description: Validation Error
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/HTTPValidationError'
    delete:
      tags:
      - Admin
      summary: Withdraw (soft-delete) any submission
      description: 'Hide the row without destroying it. Restorable, still listed with

        `include_deleted=true`, still counted out of aggregates — the same

        withdraw semantics as the portal, applied cross-user.


        DELETE is idempotent (§5): withdrawing an already-withdrawn submission

        is still 204. Only a submission that never existed 404s.'
      operationId: withdraw_submission_admin_api_v1_admin_submissions__inspection_id__delete
      security:
      - HTTPBearer: []
      parameters:
      - name: inspection_id
        in: path
        required: true
        schema:
          type: integer
          title: Inspection Id
      - name: session_token
        in: cookie
        required: false
        schema:
          anyOf:
          - type: string
          - type: 'null'
          title: Session Token
      responses:
        '204':
          description: Successful Response
        '422':
          description: Validation Error
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/HTTPValidationError'
  /api/v1/admin/submissions/{inspection_id}/approve:
    post:
      tags:
      - Admin
      summary: Approve a submission
      description: '`POST` because approving is a non-idempotent state transition (§5).


        The optional note comes from the JSON body, not `?note=` — a mutation''s

        payload belongs in the body, and this is what the admin UI already sends.'
      operationId: approve_submission_api_v1_admin_submissions__inspection_id__approve_post
      security:
      - HTTPBearer: []
      parameters:
      - name: inspection_id
        in: path
        required: true
        schema:
          type: integer
          title: Inspection Id
      - name: session_token
        in: cookie
        required: false
        schema:
          anyOf:
          - type: string
          - type: 'null'
          title: Session Token
      requestBody:
        content:
          application/json:
            schema:
              anyOf:
              - $ref: '#/components/schemas/DecisionRequest'
              - type: 'null'
              title: Data
      responses:
        '200':
          description: Successful Response
          content:
            application/json:
              schema: {}
        '422':
          description: Validation Error
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/HTTPValidationError'
  /api/v1/admin/submissions/{inspection_id}/reject:
    post:
      tags:
      - Admin
      summary: Reject a submission
      description: 'Same contract as approve: body carries the optional note.'
      operationId: reject_submission_api_v1_admin_submissions__inspection_id__reject_post
      security:
      - HTTPBearer: []
      parameters:
      - name: inspection_id
        in: path
        required: true
        schema:
          type: integer
          title: Inspection Id
      - name: session_token
        in: cookie
        required: false
        schema:
          anyOf:
          - type: string
          - type: 'null'
          title: Session Token
      requestBody:
        content:
          application/json:
            schema:
              anyOf:
              - $ref: '#/components/schemas/DecisionRequest'
              - type: 'null'
              title: Data
      responses:
        '200':
          description: Successful Response
          content:
            application/json:
              schema: {}
        '422':
          description: Validation Error
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/HTTPValidationError'
  /api/v1/admin/submissions/bulk:
    post:
      tags:
      - Admin
      summary: Approve or reject many at once
      description: 'Body: `{"ids": [1, 2], "action": "approve", "note": "..."}`.


        Each id is processed independently: one bad row does not abort the batch, and

        the response reports what happened to each.'
      operationId: bulk_decide_api_v1_admin_submissions_bulk_post
      security:
      - HTTPBearer: []
      parameters:
      - name: session_token
        in: cookie
        required: false
        schema:
          anyOf:
          - type: string
          - type: 'null'
          title: Session Token
      requestBody:
        required: true
        content:
          application/json:
            schema:
              $ref: '#/components/schemas/BulkDecisionRequest'
      responses:
        '200':
          description: Successful Response
          content:
            application/json:
              schema: {}
        '422':
          description: Validation Error
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/HTTPValidationError'
  /api/v1/admin/submissions/{inspection_id}/detection:
    get:
      tags:
      - Admin
      summary: Read any submission's detection result
      description: 'Admin counterpart of `/portal/submissions/{id}/detection`.


        Read-only on purpose: an admin reviewing a queue should not be able to burn

        30 s of CPU on someone''s submission, and a detection result is not part of

        the approve/reject decision. Admins re-run detection as the owner would.


        Returns `status: "not_run"` rather than 404 when nothing has been detected

        yet — the submission exists, it simply has no result, and conflating those

        would be misleading.'
      operationId: admin_submission_detection_api_v1_admin_submissions__inspection_id__detection_get
      security:
      - HTTPBearer: []
      parameters:
      - name: inspection_id
        in: path
        required: true
        schema:
          type: integer
          title: Inspection Id
      - name: include_deleted
        in: query
        required: false
        schema:
          type: boolean
          default: true
          title: Include Deleted
      - name: session_token
        in: cookie
        required: false
        schema:
          anyOf:
          - type: string
          - type: 'null'
          title: Session Token
      responses:
        '200':
          description: Successful Response
          content:
            application/json:
              schema: {}
        '422':
          description: Validation Error
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/HTTPValidationError'
  /api/v1/admin/submissions/{inspection_id}/detection/overlay:
    get:
      tags:
      - Admin
      summary: Serve any submission's detection overlay
      description: Admin counterpart of the portal's overlay route.
      operationId: admin_submission_detection_overlay_api_v1_admin_submissions__inspection_id__detection_overlay_get
      security:
      - HTTPBearer: []
      parameters:
      - name: inspection_id
        in: path
        required: true
        schema:
          type: integer
          title: Inspection Id
      - name: include_deleted
        in: query
        required: false
        schema:
          type: boolean
          default: true
          title: Include Deleted
      - name: session_token
        in: cookie
        required: false
        schema:
          anyOf:
          - type: string
          - type: 'null'
          title: Session Token
      responses:
        '200':
          description: Successful Response
          content:
            application/json:
              schema: {}
        '422':
          description: Validation Error
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/HTTPValidationError'
  /api/v1/admin/submissions/{inspection_id}/image:
    get:
      tags:
      - Admin
      summary: Serve any image
      description: 'Admin counterpart of `/portal/submissions/{id}/image`.


        Defaults to including withdrawn rows: an admin reviewing a dispute needs

        the image even after the owner withdrew the submission.'
      operationId: admin_submission_image_api_v1_admin_submissions__inspection_id__image_get
      security:
      - HTTPBearer: []
      parameters:
      - name: inspection_id
        in: path
        required: true
        schema:
          type: integer
          title: Inspection Id
      - name: include_deleted
        in: query
        required: false
        schema:
          type: boolean
          default: true
          title: Include Deleted
      - name: session_token
        in: cookie
        required: false
        schema:
          anyOf:
          - type: string
          - type: 'null'
          title: Session Token
      responses:
        '200':
          description: Successful Response
          content:
            application/json:
              schema: {}
        '422':
          description: Validation Error
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/HTTPValidationError'
  /api/v1/admin/submissions/{inspection_id}/restore:
    post:
      tags:
      - Admin
      summary: Restore Submission
      operationId: restore_submission_api_v1_admin_submissions__inspection_id__restore_post
      security:
      - HTTPBearer: []
      parameters:
      - name: inspection_id
        in: path
        required: true
        schema:
          type: integer
          title: Inspection Id
      - name: session_token
        in: cookie
        required: false
        schema:
          anyOf:
          - type: string
          - type: 'null'
          title: Session Token
      responses:
        '200':
          description: Successful Response
          content:
            application/json:
              schema: {}
        '422':
          description: Validation Error
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/HTTPValidationError'
  /api/v1/admin/submissions/{inspection_id}/purge:
    delete:
      tags:
      - Admin
      summary: Permanently delete
      operationId: purge_submission_api_v1_admin_submissions__inspection_id__purge_delete
      security:
      - HTTPBearer: []
      parameters:
      - name: inspection_id
        in: path
        required: true
        schema:
          type: integer
          title: Inspection Id
      - name: session_token
        in: cookie
        required: false
        schema:
          anyOf:
          - type: string
          - type: 'null'
          title: Session Token
      responses:
        '204':
          description: Successful Response
        '422':
          description: Validation Error
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/HTTPValidationError'
  /api/v1/admin/stats:
    get:
      tags:
      - Admin
      summary: Platform-wide numbers
      operationId: platform_stats_api_v1_admin_stats_get
      security:
      - HTTPBearer: []
      parameters:
      - name: session_token
        in: cookie
        required: false
        schema:
          anyOf:
          - type: string
          - type: 'null'
          title: Session Token
      responses:
        '200':
          description: Successful Response
          content:
            application/json:
              schema: {}
        '422':
          description: Validation Error
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/HTTPValidationError'
  /api/v1/admin/audit:
    get:
      tags:
      - Admin
      summary: Recent audit entries
      operationId: read_audit_api_v1_admin_audit_get
      security:
      - HTTPBearer: []
      parameters:
      - name: page
        in: query
        required: false
        schema:
          type: integer
          minimum: 1
          default: 1
          title: Page
      - name: per_page
        in: query
        required: false
        schema:
          type: integer
          maximum: 100
          minimum: 1
          default: 50
          title: Per Page
      - name: entity_type
        in: query
        required: false
        schema:
          anyOf:
          - type: string
          - type: 'null'
          title: Entity Type
      - name: action
        in: query
        required: false
        schema:
          anyOf:
          - type: string
          - type: 'null'
          title: Action
      - name: session_token
        in: cookie
        required: false
        schema:
          anyOf:
          - type: string
          - type: 'null'
          title: Session Token
      responses:
        '200':
          description: Successful Response
          content:
            application/json:
              schema: {}
        '422':
          description: Validation Error
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/HTTPValidationError'
  /api/v1/admin/cargo-types:
    get:
      tags:
      - Admin
      summary: Cargo lookup table (admin)
      description: Admin counterpart of `/portal/cargo-types`.
      operationId: list_cargo_types_admin_api_v1_admin_cargo_types_get
      security:
      - HTTPBearer: []
      parameters:
      - name: session_token
        in: cookie
        required: false
        schema:
          anyOf:
          - type: string
          - type: 'null'
          title: Session Token
      responses:
        '200':
          description: Successful Response
          content:
            application/json:
              schema: {}
        '422':
          description: Validation Error
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/HTTPValidationError'
  /api/v1/admin/users:
    get:
      tags:
      - Admin
      summary: All users
      operationId: list_users_admin_api_v1_admin_users_get
      security:
      - HTTPBearer: []
      parameters:
      - name: page
        in: query
        required: false
        schema:
          type: integer
          minimum: 1
          default: 1
          title: Page
      - name: per_page
        in: query
        required: false
        schema:
          type: integer
          maximum: 100
          minimum: 1
          default: 100
          title: Per Page
      - name: session_token
        in: cookie
        required: false
        schema:
          anyOf:
          - type: string
          - type: 'null'
          title: Session Token
      responses:
        '200':
          description: Successful Response
          content:
            application/json:
              schema: {}
        '422':
          description: Validation Error
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/HTTPValidationError'
  /api/v1/admin/users/{user_id}:
    get:
      tags:
      - Admin
      summary: Read one user (admin only)
      operationId: get_user_admin_api_v1_admin_users__user_id__get
      security:
      - HTTPBearer: []
      parameters:
      - name: user_id
        in: path
        required: true
        schema:
          type: integer
          title: User Id
      - name: session_token
        in: cookie
        required: false
        schema:
          anyOf:
          - type: string
          - type: 'null'
          title: Session Token
      responses:
        '200':
          description: Successful Response
          content:
            application/json:
              schema: {}
        '422':
          description: Validation Error
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/HTTPValidationError'
    patch:
      tags:
      - Admin
      summary: Change a user's role (admin only)
      description: 'Change one user''s role.


        `PATCH` on the user rather than `POST /users/{id}/role`: this changes part

        of an existing resource, and §5 rejects POST-for-update. The permission

        (`users:manage`), the self-demotion guard and the `set_role` audit action

        are unchanged — only the method and where `role` is carried.'
      operationId: update_user_role_api_v1_admin_users__user_id__patch
      security:
      - HTTPBearer: []
      parameters:
      - name: user_id
        in: path
        required: true
        schema:
          type: integer
          title: User Id
      - name: session_token
        in: cookie
        required: false
        schema:
          anyOf:
          - type: string
          - type: 'null'
          title: Session Token
      requestBody:
        required: true
        content:
          application/json:
            schema:
              $ref: '#/components/schemas/UserRoleUpdate'
      responses:
        '200':
          description: Successful Response
          content:
            application/json:
              schema: {}
        '422':
          description: Validation Error
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/HTTPValidationError'
  /health:
    get:
      tags:
      - Health
      summary: Liveness probe
      description: 'Process-level check. Does not touch the database, so it stays fast and

        keeps reporting healthy during a database outage.'
      operationId: health_health_get
      responses:
        '200':
          description: Successful Response
          content:
            application/json:
              schema: {}
  /health/ready:
    get:
      tags:
      - Health
      summary: Readiness probe
      description: 'Full check including the database. Returns 503 when PostgreSQL is

        unreachable, so a load balancer stops sending traffic — and per §4 the

        503 body is an RFC 9457 problem document, not an envelope.'
      operationId: readiness_health_ready_get
      responses:
        '200':
          description: Successful Response
          content:
            application/json:
              schema: {}
        '503':
          description: A dependency is unavailable
  /:
    get:
      summary: Root
      operationId: root__get
      responses:
        '200':
          description: Successful Response
          content:
            application/json:
              schema: {}
components:
  schemas:
    Body_create_submission_admin_api_v1_admin_submissions_post:
      properties:
        name:
          type: string
          title: Name
        email:
          type: string
          title: Email
        cargo_type:
          type: string
          title: Cargo Type
        phone:
          anyOf:
          - type: string
          - type: 'null'
          title: Phone
        notes:
          anyOf:
          - type: string
          - type: 'null'
          title: Notes
        status:
          type: string
          title: Status
          default: submitted
        tags:
          type: string
          title: Tags
          default: ''
        image:
          type: string
          contentMediaType: application/octet-stream
          title: Image
      type: object
      required:
      - name
      - email
      - cargo_type
      - image
      title: Body_create_submission_admin_api_v1_admin_submissions_post
    Body_portal_create_submission_api_v1_portal_submissions_post:
      properties:
        cargo_type:
          type: string
          title: Cargo Type
        status:
          type: string
          title: Status
          default: submitted
        notes:
          type: string
          title: Notes
          default: ''
        tags:
          type: string
          title: Tags
          default: ''
        image:
          type: string
          contentMediaType: application/octet-stream
          title: Image
      type: object
      required:
      - cargo_type
      - image
      title: Body_portal_create_submission_api_v1_portal_submissions_post
    BulkDecisionRequest:
      properties:
        ids:
          items:
            type: integer
          type: array
          maxItems: 200
          minItems: 1
          title: Ids
        action:
          type: string
          enum:
          - approve
          - reject
          title: Action
        note:
          anyOf:
          - type: string
            maxLength: 300
          - type: 'null'
          title: Note
      type: object
      required:
      - ids
      - action
      title: BulkDecisionRequest
      description: 'Batch approve/reject. Each id is processed independently — one bad

        row does not abort the batch, the response reports per-item outcomes.'
    ChangePasswordRequest:
      properties:
        current_password:
          type: string
          maxLength: 128
          minLength: 1
          title: Current Password
        new_password:
          type: string
          maxLength: 128
          minLength: 8
          title: New Password
      type: object
      required:
      - current_password
      - new_password
      title: ChangePasswordRequest
      description: Rotate an existing password.
    DecisionRequest:
      properties:
        note:
          anyOf:
          - type: string
            maxLength: 300
          - type: 'null'
          title: Note
      type: object
      title: DecisionRequest
      description: 'Reviewer note for a single approve/reject.


        Sent as a JSON body rather than `?note=`: §5 reserves query parameters for

        GET filtering/sorting/pagination, and every other mutation on this router

        already carries a body (`BulkDecisionRequest`, `InspectionUpdate`). The

        admin UI was already sending `{"note": …}` in the body, so a query-only

        parameter silently discarded it.'
    DetectRequest:
      properties:
        force:
          type: boolean
          title: Force
          default: false
      type: object
      title: DetectRequest
      description: 'Options for one detection run — `POST /…/submissions/{id}/detect`.


        A JSON body rather than `?force=true`: §5 of `docs/API_CONVENTIONS.md`

        reserves query parameters for `GET` filtering/sorting/pagination, and this

        is a mutation''s input. It was the last endpoint still taking one from the

        query string (`?note=` was fixed the same way), and

        `tests/test_api_contract.py` now fails if a new one appears.


        The whole body is optional: detection with no options is the common case,

        so a body-less `POST` must keep working.'
    HTTPValidationError:
      properties:
        detail:
          items:
            $ref: '#/components/schemas/ValidationError'
          type: array
          title: Detail
      type: object
      title: HTTPValidationError
    InspectionUpdate:
      properties:
        status:
          anyOf:
          - type: string
            enum:
            - draft
            - submitted
            - approved
            - rejected
          - type: 'null'
          title: Status
        status_note:
          anyOf:
          - type: string
            maxLength: 300
          - type: 'null'
          title: Status Note
        notes:
          anyOf:
          - type: string
            maxLength: 500
          - type: 'null'
          title: Notes
        cargo_type:
          anyOf:
          - type: string
            maxLength: 50
            minLength: 1
          - type: 'null'
          title: Cargo Type
        volume_m3:
          anyOf:
          - type: number
            minimum: 0.0
          - type: 'null'
          title: Volume M3
        estimated_weight_kg:
          anyOf:
          - type: number
            minimum: 0.0
          - type: 'null'
          title: Estimated Weight Kg
        tags:
          anyOf:
          - items:
              type: string
            type: array
            maxItems: 20
          - type: 'null'
          title: Tags
      type: object
      title: InspectionUpdate
      description: Partial update. Only the fields actually sent are applied.
    LoginRequest:
      properties:
        email:
          type: string
          format: email
          title: Email
        password:
          type: string
          maxLength: 128
          minLength: 1
          title: Password
      type: object
      required:
      - email
      - password
      title: LoginRequest
    RegisterRequest:
      properties:
        name:
          type: string
          maxLength: 50
          minLength: 1
          title: Name
        email:
          type: string
          format: email
          title: Email
        phone:
          anyOf:
          - type: string
          - type: 'null'
          title: Phone
        password:
          type: string
          maxLength: 128
          minLength: 8
          title: Password
      type: object
      required:
      - name
      - email
      - password
      title: RegisterRequest
      description: Create a portal account.
    SetPasswordRequest:
      properties:
        password:
          type: string
          maxLength: 128
          minLength: 8
          title: Password
      type: object
      required:
      - password
      title: SetPasswordRequest
      description: First-time password setup for an account that has none.
    UserRoleUpdate:
      properties:
        role:
          type: string
          enum:
          - user
          - admin
          title: Role
      type: object
      required:
      - role
      title: UserRoleUpdate
      description: 'An admin changing someone else''s role — `PATCH /admin/users/{id}`.


        Just `role`, and required: this is a partial update of an existing

        resource, so the method is `PATCH` on the user, not `POST` on a

        `/role` sub-path (see docs/API_CONVENTIONS.md §5, which rejects

        POST-for-update). The other `UserUpdate` fields are self-service edits

        with a different permission and a different audit action.


        A missing `role` is a 422 from this schema rather than a hand-rolled

        check in the handler.'
    ValidationError:
      properties:
        loc:
          items:
            anyOf:
            - type: string
            - type: integer
          type: array
          title: Location
        msg:
          type: string
          title: Message
        type:
          type: string
          title: Error Type
        input:
          title: Input
        ctx:
          type: object
          title: Context
      type: object
      required:
      - loc
      - msg
      - type
      title: ValidationError
  securitySchemes:
    HTTPBearer:
      type: http
      description: Paste the `session_token` JWT from POST /auth/login's Set-Cookie header.
        The browser portal uses the httpOnly cookie instead and needs nothing here.
      scheme: bearer
```
