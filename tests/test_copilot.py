import os
import tempfile
import unittest
from types import SimpleNamespace

from cryptography.fernet import Fernet

os.environ.setdefault("MGS_SECRET_KEY", Fernet.generate_key().decode())

from fastapi.testclient import TestClient  # noqa: E402

from api import automations as auto_mod, security  # noqa: E402
from api.app import create_app  # noqa: E402
from api.automations import _ensure_seeded, run_automations  # noqa: E402
from api.copilot import (  # noqa: E402
    CopilotError,
    build_business_snapshot,
    build_marketing_insights,
    run_copilot,
)
from api.db import get_session, init_db  # noqa: E402
from api.models_db import AuditEvent, Automation, Integration, Order  # noqa: E402


def _text(t):
    return SimpleNamespace(type="text", text=t)


def _tool(name, args, bid="toolu_1"):
    return SimpleNamespace(type="tool_use", name=name, input=args, id=bid)


def _resp(stop, content):
    return SimpleNamespace(stop_reason=stop, content=content)


class FakeAnthropic:
    def __init__(self, responses):
        self._q = list(responses)
        self.requests = []
        self.messages = SimpleNamespace(create=self._create)

    def _create(self, **kw):
        self.requests.append(kw)
        return self._q.pop(0)

    def close(self):
        pass


def _seed_orders(db):
    db.add(Order(customer_name="A", model_id="barn_6_5", shape="straight", runs=[8],
                 status="paid", payment_status="paid", source="website",
                 pricing={"verified_subtotal_usd": 1699, "quote_complete": True},
                 attribution={"utm_source": "facebook"}))
    db.add(Order(customer_name="B", model_id="barn_6_5", shape="L", runs=[16, 12],
                 status="quote", source="website",
                 pricing={"verified_subtotal_usd": 899, "quote_complete": False},
                 attribution={"utm_source": "google"}))
    db.add(Order(customer_name="C", model_id="raised_bed_4x4", shape="straight", runs=[8],
                 status="pending_payment", source="website", pricing={}))
    db.commit()


class CopilotServiceTest(unittest.TestCase):
    def setUp(self):
        os.environ.pop("ANTHROPIC_API_KEY", None)
        self._tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self._tmp.close()
        init_db(f"sqlite:///{self._tmp.name}")
        self.db = get_session()
        self.db.add(Integration(
            provider="anthropic", label="Anthropic",
            secret_blob=security.encrypt_dict({"api_key": "sk-ant-test"}),
            field_names=["api_key"], enabled=True,
        ))
        self.db.commit()
        _seed_orders(self.db)

    def tearDown(self):
        self.db.close()
        os.unlink(self._tmp.name)

    def test_snapshot_reflects_live_data(self):
        snap = build_business_snapshot(self.db)
        self.assertEqual(snap["orders_by_status"]["paid"], 1)
        self.assertEqual(snap["orders_by_status"]["quote"], 1)
        self.assertEqual(snap["verified_revenue_usd_all_active_orders"], 1699)
        self.assertEqual(snap["website_leads_last_7_days"], 3)

    def test_marketing_insights_group_by_source(self):
        m = build_marketing_insights(self.db)
        self.assertEqual(m["website_leads_by_source"]["facebook"], 1)
        self.assertEqual(m["website_leads_by_source"]["google"], 1)
        self.assertEqual(m["converting_leads_by_source"].get("facebook"), 1)
        self.assertNotIn("google", m["converting_leads_by_source"])
        self.assertEqual(m["abandoned_checkouts_open"], 1)

    def test_tool_loop_answers_from_live_data(self):
        fake = FakeAnthropic([
            _resp("tool_use", [_tool("get_business_snapshot", {})]),
            _resp("end_turn", [_text("You have 1 paid order worth $1,699.")]),
        ])
        out = run_copilot(self.db, [{"role": "user", "content": "how are sales?"}],
                          username="admin", client=fake)
        self.assertIn("1,699", out["reply"])
        tool_result = fake.requests[1]["messages"][-1]["content"][0]
        self.assertIn('"paid": 1', tool_result["content"])
        # Exchange logged with attributed actor.
        events = self.db.query(AuditEvent).filter(AuditEvent.kind == "copilot.exchange").all()
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].actor, "agent:copilot(admin)")

    def test_no_key_raises_503(self):
        self.db.query(Integration).delete()
        self.db.commit()
        with self.assertRaises(CopilotError) as ctx:
            run_copilot(self.db, [{"role": "user", "content": "hi"}], client=FakeAnthropic([]))
        self.assertEqual(ctx.exception.status, 503)

    def test_tool_error_surfaces_as_is_error(self):
        fake = FakeAnthropic([
            _resp("tool_use", [_tool("list_recent_orders", {"limit": "not-a-number"})]),
            _resp("end_turn", [_text("Let me try again.")]),
        ])
        run_copilot(self.db, [{"role": "user", "content": "orders"}], client=fake)
        tool_result = fake.requests[1]["messages"][-1]["content"][0]
        self.assertTrue(tool_result.get("is_error"))


class CopilotAccessTest(unittest.TestCase):
    def setUp(self):
        os.environ["MGS_ADMIN_PASSWORD"] = "owner-pass"
        os.environ.pop("ANTHROPIC_API_KEY", None)
        self._tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self._tmp.close()
        self.client = TestClient(create_app(db_url=f"sqlite:///{self._tmp.name}"))

    def tearDown(self):
        os.unlink(self._tmp.name)

    def _login(self, u, p):
        return self.client.post("/api/auth/login", json={"username": u, "password": p}).json()["token"]

    def test_owner_only(self):
        owner = self._login("admin", "owner-pass")
        self.client.post("/api/staff", json={"username": "jo", "password": "pw"},
                         headers={"Authorization": f"Bearer {owner}"})
        staff = self._login("jo", "pw")
        body = {"messages": [{"role": "user", "content": "hi"}]}
        self.assertEqual(self.client.post("/api/copilot", json=body).status_code, 401)
        self.assertEqual(self.client.post("/api/copilot", json=body,
                         headers={"Authorization": f"Bearer {staff}"}).status_code, 403)
        # Owner reaches the service (503 = no key configured, past authz).
        r = self.client.post("/api/copilot", json=body, headers={"Authorization": f"Bearer {owner}"})
        self.assertEqual(r.status_code, 503)


class AiDigestTest(unittest.TestCase):
    def setUp(self):
        os.environ.pop("ANTHROPIC_API_KEY", None)
        self._tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self._tmp.close()
        init_db(f"sqlite:///{self._tmp.name}")
        self.db = get_session()
        _seed_orders(self.db)
        _ensure_seeded(self.db)
        a = self.db.get(Automation, "ai_digest")
        a.enabled = True
        a.config = {"recipient": "josh@example.com", "send_after_hour_utc": 0}
        self.db.commit()
        self.sent = []
        self._orig = auto_mod.send_email

        def fake_send(db, to, subject, html, text=None, sender=None, from_email=None):
            self.sent.append({"to": to, "subject": subject, "html": html})
            return True
        auto_mod.send_email = fake_send

    def tearDown(self):
        auto_mod.send_email = self._orig
        self.db.close()
        os.unlink(self._tmp.name)

    def test_plain_digest_without_ai_key_and_daily_idempotency(self):
        results = run_automations(self.db, only_kind="ai_digest")
        self.assertEqual(results[0]["ok"], True)
        self.assertIn("plain", results[0]["message"])
        self.assertEqual(len(self.sent), 1)
        self.assertEqual(self.sent[0]["to"], "josh@example.com")
        self.assertIn("Verified revenue", self.sent[0]["html"])
        self.assertIn("facebook", self.sent[0]["html"])
        # Second run the same day: no second email.
        results = run_automations(self.db, only_kind="ai_digest")
        self.assertIn("already sent", results[0]["message"])
        self.assertEqual(len(self.sent), 1)

    def test_hour_gate_defers(self):
        a = self.db.get(Automation, "ai_digest")
        a.config = {"recipient": "josh@example.com", "send_after_hour_utc": 24}
        self.db.commit()
        results = run_automations(self.db, only_kind="ai_digest")
        self.assertIn("waiting until", results[0]["message"])
        self.assertEqual(len(self.sent), 0)

    def test_no_recipient_is_noop(self):
        a = self.db.get(Automation, "ai_digest")
        a.config = {"recipient": ""}
        self.db.commit()
        results = run_automations(self.db, only_kind="ai_digest")
        self.assertIn("no recipient", results[0]["message"])
        self.assertEqual(len(self.sent), 0)

    def test_ai_mode_used_when_key_present(self):
        self.db.add(Integration(
            provider="anthropic", label="Anthropic",
            secret_blob=security.encrypt_dict({"api_key": "sk-ant-test"}),
            field_names=["api_key"], enabled=True,
        ))
        self.db.commit()
        orig = auto_mod._ai_digest_text
        auto_mod._ai_digest_text = lambda db, s, m: "<p>AI digest body</p>"
        try:
            results = run_automations(self.db, only_kind="ai_digest")
            self.assertIn("sent (ai)", results[0]["message"])
            self.assertIn("AI digest body", self.sent[0]["html"])
        finally:
            auto_mod._ai_digest_text = orig


if __name__ == "__main__":
    unittest.main()
