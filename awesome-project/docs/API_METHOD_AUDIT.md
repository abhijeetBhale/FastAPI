# API_METHOD_AUDIT.md — Is every method right for the work it does?

**Question asked:** do the HTTP methods match what each endpoint actually does,
or are some of them arbitrary?

**Answer:** no operation had a random verb. Of the 44 operations, 27 are reads
and all are `GET`; of the 17 mutations, every one used the right method for its
work — but **three of them carried their input in the query string**, which §5
reserves for `GET`, and one response header was incomplete. Four defects in
total, across `/admin` and `/portal`:

| Defect | Kind | Operations affected |
|---|---|---|
| A role change was `POST` on a `/role` sub-path | wrong method | 1 |
| Approve/reject read their note from `?note=` (the UI sent a body — the note was dropped) | right method, payload in the wrong place | 2 |
| `detect` read `?force=` from the query string | right method, payload in the wrong place | 1 |
| A `405` listed only one method in `Allow` | wrong response contract, not wrong routing | — (header only) |

No defect was a *wrong verb* except the role endpoint; the rest were the right
verb with its input in the wrong place — which is why they all failed silently
(the payload was optional, so the parameter was simply ignored rather than
rejected). The query-string class is now asserted off the served schema, so it
cannot come back in a new endpoint.

Everything below was measured against `docs/API_CONVENTIONS.md` §5 and against
the code, then pinned by `tests/test_api_contract.py`.

---

## 1. The rule set applied

| Rule | Source |
|---|---|
| A method that only reads is `GET`; nothing mutates on `GET` | §5 |
| `POST` creates into a collection, or triggers a non-idempotent action | §5 |
| A partial update of an existing resource is `PATCH`, never `POST` | §5 anti-pattern table |
| `DELETE` removes, and is idempotent (repeat → 204) | §2, §5 |
| A mutation's payload is a JSON **body**; query strings are for `GET` filtering/sorting/pagination only | §5 "Request body rules" |
| `405` must carry a complete `Allow` header | §5 (RFC 9110 §15.5.6) |

---

## 2. Verdict per operation

`GET`/`read` operations — 27 of 44, all read-only, all correct:

| Surface | Paths |
|---|---|
| Auth | `GET /api/v1/auth/me` |
| Portal | `/portal/submissions`, `/portal/submissions/{id}`, `…/detection`, `…/detection/log`, `…/detection/overlay`, `…/image`, `…/lifting-plan`, `/portal/cargo-types`, `/portal/summary`, `/portal/detection/availability` |
| Admin | `/admin/submissions`, `/admin/submissions/{id}`, `/admin/submissions/pending`, `/admin/submissions/summary`, `/admin/submissions/orphaned-users`, `…/detection`, `…/detection/overlay`, `…/image`, `/admin/stats`, `/admin/audit`, `/admin/users`, `/admin/users/{id}`, `/admin/cargo-types` |
| Probes / root | `/`, `/health`, `/health/ready` |

Mutations — 17 of 44:

| Path | Method | Why that method is right | Verdict |
|---|---|---|---|
| `/api/v1/auth/register` | `POST` | Creates a user (+ session) | ✅ |
| `/api/v1/auth/login` | `POST` | Creates a session; non-idempotent by nature | ✅ |
| `/api/v1/auth/logout` | `POST` | Destroys the session; the documented action form | ✅ |
| `/api/v1/auth/change-password` | `POST` | Non-idempotent credential action; §5 explicitly allows `POST /…/password-reset` | ✅ |
| `/api/v1/auth/set-password` | `POST` | Same | ✅ |
| `/api/v1/portal/submissions` | `POST` | Creates into a collection, 201 + `Location` | ✅ |
| `/api/v1/portal/submissions/{id}` | `DELETE` | Withdraw (soft delete), idempotent → 204 | ✅ |
| `…/submissions/{id}/detect` | `POST` | Runs the detector; §5 names "run detection" as a POST action | ✅ |
| `/api/v1/admin/submissions` | `POST` | Creates on an admin's behalf, 201 + `Location` | ✅ |
| `/api/v1/admin/submissions/{id}` | `PATCH` | Partial update of an existing submission | ✅ |
| `/api/v1/admin/submissions/{id}` | `DELETE` | Soft delete, idempotent | ✅ |
| `…/submissions/{id}/purge` | `DELETE` | Hard delete; `DELETE` is the removal verb | ✅ |
| `…/submissions/{id}/approve` | `POST` | Non-idempotent state transition (§5 lists approve/reject as POST actions) | ⚠️ fixed payload — see §3.2 |
| `…/submissions/{id}/reject` | `POST` | Same | ⚠️ fixed payload — see §3.2 |
| `…/submissions/{id}/restore` | `POST` | Un-withdraw action; not a resource creation, hence the named sub-path | ✅ |
| `/api/v1/admin/submissions/bulk` | `POST` | Batch action carrying `ids` + `action` in the body | ✅ |
| `/api/v1/admin/users/{id}` | `PATCH` | Role change is a partial update of the user | ❌ was `POST /users/{id}/role` — see §3.1 |

No `PUT` exists: nothing in this API offers whole-resource replacement, and no
client assigns ids. That is why `ETag`/`If-Match`/412 (§5 "Concurrency
control") is documented but unimplemented — there is no `PUT` or `PATCH`
precondition on a client-supplied representation yet.

---

## 3. The three defects

### 3.1 `POST /api/v1/admin/users/{id}/role?role=admin` → `PATCH /api/v1/admin/users/{id}`

Two problems in one endpoint:

- **Wrong method.** A role change is a partial update of an existing resource;
  §5's anti-pattern table says exactly this: *"`POST /users/123` (update) → `PUT`
  or `PATCH /users/123`"*.
- **Payload in the query string.** `?role=` is a mutation carried in the query,
  and §5 restricts those to `GET` filtering/sorting/pagination. It also made the
  change invisible to anything reading the body.

Now: `PATCH /api/v1/admin/users/{id}` with `{"role": "admin"}`, validated by
`UserRoleUpdate` (a missing or unknown role is a 422 from the schema rather
than a hand-rolled check). The `users:manage` permission, the self-demotion 400
and the `set_role` audit action are unchanged.

### 3.2 `POST …/approve`, `…/reject` (`?note=`) and `POST …/detect` (`?force=`)

The method was right (a state transition is a POST action). The **payload
location was wrong**, and it was actively losing data: the admin UI sent
`fetch(…, { method: "POST", body: JSON.stringify({ note }) })` while the server
read `?note=`, so any note typed into the UI was dropped. Nothing surfaced the
mismatch because the parameter was optional.

Now the note is read from the JSON body (`DecisionRequest`), matching the batch
form `BulkDecisionRequest` that already worked. A test asserts the note reaches
`status_note` **and** the `audit_log` entry, because the audit trail is the
reason the note exists.

`detect` had the same shape with `?force=true`: a mutation option in the query
string. It is now `{"force": true}` in the body (`DetectRequest`). Both bodies
are optional, so a body-less `POST` still works — which is why neither bug was
ever noticed: the input was optional, so the failure mode was "the option is
silently ignored", not an error.

### 3.3 A `405` reported an incomplete `Allow` header

Where one path is served by several handler functions (`GET` + `PATCH` on
`/api/v1/admin/users/{id}`; `GET` + `PATCH` + `DELETE` on
`/api/v1/admin/submissions/{id}`), Starlette builds `Allow` from the single
route object that matched the path, so the header listed only the first
handler's method — `POST /api/v1/admin/users/{id}` answered `Allow: GET`.

That is a method-contract bug in the error response: §5 requires the header and
RFC 9110 §15.5.6 requires the *complete* set of methods the resource supports.
`errors.allowed_methods()` now rebuilds it from the app's path table, adding
`HEAD` wherever `GET` works. Preflight `OPTIONS` is intentionally not listed —
the CORS middleware answers it before routing.

---

## 4. What was checked and found correct

- **No `GET` mutates.** Every read endpoint is side-effect free; the lifting
  plan is rendered in memory and nothing is persisted, so it stays a `GET`.
- **`DELETE` is genuinely idempotent** — repeating a withdraw returns 204 with
  an empty body rather than 404 or a `null` body.
- **Creates return 201 + `Location`**, and the `Location` value resolves
  (it equals `links.self`).
- **Status codes match the method tables** in §5: 200 for `GET`/`PATCH`/action
  `POST`, 201 for creates, 204 for `DELETE`, 409 for a duplicate decision.
- **Non-2xx bodies are RFC 9457 problem documents** with the right
  `Content-Type`, including 405.

## 5. How this stays true

`tests/test_api_contract.py` holds the whole API as a table:
`METHOD_CONTRACT` maps every path to the methods it must answer. Adding a route,
removing one, or changing a verb fails the suite until the table is updated
deliberately. Three structural rules run on top, so a *new* route cannot pick an
odd verb unnoticed:

1. `PATCH` only ever targets a resource URL (ends in `{param}`).
2. `DELETE` only targets an id or a named destructive action (`purge`).
3. `POST` either creates into a collection that can be read back with `GET`, or
   its last segment names the action (`detect`, `approve`, `restore`, …).
4. No non-`GET` operation declares a query parameter — asserted directly
   against the served OpenAPI document.
