import time
import unittest
from datetime import datetime
from unittest import mock

import strategic_briefing as briefing


class StrategicBriefingTests(unittest.TestCase):
    def _approved_brief(self) -> dict:
        return {
            "id": "NEWS-TEST",
            "title": "English source headline",
            "summary": "Source summary for an approved item.",
            "category": "竞对动态",
            "source_url": "https://example.com/news",
            "published_at": "2026-07-16T09:00:00+08:00",
            "approval_message_id": "message-1",
        }

    def test_polish_approved_brief_requires_chinese_editor_output(self):
        with mock.patch.object(
            briefing,
            "_call_internal_ai",
            return_value={
                "title": "竞对推出新一代企业网络方案",
                "summary": "该公司发布新的企业网络方案，重点关注产品能力变化及其对香港市场竞争格局的影响。",
            },
        ) as call:
            result = briefing._polish_approved_brief(self._approved_brief())
        self.assertRegex(result["title"], r"[\u4e00-\u9fff]")
        self.assertLessEqual(len(result["summary"]), 96)
        self.assertTrue(result["ai_polished_at"])
        self.assertEqual(call.call_args.kwargs["max_tokens"], 2400)

    def test_polish_approved_brief_rejects_english_title(self):
        with mock.patch.object(
            briefing,
            "_call_internal_ai",
            return_value={
                "title": "English source headline",
                "summary": "这是一段符合长度要求但标题仍未中文化的中文摘要内容。",
            },
        ):
            with self.assertRaisesRegex(RuntimeError, "中文快讯标题"):
                briefing._polish_approved_brief(self._approved_brief())

    def test_ai_editor_failure_keeps_approved_item_pending(self):
        message = {
            "message_id": "message-1",
            "create_time": str(int(time.time() * 1000)),
            "msg_type": "text",
        }
        state = {}
        with (
            mock.patch.object(briefing, "_list_group_messages", return_value=([message], "bot")),
            mock.patch.object(briefing, "_message_text", return_value="确认发布 SB20260716M-01"),
            mock.patch.object(briefing, "_load_published", return_value=[]),
            mock.patch.object(briefing, "_load_candidates", return_value=[]),
            mock.patch.object(briefing, "_classify_approval", return_value=self._approved_brief()),
            mock.patch.object(briefing, "_polish_approved_brief", side_effect=RuntimeError("AI暂不可用")),
            mock.patch.object(briefing, "_save_published") as save,
        ):
            result = briefing._sync_group(datetime.now(briefing.HKT), state)
        self.assertEqual(result["published"], 0)
        self.assertEqual(len(state["pending_briefs"]), 1)
        self.assertIn("AI暂不可用", state["last_group_error"])
        save.assert_not_called()

    def test_ai_editor_success_publishes_pending_item(self):
        approved = self._approved_brief()
        polished = {
            **approved,
            "title": "竞对推出新一代企业网络方案",
            "summary": "该公司发布新的企业网络方案，重点关注产品能力变化及其对香港市场竞争格局的影响。",
            "ai_polished_at": "2026-07-16T12:00:00+08:00",
        }
        state = {"pending_briefs": [approved]}
        with (
            mock.patch.object(briefing, "_list_group_messages", return_value=([], "bot")),
            mock.patch.object(briefing, "_load_published", return_value=[]),
            mock.patch.object(briefing, "_load_candidates", return_value=[]),
            mock.patch.object(briefing, "_polish_approved_brief", return_value=polished),
            mock.patch.object(briefing, "_save_published") as save,
        ):
            result = briefing._sync_group(datetime.now(briefing.HKT), state)
        self.assertEqual(result["published"], 1)
        self.assertEqual(state["pending_briefs"], [])
        self.assertEqual(state["last_group_error"], "")
        save.assert_called_once()


if __name__ == "__main__":
    unittest.main()
