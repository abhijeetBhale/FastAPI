"""Regressions for the bugs found in review.

Each test here corresponds to a specific defect that was measured, not
guessed. If one fails, the bug is back.
"""

from __future__ import annotations

from api import API_PREFIX


class TestPaginationBounds:
    """`per_page=-5` used to reach PostgreSQL and surface as a 500."""

    def test_negative_limit_is_422(self, admin_client):
        assert admin_client.get(API_PREFIX + "/admin/submissions?per_page=-5").status_code == 422

    def test_negative_skip_is_422(self, admin_client):
        assert admin_client.get(API_PREFIX + "/admin/submissions?page=0").status_code == 422

    def test_zero_limit_is_422(self, admin_client):
        assert admin_client.get(API_PREFIX + "/admin/submissions?per_page=0").status_code == 422

    def test_absurd_limit_is_422_not_the_whole_table(self, admin_client):
        assert admin_client.get(API_PREFIX + "/admin/submissions?per_page=999999").status_code == 422

    def test_non_numeric_is_422(self, admin_client):
        assert admin_client.get(API_PREFIX + "/admin/submissions?page=abc").status_code == 422

    def test_valid_bounds_accepted(self, admin_client):
        assert admin_client.get(API_PREFIX + "/admin/submissions?page=1&per_page=100").status_code == 200


class TestNameLength:
    """An over-long name overflowed String(50) and returned 500."""

    def test_name_longer_than_column_is_422(self, admin_client):
        r = admin_client.post(
            API_PREFIX + "/auth/register",
            json={"name": "x" * 80, "email": "long@example.com",
                  "password": "quay-crane-42"},
        )
        assert r.status_code == 422, r.text

    def test_name_at_the_limit_is_accepted(self, admin_client, png_bytes):
        r = admin_client.post(
            API_PREFIX + "/auth/register",
            json={"name": "y" * 50, "email": "ok50@example.com",
                  "password": "quay-crane-42"},
        )
        assert r.status_code == 201, r.text


class TestCaseInsensitiveEmail:
    """The service lowercased lookups but the UNIQUE index did not."""

    def test_duplicate_email_different_case_is_rejected(self, admin_client):
        assert admin_client.post(
            API_PREFIX + "/auth/register",
            json={"name": "A", "email": "Dup@Example.com",
                  "password": "quay-crane-42"},
        ).status_code == 201

        # Caught by the service's case-insensitive lookup, so it is a 400 with
        # a clear message. The DB index is the safety net for concurrent writes.
        r = admin_client.post(
            API_PREFIX + "/auth/register",
            json={"name": "B", "email": "dup@example.com",
                  "password": "quay-crane-42"},
        )
        assert r.status_code in (400, 409), r.text

    def test_lowercase_normalisation_is_visible(self, admin_client):
        r = admin_client.post(
            API_PREFIX + "/auth/register",
            json={"name": "Norm", "email": "MixedCase@Example.COM",
                  "password": "quay-crane-42"},
        )
        assert r.json()["data"]["user"]["email"] == "mixedcase@example.com"

    def test_database_index_blocks_concurrent_duplicates(self, db):
        """The service check has a race; the unique index is the real guard.

        Two requests can both pass the lookup before either commits. Only the
        index makes the second one fail, and it fails as an IntegrityError the
        global handler turns into a 409.
        """
        from sqlalchemy.exc import IntegrityError

        import models
        from models.user import User

        db.add_all([
            User(name="Racer", email="Race@Example.com"),
            User(name="Racer", email="race@example.com"),
        ])
        try:
            db.commit()
            raise AssertionError("expected IntegrityError: index did not fire")
        except IntegrityError:
            db.rollback()

    def test_inspection_reuses_user_regardless_of_case(self, admin_client, png_bytes):
        first = admin_client.post(
            API_PREFIX + "/auth/register",
            json={"name": "Case", "email": "Case@Example.com",
                  "password": "quay-crane-42"},
        )
        uid = first.json()["data"]["user"]["id"]
        # Register signs the client in as Case; sign back in as admin.
        admin_client.post(API_PREFIX + "/auth/login", json={"email": "admin@example.com",
                                               "password": "quay-crane-42"})

        r = admin_client.post(
            API_PREFIX + "/admin/submissions",
            data={"name": "case", "email": "CASE@EXAMPLE.COM",
                  "cargo_type": "scrap-steel"},
            files={"image": ("a.png", png_bytes(), "image/png")},
        )
        assert r.status_code == 201
        assert r.json()["data"]["user_id"] == uid


class TestErrorHandling:
    """Unhandled errors used to leak a traceback and return a bare 500."""

    def test_unhandled_error_returns_json_with_request_id(self, client):
        # Force a genuine internal error rather than simulating one.
        import main

        @main.app.get("/_boom")
        def boom():
            raise RuntimeError("deliberate test failure")

        r = client.get("/_boom")
        assert r.status_code == 500
        body = r.json()
        assert "request_id" in body
        assert "traceback" not in r.text.lower()
        assert "deliberate test failure" not in r.text


class TestFormattingContract:
    """docs/API_CONVENTIONS.md §2/§4/§5/§6, made executable.

    Each assertion pins one convention the API made once and then kept
    making everywhere: idempotent DELETE, the replay header, Allow on 405,
    ISO 8601 UTC timestamps, omitted nulls, and surface-scoped URLs.
    """

    def _submission(self, client, png_bytes):
        client.post(API_PREFIX + "/auth/register", json={"name": "Fmt",
                                            "email": "fmt@example.com",
                                            "password": "quay-crane-42"})
        r = client.post(API_PREFIX + "/portal/submissions", data={"cargo_type": "scrap-steel"},
                        files={"image": ("f.png", png_bytes(), "image/png")})
        assert r.status_code == 201, r.text
        return r

    def test_delete_is_idempotent_with_an_empty_body(self, client, png_bytes):
        iid = self._submission(client, png_bytes).json()["data"]["id"]
        assert client.delete(f"{API_PREFIX}/portal/submissions/{iid}").status_code == 204
        # Repeat delete: still 204, not 404 (§5) — and never a "null" body.
        r = client.delete(f"{API_PREFIX}/portal/submissions/{iid}")
        assert r.status_code == 204
        assert r.content == b""

    def test_admin_delete_is_idempotent(self, admin_client, png_bytes):
        created = admin_client.post(
            API_PREFIX + "/admin/submissions",
            data={"name": "A", "email": "adm-fmt@example.com",
                  "cargo_type": "other"},
            files={"image": ("a.png", png_bytes(), "image/png")},
        )
        iid = created.json()["data"]["id"]
        assert admin_client.delete(f"{API_PREFIX}/admin/submissions/{iid}").status_code == 204
        assert admin_client.delete(f"{API_PREFIX}/admin/submissions/{iid}").status_code == 204

    def test_idempotent_replay_carries_the_header(self, client, png_bytes):
        self._submission(client, png_bytes)
        files = {"image": ("a.png", png_bytes(), "image/png")}
        first = client.post(API_PREFIX + "/portal/submissions", data={"cargo_type": "other"},
                            files=files, headers={"Idempotency-Key": "fmt-key"})
        second = client.post(API_PREFIX + "/portal/submissions", data={"cargo_type": "other"},
                             files=files, headers={"Idempotency-Key": "fmt-key"})
        assert first.status_code == 201
        assert first.headers.get("Idempotent-Replay") is None
        assert second.headers.get("Idempotent-Replay") == "true"
        assert second.json()["data"]["id"] == first.json()["data"]["id"]

    def test_405_carries_allow_and_a_problem_body(self, client):
        r = client.put(API_PREFIX + "/auth/login", json={})
        assert r.status_code == 405
        assert "allow" in {k.lower() for k in r.headers}
        assert r.headers["content-type"].startswith("application/problem+json")

    def test_timestamps_are_iso8601_utc(self, client, png_bytes):
        body = self._submission(client, png_bytes).json()["data"]
        assert body["created_at"].endswith("Z"), body["created_at"]
        assert "T" in body["created_at"]

    def test_unset_fields_are_omitted_not_null(self, client, png_bytes):
        body = self._submission(client, png_bytes).json()["data"]
        for key in ("phone", "notes", "status_note", "reviewed_by",
                    "reviewed_at", "detected_at", "volume_m3",
                    "estimated_weight_kg"):
            assert key not in body, f"{key} should be omitted, not null"

    def test_image_url_matches_the_surface(self, client, png_bytes, admin_client):
        iid = self._submission(client, png_bytes).json()["data"]["id"]
        mine = client.get(f"{API_PREFIX}/portal/submissions/{iid}").json()["data"]
        assert mine["image_url"] == f"{API_PREFIX}/portal/submissions/{iid}/image"
        theirs = admin_client.get(f"{API_PREFIX}/admin/submissions/{iid}").json()["data"]
        assert theirs["image_url"] == f"{API_PREFIX}/admin/submissions/{iid}/image"