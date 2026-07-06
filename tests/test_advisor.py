import os
import tempfile
import unittest
from types import SimpleNamespace

from cryptography.fernet import Fernet

os.environ.setdefault("MGS_SECRET_KEY", Fernet.generate_key().decode())

from fastapi.testclient import TestClient  # noqa: E402

from api import advisor as advisor_mod, security  # noqa: E402
from api.advisor import AdvisorError, run_advisor  # noqa: E402
from api.app import create_app  # noqa: E402
from api.db import dispose_engine, get_session, init_db  # noqa: E402
from api.models_db import AuditEvent, Integration, Order  # noqa: E402


def _text_block(text):
    return SimpleNamespace(type="text", text=text)


def _tool_block(name, args, block_id="toolu_1"):
    return SimpleNamespace(type="tool_use", name=name, input=args, id=block_id)


def _response(stop_reason, content):
    return SimpleNamespace(stop_reason=stop_reason, content=content)


class FakeAnthropic:
    """Scripted fake: returns queued responses and records requests."""

    def __init__(self, responses):
        self._queue = list(responses)
        self.requests = []
        self.messages = SimpleNamespace(create=self._create)

    def _create(self, **kwargs):
        self.requests.append(kwargs)
        if not self._queue:
            raise AssertionError("FakeAnthropic queue exhausted")
        return self._queue.pop(0)

    def close(self):
        pass


class AdvisorServiceTest(unittest.TestCase):
    def setUp(self):
        os.environ.pop("ANTHROPIC_API_KEY", None)
        self._tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self._tmp.close()
        init_db(f"sqlite:///{self._tmp.name}")
        self.db = get_session()
        self._add_key()

    def tearDown(self):
        self.db.close()
        dispose_engine()  # Windows: release the SQLite file lock before unlink
        os.unlink(self._tmp.name)

    def _add_key(self):
        self.db.add(Integration(
            provider="anthropic", label="Anthropic",
            secret_blob=security.encrypt_dict({"api_key": "sk-ant-test"}),
            field_names=["api_key"], enabled=True,
        ))
        self.db.commit()

    def test_simple_text_reply(self):
        fake = FakeAnthropic([_response("end_turn", [_text_block("Happy to help!")])])
        out = run_advisor(self.db, [{"role": "user", "content": "hi"}], client=fake)
        self.assertEqual(out["reply"], "Happy to help!")
        self.assertFalse(out["lead_captured"])
        # System prompt is cacheable and static; tools are attached.
        req = fake.requests[0]
        self.assertEqual(req["system"][0]["cache_control"], {"type": "ephemeral"})
        self.assertEqual(req["thinking"], {"type": "adaptive"})
        self.assertTrue(any(t["name"] == "price_configuration" for t in req["tools"]))
        # Exchange recorded in the event log with the advisor actor.
        events = self.db.query(AuditEvent).filter(AuditEvent.kind == "advisor.exchange").all()
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].actor, "agent:advisor")

    def test_tool_loop_prices_with_real_engine(self):
        fake = FakeAnthropic([
            _response("tool_use", [_tool_block("price_configuration",
                      {"model": "barn_6_5", "shape": "straight", "runs": [20]})]),
            _response("end_turn", [_text_block("A 20 ft barn starts at $1,699.")]),
        ])
        out = run_advisor(self.db, [{"role": "user", "content": "price a 20ft barn"}], client=fake)
        self.assertIn("1,699", out["reply"])
        # Second request carries the tool result from the REAL engine.
        followup = fake.requests[1]["messages"]
        tool_result = followup[-1]["content"][0]
        self.assertEqual(tool_result["type"], "tool_result")
        self.assertIn('"verified_subtotal_usd": 1699', tool_result["content"])
        self.assertIn('"engineering_status": "STANDARD"', tool_result["content"])

    def test_tool_error_is_returned_as_is_error(self):
        fake = FakeAnthropic([
            _response("tool_use", [_tool_block("price_configuration",
                      {"model": "nope", "shape": "straight", "runs": [8]})]),
            _response("end_turn", [_text_block("Hmm, let me check that model name.")]),
        ])
        run_advisor(self.db, [{"role": "user", "content": "price it"}], client=fake)
        tool_result = fake.requests[1]["messages"][-1]["content"][0]
        self.assertTrue(tool_result.get("is_error"))

    def test_lead_capture_creates_order_and_event(self):
        fake = FakeAnthropic([
            _response("tool_use", [_tool_block("submit_quote_request", {
                "model": "barn_6_5", "shape": "L", "runs": [16, 12],
                "name": "Pat", "email": "pat@x.com", "notes": "south slope",
            })]),
            _response("end_turn", [_text_block("Sent! The team will follow up.")]),
        ])
        out = run_advisor(
            self.db, [{"role": "user", "content": "yes please submit"}],
            attribution={"utm_source": "chat-test"}, client=fake,
        )
        self.assertTrue(out["lead_captured"])
        order = self.db.query(Order).one()
        self.assertEqual(order.customer_email, "pat@x.com")
        self.assertEqual(order.source, "website")
        self.assertEqual(order.contact.get("via"), "advisor")
        self.assertEqual(order.attribution.get("utm_source"), "chat-test")
        kinds = [e.kind for e in self.db.query(AuditEvent).all()]
        self.assertIn("lead.created", kinds)

    def test_lead_capture_requires_contact(self):
        fake = FakeAnthropic([
            _response("tool_use", [_tool_block("submit_quote_request", {
                "model": "barn_6_5", "shape": "straight", "runs": [8], "name": "NoContact",
            })]),
            _response("end_turn", [_text_block("I still need an email or phone.")]),
        ])
        out = run_advisor(self.db, [{"role": "user", "content": "submit"}], client=fake)
        self.assertFalse(out["lead_captured"])
        self.assertEqual(self.db.query(Order).count(), 0)

    def test_refusal_stop_reason_handled(self):
        fake = FakeAnthropic([_response("refusal", [])])
        out = run_advisor(self.db, [{"role": "user", "content": "something odd"}], client=fake)
        self.assertIn("greenhouses", out["reply"])

    def test_no_key_raises_503(self):
        self.db.query(Integration).delete()
        self.db.commit()
        with self.assertRaises(AdvisorError) as ctx:
            run_advisor(self.db, [{"role": "user", "content": "hi"}], client=FakeAnthropic([]))
        self.assertEqual(ctx.exception.status, 503)

    def test_history_validation(self):
        for bad in ([], [{"role": "system", "content": "x"}], [{"role": "user", "content": ""}],
                    [{"role": "assistant", "content": "hi"}]):
            with self.assertRaises(AdvisorError):
                run_advisor(self.db, bad, client=FakeAnthropic([]))

    def test_per_ip_rate_limit(self):
        original = advisor_mod.PER_IP_DAILY_CAP
        advisor_mod.PER_IP_DAILY_CAP = 2
        try:
            for _ in range(2):
                fake = FakeAnthropic([_response("end_turn", [_text_block("ok")])])
                run_advisor(self.db, [{"role": "user", "content": "hi"}], ip="1.2.3.4", client=fake)
            with self.assertRaises(AdvisorError) as ctx:
                run_advisor(self.db, [{"role": "user", "content": "hi"}], ip="1.2.3.4",
                            client=FakeAnthropic([_response("end_turn", [_text_block("ok")])]))
            self.assertEqual(ctx.exception.status, 429)
            # A different IP is unaffected.
            fake = FakeAnthropic([_response("end_turn", [_text_block("ok")])])
            out = run_advisor(self.db, [{"role": "user", "content": "hi"}], ip="5.6.7.8", client=fake)
            self.assertEqual(out["reply"], "ok")
        finally:
            advisor_mod.PER_IP_DAILY_CAP = original


class AdvisorEndpointTest(unittest.TestCase):
    def setUp(self):
        os.environ.pop("ANTHROPIC_API_KEY", None)
        self._tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self._tmp.close()
        self.client = TestClient(create_app(db_url=f"sqlite:///{self._tmp.name}"))

    def tearDown(self):
        dispose_engine()  # Windows: release the SQLite file lock before unlink
        os.unlink(self._tmp.name)

    def test_endpoint_is_open_but_503_without_key(self):
        r = self.client.post("/api/public/advisor", json={"messages": [{"role": "user", "content": "hi"}]})
        self.assertEqual(r.status_code, 503)
        self.assertIn("advisor", r.json()["detail"].lower())

    def test_endpoint_validates_shape(self):
        r = self.client.post("/api/public/advisor", json={"messages": []})
        self.assertEqual(r.status_code, 422)


if __name__ == "__main__":
    unittest.main()
