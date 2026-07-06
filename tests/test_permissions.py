"""Granular per-staff permissions: the owner grants individual admin areas
(orders, catalog, ...) to staff from the Staff tab. Secrets-bearing areas
(integrations, staff management, go-live) are never grantable."""

import os
import tempfile
import unittest

from cryptography.fernet import Fernet

os.environ.setdefault("MGS_SECRET_KEY", Fernet.generate_key().decode())

from fastapi.testclient import TestClient  # noqa: E402

from api.app import create_app  # noqa: E402
from api.db import dispose_engine  # noqa: E402
from api.models_db import STAFF_PERMISSIONS  # noqa: E402


class StaffPermissionsTest(unittest.TestCase):
    def setUp(self):
        os.environ["MGS_ADMIN_PASSWORD"] = "owner-pass-123"
        self._tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self._tmp.close()
        # Real auth flow — no dependency overrides.
        self.client = TestClient(create_app(db_url=f"sqlite:///{self._tmp.name}"))
        self.owner = self._login("admin", "owner-pass-123").json()["token"]

    def tearDown(self):
        dispose_engine()  # Windows: release the SQLite file lock before unlink
        os.unlink(self._tmp.name)

    def _login(self, username, password):
        return self.client.post("/api/auth/login", json={"username": username, "password": password})

    def _auth(self, token):
        return {"Authorization": f"Bearer {token}"}

    def _make_staff(self, username="jo", password="pw123", permissions=None):
        body = {"username": username, "password": password}
        if permissions is not None:
            body["permissions"] = permissions
        r = self.client.post("/api/staff", json=body, headers=self._auth(self.owner))
        self.assertEqual(r.status_code, 201, r.text)
        return r.json()

    def _staff_token(self, username="jo", password="pw123"):
        r = self._login(username, password)
        self.assertEqual(r.status_code, 200)
        return r.json()["token"]

    # ---- defaults ----
    def test_new_staff_have_no_grants(self):
        u = self._make_staff()
        self.assertEqual(u["permissions"], [])
        h = self._auth(self._staff_token())
        for path in ("/api/orders", "/api/models", "/api/catalog", "/api/presets",
                     "/api/automations"):
            self.assertEqual(self.client.get(path, headers=h).status_code, 403, path)

    def test_operational_areas_need_no_grant(self):
        self._make_staff()
        h = self._auth(self._staff_token())
        self.assertEqual(self.client.get("/api/work/board", headers=h).status_code, 200)
        self.assertEqual(self.client.get("/api/inventory", headers=h).status_code, 200)

    # ---- granting ----
    def test_granted_area_opens_up(self):
        u = self._make_staff()
        h = self._auth(self._staff_token())
        self.assertEqual(self.client.get("/api/orders", headers=h).status_code, 403)
        r = self.client.patch(f"/api/staff/{u['id']}", json={"permissions": ["orders"]},
                              headers=self._auth(self.owner))
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["permissions"], ["orders"])
        # Same token, next request — the grant is live, no re-login needed.
        self.assertEqual(self.client.get("/api/orders", headers=h).status_code, 200)
        # Other areas stay closed.
        self.assertEqual(self.client.get("/api/catalog", headers=h).status_code, 403)

    def test_grants_at_creation(self):
        self._make_staff(permissions=["catalog", "configurator"])
        h = self._auth(self._staff_token())
        self.assertEqual(self.client.get("/api/catalog", headers=h).status_code, 200)
        self.assertEqual(self.client.get("/api/models", headers=h).status_code, 200)
        self.assertEqual(self.client.get("/api/orders", headers=h).status_code, 403)

    def test_revoke_applies_to_next_request(self):
        u = self._make_staff(permissions=["orders"])
        h = self._auth(self._staff_token())
        self.assertEqual(self.client.get("/api/orders", headers=h).status_code, 200)
        self.client.patch(f"/api/staff/{u['id']}", json={"permissions": []}, headers=self._auth(self.owner))
        # Same still-valid token: revocation is immediate.
        self.assertEqual(self.client.get("/api/orders", headers=h).status_code, 403)

    def test_disabled_account_loses_granted_areas(self):
        u = self._make_staff(permissions=["orders"])
        h = self._auth(self._staff_token())
        self.assertEqual(self.client.get("/api/orders", headers=h).status_code, 200)
        self.client.patch(f"/api/staff/{u['id']}", json={"active": False}, headers=self._auth(self.owner))
        self.assertEqual(self.client.get("/api/orders", headers=h).status_code, 403)

    # ---- hard owner-only stays hard ----
    def test_secrets_areas_forbidden_even_with_all_grants(self):
        self._make_staff(permissions=list(STAFF_PERMISSIONS))
        h = self._auth(self._staff_token())
        self.assertEqual(self.client.get("/api/integrations", headers=h).status_code, 403)
        self.assertEqual(self.client.get("/api/staff", headers=h).status_code, 403)
        self.assertEqual(self.client.get("/api/setup/status", headers=h).status_code, 403)

    def test_unknown_permission_rejected(self):
        r = self.client.post("/api/staff", json={"username": "jo", "password": "pw123",
                                                 "permissions": ["integrations"]},
                             headers=self._auth(self.owner))
        self.assertEqual(r.status_code, 400)
        u = self._make_staff(username="ann")
        r = self.client.patch(f"/api/staff/{u['id']}", json={"permissions": ["root"]},
                              headers=self._auth(self.owner))
        self.assertEqual(r.status_code, 400)

    # ---- /auth/me + catalog of grantable areas ----
    def test_me_reports_live_permissions(self):
        u = self._make_staff(permissions=["presets"])
        h = self._auth(self._staff_token())
        me = self.client.get("/api/auth/me", headers=h).json()
        self.assertEqual(me["role"], "staff")
        self.assertEqual(me["permissions"], ["presets"])
        self.client.patch(f"/api/staff/{u['id']}", json={"permissions": ["presets", "orders"]},
                          headers=self._auth(self.owner))
        me = self.client.get("/api/auth/me", headers=h).json()
        self.assertEqual(sorted(me["permissions"]), ["orders", "presets"])

    def test_me_owner_gets_all_areas(self):
        me = self.client.get("/api/auth/me", headers=self._auth(self.owner)).json()
        self.assertEqual(me["role"], "owner")
        self.assertEqual(tuple(me["permissions"]), STAFF_PERMISSIONS)

    def test_permission_catalog_endpoint(self):
        r = self.client.get("/api/staff/permissions", headers=self._auth(self.owner))
        self.assertEqual(r.status_code, 200)
        keys = [p["key"] for p in r.json()]
        self.assertEqual(tuple(keys), STAFF_PERMISSIONS)
        self.assertTrue(all(p["label"] for p in r.json()))

    # ---- owner unaffected ----
    def test_owner_still_has_everything(self):
        h = self._auth(self.owner)
        for path in ("/api/orders", "/api/models", "/api/catalog", "/api/presets",
                     "/api/automations", "/api/integrations", "/api/staff", "/api/setup/status"):
            self.assertEqual(self.client.get(path, headers=h).status_code, 200, path)


if __name__ == "__main__":
    unittest.main()
