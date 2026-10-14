"""The URL contract: base path, method, and where a mutation's payload lives.

Three properties, each of which has been wrong at some point in this API's
history:

1. **Every API route lives under `/api/v1`.** The non-API surfaces are listed
   explicitly, so a route added outside the prefix fails here rather than being
   discovered at the next version bump.
2. **The method matches the work.** `METHOD_CONTRACT` below is the whole API;
   a new path or a changed verb fails until it is a deliberate edit. Three
   structural rules are asserted on top of the table: `PATCH` only ever targets
   a resource URL, `DELETE` only removes something, and `POST` either creates
   into a collection or names the action it performs.
3. **A mutation's payload is a JSON body**, never a query string (§5 reserves
   query parameters for GET filtering, sorting and pagination). This is
   measured behaviourally, not by inspection: the approve/reject note used to be
   read from `?note=` while the admin UI sent `{"note": …}`, so the note was
   silently dropped.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

from api import API_PREFIX


#: Every path the app exposes, and the methods it must answer on. Health is
#: deliberately outside the version prefix (D1) — probe configuration in a load
#: balancer is not an API contract worth versioning.
METHOD_CONTRACT: dict[str, set[str]] = {
    "/": {"get"},
    "/health": {"get"},
    "/health/ready": {"get"},
    # ---- auth ----------------------------------------------------------
    f"{API_PREFIX}/auth/register": {"post"},
    f"{API_PREFIX}/auth/login": {"post"},
    f"{API_PREFIX}/auth/logout": {"post"},
    f"{API_PREFIX}/auth/me": {"get"},
    f"{API_PREFIX}/auth/change-password": {"post"},
    f"{API_PREFIX}/auth/set-password": {"post"},
    # ---- portal --------------------------------------------------------
    f"{API_PREFIX}/portal/submissions": {"get", "post"},
    f"{API_PREFIX}/portal/submissions/{{inspection_id}}": {"get", "delete"},
    f"{API_PREFIX}/portal/submissions/{{inspection_id}}/detect": {"post"},
    f"{API_PREFIX}/portal/submissions/{{inspection_id}}/detection": {"get"},
    f"{API_PREFIX}/portal/submissions/{{inspection_id}}/detection/log": {"get"},
    f"{API_PREFIX}/portal/submissions/{{inspection_id}}/detection/overlay": {"get"},
    f"{API_PREFIX}/portal/submissions/{{inspection_id}}/image": {"get"},
    f"{API_PREFIX}/portal/submissions/{{inspection_id}}/lifting-plan": {"get"},
    f"{API_PREFIX}/portal/cargo-types": {"get"},
    f"{API_PREFIX}/portal/summary": {"get"},
    f"{API_PREFIX}/portal/detection/availability": {"get"},
    # ---- admin ---------------------------------------------------------
    f"{API_PREFIX}/admin/submissions": {"get", "post"},
    f"{API_PREFIX}/admin/submissions/{{inspection_id}}": {"get", "patch", "delete"},
    f"{API_PREFIX}/admin/submissions/{{inspection_id}}/approve": {"post"},
    f"{API_PREFIX}/admin/submissions/{{inspection_id}}/reject": {"post"},
    f"{API_PREFIX}/admin/submissions/{{inspection_id}}/restore": {"post"},
    f"{API_PREFIX}/admin/submissions/{{inspection_id}}/purge": {"delete"},
    f"{API_PREFIX}/admin/submissions/{{inspection_id}}/detection": {"get"},
    f"{API_PREFIX}/admin/submissions/{{inspection_id}}/detection/overlay": {"get"},
    f"{API_PREFIX}/admin/submissions/{{inspection_id}}/image": {"get"},
    f"{API_PREFIX}/admin/submissions/bulk": {"post"},
    f"{API_PREFIX}/admin/submissions/pending": {"get"},
    f"{API_PREFIX}/admin/submissions/summary": {"get"},
    f"{API_PREFIX}/admin/submissions/orphaned-users": {"get"},
    f"{API_PREFIX}/admin/stats": {"get"},
    f"{API_PREFIX}/admin/audit": {"get"},
    f"{API_PREFIX}/admin/users": {"get"},
    f"{API_PREFIX}/admin/users/{{user_id}}": {"get", "patch"},
    f"{API_PREFIX}/admin/cargo-types": {"get"},
}

#: Last path segments that name an action rather than a resource.
ACTION_SEGMENTS = frozenset(
    {
        "detect",
        "approve",
        "reject",
        "restore",
        "purge",
        "bulk",
        "login",
        "logout",
        "register",
        "change-password",
        "set-password",
    }
)

SAFE_METHODS = frozenset({"get", "head", "options"})


@pytest.fixture
def live_paths(client) -> dict[str, set[str]]:
    """`{path: {methods}}` straight from the served OpenAPI document."""
    return {
        path: set(ops)
        for path, ops in client.get("/openapi.json").json()["paths"].items()
    }


@pytest.fixture
def portal(client):
    """The plain `client` fixture is anonymous; the portal routes need a user."""
    r = client.post(
        f"{API_PREFIX}/auth/register",
        json={"name": "Owner", "email": "owner@example.com",
              "password": "quay-crane-42"},
    )
    assert r.status_code == 201, r.text
    return client


CONVENTIONS = (
    Path(__file__).resolve().parent.parent / "docs" / "API_CONVENTIONS.md"
)


def documented_spec() -> dict:
    """The OpenAPI document as printed in §9 of the conventions."""
    text = CONVENTIONS.read_text(encoding="utf-8")
    block = text.split("## 9. OpenAPI 3.1 document", 1)[1]
    yaml_text = block.split("```yaml", 1)[1].split("```", 1)[0]
    return yaml.safe_load(yaml_text)


def create_submission(client, png_bytes, cargo_type: str = "scrap-steel") -> dict:
    r = client.post(
        f"{API_PREFIX}/portal/submissions",
        data={"cargo_type": cargo_type},
        files={"image": ("c.png", png_bytes(), "image/png")},
    )
    assert r.status_code == 201, r.text
    return r.json()["data"]


# ---------------------------------------------------------------- 1: base path
class TestBasePath:
    def test_every_path_and_method_is_the_documented_contract(self, live_paths):
        """A new route, a moved route or a changed verb fails here."""
        missing = {p: METHOD_CONTRACT[p] for p in METHOD_CONTRACT if p not in live_paths}
        extra = {p: live_paths[p] for p in live_paths if p not in METHOD_CONTRACT}
        wrong = {
            p: (METHOD_CONTRACT[p], live_paths[p])
            for p in METHOD_CONTRACT
            if p in live_paths and live_paths[p] != METHOD_CONTRACT[p]
        }
        assert not (missing or extra or wrong), (
            f"missing={missing} extra={extra} wrong={wrong}"
        )

    def test_no_api_path_is_unversioned(self, live_paths):
        unversioned = {"/", "/health", "/health/ready"}
        strays = [
            p for p in live_paths
            if p not in unversioned and not p.startswith(f"{API_PREFIX}/")
        ]
        assert not strays, f"API paths outside {API_PREFIX}: {strays}"

    def test_the_prefix_is_the_documented_version(self):
        assert API_PREFIX == "/api/v1"

    def test_old_unprefixed_paths_are_gone(self, client):
        """Hard cutover (D7): no dual mount, no redirect to the new path."""
        client.cookies.clear()
        for path in ("/auth/me", "/portal/submissions", "/admin/submissions",
                     "/portal/submissions/1/detection"):
            assert client.get(path).status_code == 404, path

    def test_health_and_the_root_stay_outside_the_prefix(self, client):
        assert client.get("/health").status_code == 200
        root = client.get("/").json()["data"]
        assert root["api"] == API_PREFIX
        assert root["health"] == "/health"

    def test_the_gates_follow_the_routes(self, client):
        """The middleware prefix lists and the routes must move together.

        The auth middleware *fails open* for an unlisted prefix, so a route that
        moved while `PROTECTED_PREFIXES` did not would be routed without the
        middleware ever looking at it. This is the test that catches that.
        """
        client.cookies.clear()
        assert client.get(f"{API_PREFIX}/portal/submissions").status_code == 401
        assert client.get(f"{API_PREFIX}/admin/submissions").status_code == 401

        r = client.post(
            f"{API_PREFIX}/auth/register",
            json={"name": "Gate", "email": "gate@example.com",
                  "password": "quay-crane-42"},
        )
        assert r.status_code == 201, r.text
        # Signed in: portal opens, admin stays shut.
        assert client.get(f"{API_PREFIX}/portal/submissions").status_code == 200
        assert client.get(f"{API_PREFIX}/admin/submissions").status_code == 403


# ------------------------------------------------------------- 2: the method
class TestMethodMatchesTheWork:
    """Structural rules, so a *new* route cannot pick an odd verb unnoticed."""

    def test_patch_only_ever_targets_a_resource_url(self, live_paths):
        """`PATCH` is a partial update of an existing thing, so its URL must end
        in that thing's id — not in an action verb."""
        offenders = [
            p for p, methods in live_paths.items()
            if "patch" in methods and not p.endswith("}")
        ]
        assert not offenders, f"PATCH on a non-resource URL: {offenders}"

    def test_delete_only_removes_something(self, live_paths):
        """`DELETE` ends in the resource id, or in a named destructive action."""
        offenders = [
            p for p, methods in live_paths.items()
            if "delete" in methods
            and not p.endswith("}")
            and p.rsplit("/", 1)[-1] not in {"purge"}
        ]
        assert not offenders, f"DELETE on a non-destructive URL: {offenders}"

    def test_post_either_creates_or_names_its_action(self, live_paths):
        """`POST` is the one method with no shape of its own, so the rule is
        explicit: it creates into a collection (which can be read back with
        `GET`), or the last segment names the action it performs."""
        offenders = []
        for path, methods in live_paths.items():
            if "post" not in methods:
                continue
            if path.rsplit("/", 1)[-1] in ACTION_SEGMENTS:
                continue
            if "get" in methods and not path.endswith("}"):
                continue  # a collection: POST creates, GET lists
            offenders.append(path)
        assert not offenders, f"POST with no create/action meaning: {offenders}"

    def test_no_mutation_takes_its_input_from_the_query_string(self, client):
        """§5: query parameters are for `GET` filtering/sorting/pagination.

        Two endpoints shipped this bug and both were silent, because the input
        was optional: `?note=` on approve/reject (the UI sent a body, so notes
        vanished) and `?force=` on detect. The rule is asserted directly off the
        served schema, so a third cannot appear unnoticed.
        """
        offenders = {}
        for path, ops in client.get("/openapi.json").json()["paths"].items():
            for method, op in ops.items():
                if method in SAFE_METHODS or not isinstance(op, dict):
                    continue
                query = [
                    p["name"] for p in op.get("parameters", [])
                    if p.get("in") == "query"
                ]
                if query:
                    offenders[f"{method.upper()} {path}"] = query
        assert not offenders, (
            f"mutations reading the query string: {offenders} — "
            "move the input into the request body"
        )

    def test_no_read_endpoint_is_a_mutation(self, live_paths):
        """`GET` must be safe. Every mutation path must also offer a mutating
        method somewhere else — i.e. mutations are not reachable by GET alone."""
        for path, methods in live_paths.items():
            if path in ("/", "/health", "/health/ready"):
                continue
            read_only = methods & SAFE_METHODS
            if read_only and path.rsplit("/", 1)[-1] in ACTION_SEGMENTS:
                # An action path that only answers GET would be a README for a
                # mutation that never happens.
                assert methods - SAFE_METHODS, f"{path} is GET-only but named like an action"


# ------------------------------------------------- 3: payloads live in the body
class TestMutationPayloadsLiveInTheBody:
    def test_approve_reads_the_note_from_the_body(self, admin_client, png_bytes):
        submission = create_submission(admin_client, png_bytes)
        r = admin_client.post(
            f"{API_PREFIX}/admin/submissions/{submission['id']}/approve",
            json={"note": "looks correct"},
        )
        assert r.status_code == 200, r.text
        assert r.json()["data"]["status_note"] == "looks correct"

    def test_the_note_reaches_the_audit_trail(self, admin_client, png_bytes):
        """The body note is what gets recorded — the bug this pins was a note
        sent in the body and read from the query string, so it vanished."""
        submission = create_submission(admin_client, png_bytes)
        admin_client.post(
            f"{API_PREFIX}/admin/submissions/{submission['id']}/reject",
            json={"note": "blurry image"},
        )
        entries = admin_client.get(
            f"{API_PREFIX}/admin/audit?entity_type=inspection&action=rejected"
        ).json()["data"]
        assert entries, "no audit entry for the rejection"
        assert entries[0]["detail"]["note"] == "blurry image"

    def test_approve_without_a_body_is_still_valid(self, admin_client, png_bytes):
        """The note is optional, so an empty body must not be a 422."""
        submission = create_submission(admin_client, png_bytes)
        r = admin_client.post(
            f"{API_PREFIX}/admin/submissions/{submission['id']}/approve"
        )
        assert r.status_code == 200, r.text
        assert r.json()["data"]["status"] == "approved"

    def test_a_role_change_is_a_patch_on_the_user(self, admin_client, db):
        from models.user import User

        target = User(name="Target", email="target@example.com")
        db.add(target)
        db.commit()

        r = admin_client.patch(
            f"{API_PREFIX}/admin/users/{target.id}", json={"role": "admin"}
        )
        assert r.status_code == 200, r.text
        assert r.json()["data"]["role"] == "admin"
        # Read it back through the API: the change persisted, not just echoed.
        assert admin_client.get(
            f"{API_PREFIX}/admin/users/{target.id}"
        ).json()["data"]["role"] == "admin"

    def test_the_old_role_endpoint_is_gone(self, admin_client, db):
        """`POST /users/{id}/role` was RPC-style: a mutation named like a
        resource, with the value in a query string."""
        from models.user import User

        target = User(name="Target2", email="target2@example.com")
        db.add(target)
        db.commit()

        assert admin_client.post(
            f"{API_PREFIX}/admin/users/{target.id}/role", params={"role": "admin"}
        ).status_code == 404

        # The method is part of the contract: POST to the user is not the
        # documented way to change one.
        r = admin_client.post(f"{API_PREFIX}/admin/users/{target.id}")
        assert r.status_code == 405
        assert "PATCH" in r.headers.get("allow", "").upper()

    @pytest.mark.parametrize("body", [{}, {"role": "superuser"}])
    def test_a_role_change_needs_a_valid_role(self, admin_client, db, body):
        from models.user import User

        target = User(name="Target3", email="target3@example.com")
        db.add(target)
        db.commit()
        assert admin_client.patch(
            f"{API_PREFIX}/admin/users/{target.id}", json=body
        ).status_code == 422

    def test_a_non_admin_cannot_change_a_role(self, client, db):
        from models.user import User

        target = User(name="Target4", email="target4@example.com")
        db.add(target)
        db.commit()
        assert client.patch(
            f"{API_PREFIX}/admin/users/{target.id}", json={"role": "admin"}
        ).status_code in (401, 403)


# ------------------------------------------------------------ 4: the links work
class TestAdvertisedLinksResolve:
    """A response that advertises a path must not advertise a 404."""

    def test_portal_self_and_image_urls_resolve(self, portal, png_bytes):
        submission = create_submission(portal, png_bytes)

        detail = portal.get(f"{API_PREFIX}/portal/submissions/{submission['id']}")
        assert detail.status_code == 200
        assert detail.json()["links"]["self"] == (
            f"{API_PREFIX}/portal/submissions/{submission['id']}"
        )

        listing = portal.get(f"{API_PREFIX}/portal/submissions").json()
        assert listing["links"]["self"].startswith(
            f"{API_PREFIX}/portal/submissions?"
        )
        item = next(i for i in listing["data"] if i["id"] == submission["id"])
        assert portal.get(item["image_url"]).status_code == 200

    def test_admin_self_and_image_urls_resolve(self, admin_client, png_bytes):
        submission = create_submission(admin_client, png_bytes)
        detail = admin_client.get(
            f"{API_PREFIX}/admin/submissions/{submission['id']}"
        )
        assert detail.status_code == 200
        body = detail.json()
        assert body["links"]["self"] == (
            f"{API_PREFIX}/admin/submissions/{submission['id']}"
        )
        assert admin_client.get(body["data"]["image_url"]).status_code == 200

    def test_created_resource_location_is_prefixed(self, portal, png_bytes):
        r = portal.post(
            f"{API_PREFIX}/portal/submissions",
            data={"cargo_type": "scrap-steel"},
            files={"image": ("c.png", png_bytes(), "image/png")},
        )
        assert r.status_code == 201, r.text
        location = r.headers["location"]
        assert location.startswith(f"{API_PREFIX}/portal/submissions/")
        assert portal.get(location).status_code == 200

class TestTheDocumentMatchesTheApp:
    """§9 of `docs/API_CONVENTIONS.md` is generated from `app.openapi()`.

    Generated or not, it is checked in — so it can be edited by hand and drift.
    This is the test that notices, and the fix is to re-run
    `scripts/regen_openapi.py` rather than to touch the document.
    """

    def test_the_documented_paths_are_the_served_paths(self, client):
        documented = {
            path: set(ops) for path, ops in documented_spec()["paths"].items()
        }
        served = {
            path: set(ops)
            for path, ops in client.get("/openapi.json").json()["paths"].items()
        }
        differing = {
            p: (documented.get(p), served.get(p))
            for p in set(documented) | set(served)
            if documented.get(p) != served.get(p)
        }
        assert not differing, (
            f"documented vs served differ: {differing} — "
            "run scripts/regen_openapi.py"
        )

    def test_the_endpoint_reference_lists_exactly_the_served_operations(self, client):
        """§7 is written by hand, §9 is generated. Both describe one API.

        This is the check that caught 21 endpoints documented as
        `/{id}` while the routes declare `{inspection_id}` / `{user_id}` — the
        path-parameter names are part of the contract, not decoration.
        """
        text = CONVENTIONS.read_text(encoding="utf-8")
        section = (
            text.split("## 7. Endpoint reference", 1)[1]
            .split("## 8. JSON Schemas", 1)[0]
        )
        documented = {
            (m.group(1).lower(), m.group(2))
            for m in re.finditer(r"^#### `([A-Z]+) (\S+)`", section, re.M)
        }
        served = {
            (method, path)
            for path, ops in client.get("/openapi.json").json()["paths"].items()
            for method in ops
        }
        assert documented == served, (
            f"documented but not served: {sorted(documented - served)}; "
            f"served but not documented: {sorted(served - documented)}"
        )

    def test_no_documented_path_is_unprefixed(self):
        """§0 says every API path starts with `/api/v1`; §9 must agree."""
        unversioned = {"/", "/health", "/health/ready"}
        strays = [
            p for p in documented_spec()["paths"]
            if p not in unversioned and not p.startswith(f"{API_PREFIX}/")
        ]
        assert not strays, f"§9 documents unprefixed API paths: {strays}"


class TestKebabCaseSegments:
    def test_the_lifting_plan_path_is_kebab_case(self, portal, png_bytes):
        """D2: one segment was snake_case, which was the only path in the API
        not using kebab-case."""
        submission = create_submission(portal, png_bytes)
        url = f"{API_PREFIX}/portal/submissions/{submission['id']}/lifting-plan"
        # 422 = "run detection first", which proves the route exists (a 404
        # would mean the path had moved).
        assert portal.get(url).status_code == 422
        assert portal.get(
            f"{API_PREFIX}/portal/submissions/{submission['id']}/lifting_plan"
        ).status_code == 404
