import unittest

from greenhouse import Catalog, assess, configure
from greenhouse.engineering import PRELIMINARY_OK, REQUIRES_SIGNOFF, STANDARD
from greenhouse.models import straight, t_shape


def _catalog_with_verified_limits():
    cat = Catalog.load()
    # Reach into the loaded dict and flip placeholder limits to verified,
    # simulating Josh entering real engineering numbers.
    data = cat._data  # noqa: SLF001 - test introspection
    limits = data["configuration_limits"]
    for key in ("max_straight_run_ft", "max_total_footprint_sqft", "max_junctions"):
        limits[key]["verified"] = True
    return cat


class EngineeringTest(unittest.TestCase):
    def setUp(self):
        self.cat = Catalog.load()

    def test_straight_run_is_standard(self):
        config = configure(self.cat, "barn_6_5", straight(20))
        check = assess(self.cat, config)
        self.assertEqual(check.status, STANDARD)
        self.assertTrue(check.ok_without_signoff)

    def test_nonstandard_requires_signoff_when_limits_unverified(self):
        config = configure(self.cat, "barn_6_5", t_shape(16, 16, 8))
        check = assess(self.cat, config)
        self.assertEqual(check.status, REQUIRES_SIGNOFF)
        self.assertFalse(check.ok_without_signoff)

    def test_preliminary_ok_when_within_verified_limits(self):
        cat = _catalog_with_verified_limits()
        # arms 8+8+8 = 24 ft -> footprint ~154 sqft (<1200), longest run 8 (<40), 1 junction (<=2)
        config = configure(cat, "raised_bed_4x4", t_shape(8, 8, 8))
        check = assess(cat, config)
        self.assertEqual(check.status, PRELIMINARY_OK)
        self.assertTrue(check.ok_without_signoff)

    def test_exceeding_verified_limit_requires_signoff(self):
        cat = _catalog_with_verified_limits()
        # longest run 60 ft exceeds verified 40 ft limit
        config = configure(cat, "barn_6_5", t_shape(60, 8, 8))
        check = assess(cat, config)
        self.assertEqual(check.status, REQUIRES_SIGNOFF)

    def test_disclaimer_always_present(self):
        config = configure(self.cat, "barn_6_5", straight(8))
        check = assess(self.cat, config)
        self.assertIn("not a structural certification", check.disclaimer)


if __name__ == "__main__":
    unittest.main()
