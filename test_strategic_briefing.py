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

    def test_model_authored_copy_is_normalized_to_simplified_chinese(self):
        result = briefing._validated_ai_copy(
            {
                "title": "香港電訊擴展人工智能服務",
                "summary": "香港電訊宣佈擴展人工智能服務，為企業客戶提供新的網絡能力。",
                "should_include": True,
                "region": "香港本地",
                "category": "競對動態",
                "keywords": "人工智能",
                "inclusion_reason": "直接關係香港企業市場的競爭格局變化。",
                "region_reason": "事件主體與受影響市場均在香港。",
            },
            require_review_fields=True,
            allowed_keywords="人工智能",
        )
        self.assertEqual(result["title"], "香港电讯扩展人工智能服务")
        self.assertIn("企业客户", result["summary"])
        self.assertEqual(result["category"], "竞对动态")
        self.assertIn("竞争格局变化", result["inclusion_reason"])

    def test_explicit_taiwan_evidence_overrides_ai_hong_kong_region(self):
        result = briefing._validated_ai_copy(
            {
                "title": "辉达代理AI RTX Spark携手联发科",
                "summary": "辉达代理AI RTX Spark技术与联发科合作，并有4家台厂新品接力上场。",
                "should_include": True,
                "region": "香港本地",
                "category": "行业动态",
                "keywords": "AI",
                "inclusion_reason": "涉及AI技术合作与台厂新品上市，具产业动态价值。",
                "region_reason": "模型错误认为影响香港市场。",
            },
            require_review_fields=True,
            allowed_keywords="AI",
            source_item={
                "source_title": "7/22盘前｜辉达代理AI RTX Spark牵手联发科 4台厂新品接力上场",
                "source_summary": "台股盘前重点新闻。",
                "jurisdiction": "TW",
            },
        )
        self.assertEqual(result["region"], "国际/行业")

    def test_explicit_hong_kong_evidence_keeps_local_region(self):
        self.assertEqual(
            briefing._enforce_region_from_source_evidence(
                "香港本地",
                {"source_title": "台湾企业在香港推出新服务"},
            ),
            "香港本地",
        )

    def test_competitor_category_is_decided_by_ai_without_hard_override(self):
        result = briefing._validated_ai_copy(
            {
                "title": "T-Mobile上调2026年自由现金流预期",
                "summary": "T-Mobile上调全年自由现金流指引，并维持服务收入展望。",
                "should_include": True,
                "region": "国际/行业",
                "category": "行业动态",
                "keywords": "T-Mobile",
                "inclusion_reason": "运营商业绩指引直接反映竞对经营表现。",
                "region_reason": "事件主体和受影响市场均位于美国。",
            },
            require_review_fields=True,
            allowed_keywords="T-Mobile",
            source_item={
                "module": "竞争对手",
                "source_title": "T-Mobile raises 2026 free cash flow outlook",
            },
        )
        self.assertEqual(result["category"], "行业动态")

    def test_candidate_editor_receives_module_and_rule_category(self):
        payload = briefing._candidate_editor_input(
            "1234567890abcdef",
            {
                "module": "竞争对手",
                "category": "竞对动态",
                "title": "T-Mobile raises 2026 free cash flow outlook",
                "snippet": "T-Mobile raised its full-year free cash flow guidance.",
                "keywords": ["T-Mobile"],
            },
        )
        self.assertEqual(payload["monitoring_module"], "竞争对手")
        self.assertEqual(payload["rule_category"], "竞对动态")
        self.assertIn("T-Mobile", payload["matched_keywords"])
        self.assertIn("业绩或现金流指引", briefing._CATEGORY_CLASSIFICATION_GUIDANCE)
        self.assertIn("地域与分类是两个独立维度", briefing._CATEGORY_CLASSIFICATION_GUIDANCE)
        self.assertIn("技术监控词命中", briefing._CATEGORY_CLASSIFICATION_GUIDANCE)

    def test_competitor_candidate_uses_ai_semantic_decision_without_hard_override(self):
        item = {
            "module": "竞争对手",
            "category": "行业动态",
            "title": "T-Mobile推出常规客户服务更新",
            "snippet": "T-Mobile announced a routine customer service update.",
            "keywords": ["T-Mobile"],
            "source": "Example News",
            "url": "https://example.com/news/t-mobile-service",
            "ai_title": "T-Mobile更新客户服务安排",
            "ai_summary": "T-Mobile公布常规客户服务调整，涉及现有用户的服务安排。",
            "ai_should_include": False,
            "ai_region": "国际/行业",
            "ai_category": "行业动态",
            "ai_keywords": "T-Mobile",
            "ai_inclusion_reason": "模型认为事件规模较小，不建议纳入候选池。",
            "ai_region_reason": "事件主体和受影响市场均位于美国。",
        }

        with (
            mock.patch.object(briefing, "_read_json", return_value={"items": {}}),
            mock.patch.object(briefing, "_atomic_write_json"),
            mock.patch.object(briefing, "_call_internal_ai") as ai_call,
        ):
            result = briefing.polish_candidates_before_review([item])

        self.assertEqual(result, [])
        ai_call.assert_not_called()

    def test_batch_editor_failure_immediately_retries_each_item(self):
        item = {
            "module": "竞争对手",
            "category": "竞对动态",
            "title": "HKBN推出企业宽频服务更新",
            "snippet": "HKBN announced an enterprise broadband service update in Hong Kong.",
            "keywords": ["HKBN"],
            "source": "Example News",
            "url": "https://example.com/news/hkbn-broadband",
        }
        single_result = {
            "title": "香港宽频更新企业宽频服务",
            "summary": "香港宽频在香港推出企业宽频服务更新，调整企业客户的网络服务安排。",
            "should_include": True,
            "region": "香港本地",
            "category": "竞对动态",
            "keywords": "HKBN",
            "inclusion_reason": "直接反映香港宽频的企业客户产品与服务变化。",
            "region_reason": "事件主体及受影响市场均在香港。",
        }
        with (
            mock.patch.object(briefing, "_read_json", return_value={"items": {}}),
            mock.patch.object(briefing, "_atomic_write_json"),
            mock.patch.object(
                briefing,
                "_call_internal_ai",
                side_effect=[ValueError("unterminated JSON"), single_result],
            ) as ai_call,
        ):
            result = briefing.polish_candidates_before_review([item])

        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["ai_title"], single_result["title"])
        self.assertEqual(ai_call.call_count, 2)

    def test_candidate_editor_marks_verified_competitor_context(self):
        payload = briefing._candidate_editor_input(
            "1234567890abcdef",
            {
                "module": "竞争对手",
                "title": "HKBN launches a broadband service update",
                "snippet": "HKBN announced the service change in Hong Kong.",
                "keywords": ["HKBN"],
            },
        )
        self.assertTrue(payload["competitor_candidate"])

    def test_ambiguous_competitor_alias_requires_telecom_context(self):
        self.assertFalse(
            briefing._is_competitor_candidate(
                {
                    "module": "竞争对手",
                    "title": "Player returns after injury",
                    "snippet": "CSL reporter interviews the football player.",
                    "keywords": ["csl"],
                }
            )
        )

    def test_approved_brief_prompt_requires_simplified_chinese(self):
        with mock.patch.object(
            briefing,
            "_call_internal_ai",
            return_value={
                "title": "竞对推出新一代企业网络方案",
                "summary": "该公司发布新的企业网络方案，重点关注产品能力变化及市场影响。",
            },
        ) as call:
            briefing._polish_approved_brief(self._approved_brief())
        self.assertIn("简体中文", call.call_args.args[0])

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
