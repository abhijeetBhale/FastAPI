"""The UI's half of the contract.

`static/index.html` reads specific JSON paths out of specific endpoints. Those
paths are untyped — a wrong one is not an error in JavaScript, it is
`undefined` — so a change to the envelope silently breaks the page.

The bug this file exists for: the UI read `d.user` after `fetch(...).json()`
while the API sends `data.user`, so a signed-in reload fell through to the
sign-in screen and the portal never rendered. Both the browser and the API were
"working"; only the seam between them was wrong. Every path the UI reads is
asserted here, so moving one fails in pytest with the path named, instead of in
a browser with a blank page.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from api import API_PREFIX
from services.security import COOKIE_NAME


def at(payload: dict, path: str):
    """Follow a dotted path, asserting each segment exists.

    `at(body, "data.user.email")` — the failure message names the missing step,
    which is the whole point: an assertion error that says
    `missing 'user' in {...}` reads like the browser bug it is.
    """
    node = payload
    walked: list[str] = []
    for part in path.split("."):
        if part == "[]":
            assert isinstance(node, list) and node, (
                f"UI reads {path!r} but {'.'.join(walked) or 'the body'} is not a "
                f"non-empty list (got {type(node).__name__})"
            )
            node = node[0]
            walked.append("[]")
            continue
        assert isinstance(node, dict) and part in node, (
            f"UI reads {path!r} but {'.'.join(walked) or 'the body'} has no "
            f"{part!r} — keys: {sorted(node)[:12] if isinstance(node, dict) else type(node)}"
        )
        node = node[part]
        walked.append(part)
    return node


@pytest.fixture
def portal(client):
    """A signed-in, non-admin client — what `/ui` has after a sign-in."""
    r = client.post(
        f"{API_PREFIX}/auth/register",
        json={"name": "UI User", "email": "ui@example.com",
              "password": "quay-crane-42"},
    )
    assert r.status_code == 201, r.text
    return client


def upload(client, png_bytes, cargo_type: str = "scrap-steel") -> dict:
    r = client.post(
        f"{API_PREFIX}/portal/submissions",
        data={"cargo_type": cargo_type},
        files={"image": ("c.png", png_bytes(), "image/png")},
    )
    assert r.status_code == 201, r.text
    return r.json()


# --------------------------------------------------------------- session / boot
class TestSession:
    """`boot()` runs on every page load, including a reload."""

    def test_me_puts_the_user_under_data(self, portal):
        body = portal.get(f"{API_PREFIX}/auth/me").json()
        # The exact reads in boot(): me = res.data.user; res.data.is_admin
        assert isinstance(at(body, "data.user.id"), int)
        at(body, "data.user.name")
        at(body, "data.user.email")
        assert isinstance(at(body, "data.is_admin"), bool)
        at(body, "data.permissions")
        # And not at the top level — that is what used to be read.
        assert "user" not in body, "the UI reads data.user; a flat `user` would be missed"

    def test_a_reload_still_has_the_session(self, portal):
        """The session is an httpOnly cookie, so a reload re-authenticates.

        Two independent reads, one per page load: if the cookie did not survive,
        the second would be 401 and the UI would show the sign-in screen.
        """
        first = portal.get(f"{API_PREFIX}/auth/me")
        second = portal.get(f"{API_PREFIX}/auth/me")
        assert first.status_code == 200, first.text
        assert second.status_code == 200, second.text
        assert at(second.json(), "data.user.email") == "ui@example.com"

    def test_login_and_register_put_the_user_under_data(self, client):
        body = client.post(
            f"{API_PREFIX}/auth/register",
            json={"name": "UI Two", "email": "ui2@example.com",
                  "password": "quay-crane-42"},
        ).json()
        # The sign-in handler reads res.data.user.
        at(body, "data.user.id")
        at(body, "data.expires_in_hours")
        assert "user" not in body

    def test_logout_clears_the_session(self, portal):
        assert portal.post(f"{API_PREFIX}/auth/logout").status_code == 200
        assert portal.get(f"{API_PREFIX}/auth/me").status_code == 401


# ------------------------------------------------------------------- portal tab
class TestPortalViews:
    def test_summary_reads_data_stats(self, portal, png_bytes):
        upload(portal, png_bytes)
        body = portal.get(f"{API_PREFIX}/portal/summary").json()
        # refreshStats() reads exactly these four.
        at(body, "data.stats.inspections")
        at(body, "data.stats.approved")
        at(body, "data.stats.rejected")
        at(body, "data.stats.total_weight_kg")

    def test_cargo_types_are_under_data(self, portal):
        body = portal.get(f"{API_PREFIX}/portal/cargo-types").json()
        # loadCargoTypes() reads res.data, then c.slug / c.label / c.density_kg_m3.
        assert isinstance(at(body, "data"), list)
        at(body, "data.[].slug")
        at(body, "data.[].label")
        at(body, "data.[].density_kg_m3")

    def test_the_list_is_data_plus_meta_pagination(self, portal, png_bytes):
        upload(portal, png_bytes)
        body = portal.get(f"{API_PREFIX}/portal/submissions?page=1&per_page=6").json()
        # refresh() reads res.data for the cards and res.page for the count.
        at(body, "data.[].id")
        at(body, "data.[].image_url")
        at(body, "data.[].status")
        at(body, "data.[].created_at")
        at(body, "meta.pagination.page")
        at(body, "meta.pagination.per_page")
        at(body, "meta.pagination.total")
        at(body, "meta.pagination.total_pages")

    def test_the_page_parameters_the_ui_sends_are_the_ones_the_api_uses(
        self, portal, png_bytes
    ):
        """The UI sent `?skip=&limit=` while the API paginates with
        `?page=&per_page=`; the unknown params were ignored, so every page
        showed the first slice."""
        for _ in range(3):
            upload(portal, png_bytes)
        one = portal.get(f"{API_PREFIX}/portal/submissions?page=1&per_page=2").json()
        two = portal.get(f"{API_PREFIX}/portal/submissions?page=2&per_page=2").json()
        assert at(one, "meta.pagination.per_page") == 2
        assert at(two, "meta.pagination.page") == 2
        first_ids = [i["id"] for i in one["data"]]
        second_ids = [i["id"] for i in two["data"]]
        assert first_ids and second_ids
        assert not set(first_ids) & set(second_ids), "page 2 repeated page 1"


# -------------------------------------------------------------------- admin tab
class TestAdminViews:
    def test_stats_reads_data_stats(self, admin_client, png_bytes):
        upload(admin_client, png_bytes)
        body = admin_client.get(f"{API_PREFIX}/admin/stats").json()
        # refreshAdmin() reads s.stats.inspections / .approved / .pending, s.users.
        at(body, "data.stats.inspections")
        at(body, "data.stats.approved")
        at(body, "data.stats.pending")
        at(body, "data.users")

    def test_the_admin_list_is_data_plus_meta_pagination(self, admin_client, png_bytes):
        upload(admin_client, png_bytes)
        body = admin_client.get(
            f"{API_PREFIX}/admin/submissions?page=1&per_page=10"
        ).json()
        at(body, "data.[].id")
        at(body, "data.[].image_url")
        at(body, "data.[].cargo_label")
        at(body, "meta.pagination.total_pages")

    def test_bulk_reads_data_processed_and_results(self, admin_client, png_bytes):
        ids = [upload(admin_client, png_bytes)["data"]["id"] for _ in range(2)]
        body = admin_client.post(
            f"{API_PREFIX}/admin/submissions/bulk",
            json={"ids": ids, "action": "approve"},
        ).json()
        assert at(body, "data.processed") == 2
        assert at(body, "data.results.[].ok") is True

    def test_a_decision_returns_the_updated_submission(self, admin_client, png_bytes):
        sub = upload(admin_client, png_bytes)["data"]
        body = admin_client.post(
            f"{API_PREFIX}/admin/submissions/{sub['id']}/approve",
            json={"note": "ui contract"},
        ).json()
        assert at(body, "data.status") == "approved"
        assert at(body, "data.status_note") == "ui contract"

    def test_withdrawing_returns_no_body(self, admin_client, png_bytes):
        """The UI only checks `res.ok`, but a JSON body here would be a bug."""
        sub = upload(admin_client, png_bytes)["data"]
        r = admin_client.delete(f"{API_PREFIX}/portal/submissions/{sub['id']}")
        assert r.status_code == 204
        assert r.content == b""


# -------------------------------------------------------------- errors the UI shows
class TestProblemBodies:
    """Errors are RFC 9457 documents, not envelopes — the UI reads `detail`."""

    def test_a_failure_has_a_top_level_detail(self, client):
        client.cookies.clear()
        body = client.get(f"{API_PREFIX}/auth/me").json()
        assert at(body, "detail")
        assert at(body, "status") == 401
        assert "data" not in body, "a problem document is not an envelope"

    def test_a_validation_failure_lists_fields(self, client):
        body = client.post(
            f"{API_PREFIX}/auth/register", json={"email": "nope"}
        ).json()
        at(body, "errors.[].field")
        at(body, "errors.[].message")


# -------------------------------------------- where the signed-in shell is decided
UI_HTML = Path(__file__).resolve().parent.parent / "static" / "index.html"


def function_body(source: str, name: str) -> str:
    """The `{...}` body of `function <name>(`, found by brace matching."""
    start = source.index(f"function {name}(")
    open_brace = source.index("{", start)
    depth = 0
    for i in range(open_brace, len(source)):
        if source[i] == "{":
            depth += 1
        elif source[i] == "}":
            depth -= 1
            if depth == 0:
                return source[open_brace : i + 1]
    raise AssertionError(f"{name}: unbalanced braces — did the function move?")


def between(source: str, start: str, end: str) -> str:
    i = source.index(start)
    return source[i : source.index(end, i)]


class TestOneSignedInShell:
    """A signed-in page must not depend on *how* it signed in.

    The UI has no JavaScript test runner, so the page's source is the artifact
    under test here — the same way §"the UI reads these paths" above tests it
    from the API side. The node harness that boots the page's real script against
    a running server and asserts the rendered DOM is a scratch tool, not part of
    the suite; these assertions are the durable half of it.

    The bug this class exists for is the reload bug's sibling: `boot()` learned to
    read `data.user`, but the sign-in form still rendered the portal itself from
    its own reply. `/auth/login` does not carry `is_admin` — only `/auth/me`
    does — so an admin who signed in through the form got no Admin tab until a
    page reload, and no code path ever hid that tab again afterwards.
    """

    def test_the_sign_in_form_asks_the_server_who_it_signed_in(self):
        src = UI_HTML.read_text(encoding="utf-8")
        branch = between(
            src,
            'if (!res.ok) throw new Error(res.detail || "Sign in failed.");',
            "  } catch (e) {",
        )
        assert "await boot();" in branch, (
            "the sign-in handler must re-read the session through boot()/"
            "auth/me: that is the only reply carrying `is_admin`"
        )
        assert "showPortal()" not in branch, (
            "the sign-in handler rendered the portal from /auth/login's reply "
            "instead of going through boot(); an admin would get no Admin tab "
            "until a reload"
        )

    def test_the_admin_tab_is_decided_by_the_servers_role(self):
        src = UI_HTML.read_text(encoding="utf-8")
        apply_session = function_body(src, "applySession")
        assert "session.is_admin" in apply_session
        assert '"adminTab"' in apply_session, (
            "applySession must be what shows/hides the Admin tab"
        )
        assert "!session.is_admin" in apply_session, (
            "the Admin tab follows the server's role, not the UI's guess"
        )
        # And it is reached from boot(), so a reload and a sign-in agree.
        assert "applySession(res.data)" in function_body(src, "boot")
        # The entry point still boots on load, and only once.
        assert src.count("\nboot();") == 1

    def test_signing_out_drops_the_whole_signed_in_shell(self):
        src = UI_HTML.read_text(encoding="utf-8")
        show_auth = function_body(src, "showAuth")
        assert '"adminTab"' in show_auth, (
            "signing out must hide the Admin tab; otherwise the next account on "
            "this page inherits it and gets 403s"
        )
        assert 'classList.add("hidden")' in show_auth
        assert 'switchTab("submissions")' in show_auth

    def test_both_reads_are_cookie_sessions(self, client):
        """Neither path relies on client-side state, which is why a reload works.

        `/auth/me` after a sign-in is the same request as `/auth/me` on a fresh
        page load: same cookie, same body. The UI's own `me` variable is a cache.
        """
        registered = client.post(
            f"{API_PREFIX}/auth/register",
            json={"name": "Shell", "email": "shell@example.com",
                  "password": "quay-crane-42"},
        )
        assert registered.status_code == 201, registered.text
        assert COOKIE_NAME in registered.cookies, (
            "the session travels in the cookie, not the body — that is what makes "
            "a reload work with no client-side state"
        )
        assert "httponly" in registered.headers["set-cookie"].lower()
        after_signin = client.get(f"{API_PREFIX}/auth/me").json()
        after_reload = client.get(f"{API_PREFIX}/auth/me").json()
        assert after_signin["data"] == after_reload["data"]
        assert at(after_reload, "data.is_admin") is False
