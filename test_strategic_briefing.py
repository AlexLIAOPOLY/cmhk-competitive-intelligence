import time
import unittest
from datetime import datetime
from unittest import mock

import strategic_briefing as briefing


class StrategicBriefingTests(unittest.TestCase):
    def test_empty_semantic_dedupe_reports_zero_history_shards(self):
        result = briefing.agent_semantic_deduplicate_candidates(
            [],
            [{"news_id": "old", "title": "历史新闻"}],
        )

        self.assertEqual(result["kept"], [])
        self.assertEqual(result["history_count"], 1)
        self.assertEqual(result["history_shards"], 0)

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
        self.assertIn("泛香港5G基站", briefing._CATEGORY_CLASSIFICATION_GUIDANCE)

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

    def test_editor_defers_incomplete_ai_batch_instead_of_returning_empty_success(self):
        item = {
            "module": "竞争对手",
            "category": "竞对动态",
            "title": "KDDI与Globe合作改造零售门店",
            "snippet": "KDDI and Globe announced a retail store partnership.",
            "keywords": ["KDDI"],
            "source": "Example News",
            "url": "https://example.com/news/kddi-globe",
        }
        writes = []
        with (
            mock.patch.object(briefing, "_read_json", return_value={"items": {}}),
            mock.patch.object(
                briefing,
                "_atomic_write_json",
                side_effect=lambda path, payload: writes.append((path, payload)),
            ),
            mock.patch.object(
                briefing,
                "_call_internal_ai",
                side_effect=RuntimeError("rate limited"),
            ),
        ):
            with self.assertRaisesRegex(RuntimeError, "本轮禁止写表"):
                briefing.polish_candidates_before_review([item])

        audit = next(
            payload
            for path, payload in writes
            if path == briefing.AI_EDITOR_AUDIT_PATH
        )
        self.assertEqual(audit["input_count"], 1)
        self.assertEqual(audit["resolved_count"], 0)
        self.assertEqual(audit["deferred_count"], 1)

    def test_editor_retries_ai_that_denies_configured_competitor_scope(self):
        item = {
            "module": "竞争对手",
            "category": "竞对动态",
            "title": "Globe partners with Japan's KDDI to reinvent retail stores",
            "snippet": "Globe Telecom is partnering with KDDI on physical retail.",
            "keywords": ["KDDI"],
            "source": "Example News",
            "url": "https://example.com/news/kddi-globe",
        }
        wrong = {
            "title": "Globe与日本KDDI合作重塑零售门店",
            "summary": "Globe与日本KDDI达成合作，共同优化实体零售门店体验。",
            "should_include": False,
            "region": "国际/行业",
            "category": "行业动态",
            "keywords": "KDDI",
            "inclusion_reason": "KDDI不是目标竞对，因此不纳入监控。",
            "region_reason": "事件发生在菲律宾与日本市场。",
        }
        corrected = {
            **wrong,
            "should_include": True,
            "category": "竞对动态",
            "inclusion_reason": "KDDI是正式监控的国际对标运营商，合作事项属于竞对动态。",
        }
        with (
            mock.patch.object(
                briefing,
                "_read_json",
                return_value={
                    "items": {briefing._candidate_editor_key(item): wrong}
                },
            ),
            mock.patch.object(briefing, "_atomic_write_json"),
            mock.patch.object(
                briefing,
                "_call_internal_ai",
                return_value=corrected,
            ) as ai_call,
        ):
            result = briefing.polish_candidates_before_review([item])

        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["ai_category"], "竞对动态")
        self.assertTrue(ai_call.called)
        self.assertTrue(
            ai_call.call_args.args[1].find("monitoring_scope_confirmed") >= 0
        )

    def test_semantic_agent_deduplicates_same_event_with_different_headline(self):
        item = {
            "news_id": "candidate-1",
            "ai_title": "Verizon第二季度业绩超出预期",
            "ai_summary": "Verizon公布第二季度财报，收入与用户表现超过市场预期。",
            "source_date": "2026-07-25",
            "source": "媒体甲",
            "url": "https://example.com/verizon-results-cn",
        }
        history = [
            {
                "news_id": "history-1",
                "title": "Verizon Q2 results beat expectations",
                "summary": "The carrier reported its second-quarter revenue and subscriber results.",
                "source_date": "2026-07-25",
                "source": "媒体乙",
                "source_url": "https://example.com/verizon-results-en",
            }
        ]
        with (
            mock.patch.object(
                briefing,
                "_call_internal_ai",
                return_value={
                    "items": [
                        {
                            "id": "candidate-1",
                            "is_duplicate": True,
                            "duplicate_of": "history-1",
                            "reason": "两条记录均描述Verizon同一份第二季度财报及同一组业绩结果。",
                        }
                    ]
                },
            ),
            mock.patch.object(briefing, "_atomic_write_json"),
        ):
            result = briefing.agent_semantic_deduplicate_candidates([item], history)

        self.assertEqual(result["kept"], [])
        self.assertEqual(len(result["duplicates"]), 1)
        self.assertEqual(result["duplicates"][0]["duplicate_of"], "history-1")

    def test_semantic_agent_independently_confirms_same_batch_events(self):
        first = {
            "news_id": "candidate-a",
            "ai_title": "Verizon门店连续第14年举办免费背包活动",
            "ai_summary": "Verizon授权门店在返校季向家庭免费派发背包。",
            "source_date": "2026-07-26",
            "source": "媒体甲",
            "url": "https://example.com/verizon-backpack-a",
        }
        second = {
            "news_id": "candidate-b",
            "ai_title": "Verizon TCC举办返校季背包赠送活动",
            "ai_summary": "Verizon门店举办School Rocks活动并向学生免费赠送背包。",
            "source_date": "2026-07-26",
            "source": "媒体乙",
            "url": "https://example.com/verizon-backpack-b",
        }
        responses = [
            {
                "items": [
                    {
                        "id": "candidate-a",
                        "is_duplicate": False,
                        "duplicate_of": "",
                        "reason": "当前历史中没有相同活动记录。",
                    },
                    {
                        "id": "candidate-b",
                        "is_duplicate": False,
                        "duplicate_of": "",
                        "reason": "批量初审暂未确认与其他记录重复。",
                    },
                ]
            },
            {
                "items": [
                    {
                        "id": "candidate-a",
                        "is_duplicate": False,
                        "duplicate_of": "",
                        "reason": "独立复核未发现更早的相同活动。",
                    }
                ]
            },
            {
                "items": [
                    {
                        "id": "candidate-b",
                        "is_duplicate": True,
                        "duplicate_of": "candidate-a",
                        "reason": "两条记录均为Verizon返校季免费背包派发活动。",
                    }
                ]
            },
        ]
        with (
            mock.patch.object(
                briefing,
                "_call_internal_ai",
                side_effect=responses,
            ),
            mock.patch.object(briefing, "_atomic_write_json"),
        ):
            result = briefing.agent_semantic_deduplicate_candidates(
                [first, second],
                [],
            )

        self.assertEqual(result["kept"], [first])
        self.assertEqual(len(result["duplicates"]), 1)
        self.assertEqual(result["duplicates"][0]["duplicate_of"], "candidate-a")

    def test_semantic_dedupe_uses_high_confidence_competitor_event_signature(self):
        item = {
            "news_id": "candidate-erie",
            "ai_title": "Verizon门店参与Erie社区返校季背包赠送活动",
            "ai_summary": "Verizon门店参与School Rocks活动并向学生免费赠送书包。",
            "source_date": "2026-07-27",
            "source": "媒体甲",
            "url": "https://example.com/verizon-erie",
        }
        history = [
            {
                "news_id": "history-backpack",
                "title": "Verizon门店举办返校季背包赠送活动",
                "summary": "Verizon门店向家庭免费派发背包。",
                "source_date": "2026-07-25",
                "source": "媒体乙",
                "source_url": "https://example.com/verizon-backpack",
            }
        ]
        with (
            mock.patch.object(briefing, "_call_internal_ai") as ai_call,
            mock.patch.object(briefing, "_atomic_write_json"),
        ):
            result = briefing.agent_semantic_deduplicate_candidates([item], history)

        self.assertEqual(result["kept"], [])
        self.assertEqual(len(result["duplicates"]), 1)
        self.assertEqual(
            result["duplicates"][0]["duplicate_of"],
            "history-backpack",
        )
        ai_call.assert_not_called()

    def test_semantic_priority_history_surfaces_exact_url_before_similar_topics(self):
        candidate = {
            "id": "candidate",
            "title": "Verizon门店举办返校季活动",
            "summary": "Verizon门店向家庭赠送背包。",
            "published_at": "2026-07-25",
            "url": "https://example.com/verizon-backpack?utm_source=rss",
        }
        history = [
            {
                "id": "same-topic",
                "title": "Verizon开展暑期客户活动",
                "summary": "Verizon在多个城市举办客户活动。",
                "published_at": "2026-07-25",
                "url": "https://example.com/verizon-summer",
            },
            {
                "id": "same-url",
                "title": "Local Verizon stores host backpack giveaways",
                "summary": "Stores give backpacks to families for back-to-school.",
                "published_at": "2026-07-25",
                "url": "https://example.com/verizon-backpack",
            },
        ]

        ranked = briefing._semantic_priority_history(candidate, history)

        self.assertEqual(ranked[0]["id"], "same-url")

    def test_semantic_agent_keeps_different_events_from_same_competitor(self):
        item = {
            "news_id": "candidate-2",
            "ai_title": "Verizon在纽约扩建5G网络",
            "ai_summary": "Verizon宣布在纽约新增5G基站并扩大网络覆盖。",
            "source_date": "2026-07-26",
            "source": "媒体甲",
            "url": "https://example.com/verizon-5g",
        }
        history = [
            {
                "news_id": "history-2",
                "title": "Verizon公布第二季度财报",
                "summary": "Verizon披露收入、利润和用户数据。",
                "source_date": "2026-07-25",
                "source": "媒体乙",
                "source_url": "https://example.com/verizon-results",
            }
        ]
        with (
            mock.patch.object(
                briefing,
                "_call_internal_ai",
                return_value={
                    "items": [
                        {
                            "id": "candidate-2",
                            "is_duplicate": False,
                            "duplicate_of": "",
                            "reason": "两条新闻虽涉及同一公司，但分别是网络扩建和财报披露两个不同事件。",
                        }
                    ]
                },
            ),
            mock.patch.object(briefing, "_atomic_write_json"),
        ):
            result = briefing.agent_semantic_deduplicate_candidates([item], history)

        self.assertEqual(result["kept"], [item])
        self.assertEqual(result["duplicates"], [])

    def test_semantic_agent_failure_defers_candidate_instead_of_bypassing(self):
        item = {
            "news_id": "candidate-3",
            "ai_title": "香港宽频推出企业服务",
            "ai_summary": "香港宽频公布新的企业连接服务及客户安排。",
            "source_date": "2026-07-26",
            "source": "媒体甲",
            "url": "https://example.com/hkbn-enterprise",
        }
        with (
            mock.patch.object(
                briefing,
                "_call_internal_ai",
                side_effect=RuntimeError("Agent unavailable"),
            ),
            mock.patch.object(briefing, "_atomic_write_json"),
        ):
            result = briefing.agent_semantic_deduplicate_candidates([item], [])

        self.assertEqual(result["kept"], [])
        self.assertEqual(result["duplicates"], [])
        self.assertEqual(len(result["deferred"]), 1)

    def test_semantic_agent_cannot_deny_same_id_or_url_identity_match(self):
        item = {
            "news_id": "same-id",
            "ai_title": "Verizon门店举办返校季活动",
            "ai_summary": "Verizon门店向家庭赠送背包。",
            "source_date": "2026-07-25",
            "source": "媒体甲",
            "url": "https://example.com/verizon-backpack",
        }
        history = [
            {
                "news_id": "same-id",
                "title": "Local Verizon stores host backpack giveaways",
                "summary": "Stores give backpacks to families.",
                "source_date": "2026-07-25",
                "source": "媒体乙",
                "source_url": "https://example.com/verizon-backpack",
            }
        ]
        with (
            mock.patch.object(
                briefing,
                "_call_internal_ai",
            ) as ai_call,
            mock.patch.object(briefing, "_atomic_write_json"),
        ):
            result = briefing.agent_semantic_deduplicate_candidates([item], history)

        self.assertEqual(result["kept"], [])
        self.assertEqual(len(result["duplicates"]), 1)
        self.assertEqual(result["duplicates"][0]["duplicate_of"], "same-id")
        self.assertEqual(result["deferred"], [])
        ai_call.assert_not_called()

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

    def test_editor_tells_agent_to_distinguish_hong_kong_csl_from_csl_limited(self):
        item = {
            "module": "竞争对手",
            "category": "竞对动态",
            "title": "CSL profit expected to remain flat in FY27",
            "snippet": "A broker maintained its rating on the Australian company.",
            "keywords": ["csl"],
            "source": "Market News",
            "url": "https://example.com/news/csl-rating",
        }
        ai_result = {
            "items": [
                {
                    "id": briefing._candidate_editor_key(item)[:16],
                    "title": "CSL预计FY27利润持平",
                    "summary": "券商预计澳洲CSL公司FY27利润持平，并维持其股票评级。",
                    "should_include": False,
                    "region": "国际/行业",
                    "category": "行业动态",
                    "keywords": "csl",
                    "inclusion_reason": "主体是澳洲生物科技公司CSL Limited，并非香港csl电讯品牌。",
                    "region_reason": "事件主体为澳洲公司。",
                }
            ]
        }
        with (
            mock.patch.object(briefing, "_read_json", return_value={"items": {}}),
            mock.patch.object(briefing, "_atomic_write_json"),
            mock.patch.object(
                briefing,
                "_call_internal_ai",
                return_value=ai_result,
            ) as ai_call,
        ):
            result = briefing.polish_candidates_before_review([item])

        self.assertEqual(result, [])
        self.assertIn("澳洲生物科技公司CSL Limited", ai_call.call_args.args[0])

    def test_editor_prompt_declares_verified_international_operator_as_monitored_competitor(self):
        item = {
            "module": "竞争对手",
            "category": "竞对动态",
            "title": "Globe partners with Japan's KDDI to reinvent retail stores",
            "snippet": "Globe Telecom is partnering with KDDI on physical retail.",
            "keywords": ["KDDI"],
            "source": "Example News",
            "url": "https://example.com/news/kddi-globe",
        }
        ai_result = {
            "items": [
                {
                    "id": briefing._candidate_editor_key(item)[:16],
                    "title": "Globe与KDDI合作改造零售门店",
                    "summary": "Globe与日本运营商KDDI合作优化实体零售体验并探索业务增长机会。",
                    "should_include": True,
                    "region": "国际/行业",
                    "category": "竞对动态",
                    "keywords": "KDDI",
                    "inclusion_reason": "反映被监测国际运营商KDDI的渠道合作动态。",
                    "region_reason": "事件主体为菲律宾与日本运营商。",
                }
            ]
        }
        with (
            mock.patch.object(briefing, "_read_json", return_value={"items": {}}),
            mock.patch.object(briefing, "_atomic_write_json"),
            mock.patch.object(
                briefing,
                "_call_internal_ai",
                return_value=ai_result,
            ) as ai_call,
        ):
            result = briefing.polish_candidates_before_review([item])

        self.assertEqual(len(result), 1)
        prompt = ai_call.call_args.args[0]
        self.assertIn("该运营商就是被监测竞对", prompt)
        self.assertIn("KDDI、AT&T、Verizon", prompt)

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
