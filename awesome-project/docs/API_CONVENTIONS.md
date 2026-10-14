# API_CONVENTIONS.md — Global response, request & method standards

Every endpoint in this API follows the conventions below. They are the
contract between the server and every client (browser portal, Swagger UI,
curl, scripts). Where an endpoint's current behaviour diverges, this document
is the target — the divergence is a bug to fix, not a choice to preserve.

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
- `links` values are relative paths (`/portal/submissions/28`), never
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
    "self": "/portal/submissions/31"
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
    "self": "/portal/submissions?page=1&per_page=20",
    "next": "/portal/submissions?page=2&per_page=20"
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
Include `Allow` header.

### Idempotency-Key header (POST & PATCH)

```http
POST /portal/submissions
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

### 7.1 Auth (`/auth/*`)

#### `POST /auth/register` — 201

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
    "self": "/auth/me"
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
| `links.self` | string | ✅ | | `"/auth/me"` |

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

#### `POST /auth/login` — 200

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
    "self": "/auth/me"
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

#### `POST /auth/logout` — 200

Clears the session cookie.

```json
{ "data": { "detail": "Signed out" } }
```

---

#### `GET /auth/me` — 200

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
    "self": "/auth/me"
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

#### `POST /auth/change-password` — 200

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

#### `POST /auth/set-password` — 200

First password for an account that has none.

**Request** (`application/json`): `{ "password": "quay-crane-42" }`

**Response 200**: `{ "data": { "detail": "Password set" } }`

400 if the account already has a password — use `change-password`.

---

### 7.2 Portal submissions (`/portal/*`)

#### `GET /portal/submissions` — 200

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
      "image_url": "/portal/submissions/28/image",
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
    "self": "/portal/submissions?page=1&per_page=6"
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
| `data[].image_url` | string | ✅ | Owner-scoped image path | `"/portal/submissions/28/image"` |
| `data[].detection_status` | string | ✅ | `not_run`/`detected`/`no_cargo`/`error` | `"detected"` |
| `data[].cargo_object_count` | int | ✅ | Detected regions | `2` |
| `data[].created_at` | string | ✅ | ISO 8601 UTC | |
| `meta.pagination.page` | int | ✅ | Current page | `1` |
| `meta.pagination.per_page` | int | ✅ | Page size | `6` |
| `meta.pagination.total` | int | ✅ | Total rows | `1` |
| `meta.pagination.total_pages` | int | ✅ | | `1` |

Query: `page`, `per_page`, `status`, `cargo_type`, `tag`, `search`, `sort`.

---

#### `POST /portal/submissions` — 201

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
    "image_url": "/portal/submissions/29/image",
    "detection_status": "not_run",
    "cargo_object_count": 0,
    "created_at": "2026-10-13T16:06:16Z"
  },
  "links": {
    "self": "/portal/submissions/29"
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

#### `GET /portal/submissions/{id}` — 200

Single submission. Full field set including `tags`, `notes`, `reviewed_by`,
`reviewed_at`, `volume_m3`, `estimated_weight_kg`, `detection_status`,
`detected_at`, `cargo_object_count`.

---

#### `DELETE /portal/submissions/{id}` — 204

Withdraw (soft-delete). Empty body — no envelope, not even `null`.
Idempotent: repeating the delete is still 204, not 404.

---

#### `GET /portal/submissions/{id}/image` — 200

Image bytes. `Content-Type` from stored metadata.

---

#### `POST /portal/submissions/{id}/detect` — 200

Run detection. Blocks 16–45 s. Returns the detection envelope (see §7.3).

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

#### `GET /portal/submissions/{id}/detection` — 200

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
      "overlay": "/portal/submissions/28/detection/overlay"
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

#### `GET /portal/submissions/{id}/detection/log` — 200

Detector stdout tail for the most recent run — for diagnosing a failed one.

```json
{
  "data": { "inspection_id": 28, "returncode": 0, "stdout_tail": "[runner] OK" }
}
```

`returncode` is `0` once a run exists and `1` before any run; the tail is
empty when the run directory has since been swept by `cleanup_runs`.

---

#### `GET /portal/submissions/{id}/detection/overlay` — 200

PNG bytes. 404 when nothing was detected.

---

#### `GET /portal/submissions/{id}/lifting_plan` — 200

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

#### `GET /portal/detection/availability` — 200

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

#### `GET /portal/cargo-types` — 200

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

#### `GET /portal/summary` — 200

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

### 7.3 Admin (`/admin/*`)

All admin endpoints require `role == admin` (middleware + dependency).
Another user's resource → 404, never 403.

#### `GET /admin/submissions` — 200

Cross-user list. Same shape as portal list. Query: `page`, `per_page`,
`user_id`, `cargo_type`, `status`, `tag`, `search`, `include_deleted`, `sort`.

---

#### `POST /admin/submissions` — 201

Create on behalf of any user. `multipart/form-data` with `name`, `email`,
`cargo_type`, `phone`, `notes`, `status`, `tags`, `image`.

---

#### `GET /admin/submissions/pending` — 200

Review queue. `status=submitted`, oldest first.

---

#### `GET /admin/submissions/summary` — 200

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

#### `GET /admin/submissions/orphaned-users` — 200

Users with zero inspections.

```json
{
  "data": [
    { "id": 9, "name": "Nobody", "email": "nobody@example.com" }
  ]
}
```

---

#### `GET /admin/submissions/{id}` — 200

Any submission, including soft-deleted (`include_deleted=true`).

---

#### `PATCH /admin/submissions/{id}` — 200

Partial update. Body: `application/merge-patch+json` or `application/json`.

---

#### `DELETE /admin/submissions/{id}` — 204

Withdraw (soft-delete). Idempotent: repeating the delete is still 204.

---

#### `DELETE /admin/submissions/{id}/purge` — 204

Hard delete.

---

#### `POST /admin/submissions/{id}/approve` — 200

Query: `note`. Sets `status=approved`, `reviewed_by`, `reviewed_at`.

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

#### `POST /admin/submissions/{id}/reject` — 200

Query: `note`. Sets `status=rejected`.

---

#### `POST /admin/submissions/{id}/restore` — 200

Un-withdraw a soft-deleted submission.

---

#### `POST /admin/submissions/bulk` — 200

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

#### `GET /admin/submissions/{id}/detection` — 200

Same envelope as portal detection. Read-only.

---

#### `GET /admin/submissions/{id}/detection/overlay` — 200

PNG bytes.

---

#### `GET /admin/submissions/{id}/image` — 200

Original upload bytes.

---

#### `GET /admin/stats` — 200

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

#### `GET /admin/audit` — 200

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
    "self": "/admin/audit?page=1&per_page=20",
    "next": "/admin/audit?page=2&per_page=20"
  }
}
```

Query: `page`, `per_page`, `entity_type`, `action`.

---

#### `GET /admin/users` — 200

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
    "self": "/admin/users?page=1&per_page=100"
  }
}
```

---

#### `GET /admin/users/{id}` — 200

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
    "self": "/admin/users/7"
  }
}
```

---

#### `POST /admin/users/{id}/role` — 200

Query: `role` (`user`|`admin`).

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

#### `GET /admin/cargo-types` — 200

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

```yaml
openapi: 3.1.0
info:
  title: Cargo Inspection API
  version: "2.0.0"
  description: |
    Cargo inspection portal with SAM/YOLO detection and lifting-plan
    generation. All responses use the envelope defined in
    `docs/API_CONVENTIONS.md`.
servers:
  - url: http://127.0.0.1:8000
tags:
  - name: Auth
  - name: Portal
  - name: Detection
  - name: Lifting Plan
  - name: Admin
  - name: Health

paths:
  /:
    get:
      operationId: root_index
      summary: API entry point
      tags: [Portal]
      responses:
        "200":
          description: Running
          content:
            application/json:
              schema:
                $ref: "#/components/schemas/Envelope"

  /health:
    get:
      operationId: health_check
      summary: Liveness probe
      tags: [Health]
      responses:
        "200":
          description: Alive
          content:
            application/json:
              schema:
                $ref: "#/components/schemas/Envelope"

  /health/ready:
    get:
      operationId: health_ready
      summary: Readiness probe
      tags: [Health]
      responses:
        "200":
          description: Ready
          content:
            application/json:
              schema:
                $ref: "#/components/schemas/Envelope"
        "503":
          description: Not ready
          content:
            application/problem+json:
              schema:
                $ref: "#/components/schemas/Problem"

  /auth/register:
    post:
      operationId: auth_register
      summary: Create account and sign in
      tags: [Auth]
      requestBody:
        required: true
        content:
          application/json:
            schema:
              type: object
              required: [name, email, password]
              properties:
                name: { type: string, minLength: 1, maxLength: 50 }
                email: { type: string, format: email }
                phone: { type: string, pattern: "^[0-9]{10,15}$" }
                password: { type: string, minLength: 8, maxLength: 128 }
      responses:
        "201":
          description: Created
          headers:
            Location:
              schema: { type: string }
          content:
            application/json:
              schema:
                $ref: "#/components/schemas/Envelope"
        "409":
          $ref: "#/components/responses/Conflict"

  /auth/login:
    post:
      operationId: auth_login
      summary: Sign in
      tags: [Auth]
      requestBody:
        required: true
        content:
          application/json:
            schema:
              type: object
              required: [email, password]
              properties:
                email: { type: string, format: email }
                password: { type: string, minLength: 1, maxLength: 128 }
      responses:
        "200":
          description: Signed in
          content:
            application/json:
              schema:
                $ref: "#/components/schemas/Envelope"
        "401":
          $ref: "#/components/responses/Unauthorized"

  /auth/logout:
    post:
      operationId: auth_logout
      summary: Sign out
      tags: [Auth]
      responses:
        "200":
          description: Signed out
          content:
            application/json:
              schema:
                $ref: "#/components/schemas/Envelope"

  /auth/me:
    get:
      operationId: auth_me
      summary: Current user and permissions
      tags: [Auth]
      responses:
        "200":
          description: Current user
          content:
            application/json:
              schema:
                $ref: "#/components/schemas/Envelope"
        "401":
          $ref: "#/components/responses/Unauthorized"

  /auth/change-password:
    post:
      operationId: auth_change_password
      summary: Change password
      tags: [Auth]
      requestBody:
        required: true
        content:
          application/json:
            schema:
              type: object
              required: [current_password, new_password]
              properties:
                current_password: { type: string }
                new_password: { type: string, minLength: 8, maxLength: 128 }
      responses:
        "200":
          description: Changed
          content:
            application/json:
              schema:
                $ref: "#/components/schemas/Envelope"
        "401":
          $ref: "#/components/responses/Unauthorized"

  /auth/set-password:
    post:
      operationId: auth_set_password
      summary: Set first password
      tags: [Auth]
      requestBody:
        required: true
        content:
          application/json:
            schema:
              type: object
              required: [password]
              properties:
                password: { type: string, minLength: 8, maxLength: 128 }
      responses:
        "200":
          description: Password set
          content:
            application/json:
              schema:
                $ref: "#/components/schemas/Envelope"

  /portal/submissions:
    get:
      operationId: portal_list_submissions
      summary: My submissions
      tags: [Portal]
      parameters:
        - { name: page, in: query, schema: { type: integer, default: 1 } }
        - { name: per_page, in: query, schema: { type: integer, default: 6, maximum: 100 } }
        - { name: status, in: query, schema: { type: string } }
        - { name: cargo_type, in: query, schema: { type: string } }
        - { name: tag, in: query, schema: { type: string } }
        - { name: search, in: query, schema: { type: string } }
        - { name: sort, in: query, schema: { type: string, default: "-created_at" } }
      responses:
        "200":
          description: Paginated list
          content:
            application/json:
              schema:
                $ref: "#/components/schemas/Envelope"
        "401":
          $ref: "#/components/responses/Unauthorized"
    post:
      operationId: portal_create_submission
      summary: Upload a submission
      tags: [Portal]
      parameters:
        - name: Idempotency-Key
          in: header
          schema: { type: string, format: uuid }
      requestBody:
        required: true
        content:
          multipart/form-data:
            schema:
              type: object
              required: [cargo_type, image]
              properties:
                cargo_type: { type: string }
                status: { type: string, default: submitted }
                notes: { type: string }
                tags: { type: string }
                image: { type: string, format: binary }
      responses:
        "201":
          description: Created
          headers:
            Location:
              schema: { type: string }
          content:
            application/json:
              schema:
                $ref: "#/components/schemas/Envelope"
        "403":
          $ref: "#/components/responses/Forbidden"

  /portal/submissions/{inspection_id}:
    get:
      operationId: portal_get_submission
      summary: One of my submissions
      tags: [Portal]
      parameters:
        - { name: inspection_id, in: path, required: true, schema: { type: integer } }
      responses:
        "200":
          description: Submission
          content:
            application/json:
              schema:
                $ref: "#/components/schemas/Envelope"
        "404":
          $ref: "#/components/responses/NotFound"
    delete:
      operationId: portal_withdraw_submission
      summary: Withdraw (soft-delete)
      tags: [Portal]
      parameters:
        - { name: inspection_id, in: path, required: true, schema: { type: integer } }
      responses:
        "204":
          description: Withdrawn
        "404":
          $ref: "#/components/responses/NotFound"

  /portal/submissions/{inspection_id}/image:
    get:
      operationId: portal_submission_image
      summary: Submission image bytes
      tags: [Portal]
      parameters:
        - { name: inspection_id, in: path, required: true, schema: { type: integer } }
      responses:
        "200":
          description: Image
          content:
            image/*:
              schema: { type: string, format: binary }
        "404":
          $ref: "#/components/responses/NotFound"

  /portal/submissions/{inspection_id}/detect:
    post:
      operationId: portal_detect_submission
      summary: Run cargo detection (blocks 16-45s)
      tags: [Detection]
      parameters:
        - { name: inspection_id, in: path, required: true, schema: { type: integer } }
        - { name: force, in: query, schema: { type: boolean, default: false } }
      responses:
        "200":
          description: Detection result
          content:
            application/json:
              schema:
                $ref: "#/components/schemas/Envelope"
        "502":
          $ref: "#/components/responses/DetectionFailed"
        "503":
          $ref: "#/components/responses/ServiceUnavailable"
        "504":
          $ref: "#/components/responses/DetectionTimeout"

  /portal/submissions/{inspection_id}/detection:
    get:
      operationId: portal_get_detection
      summary: Stored detection result
      tags: [Detection]
      parameters:
        - { name: inspection_id, in: path, required: true, schema: { type: integer } }
      responses:
        "200":
          description: Detection result
          content:
            application/json:
              schema:
                $ref: "#/components/schemas/Envelope"
        "404":
          $ref: "#/components/responses/NotFound"

  /portal/submissions/{inspection_id}/detection/overlay:
    get:
      operationId: portal_detection_overlay
      summary: Annotated overlay PNG
      tags: [Detection]
      parameters:
        - { name: inspection_id, in: path, required: true, schema: { type: integer } }
      responses:
        "200":
          description: PNG
          content:
            image/png:
              schema: { type: string, format: binary }
        "404":
          $ref: "#/components/responses/NotFound"

  /portal/submissions/{inspection_id}/detection/log:
    get:
      operationId: portal_detection_log
      summary: Detector stdout tail
      tags: [Detection]
      parameters:
        - { name: inspection_id, in: path, required: true, schema: { type: integer } }
      responses:
        "200":
          description: Log tail
          content:
            application/json:
              schema:
                $ref: "#/components/schemas/Envelope"

  /portal/submissions/{inspection_id}/lifting_plan:
    get:
      operationId: portal_lifting_plan
      summary: Generate lifting plan Markdown
      tags: [Lifting Plan]
      parameters:
        - { name: inspection_id, in: path, required: true, schema: { type: integer } }
        - { name: ref_m, in: query, schema: { type: number, exclusiveMinimum: 0 } }
        - { name: ref_px, in: query, schema: { type: number, exclusiveMinimum: 0 } }
        - name: format
          in: query
          schema: { type: string, enum: [markdown, json], default: markdown }
      responses:
        "200":
          description: Markdown document
          content:
            text/markdown:
              schema: { type: string }
            application/json:
              description: Only with `format=json` — the same data enveloped
              schema:
                $ref: "#/components/schemas/Envelope"
        "422":
          $ref: "#/components/responses/Unprocessable"

  /portal/detection/availability:
    get:
      operationId: portal_detection_availability
      summary: Detector availability
      tags: [Detection]
      responses:
        "200":
          description: Availability
          content:
            application/json:
              schema:
                $ref: "#/components/schemas/Envelope"

  /portal/cargo-types:
    get:
      operationId: portal_cargo_types
      summary: Cargo lookup table
      tags: [Portal]
      responses:
        "200":
          description: Cargo types
          content:
            application/json:
              schema:
                $ref: "#/components/schemas/Envelope"

  /portal/summary:
    get:
      operationId: portal_summary
      summary: Dashboard counts
      tags: [Portal]
      responses:
        "200":
          description: Summary
          content:
            application/json:
              schema:
                $ref: "#/components/schemas/Envelope"

  /admin/submissions:
    get:
      operationId: admin_list_submissions
      summary: All submissions
      tags: [Admin]
      parameters:
        - { name: page, in: query, schema: { type: integer, default: 1 } }
        - { name: per_page, in: query, schema: { type: integer, default: 20, maximum: 100 } }
        - { name: user_id, in: query, schema: { type: integer } }
        - { name: cargo_type, in: query, schema: { type: string } }
        - { name: status, in: query, schema: { type: string } }
        - { name: tag, in: query, schema: { type: string } }
        - { name: search, in: query, schema: { type: string } }
        - { name: include_deleted, in: query, schema: { type: boolean, default: false } }
        - { name: sort, in: query, schema: { type: string, default: "-created_at" } }
      responses:
        "200":
          description: Paginated list
          content:
            application/json:
              schema:
                $ref: "#/components/schemas/Envelope"
        "403":
          $ref: "#/components/responses/Forbidden"

  /admin/submissions/{inspection_id}:
    get:
      operationId: admin_get_submission
      summary: Any submission
      tags: [Admin]
      parameters:
        - { name: inspection_id, in: path, required: true, schema: { type: integer } }
        - { name: include_deleted, in: query, schema: { type: boolean, default: false } }
      responses:
        "200":
          description: Submission
          content:
            application/json:
              schema:
                $ref: "#/components/schemas/Envelope"
        "404":
          $ref: "#/components/responses/NotFound"
    patch:
      operationId: admin_patch_submission
      summary: Partial update
      tags: [Admin]
      parameters:
        - { name: inspection_id, in: path, required: true, schema: { type: integer } }
      requestBody:
        required: true
        content:
          application/merge-patch+json:
            schema:
              type: object
              properties:
                status: { type: string }
                status_note: { type: string }
                notes: { type: string }
                tags: { type: array, items: { type: string } }
      responses:
        "200":
          description: Updated
          content:
            application/json:
              schema:
                $ref: "#/components/schemas/Envelope"
        "404":
          $ref: "#/components/responses/NotFound"
    delete:
      operationId: admin_withdraw_submission
      summary: Withdraw (soft-delete)
      tags: [Admin]
      parameters:
        - { name: inspection_id, in: path, required: true, schema: { type: integer } }
      responses:
        "204":
          description: Withdrawn
        "404":
          $ref: "#/components/responses/NotFound"

  /admin/submissions/{inspection_id}/approve:
    post:
      operationId: admin_approve_submission
      summary: Approve
      tags: [Admin]
      parameters:
        - { name: inspection_id, in: path, required: true, schema: { type: integer } }
        - { name: note, in: query, schema: { type: string, maxLength: 300 } }
      responses:
        "200":
          description: Approved
          content:
            application/json:
              schema:
                $ref: "#/components/schemas/Envelope"
        "409":
          $ref: "#/components/responses/Conflict"

  /admin/submissions/{inspection_id}/reject:
    post:
      operationId: admin_reject_submission
      summary: Reject
      tags: [Admin]
      parameters:
        - { name: inspection_id, in: path, required: true, schema: { type: integer } }
        - { name: note, in: query, schema: { type: string, maxLength: 300 } }
      responses:
        "200":
          description: Rejected
          content:
            application/json:
              schema:
                $ref: "#/components/schemas/Envelope"
        "409":
          $ref: "#/components/responses/Conflict"

  /admin/submissions/{inspection_id}/restore:
    post:
      operationId: admin_restore_submission
      summary: Restore withdrawn
      tags: [Admin]
      parameters:
        - { name: inspection_id, in: path, required: true, schema: { type: integer } }
      responses:
        "200":
          description: Restored
          content:
            application/json:
              schema:
                $ref: "#/components/schemas/Envelope"
        "404":
          $ref: "#/components/responses/NotFound"

  /admin/submissions/{inspection_id}/purge:
    delete:
      operationId: admin_purge_submission
      summary: Hard delete
      tags: [Admin]
      parameters:
        - { name: inspection_id, in: path, required: true, schema: { type: integer } }
      responses:
        "204":
          description: Purged
        "404":
          $ref: "#/components/responses/NotFound"

  /admin/submissions/bulk:
    post:
      operationId: admin_bulk_decide
      summary: Approve or reject many
      tags: [Admin]
      requestBody:
        required: true
        content:
          application/json:
            schema:
              type: object
              required: [ids, action]
              properties:
                ids:
                  type: array
                  items: { type: integer }
                  maxItems: 200
                action: { type: string, enum: [approve, reject] }
                note: { type: string, maxLength: 300 }
      responses:
        "200":
          description: Per-item results
          content:
            application/json:
              schema:
                $ref: "#/components/schemas/Envelope"
        "422":
          $ref: "#/components/responses/Unprocessable"

  /admin/submissions/pending:
    get:
      operationId: admin_pending_submissions
      summary: Review queue
      tags: [Admin]
      parameters:
        - { name: page, in: query, schema: { type: integer, default: 1 } }
        - { name: per_page, in: query, schema: { type: integer, default: 20, maximum: 100 } }
      responses:
        "200":
          description: Paginated queue
          content:
            application/json:
              schema:
                $ref: "#/components/schemas/Envelope"

  /admin/submissions/summary:
    get:
      operationId: admin_submissions_summary
      summary: Per-user aggregates
      tags: [Admin]
      responses:
        "200":
          description: Aggregates
          content:
            application/json:
              schema:
                $ref: "#/components/schemas/Envelope"

  /admin/submissions/orphaned-users:
    get:
      operationId: admin_orphaned_users
      summary: Users with no inspections
      tags: [Admin]
      responses:
        "200":
          description: Orphaned users
          content:
            application/json:
              schema:
                $ref: "#/components/schemas/Envelope"

  /admin/submissions/{inspection_id}/detection:
    get:
      operationId: admin_get_detection
      summary: Any submission's detection
      tags: [Admin, Detection]
      parameters:
        - { name: inspection_id, in: path, required: true, schema: { type: integer } }
        - { name: include_deleted, in: query, schema: { type: boolean, default: true } }
      responses:
        "200":
          description: Detection result
          content:
            application/json:
              schema:
                $ref: "#/components/schemas/Envelope"
        "404":
          $ref: "#/components/responses/NotFound"

  /admin/submissions/{inspection_id}/detection/overlay:
    get:
      operationId: admin_detection_overlay
      summary: Any submission's overlay
      tags: [Admin, Detection]
      parameters:
        - { name: inspection_id, in: path, required: true, schema: { type: integer } }
      responses:
        "200":
          description: PNG
          content:
            image/png:
              schema: { type: string, format: binary }
        "404":
          $ref: "#/components/responses/NotFound"

  /admin/submissions/{inspection_id}/image:
    get:
      operationId: admin_submission_image
      summary: Any submission's image
      tags: [Admin]
      parameters:
        - { name: inspection_id, in: path, required: true, schema: { type: integer } }
        - { name: include_deleted, in: query, schema: { type: boolean, default: true } }
      responses:
        "200":
          description: Image
          content:
            image/*:
              schema: { type: string, format: binary }
        "404":
          $ref: "#/components/responses/NotFound"

  /admin/stats:
    get:
      operationId: admin_platform_stats
      summary: Platform-wide numbers
      tags: [Admin]
      responses:
        "200":
          description: Stats
          content:
            application/json:
              schema:
                $ref: "#/components/schemas/Envelope"

  /admin/audit:
    get:
      operationId: admin_audit_log
      summary: Audit entries
      tags: [Admin]
      parameters:
        - { name: page, in: query, schema: { type: integer, default: 1 } }
        - { name: per_page, in: query, schema: { type: integer, default: 50, maximum: 100 } }
        - { name: entity_type, in: query, schema: { type: string } }
        - { name: action, in: query, schema: { type: string } }
      responses:
        "200":
          description: Paginated audit
          content:
            application/json:
              schema:
                $ref: "#/components/schemas/Envelope"

  /admin/users:
    get:
      operationId: admin_list_users
      summary: All users
      tags: [Admin]
      parameters:
        - { name: page, in: query, schema: { type: integer, default: 1 } }
        - { name: per_page, in: query, schema: { type: integer, default: 100, maximum: 100 } }
      responses:
        "200":
          description: Paginated users
          content:
            application/json:
              schema:
                $ref: "#/components/schemas/Envelope"

  /admin/users/{user_id}:
    get:
      operationId: admin_get_user
      summary: One user
      tags: [Admin]
      parameters:
        - { name: user_id, in: path, required: true, schema: { type: integer } }
      responses:
        "200":
          description: User
          content:
            application/json:
              schema:
                $ref: "#/components/schemas/Envelope"
        "404":
          $ref: "#/components/responses/NotFound"

  /admin/users/{user_id}/role:
    post:
      operationId: admin_set_user_role
      summary: Change role
      tags: [Admin]
      parameters:
        - { name: user_id, in: path, required: true, schema: { type: integer } }
        - name: role
          in: query
          required: true
          schema: { type: string, enum: [user, admin] }
      responses:
        "200":
          description: Role updated
          content:
            application/json:
              schema:
                $ref: "#/components/schemas/Envelope"
        "400":
          $ref: "#/components/responses/BadRequest"

  /admin/cargo-types:
    get:
      operationId: admin_cargo_types
      summary: Cargo lookup table
      tags: [Admin]
      responses:
        "200":
          description: Cargo types
          content:
            application/json:
              schema:
                $ref: "#/components/schemas/Envelope"

components:
  securitySchemes:
    bearerAuth:
      type: http
      scheme: bearer
      description: Session JWT from POST /auth/login

  schemas:
    Envelope:
      type: object
      required: [data]
      properties:
        data: {}
        meta:
          type: object
          properties:
            pagination:
              $ref: "#/components/schemas/Pagination"
            inspection_id: { type: integer }
            detected_at: { type: string, format: date-time }
            elapsed_seconds: { type: number }
            image:
              $ref: "#/components/schemas/Image"
            expires_in_hours: { type: integer }
        links:
          type: object
          properties:
            self: { type: string }
            overlay: { type: string }
            next: { type: string }
            prev: { type: string }
            first: { type: string }
            last: { type: string }
        error:
          $ref: "#/components/schemas/Problem"

    Pagination:
      type: object
      required: [page, per_page, total, total_pages]
      properties:
        page: { type: integer, minimum: 1 }
        per_page: { type: integer, minimum: 1, maximum: 100 }
        total: { type: integer, minimum: 0 }
        total_pages: { type: integer, minimum: 0 }

    Image:
      type: object
      required: [width, height]
      properties:
        width: { type: integer }
        height: { type: integer }

    Rect:
      type: object
      required: [x, y, w, h]
      properties:
        x: { type: integer }
        y: { type: integer }
        w: { type: integer }
        h: { type: integer }

    Problem:
      type: object
      required: [type, title, status, detail]
      properties:
        type: { type: string, format: uri }
        title: { type: string }
        status: { type: integer }
        detail: { type: string }
        errors:
          type: array
          items:
            type: object
            required: [field, message]
            properties:
              field: { type: string }
              message: { type: string }

    DetectionData:
      type: object
      required: [detected]
      properties:
        detected: { type: boolean }
        label: { type: string }
        aggregate_score: { type: number }
        objects:
          type: array
          items:
            type: object
            required: [label, yolo_confidence, sam_score, mask_area_px, box]
            properties:
              label: { type: string }
              yolo_confidence: { type: number }
              sam_score: { type: number }
              mask_area_px: { type: integer }
              box: { $ref: "#/components/schemas/Rect" }
              models:
                type: object
                properties:
                  yolo: { $ref: "#/components/schemas/Rect" }
                  sam: { $ref: "#/components/schemas/Rect" }
        box: { $ref: "#/components/schemas/Rect" }
        mask:
          type: object
          properties:
            area_ratio: { type: number }
            border_leak: { type: number }
        detector_origin: { type: string }
        uses_zip_taxonomy: { type: boolean }
        stage: { type: string }
        timed_out: { type: boolean }

    Submission:
      type: object
      required: [id, user_id, cargo_type, status, image_url, detection_status, created_at]
      properties:
        id: { type: integer }
        user_id: { type: integer }
        name: { type: string }
        email: { type: string }
        phone: { type: string }
        cargo_type: { type: string }
        cargo_label: { type: string }
        density_kg_m3: { type: number }
        status:
          type: string
          enum: [draft, submitted, approved, rejected]
        status_note: { type: string }
        notes: { type: string }
        reviewed_by: { type: integer }
        reviewed_at: { type: string, format: date-time }
        volume_m3: { type: number }
        estimated_weight_kg: { type: number }
        image_filename: { type: string }
        image_url: { type: string }
        image_width: { type: integer }
        image_height: { type: integer }
        tags:
          type: array
          items:
            type: object
            required: [id, name]
            properties:
              id: { type: integer }
              name: { type: string }
              colour: { type: string }
        detection_status:
          type: string
          enum: [not_run, detected, no_cargo, error]
        detected_at: { type: string, format: date-time }
        cargo_object_count: { type: integer }
        created_at: { type: string, format: date-time }
        updated_at: { type: string, format: date-time }

    User:
      type: object
      required: [id, name, email, role, created_at]
      properties:
        id: { type: integer }
        name: { type: string }
        email: { type: string }
        phone: { type: string }
        role:
          type: string
          enum: [user, admin]
        is_active: { type: boolean }
        is_admin: { type: boolean }
        created_at: { type: string, format: date-time }
        inspection_count: { type: integer }
        has_password: { type: boolean }

    CargoType:
      type: object
      required: [id, slug, label]
      properties:
        id: { type: integer }
        slug: { type: string }
        label: { type: string }
        density_kg_m3: { type: number }
        description: { type: string }

    AuditEntry:
      type: object
      required: [id, action, entity_type, entity_id, created_at]
      properties:
        id: { type: integer }
        action: { type: string }
        entity_type: { type: string }
        entity_id: { type: integer }
        actor_user_id: { type: integer }
        detail: { type: object }
        created_at: { type: string, format: date-time }

  responses:
    Unauthorized:
      description: Missing or invalid session
      content:
        application/problem+json:
          schema:
            $ref: "#/components/schemas/Problem"
    Forbidden:
      description: Wrong role or permission
      content:
        application/problem+json:
          schema:
            $ref: "#/components/schemas/Problem"
    NotFound:
      description: Resource not found
      content:
        application/problem+json:
          schema:
            $ref: "#/components/schemas/Problem"
    Conflict:
      description: Duplicate or already-decided
      content:
        application/problem+json:
          schema:
            $ref: "#/components/schemas/Problem"
    Unprocessable:
      description: Validation failure
      content:
        application/problem+json:
          schema:
            $ref: "#/components/schemas/Problem"
    BadRequest:
      description: Malformed request
      content:
        application/problem+json:
          schema:
            $ref: "#/components/schemas/Problem"
    ServiceUnavailable:
      description: Detector disabled or busy
      content:
        application/problem+json:
          schema:
            $ref: "#/components/schemas/Problem"
    DetectionFailed:
      description: Detector completed but failed
      content:
        application/problem+json:
          schema:
            $ref: "#/components/schemas/Problem"
    DetectionTimeout:
      description: Detector exceeded time budget
      content:
        application/problem+json:
          schema:
            $ref: "#/components/schemas/Problem"

security:
  - bearerAuth: []
```
