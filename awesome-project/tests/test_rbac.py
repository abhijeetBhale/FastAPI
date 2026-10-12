"""Role-based access control.

The property under test is that a *user* cannot do anything an *admin* can, and
that a user can never act outside their own submissions — regardless of what
they put in a URL or a form field.
"""

from __future__ import annotations

import pytest

from models.user import User
from services.rbac import (
    P_AUDIT_READ,
    P_SUBMISSIONS_CREATE,
    P_SUBMISSIONS_READ_ANY,
    P_SUBMISSIONS_REVIEW_ANY,
    Role,
    has_permission,
    permissions_for,
)


def png_bytes(w=8, h=8):
    import struct, zlib

    def chunk(t, b):
        return struct.pack(">I", len(b)) + t + b + struct.pack(
            ">I", zlib.crc32(t + b) & 0xFFFFFFFF)

    raw = b"".join(b"\x00" + bytes((10, 120, 200)) * w for _ in range(h))
    return (b"\x89PNG\r\n\x1a\n"
            + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw))
            + chunk(b"IEND", b""))


@pytest.fixture
def users(client, db, png_bytes):
    """A regular user (reg) and an admin (boss), each with one submission."""
    client.post("/auth/register", json={"name": "Regular", "email": "reg@example.com",
                                        "password": "quay-crane-42"})
    reg = client.post("/portal/submissions", data={"cargo_type": "scrap-steel"},
                      files={"image": ("r.png", png_bytes(), "image/png")}).json()
    client.post("/auth/logout")
    client.cookies.clear()

    client.post("/auth/register", json={"name": "Boss", "email": "boss@example.com",
                                        "password": "quay-crane-42"})
    # Boss is the administrator.
    boss = db.query(User).filter(User.email == "boss@example.com").one()
    boss.role = Role.ADMIN.value
    db.commit()
    adm = client.post("/portal/submissions", data={"cargo_type": "thermal-coal"},
                      files={"image": ("a.png", png_bytes(), "image/png")}).json()
    return {"reg": reg, "adm": adm}


def as_user(client, email="reg@example.com", pw="quay-crane-42"):
    client.cookies.clear()
    return client.post("/auth/login", json={"email": email, "password": pw})


# ------------------------------------------------------------------ model
class TestPermissionModel:
    def test_user_lacks_admin_permissions(self, db):
        u = User(name="U", email="u@x.com", role="user")
        assert not has_permission(u, P_SUBMISSIONS_READ_ANY)
        assert not has_permission(u, P_SUBMISSIONS_REVIEW_ANY)
        assert not has_permission(u, P_AUDIT_READ)

    def test_user_keeps_own_actions(self, db):
        u = User(name="U", email="u@x.com", role="user")
        assert has_permission(u, P_SUBMISSIONS_CREATE)

    def test_admin_has_everything(self, db):
        a = User(name="A", email="a@x.com", role="admin")
        for p in (P_SUBMISSIONS_READ_ANY, P_SUBMISSIONS_REVIEW_ANY, P_AUDIT_READ):
            assert has_permission(a, p)

    def test_unknown_role_degrades_to_least_privilege(self, db):
        """Fail closed: a corrupt role must not grant access."""
        u = User(name="U", email="u@x.com", role="superuser")
        assert not has_permission(u, P_SUBMISSIONS_REVIEW_ANY)
        assert has_permission(u, P_SUBMISSIONS_CREATE)

    def test_permission_list_for_the_ui(self, client):
        r = client.post("/auth/register", json={"name": "P", "email": "p@x.com",
                                                "password": "quay-crane-42"})
        assert r.status_code == 201
        me = client.get("/auth/me").json()
        assert me["is_admin"] is False
        assert "submissions:review:any" not in me["permissions"]


# ------------------------------------------------------------------ middleware
class TestMiddlewareGating:
    def test_admin_prefix_needs_a_session(self, client):
        client.cookies.clear()
        r = client.get("/admin/submissions")
        assert r.status_code == 401
        assert r.json()["code"] == "authentication_required"

    @pytest.mark.parametrize("path", [
        "/admin/submissions", "/admin/stats", "/admin/audit",
        "/admin/users", "/admin/submissions/pending",
    ])
    def test_every_admin_path_is_401_when_signed_out(self, client, path):
        client.cookies.clear()
        assert client.get(path).status_code == 401

    def test_non_admin_on_admin_path_is_403(self, client, users):
        as_user(client)
        r = client.get("/admin/submissions")
        assert r.status_code == 403
        assert r.json()["code"] == "insufficient_role"

    def test_garbage_cookie_is_401_not_500(self, client):
        client.cookies.set("session_token", "not-a-real-token")
        assert client.get("/admin/submissions").status_code == 401

    def test_public_paths_stay_open(self, client):
        client.cookies.clear()
        assert client.get("/health").status_code == 200
        assert client.get("/").status_code == 200

    def test_request_id_header_is_returned(self, client):
        r = client.get("/health")
        assert "X-Request-ID" in r.headers
        assert "X-Response-Time-ms" in r.headers


# ------------------------------------------------------------------ closed hole
class TestPreviouslyOpenRoutes:
    """These were reachable with NO cookie before RBAC existed."""

    def test_patch_inspection_requires_admin(self, client, users):
        client.cookies.clear()                      # no session at all
        r = client.patch(f"/inspections/{users['reg']['id']}",
                         json={"status": "approved"})
        assert r.status_code == 401, "was 200 before RBAC"

    def test_regular_user_cannot_patch_status(self, client, users):
        as_user(client)
        r = client.patch(f"/inspections/{users['reg']['id']}",
                         json={"status": "approved"})
        assert r.status_code == 403

    def test_purge_requires_admin(self, client, users):
        client.cookies.clear()
        assert client.delete(f"/inspections/{users['reg']['id']}/purge").status_code == 401

    def test_user_list_requires_admin(self, client, users):
        client.cookies.clear()
        r = client.get("/users/")
        assert r.status_code == 403 or r.status_code == 401

    def test_user_list_blocked_for_regular_user(self, client, users):
        as_user(client)
        assert client.get("/users/").status_code == 403

    def test_admin_can_patch(self, client, users):
        as_user(client, "boss@example.com")
        r = client.patch(f"/inspections/{users['reg']['id']}",
                         json={"status": "approved"})
        assert r.status_code == 200
        assert r.json()["status"] == "approved"


# ------------------------------------------------------------------ review flow
class TestAdminReview:
    def test_admin_sees_every_submission(self, client, users):
        as_user(client, "boss@example.com")
        r = client.get("/admin/submissions")
        assert r.status_code == 200
        ids = {i["id"] for i in r.json()["items"]}
        assert ids == {users["reg"]["id"], users["adm"]["id"]}

    def test_pending_queue_holds_submitted_only(self, client, users):
        as_user(client, "boss@example.com")
        assert client.get("/admin/submissions/pending").json()["total"] == 2

        client.post(f"/admin/submissions/{users['reg']['id']}/approve")
        assert client.get("/admin/submissions/pending").json()["total"] == 1

    def test_approve_records_who_and_when(self, client, users):
        as_user(client, "boss@example.com")
        r = client.post(f"/admin/submissions/{users['reg']['id']}/approve",
                        params={"note": "looks correct"})
        assert r.status_code == 200
        body = r.json()
        assert body["status"] == "approved"
        assert body["status_note"] == "looks correct"
        assert body["reviewed_by"] is not None
        assert body["reviewed_at"] is not None

    def test_reject(self, client, users):
        as_user(client, "boss@example.com")
        r = client.post(f"/admin/submissions/{users['reg']['id']}/reject",
                        params={"note": "blurry"})
        assert r.json()["status"] == "rejected"

    def test_user_cannot_approve_anything(self, client, users):
        as_user(client, "reg@example.com")
        r = client.post(f"/admin/submissions/{users['adm']['id']}/approve")
        assert r.status_code == 403

    def test_duplicate_decision_is_409(self, client, users):
        as_user(client, "boss@example.com")
        iid = users["reg"]["id"]
        assert client.post(f"/admin/submissions/{iid}/approve").status_code == 200
        assert client.post(f"/admin/submissions/{iid}/approve").status_code == 409

    def test_decision_on_missing_submission_is_404(self, client, users):
        as_user(client, "boss@example.com")
        assert client.post("/admin/submissions/999999/approve").status_code == 404

    def test_bulk_decide(self, client, users):
        as_user(client, "boss@example.com")
        r = client.post("/admin/submissions/bulk", json={
            "ids": [users["reg"]["id"], users["adm"]["id"], 999999],
            "action": "approve",
        })
        assert r.status_code == 200
        body = r.json()
        assert body["processed"] == 3
        assert sum(1 for x in body["results"] if x["ok"]) == 2

    def test_bulk_rejects_bad_action(self, client, users):
        as_user(client, "boss@example.com")
        r = client.post("/admin/submissions/bulk",
                        json={"ids": [1], "action": "delete"})
        assert r.status_code == 422

    def test_decision_is_audited(self, client, users, db):
        from models.audit_log import AuditLog

        as_user(client, "boss@example.com")
        client.post(f"/admin/submissions/{users['reg']['id']}/approve")

        entries = db.query(AuditLog).filter(AuditLog.action == "approved").all()
        assert entries, "approval must leave an audit trail"
        assert entries[0].entity_id == users["reg"]["id"]

    def test_admin_can_serve_any_image(self, client, users):
        as_user(client, "boss@example.com")
        r = client.get(f"/admin/submissions/{users['reg']['id']}/image")
        assert r.status_code == 200
        assert r.headers["content-type"].startswith("image/")


class TestImageAccess:
    """Images are on the protected router, so each surface needs its own route.

    A regression hid the portal's own thumbnails behind the admin permission;
    these tests pin both halves so it cannot come back.
    """

    def test_owner_can_view_their_own_image(self, client, users):
        as_user(client, "reg@example.com")
        r = client.get(f"/portal/submissions/{users['reg']['id']}/image")
        assert r.status_code == 200, "portal thumbnails must load for the owner"
        assert r.headers["content-type"].startswith("image/")

    def test_user_cannot_view_another_users_image(self, client, users):
        as_user(client, "reg@example.com")
        r = client.get(f"/portal/submissions/{users['adm']['id']}/image")
        assert r.status_code == 404

    def test_admin_image_route_is_not_user_accessible(self, client, users):
        as_user(client, "reg@example.com")
        assert client.get(
            f"/inspections/{users['reg']['id']}/image"
        ).status_code == 403

    def test_anonymous_cannot_fetch_images(self, client, users):
        client.cookies.clear()
        assert client.get(
            f"/inspections/{users['reg']['id']}/image"
        ).status_code == 401


# ------------------------------------------------------------------ user limits
class TestUserCannotSelfApprove:
    def test_portal_upload_rejects_approved_status(self, client, users, png_bytes):
        as_user(client, "reg@example.com")
        r = client.post("/portal/submissions",
                        data={"cargo_type": "other", "status": "approved"},
                        files={"image": ("x.png", png_bytes(), "image/png")})
        assert r.status_code == 403
        assert "administrator" in r.json()["detail"].lower()

    def test_portal_upload_rejects_rejected_status(self, client, users, png_bytes):
        as_user(client, "reg@example.com")
        r = client.post("/portal/submissions",
                        data={"cargo_type": "other", "status": "rejected"},
                        files={"image": ("x.png", png_bytes(), "image/png")})
        assert r.status_code == 403

    def test_draft_and_submitted_are_allowed(self, client, users, png_bytes):
        as_user(client, "reg@example.com")
        for status in ("draft", "submitted"):
            r = client.post("/portal/submissions",
                            data={"cargo_type": "other", "status": status},
                            files={"image": ("x.png", png_bytes(), "image/png")})
            assert r.status_code == 201, status


class TestUserIsolationStillHolds:
    def test_user_cannot_read_another_users_submission(self, client, users):
        as_user(client, "reg@example.com")
        r = client.get(f"/portal/submissions/{users['adm']['id']}")
        assert r.status_code == 404

    def test_user_cannot_withdraw_another_users(self, client, users):
        as_user(client, "reg@example.com")
        assert client.delete(f"/portal/submissions/{users['adm']['id']}").status_code == 404

    def test_user_cannot_read_another_user_profile(self, client, users, db):
        boss = db.query(User).filter(User.email == "boss@example.com").one()
        as_user(client, "reg@example.com")
        assert client.get(f"/users/{boss.id}").status_code == 404

    def test_user_can_read_own_profile(self, client, users, db):
        me = db.query(User).filter(User.email == "reg@example.com").one()
        as_user(client, "reg@example.com")
        assert client.get(f"/users/{me.id}").status_code == 200

    def test_admin_can_read_any_profile(self, client, users, db):
        reg = db.query(User).filter(User.email == "reg@example.com").one()
        as_user(client, "boss@example.com")
        assert client.get(f"/users/{reg.id}").status_code == 200


# ------------------------------------------------------------------ admin tools
class TestAdminTools:
    def test_audit_readable_by_admin_only(self, client, users):
        as_user(client, "boss@example.com")
        assert client.get("/admin/audit").status_code == 200

        as_user(client, "reg@example.com")
        assert client.get("/admin/audit").status_code == 403

    def test_platform_stats(self, client, users):
        as_user(client, "boss@example.com")
        s = client.get("/admin/stats").json()
        assert s["stats"]["inspections"] == 2
        assert s["users"] >= 2
        assert s["by_cargo"]

    def test_promote_user_to_admin(self, client, users, db):
        as_user(client, "boss@example.com")
        reg = db.query(User).filter(User.email == "reg@example.com").one()
        r = client.post(f"/admin/users/{reg.id}/role", params={"role": "admin"})
        assert r.status_code == 200
        assert r.json()["role"] == "admin"

    def test_admin_cannot_demote_self(self, client, users, db):
        as_user(client, "boss@example.com")
        boss = db.query(User).filter(User.email == "boss@example.com").one()
        r = client.post(f"/admin/users/{boss.id}/role", params={"role": "user"})
        assert r.status_code == 400

    def test_role_must_be_valid(self, client, users, db):
        as_user(client, "boss@example.com")
        reg = db.query(User).filter(User.email == "reg@example.com").one()
        assert client.post(
            f"/admin/users/{reg.id}/role", params={"role": "superuser"}
        ).status_code == 422

    def test_restore_soft_deleted(self, client, users):
        as_user(client, "reg@example.com")
        iid = users["reg"]["id"]
        assert client.delete(f"/portal/submissions/{iid}").status_code == 204

        as_user(client, "boss@example.com")
        assert client.get(f"/admin/submissions/{iid}?include_deleted=true").status_code == 200
        assert client.post(f"/admin/submissions/{iid}/restore").status_code == 200