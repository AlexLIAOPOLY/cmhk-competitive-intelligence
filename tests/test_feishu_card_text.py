from __future__ import annotations

import unittest

from cmhk.integrations.feishu_card_text import without_markdown_bold_markers


class FeishuCardTextTests(unittest.TestCase):
    def test_removes_plain_and_escaped_bold_markers_from_visible_content(self) -> None:
        original = {
            "schema": "2.0",
            "body": {
                "elements": [
                    {"tag": "markdown", "content": "**订阅内容**\n战略新闻"},
                    {"tag": "markdown", "content": r"\*\*报告形式\*\*：PDF"},
                    {
                        "tag": "button",
                        "text": {"tag": "plain_text", "content": "**确认订阅**"},
                        "behaviors": [{"type": "callback", "value": {"action": "keep**value"}}],
                    },
                ]
            },
        }

        normalized = without_markdown_bold_markers(original)

        self.assertEqual(normalized["body"]["elements"][0]["content"], "订阅内容\n战略新闻")
        self.assertEqual(normalized["body"]["elements"][1]["content"], "报告形式：PDF")
        self.assertEqual(normalized["body"]["elements"][2]["text"]["content"], "确认订阅")
        self.assertEqual(
            normalized["body"]["elements"][2]["behaviors"][0]["value"]["action"],
            "keep**value",
        )
        self.assertEqual(original["body"]["elements"][0]["content"], "**订阅内容**\n战略新闻")


if __name__ == "__main__":
    unittest.main()
