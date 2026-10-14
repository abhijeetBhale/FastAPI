"""Authentication and portal authorisation.

The important property under test is *isolation*: a signed-in user must not be
able to read or withdraw another user's submissions, regardless of what they put
in the URL.
"""

from __future__ import annotations

import pytest

from api import API_PREFIX
from services.security import (
    create_access_token,
    hash_password,
    password_problems,
    verify_password,
)


# ---------------------------------------------------------------- passwords
class TestPasswordHashing:
    def test_round_trip(self):
        h = hash_password("hunter2000")
        assert verify_password("hunter2000", h)
        assert not verify_password("hunter2001", h)

    def test_hash_is_salted(self):
        a = hash_password("same-password")
        b = hash_password("same-password")
        assert a != b, "identical passwords must not produce identical digests"

    def test_stored_format_carries_algorithm_and_iterations(self):
        h = hash_password("hunter2000")
        algorithm, iterations, salt, digest = h.split("$")
        assert algorithm == "pbkdf2_sha256"
        assert int(iterations) >= 100_000
        assert salt and digest

    def test_plaintext_never_appears_in_the_digest(self):
        h = hash_password("supersecret1")
        assert "supersecret1" not in h

    @pytest.mark.parametrize("bad", ["", "short1", "nodigitshere", "12345678", None])
    def test_verify_rejects_bad_input_without_raising(self, bad):
        assert verify_password(bad or "", None) is False
        assert verify_password(bad or "", "not-a-valid-hash") is False
        assert verify_password(bad or "", "pbkdf2_sha256$1$$$") is False

    @pytest.mark.parametrize(
        "weak", ["123", "abc", "password", "password1", "qwerty12"]
    )
    def test_weak_passwords_are_reported(self, weak):
        assert password_problems(weak), f"{weak!r} should be rejected"

    def test_good_password_has_no_problems(self):
        assert password_problems("quay-crane-42") == []


# ---------------------------------------------------------------- account
class TestRegistration:
    def test_register_then_login(self, client):
        r = client.post(API_PREFIX + "/auth/register", json={
            "name": "Asha", "email": "asha@example.com",
            "password": "quay-crane-42",
        })
        assert r.status_code == 201, r.text
        assert r.json()["data"]["user"]["email"] == "asha@example.com"
        assert r.json()["data"]["user"]["inspection_count"] == 0
        assert r.json()["data"]["user"]["has_password"] is True

        # The cookie was set, so /me works straight after registering.
        assert client.get(API_PREFIX + "/auth/me").status_code == 200

    def test_weak_password_is_422_with_reasons(self, client):
        # Long enough to pass the schema's length rule, so the service's own
        # checks are what reject it and the reasons reach the user.
        r = client.post(API_PREFIX + "/auth/register", json={
            "name": "Weak", "email": "weak@example.com", "password": "password1",
        })
        assert r.status_code == 422
        assert "too common" in r.json()["detail"]

    def test_short_password_is_rejected_by_the_schema(self, client):
        r = client.post(API_PREFIX + "/auth/register", json={
            "name": "Short", "email": "short@example.com", "password": "123",
        })
        assert r.status_code == 422
        # RFC 9457: per-field failures land in `errors[]`.
        assert any("8 characters" in e.get("message", "")
                   for e in r.json()["errors"])

    def test_duplicate_email_is_409(self, client):
        client.post(API_PREFIX + "/auth/register", json={
            "name": "First", "email": "dupe@example.com", "password": "quay-crane-42"})
        r = client.post(API_PREFIX + "/auth/register", json={
            "name": "Second", "email": "DUPE@example.com", "password": "quay-crane-42"})
        assert r.status_code == 409

    def test_token_is_not_returned_in_the_body(self, client):
        """It is an httpOnly cookie, so JS cannot read it."""
        r = client.post(API_PREFIX + "/auth/register", json={
            "name": "Tok", "email": "tok@example.com", "password": "quay-crane-42"})
        assert "token" not in r.text.lower()

    def test_cookie_is_httponly(self, client):
        r = client.post(API_PREFIX + "/auth/register", json={
            "name": "H", "email": "h@example.com", "password": "quay-crane-42"})
        cookie = r.headers.get("set-cookie", "")
        assert "httponly" in cookie.lower()
        assert "samesite=strict" in cookie.lower()


class TestLogin:
    def _register(self, client, email="login@example.com", pw="quay-crane-42"):
        client.post(API_PREFIX + "/auth/register",
                    json={"name": "L", "email": email, "password": pw})

    def test_valid_credentials(self, client):
        self._register(client)
        client.cookies.clear()
        r = client.post(API_PREFIX + "/auth/login",
                         json={"email": "login@example.com", "password": "quay-crane-42"})
        assert r.status_code == 200

    def test_email_case_insensitive(self, client):
        self._register(client)
        client.cookies.clear()
        r = client.post(API_PREFIX + "/auth/login",
                         json={"email": "LOGIN@EXAMPLE.COM", "password": "quay-crane-42"})
        assert r.status_code == 200

    def test_wrong_password_is_401(self, client):
        self._register(client)
        client.cookies.clear()
        r = client.post(API_PREFIX + "/auth/login",
                         json={"email": "login@example.com", "password": "wrong-pass-9"})
        assert r.status_code == 401

    def test_unknown_email_gives_the_same_message(self, client):
        self._register(client)
        client.cookies.clear()
        r = client.post(API_PREFIX + "/auth/login",
                         json={"email": "nobody@example.com", "password": "quay-crane-42"})
        assert r.status_code == 401
        # Identical wording, so the response cannot be used to enumerate accounts.
        assert "incorrect" in r.json()["detail"].lower()

    def test_account_without_password_cannot_log_in(self, client, db):
        """Users that predate the portal have no password_hash."""
        from models.user import User

        db.add(User(name="Legacy", email="legacy@example.com"))
        db.commit()
        client.cookies.clear()

        r = client.post(API_PREFIX + "/auth/login",
                         json={"email": "legacy@example.com", "password": "anything-1"})
        assert r.status_code == 401
        assert "no password" in r.json()["detail"].lower()

    def test_deactivated_account_cannot_log_in(self, client, db):
        from models.user import User
        from services.security import hash_password as hp

        db.add(User(name="Gone", email="gone@example.com",
                    password_hash=hp("quay-crane-42"), is_active=False))
        db.commit()
        client.cookies.clear()

        r = client.post(API_PREFIX + "/auth/login",
                         json={"email": "gone@example.com", "password": "quay-crane-42"})
        assert r.status_code == 401


class TestSession:
    def test_me_requires_a_cookie(self, client):
        client.cookies.clear()
        assert client.get(API_PREFIX + "/auth/me").status_code == 401

    def test_me_returns_the_signed_in_user(self, client):
        client.post(API_PREFIX + "/auth/register", json={
            "name": "Me", "email": "me@example.com", "password": "quay-crane-42"})
        r = client.get(API_PREFIX + "/auth/me")
        assert r.status_code == 200
        # The me endpoint wraps the user so the UI can also read permissions.
        body = r.json()["data"]
        assert body["user"]["email"] == "me@example.com"
        assert body["is_admin"] is False
        assert "submissions:create" in body["permissions"]

    def test_logout_clears_the_cookie(self, client):
        client.post(API_PREFIX + "/auth/register", json={
            "name": "Out", "email": "out@example.com", "password": "quay-crane-42"})
        assert client.get(API_PREFIX + "/auth/me").status_code == 200
        client.post(API_PREFIX + "/auth/logout")
        client.cookies.clear()
        assert client.get(API_PREFIX + "/auth/me").status_code == 401

    def test_tampered_token_is_rejected(self, client, db):
        from models.user import User

        user = User(name="T", email="t@example.com")
        db.add(user); db.commit(); db.refresh(user)

        token = create_access_token(user)
        client.cookies.set("session_token", token[:-3] + "aaa")
        assert client.get(API_PREFIX + "/auth/me").status_code == 401


# ---------------------------------------------------------------- portal
class TestPortalRequiresAuth:
    @pytest.mark.parametrize("method,path", [
        ("get", API_PREFIX + "/portal/summary"),
        ("get", API_PREFIX + "/portal/submissions"),
        ("post", API_PREFIX + "/portal/submissions"),
        ("get", API_PREFIX + "/portal/submissions/1"),
        ("delete", API_PREFIX + "/portal/submissions/1"),
    ])
    def test_unauthenticated_is_401(self, client, method, path):
        client.cookies.clear()
        assert getattr(client, method)(path).status_code == 401


class TestPortalIsolation:
    """The core authorisation property."""

    @pytest.fixture
    def two_users(self, client, png_bytes):
        """Asha owns inspection A; Bob owns inspection B."""
        client.post(API_PREFIX + "/auth/register", json={
            "name": "Asha", "email": "asha@example.com", "password": "quay-crane-42"})
        a = client.post(API_PREFIX + "/portal/submissions",
                        data={"cargo_type": "scrap-steel"},
                        files={"image": ("a.png", png_bytes(), "image/png")})
        assert a.status_code == 201

        client.post(API_PREFIX + "/auth/logout")
        client.cookies.clear()
        client.post(API_PREFIX + "/auth/register", json={
            "name": "Bob", "email": "bob@example.com", "password": "quay-crane-42"})
        b = client.post(API_PREFIX + "/portal/submissions",
                        data={"cargo_type": "thermal-coal"},
                        files={"image": ("b.png", png_bytes(), "image/png")})
        assert b.status_code == 201

        return a.json()["data"]["id"], b.json()["data"]["id"]

    def test_list_shows_only_my_own(self, client, two_users):
        a_id, b_id = two_users
        r = client.get(API_PREFIX + "/portal/submissions")
        assert r.status_code == 200
        ids = {i["id"] for i in r.json()["data"]}
        assert ids == {b_id}, "Bob must not see Asha's submission"

    def test_total_is_scoped_too(self, client, two_users):
        assert client.get(API_PREFIX + "/portal/submissions").json()["meta"]["pagination"]["total"] == 1

    def test_cannot_read_another_users_submission(self, client, two_users):
        a_id, _ = two_users
        # 404, not 403: a 403 would confirm the id exists.
        assert client.get(f"{API_PREFIX}/portal/submissions/{a_id}").status_code == 404

    def test_cannot_withdraw_another_users_submission(self, client, two_users):
        a_id, _ = two_users
        assert client.delete(f"{API_PREFIX}/portal/submissions/{a_id}").status_code == 404

    def test_owner_can_read_their_own(self, client, two_users):
        _, b_id = two_users
        r = client.get(f"{API_PREFIX}/portal/submissions/{b_id}")
        assert r.status_code == 200
        assert r.json()["data"]["name"] == "Bob"

    def test_user_id_filter_cannot_be_forced(self, client, two_users):
        """Passing another user's id as a filter must not widen the result."""
        a_id, b_id = two_users
        r = client.get(f"{API_PREFIX}/portal/submissions?user_id={a_id}")
        assert r.status_code in (200, 422)
        if r.status_code == 200:
            assert {i["id"] for i in r.json()["data"]} == {b_id}

    def test_summary_is_scoped(self, client, two_users):
        assert client.get(API_PREFIX + "/portal/summary").json()["data"]["total"] == 1


class TestPortalPagination:
    @pytest.fixture
    def seeded_user(self, client, png_bytes):
        client.post(API_PREFIX + "/auth/register", json={
            "name": "Pager", "email": "pager@example.com", "password": "quay-crane-42"})
        for i in range(7):
            r = client.post(API_PREFIX + "/portal/submissions",
                            data={"cargo_type": "scrap-steel", "notes": f"load {i}"},
                            files={"image": (f"p{i}.png", png_bytes(), "image/png")})
            assert r.status_code == 201, r.text
        return client

    def test_envelope_counts(self, seeded_user):
        r = seeded_user.get(API_PREFIX + "/portal/submissions?per_page=3").json()
        assert r["meta"]["pagination"]["total"] == 7
        assert r["meta"]["pagination"]["per_page"] == 3
        assert r["meta"]["pagination"]["total_pages"] == 3
        assert len(r["data"]) == 3

    def test_pages_cover_everything_without_overlap(self, seeded_user):
        seen = []
        for p in range(1, 4):
            r = seeded_user.get(f"{API_PREFIX}/portal/submissions?page={p}&per_page=3&sort=id").json()
            seen += [i["id"] for i in r["data"]]
        assert len(seen) == 7
        assert len(set(seen)) == 7, "a row appeared on two pages"

    def test_out_of_range_page_is_empty_not_an_error(self, seeded_user):
        r = seeded_user.get(API_PREFIX + "/portal/submissions?page=99&per_page=3")
        assert r.status_code == 200
        assert r.json()["data"] == []

    def test_invalid_page_params_are_422(self, seeded_user):
        assert seeded_user.get(API_PREFIX + "/portal/submissions?per_page=0").status_code == 422
        assert seeded_user.get(API_PREFIX + "/portal/submissions?page=0").status_code == 422
        assert seeded_user.get(API_PREFIX + "/portal/submissions?per_page=9999").status_code == 422


class TestPortalUpload:
    def test_upload_lands_in_my_submissions(self, client, png_bytes):
        client.post(API_PREFIX + "/auth/register", json={
            "name": "Uploader", "email": "up@example.com", "password": "quay-crane-42"})
        r = client.post(API_PREFIX + "/portal/submissions",
                        data={"cargo_type": "thermal-coal", "notes": "via portal",
                              "tags": "urgent, portal"},
                        files={"image": ("u.png", png_bytes(8, 8), "image/png")})
        assert r.status_code == 201
        assert r.json()["data"]["cargo_type"] == "thermal-coal"
        assert {t["name"] for t in r.json()["data"]["tags"]} == {"urgent", "portal"}

        # It appears in the list straight away.
        listed = client.get(API_PREFIX + "/portal/submissions").json()
        assert listed["meta"]["pagination"]["total"] == 1
        assert listed["data"][0]["id"] == r.json()["data"]["id"]

    def test_details_come_from_the_account_not_the_form(self, client, png_bytes):
        """The portal form cannot spoof who submitted."""
        client.post(API_PREFIX + "/auth/register", json={
            "name": "Real Name", "email": "real@example.com",
            "phone": "+91 90000 11111", "password": "quay-crane-42"})
        r = client.post(API_PREFIX + "/portal/submissions",
                        data={"cargo_type": "other", "name": "Someone Else",
                              "email": "spoof@example.com"},
                        files={"image": ("u.png", png_bytes(), "image/png")})
        assert r.json()["data"]["name"] == "Real Name"
        assert r.json()["data"]["email"] == "real@example.com"

    def test_missing_cargo_type_is_422(self, client, png_bytes):
        client.post(API_PREFIX + "/auth/register", json={
            "name": "NoCargo", "email": "nc@example.com", "password": "quay-crane-42"})
        r = client.post(API_PREFIX + "/portal/submissions", data={"cargo_type": ""},
                        files={"image": ("u.png", png_bytes(), "image/png")})
        assert r.status_code == 422

    def test_idempotent_replay_does_not_duplicate(self, client, png_bytes):
        client.post(API_PREFIX + "/auth/register", json={
            "name": "Idem", "email": "idem@example.com", "password": "quay-crane-42"})
        first = client.post(
            API_PREFIX + "/portal/submissions", data={"cargo_type": "other"},
            files={"image": ("a.png", png_bytes(), "image/png")},
            headers={"Idempotency-Key": "portal-abc"},
        )
        second = client.post(
            API_PREFIX + "/portal/submissions", data={"cargo_type": "other"},
            files={"image": ("a.png", png_bytes(), "image/png")},
            headers={"Idempotency-Key": "portal-abc"},
        )
        assert second.json()["data"]["id"] == first.json()["data"]["id"]
        assert client.get(API_PREFIX + "/portal/submissions").json()["meta"]["pagination"]["total"] == 1

    def test_bad_file_type_is_400(self, client, png_bytes):
        client.post(API_PREFIX + "/auth/register", json={
            "name": "Bad", "email": "bad@example.com", "password": "quay-crane-42"})
        r = client.post(API_PREFIX + "/portal/submissions", data={"cargo_type": "other"},
                        files={"image": ("x.txt", b"not an image", "text/plain")})
        assert r.status_code == 400