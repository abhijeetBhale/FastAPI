"""Swagger UI / OpenAPI authentication.

Swagger UI's "Authorize" dialog can only hold an apiKey, a bearer token or an
OAuth2 flow â€” it has no way to present an httpOnly cookie. So /docs is
unusable against a cookie-only API: every protected operation fails 401 and
there is no control on the page to fix it.

These tests pin the fix, which has three independent parts. Breaking any one of
them leaves /docs broken while the portal keeps working, which is the worst
kind of failure because it looks fine in manual testing.

  1. OpenAPI must declare a security scheme, or Swagger renders no Authorize
     button at all.
  2. Protected operations must carry a security requirement, or Swagger shows
     no lock icon and the requirement is invisible.
  3. The bearer token must be accepted by BOTH the middleware (which runs before
     routing and would otherwise reject it) and the dependency.
"""

from __future__ import annotations

import pytest


def bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


# ------------------------------------------------------------------ 1 + 2: the spec
class TestOpenAPISpec:
    def test_a_security_scheme_is_declared(self, client):
        """Without this, Swagger has nothing to render an Authorize dialog for."""
        schemes = client.get("/openapi.json").json()["components"]["securitySchemes"]
        assert schemes, "no securitySchemes declared â€” /docs will have no Authorize button"

    def test_the_scheme_is_a_bearer_scheme(self, client):
        """Swagger's Authorize button only works for http/apikey/oauth2."""
        schemes = client.get("/openapi.json").json()["components"]["securitySchemes"]
        kinds = {s.get("type") for s in schemes.values()}
        schemes_by_type = {s.get("scheme") for s in schemes.values()
                           if s.get("type") == "http"}
        assert kinds & {"http", "apiKey", "oauth2"}, f"unusable scheme types: {kinds}"
        assert "bearer" in schemes_by_type, f"expected an http/bearer scheme, got {schemes_by_type}"

    @pytest.mark.parametrize(
        "path",
        [
            "/portal/submissions",
            "/portal/summary",
            "/portal/cargo-types",
            "/admin/submissions",
            "/admin/stats",
            "/admin/audit",
            "/admin/users",
        ],
    )
    def test_protected_operations_declare_security(self, client, path):
        """No lock icon means the requirement is invisible to a docs reader."""
        ops = client.get("/openapi.json").json()["paths"][path]
        unsecured = [m.upper() for m, op in ops.items()
                     if isinstance(op, dict) and m in
                     ("get", "post", "put", "patch", "delete") and not op.get("security")]
        assert not unsecured, f"{path}: {unsecured} declare no security requirement"

    @pytest.mark.parametrize("path", ["/auth/login", "/auth/register", "/health"])
    def test_public_operations_are_not_marked(self, client, path):
        """Marking /auth/login as secured makes the docs demand a token you
        cannot obtain yet â€” an obvious dead end for a first-time reader."""
        ops = client.get("/openapi.json").json()["paths"][path]
        marked = [m.upper() for m, op in ops.items()
                  if isinstance(op, dict) and m in
                  ("get", "post", "put", "patch", "delete") and op.get("security")]
        assert not marked, f"{path}: {marked} wrongly require authentication"


# ------------------------------------------------------------------ 3: it actually works
class TestBearerAuthenticates:
    """The whole point: a token pasted into Swagger must behave like the cookie."""

    def test_bearer_token_authenticates_a_portal_route(self, client):
        r = client.post("/auth/register", json={"name": "Docs", "email": "docs@x.com",
                                                "password": "quay-crane-42"})
        assert r.status_code == 201
        token = client.cookies.get("session_token")

        # Exactly what Swagger does: drop the cookie, send only the header.
        client.cookies.clear()
        me = client.get("/auth/me", headers=bearer(token))
        assert me.status_code == 200
        assert me.json()["data"]["user"]["email"] == "docs@x.com"

    def test_bearer_token_reaches_the_middleware_gate(self, client):
        """The bug this guards: the middleware runs before routing, so a valid
        bearer token used to be rejected there with 401 while the dependency
        that would have accepted it was never reached."""
        client.post("/auth/register", json={"name": "Docs2", "email": "docs2@x.com",
                                            "password": "quay-crane-42"})
        token = client.cookies.get("session_token")
        client.cookies.clear()

        # /portal is gated by AuthenticationMiddleware before routing happens.
        r = client.get("/portal/submissions", headers=bearer(token))
        assert r.status_code == 200, r.text

    def test_bearer_token_reaches_the_rbac_gate(self, client, db):
        """Same reasoning for /admin, which adds a role check on top."""
        from models.user import User

        client.post("/auth/register", json={"name": "DocsBoss", "email": "boss@x.com",
                                            "password": "quay-crane-42"})
        u = db.query(User).filter(User.email == "boss@x.com").one()
        u.role = "admin"
        db.commit()

        token = client.cookies.get("session_token")
        client.cookies.clear()
        r = client.get("/admin/submissions", headers=bearer(token))
        assert r.status_code == 200, r.text

    def test_bearer_does_not_bypass_ownership(self, client, db):
        """A second credential must not be a second set of rules. This user owns
        nothing, so another's submission is still a 404 â€” not a 200."""
        from models.user import User

        client.post("/auth/register", json={"name": "Owner", "email": "owner@x.com",
                                            "password": "quay-crane-42"})
        import struct, zlib

        def chunk(t, b):
            return struct.pack(">I", len(b)) + t + b + struct.pack(
                ">I", zlib.crc32(t + b) & 0xFFFFFFFF)

        w = h = 4
        raw = b"".join(b"\x00" + bytes((1, 2, 3)) * w for _ in range(h))
        png = (b"\x89PNG\r\n\x1a\n"
               + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
               + chunk(b"IDAT", zlib.compress(raw))
               + chunk(b"IEND", b""))
        owned = client.post("/portal/submissions", data={"cargo_type": "scrap-steel"},
                            files={"image": ("o.png", png, "image/png")}).json()["data"]
        owner_token = client.cookies.get("session_token")

        client.post("/auth/logout")
        client.cookies.clear()
        client.post("/auth/register", json={"name": "Snoop", "email": "snoop@x.com",
                                            "password": "quay-crane-42"})
        snoop_token = client.cookies.get("session_token")

        r = client.get(f"/portal/submissions/{owned['id']}",
                       headers=bearer(snoop_token))
        assert r.status_code == 404, r.text

    def test_missing_credential_is_still_401(self, client):
        client.cookies.clear()
        assert client.get("/auth/me").status_code == 401
        assert client.get("/portal/submissions").status_code == 401

    def test_a_forged_bearer_token_is_rejected(self, client):
        client.cookies.clear()
        r = client.get("/auth/me", headers=bearer("not.a.jwt"))
        assert r.status_code == 401

    def test_a_non_bearer_scheme_is_ignored(self, client):
        """`Basic <jwt>` is not a bearer token and must not be accepted."""
        client.post("/auth/register", json={"name": "Schemes", "email": "s@x.com",
                                            "password": "quay-crane-42"})
        token = client.cookies.get("session_token")
        client.cookies.clear()
        r = client.get("/auth/me", headers={"Authorization": f"Basic {token}"})
        assert r.status_code == 401

    def test_the_cookie_still_wins_over_the_header(self, client):
        """Cookie is checked first, so a stale Authorization header from some
        proxy cannot displace a valid browser session."""
        client.post("/auth/register", json={"name": "Prefer", "email": "pref@x.com",
                                            "password": "quay-crane-42"})
        token = client.cookies.get("session_token")
        # Cookie present and valid; header carries a different (bogus) token.
        r = client.get("/auth/me", headers=bearer("garbage.token.here"))
        assert r.status_code == 200
        assert r.json()["data"]["user"]["email"] == "pref@x.com"
