import os
import tempfile
import unittest

import httpx
from cryptography.fernet import Fernet

os.environ.setdefault("MGS_SECRET_KEY", Fernet.generate_key().decode())

from api import billing  # noqa: E402
from api.db import dispose_engine, get_session, init_db  # noqa: E402
from api.models_db import Order  # noqa: E402
from api.stripe_client import STRIPE_BASE, StripeClient  # noqa: E402


def make_stripe_mock(counter):
    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        counter[path] = counter.get(path, 0) + 1
        if path == "/v1/customers":
            return httpx.Response(200, json={"id": "cus_test"})
        if path == "/v1/invoiceitems":
            return httpx.Response(200, json={"id": "ii_test"})
        if path == "/v1/invoices":
            return httpx.Response(200, json={"id": "in_test", "status": "draft", "hosted_invoice_url": "https://stripe/inv/x"})
        if path.endswith("/finalize"):
            return httpx.Response(200, json={"id": "in_test", "status": "open"})
        if path.endswith("/send"):
            return httpx.Response(200, json={"id": "in_test", "status": "open", "hosted_invoice_url": "https://stripe/inv/x"})
        return httpx.Response(404, json={})
    return StripeClient(http_client=httpx.Client(base_url=STRIPE_BASE, transport=httpx.MockTransport(handler)))


class BillingTest(unittest.TestCase):
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
        order = Order(
            customer_name="Green Acres",
            customer_email="a@b.com",
            status="confirmed",
            model_id="barn_6_5",
            shape="straight",
            runs=[20],
            bom=[{"sku_id": "base_kit", "name": "Barn Base", "quantity": 1}],
            quote_lines=[
                {"sku_id": "base_kit", "name": "Barn Base", "quantity": 1, "unit_price_usd": 1699, "verified_price": True, "extended_usd": 1699},
                {"sku_id": "extension_module", "name": "Ext", "quantity": 4, "unit_price_usd": 350, "verified_price": True, "extended_usd": 1400},
            ],
            pricing={"verified_subtotal_usd": 3099, "quote_complete": complete},
            contact={"email": "a@b.com"},
            external_refs={},
        )
        self.db.add(order)
        self.db.commit()
        return order

    def test_creates_draft_invoice_with_one_item_per_priced_line(self):
        counter = {}
        client = make_stripe_mock(counter)
        order = self._order()
        refs = billing.create_invoice_for_order(self.db, order, send=False, stripe_client=client)
        self.assertEqual(refs["stripe_invoice_id"], "in_test")
        self.assertEqual(refs["stripe_invoice_status"], "draft")
        self.assertEqual(counter["/v1/customers"], 1)
        self.assertEqual(counter["/v1/invoiceitems"], 2)  # one per priced line
        self.assertEqual(counter["/v1/invoices"], 1)
        self.assertNotIn("/v1/invoices/in_test/send", counter)  # draft, not sent

    def test_send_finalizes_and_sends(self):
        counter = {}
        client = make_stripe_mock(counter)
        order = self._order()
        refs = billing.create_invoice_for_order(self.db, order, send=True, stripe_client=client)
        self.assertEqual(refs["stripe_invoice_status"], "open")
        self.assertEqual(counter["/v1/invoices/in_test/finalize"], 1)
        self.assertEqual(counter["/v1/invoices/in_test/send"], 1)

    def test_idempotent_when_already_invoiced(self):
        counter = {}
        client = make_stripe_mock(counter)
        order = self._order()
        billing.create_invoice_for_order(self.db, order, stripe_client=client)
        first_count = dict(counter)
        # second call should short-circuit and not hit Stripe again
        billing.create_invoice_for_order(self.db, order, stripe_client=make_stripe_mock(counter))
        self.assertEqual(counter["/v1/customers"], first_count["/v1/customers"])

    def test_refuses_incomplete_quote(self):
        client = make_stripe_mock({})
        order = self._order(complete=False)
        with self.assertRaises(billing.BillingError):
            billing.create_invoice_for_order(self.db, order, stripe_client=client)

    def test_no_stripe_integration_raises(self):
        order = self._order()
        # No stripe_client injected and no Integration row -> clear BillingError.
        with self.assertRaises(billing.BillingError):
            billing.create_invoice_for_order(self.db, order)


if __name__ == "__main__":
    unittest.main()
