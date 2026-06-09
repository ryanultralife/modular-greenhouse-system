import os
import tempfile
import unittest
from pathlib import Path

from cryptography.fernet import Fernet

os.environ.setdefault("MGS_SECRET_KEY", Fernet.generate_key().decode())

from fastapi.testclient import TestClient  # noqa: E402

from api.app import create_app  # noqa: E402
from api.walkthrough_content import render_markdown  # noqa: E402


class WalkthroughTest(unittest.TestCase):
    def setUp(self):
        os.environ["MGS_ADMIN_PASSWORD"] = "owner-pass"
        self._tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self._tmp.close()
        self.client = TestClient(create_app(db_url=f"sqlite:///{self._tmp.name}"))

    def tearDown(self):
        os.unlink(self._tmp.name)

    def _login(self, u, p):
        return self.client.post("/api/auth/login", json={"username": u, "password": p}).json()["token"]

    def _auth(self, t):
        return {"Authorization": f"Bearer {t}"}

    def test_owner_sees_all_flows(self):
        token = self._login("admin", "owner-pass")
        r = self.client.get("/api/walkthrough", headers=self._auth(token))
        self.assertEqual(r.status_code, 200)
        data = r.json()
        self.assertEqual(data["role"], "owner")
        self.assertIn("architecture", data)
        ids = {f["id"] for f in data["flows"]}
        for required in ("big_picture", "money_path", "marketing_funnel", "why_choices"):
            self.assertIn(required, ids)

    def test_staff_sees_filtered_flows(self):
        owner = self._login("admin", "owner-pass")
        self.client.post("/api/staff", json={"username": "jo", "password": "pw"}, headers=self._auth(owner))
        token = self._login("jo", "pw")
        data = self.client.get("/api/walkthrough", headers=self._auth(token)).json()
        self.assertEqual(data["role"], "staff")
        ids = {f["id"] for f in data["flows"]}
        self.assertIn("daily_ops", ids)            # staff-relevant
        self.assertNotIn("money_path", ids)         # owner-only
        self.assertNotIn("marketing_funnel", ids)   # owner-only

    def test_unauthenticated_blocked(self):
        self.assertEqual(self.client.get("/api/walkthrough").status_code, 401)

    def test_committed_doc_is_in_sync(self):
        # docs/WALKTHROUGH.md must match the generator, so it never drifts from
        # the in-app content. Regenerate with scripts/gen_walkthrough_doc.py.
        doc = Path(__file__).resolve().parents[1] / "docs" / "WALKTHROUGH.md"
        self.assertTrue(doc.exists(), "docs/WALKTHROUGH.md missing — run scripts/gen_walkthrough_doc.py")
        self.assertEqual(
            doc.read_text(), render_markdown(),
            "docs/WALKTHROUGH.md is stale — run python3 scripts/gen_walkthrough_doc.py",
        )


if __name__ == "__main__":
    unittest.main()
