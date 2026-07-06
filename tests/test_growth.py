import os
import tempfile
import unittest
from datetime import datetime, timedelta, timezone

import httpx
from cryptography.fernet import Fernet

os.environ.setdefault("MGS_SECRET_KEY", Fernet.generate_key().decode())

from api import growth  # noqa: E402
from api.automations import _ensure_seeded, run_automations  # noqa: E402
from api.db import dispose_engine, get_session, init_db  # noqa: E402
from api.models_db import AuditEvent, Automation, Order  # noqa: E402


def _lead(db, *, email="lead@x.com", minutes_old=120, status="quote",
          subtotal=1699, complete=True, signoff=False, name="Pat"):
    order = Order(
        customer_name=name, customer_email=email,
        contact={"email": email}, source="website",
        model_id="barn_6_5", shape="straight", runs=[20], status=status,
        pricing={"verified_subtotal_usd": subtotal, "quote_complete": complete},
        engineering={"requires_signoff": signoff},
    )
    db.add(order)
    db.commit()
    order.created_at = datetime.now(timezone.utc) - timedelta(minutes=minutes_old)
    db.commit()
    return order


class GrowthBase(unittest.TestCase):
    def setUp(self):
        os.environ.pop("ANTHROPIC_API_KEY", None)
        self._tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self._tmp.close()
        init_db(f"sqlite:///{self._tmp.name}")
        self.db = get_session()
        _ensure_seeded(self.db)
        self.sent = []
        self._orig_send = growth.send_email

        def fake_send(db, to, subject, html, text=None, sender=None, from_email=None):
            self.sent.append({"to": to, "subject": subject, "html": html})
            return True
        growth.send_email = fake_send

    def tearDown(self):
        growth.send_email = self._orig_send
        self.db.close()
        dispose_engine()  # Windows: release the SQLite file lock before unlink
        os.unlink(self._tmp.name)

    def _enable(self, kind, **config):
        a = self.db.get(Automation, kind)
        a.enabled = True
        a.config = {**(a.config or {}), **config}
        self.db.commit()


class LeadFollowupTest(GrowthBase):
    def test_sends_personalized_template_and_is_idempotent(self):
        self._enable("lead_followup", delay_minutes=60)
        _lead(self.db, minutes_old=120)
        results = run_automations(self.db, only_kind="lead_followup")
        self.assertTrue(results[0]["ok"])
        self.assertIn("1 followed up (template)", results[0]["message"])
        self.assertEqual(len(self.sent), 1)
        html = self.sent[0]["html"]
        self.assertIn("Pat", html)
        self.assertIn("barn_6_5", html)
        self.assertIn("$1,699.00", html)
        # Second run: no re-send for the same lead.
        run_automations(self.db, only_kind="lead_followup")
        self.assertEqual(len(self.sent), 1)

    def test_respects_delay(self):
        self._enable("lead_followup", delay_minutes=60)
        _lead(self.db, minutes_old=10)  # too fresh
        results = run_automations(self.db, only_kind="lead_followup")
        self.assertIn("0 followed up", results[0]["message"])
        self.assertEqual(len(self.sent), 0)

    def test_incomplete_pricing_and_signoff_are_honest(self):
        self._enable("lead_followup", delay_minutes=0)
        _lead(self.db, complete=False, signoff=True, minutes_old=5)
        run_automations(self.db, only_kind="lead_followup")
        html = self.sent[0]["html"]
        self.assertIn("confirm final pricing", html)
        self.assertIn("engineer will review", html)

    def test_skips_leads_without_email_and_non_quotes(self):
        self._enable("lead_followup", delay_minutes=0)
        _lead(self.db, email="", minutes_old=5)
        _lead(self.db, email="paid@x.com", status="paid", minutes_old=5)
        results = run_automations(self.db, only_kind="lead_followup")
        self.assertIn("0 followed up", results[0]["message"])
        self.assertIn("1 skipped", results[0]["message"])
        self.assertEqual(len(self.sent), 0)

    def test_max_per_run_caps_backlog(self):
        self._enable("lead_followup", delay_minutes=0, max_per_run=2)
        for i in range(4):
            _lead(self.db, email=f"l{i}@x.com", minutes_old=30 + i)
        results = run_automations(self.db, only_kind="lead_followup")
        self.assertIn("2 followed up", results[0]["message"])
        self.assertEqual(len(self.sent), 2)

    def test_ai_mode_when_available(self):
        self._enable("lead_followup", delay_minutes=0)
        _lead(self.db, minutes_old=5)
        orig = growth._ai_followup
        growth._ai_followup = lambda db, ctx: "<p>AI email body</p>"
        try:
            results = run_automations(self.db, only_kind="lead_followup")
            self.assertIn("(ai)", results[0]["message"])
            self.assertIn("AI email body", self.sent[0]["html"])
        finally:
            growth._ai_followup = orig


class SocialPostsTest(GrowthBase):
    def test_neither_configured_is_noop(self):
        self._enable("social_posts")
        results = run_automations(self.db, only_kind="social_posts")
        self.assertIn("no recipient or webhook_url", results[0]["message"])

    def test_email_pack_template_mode(self):
        self._enable("social_posts", recipient="josh@example.com")
        results = run_automations(self.db, only_kind="social_posts")
        self.assertTrue(results[0]["ok"])
        self.assertIn("(template)", results[0]["message"])
        self.assertEqual(len(self.sent), 1)
        html = self.sent[0]["html"]
        self.assertIn("130 mph", html)          # grounded engineering fact
        self.assertIn("4-ft sections", html)    # grounded product fact

    def test_webhook_delivery(self):
        posted = []

        def handler(request: httpx.Request) -> httpx.Response:
            posted.append(request.content.decode())
            return httpx.Response(200, json={"ok": True})

        client = httpx.Client(transport=httpx.MockTransport(handler))
        ok, msg = growth.run_social_posts(
            self.db, {"webhook_url": "https://hook.example/fb", "posts_per_batch": 2},
            http_client=client,
        )
        self.assertTrue(ok)
        self.assertGreaterEqual(len(posted), 1)
        self.assertIn("social_post", posted[0])

    def test_cadence_idempotency(self):
        self._enable("social_posts", recipient="josh@example.com", cadence_days=7)
        run_automations(self.db, only_kind="social_posts")
        self.assertEqual(len(self.sent), 1)
        results = run_automations(self.db, only_kind="social_posts")
        self.assertIn("next batch due", results[0]["message"])
        self.assertEqual(len(self.sent), 1)

    def test_ai_mode_when_available(self):
        self._enable("social_posts", recipient="josh@example.com")
        orig = growth._ai_posts
        growth._ai_posts = lambda db, facts, n: [{"text": "AI post about greenhouses", "image_hint": "greenhouse"}]
        try:
            results = run_automations(self.db, only_kind="social_posts")
            self.assertIn("(ai)", results[0]["message"])
            self.assertIn("AI post about greenhouses", self.sent[0]["html"])
        finally:
            growth._ai_posts = orig

    def test_event_recorded(self):
        self._enable("social_posts", recipient="josh@example.com")
        run_automations(self.db, only_kind="social_posts")
        kinds = [e.kind for e in self.db.query(AuditEvent).all()]
        self.assertIn("marketing.social_posts.sent", kinds)


if __name__ == "__main__":
    unittest.main()
