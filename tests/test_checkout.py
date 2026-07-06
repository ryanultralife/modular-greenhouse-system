import os
import tempfile
import unittest

from cryptography.fernet import Fernet

os.environ.setdefault("MGS_SECRET_KEY", Fernet.generate_key().decode())

from api import checkout, inventory_store  # noqa: E402
from api.checkout import CheckoutError  # noqa: E402
from api.db import dispose_engine, get_session, init_db  # noqa: E402
from api.models_db import CoPackerOrder, Order, Preset  # noqa: E402


class FakeStripe:
    def create_checkout_session(self, **kw):
        self.kwargs = kw
        return {"id": "cs_test_123", "url": "https://stripe/checkout/cs_test_123"}

    def close(self):
        pass


class CheckoutTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self._tmp.close()
        init_db(f"sqlite:///{self._tmp.name}")
        self.db = get_session()

    def tearDown(self):
        self.db.close()
        dispose_engine()  # Windows: release the SQLite file lock before unlink
        os.unlink(self._tmp.name)

    def _preset(self, price=1499.0, verified=True, stock=2, copacker="Acme"):
        p = Preset(name="Barn 6x8", model_id="barn_6_5", shape="straight", runs=[8],
                   price_usd=price, verified_price=verified, ship_speed="next_day", active=True)
        self.db.add(p)
        self.db.commit()
        inventory_store.upsert_item(self.db, kind="finished_unit", key=p.stock_key,
                                    name=p.name, on_hand=stock, copacker=copacker)
        return p

    def test_create_checkout_makes_pending_order(self):
        p = self._preset()
        res = checkout.create_checkout_for_preset(
            self.db, p, name="Pat", email="pat@x.com", base_url="https://site", stripe_client=FakeStripe()
        )
        self.assertEqual(res["checkout_url"], "https://stripe/checkout/cs_test_123")
        order = self.db.get(Order, res["order_id"])
        self.assertEqual(order.status, "pending_payment")
        self.assertEqual(order.preset_id, p.id)
        self.assertEqual(order.external_refs["stripe_checkout_session_id"], "cs_test_123")

    def test_unpriced_preset_rejected(self):
        p = self._preset(verified=False)
        with self.assertRaises(CheckoutError):
            checkout.create_checkout_for_preset(self.db, p, name="", email="", base_url="x", stripe_client=FakeStripe())

    def test_out_of_stock_rejected(self):
        p = self._preset(stock=0)
        with self.assertRaises(CheckoutError):
            checkout.create_checkout_for_preset(self.db, p, name="", email="", base_url="x", stripe_client=FakeStripe())

    def test_handle_paid_decrements_stock_and_triggers_copacker(self):
        p = self._preset(stock=2, copacker="Acme Co")
        res = checkout.create_checkout_for_preset(
            self.db, p, name="Pat", email="pat@x.com", base_url="https://site", stripe_client=FakeStripe()
        )
        order = self.db.get(Order, res["order_id"])
        checkout.handle_paid_order(self.db, order)

        self.assertEqual(order.payment_status, "paid")
        self.assertEqual(order.status, "paid")
        self.assertEqual(inventory_store.get_item(self.db, p.stock_key).on_hand, 1)
        cps = self.db.query(CoPackerOrder).all()
        self.assertEqual(len(cps), 1)
        self.assertEqual(cps[0].trigger, "preset_sale")
        self.assertEqual(cps[0].copacker, "Acme Co")
        self.assertEqual(cps[0].related_order_id, order.id)

    def test_handle_paid_is_idempotent(self):
        p = self._preset(stock=2)
        res = checkout.create_checkout_for_preset(
            self.db, p, name="Pat", email="pat@x.com", base_url="https://site", stripe_client=FakeStripe()
        )
        order = self.db.get(Order, res["order_id"])
        checkout.handle_paid_order(self.db, order)
        checkout.handle_paid_order(self.db, order)  # second call no-op
        self.assertEqual(inventory_store.get_item(self.db, p.stock_key).on_hand, 1)
        self.assertEqual(len(self.db.query(CoPackerOrder).all()), 1)


if __name__ == "__main__":
    unittest.main()
