import os
import tempfile
import unittest

import httpx
from cryptography.fernet import Fernet

os.environ.setdefault("MGS_SECRET_KEY", Fernet.generate_key().decode())

from api import quickbooks_sync  # noqa: E402
from api.db import dispose_engine, get_session, init_db  # noqa: E402
from api.models_db import Order  # noqa: E402
from api.quickbooks_client import ENV_BASE, QuickBooksClient  # noqa: E402


def make_qbo_mock(counter):
    def handler(request: httpx.Request) -> httpx.Response:
        host, path = request.url.host, request.url.path
        counter[path] = counter.get(path, 0) + 1
        if host == "oauth.platform.intuit.com":
            return httpx.Response(200, json={"access_token": "at", "refresh_token": "rt2"})
        if path.endswith("/query"):
            q = request.url.params.get("query", "")
            if "from Item" in q:
                return httpx.Response(200, json={"QueryResponse": {"Item": [{"Id": "7"}]}})
            return httpx.Response(200, json={"QueryResponse": {}})  # customer not found
        if path.endswith("/customer"):
            return httpx.Response(200, json={"Customer": {"Id": "C1"}})
        if path.endswith("/invoice"):
            return httpx.Response(200, json={"Invoice": {"Id": "INV1", "DocNumber": "1001"}})
        return httpx.Response(404, json={})
    client = QuickBooksClient(
        client_id="id", client_secret="sec", refresh_token="rt", realm_id="R1",
        http_client=httpx.Client(base_url=ENV_BASE["production"], transport=httpx.MockTransport(handler)),
    )
    return client


class QuickBooksSyncTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self._tmp.close()
        init_db(f"sqlite:///{self._tmp.name}")
        self.db = get_session()

    def tearDown(self):
        self.db.close()
        dispose_engine()  # Windows: release the SQLite file lock before unlink
        os.unlink(self._tmp.name)

    def _order(self, complete=True):
        o = Order(
            customer_name="Green Acres", customer_email="a@b.com", status="confirmed",
            model_id="barn_6_5", shape="straight", runs=[20],
            bom=[{"sku_id": "base_kit", "name": "Barn Base", "quantity": 1}],
            quote_lines=[{"sku_id": "base_kit", "name": "Barn Base", "quantity": 1, "unit_price_usd": 1699, "verified_price": True}],
            pricing={"verified_subtotal_usd": 1699, "quote_complete": complete},
            contact={"email": "a@b.com"}, external_refs={},
        )
        self.db.add(o)
        self.db.commit()
        return o

    def test_sync_creates_customer_and_invoice(self):
        counter = {}
        client = make_qbo_mock(counter)
        order = self._order()
        refs = quickbooks_sync.sync_order(self.db, order, client=client)
        self.assertEqual(refs["qbo_invoice_id"], "INV1")
        self.assertEqual(refs["qbo_customer_id"], "C1")
        self.assertEqual(refs["qbo_invoice_doc_number"], "1001")
        # token refreshed once, item looked up, customer created, invoice created
        self.assertEqual(counter["/oauth2/v1/tokens/bearer"], 1)
        self.assertEqual(counter["/v3/company/R1/customer"], 1)
        self.assertEqual(counter["/v3/company/R1/invoice"], 1)

    def test_idempotent(self):
        counter = {}
        order = self._order()
        quickbooks_sync.sync_order(self.db, order, client=make_qbo_mock(counter))
        before = dict(counter)
        quickbooks_sync.sync_order(self.db, order, client=make_qbo_mock(counter))
        self.assertEqual(counter["/v3/company/R1/invoice"], before["/v3/company/R1/invoice"])

    def test_refuses_incomplete_quote(self):
        with self.assertRaises(quickbooks_sync.QuickBooksSyncError):
            quickbooks_sync.sync_order(self.db, self._order(complete=False), client=make_qbo_mock({}))

    def test_no_integration_raises(self):
        with self.assertRaises(quickbooks_sync.QuickBooksSyncError):
            quickbooks_sync.sync_order(self.db, self._order())


if __name__ == "__main__":
    unittest.main()
