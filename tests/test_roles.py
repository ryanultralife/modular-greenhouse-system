import os
import tempfile
import unittest

from cryptography.fernet import Fernet

os.environ.setdefault("MGS_SECRET_KEY", Fernet.generate_key().decode())

from fastapi.testclient import TestClient  # noqa: E402

from api.app import create_app  # noqa: E402


class RolesWorkBoardTest(unittest.TestCase):
    def setUp(self):
        os.environ["MGS_ADMIN_PASSWORD"] = "owner-pass-123"
        self._tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self._tmp.close()
        # Real auth flow — no dependency overrides.
        self.client = TestClient(create_app(db_url=f"sqlite:///{self._tmp.name}"))

    def tearDown(self):
        os.unlink(self._tmp.name)

    def _login(self, username, password):
        r = self.client.post("/api/auth/login", json={"username": username, "password": password})
        return r

    def _auth(self, token):
        return {"Authorization": f"Bearer {token}"}

    def test_owner_login_role(self):
        r = self._login("admin", "owner-pass-123")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["role"], "owner")

    def test_owner_creates_staff_and_staff_logs_in(self):
        owner = self._login("admin", "owner-pass-123").json()["token"]
        r = self.client.post("/api/staff", json={"username": "jo", "password": "pw123"}, headers=self._auth(owner))
        self.assertEqual(r.status_code, 201)
        self.assertEqual(r.json()["role"], "staff")

        r = self._login("jo", "pw123")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["role"], "staff")

    def test_staff_cannot_manage_staff_or_see_secrets(self):
        owner = self._login("admin", "owner-pass-123").json()["token"]
        self.client.post("/api/staff", json={"username": "jo", "password": "pw123"}, headers=self._auth(owner))
        staff = self._login("jo", "pw123").json()["token"]
        h = self._auth(staff)
        # Owner-only routers must be forbidden for staff.
        self.assertEqual(self.client.get("/api/orders", headers=h).status_code, 403)
        self.assertEqual(self.client.get("/api/integrations", headers=h).status_code, 403)
        self.assertEqual(self.client.get("/api/catalog", headers=h).status_code, 403)
        self.assertEqual(self.client.get("/api/staff", headers=h).status_code, 403)
        self.assertEqual(self.client.get("/api/setup/status", headers=h).status_code, 403)

    def test_staff_can_use_work_board_and_inventory(self):
        owner = self._login("admin", "owner-pass-123").json()["token"]
        self.client.post("/api/staff", json={"username": "jo", "password": "pw123"}, headers=self._auth(owner))
        staff = self._login("jo", "pw123").json()["token"]
        h = self._auth(staff)
        self.assertEqual(self.client.get("/api/work/board", headers=h).status_code, 200)
        self.assertEqual(self.client.get("/api/inventory", headers=h).status_code, 200)
        self.assertEqual(self.client.get("/api/shipping/queue", headers=h).status_code, 200)

    def test_work_board_is_money_free(self):
        owner = self._login("admin", "owner-pass-123").json()["token"]
        # An owner creates a confirmed order via the owner API.
        oid = self.client.post("/api/orders", json={"model": "barn_6_5", "shape": "straight", "runs": [20]},
                               headers=self._auth(owner)).json()["id"]
        self.client.patch(f"/api/orders/{oid}", json={"status": "confirmed"}, headers=self._auth(owner))

        self.client.post("/api/staff", json={"username": "jo", "password": "pw123"}, headers=self._auth(owner))
        staff = self._login("jo", "pw123").json()["token"]
        board = self.client.get("/api/work/board", headers=self._auth(staff)).json()
        self.assertEqual(board["fabricate"]["count"], 1)
        # No financial fields leak to staff.
        blob = str(board)
        for banned in ("price", "subtotal", "stripe", "pricing", "external_refs"):
            self.assertNotIn(banned, blob.lower())

    def test_staff_start_build(self):
        owner = self._login("admin", "owner-pass-123").json()["token"]
        oid = self.client.post("/api/orders", json={"model": "barn_6_5", "shape": "straight", "runs": [8]},
                               headers=self._auth(owner)).json()["id"]
        self.client.patch(f"/api/orders/{oid}", json={"status": "confirmed"}, headers=self._auth(owner))
        self.client.post("/api/staff", json={"username": "jo", "password": "pw123"}, headers=self._auth(owner))
        staff = self._login("jo", "pw123").json()["token"]
        r = self.client.post(f"/api/work/orders/{oid}/start", headers=self._auth(staff))
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["status"], "in_production")

    def test_unauthenticated_blocked(self):
        self.assertEqual(self.client.get("/api/work/board").status_code, 401)
        self.assertEqual(self.client.get("/api/orders").status_code, 401)

    def test_duplicate_and_reserved_usernames(self):
        owner = self._login("admin", "owner-pass-123").json()["token"]
        h = self._auth(owner)
        self.assertEqual(self.client.post("/api/staff", json={"username": "admin", "password": "x"}, headers=h).status_code, 400)
        self.client.post("/api/staff", json={"username": "jo", "password": "pw"}, headers=h)
        self.assertEqual(self.client.post("/api/staff", json={"username": "jo", "password": "pw"}, headers=h).status_code, 409)


if __name__ == "__main__":
    unittest.main()
