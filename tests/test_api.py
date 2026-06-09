import os
import tempfile
import unittest

from cryptography.fernet import Fernet

os.environ.setdefault("MGS_SECRET_KEY", Fernet.generate_key().decode())

from fastapi.testclient import TestClient  # noqa: E402

from api.app import create_app  # noqa: E402


class ApiTest(unittest.TestCase):
    def setUp(self):
        from api.auth import require_owner, require_staff

        self._tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self._tmp.close()
        app = create_app(db_url=f"sqlite:///{self._tmp.name}")
        owner = {"sub": "admin", "role": "owner"}
        app.dependency_overrides[require_owner] = lambda: owner
        app.dependency_overrides[require_staff] = lambda: owner
        self.client = TestClient(app)

    def tearDown(self):
        os.unlink(self._tmp.name)

    def test_models_endpoint(self):
        r = self.client.get("/api/models")
        self.assertEqual(r.status_code, 200)
        ids = [m["id"] for m in r.json()["models"]]
        self.assertIn("barn_6_5", ids)

    def test_quote_endpoint(self):
        r = self.client.post("/api/quote", json={"model": "barn_6_5", "shape": "straight", "runs": [20]})
        self.assertEqual(r.status_code, 200)
        data = r.json()
        self.assertEqual(data["total_bays"], 5)
        self.assertEqual(data["verified_subtotal_usd"], 1699)
        self.assertEqual(data["engineering"]["status"], "STANDARD")

    def test_quote_bad_shape(self):
        r = self.client.post("/api/quote", json={"model": "barn_6_5", "shape": "T", "runs": [8]})
        self.assertEqual(r.status_code, 400)

    def test_order_lifecycle(self):
        r = self.client.post("/api/orders", json={
            "model": "raised_bed_4x4", "shape": "T", "runs": [16, 16, 12],
            "customer_name": "Test Farm",
        })
        self.assertEqual(r.status_code, 201)
        oid = r.json()["id"]
        self.assertTrue(r.json()["engineering"]["requires_signoff"])

        r = self.client.patch(f"/api/orders/{oid}", json={"status": "confirmed"})
        self.assertEqual(r.json()["status"], "confirmed")

        r = self.client.get("/api/orders?status=confirmed")
        self.assertEqual(len(r.json()), 1)

    def test_illegal_status_transition_rejected(self):
        oid = self.client.post("/api/orders", json={"model": "barn_6_5", "shape": "straight", "runs": [8]}).json()["id"]
        self.client.patch(f"/api/orders/{oid}", json={"status": "confirmed"})
        self.client.patch(f"/api/orders/{oid}", json={"status": "in_production"})
        self.client.patch(f"/api/orders/{oid}", json={"status": "shipped"})
        # shipped is terminal: cannot regress to quote.
        r = self.client.patch(f"/api/orders/{oid}", json={"status": "quote"})
        self.assertEqual(r.status_code, 400)
        self.assertIn("Cannot move", r.json()["detail"])

    def test_stock_list_aggregates_confirmed_orders(self):
        for _ in range(2):
            r = self.client.post("/api/orders", json={"model": "barn_6_5", "shape": "straight", "runs": [20]})
            oid = r.json()["id"]
            self.client.patch(f"/api/orders/{oid}", json={"status": "confirmed"})

        r = self.client.get("/api/production/stock-list?status=confirmed")
        self.assertEqual(r.status_code, 200)
        lines = {l["sku_id"]: l for l in r.json()["all_lines"]}
        self.assertEqual(lines["base_kit"]["quantity"], 2)
        self.assertEqual(lines["extension_module"]["quantity"], 8)  # 4 per order * 2

    def test_fab_session_flow(self):
        r = self.client.post("/api/orders", json={"model": "barn_6_5", "shape": "straight", "runs": [12]})
        oid = r.json()["id"]
        r = self.client.post("/api/fab-sessions", json={"week_of": "2026-06-01", "label": "Wk22"})
        sid = r.json()["id"]
        r = self.client.post(f"/api/fab-sessions/{sid}/assign", json={"order_ids": [oid]})
        self.assertEqual(r.json()["order_ids"], [oid])
        r = self.client.get(f"/api/fab-sessions/{sid}/stock-list")
        self.assertEqual(r.json()["order_count"], 1)

    def test_catalog_edit_updates_quote(self):
        from greenhouse.catalog import DEFAULT_CATALOG_PATH

        original = DEFAULT_CATALOG_PATH.read_bytes()
        try:
            # Set a verified price on the barn extension module, then re-quote.
            r = self.client.put("/api/catalog/models/barn_6_5/skus/extension_module",
                                json={"price_usd": 350, "verified_price": True})
            self.assertEqual(r.status_code, 200)
            r = self.client.post("/api/quote", json={"model": "barn_6_5", "shape": "straight", "runs": [20]})
            # base 1699 + 4 * 350 = 3099, and quote now complete
            self.assertEqual(r.json()["verified_subtotal_usd"], 3099)
            self.assertTrue(r.json()["quote_complete"])
        finally:
            # Restore the catalog file byte-for-byte so the repo copy is untouched.
            DEFAULT_CATALOG_PATH.write_bytes(original)

    def test_integration_store_and_mask(self):
        r = self.client.post("/api/integrations", json={
            "provider": "stripe", "credentials": {"secret_key": "sk_test_abcd9999"},
        })
        self.assertEqual(r.status_code, 201)
        masked = r.json()["masked"]
        self.assertEqual(masked["secret_key"], "****9999")  # never returns full secret

        r = self.client.get("/api/integrations")
        self.assertEqual(len(r.json()), 1)

    def test_integration_unknown_provider_rejected(self):
        r = self.client.post("/api/integrations", json={
            "provider": "bogus", "credentials": {"x": "y"},
        })
        self.assertEqual(r.status_code, 400)


if __name__ == "__main__":
    unittest.main()
