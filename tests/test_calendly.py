import os
import tempfile
import unittest

import httpx
from cryptography.fernet import Fernet

os.environ.setdefault("MGS_SECRET_KEY", Fernet.generate_key().decode())

from api import calendly_actions  # noqa: E402
from api.calendly_client import CALENDLY_BASE, CalendlyClient  # noqa: E402
from api.db import get_session, init_db  # noqa: E402
from api.models_db import Order  # noqa: E402


def make_calendly_mock(counter):
    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        counter[path] = counter.get(path, 0) + 1
        if path == "/users/me":
            return httpx.Response(200, json={"resource": {"uri": "https://api.calendly.com/users/U1"}})
        if path == "/event_types":
            return httpx.Response(200, json={"collection": [{"uri": "https://api.calendly.com/event_types/E1"}]})
        if path == "/scheduling_links":
            return httpx.Response(201, json={"resource": {"booking_url": "https://calendly.com/d/abc"}})
        return httpx.Response(404, json={})
    return CalendlyClient(http_client=httpx.Client(base_url=CALENDLY_BASE, transport=httpx.MockTransport(handler)))


class CalendlyActionTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self._tmp.close()
        init_db(f"sqlite:///{self._tmp.name}")
        self.db = get_session()

    def tearDown(self):
        self.db.close()
        os.unlink(self._tmp.name)

    def _order(self, refs=None):
        o = Order(
            customer_name="Jane", status="confirmed", model_id="barn_6_5", shape="straight",
            runs=[8], bom=[], quote_lines=[], pricing={}, contact={"email": "j@x.com"},
            external_refs=refs or {},
        )
        self.db.add(o)
        self.db.commit()
        return o

    def test_creates_link_via_first_event_type(self):
        counter = {}
        url = calendly_actions.create_install_link(self.db, self._order(), client=make_calendly_mock(counter))
        self.assertEqual(url, "https://calendly.com/d/abc")
        self.assertEqual(counter["/users/me"], 1)
        self.assertEqual(counter["/event_types"], 1)
        self.assertEqual(counter["/scheduling_links"], 1)

    def test_uses_provided_event_type_uri(self):
        counter = {}
        url = calendly_actions.create_install_link(
            self.db, self._order(), client=make_calendly_mock(counter),
            event_type_uri="https://api.calendly.com/event_types/E9",
        )
        self.assertEqual(url, "https://calendly.com/d/abc")
        self.assertNotIn("/users/me", counter)  # skipped lookup
        self.assertEqual(counter["/scheduling_links"], 1)

    def test_idempotent_when_already_scheduled(self):
        counter = {}
        order = self._order(refs={"calendly_booking_url": "https://calendly.com/d/existing"})
        url = calendly_actions.create_install_link(self.db, order, client=make_calendly_mock(counter))
        self.assertEqual(url, "https://calendly.com/d/existing")
        self.assertEqual(counter, {})  # no calls made

    def test_no_integration_raises(self):
        with self.assertRaises(calendly_actions.CalendlySchedulingError):
            calendly_actions.create_install_link(self.db, self._order())


if __name__ == "__main__":
    unittest.main()
