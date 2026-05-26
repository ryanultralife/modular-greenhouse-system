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
        os.unlink(self._tmp.name)

    def test_webhook_without_secret_configured_400(self):
        # No Stripe integration / webhook secret -> refuse (can't verify).
        r = self.client.post("/api/stripe/webhook", content=b"{}", headers={"Stripe-Signature": "t=1,v1=x"})
        self.assertEqual(r.status_code, 400)
        self.assertIn("webhook secret", r.json()["detail"].lower())


if __name__ == "__main__":
    unittest.main()
