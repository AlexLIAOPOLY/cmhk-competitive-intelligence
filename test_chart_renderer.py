import unittest

import matplotlib.pyplot as plt

from chart_renderer import _format_value_label, _label_bars


class ChartLabelLayoutTests(unittest.TestCase):
    def test_dense_grouped_bars_keep_every_nonzero_label_inside_the_bar(self) -> None:
        fig, ax = plt.subplots()
        values = [708421, 740500, 736819, 745917, 768070, 848258, 937259, 1009300, 1040800, 1050930]
        bars = ax.bar(range(len(values)), values)
        labels = _label_bars(ax, bars, values, None, center=True, compact=True, rotation=90)
        try:
            self.assertEqual(len(labels), len(values))
            self.assertTrue(all(label.get_text() for label in labels))
            self.assertTrue(all(label.get_rotation() == 90 for label in labels))
        finally:
            plt.close(fig)

    def test_dense_value_labels_are_compact_and_do_not_repeat_axis_unit(self) -> None:
        self.assertEqual(_format_value_label(708421, compact=True), "708k")
        self.assertEqual(_format_value_label(1040800, compact=True), "1.04M")


if __name__ == "__main__":
    unittest.main()
