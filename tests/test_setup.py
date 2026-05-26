import os
import tempfile
import unittest

from cryptography.fernet import Fernet

os.environ.setdefault("MGS_SECRET_KEY", Fernet.generate_key().decode())

from fastapi.testclient import TestClient  # noqa: E402

from api.app import create_app  # noqa: E402


class SetupStatusTest(unittest.TestCase):
    def setUp(self):
        from api.auth import require_admin

        self._tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self._tmp.close()
        app = create_app(db_url=f"sqlite:///{self._tmp.name}")
        app.dependency_overrides[require_admin] = lambda: "admin"
        self.client = TestClient(app)

    def tearDown(self):
        os.unlink(self._tmp.name)

    def _checks(self):
        return {c["id"]: c for c in self.client.get("/api/setup/status").json()["checks"]}

    def test_fresh_install_not_ready(self):
        body = self.client.get("/api/setup/status").json()
        self.assertFalse(body["ready"])
        checks = {c["id"]: c for c in body["checks"]}
        self.assertFalse(checks["stripe_key"]["ok"])
        self.assertFalse(checks["stripe_webhook"]["ok"])
        self.assertFalse(checks["presets_buyable"]["ok"])

    def test_becomes_ready_after_required_steps(self):
        self.client.post("/api/integrations", json={
            "provider": "stripe",
            "credentials": {"secret_key": "sk_test_x", "webhook_secret": "whsec_x"},
        })
        pid = self.client.post("/api/presets", json={
            "name": "Barn Ready", "price_usd": 1499, "verified_price": True,
        }).json()["id"]
        self.client.post(f"/api/inventory/preset:{pid}/adjust", json={"delta": 2})

        body = self.client.get("/api/setup/status").json()
        checks = {c["id"]: c for c in body["checks"]}
        self.assertTrue(checks["stripe_key"]["ok"])
        self.assertTrue(checks["stripe_webhook"]["ok"])
        self.assertTrue(checks["presets_buyable"]["ok"])
        self.assertTrue(body["ready"])  # all required satisfied


if __name__ == "__main__":
    unittest.main()
