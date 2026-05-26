import unittest

from production import compute_material_needs

CATALOG = {
    "materials": {
        "frame_tube": {"name": "Frame tubing", "unit": "ft"},
        "poly_panel": {"name": "Poly panel", "unit": "each"},
    },
    "material_bom": {
        "base_kit": [{"material": "frame_tube", "qty": 40}, {"material": "poly_panel", "qty": 6}],
        "extension_module": [{"material": "frame_tube", "qty": 20}, {"material": "poly_panel", "qty": None}],
    },
}


class MaterialsTest(unittest.TestCase):
    def test_sums_known_quantities(self):
        orders = [
            {"id": 1, "model_id": "barn_6_5", "bom": [
                {"sku_id": "base_kit", "quantity": 1},
                {"sku_id": "extension_module", "quantity": 3},
            ]},
        ]
        plan = compute_material_needs(orders, CATALOG)
        needs = {n.material_id: n for n in plan.needs}
        self.assertEqual(needs["frame_tube"].quantity, 40 + 20 * 3)  # 100
        self.assertEqual(needs["frame_tube"].unit, "ft")

    def test_placeholder_qty_marks_incomplete(self):
        orders = [{"id": 1, "model_id": "barn_6_5", "bom": [{"sku_id": "extension_module", "quantity": 2}]}]
        plan = compute_material_needs(orders, CATALOG)
        self.assertFalse(plan.complete)
        poly = next(n for n in plan.needs if n.material_id == "poly_panel")
        self.assertFalse(poly.complete)

    def test_empty_orders_complete(self):
        plan = compute_material_needs([], CATALOG)
        self.assertTrue(plan.complete)
        self.assertEqual(plan.needs, [])


if __name__ == "__main__":
    unittest.main()
