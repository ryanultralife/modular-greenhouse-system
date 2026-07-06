import hashlib
import hmac
import os
import tempfile
import time
import unittest

from cryptography.fernet import Fernet

os.environ.setdefault("MGS_SECRET_KEY", Fernet.generate_key().decode())

from fastapi.testclient import TestClient  # noqa: E402

from api.app import create_app  # noqa: E402
from api.db import dispose_engine  # noqa: E402
from api.stripe_client import verify_webhook_signature  # noqa: E402


def sign(payload: bytes, secret: str, t: int | None = None) -> str:
    t = t or int(time.time())
    sig = hmac.new(secret.encode(), f"{t}.".encode() + payload, hashlib.sha256).hexdigest()
    return f"t={t},v1={sig}"


class WebhookSignatureTest(unittest.TestCase):
    def test_valid_signature(self):
        payload = b'{"hello":"world"}'
        secret = "whsec_test"
        self.assertTrue(verify_webhook_signature(payload, sign(payload, secret), secret))

    def test_tampered_payload_fails(self):
        secret = "whsec_test"
        header = sign(b'{"a":1}', secret)
        self.assertFalse(verify_webhook_signature(b'{"a":2}', header, secret))

    def test_stale_timestamp_fails(self):
        payload = b"{}"
        secret = "whsec_test"
        old = sign(payload, secret, t=int(time.time()) - 10_000)
        self.assertFalse(verify_webhook_signature(payload, old, secret))

    def test_missing_secret_or_header(self):
        self.assertFalse(verify_webhook_signature(b"{}", "", "whsec"))
        self.assertFalse(verify_webhook_signature(b"{}", "t=1,v1=abc", ""))


class WebhookEndpointTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self._tmp.close()
        self.client = TestClient(create_app(db_url=f"sqlite:///{self._tmp.name}"))

    def tearDown(self):
        dispose_engine()  # Windows: release the SQLite file lock before unlink
        os.unlink(self._tmp.name)

    def test_webhook_without_secret_configured_400(self):
        # No Stripe integration / webhook secret -> refuse (can't verify).
        r = self.client.post("/api/stripe/webhook", content=b"{}", headers={"Stripe-Signature": "t=1,v1=x"})
        self.assertEqual(r.status_code, 400)
        self.assertIn("webhook secret", r.json()["detail"].lower())


class WebhookFulfillmentTest(unittest.TestCase):
    """Validly-signed checkout.session.completed -> fulfillment, and idempotent
    against Stripe's at-least-once duplicate delivery."""

    SECRET = "whsec_fulfilltest"

    def setUp(self):
        import json

        from api import inventory_store, security
        from api.checkout import create_checkout_for_preset
        from api.db import get_session
        from api.models_db import CoPackerOrder, Integration, Preset

        self._json = json
        self._tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self._tmp.close()
        self.client = TestClient(create_app(db_url=f"sqlite:///{self._tmp.name}"))
        self.db = get_session()
        self._inv = inventory_store
        self._CoPackerOrder = CoPackerOrder

        # Configure Stripe with a webhook secret.
        self.db.add(Integration(
            provider="stripe", label="Stripe",
            secret_blob=security.encrypt_dict({"secret_key": "sk_test", "webhook_secret": self.SECRET}),
            field_names=["secret_key", "webhook_secret"], enabled=True,
        ))
        # A priced, stocked preset.
        preset = Preset(name="Barn 6x8", model_id="barn_6_5", shape="straight", runs=[8],
                        price_usd=1499, verified_price=True, active=True)
        self.db.add(preset)
        self.db.commit()
        inventory_store.upsert_item(self.db, kind="finished_unit", key=preset.stock_key, name=preset.name, on_hand=2)

        # Use the service layer (with a fake Stripe) to create a pending order.
        class _FakeStripe:
            def create_checkout_session(self, **kw):
                return {"id": "cs_test", "url": "https://stripe/cs_test"}
            def close(self):
                pass

        res = create_checkout_for_preset(self.db, preset, name="Pat", email="p@x.com",
                                         base_url="https://site", stripe_client=_FakeStripe())
        self.order_id = res["order_id"]
        self.stock_key = preset.stock_key

    def tearDown(self):
        self.db.close()
        dispose_engine()  # Windows: release the SQLite file lock before unlink
        os.unlink(self._tmp.name)

    def _event(self):
        return self._json.dumps({
            "id": "evt_1", "type": "checkout.session.completed",
            "data": {"object": {"id": "cs_test", "metadata": {"order_id": str(self.order_id)}}},
        }).encode()

    def _post(self, payload):
        return self.client.post("/api/stripe/webhook", content=payload,
                                headers={"Stripe-Signature": sign(payload, self.SECRET)})

    def test_valid_webhook_fulfills_and_is_idempotent(self):
        payload = self._event()

        r1 = self._post(payload)
        self.assertEqual(r1.status_code, 200)
        self.db.expire_all()
        from api.models_db import Order
        self.assertEqual(self.db.get(Order, self.order_id).payment_status, "paid")
        self.assertEqual(self._inv.get_item(self.db, self.stock_key).on_hand, 1)  # 2 - 1
        self.assertEqual(len(self.db.query(self._CoPackerOrder).all()), 1)

        # Duplicate delivery (Stripe retries) must not double-fulfill.
        r2 = self._post(payload)
        self.assertEqual(r2.status_code, 200)
        self.db.expire_all()
        self.assertEqual(self._inv.get_item(self.db, self.stock_key).on_hand, 1)  # still 1
        self.assertEqual(len(self.db.query(self._CoPackerOrder).all()), 1)  # still 1

    def test_bad_signature_rejected(self):
        payload = self._event()
        r = self.client.post("/api/stripe/webhook", content=payload,
                             headers={"Stripe-Signature": "t=1,v1=deadbeef"})
        self.assertEqual(r.status_code, 400)


if __name__ == "__main__":
    unittest.main()
