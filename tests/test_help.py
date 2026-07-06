import os
import tempfile
import unittest

from cryptography.fernet import Fernet

os.environ.setdefault("MGS_SECRET_KEY", Fernet.generate_key().decode())

from fastapi.testclient import TestClient  # noqa: E402

from api.app import create_app  # noqa: E402
from api.db import dispose_engine  # noqa: E402


class HelpTest(unittest.TestCase):
    def setUp(self):
        os.environ["MGS_ADMIN_PASSWORD"] = "owner-pass"
        self._tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self._tmp.close()
        # Real auth flow — no overrides — so role filtering is exercised.
        self.client = TestClient(create_app(db_url=f"sqlite:///{self._tmp.name}"))

    def tearDown(self):
        dispose_engine()  # Windows: release the SQLite file lock before unlink
        os.unlink(self._tmp.name)

    def _login(self, u, p):
        return self.client.post("/api/auth/login", json={"username": u, "password": p}).json()["token"]

    def _auth(self, token):
        return {"Authorization": f"Bearer {token}"}

    def test_owner_help_includes_owner_sections(self):
        token = self._login("admin", "owner-pass")
        r = self.client.get("/api/help/overview", headers=self._auth(token))
        self.assertEqual(r.status_code, 200)
        data = r.json()
        self.assertEqual(data["role"], "owner")
        ids = {s["id"] for s in data["sections"]}
        # Owner should see pricing, presets, staff management, stripe.
        for required in ("prices", "presets", "staff", "stripe", "today", "loop"):
            self.assertIn(required, ids)

    def test_staff_help_hides_owner_sections(self):
        owner = self._login("admin", "owner-pass")
        self.client.post("/api/staff", json={"username": "jo", "password": "pw"}, headers=self._auth(owner))
        token = self._login("jo", "pw")
        r = self.client.get("/api/help/overview", headers=self._auth(token))
        data = r.json()
        self.assertEqual(data["role"], "staff")
        ids = {s["id"] for s in data["sections"]}
        # Staff get the Today / scope sections.
        for required in ("today", "next_week", "staff_scope", "loop"):
            self.assertIn(required, ids)
        # Staff must NOT see owner-only sections.
        for forbidden in ("prices", "presets", "staff", "stripe", "go_live", "email", "copacker", "inventory"):
            self.assertNotIn(forbidden, ids)

    def test_status_snippets_are_present(self):
        token = self._login("admin", "owner-pass")
        data = self.client.get("/api/help/overview", headers=self._auth(token)).json()
        # A few sections should carry a live status badge.
        with_status = [s for s in data["sections"] if "status" in s]
        self.assertGreaterEqual(len(with_status), 3)
        # Help text is deliberately explanatory — it talks ABOUT prices/Stripe/payments
        # in plain English. Operational-data leak protection lives in test_roles
        # against /work/board, not here.

    def test_unauthenticated_blocked(self):
        self.assertEqual(self.client.get("/api/help/overview").status_code, 401)


if __name__ == "__main__":
    unittest.main()
