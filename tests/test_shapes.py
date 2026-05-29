import unittest

from greenhouse import shape_options
from greenhouse.models import SHAPE_INFO, SHAPE_RUN_COUNTS, build_layout


class ShapeMetadataTest(unittest.TestCase):
    def test_run_counts_derived_from_shape_info(self):
        self.assertEqual(
            SHAPE_RUN_COUNTS, {name: info["runs"] for name, info in SHAPE_INFO.items()}
        )

    def test_shape_options_have_friendly_labels(self):
        opts = {o["name"]: o for o in shape_options()}
        self.assertEqual(opts["L"]["label"], "L-shape")
        self.assertEqual(opts["T"]["label"], "T-shape")
        self.assertEqual(opts["straight"]["label"], "Straight")

    def test_arm_labels_match_run_count(self):
        for o in shape_options():
            self.assertEqual(
                len(o["arm_labels"]), o["runs"],
                f"{o['name']} has {len(o['arm_labels'])} arm labels for {o['runs']} runs",
            )

    def test_every_shape_still_builds(self):
        # Each advertised shape must build with the advertised number of runs.
        for o in shape_options():
            layout = build_layout(o["name"], [8] * o["runs"])
            self.assertEqual(layout.shape, o["name"])


if __name__ == "__main__":
    unittest.main()
