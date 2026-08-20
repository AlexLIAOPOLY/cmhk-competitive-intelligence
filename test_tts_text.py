import unittest

from tts_service import prepare_tts_text


class PrepareTtsTextTests(unittest.TestCase):
    def test_decimal_percentage_is_spoken_in_chinese_order(self):
        self.assertEqual(prepare_tts_text("增长8.3%"), "增长百分之八点三")

    def test_multiple_and_negative_percentages(self):
        self.assertEqual(
            prepare_tts_text("增长8.3%，下降17.6%，变动-4.2%"),
            "增长百分之八点三，下降百分之十七点六，变动百分之负四点二",
        )

    def test_integer_percentage(self):
        self.assertEqual(prepare_tts_text("派息率75%"), "派息率百分之七十五")


if __name__ == "__main__":
    unittest.main()
