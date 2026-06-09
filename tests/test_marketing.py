import os
import tempfile
import unittest

import httpx
from cryptography.fernet import Fernet

os.environ.setdefault("MGS_SECRET_KEY", Fernet.generate_key().decode())

from fastapi.testclient import TestClient  # noqa: E402

from api import automations as auto_mod, inventory_store, security  # noqa: E402
from api.app import create_app  # noqa: E402
from api.auth import require_owner, require_staff  # noqa: E402
from api.automations import _ensure_seeded, run_automations  # noqa: E402
from api.db import get_session, init_db  # noqa: E402
from api.models_db import AuditEvent, Automation, Integration, Order, Preset  # noqa: E402


# ---- fake SMTP sender for the email-driven automations ----
class FakeSender:
    def __init__(self):
        self.sent = []

    def send(self, from_email, to, subject, html, text=None):
        self.sent.append({"to": to, "subject": subject, "html": html})


class AttributionAndEventsTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self._tmp.close()
        app = create_app(db_url=f"sqlite:///{self._tmp.name}")
        owner = {"sub": "admin", "role": "owner"}
        app.dependency_overrides[require_owner] = lambda: owner
        app.dependency_overrides[require_staff] = lambda: owner
        self.client = TestClient(app)

    def tearDown(self):
        os.unlink(self._tmp.name)

    def test_lead_records_event_and_attribution(self):
        r = self.client.post("/api/public/quote-request", json={
            "model": "barn_6_5", "shape": "straight", "runs": [8],
            "name": "Pat", "email": "pat@example.com",
            "attribution": {"utm_source": "facebook", "utm_campaign": "summer", "referrer": "https://example.com",
                            "landing_path": "/", "bogus_key": "should_be_dropped"},
        })
        self.assertEqual(r.status_code, 201)
        oid = r.json()["order_id"]

        order = self.client.get(f"/api/orders/{oid}").json()
        attr = order["attribution"]
        self.assertEqual(attr["utm_source"], "facebook")
        self.assertEqual(attr["utm_campaign"], "summer")
        self.assertNotIn("bogus_key", attr)  # unknown keys filtered out

        events = self.client.get("/api/automations/events").json()
        kinds = [e["kind"] for e in events]
        self.assertIn("lead.created", kinds)

    def test_order_shipped_records_event(self):
        from greenhouse.catalog import DEFAULT_CATALOG_PATH

        original = DEFAULT_CATALOG_PATH.read_bytes()
        try:
            # weight on so the order is ship-ready
            self.client.put("/api/catalog/models/barn_6_5/skus/base_kit", json={"weight_lb": 200})
            oid = self.client.post("/api/orders", json={"model": "barn_6_5", "shape": "straight", "runs": [4]}).json()["id"]
            self.client.patch(f"/api/orders/{oid}", json={"status": "confirmed"})
            self.client.patch(f"/api/orders/{oid}", json={"status": "in_production"})
            self.client.post(f"/api/orders/{oid}/ship", json={"carrier": "UPS"})

            events = self.client.get("/api/automations/events").json()
            self.assertIn("order.shipped", [e["kind"] for e in events])
        finally:
            DEFAULT_CATALOG_PATH.write_bytes(original)


class AutomationRunnerTest(unittest.TestCase):
    SECRET = "whsec_marketing"

    def setUp(self):
        self._tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self._tmp.close()
        init_db(f"sqlite:///{self._tmp.name}")
        self.db = get_session()

    def tearDown(self):
        self.db.close()
        os.unlink(self._tmp.name)

    def _smtp_integration(self):
        self.db.add(Integration(
            provider="smtp", label="smtp",
            secret_blob=security.encrypt_dict({"host": "smtp.example.com", "from_email": "shop@example.com"}),
            field_names=["host", "from_email"], enabled=True,
        ))
        self.db.commit()

    def test_abandoned_checkout_sends_and_is_idempotent(self):
        from datetime import datetime, timedelta, timezone

        self._smtp_integration()
        # Stale pending_payment order with an email.
        old = datetime.now(timezone.utc) - timedelta(hours=24)
        order = Order(
            customer_name="Pat", customer_email="pat@x.com", contact={"email": "pat@x.com"},
            source="website", model_id="barn_6_5", shape="straight", runs=[8],
            status="pending_payment", payment_status="unpaid", preset_id=1,
        )
        self.db.add(order)
        self.db.commit()
        # Backdate created_at past the default grace period (4h).
        order.created_at = old
        self.db.commit()

        _ensure_seeded(self.db)
        a = self.db.get(Automation, "abandoned_checkout")
        a.enabled = True
        self.db.commit()

        fake = FakeSender()
        # automations.py imported send_email at module load, so patch the
        # reference in that module specifically.
        original = auto_mod.send_email

        def patched(db, to, subject, html, text=None, sender=None, from_email=None):
            fake.send(from_email or "shop@example.com", to, subject, html, text)
            return True
        auto_mod.send_email = patched
        try:
            run_automations(self.db, only_kind="abandoned_checkout")
            self.assertEqual(len(fake.sent), 1)
            self.assertEqual(fake.sent[0]["to"], "pat@x.com")
            # Second run: idempotent, no extra send.
            run_automations(self.db, only_kind="abandoned_checkout")
            self.assertEqual(len(fake.sent), 1)
        finally:
            auto_mod.send_email = original

    def test_list_sync_posts_to_webhook(self):
        from api.audit import record_event

        record_event(self.db, "lead.created", entity_type="order", entity_id=42,
                     data={"email": "lead@x.com", "name": "Lead Person"})
        _ensure_seeded(self.db)
        a = self.db.get(Automation, "list_sync")
        a.enabled = True
        a.config = {"webhook_url": "https://hook.example/sync"}
        self.db.commit()

        posted = []

        def handler(request: httpx.Request) -> httpx.Response:
            posted.append({"url": str(request.url), "body": request.content.decode()})
            return httpx.Response(200, json={"ok": True})

        client = httpx.Client(transport=httpx.MockTransport(handler))
        ok, msg = auto_mod._run_list_sync(self.db, dict(a.config), http_client=client)
        self.assertTrue(ok)
        self.assertEqual(len(posted), 1)
        self.assertIn("lead@x.com", posted[0]["body"])
        # Idempotent second run.
        ok2, msg2 = auto_mod._run_list_sync(self.db, dict(a.config), http_client=client)
        self.assertEqual(len(posted), 1)

    def test_disabled_automation_is_skipped(self):
        _ensure_seeded(self.db)  # all disabled by default
        results = run_automations(self.db)
        for r in results:
            self.assertIn(r["message"], ("disabled", "no webhook_url configured"))


class CronEndpointTest(unittest.TestCase):
    def setUp(self):
        os.environ["CRON_SECRET"] = "cron-test-secret"
        self._tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self._tmp.close()
        self.client = TestClient(create_app(db_url=f"sqlite:///{self._tmp.name}"))

    def tearDown(self):
        os.unlink(self._tmp.name)
        os.environ.pop("CRON_SECRET", None)

    def test_cron_requires_correct_bearer(self):
        r = self.client.get("/api/cron/automations")
        self.assertEqual(r.status_code, 401)
        r = self.client.get("/api/cron/automations", headers={"Authorization": "Bearer wrong"})
        self.assertEqual(r.status_code, 401)
        r = self.client.get("/api/cron/automations", headers={"Authorization": "Bearer cron-test-secret"})
        self.assertEqual(r.status_code, 200)
        self.assertIn("results", r.json())

    def test_cron_returns_503_when_secret_not_set(self):
        os.environ.pop("CRON_SECRET", None)
        os.environ.pop("MGS_AUTOMATION_SECRET", None)
        r = self.client.get("/api/cron/automations", headers={"Authorization": "Bearer anything"})
        self.assertEqual(r.status_code, 503)


if __name__ == "__main__":
    unittest.main()
