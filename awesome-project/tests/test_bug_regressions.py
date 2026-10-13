"""Regressions for the bugs found in review.

Each test here corresponds to a specific defect that was measured, not
guessed. If one fails, the bug is back.
"""

from __future__ import annotations


class TestPaginationBounds:
    """`limit=-5` used to reach PostgreSQL and surface as a 500."""

    def test_negative_limit_is_422(self, admin_client):
        assert admin_client.get("/admin/submissions?limit=-5").status_code == 422

    def test_negative_skip_is_422(self, admin_client):
        assert admin_client.get("/admin/submissions?skip=-1").status_code == 422

    def test_zero_limit_is_422(self, admin_client):
        assert admin_client.get("/admin/submissions?limit=0").status_code == 422

    def test_absurd_limit_is_422_not_the_whole_table(self, admin_client):
        assert admin_client.get("/admin/submissions?limit=999999").status_code == 422

    def test_non_numeric_is_422(self, admin_client):
        assert admin_client.get("/admin/submissions?skip=abc").status_code == 422

    def test_valid_bounds_accepted(self, admin_client):
        assert admin_client.get("/admin/submissions?skip=0&limit=100").status_code == 200


class TestNameLength:
    """An over-long name overflowed String(50) and returned 500."""

    def test_name_longer_than_column_is_422(self, admin_client):
        r = admin_client.post(
            "/auth/register",
            json={"name": "x" * 80, "email": "long@example.com",
                  "password": "quay-crane-42"},
        )
        assert r.status_code == 422, r.text

    def test_name_at_the_limit_is_accepted(self, admin_client, png_bytes):
        r = admin_client.post(
            "/auth/register",
            json={"name": "y" * 50, "email": "ok50@example.com",
                  "password": "quay-crane-42"},
        )
        assert r.status_code == 201, r.text


class TestCaseInsensitiveEmail:
    """The service lowercased lookups but the UNIQUE index did not."""

    def test_duplicate_email_different_case_is_rejected(self, admin_client):
        assert admin_client.post(
            "/auth/register",
            json={"name": "A", "email": "Dup@Example.com",
                  "password": "quay-crane-42"},
        ).status_code == 201

        # Caught by the service's case-insensitive lookup, so it is a 400 with
        # a clear message. The DB index is the safety net for concurrent writes.
        r = admin_client.post(
            "/auth/register",
            json={"name": "B", "email": "dup@example.com",
                  "password": "quay-crane-42"},
        )
        assert r.status_code in (400, 409), r.text

    def test_lowercase_normalisation_is_visible(self, admin_client):
        r = admin_client.post(
            "/auth/register",
            json={"name": "Norm", "email": "MixedCase@Example.COM",
                  "password": "quay-crane-42"},
        )
        assert r.json()["user"]["email"] == "mixedcase@example.com"

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
            "/auth/register",
            json={"name": "Case", "email": "Case@Example.com",
                  "password": "quay-crane-42"},
        )
        uid = first.json()["user"]["id"]
        # Register signs the client in as Case; sign back in as admin.
        admin_client.post("/auth/login", json={"email": "admin@example.com",
                                               "password": "quay-crane-42"})

        r = admin_client.post(
            "/admin/submissions",
            data={"name": "case", "email": "CASE@EXAMPLE.COM",
                  "cargo_type": "scrap-steel"},
            files={"image": ("a.png", png_bytes(), "image/png")},
        )
        assert r.status_code == 201
        assert r.json()["user_id"] == uid


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