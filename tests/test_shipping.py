import os
import tempfile
import unittest

from cryptography.fernet import Fernet

os.environ.setdefault("MGS_SECRET_KEY", Fernet.generate_key().decode())

from fastapi.testclient import TestClient  # noqa: E402

from api.app import create_app  # noqa: E402
from production import build_shipment_plan  # noqa: E402


CATALOG = {
    "models": {
        "barn_6_5": {
            "skus": {
                "base_kit": {"name": "Barn Base", "weight_lb": 200},
                "extension_module": {"name": "Ext", "weight_lb": 60},
                "mystery": {"name": "Mystery"},  # no weight
            }
        }
    }
}


class ShipmentPlanPureTest(unittest.TestCase):
    def test_weight_rollup_complete(self):
        order = {"id": 1, "model_id": "barn_6_5", "bom": [
            {"sku_id": "base_kit", "name": "Barn Base", "quantity": 1},
            {"sku_id": "extension_module", "name": "Ext", "quantity": 4},
        ]}
        plan = build_shipment_plan(order, CATALOG)
        self.assertTrue(plan.ready)
        self.assertEqual(plan.total_weight_lb, 440.0)  # 200 + 60*4
        self.assertEqual(plan.total_units, 5)

    def test_unknown_weight_blocks_readiness(self):
        order = {"id": 2, "model_id": "barn_6_5", "bom": [
            {"sku_id": "base_kit", "name": "Barn Base", "quantity": 1},
            {"sku_id": "mystery", "name": "Mystery", "quantity": 1},
        ]}
        plan = build_shipment_plan(order, CATALOG)
        self.assertFalse(plan.ready)
        self.assertIsNone(plan.total_weight_lb)


class ShippingApiTest(unittest.TestCase):
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

    def _order(self, runs):
        return self.client.post("/api/orders", json={"model": "barn_6_5", "shape": "straight", "runs": runs}).json()["id"]

    def test_shipment_plan_not_ready_with_default_catalog(self):
        # Default catalog has no weights set, so an order is not ship-ready.
        oid = self._order([20])
        r = self.client.get(f"/api/orders/{oid}/shipment-plan")
        self.assertEqual(r.status_code, 200)
        self.assertFalse(r.json()["ready"])

    def test_ship_blocked_when_not_ready(self):
        oid = self._order([20])
        r = self.client.post(f"/api/orders/{oid}/ship", json={"carrier": "UPS"})
        self.assertEqual(r.status_code, 400)

    def test_ship_succeeds_after_weights_set(self):
        from greenhouse.catalog import DEFAULT_CATALOG_PATH

        original = DEFAULT_CATALOG_PATH.read_bytes()
        try:
            # single-bay barn -> only base_kit; give it a weight, then ship.
            self.client.put("/api/catalog/models/barn_6_5/skus/base_kit", json={"weight_lb": 210})
            oid = self._order([4])
            plan = self.client.get(f"/api/orders/{oid}/shipment-plan").json()
            self.assertTrue(plan["ready"])
            self.assertEqual(plan["total_weight_lb"], 210.0)

            r = self.client.post(f"/api/orders/{oid}/ship", json={"carrier": "UPS", "tracking": "1Z999"})
            self.assertEqual(r.status_code, 200)
            body = r.json()
            self.assertEqual(body["status"], "shipped")
            self.assertTrue(body["shipping"]["same_day"])  # shipped same day it was created
            self.assertEqual(body["shipping"]["carrier"], "UPS")
        finally:
            DEFAULT_CATALOG_PATH.write_bytes(original)

    def test_shipping_queue(self):
        oid = self._order([12])
        # Follow the legal lifecycle: quote -> confirmed -> in_production.
        self.client.patch(f"/api/orders/{oid}", json={"status": "confirmed"})
        self.client.patch(f"/api/orders/{oid}", json={"status": "in_production"})
        r = self.client.get("/api/shipping/queue?status=in_production")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["count"], 1)
        self.assertEqual(r.json()["orders"][0]["order_id"], oid)


if __name__ == "__main__":
    unittest.main()
