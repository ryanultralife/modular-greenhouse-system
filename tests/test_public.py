import os
import tempfile
import unittest

from cryptography.fernet import Fernet

os.environ.setdefault("MGS_SECRET_KEY", Fernet.generate_key().decode())

from fastapi.testclient import TestClient  # noqa: E402

from api.app import create_app  # noqa: E402


class PublicFlowTest(unittest.TestCase):
    def setUp(self):
        from api.auth import require_admin

        self._tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self._tmp.close()
        app = create_app(db_url=f"sqlite:///{self._tmp.name}")
        app.dependency_overrides[require_admin] = lambda: "admin"
        self.client = TestClient(app)

    def tearDown(self):
        os.unlink(self._tmp.name)

    def test_public_models(self):
        r = self.client.get("/api/public/models")
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertIn("models", body)
        self.assertIn("envelope", body)
        self.assertEqual(body["envelope"]["wind_mph"], 130)
        # base price is exposed for verified-priced models
        barn = next(m for m in body["models"] if m["id"] == "barn_6_5")
        self.assertEqual(barn["base_price_usd"], 1699)

    def test_customer_site_served_at_root(self):
        r = self.client.get("/")
        self.assertEqual(r.status_code, 200)
        self.assertIn("Modular", r.text)
        self.assertEqual(self.client.get("/configure.html").status_code, 200)

    def test_admin_app_served_under_admin(self):
        r = self.client.get("/admin/")
        self.assertEqual(r.status_code, 200)
        self.assertIn("Admin", r.text)

    def test_api_still_routes_under_root_mount(self):
        # The catch-all "/" static mount must not shadow the API.
        self.assertEqual(self.client.get("/api/public/models").status_code, 200)
        self.assertEqual(self.client.get("/health").status_code, 200)

    def test_public_quote_is_trimmed(self):
        r = self.client.post("/api/public/quote", json={"model": "barn_6_5", "shape": "straight", "runs": [20]})
        self.assertEqual(r.status_code, 200)
        data = r.json()
        self.assertEqual(data["total_bays"], 5)
        self.assertIn("engineering_status", data)
        self.assertNotIn("quote_lines", data)  # internals not exposed publicly

    def test_quote_request_creates_website_lead(self):
        r = self.client.post("/api/public/quote-request", json={
            "model": "barn_6_5", "shape": "straight", "runs": [16],
            "name": "Jane", "email": "jane@example.com",
        })
        self.assertEqual(r.status_code, 201)
        oid = r.json()["order_id"]

        admin = self.client.get(f"/api/orders/{oid}").json()
        self.assertEqual(admin["source"], "website")
        self.assertEqual(admin["status"], "quote")
        self.assertEqual(admin["contact"]["email"], "jane@example.com")

    def test_quote_request_requires_contact(self):
        r = self.client.post("/api/public/quote-request", json={
            "model": "barn_6_5", "shape": "straight", "runs": [16], "name": "NoContact",
        })
        self.assertEqual(r.status_code, 400)

    def test_invoice_endpoint_without_stripe_returns_400(self):
        # A single-bay barn is base-kit-only, so its quote is complete (verified
        # price). Invoicing should then fail on the missing Stripe integration.
        oid = self.client.post("/api/orders", json={"model": "barn_6_5", "shape": "straight", "runs": [4]}).json()["id"]
        r = self.client.post(f"/api/orders/{oid}/invoice")
        self.assertEqual(r.status_code, 400)
        self.assertIn("Stripe", r.json()["detail"])


if __name__ == "__main__":
    unittest.main()
