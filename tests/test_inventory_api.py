import os
import tempfile
import unittest

from cryptography.fernet import Fernet

os.environ.setdefault("MGS_SECRET_KEY", Fernet.generate_key().decode())

from fastapi.testclient import TestClient  # noqa: E402

from api.app import create_app  # noqa: E402


class InventoryPresetApiTest(unittest.TestCase):
    def setUp(self):
        from api.auth import require_admin

        self._tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self._tmp.close()
        app = create_app(db_url=f"sqlite:///{self._tmp.name}")
        app.dependency_overrides[require_admin] = lambda: "admin"
        self.client = TestClient(app)

    def tearDown(self):
        os.unlink(self._tmp.name)

    def test_inventory_crud_and_adjust(self):
        r = self.client.put("/api/inventory", json={
            "kind": "material", "key": "frame_tube", "name": "Frame tubing",
            "on_hand": 100, "unit": "ft", "reorder_point": 20,
        })
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["on_hand"], 100)

        r = self.client.post("/api/inventory/frame_tube/adjust", json={"delta": -85})
        self.assertEqual(r.json()["on_hand"], 15)
        self.assertTrue(r.json()["low"])  # 15 <= reorder 20

        self.assertEqual(len(self.client.get("/api/inventory/low-stock").json()), 1)

    def test_material_needs_incomplete_with_placeholder_bom(self):
        # Create + confirm an order; the seed material_bom has null quantities.
        oid = self.client.post("/api/orders", json={"model": "barn_6_5", "shape": "straight", "runs": [20]}).json()["id"]
        self.client.patch(f"/api/orders/{oid}", json={"status": "confirmed"})
        r = self.client.get("/api/production/material-needs?status=confirmed")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["order_count"], 1)
        self.assertFalse(r.json()["complete"])  # placeholder quantities

    def test_preset_lifecycle_and_public_listing(self):
        # Create a priced preset; it should not be buyable until stocked.
        r = self.client.post("/api/presets", json={
            "name": "Barn 6x8 Ready-to-Ship", "model_id": "barn_6_5", "shape": "straight",
            "runs": [8], "price_usd": 1499, "verified_price": True, "ship_speed": "next_day",
        })
        self.assertEqual(r.status_code, 201)
        pid = r.json()["id"]

        pub = self.client.get("/api/public/presets").json()["presets"]
        preset = next(p for p in pub if p["id"] == pid)
        self.assertFalse(preset["buyable"])  # no stock yet
        self.assertEqual(preset["price_usd"], 1499)

        # Stock it.
        self.client.post(f"/api/inventory/preset:{pid}/adjust", json={"delta": 3})
        pub = self.client.get("/api/public/presets").json()["presets"]
        preset = next(p for p in pub if p["id"] == pid)
        self.assertTrue(preset["buyable"])

    def test_public_checkout_without_stripe_returns_400(self):
        pid = self.client.post("/api/presets", json={
            "name": "X", "price_usd": 1000, "verified_price": True,
        }).json()["id"]
        self.client.post(f"/api/inventory/preset:{pid}/adjust", json={"delta": 1})
        r = self.client.post("/api/public/checkout", json={"preset_id": pid, "email": "a@b.com"})
        self.assertEqual(r.status_code, 400)
        self.assertIn("Stripe", r.json()["detail"])

    def test_copacker_config_and_manual_order(self):
        self.client.put("/api/copacker/config", json={"name": "Acme", "email": "acme@x.com"})
        self.assertEqual(self.client.get("/api/copacker/config").json()["name"], "Acme")
        r = self.client.post("/api/copacker/orders", json={
            "copacker": "Acme", "items": [{"key": "preset:1", "name": "Barn", "quantity": 2}],
        })
        self.assertEqual(r.status_code, 201)
        self.assertEqual(len(self.client.get("/api/copacker/orders").json()), 1)


if __name__ == "__main__":
    unittest.main()
