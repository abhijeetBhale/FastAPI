"""Query patterns: eager loading, filtering, aggregates, soft delete.

These are the tests worth reading to understand the SQL the service produces.
"""

from __future__ import annotations

import pytest
from sqlalchemy import event
from sqlalchemy.engine import Engine


def count_queries() -> list[str]:
    """Collect SQL statements for the duration of a test."""
    statements: list[str] = []

    def _before(conn, cursor, statement, params, context, executemany):
        statements.append(statement.strip().split("\n")[0][:80])

    event.listen(Engine, "before_cursor_execute", _before)
    return statements


@pytest.fixture
def queries():
    stmts = []

    def _before(conn, cursor, statement, params, context, executemany):
        stmts.append(statement.strip().split("\n")[0][:80])

    event.listen(Engine, "before_cursor_execute", _before)
    yield stmts
    event.remove(Engine, "before_cursor_execute", _before)


@pytest.fixture
def seeded(client, png_bytes):
    """Three inspections, two users, varied cargo types and tags."""
    made = []
    for name, email, cargo, tags in [
        ("Alpha", "alpha@example.com", "scrap-steel", "urgent,heavy"),
        ("Beta", "beta@example.com", "thermal-coal", "heavy"),
        ("Gamma", "gamma@example.com", "scrap-steel", "urgent"),
    ]:
        r = client.post(
            "/inspections/",
            data={
                "name": name,
                "email": email,
                "cargo_type": cargo,
                "tags": tags,
                "notes": f"{name} load",
            },
            files={"image": (f"{name}.png", png_bytes(8, 8), "image/png")},
        )
        assert r.status_code == 201, r.text
        made.append(r.json())
    return made


class TestNoN1Queries:
    def test_listing_many_inspections_uses_a_fixed_number_of_queries(
        self, client, seeded, queries
    ):
        """Serialising user/cargo/tags must not issue a query per row."""
        # Warm the connection so pool setup is not counted.
        client.get("/inspections/?limit=1")
        queries.clear()

        r = client.get("/inspections/?limit=100")
        assert r.status_code == 200
        assert len(r.json()["items"]) == 3

        user_queries = [q for q in queries if q.upper().startswith("SELECT USERS")]
        # 3 rows -> must be 1 batched selectinload, not 3.
        assert len(user_queries) <= 2, (
            f"expected batched eager loading, got {len(user_queries)} "
            f"user queries:\n" + "\n".join(user_queries)
        )


class TestFiltering:
    def test_filter_by_cargo_type(self, client, seeded):
        r = client.get("/inspections/?cargo_type=scrap-steel")
        assert r.status_code == 200
        assert r.json()["total"] == 2

    def test_filter_by_status(self, client, seeded):
        assert client.get("/inspections/?status=submitted").json()["total"] == 3
        assert client.get("/inspections/?status=approved").json()["total"] == 0

    def test_filter_by_tag(self, client, seeded):
        r = client.get("/inspections/?tag=urgent")
        assert r.json()["total"] == 2

    def test_search_matches_notes_name_and_filename(self, client, seeded):
        assert client.get("/inspections/?search=Beta").json()["total"] == 1
        assert client.get("/inspections/?search=Alpha").json()["total"] == 1
        assert client.get("/inspections/?search=alpha@example").json()["total"] == 1

    def test_combined_filters_are_anded(self, client, seeded):
        r = client.get("/inspections/?cargo_type=scrap-steel&tag=heavy")
        assert r.json()["total"] == 1

    def test_unknown_status_is_422(self, client, seeded):
        assert client.get("/inspections/?status=bogus").status_code == 422

    def test_unknown_sort_column_is_422(self, client, seeded):
        assert client.get("/inspections/?sort=image_filename").status_code == 422

    def test_sort_is_not_sql_injectable(self, client, seeded):
        # Whitelisted, never interpolated. Must be rejected, not executed.
        r = client.get("/inspections/?sort=id;DROP TABLE users")
        assert r.status_code == 422
        assert client.get("/users/").status_code == 200


class TestPagination:
    def test_envelope_reports_totals(self, client, seeded):
        r = client.get("/inspections/?limit=2").json()
        assert r["total"] == 3
        assert len(r["items"]) == 2
        assert r["pages"] == 2

    def test_pages_do_not_overlap(self, client, seeded):
        first = client.get("/inspections/?skip=0&limit=2&sort=id").json()
        second = client.get("/inspections/?skip=2&limit=2&sort=id").json()
        ids_a = {i["id"] for i in first["items"]}
        ids_b = {i["id"] for i in second["items"]}
        assert ids_a and ids_b
        assert not (ids_a & ids_b)


class TestSoftDelete:
    def test_deleted_rows_are_hidden(self, client, seeded):
        victim = seeded[0]["id"]
        assert client.delete(f"/inspections/{victim}").status_code == 204

        assert client.get(f"/inspections/{victim}").status_code == 404
        assert client.get("/inspections/").json()["total"] == 2

    def test_deleted_rows_can_be_listed_explicitly(self, client, seeded):
        client.delete(f"/inspections/{seeded[0]['id']}")
        r = client.get("/inspections/?include_deleted=true")
        assert r.json()["total"] == 3

    def test_restore_brings_the_row_back(self, client, seeded):
        victim = seeded[0]["id"]
        client.delete(f"/inspections/{victim}")
        assert client.post(f"/inspections/{victim}/restore").status_code == 200
        assert client.get(f"/inspections/{victim}").status_code == 200

    def test_purge_removes_it_for_good(self, client, seeded):
        victim = seeded[0]["id"]
        assert client.delete(f"/inspections/{victim}/purge").status_code == 204
        assert (
            client.get(f"/inspections/{victim}?include_deleted=true").status_code
            == 404
        )


class TestAggregates:
    def test_per_user_summary(self, client, seeded):
        r = client.get("/inspections/summary")
        assert r.status_code == 200
        rows = {row["email"]: row for row in r.json()}
        alpha = rows["alpha@example.com"]
        assert alpha["inspection_count"] == 1
        assert alpha["approved_count"] == 0
        assert alpha["last_inspection_at"] is not None

    def test_summary_is_ordered_by_volume(self, client, seeded):
        rows = client.get("/inspections/summary").json()
        counts = [r["inspection_count"] for r in rows]
        assert counts == sorted(counts, reverse=True)

    def test_summary_includes_a_user_with_no_inspections(self, client, seeded):
        client.post("/users/", json={"name": "Nobody", "email": "nobody@example.com"})
        rows = {r["email"]: r for r in client.get("/inspections/summary").json()}
        # outerjoin, not innerjoin: zero-inspection users must still appear.
        assert rows["nobody@example.com"]["inspection_count"] == 0
        assert rows["nobody@example.com"]["total_weight_kg"] == 0.0

    def test_stats_headline_numbers(self, client, seeded):
        r = client.get("/inspections/stats").json()
        assert r["inspections"] == 3
        assert r["approved"] == 0

    def test_summary_excludes_soft_deleted(self, client, seeded):
        client.delete(f"/inspections/{seeded[0]['id']}")
        r = client.get("/inspections/summary").json()
        alpha = [x for x in r if x["email"] == "alpha@example.com"][0]
        assert alpha["inspection_count"] == 0

    def test_orphaned_users_uses_not_exists(self, client, seeded):
        # A user who exists but has never submitted an inspection.
        client.post("/users/", json={"name": "Idle", "email": "idle@example.com"})
        r = client.get("/inspections/orphaned-users")
        assert r.status_code == 200
        emails = {u["email"] for u in r.json()}
        assert "idle@example.com" in emails
        assert "alpha@example.com" not in emails


class TestStatusWorkflow:
    def test_patch_status(self, client, seeded):
        r = client.patch(
            f"/inspections/{seeded[0]['id']}",
            json={"status": "approved", "status_note": "looks fine"},
        )
        assert r.status_code == 200
        assert r.json()["status"] == "approved"

    def test_invalid_status_is_rejected(self, client, seeded):
        r = client.patch(f"/inspections/{seeded[0]['id']}", json={"status": "nope"})
        assert r.status_code == 422

    def test_create_with_explicit_status(self, client, png_bytes):
        r = client.post(
            "/inspections/",
            data={"name": "D", "email": "d@example.com",
                  "cargo_type": "other", "status": "draft"},
            files={"image": ("a.png", png_bytes(), "image/png")},
        )
        assert r.json()["status"] == "draft"


class TestIdempotency:
    def test_replay_returns_the_original_without_duplicating(
        self, client, png_bytes
    ):
        payload = {
            "name": "Idem",
            "email": "idem@example.com",
            "cargo_type": "scrap-steel",
        }
        files = {"image": ("a.png", png_bytes(), "image/png")}

        first = client.post(
            "/inspections/", data=payload, files=files,
            headers={"Idempotency-Key": "key-abc-123"},
        )
        assert first.status_code == 201

        second = client.post(
            "/inspections/", data=payload, files=files,
            headers={"Idempotency-Key": "key-abc-123"},
        )
        assert second.status_code == 201
        assert second.json()["id"] == first.json()["id"]
        assert client.get("/inspections/").json()["total"] == 1

    def test_different_keys_create_different_rows(self, client, png_bytes):
        payload = {"name": "K", "email": "k@example.com", "cargo_type": "other"}
        files = {"image": ("a.png", png_bytes(), "image/png")}
        a = client.post("/inspections/", data=payload, files=files,
                        headers={"Idempotency-Key": "k1"})
        b = client.post("/inspections/", data=payload, files=files,
                        headers={"Idempotency-Key": "k2"})
        assert a.json()["id"] != b.json()["id"]


class TestAuditTrail:
    def test_creation_is_audited(self, client, seeded, db):
        from models.audit_log import AuditLog

        insp = seeded[0]
        entries = (
            db.query(AuditLog)
            .filter(AuditLog.entity_type == "inspection")
            .filter(AuditLog.entity_id == insp["id"])
            .all()
        )
        assert any(e.action == "create" for e in entries)

    def test_status_change_is_audited(self, client, seeded, db):
        from models.audit_log import AuditLog

        insp = seeded[0]
        client.patch(f"/inspections/{insp['id']}", json={"status": "approved"})
        actions = [
            e.action
            for e in db.query(AuditLog)
            .filter(AuditLog.entity_type == "inspection")
            .filter(AuditLog.entity_id == insp["id"])
            .all()
        ]
        assert "update" in actions


class TestCargoTypeLookup:
    def test_lookup_table_is_seeded(self, client):
        r = client.get("/inspections/cargo-types")
        assert r.status_code == 200
        slugs = {c["slug"] for c in r.json()}
        assert {"scrap-steel", "thermal-coal", "construction-gravel",
                "agricultural-grain", "other"} <= slugs

    def test_densities_are_exposed(self, client):
        types = {c["slug"]: c for c in client.get("/inspections/cargo-types").json()}
        assert types["scrap-steel"]["density_kg_m3"] == 7850.0
        assert types["thermal-coal"]["density_kg_m3"] == 800.0

    def test_unknown_slug_falls_back_to_other(self, client, png_bytes):
        r = client.post(
            "/inspections/",
            data={"name": "X", "email": "x@fallback.com",
                  "cargo_type": "unobtainium"},
            files={"image": ("a.png", png_bytes(), "image/png")},
        )
        assert r.status_code == 201
        assert r.json()["cargo_type"] == "other"

    def test_response_includes_label_and_density(self, client, png_bytes):
        r = client.post(
            "/inspections/",
            data={"name": "Y", "email": "y@label.com",
                  "cargo_type": "thermal-coal"},
            files={"image": ("a.png", png_bytes(), "image/png")},
        ).json()
        assert r["cargo_label"] == "Thermal Coal"
        assert r["density_kg_m3"] == 800.0


class TestTags:
    def test_tags_round_trip(self, client, seeded):
        r = client.get(f"/inspections/{seeded[0]['id']}").json()
        assert {t["name"] for t in r["tags"]} == {"urgent", "heavy"}

    def test_tags_are_reused_not_duplicated(self, client, seeded, db):
        from models.tag import Tag

        names = [t.name for t in db.query(Tag).order_by(Tag.name).all()]
        assert names.count("urgent") == 1

    def test_patch_replaces_tags(self, client, seeded):
        r = client.patch(
            f"/inspections/{seeded[0]['id']}", json={"tags": ["recheck"]}
        )
        assert {t["name"] for t in r.json()["tags"]} == {"recheck"}