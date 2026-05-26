import unittest

from production import build_stock_list


CATALOG = {
    "models": {
        "barn_6_5": {
            "skus": {
                "base_kit": {"name": "Barn Base", "weight_lb": 200, "fulfillment": "in_house"},
                "extension_module": {"name": "Ext", "weight_lb": 60, "fulfillment": "in_house"},
                "auto_vent": {"name": "Vent", "weight_lb": 3, "fulfillment": "copacker", "copacker": "Acme Vents"},
            }
        }
    }
}


def _order(oid, lines):
    return {"id": oid, "model_id": "barn_6_5", "bom": lines}


class PlannerTest(unittest.TestCase):
    def test_aggregates_quantities_across_orders(self):
        orders = [
            _order(1, [{"sku_id": "base_kit", "name": "Barn Base", "quantity": 1},
                       {"sku_id": "extension_module", "name": "Ext", "quantity": 3}]),
            _order(2, [{"sku_id": "base_kit", "name": "Barn Base", "quantity": 1},
                       {"sku_id": "extension_module", "name": "Ext", "quantity": 2}]),
        ]
        stock = build_stock_list(orders, CATALOG)
        by_sku = {l.sku_id: l for l in stock.lines}
        self.assertEqual(by_sku["base_kit"].quantity, 2)
        self.assertEqual(by_sku["extension_module"].quantity, 5)
        self.assertEqual(stock.order_ids, [1, 2])

    def test_weight_rollup(self):
        orders = [_order(1, [{"sku_id": "extension_module", "name": "Ext", "quantity": 4}])]
        stock = build_stock_list(orders, CATALOG)
        self.assertEqual(stock.lines[0].total_weight_lb, 240.0)  # 60 * 4

    def test_unknown_weight_poisons_rollup(self):
        cat = {"models": {"barn_6_5": {"skus": {"x": {"name": "X"}}}}}  # no weight_lb
        orders = [_order(1, [{"sku_id": "x", "name": "X", "quantity": 2}])]
        stock = build_stock_list(orders, cat)
        self.assertIsNone(stock.lines[0].total_weight_lb)

    def test_copacker_split(self):
        orders = [_order(1, [
            {"sku_id": "base_kit", "name": "Barn Base", "quantity": 1},
            {"sku_id": "auto_vent", "name": "Vent", "quantity": 2},
        ])]
        stock = build_stock_list(orders, CATALOG)
        self.assertEqual(len(stock.in_house), 1)
        self.assertEqual(stock.in_house[0].sku_id, "base_kit")
        groups = stock.by_copacker()
        self.assertIn("Acme Vents", groups)
        self.assertEqual(groups["Acme Vents"][0].sku_id, "auto_vent")


if __name__ == "__main__":
    unittest.main()
