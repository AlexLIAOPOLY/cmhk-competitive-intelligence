import unittest

from chart_renderer import _format_value_label, _visible_bar_label_indexes


class ChartLabelLayoutTests(unittest.TestCase):
    def test_dense_grouped_bars_use_spaced_label_groups(self) -> None:
        self.assertEqual(_visible_bar_label_indexes(10, 3), {0, 3, 6, 9})

    def test_dense_value_labels_are_compact_and_do_not_repeat_axis_unit(self) -> None:
        self.assertEqual(_format_value_label(708421, compact=True), "708k")
        self.assertEqual(_format_value_label(1040800, compact=True), "1.04M")


if __name__ == "__main__":
    unittest.main()
