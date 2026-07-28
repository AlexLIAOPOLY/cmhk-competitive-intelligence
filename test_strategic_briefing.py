import time
import unittest
from datetime import datetime
from unittest import mock

import strategic_briefing as briefing


class StrategicBriefingTests(unittest.TestCase):
    def test_public_snapshot_exposes_dated_candidate_activity_for_empty_state_charts(self):
        with (
            mock.patch.object(briefing, "_load_state", return_value={}),
            mock.patch.object(briefing, "_load_published", return_value=[]),
            mock.patch.object(
                briefing,
                "_read_json",
                return_value={
                    "items": [
                        {
                            "title": "运营商发布网络建设计划",
                            "module": "基础设施/网络/技术类",
                            "source_date": "2026-07-28T08:00:00+08:00",
                        },
                        {
                            "title": "没有明确发布日期",
                            "module": "竞争对手",
                            "source_date": "",
                        },
                    ]
                },
            ),
        ):
            snapshot = briefing.public_snapshot()

        self.assertEqual(snapshot["items"], [])
        self.assertEqual(
            snapshot["candidate_items"],
            [
                {
                    "title": "运营商发布网络建设计划",
                    "category": "网络与技术",
                    "published_at": "2026-07-28T08:00:00+08:00",
                }
            ],
        )

    def test_comprehensive_query_plans_cover_every_configured_keyword(self):
        spec = {
            "modules": [
                {
                    "name": "模块甲",
                    "keywords": [f"关键词{index}" for index in range(27)],
                    "source_urls": [],
                },
                {
                    "name": "模块乙",
                    "keywords": [f"战略词{index}" for index in range(18)],
                    "source_urls": [],
                },
            ]
        }
        state = {"query_cursor": 9}

        plans = briefing._query_plans(spec, state, max_queries=None)

        covered = {
            keyword
            for plan in plans
            for keyword in plan["keywords"]
        }
        self.assertEqual(
            covered,
            {
                keyword
                for module in spec["modules"]
                for keyword in module["keywords"]
            },
        )
        self.assertEqual(len(plans), 10)
        self.assertEqual(state["query_cursor"], 0)

    def test_lightweight_query_plans_keep_rotating_limit(self):
        spec = {
            "modules": [
                {
                    "name": "模块",
                    "keywords": [f"关键词{index}" for index in range(30)],
                    "source_urls": [],
                }
            ]
        }
        state = {"query_cursor": 0}

        plans = briefing._query_plans(spec, state, max_queries=4)

        self.assertEqual(len(plans), 4)
        self.assertEqual(state["query_cursor"], 4)

    def test_split_keywords_preserves_commas_inside_parentheses(self):
        self.assertEqual(
            briefing._split_keywords(
                "港元利率（HIBOR 1M/3M），人民币、美元汇率"
            ),
            ["港元利率（HIBOR 1M/3M）", "人民币", "美元汇率"],
        )

    def test_scan_downstream_error_cannot_be_recorded_as_completed(self):
        with self.assertRaisesRegex(RuntimeError, "飞书审核表"):
            briefing._require_scan_downstream_success(
                {"result_count": 29},
                {"error": "'history_shards'"},
            )

        briefing._require_scan_downstream_success(
            {"result_count": 29},
            {"status": "ok", "new_count": 1},
        )

    def test_scan_notification_retries_with_stable_idempotency_key(self):
        response = {
            "data": {"message_id": "om_notification"},
            "_identity": "bot",
        }
        with (
            mock.patch.dict(
                briefing.os.environ,
                {"CMHK_STRATEGIC_GROUP_NOTIFICATIONS": "1"},
            ),
            mock.patch.object(
                briefing,
                "_lark_api",
                side_effect=[RuntimeError("temporary EOF"), response],
            ) as lark_api,
            mock.patch.object(briefing.time, "sleep") as sleep,
        ):
            message_id, identity = briefing._send_scan_message(
                now=datetime(2026, 7, 28, 9, 0, tzinfo=briefing.HKT),
                slot_label="晨间扫描",
                candidates=[],
                spec={"keyword_count": 136, "module_count": 6},
                review_result={
                    "new_count": 16,
                    "new_category_counts": {"竞对动态": 16},
                    "new_region_counts": {"香港本地": 3, "国际/行业": 13},
                    "new_source_count": 14,
                    "source_candidate_count": 26,
                    "sheet_url": "https://example.com/sheet",
                },
                notification_key="2026-07-28@09:00",
            )

        self.assertEqual(message_id, "om_notification")
        self.assertEqual(identity, "bot")
        self.assertEqual(lark_api.call_count, 2)
        first_uuid = lark_api.call_args_list[0].kwargs["data"]["uuid"]
        second_uuid = lark_api.call_args_list[1].kwargs["data"]["uuid"]
        self.assertEqual(first_uuid, second_uuid)
        self.assertRegex(
            first_uuid,
            r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
        )
        sleep.assert_called_once_with(1)

    def test_pending_scan_notification_replays_once_after_resume(self):
        slot_key = "2026-07-28@09:00"
        state = {
            "scan_slots": {slot_key: {"status": "completed", "message_id": ""}},
            "pending_scan_notifications": {
                slot_key: {
                    "now": "2026-07-28T09:00:00+08:00",
                    "slot_label": "晨间扫描",
                    "spec": {"keyword_count": 136, "module_count": 6},
                    "review_result": {"new_count": 16},
                }
            },
        }
        with (
            mock.patch.dict(
                briefing.os.environ,
                {"CMHK_STRATEGIC_GROUP_NOTIFICATIONS": "1"},
            ),
            mock.patch.object(
                briefing,
                "_send_scan_message",
                return_value=("om_replayed", "bot"),
            ) as send,
            mock.patch.object(briefing, "_append_event") as append_event,
        ):
            result = briefing._flush_pending_scan_notifications(
                datetime(2026, 7, 28, 10, 0, tzinfo=briefing.HKT),
                state,
            )

        self.assertEqual(
            result,
            [{"slot": slot_key, "message_id": "om_replayed"}],
        )
        self.assertEqual(state["pending_scan_notifications"], {})
        self.assertEqual(
            state["scan_slots"][slot_key]["message_id"],
            "om_replayed",
        )
        self.assertEqual(state["outbound_message_ids"], ["om_replayed"])
        send.assert_called_once()
        append_event.assert_called_once()

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

    def test_mainland_ministry_evidence_overrides_ai_hong_kong_region(self):
        self.assertEqual(
            briefing._enforce_region_from_source_evidence(
                "香港本地",
                {
                    "source_title": "工业和信息化部发文提升中小企业数字化转型服务供给",
                    "source_summary": "工信部发布政策，支持内地中小企业数字化转型。",
                },
            ),
            "国际/行业",
        )

    def test_competitor_route_requires_competitor_category(self):
        with self.assertRaisesRegex(RuntimeError, "竞对直通必须归为竞对动态"):
            briefing._validated_ai_copy(
                {
                    "title": "T-Mobile上调2026年自由现金流预期",
                    "summary": "T-Mobile上调全年自由现金流指引，并维持服务收入展望。",
                    "should_include": True,
                    "region": "国际/行业",
                    "category": "行业动态",
                    "keywords": "T-Mobile",
                    "inclusion_reason": "上调现金流指引将影响资本配置判断。",
                    "region_reason": "事件主体和受影响市场均位于美国。",
                    "decision_path": "竞对直通",
                    "signal_type": "竞对经营动作",
                    "business_impact": "资本配置",
                    "exclusion_code": "无",
                },
                require_review_fields=True,
                require_decision_fields=True,
                allowed_keywords="T-Mobile",
                source_item={
                    "module": "竞争对手",
                    "source_title": "T-Mobile raises 2026 free cash flow outlook",
                },
            )

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
        self.assertIn(
            "matched_keywords全部来自正式监控配置",
            briefing._STRATEGIC_INCLUSION_GUIDANCE,
        )
        self.assertIn(
            "不得再要求关联某家竞对",
            briefing._STRATEGIC_INCLUSION_GUIDANCE,
        )

    def test_non_competitor_strategic_keyword_signal_is_included(self):
        item = {
            "module": "政策/法规类",
            "category": "政策监管",
            "title": "香港公布数据中心能源使用新规",
            "snippet": "新规将提高数据中心能源披露和合规要求，并影响运营成本。",
            "keywords": ["Data center", "监管"],
            "source": "Government News",
            "url": "https://example.com/news/hk-data-centre-rule",
        }
        ai_result = {
            "items": [
                {
                    "id": briefing._candidate_editor_key(item)[:16],
                    "title": "香港公布数据中心能源使用新规",
                    "summary": "香港提高数据中心能源披露及合规要求，相关运营商将面对新的合规与成本安排。",
                    "should_include": True,
                    "region": "香港本地",
                    "category": "政策监管",
                    "keywords": "Data center、监管",
                    "inclusion_reason": "数据中心能源新规将直接改变基础设施合规要求和运营成本。",
                    "region_reason": "政策由香港发布并影响香港数据中心运营。",
                    "decision_path": "战略信号",
                    "signal_type": "监管政策",
                    "business_impact": "合规与牌照",
                    "exclusion_code": "无",
                }
            ]
        }
        with (
            mock.patch.object(briefing, "_read_json", return_value={"items": {}}),
            mock.patch.object(briefing, "_atomic_write_json"),
            mock.patch.object(briefing, "_call_internal_ai", return_value=ai_result),
        ):
            result = briefing.polish_candidates_before_review([item])

        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["ai_decision_path"], "战略信号")
        self.assertEqual(result[0]["ai_signal_type"], "监管政策")
        self.assertEqual(result[0]["ai_business_impact"], "合规与牌照")

    def test_strategic_signal_requires_concrete_business_impact(self):
        with self.assertRaisesRegex(RuntimeError, "缺少具体业务影响"):
            briefing._validated_ai_copy(
                {
                    "title": "行业发布人工智能发展报告",
                    "summary": "报告梳理人工智能产业趋势，但没有说明对电信业务的具体影响。",
                    "should_include": True,
                    "region": "国际/行业",
                    "category": "行业动态",
                    "keywords": "AI",
                    "inclusion_reason": "报告讨论人工智能发展，因此可能具有战略价值。",
                    "region_reason": "报告讨论全球行业趋势。",
                    "decision_path": "战略信号",
                    "signal_type": "关键技术",
                    "business_impact": "无",
                    "exclusion_code": "无",
                },
                require_review_fields=True,
                require_decision_fields=True,
                allowed_keywords="AI",
            )

    def test_commentary_without_concrete_event_cannot_enter_strategic_route(self):
        with self.assertRaisesRegex(RuntimeError, "观点或评论未包含"):
            briefing._validated_ai_copy(
                {
                    "title": "评论员分析地区战争对市场的影响",
                    "summary": "评论员讨论地区战争可能带来的长期市场风险。",
                    "should_include": True,
                    "region": "国际/行业",
                    "category": "宏观经济",
                    "keywords": "War",
                    "inclusion_reason": "评论涉及战争，因此可能影响运营和供应。",
                    "region_reason": "评论讨论国际地区局势。",
                    "decision_path": "战略信号",
                    "signal_type": "宏观与地缘",
                    "business_impact": "供应韧性",
                    "exclusion_code": "无",
                },
                require_review_fields=True,
                require_decision_fields=True,
                allowed_keywords="War",
                source_item={
                    "source_title": "MSNBC评论员分析特朗普对伊战争150天影响",
                    "source_summary": "节目嘉宾分析战争可能造成的政治和市场影响。",
                },
            )

    def test_generic_trend_without_new_event_cannot_enter_strategic_route(self):
        with self.assertRaisesRegex(RuntimeError, "缺少可验证的新动作"):
            briefing._validated_ai_copy(
                {
                    "title": "中国AI四强追赶美国",
                    "summary": "文章比较中国与美国人工智能企业的整体发展趋势。",
                    "should_include": True,
                    "region": "国际/行业",
                    "category": "行业动态",
                    "keywords": "AI",
                    "inclusion_reason": "行业竞争趋势可能影响市场格局。",
                    "region_reason": "内容讨论国际行业竞争。",
                    "decision_path": "战略信号",
                    "signal_type": "关键技术",
                    "business_impact": "竞争格局",
                    "exclusion_code": "无",
                },
                require_review_fields=True,
                require_decision_fields=True,
                allowed_keywords="AI",
                source_item={
                    "source_title": "中国AI四强追赶美国",
                    "source_summary": "文章比较两国企业的整体发展趋势。",
                },
            )

    def test_stock_market_movement_cannot_enter_strategic_route(self):
        with self.assertRaisesRegex(RuntimeError, "股价、行情或市场情绪"):
            briefing._validated_ai_copy(
                {
                    "title": "韩股重挫AI晶片股暴跌",
                    "summary": "AI相关疑虑导致晶片股价大幅下跌。",
                    "should_include": True,
                    "region": "国际/行业",
                    "category": "行业动态",
                    "keywords": "AI",
                    "inclusion_reason": "股市下跌可能影响行业融资。",
                    "region_reason": "事件发生在韩国市场。",
                    "decision_path": "战略信号",
                    "signal_type": "市场需求",
                    "business_impact": "资本配置",
                    "exclusion_code": "无",
                },
                require_review_fields=True,
                require_decision_fields=True,
                allowed_keywords="AI",
                source_item={
                    "source_title": "韩股一度重挫逾7% AI相关疑虑造成晶片股价暴跌",
                    "source_summary": "韩国股市下跌，晶片股价格大幅波动。",
                },
            )

    def test_hard_policy_exclusion_is_resolved_not_deferred(self):
        item = {
            "module": "基础设施/网络/技术类",
            "category": "行业动态",
            "title": "中国AI四强追赶美国",
            "snippet": "文章比较中美人工智能企业的整体发展趋势。",
            "keywords": ["AI"],
            "source": "Example",
            "url": "https://example.com/ai-trend",
        }
        ai_result = {
            "items": [
                {
                    "id": briefing._candidate_editor_key(item)[:16],
                    "title": "中国AI四强追赶美国",
                    "summary": "文章比较中美人工智能企业的整体发展趋势。",
                    "should_include": True,
                    "region": "国际/行业",
                    "category": "行业动态",
                    "keywords": "AI",
                    "inclusion_reason": "行业竞争趋势可能影响市场格局。",
                    "region_reason": "内容讨论国际行业竞争。",
                    "decision_path": "战略信号",
                    "signal_type": "关键技术",
                    "business_impact": "竞争格局",
                    "exclusion_code": "无",
                }
            ]
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
                return_value=ai_result,
            ) as call,
        ):
            result = briefing.polish_candidates_before_review([item])

        self.assertEqual(result, [])
        self.assertEqual(call.call_count, 0)
        audit = next(
            payload
            for path, payload in writes
            if path == briefing.AI_EDITOR_AUDIT_PATH
        )
        self.assertEqual(audit["resolved_count"], 1)
        self.assertEqual(audit["excluded_count"], 1)
        self.assertEqual(audit["deferred_count"], 0)

    def test_review_copy_uses_source_title_and_summary_when_ai_omits_format_fields(self):
        result = briefing._validated_ai_copy(
            {
                "should_include": False,
                "region": "国际/行业",
                "category": "行业动态",
                "keywords": "AI",
                "inclusion_reason": "文章仅偶然提及AI，没有具体技术、市场或业务事件。",
                "region_reason": "事件发生在海外市场。",
                "decision_path": "排除",
                "signal_type": "无",
                "business_impact": "无",
                "exclusion_code": "关键词偶然出现",
            },
            require_review_fields=True,
            require_decision_fields=True,
            allowed_keywords="AI",
            source_item={
                "source_title": "海外企业发布季度社会活动简报",
                "source_summary": "该企业介绍社区活动，并在背景材料中偶然提到人工智能。",
            },
        )

        self.assertEqual(result["title"], "海外企业发布季度社会活动简报")
        self.assertIn("社区活动", result["summary"])
        self.assertFalse(result["should_include"])

    def test_single_item_retry_accepts_batch_wrapper(self):
        item = {
            "module": "政策/法规类",
            "category": "政策监管",
            "title": "海外社区活动简报",
            "snippet": "该企业介绍社区活动，并在背景材料中偶然提到人工智能。",
            "keywords": ["AI"],
            "source": "Example",
            "url": "https://example.com/community",
        }
        wrapped_retry = {
            "items": [
                {
                    "id": briefing._candidate_editor_key(item)[:16],
                    "should_include": False,
                    "region": "国际/行业",
                    "category": "行业动态",
                    "keywords": "AI",
                    "inclusion_reason": "文章仅偶然提及AI，没有具体技术、市场或业务事件。",
                    "region_reason": "事件发生在海外市场。",
                    "decision_path": "排除",
                    "signal_type": "无",
                    "business_impact": "无",
                    "exclusion_code": "关键词偶然出现",
                }
            ]
        }
        with (
            mock.patch.object(briefing, "_read_json", return_value={"items": {}}),
            mock.patch.object(briefing, "_atomic_write_json"),
            mock.patch.object(
                briefing,
                "_call_internal_ai",
                side_effect=[{}, wrapped_retry],
            ),
        ):
            result = briefing.polish_candidates_before_review([item])

        self.assertEqual(result, [])

    def test_verbose_batch_omission_gets_compact_decision_instead_of_defer(self):
        included = {
            "module": "竞争对手",
            "category": "竞对动态",
            "title": "HKT推出企业AI平台",
            "snippet": "HKT announced an AI platform for enterprise customers.",
            "keywords": ["HKT", "AI"],
            "source": "Example",
            "url": "https://example.com/hkt-ai",
        }
        excluded = {
            "module": "基础设施/网络/技术类",
            "category": "行业动态",
            "title": "评论员讨论人工智能未来",
            "snippet": "评论员表达对人工智能未来的个人观点，没有宣布具体变化。",
            "keywords": ["AI"],
            "source": "Example",
            "url": "https://example.com/ai-opinion",
        }
        verbose = {
            "items": [
                {
                    "id": briefing._candidate_editor_key(included)[:16],
                    "title": "HKT推出企业AI平台",
                    "summary": "HKT面向企业客户推出AI平台，扩展企业数字服务能力。",
                    "should_include": True,
                    "region": "香港本地",
                    "category": "竞对动态",
                    "keywords": "HKT、AI",
                    "inclusion_reason": "HKT推出企业AI平台，直接影响企业产品与竞争格局。",
                    "region_reason": "事件主体及目标市场均在香港。",
                    "decision_path": "竞对直通",
                    "signal_type": "竞对经营动作",
                    "business_impact": "竞争格局",
                    "exclusion_code": "无",
                }
            ]
        }
        compact = {
            "items": [
                {
                    "id": briefing._candidate_editor_key(excluded)[:16],
                    "route": "X",
                    "signal": "0",
                    "impact": "0",
                    "exclude": "5",
                    "region": "I",
                }
            ]
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
                side_effect=[verbose, compact],
            ) as call,
        ):
            result = briefing.polish_candidates_before_review([included, excluded])

        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["ai_decision_path"], "竞对直通")
        self.assertEqual(call.call_count, 2)
        audit = next(
            payload
            for path, payload in writes
            if path == briefing.AI_EDITOR_AUDIT_PATH
        )
        self.assertEqual(audit["resolved_count"], 2)
        self.assertEqual(audit["excluded_count"], 1)
        self.assertEqual(audit["deferred_count"], 0)
        self.assertEqual(audit["compact_retry_item_count"], 1)
        self.assertEqual(audit["compact_retry_resolved_count"], 1)

    def test_compact_codes_repair_invalid_verbose_decision_without_third_call(self):
        item = {
            "module": "基础设施/网络/技术类",
            "category": "行业动态",
            "title": "香港公布数据中心能源使用新规",
            "snippet": "新规提高数据中心能源披露要求并影响运营成本。",
            "keywords": ["Data center"],
            "source": "Example",
            "url": "https://example.com/data-centre-rule",
        }
        item_id = briefing._candidate_editor_key(item)[:16]
        verbose = {
            "items": [
                {
                    "id": item_id,
                    "title": "香港公布数据中心能源使用新规",
                    "summary": "香港提高数据中心能源披露要求，相关运营方将面对新的合规与成本安排。",
                    "should_include": True,
                    "region": "香港本地",
                    "category": "行业动态",
                    "keywords": "Data center",
                    "inclusion_reason": "数据中心新规将改变基础设施运营要求。",
                    "region_reason": "政策在香港发布。",
                    "decision_path": "战略信号",
                    "signal_type": "监管政策",
                    "business_impact": "一整段不合法的自由文本",
                    "exclusion_code": "无",
                }
            ]
        }
        compact = {
            "items": [
                {
                    "id": item_id,
                    "route": "S",
                    "signal": "R",
                    "impact": "L",
                    "exclude": "0",
                    "region": "H",
                }
            ]
        }
        with (
            mock.patch.object(briefing, "_read_json", return_value={"items": {}}),
            mock.patch.object(briefing, "_atomic_write_json"),
            mock.patch.object(
                briefing,
                "_call_internal_ai",
                side_effect=[verbose, compact],
            ) as call,
        ):
            result = briefing.polish_candidates_before_review([item])

        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["ai_business_impact"], "合规与牌照")
        self.assertEqual(result[0]["ai_decision_path"], "战略信号")
        self.assertEqual(call.call_count, 2)

    def test_single_item_retry_budget_defers_without_unbounded_calls(self):
        items = [
            {
                "module": "基础设施/网络/技术类",
                "category": "行业动态",
                "title": f"海外企业发布技术活动简报{i}",
                "snippet": "该企业介绍社区活动，并在背景材料中偶然提到人工智能。",
                "keywords": ["AI"],
                "source": "Example",
                "url": f"https://example.com/community/{i}",
            }
            for i in range(2)
        ]
        writes = []
        with (
            mock.patch.object(briefing, "_read_json", return_value={"items": {}}),
            mock.patch.object(
                briefing,
                "_atomic_write_json",
                side_effect=lambda path, payload: writes.append((path, payload)),
            ),
            mock.patch.object(briefing, "_call_internal_ai", return_value={}) as call,
            mock.patch.object(briefing, "AI_EDITOR_SINGLE_RETRY_LIMIT", 0),
        ):
            result = briefing.polish_candidates_before_review(items)

        self.assertEqual(result, [])
        self.assertEqual(call.call_count, 2)
        audit = next(
            payload
            for path, payload in writes
            if path == briefing.AI_EDITOR_AUDIT_PATH
        )
        self.assertEqual(audit["single_retry_attempt_count"], 0)
        self.assertEqual(audit["retry_budget_exhausted_count"], 2)
        self.assertEqual(audit["compact_retry_item_count"], 2)
        self.assertEqual(audit["compact_retry_resolved_count"], 0)
        self.assertFalse(audit["write_blocked"])

    def test_competitor_route_fills_format_only_impact_without_blocking(self):
        result = briefing._validated_ai_copy(
            {
                "title": "SmarTone调整门店客户服务时间",
                "summary": "SmarTone公布门店客户服务时间调整，直接影响现有客户服务安排。",
                "should_include": True,
                "region": "香港本地",
                "category": "竞对动态",
                "keywords": "SmarTone",
                "inclusion_reason": "门店服务时间调整属于竞对客户服务信息。",
                "region_reason": "事件主体及受影响门店均在香港。",
                "decision_path": "竞对直通",
                "signal_type": "",
                "business_impact": "无",
                "exclusion_code": "",
            },
            require_review_fields=True,
            require_decision_fields=True,
            allowed_keywords="SmarTone",
            source_item={
                "module": "竞争对手",
                "title": "SmarTone调整门店客户服务时间",
                "keywords": ["SmarTone"],
            },
        )

        self.assertTrue(result["should_include"])
        self.assertEqual(result["signal_type"], "竞对经营动作")
        self.assertEqual(result["business_impact"], "竞争格局")
        self.assertEqual(result["exclusion_code"], "无")

    def test_competitor_candidate_cannot_be_rejected_for_lack_of_strategic_value(self):
        with self.assertRaisesRegex(RuntimeError, "只能因主体误判或明确噪音"):
            briefing._validated_ai_copy(
                {
                    "title": "AT&T开展社区数字技能培训",
                    "summary": "AT&T在当地社区开设数字技能培训项目并向居民提供设备。",
                    "should_include": False,
                    "region": "国际/行业",
                    "category": "行业动态",
                    "keywords": "AT&T",
                    "inclusion_reason": "活动规模较小，缺少战略价值。",
                    "region_reason": "事件发生在美国。",
                    "decision_path": "排除",
                    "signal_type": "无",
                    "business_impact": "无",
                    "exclusion_code": "无电信战略影响",
                },
                require_review_fields=True,
                require_decision_fields=True,
                allowed_keywords="AT&T",
                source_item={
                    "module": "竞争对手",
                    "title": "AT&T开展社区数字技能培训",
                    "snippet": "AT&T opened a digital skills training center.",
                    "keywords": ["AT&T"],
                },
            )

    def test_confirmed_competitor_event_is_included_even_when_routine(self):
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
            "ai_should_include": True,
            "ai_region": "国际/行业",
            "ai_category": "竞对动态",
            "ai_keywords": "T-Mobile",
            "ai_inclusion_reason": "客户服务调整直接影响用户体验与渠道运营。",
            "ai_region_reason": "事件主体和受影响市场均位于美国。",
            "ai_decision_path": "竞对直通",
            "ai_signal_type": "竞对经营动作",
            "ai_business_impact": "客户与渠道",
            "ai_exclusion_code": "无",
            "ai_editor_version": briefing.AI_EDITOR_VERSION,
        }

        with (
            mock.patch.object(briefing, "_read_json", return_value={"items": {}}),
            mock.patch.object(briefing, "_atomic_write_json"),
            mock.patch.object(briefing, "_call_internal_ai") as ai_call,
        ):
            result = briefing.polish_candidates_before_review([item])

        self.assertEqual(len(result), 1)
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
            "decision_path": "竞对直通",
            "signal_type": "竞对经营动作",
            "business_impact": "产品与定价",
            "exclusion_code": "无",
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

    def test_editor_defers_fully_failed_ai_batch_without_blocking(self):
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
            result = briefing.polish_candidates_before_review([item])

        self.assertEqual(result, [])
        audit = next(
            payload
            for path, payload in writes
            if path == briefing.AI_EDITOR_AUDIT_PATH
        )
        self.assertEqual(audit["input_count"], 1)
        self.assertEqual(audit["resolved_count"], 0)
        self.assertEqual(audit["deferred_count"], 1)
        self.assertTrue(audit["continued_with_partial_results"])
        self.assertFalse(audit["write_blocked"])
        self.assertFalse(audit["policy"]["batch_blocking"])

    def test_editor_isolates_one_failed_item_and_continues_resolved_items(self):
        items = []
        for index in range(1):
            items.append(
                {
                    "module": "竞争对手",
                    "category": "竞对动态",
                    "title": f"Verizon发布第{index + 1}项网络更新",
                    "snippet": "Verizon announced a network service update.",
                    "keywords": ["Verizon"],
                    "source": "Example News",
                    "url": f"https://example.com/news/verizon-{index + 1}",
                    "ai_title": f"Verizon发布第{index + 1}项网络更新",
                    "ai_summary": "Verizon公布网络服务更新及相关客户安排。",
                    "ai_should_include": True,
                    "ai_region": "国际/行业",
                    "ai_category": "竞对动态",
                    "ai_keywords": "Verizon",
                    "ai_inclusion_reason": "直接反映被监测竞对的网络服务变化。",
                    "ai_region_reason": "事件主体为国际对标运营商Verizon。",
                    "ai_decision_path": "竞对直通",
                    "ai_signal_type": "竞对经营动作",
                    "ai_business_impact": "网络与运营",
                    "ai_exclusion_code": "无",
                    "ai_editor_version": briefing.AI_EDITOR_VERSION,
                }
            )
        items.append(
            {
                "module": "竞争对手",
                "category": "竞对动态",
                "title": "KDDI发布门店更新",
                "snippet": "KDDI announced a retail store update.",
                "keywords": ["KDDI"],
                "source": "Example News",
                "url": "https://example.com/news/kddi-store",
            }
        )
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
            result = briefing.polish_candidates_before_review(items)

        self.assertEqual(len(result), 1)
        audit = next(
            payload
            for path, payload in writes
            if path == briefing.AI_EDITOR_AUDIT_PATH
        )
        self.assertEqual(audit["resolved_count"], 1)
        self.assertEqual(audit["deferred_count"], 1)
        self.assertTrue(audit["continued_with_partial_results"])
        self.assertFalse(audit["write_blocked"])

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
            "decision_path": "排除",
            "signal_type": "无",
            "business_impact": "无",
            "exclusion_code": "同名或主体误判",
            "editor_version": briefing.AI_EDITOR_VERSION,
        }
        corrected = {
            **wrong,
            "should_include": True,
            "category": "竞对动态",
            "inclusion_reason": "KDDI是正式监控的国际对标运营商，合作事项属于竞对动态。",
            "decision_path": "竞对直通",
            "signal_type": "竞对经营动作",
            "business_impact": "客户与渠道",
            "exclusion_code": "无",
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

    def test_competitor_plan_label_does_not_turn_publisher_name_into_subject(self):
        self.assertFalse(
            briefing._is_competitor_candidate(
                {
                    "module": "竞争对手",
                    "category": "行业动态",
                    "canonical_competitor": "i-CABLE",
                    "title": "日本推理小说作家离世",
                    "snippet": "日本作家因病离世，报道来自i-cable.com。",
                    "keywords": ["i-CABLE"],
                    "source": "i-cable.com",
                    "url": "https://news.google.com/example",
                }
            )
        )

    def test_upstream_competitor_category_does_not_override_subject_evidence(self):
        self.assertFalse(
            briefing._is_competitor_candidate(
                {
                    "module": "竞争对手",
                    "category": "竞对动态",
                    "title": "泽连斯基访美讨论俄乌战争",
                    "snippet": "The leaders discussed the war and regional security.",
                    "keywords": ["Globe"],
                    "source": "The Boston Globe",
                    "url": "https://example.com/world/zelensky",
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
                    "decision_path": "排除",
                    "signal_type": "无",
                    "business_impact": "无",
                    "exclusion_code": "同名或主体误判",
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
                    "decision_path": "竞对直通",
                    "signal_type": "竞对经营动作",
                    "business_impact": "客户与渠道",
                    "exclusion_code": "无",
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
