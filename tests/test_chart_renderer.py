import unittest

import matplotlib.pyplot as plt

from cmhk.reporting.charts import CHART_BG, _format_value_label, _label_bars, _wrap_category_label, render_chart


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

    def test_long_dated_category_label_wraps_and_truncates(self) -> None:
        label = _wrap_category_label("2029-03 全部届满 6/7GHz 140MHz")
        self.assertEqual(label.splitlines()[0], "2029-03")
        self.assertLessEqual(len(label.splitlines()), 2)
        self.assertTrue(label.endswith("…"))

    def test_year_only_category_still_keeps_the_date_on_its_own_line(self) -> None:
        label = _wrap_category_label("2029 最早供频 1.4GHz 118.5MHz", width=9)
        self.assertEqual(label.splitlines()[0], "2029")
        self.assertLessEqual(len(label.splitlines()), 2)

    def test_renderer_uses_dark_gray_canvas_for_long_category_chart(self) -> None:
        result = render_chart(
            {
                "type": "bar",
                "title": "香港近期频谱拍卖与重新指配关键节点",
                "unit": "频段/事件",
                "x": [
                    "2024-11 拍卖 6/7GHz 300MHz",
                    "2026-06 重新指配 850/900MHz 20MHz",
                    "2029-03 全部届满 6/7GHz 140MHz",
                ],
                "series": [{"name": "事件", "data": [1, 1, 1]}],
            }
        )
        image = plt.imread(result["path"])
        expected = tuple(int(CHART_BG[index:index + 2], 16) / 255 for index in (1, 3, 5))
        self.assertTrue(all(abs(float(image[0, 0, channel]) - expected[channel]) < 0.02 for channel in range(3)))


if __name__ == "__main__":
    unittest.main()
