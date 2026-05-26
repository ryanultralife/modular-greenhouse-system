import unittest

from greenhouse import Catalog, build_quote, configure
from greenhouse.models import straight


class QuoteTest(unittest.TestCase):
    def setUp(self):
        self.cat = Catalog.load()

    def test_base_kit_price_is_verified(self):
        config = configure(self.cat, "barn_6_5", straight(4))
        quote = build_quote(self.cat, config)
        self.assertEqual(len(quote.lines), 1)
        line = quote.lines[0]
        self.assertEqual(line.unit_price_usd, 1699)
        self.assertTrue(line.verified_price)
        self.assertEqual(quote.verified_subtotal_usd, 1699)
        self.assertTrue(quote.is_complete)

    def test_raised_bed_base_price(self):
        config = configure(self.cat, "raised_bed_4x4", straight(4))
        quote = build_quote(self.cat, config)
        self.assertEqual(quote.verified_subtotal_usd, 899)

    def test_extension_modules_are_tbd(self):
        config = configure(self.cat, "barn_6_5", straight(20))
        quote = build_quote(self.cat, config)
        # base kit verified, extension modules have no verified price yet
        self.assertEqual(quote.verified_subtotal_usd, 1699)
        self.assertFalse(quote.is_complete)
        tbd_skus = {ln.sku_id for ln in quote.tbd_lines}
        self.assertIn("extension_module", tbd_skus)

    def test_extended_price_multiplies_quantity(self):
        config = configure(self.cat, "barn_6_5", straight(4))
        quote = build_quote(self.cat, config)
        self.assertEqual(quote.lines[0].extended_usd, 1699)


if __name__ == "__main__":
    unittest.main()
