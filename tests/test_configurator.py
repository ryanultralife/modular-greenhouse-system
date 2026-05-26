import unittest

from greenhouse import Catalog, build_layout, configure, footprint_sqft
from greenhouse.models import l_shape, straight, t_shape, x_shape


class ConfiguratorTest(unittest.TestCase):
    def setUp(self):
        self.cat = Catalog.load()

    def _bom(self, config):
        return {line.sku_id: line.quantity for line in config.bom}

    def test_base_kit_only_for_single_bay(self):
        config = configure(self.cat, "barn_6_5", straight(4))
        bom = self._bom(config)
        self.assertEqual(config.total_bays, 1)
        self.assertEqual(bom, {"base_kit": 1})

    def test_straight_run_extension_modules(self):
        # 20 ft / 4 ft = 5 bays. Base kit covers 1, so 4 extensions.
        config = configure(self.cat, "barn_6_5", straight(20))
        bom = self._bom(config)
        self.assertEqual(config.total_bays, 5)
        self.assertEqual(bom["base_kit"], 1)
        self.assertEqual(bom["extension_module"], 4)
        self.assertNotIn("end_cap", bom)  # 2 open ends covered by base kit
        self.assertNotIn("junction_kit", bom)

    def test_open_ends_by_shape(self):
        self.assertEqual(straight(8).open_ends, 2)
        self.assertEqual(l_shape(8, 8).open_ends, 2)
        self.assertEqual(t_shape(8, 8, 8).open_ends, 3)
        self.assertEqual(x_shape(8, 8, 8, 8).open_ends, 4)

    def test_t_shape_adds_junction_and_extra_end_cap(self):
        config = configure(self.cat, "raised_bed_4x4", t_shape(8, 8, 8))
        bom = self._bom(config)
        # 3 open ends, base covers 2 -> 1 extra end cap; 1 tee junction.
        self.assertEqual(config.open_ends, 3)
        self.assertEqual(bom["junction_kit"], 1)
        self.assertEqual(bom["end_cap"], 1)

    def test_x_shape_extra_end_caps(self):
        config = configure(self.cat, "raised_bed_4x4", x_shape(8, 8, 8, 8))
        bom = self._bom(config)
        self.assertEqual(config.open_ends, 4)
        self.assertEqual(bom["end_cap"], 2)  # 4 open ends - 2 from base
        self.assertEqual(bom["junction_kit"], 1)

    def test_total_bays_sums_all_runs(self):
        # T with arms 16 + 16 + 8 = 40 ft -> 10 bays.
        config = configure(self.cat, "barn_6_5", t_shape(16, 16, 8))
        self.assertEqual(config.total_bays, 10)
        self.assertEqual(self._bom(config)["extension_module"], 9)

    def test_footprint(self):
        config = configure(self.cat, "raised_bed_4x4", straight(20))
        self.assertEqual(footprint_sqft(self.cat, config), 80.0)  # 20 ft x 4 ft

    def test_build_layout_validates_run_count(self):
        with self.assertRaises(ValueError):
            build_layout("T", [8, 8])  # T needs 3 runs

    def test_unknown_model_raises(self):
        from greenhouse import CatalogError

        with self.assertRaises(CatalogError):
            configure(self.cat, "nope", straight(8))


if __name__ == "__main__":
    unittest.main()
