from __future__ import annotations

import json
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest import mock
from unittest.mock import patch

import executive_intelligence_pipeline as pipeline
import crawl
from data_curation.workflow import _source_rank
import scheduler


class ExecutiveIntelligencePipelineTests(unittest.TestCase):
    def test_period_rank_understands_half_year_and_canonical_named_month(self):
        self.assertEqual(pipeline._period_rank("H1 2026"), (2026, 6, 30))
        self.assertEqual(pipeline._period_rank("Jun '26 Jun 30, 2026"), (2026, 6, 30))
        self.assertGreater(pipeline._period_rank("H1 2026"), pipeline._period_rank("Q1 2026"))

    def test_ui_numeric_comparison_ignores_equal_values_and_new_fields(self):
        previous = {
            "domains": {
                "international": [
                    {"key": "Verizon|main", "entity": "Verizon", "field": "页面主值", "value": 138.19, "unit": "十亿美元"},
                ],
            },
        }
        current = {
            "domains": {
                "international": [
                    {"key": "Verizon|main", "entity": "Verizon", "field": "页面主值", "value": 138.19, "unit": "十亿美元", "context": "重新抓取"},
                    {"key": "Verizon|component:0:核验来源", "entity": "Verizon", "field": "核验来源", "value": 3, "unit": "个"},
                ],
            },
        }

        result = pipeline._compare_ui_numeric_values(previous, current)

        self.assertTrue(result["baseline_available"])
        self.assertEqual(result["changed"], 0)
        self.assertEqual(result["added"], 1)
        self.assertEqual(result["items"], [])

    def test_ui_numeric_comparison_records_explicit_old_and_new_values(self):
        previous = {
            "domains": {
                "international": [
                    {"key": "Verizon|main", "entity": "Verizon", "field": "页面主值", "value": 138.19, "unit": "十亿美元"},
                ],
            },
        }
        current = {
            "domains": {
                "international": [
                    {"key": "Verizon|main", "entity": "Verizon", "field": "页面主值", "value": 140.2, "unit": "十亿美元"},
                ],
            },
        }

        result = pipeline._compare_ui_numeric_values(previous, current)

        self.assertEqual(result["changed"], 1)
        self.assertEqual(result["domains"]["international"]["changed"], 1)
        self.assertEqual(result["items"][0]["old_value"], 138.19)
        self.assertEqual(result["items"][0]["new_value"], 140.2)

    def test_0100_handoff_requires_current_hkt_date(self):
        now = datetime(2026, 8, 25, 3, 0, tzinfo=pipeline.HKT)
        with patch.object(
            pipeline,
            "_read_json",
            return_value={"handoff_for_date": "2026-08-25", "signal_count": 3},
        ):
            result = pipeline.load_0100_source_discovery_handoff(now=now, dry_run=True)

        self.assertTrue(result["available"])
        self.assertEqual(result["signal_count"], 3)

    def test_four_database_sheet_rows_follow_discovered_reports(self):
        row = {"block": "国际运营商", "package": "四库自动更新｜财报经营指标"}
        self.assertTrue(crawl.is_database_update_row(row, 48))
        self.assertFalse(crawl.is_database_update_row({"block": "政策", "package": "法规"}, 23))

    def test_focus_prompts_use_relation_few_shots_and_forbid_free_form_causality(self):
        source = Path(pipeline.__file__).read_text(encoding="utf-8")

        self.assertIn("FOCUS_RELATION_FEW_SHOTS", source)
        self.assertIn("任务不是解释数据", source)
        self.assertIn("至少比较两个竞对、两个期间或两个指标", source)
        self.assertIn("问题：只是复述数字", source)
        self.assertIn("问题：期间不同且虚构因果", source)
        self.assertIn('(\"导致\", \"造成\", \"推动\", \"带来\", \"源于\", \"驱动\")', source)
        self.assertIn('validated_focus["headline"] = str(evidence_focus.get("headline")', source)

    def test_four_database_model_route_prefers_v4_pro(self):
        source = Path(pipeline.__file__).read_text(encoding="utf-8")

        self.assertEqual(
            pipeline._executive_model_route(),
            ["DeepSeek-V4-Pro", "GLM", "Qwen3-30B-A3B-Instruct-2507"],
        )
        self.assertNotIn(
            'list(dict.fromkeys(["Qwen3-30B-A3B-Instruct-2507", "GLM", configured_model]))',
            source,
        )
        self.assertIn('detail必须包含“表明、反映、说明”三者之一且只用一个即可', source)

    def test_manual_discovery_uses_two_explicit_numeric_anchors_per_pair(self):
        evidence = pipeline._analysis_input_snapshot()
        expected = {
            ("mainland", "local"): {"10501.9亿元", "36553百万港元"},
            ("international", "cloud"): {"138.19十亿美元", "128725百万美元"},
            ("local", "cloud"): {"36553百万港元", "128725百万美元"},
            ("mainland", "international"): {"10501.9亿元", "138.19十亿美元"},
        }
        for pair, values in expected.items():
            scoped = pipeline._manual_discovery_evidence(evidence, *pair)
            self.assertEqual(set(scoped["required_values"]), values)
            self.assertEqual({item["domain"] for item in scoped["evidence"]}, set(pair))
            self.assertTrue(all(item["source_url"].startswith("http") for item in scoped["evidence"]))

    def test_manual_discovery_regeneration_bypasses_cache_and_retries_identical_result(self):
        discoveries = [
            {"from": "mainland", "to": "international", "title": "旧标题", "detail": "旧正文", "kind": "AI综合研判"},
            {"from": "local", "to": "cloud", "title": "二", "detail": "正文二", "kind": "AI综合研判"},
            {"from": "international", "to": "cloud", "title": "三", "detail": "正文三", "kind": "AI综合研判"},
            {"from": "local", "to": "mainland", "title": "四", "detail": "正文四", "kind": "AI综合研判"},
        ]
        cached = json.dumps(discoveries[0], ensure_ascii=False)
        fresh = json.dumps({**discoveries[0], "title": "新标题", "detail": "新正文"}, ensure_ascii=False)
        responses = []
        for content in (cached, fresh):
            response = mock.MagicMock()
            response.__enter__.return_value.read.return_value = json.dumps({
                "choices": [{"message": {"content": content}}]
            }).encode("utf-8")
            responses.append(response)

        with tempfile.TemporaryDirectory() as temp_dir:
            output_path = Path(temp_dir) / "analysis.json"
            output_path.write_text(json.dumps({
                "model_analysis": {
                    "evidence_hash": "evidence-hash",
                    "insight_format": pipeline.INSIGHT_FORMAT_VERSION,
                    "summaries": {"macro": {}},
                    "discoveries": discoveries,
                }
            }, ensure_ascii=False), encoding="utf-8")
            with (
                patch("executive_intelligence_pipeline._analysis_input_snapshot", return_value={"domains": []}),
                patch("executive_intelligence_pipeline._content_hash", return_value="evidence-hash"),
                patch("executive_intelligence_pipeline._compact_discovery_evidence", return_value={"domains": []}),
                patch("executive_intelligence_pipeline._validate_model_discoveries", side_effect=lambda items, _evidence: items),
                patch("ai_config.load_ai_config", return_value={
                    "api_key": "test-key", "base_url": "https://example.test/v1", "model": "deepseek-v4"
                }),
                patch("ai_rate_limit.wait_for_internal_ai_slot"),
                patch("network_utils.urlopen_with_local_proxy_fallback", side_effect=responses) as request,
            ):
                result = pipeline.regenerate_model_discovery(
                    0, "mainland", "international", path=output_path
                )

        requests = [call.args[0] for call in request.call_args_list]
        bodies = [json.loads(item.data.decode("utf-8")) for item in requests]
        self.assertEqual([body["model"] for body in bodies], ["DeepSeek-V4-Pro", "GLM"])
        request_ids = [item.get_header("X-request-id") for item in requests]
        self.assertNotEqual(request_ids[0], request_ids[1])
        self.assertIn(request_ids[0], bodies[0]["messages"][-1]["content"])
        self.assertIn("内地移动用户与国际后付费口径属于不同层面", bodies[0]["messages"][-1]["content"])
        self.assertIn("用户总量不能替代客户价值判断", bodies[1]["messages"][-1]["content"])
        self.assertEqual(requests[0].get_header("Cache-control"), "no-cache, no-store")
        self.assertEqual(request.call_args_list[0].kwargs["timeout"], 15)
        self.assertEqual(result["title"], "新标题")
        self.assertEqual(result["model"], "GLM")

    def test_discovery_generation_contract_uses_current_ui_domains(self):
        source = Path(pipeline.__file__).read_text(encoding="utf-8")
        self.assertIn("local、international、mainland、cloud四个战略总览数据域", source)
        self.assertNotIn("local、international、cloud、macro四库证据", source)
        self.assertEqual(pipeline.UI_DOMAIN_IDS, ("local", "international", "mainland", "cloud"))

    def test_manual_discovery_regeneration_falls_back_for_all_four_pairs(self):
        evidence = pipeline._analysis_input_snapshot()
        discoveries = pipeline._deterministic_discoveries(evidence)
        for index, discovery in enumerate(discoveries):
            for regeneration_index in range(3):
                fallback = pipeline._safe_discovery_regeneration_fallback(
                    evidence,
                    str(discovery["from"]),
                    str(discovery["to"]),
                    current=discovery,
                    regeneration_index=regeneration_index,
                )
                candidate = [dict(item) for item in discoveries]
                candidate[index] = fallback
                pipeline._validate_model_discoveries(candidate, evidence)
        empty_response = mock.MagicMock()
        empty_response.__enter__.return_value.read.return_value = json.dumps({
            "choices": [{"message": {"content": ""}}]
        }).encode("utf-8")

        with tempfile.TemporaryDirectory() as temp_dir:
            output_path = Path(temp_dir) / "analysis.json"
            output_path.write_text(json.dumps({
                "model_analysis": {
                    "evidence_hash": pipeline._content_hash(evidence),
                    "insight_format": pipeline.INSIGHT_FORMAT_VERSION,
                    "summaries": {"local": {}},
                    "discoveries": discoveries,
                }
            }, ensure_ascii=False), encoding="utf-8")
            results = []
            with (
                patch("executive_intelligence_pipeline._analysis_input_snapshot", return_value=evidence),
                patch("ai_config.load_ai_config", return_value={
                    "api_key": "test-key", "base_url": "https://example.test/v1", "model": "deepseek-v4"
                }),
                patch("ai_rate_limit.wait_for_internal_ai_slot"),
                patch("network_utils.urlopen_with_local_proxy_fallback", return_value=empty_response),
            ):
                for index, discovery in enumerate(discoveries):
                    results.append(pipeline.regenerate_model_discovery(
                        index,
                        str(discovery["from"]),
                        str(discovery["to"]),
                        path=output_path,
                    ))

        self.assertTrue(all(item["ok"] and item["fallback_used"] for item in results))
        self.assertTrue(all(item["model"] == "evidence-rule-fallback" for item in results))
        self.assertEqual(len({item["title"] for item in results}), 4)
        self.assertTrue(all(item["kind"] == "数据证据解读" for item in results))

    def test_focus_generation_changes_cache_busting_prompt_each_time(self):
        focus = {
            "id": "scale",
            "label": "方案规模",
            "metric": {"value": 161, "unit": "项"},
            "items": [
                {"name": "HKBN", "value": 59, "unit": "项"},
                {"name": "HGC", "value": 7, "unit": "项"},
            ],
        }
        content = json.dumps({
            "headline": "头部供给形成断层",
            "analysis": "HKBN 59项与HGC 7项形成断层，表明供给集中度主要由头部厂商形成，并非均衡分布。"
        }, ensure_ascii=False)

        def response(*_args, **_kwargs):
            result = mock.MagicMock()
            result.__enter__.return_value.read.return_value = json.dumps({
                "choices": [{"message": {"content": content}}]
            }).encode("utf-8")
            return result

        with (
            patch("ai_config.load_ai_config", return_value={
                "api_key": "test-key", "base_url": "https://example.test/v1", "model": "deepseek-v4"
            }),
            patch("ai_rate_limit.wait_for_internal_ai_slot"),
            patch("network_utils.urlopen_with_local_proxy_fallback", side_effect=response) as request,
        ):
            pipeline.generate_model_focus_insight("local", focus)
            pipeline.generate_model_focus_insight("local", focus)

        prompts = [
            json.loads(call.args[0].data.decode("utf-8"))["messages"][1]["content"]
            for call in request.call_args_list
        ]
        self.assertEqual(len(prompts), 2)
        self.assertNotEqual(prompts[0], prompts[1])
        requests = [call.args[0] for call in request.call_args_list]
        self.assertTrue(all(item.get_header("Cache-control") == "no-cache, no-store" for item in requests))
        self.assertTrue(all(item.get_header("Pragma") == "no-cache" for item in requests))
        self.assertNotEqual(
            requests[0].get_header("X-request-id"),
            requests[1].get_header("X-request-id"),
        )
        self.assertIn("?request_id=focus-local-scale-", requests[0].full_url)
        self.assertNotEqual(requests[0].full_url, requests[1].full_url)

    def test_focus_generation_marks_recent_ai_copy_as_forbidden(self):
        focus = {
            "id": "scale",
            "label": "在售方案组合",
            "metric": {"value": 84, "unit": "个"},
            "insight": "旧版共161项，不得再发给模型。",
            "headline": "旧版头部三家主导",
            "recent_insights": ["历史文案含59项与48项。"],
            "recent_headlines": ["方案供给集中"],
            "items": [
                {"name": "HKBN", "value": 27, "unit": "个产品"},
                {"name": "HGC", "value": 4, "unit": "个产品"},
            ],
        }
        content = json.dumps({
            "headline": "去重后选择呈分层",
            "analysis": "HKBN 27个产品与HGC 4个产品形成差距，说明去重后产品选择并非均匀分布。",
        }, ensure_ascii=False)
        response = mock.MagicMock()
        response.__enter__.return_value.read.return_value = json.dumps({
            "choices": [{"message": {"content": content}}]
        }).encode("utf-8")
        with (
            patch("ai_config.load_ai_config", return_value={
                "api_key": "test-key", "base_url": "https://example.test/v1", "model": "deepseek-v4"
            }),
            patch("ai_rate_limit.wait_for_internal_ai_slot"),
            patch("network_utils.urlopen_with_local_proxy_fallback", return_value=response) as request,
        ):
            pipeline.generate_model_focus_insight("local", focus)

        prompt = json.loads(request.call_args.args[0].data.decode("utf-8"))["messages"][1]["content"]
        self.assertIn('"forbidden_recent_analyses"', prompt)
        self.assertIn("旧版共161项，不得再发给模型。", prompt)
        self.assertIn("历史文案含59项与48项。", prompt)
        self.assertIn("旧版头部三家主导", prompt)
        self.assertIn('"value": 84', prompt)
        self.assertIn('"value": 27', prompt)

    def test_local_scale_regeneration_excludes_track_details_and_retries_scope_leak(self):
        focus = {
            "id": "scale",
            "label": "方案规模",
            "metric": {"value": 161, "unit": "项"},
            "insight": "59项与7项的差距表明方案数量集中于头部厂商。",
            "items": [
                {"name": "HKBN", "value": 59, "unit": "项", "detail": "覆盖4个赛道"},
                {"name": "HGC", "value": 7, "unit": "项", "detail": "覆盖1个赛道"},
            ],
        }
        leaked = json.dumps({
            "headline": "赛道广度决定规模",
            "analysis": "HKBN 59项覆盖4个赛道，说明方案规模与赛道广度相关。"
        }, ensure_ascii=False)
        replacement = json.dumps({
            "headline": "方案供给头部集中",
            "analysis": "HKBN 59项与HGC 7项形成数量断层，表明在售方案供给集中于头部厂商。"
        }, ensure_ascii=False)
        responses = []
        for content in (leaked, replacement):
            response = mock.MagicMock()
            response.__enter__.return_value.read.return_value = json.dumps({
                "choices": [{"message": {"content": content}}]
            }).encode("utf-8")
            responses.append(response)
        with (
            patch("ai_config.load_ai_config", return_value={
                "api_key": "test-key", "base_url": "https://example.test/v1", "model": "deepseek-v4"
            }),
            patch("ai_rate_limit.wait_for_internal_ai_slot"),
            patch("network_utils.urlopen_with_local_proxy_fallback", side_effect=responses) as request,
        ):
            result = pipeline.generate_model_focus_insight("local", focus)

        first_payload = json.loads(request.call_args_list[0].args[0].data.decode("utf-8"))
        first_prompt = first_payload["messages"][1]["content"]
        self.assertNotIn("覆盖4个赛道", first_prompt)
        self.assertIn("记录数只作数据质量边界", first_prompt)
        self.assertIn("不能成为标题或主要结论", first_prompt)
        self.assertIn("请求唯一标识", first_prompt)
        self.assertIn("required_angle", first_prompt)
        self.assertEqual(request.call_count, 2)
        self.assertNotIn("赛道", result["focus"]["analysis"])

    def test_current_local_scale_refresh_requires_a_distinct_supported_angle(self):
        focus = {
            "id": "scale",
            "label": "在售方案组合",
            "metric": {"value": 84, "unit": "个"},
            "regeneration_index": 8,
            "items": [
                {"name": "HKBN", "value": 27, "unit": "个产品", "record_count": 59, "component_count": 27},
                {"name": "3HK / Hutchison", "value": 24, "unit": "个产品", "record_count": 48, "component_count": 24},
                {"name": "SmarTone", "value": 21, "unit": "个产品", "record_count": 37, "component_count": 21},
                {"name": "i-CABLE", "value": 8, "unit": "个产品", "record_count": 10, "component_count": 8},
                {"name": "HGC", "value": 4, "unit": "个产品", "record_count": 7, "component_count": 4},
            ],
        }
        same_meaning = json.dumps({
            "headline": "在售产品头部集中",
            "analysis": "HKBN 27个、3HK 24个与SmarTone 21个高于i-CABLE 8个及HGC 4个，说明头部三家集中度较高。",
        }, ensure_ascii=False)
        new_boundary = json.dumps({
            "headline": "数量不代表吸引力",
            "analysis": "去重后在售产品84个，但产品数量不能等同产品吸引力或竞争力，这页只能说明当前收录的选择宽度。",
        }, ensure_ascii=False)
        responses = []
        for content in (same_meaning, new_boundary):
            response = mock.MagicMock()
            response.__enter__.return_value.read.return_value = json.dumps({
                "choices": [{"message": {"content": content}}]
            }).encode("utf-8")
            responses.append(response)
        with (
            patch("ai_config.load_ai_config", return_value={
                "api_key": "test-key", "base_url": "https://example.test/v1", "model": "deepseek-v4"
            }),
            patch("ai_rate_limit.wait_for_internal_ai_slot"),
            patch("network_utils.urlopen_with_local_proxy_fallback", side_effect=responses) as request,
        ):
            result = pipeline.generate_model_focus_insight("local", focus)

        first_prompt = json.loads(request.call_args_list[0].args[0].data.decode("utf-8"))["messages"][1]["content"]
        retry_prompt = json.loads(request.call_args_list[1].args[0].data.decode("utf-8"))["messages"][-1]["content"]
        self.assertIn("产品数量不能等同产品吸引力", first_prompt)
        self.assertIn('"record_count": 59', first_prompt)
        self.assertIn("数据边界", retry_prompt)
        self.assertEqual(request.call_count, 2)
        self.assertIn("不能等同", result["focus"]["analysis"])
        self.assertNotIn("头部三家集中度", result["focus"]["analysis"])

    def test_current_local_scale_refresh_repairs_to_a_grounded_judgement(self):
        focus = {
            "id": "scale",
            "label": "在售方案组合",
            "metric": {"value": 84, "unit": "个"},
            "regeneration_index": 8,
            "items": [
                {"name": "HKBN", "value": 27, "unit": "个产品", "record_count": 59, "component_count": 27},
                {"name": "3HK / Hutchison", "value": 24, "unit": "个产品", "record_count": 48, "component_count": 24},
                {"name": "SmarTone", "value": 21, "unit": "个产品", "record_count": 37, "component_count": 21},
                {"name": "i-CABLE", "value": 8, "unit": "个产品", "record_count": 10, "component_count": 8},
                {"name": "HGC", "value": 4, "unit": "个产品", "record_count": 7, "component_count": 4},
            ],
        }
        too_long = json.dumps({
            "headline": "数量不代表吸引力",
            "analysis": "去重后在售产品84个，但产品数量不能等同产品吸引力或竞争力。" + "数据边界" * 30,
        }, ensure_ascii=False)
        responses = []
        for _ in range(6):
            response = mock.MagicMock()
            response.__enter__.return_value.read.return_value = json.dumps({
                "choices": [{"message": {"content": too_long}}]
            }).encode("utf-8")
            responses.append(response)
        with (
            patch("ai_config.load_ai_config", return_value={
                "api_key": "test-key", "base_url": "https://example.test/v1", "model": "deepseek-v4"
            }),
            patch("ai_rate_limit.wait_for_internal_ai_slot"),
            patch("network_utils.urlopen_with_local_proxy_fallback", side_effect=responses),
        ):
            result = pipeline.generate_model_focus_insight("local", focus)

        self.assertEqual(result["model"], "DeepSeek-V4-Pro")
        self.assertTrue(result["focus"]["repaired"])
        self.assertEqual(result["focus"]["headline"], "数量不代表吸引力")
        self.assertIn("去重后在售产品84个", result["focus"]["analysis"])
        self.assertLessEqual(len(result["focus"]["analysis"]), 120)

    def test_fast_focus_generation_retries_a_duplicate_with_another_model(self):
        focus = {
            "id": "scale",
            "label": "方案规模",
            "metric": {"value": 161, "unit": "项"},
            "insight": "HKBN59项高于HGC7项，结构差异表明方案供给集中于头部，而非各品牌同步扩张。",
            "items": [
                {"name": "HKBN", "value": 59, "unit": "项"},
                {"name": "HGC", "value": 7, "unit": "项"},
            ],
        }
        duplicate = json.dumps({
            "headline": "方案供给头部集中",
            "analysis": focus["insight"],
        }, ensure_ascii=False)
        replacement = json.dumps({
            "headline": "头尾方案形成断层",
            "analysis": "59项与7项形成明显断层，说明竞争结构受制于头部集中，并非各品牌同步扩张。"
        }, ensure_ascii=False)
        responses = []
        for content in (duplicate, replacement):
            response = mock.MagicMock()
            response.__enter__.return_value.read.return_value = json.dumps({
                "choices": [{"message": {"content": content}}]
            }).encode("utf-8")
            responses.append(response)
        with (
            patch("ai_config.load_ai_config", return_value={
                "api_key": "test-key", "base_url": "https://example.test/v1", "model": "deepseek-v4"
            }),
            patch("ai_rate_limit.wait_for_internal_ai_slot"),
            patch("network_utils.urlopen_with_local_proxy_fallback", side_effect=responses) as request,
        ):
            result = pipeline.generate_model_focus_insight("local", focus)

        self.assertEqual(request.call_count, 2)
        self.assertEqual(result["model"], "GLM")
        self.assertNotEqual(result["focus"]["analysis"], focus["insight"])

    def test_revenue_focus_refresh_uses_current_verified_values(self):
        evidence = pipeline._analysis_input_snapshot()
        local = next(item for item in evidence["domains"] if item["id"] == "local")
        focus = next(item for item in local["focuses"] if item["id"] == "revenue")
        content = json.dumps({
            "headline": "经营资源底盘分层",
            "analysis": "HKT FY2025营收36553百万港元，3HK为5448百万港元；这表明HKT经营资源底盘更厚，3HK资源容错较窄，但营收不等同盈利能力。",
        }, ensure_ascii=False)
        response = mock.MagicMock()
        response.__enter__.return_value.read.return_value = json.dumps({
            "choices": [{"message": {"content": content}}]
        }).encode("utf-8")
        with (
            patch("ai_config.load_ai_config", return_value={
                "api_key": "test-key", "base_url": "https://example.test/v1", "model": "deepseek-v4"
            }),
            patch("ai_rate_limit.wait_for_internal_ai_slot"),
            patch("network_utils.urlopen_with_local_proxy_fallback", return_value=response) as request,
        ):
            result = pipeline.generate_model_focus_insight("local", focus)

        prompt = json.loads(request.call_args.args[0].data.decode("utf-8"))["messages"][1]["content"]
        self.assertIn('"value": 36553.0', prompt)
        self.assertIn("只比较FY2025营收绝对值", prompt)
        self.assertIn("HKT FY2025营收36553", result["focus"]["analysis"])

    def test_revenue_focus_gate_requires_current_operating_values(self):
        evidence = pipeline._analysis_input_snapshot()
        local = next(item for item in evidence["domains"] if item["id"] == "local")
        focus = next(item for item in local["focuses"] if item["id"] == "revenue")
        bad = "HKT与3HK披露频次不同，说明竞争资源形成分层。"
        self.assertIn("缺少输入数值证据", pipeline._focus_gate_error("local", "revenue", bad, focus))
        causal = "HKT FY2025营收36553百万港元，3HK为5448百万港元；HKT规模优势驱动盈利能力提升。"
        self.assertIn("未经证据支持的因果词", pipeline._focus_gate_error("local", "revenue", causal, focus))
        good = "HKT FY2025营收36553百万港元，3HK为5448百万港元；这表明HKT经营资源底盘更厚，3HK资源容错较窄，但营收不等同盈利能力。"
        self.assertEqual(pipeline._focus_gate_error("local", "revenue", good, focus), "")

    def test_current_focus_bundle_repairs_disclosure_headline(self):
        evidence = pipeline._analysis_input_snapshot()
        summaries = pipeline._deterministic_domain_summaries(evidence)
        local = next(item for item in summaries if item["domain"] == "local")
        revenue = next(item for item in local["focuses"] if item["id"] == "revenue")
        revenue["headline"] = "财报披露密度分层"
        validated = pipeline._validate_model_summaries(summaries, evidence)
        validated_revenue = next(
            focus
            for summary in validated if summary["domain"] == "local"
            for focus in summary["focuses"] if focus["id"] == "revenue"
        )
        self.assertEqual(validated_revenue["headline"], pipeline._strategic_focus_headline("local", "revenue"))
        revenue["headline"] = "营收口径边界显现"
        validated = pipeline._validate_model_summaries(summaries, evidence)
        validated_revenue = next(
            focus
            for summary in validated if summary["domain"] == "local"
            for focus in summary["focuses"] if focus["id"] == "revenue"
        )
        self.assertEqual(validated_revenue["headline"], pipeline._strategic_focus_headline("local", "revenue"))

    def test_focus_generation_normalizes_long_title_without_discarding_fresh_analysis(self):
        evidence = pipeline._analysis_input_snapshot()
        local = next(item for item in evidence["domains"] if item["id"] == "local")
        focus = next(item for item in local["focuses"] if item["id"] == "revenue")
        fresh_analysis = (
            "HKT FY2025营收36553百万港元，3HK为5448百万港元；"
            "这表明HKT经营资源底盘更厚，3HK资源容错较窄，但营收不等同盈利能力。"
        )
        content = json.dumps({
            "headline": "经营资源承载能力与盈利能力不能直接等同",
            "analysis": fresh_analysis,
        }, ensure_ascii=False)
        response = mock.MagicMock()
        response.__enter__.return_value.read.return_value = json.dumps({
            "choices": [{"message": {"content": content}}]
        }).encode("utf-8")

        with (
            patch("ai_config.load_ai_config", return_value={
                "api_key": "test-key", "base_url": "https://example.test/v1", "model": "deepseek-v4"
            }),
            patch("ai_rate_limit.wait_for_internal_ai_slot"),
            patch("network_utils.urlopen_with_local_proxy_fallback", return_value=response) as request,
        ):
            result = pipeline.generate_model_focus_insight("local", focus)

        self.assertEqual(request.call_count, 1)
        self.assertEqual(result["focus"]["analysis"], fresh_analysis)
        self.assertLessEqual(len(result["focus"]["headline"]), 14)

    def test_macro_service_regeneration_rotates_to_safe_evidence_fallback(self):
        focus = {
            "id": "service",
            "label": "服务压力",
            "metric": {"value": 2.9, "unit": "%"},
            "items": [
                {"name": "5G人口覆盖", "value": 99.9},
                {"name": "已分配公共移动及5G频谱", "value": 850},
                {"name": "电讯业投资", "value": 1.3},
                {"name": "电讯投诉", "value": 2.9},
            ],
            "regeneration_index": 2,
            "recent_insights": [
                "电讯业投资同比1.3%截至2025-03-31，电讯投诉同比2.9%截至2025-12-31，期间口径不同，不能判断两者关系。",
            ],
        }
        invalid = json.dumps({
            "headline": "投资增量驱动服务改善",
            "analysis": "电讯业投资1.3%直接驱动投诉2.9%，说明两者存在因果。",
        }, ensure_ascii=False)
        responses = []
        for _ in range(6):
            response = mock.MagicMock()
            response.__enter__.return_value.read.return_value = json.dumps({
                "choices": [{"message": {"content": invalid}}]
            }).encode("utf-8")
            responses.append(response)

        with (
            patch("ai_config.load_ai_config", return_value={
                "api_key": "test-key", "base_url": "https://example.test/v1", "model": "deepseek-v4"
            }),
            patch("ai_rate_limit.wait_for_internal_ai_slot"),
            patch("network_utils.urlopen_with_local_proxy_fallback", side_effect=responses) as request,
        ):
            result = pipeline.generate_model_focus_insight("macro", focus)

        self.assertGreaterEqual(request.call_count, 1)
        self.assertTrue(
            result["focus"].get("repaired")
            or result["focus"].get("origin") == "evidence_rule"
        )
        self.assertFalse(pipeline._focus_gate_error("macro", "service", result["focus"]["analysis"], focus))
        self.assertNotIn("驱动", result["focus"]["headline"])
        self.assertIn("期间不同", result["focus"]["analysis"])
        self.assertNotIn("因果", result["focus"]["analysis"])

    def test_international_growth_empty_model_output_uses_safe_new_judgement(self):
        focus = {
            "id": "growth",
            "label": "营收同比",
            "metric": {"value": 6.4, "unit": "%"},
            "insight": "中国铁塔与中国移动保持正增长，中国联通与中国电信转负，行业并非同步扩张。",
            "items": [
                {"name": "中国铁塔", "value": 6.4},
                {"name": "中国移动", "value": 1.8},
                {"name": "中国联通", "value": -1.2},
                {"name": "中国电信", "value": -2.1},
            ],
            "regeneration_index": 1,
            "recent_insights": ["中国铁塔与中国移动保持正增长，中国联通与中国电信转负，行业并非同步扩张。"],
        }
        responses = []
        for _ in range(6):
            response = mock.MagicMock()
            response.__enter__.return_value.read.return_value = json.dumps({
                "choices": [{"message": {"content": ""}}]
            }).encode("utf-8")
            responses.append(response)

        with (
            patch("ai_config.load_ai_config", return_value={
                "api_key": "test-key", "base_url": "https://example.test/v1", "model": "deepseek-v4"
            }),
            patch("ai_rate_limit.wait_for_internal_ai_slot"),
            patch("network_utils.urlopen_with_local_proxy_fallback", side_effect=responses) as request,
        ):
            result = pipeline.generate_model_focus_insight("international", focus)

        self.assertGreaterEqual(request.call_count, 1)
        self.assertEqual(result["model"], "evidence-rule-fallback")
        self.assertEqual(result["focus"].get("origin"), "evidence_rule")
        self.assertFalse(
            pipeline._focus_gate_error("international", "growth", result["focus"]["analysis"], focus)
        )
        self.assertNotIn("Expecting value", result["focus"]["analysis"])

    def test_empty_model_payload_has_stable_nontechnical_error(self):
        with self.assertRaisesRegex(ValueError, "模型本次未返回有效内容"):
            pipeline._extract_json_payload("")

    def test_truncated_focus_json_can_be_salvaged_without_exposing_parser_error(self):
        parsed = pipeline._extract_focus_response(
            '{"headline":"增长梯队分化","analysis":"Google35.8%与Alibaba11.0%形成两层，说明增长阶段不同。'
        )

        self.assertEqual(parsed["headline"], "增长梯队分化")
        self.assertIn("Google35.8%", parsed["analysis"])

    def test_numeric_tokens_keep_full_number_when_attached_to_company_name(self):
        self.assertEqual(pipeline._numeric_tokens("Google35.8%与AWS19.7%"), {"35.8", "19.7"})

    def test_focus_gate_rejects_broken_compacted_sentence_order(self):
        focus = {
            "id": "mobile_price",
            "items": [
                {"name": "3HK", "value": 168, "low": 98, "high": 398},
                {"name": "SmarTone", "value": 239, "low": 128, "high": 498},
            ],
        }
        error = pipeline._focus_gate_error(
            "local",
            "mobile_price",
            "但两者价格带重合，意味着中，仅两家样本可比。",
            focus,
        )

        self.assertIn("句序不完整", error)
        self.assertIn(
            "句序不完整",
            pipeline._focus_gate_error(
                "local",
                "mobile_price",
                "3HK与SmarTone彼此存在差距个，这说明价格结构存在两层区隔。",
                focus,
            ),
        )
        self.assertIn(
            "句序不完整",
            pipeline._focus_gate_error(
                "local",
                "mobile_price",
                "3HK为168港元，SmarTone为239港元，价格区隔意味着中。",
                focus,
            ),
        )
        self.assertIn(
            "句序不完整",
            pipeline._focus_gate_error(
                "local",
                "mobile_price",
                "这说明价格结构存在两层，3HK为168港元且SmarTone为239港元。",
                focus,
            ),
        )

    def test_derived_count_repair_consumes_dangling_unit(self):
        repaired, changed = pipeline._repair_generated_focus_analysis(
            "头部三家相差6个，说明产品数量结构呈现分层。",
            {"items": [{"value": 27}, {"value": 24}, {"value": 21}]},
        )

        self.assertTrue(changed)
        self.assertIn("存在差距", repaired)
        self.assertNotIn("存在差距个", repaired)

    def test_overlap_prompt_exposes_admitted_range_evidence(self):
        source = Path(pipeline.__file__).read_text(encoding="utf-8")

        self.assertIn(
            '**({"analysis": item.get("analysis")} if (domain_id, focus_id) == ("local", "overlap") else {})',
            source,
        )
        self.assertIn(
            '**({"relationships": item.get("components")} if (domain_id, focus_id) == ("local", "overlap") else {})',
            source,
        )
        self.assertIn("if similarity >= 0.88:", source)

    def test_overlap_gate_rejects_cross_product_category_mixing(self):
        focus = {
            "id": "overlap",
            "metric": {"value": 1, "unit": "类重合"},
            "items": [
                {"name": "3HK", "value": 1},
                {"name": "SmarTone", "value": 1},
                {"name": "HKBN", "value": 1},
                {"name": "i-CABLE", "value": 1},
                {"name": "HGC", "value": 0},
            ],
        }

        self.assertIn(
            "家宽主体混入个人5G",
            pipeline._focus_gate_error(
                "local", "overlap",
                "3HK、SmarTone、HKBN和i-CABLE均有1类重合，说明个人5G重合集中于多数主体。",
                focus,
            ),
        )
        self.assertIn(
            "误写为区间独立",
            pipeline._focus_gate_error(
                "local", "overlap",
                "HGC为0类重合，说明HGC区间独立且价格区隔呈现两层结构。",
                focus,
            ),
        )

    def test_focus_headline_keeps_5g_term_intact(self):
        self.assertEqual(
            pipeline._normalize_fresh_focus_headline(
                "个人5G区间重合分化",
                label="同类价格重合",
                recent_headlines=[],
            ),
            "个人5G区间重合分化",
        )

    def test_relation_regeneration_tracks_title_history(self):
        source = Path(pipeline.__file__).read_text(encoding="utf-8")

        self.assertIn('manual_discovery_regeneration_title_history', source)
        self.assertIn("跨库标题与最近版本过于相似", source)

    def test_cloud_profit_gate_rejects_derived_sample_count(self):
        evidence = pipeline._analysis_input_snapshot()
        focus = next(
            focus
            for domain in evidence["domains"] if domain["id"] == "cloud"
            for focus in domain["focuses"] if focus["id"] == "profit"
        )
        error = pipeline._focus_gate_error(
            "cloud",
            "profit",
            "AWS经营利润45606百万美元，腾讯代理分部毛利16358百万美元；口径不同不能等同排名，七家中仅六家有可比数值。",
            focus,
        )

        self.assertIn("自行统计了样本家数", error)

    def test_final_grounded_repair_is_fresh_and_gated(self):
        evidence = pipeline._analysis_input_snapshot()
        focus = next(
            focus
            for domain in evidence["domains"] if domain["id"] == "cloud"
            for focus in domain["focuses"] if focus["id"] == "investment"
        )
        first = pipeline._final_grounded_focus_repair(
            "cloud", focus, regeneration_index=1, recent_insights=[]
        )
        second = pipeline._final_grounded_focus_repair(
            "cloud", focus, regeneration_index=2, recent_insights=[first]
        )

        self.assertTrue(first)
        self.assertTrue(second)
        self.assertNotEqual(first, second)
        self.assertFalse(pipeline._focus_gate_error("cloud", "investment", first, focus))
        self.assertFalse(pipeline._focus_gate_error("cloud", "investment", second, focus))

    def test_focus_regeneration_merges_one_validated_insight(self):
        evidence = pipeline._analysis_input_snapshot()
        domain = next(item for item in evidence["domains"] if item["id"] == "international")
        focus = next(item for item in domain["focuses"] if item["id"] == "ebitda")
        scoped_summary = next(
            item for item in pipeline._deterministic_domain_summaries(evidence)
            if item["domain"] == "international"
        )
        scoped_summary["focuses"] = [
            item for item in scoped_summary["focuses"] if item["id"] == "ebitda"
        ]
        scoped_summary["focuses"][0]["analysis"] = pipeline._compact_grounded_focus_analysis(
            "international", focus
        )
        scoped_summary["focuses"][0]["headline"] = "经营造血能力分层"
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "analysis.json"
            path.write_text("{}", encoding="utf-8")
            with (
                patch("executive_intelligence_pipeline._analysis_input_snapshot", return_value=evidence),
                patch("executive_intelligence_pipeline.generate_model_focus_insight", return_value={
                    "model": "test-model",
                    "focus": scoped_summary["focuses"][0],
                }) as generate,
            ):
                progress = []
                result = pipeline.regenerate_model_focus_summary(
                    "international", "ebitda", path=path, progress=progress.append
                )

            saved = json.loads(path.read_text(encoding="utf-8"))["model_analysis"]
            self.assertTrue(result["ok"])
            self.assertEqual(result["focus"], "ebitda")
            self.assertEqual(saved["manual_focus_regeneration"]["focus"], "ebitda")
            self.assertEqual(
                saved["manual_focus_regeneration_history"]["international.ebitda"][-1],
                scoped_summary["focuses"][0]["analysis"],
            )
            self.assertEqual(saved["manual_focus_regeneration_counts"]["international.ebitda"], 1)
            saved_focus = next(
                item for item in next(
                    summary for summary in saved["summaries"] if summary["domain"] == "international"
                )["focuses"] if item["id"] == "ebitda"
            )
            self.assertEqual(saved_focus["headline"], "经营造血能力分层")
            self.assertEqual(len(saved["summaries"]), 4)
            self.assertEqual(generate.call_args.kwargs["temperature"], 0.25)
            self.assertEqual(progress[0], "正在读取当前证据")
            self.assertEqual(progress[-1], "证据校验通过，正在返回洞察")

    def test_current_focus_regeneration_is_registered_and_persisted(self):
        evidence = pipeline._analysis_input_snapshot()
        revenue = next(
            focus
            for domain in evidence["domains"] if domain["id"] == "local"
            for focus in domain["focuses"] if focus["id"] == "revenue"
        )
        generated_focus = next(
            focus
            for summary in pipeline._deterministic_domain_summaries(evidence)
            if summary["domain"] == "local"
            for focus in summary["focuses"]
            if focus["id"] == "revenue"
        )
        self.assertFalse(pipeline._focus_gate_error("local", "revenue", generated_focus["analysis"], revenue))
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "analysis.json"
            path.write_text("{}", encoding="utf-8")
            with (
                patch("executive_intelligence_pipeline._analysis_input_snapshot", return_value=evidence),
                patch("executive_intelligence_pipeline.generate_model_focus_insight", return_value={
                    "model": "test-model",
                    "focus": generated_focus,
                }),
            ):
                result = pipeline.regenerate_model_focus_summary("local", "revenue", path=path)
            saved = json.loads(path.read_text(encoding="utf-8"))["model_analysis"]
        saved_revenue = next(
            focus
            for summary in saved["summaries"] if summary["domain"] == "local"
            for focus in summary["focuses"] if focus["id"] == "revenue"
        )
        self.assertTrue(result["ok"])
        self.assertEqual(saved_revenue["headline"], generated_focus["headline"])
        self.assertEqual(saved_revenue["analysis"], generated_focus["analysis"])

    def test_focus_regeneration_does_not_merge_stale_unrelated_ai_copy(self):
        evidence = pipeline._analysis_input_snapshot()
        evidence_hash = pipeline._content_hash(evidence)
        generated_focus = next(
            focus
            for summary in pipeline._deterministic_domain_summaries(evidence)
            if summary["domain"] == "local"
            for focus in summary["focuses"]
            if focus["id"] == "revenue"
        )
        generated_focus = {
            **generated_focus,
            "headline": "经营资源底盘分层",
        }
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "analysis.json"
            path.write_text(json.dumps({
                "model_analysis": {
                    "evidence_hash": evidence_hash,
                    "insight_format": pipeline.INSIGHT_FORMAT_VERSION,
                    "summaries": [{
                        "domain": "local",
                        "headline": "旧版",
                        "analysis": "旧口径共161项。",
                        "focuses": [{"id": "scale", "headline": "旧版", "analysis": "旧口径161项。"}],
                    }],
                    "discoveries": [],
                }
            }, ensure_ascii=False), encoding="utf-8")
            with (
                patch("executive_intelligence_pipeline._analysis_input_snapshot", return_value=evidence),
                patch("executive_intelligence_pipeline.generate_model_focus_insight", return_value={
                    "model": "test-model",
                    "focus": generated_focus,
                }),
            ):
                result = pipeline.regenerate_model_focus_summary("local", "revenue", path=path)

            saved = json.loads(path.read_text(encoding="utf-8"))["model_analysis"]
            serialized = json.dumps(saved["summaries"], ensure_ascii=False)
            self.assertTrue(result["ok"])
            self.assertNotIn("旧口径共161项", serialized)
            self.assertFalse(any(
                focus.get("id") == "scale"
                for summary in saved["summaries"]
                for focus in summary.get("focuses") or []
            ))
            self.assertIn("经营资源底盘分层", serialized)

    def test_analysis_evidence_excludes_rendered_ai_relations(self):
        rendered = {
            "domains": [],
            "relations": [{
                "from": "local",
                "to": "cloud",
                "title": "上一轮AI发现",
                "detail": "不得反馈进下一轮证据哈希。",
                "origin": "ai",
            }],
        }
        with patch(
            "cmhk.intelligence.executive.build_executive_intelligence_snapshot",
            return_value=rendered,
        ):
            evidence = pipeline._analysis_input_snapshot()

        self.assertEqual(evidence, {"domains": [], "relations": []})

    def test_scheduled_refresh_retries_then_logs_locally_and_finalizes_task(self):
        failed = {
            "ok": False,
            "status": "completed_with_fallback",
            "agent_run_id": "agent-test",
            "failed_domains": ["cloud"],
            "duration_ms": 10,
        }
        with (
            patch("executive_intelligence_pipeline.run_pipeline", return_value=failed) as run,
            patch("executive_intelligence_pipeline.time.sleep") as sleep,
            patch("executive_intelligence_pipeline._task_event"),
            patch("executive_intelligence_pipeline._finalize_refresh_task") as finalize,
            patch.dict("os.environ", {"CMHK_INTELLIGENCE_RETRY_DELAYS": "0,0"}),
        ):
            result = pipeline.run_pipeline_with_recovery(
                agent_run_id="agent-test",
                task_run_id="refresh-test",
                parent_crawl_run_id="crawl-test",
                max_attempts=3,
            )

        self.assertFalse(result["ok"])
        self.assertEqual(result["attempts"], 3)
        self.assertEqual(run.call_count, 3)
        self.assertEqual(sleep.call_count, 2)
        self.assertEqual(result["notification_policy"], "local_log_only")
        self.assertFalse(finalize.call_args.kwargs["ok"])

    def test_scheduled_refresh_accepts_fully_gated_fallback_after_retries(self):
        fallback = {
            "ok": False,
            "status": "completed_with_fallback",
            "agent_run_id": "agent-test",
            "failed_domains": [],
            "duration_ms": 10,
            "model_analysis": {
                "fallback_used": True,
                "focuses_expected": 17,
                "focuses_passed": 17,
            },
            "pages_publish": {"ok": True, "status": "verified"},
        }
        with (
            patch("executive_intelligence_pipeline.run_pipeline", return_value=fallback) as run,
            patch("executive_intelligence_pipeline.time.sleep"),
            patch("executive_intelligence_pipeline._task_event"),
            patch("executive_intelligence_pipeline._finalize_refresh_task") as finalize,
            patch.dict("os.environ", {"CMHK_INTELLIGENCE_RETRY_DELAYS": "0,0"}),
        ):
            result = pipeline.run_pipeline_with_recovery(
                agent_run_id="agent-test",
                task_run_id="refresh-test",
                parent_crawl_run_id="crawl-test",
                max_attempts=3,
            )

        self.assertEqual(run.call_count, 3)
        self.assertTrue(result["ok"])
        self.assertTrue(result["degraded"])
        self.assertTrue(result["recovery_exhausted"])
        self.assertEqual(result["status"], "completed_with_fallback")
        self.assertTrue(finalize.call_args.kwargs["ok"])

    def test_refresh_task_persists_parent_crawl_run_id(self):
        with (
            patch("cmhk.crawl.run_registry.start_crawl_run", return_value={
                "crawl_run_id": "refresh-test",
                "stream_log_path": "/tmp/refresh-test.jsonl",
            }) as start,
            patch("cmhk.crawl.run_registry.append_crawl_run_event"),
        ):
            task = pipeline._start_refresh_task(
                agent_run_id="agent-test",
                parent_crawl_run_id="crawl-parent",
            )

        self.assertEqual(task["crawl_run_id"], "refresh-test")
        self.assertEqual(start.call_args.kwargs["parent_crawl_run_id"], "crawl-parent")

    def test_watchdog_launches_one_recovery_for_unmatched_daily_crawl(self):
        scheduled = {
            "crawl_run_id": "crawl-0300",
            "trigger": "定时爬虫",
            "run_status": "completed",
            "completed_at_hkt": "2026-08-04T03:30:00+08:00",
            "curation": {"agent_run_id": "agent-0300"},
        }
        with (
            patch("cmhk.crawl.run_registry.load_index", return_value=[scheduled]),
            patch("executive_intelligence_pipeline._read_json", side_effect=[{}, {}]),
            patch("executive_intelligence_pipeline.launch_pipeline_async", return_value={
                "ok": True, "task_run_id": "refresh-recovery"
            }) as launch,
            patch("executive_intelligence_pipeline._atomic_write_json") as write,
        ):
            result = pipeline.monitor_scheduled_refresh_health(
                datetime.fromisoformat("2026-08-04T06:00:00+08:00")
            )

        self.assertEqual(result["status"], "recovery_launched")
        launch.assert_called_once()
        self.assertEqual(result["notification_policy"], "local_log_only")
        write.assert_called_once()

    def test_four_database_refresh_has_no_feishu_message_sender(self):
        source = Path(pipeline.__file__).read_text(encoding="utf-8")
        self.assertNotIn("TARGET_CHAT_IDS", source)
        self.assertNotIn("_lark_api", source)
        self.assertNotIn("/im/v1/messages", source)

    def test_ai_analysis_rejects_fact_whose_basis_denies_metric_amount(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            facts = Path(tmp) / "facts.jsonl"
            facts.write_text(
                json.dumps(
                    {
                        "company": "Microsoft Azure",
                        "metric": "资本开支",
                        "value": "20.1亿美元",
                        "basis": "资本性资产购置同比增加20.1亿美元，无资本开支总额。",
                        "decision": "accepted",
                        "status": "ok",
                        "entity_supported": True,
                        "metric_supported": True,
                        "value_supported": True,
                        "quality_score": 0.95,
                        "confidence": 0.95,
                        "source_tier": "official",
                        "sources": ["https://www.microsoft.com/investor/reports/ar25/index.html"],
                    },
                    ensure_ascii=False,
                )
                + "\n",
                encoding="utf-8",
            )
            payload = pipeline.build_ai_analysis(agent_run_id="audit", verified_facts_path=facts)
        self.assertEqual(payload["domain_counts"]["cloud"], 0)

    def test_financial_report_link_discovery_keeps_official_report_links(self):
        html = b'''<html><body>
        <a href="/reports/2026-q1.pdf">2026 First Quarter Results</a>
        <a href="/about">About us</a>
        <a href="https://cdn.example.com/ar2025.pdf" title="2025 Annual Report">View</a>
        </body></html>'''
        links = crawl.extract_financial_report_links(html, "text/html", "https://ir.example.com/index")
        self.assertEqual([item["url"] for item in links], [
            "https://ir.example.com/reports/2026-q1.pdf",
            "https://cdn.example.com/ar2025.pdf",
        ])

    def test_financial_report_link_discovery_uses_sibling_title_for_download_icon(self):
        html = b'''<html><body><div>
        <div>2026 Interim Results Announcement</div>
        <a href="/assets/e-2026.07.29-results.pdf"><img alt="download"></a>
        </div></body></html>'''
        links = crawl.extract_financial_report_links(html, "text/html", "https://ir.example.com/results/")
        self.assertEqual(links[0]["title"], "2026 Interim Results Announcement")
        self.assertEqual(links[0]["url"], "https://ir.example.com/assets/e-2026.07.29-results.pdf")

    def test_cloud_investor_relations_domains_are_ranked_official(self):
        for url in (
            "https://ir.aboutamazon.com/quarterly-results/default.aspx",
            "https://www.microsoft.com/en-us/Investor/earnings",
            "https://abc.xyz/investor/",
            "https://www.alibabagroup.com/en-US/ir-financial-reports-quarterly-results",
            "https://www.tencent.com/investors/financial-reports/",
            "https://www.huawei.com/en/annual-report",
            "https://investor.oracle.com/financials/default.aspx",
        ):
            self.assertEqual(_source_rank([url]), (1.0, "official"), url)

    def test_crawl_configuration_can_include_tagged_monitor_rows_after_row_34(self):
        headers = ["项目名称", "数据板块", "对象/内部大类", "指标包/数据类", "具体需要收集的数据", "来源/系统", "robots.txt链接", "信息获取渠道", "更新频率"]
        values = [headers]
        values.append(["竞争对手与行业情报监测", "本地", "HKBN", "财报", "收入", "https://example.com/hkbn", "", "官网", "每天 03:00"])
        values.extend([[""] * 9 for _ in range(32)])
        values.append(["经营趋势预测与沙盘推演", "内部", "财务", "经营", "收入", "内部", "", "ETL", "月度"])
        values.extend([[""] * 9 for _ in range(16)])
        values.append(["竞争对手与行业情报监测", "云厂商", "AWS", "财报经营指标", "云收入", "https://example.com/aws", "", "官方IR", "每天 03:00"])
        payload = {"data": {"valueRange": {"values": values}}}
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "sheet.json"
            path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
            with patch.object(crawl, "SPREADSHEET_JSON", path):
                rows = crawl.parse_latest_sheet()
        self.assertEqual([row["object"] for row in rows], ["HKBN", "AWS"])
        self.assertGreater(int(rows[-1]["row"]), 34)

    def test_ai_analysis_only_publishes_agent_accepted_supported_facts(self):
        accepted = {
            "company": "中国移动",
            "metric": "资本开支",
            "value": "资本开支同比下降。",
            "basis": "官方一季报",
            "status": "ok",
            "decision": "accepted",
            "entity_supported": True,
            "metric_supported": True,
            "value_supported": True,
            "quality_score": 0.96,
            "confidence": 0.95,
            "source_tier": "official",
            "sources": ["https://example.com/official.pdf"],
        }
        rejected = {**accepted, "company": "中国电信", "decision": "rejected"}
        unsupported = {**accepted, "company": "中国联通", "value_supported": False}
        no_source = {**accepted, "company": "中国铁塔", "sources": []}
        with tempfile.TemporaryDirectory() as temp_dir:
            source = Path(temp_dir) / "facts.jsonl"
            source.write_text(
                "\n".join(json.dumps(item, ensure_ascii=False) for item in (accepted, rejected, unsupported, no_source)),
                encoding="utf-8",
            )
            payload = pipeline.build_ai_analysis(agent_run_id="run-test", verified_facts_path=source)
        self.assertEqual(payload["domain_counts"]["mainland"], 1)
        self.assertEqual(payload["domains"]["mainland"][0]["company"], "中国移动")
        self.assertEqual(payload["domain_counts"]["international"], 0)

    def test_ai_analysis_publish_is_idempotent_for_same_agent_output(self):
        fact = {
            "company": "HKBN", "metric": "资费", "value": "月费保持不变。", "basis": "官方网页",
            "status": "ok", "decision": "accepted", "entity_supported": True, "metric_supported": True,
            "value_supported": True, "quality_score": 0.99, "confidence": 0.98, "source_tier": "official",
            "sources": ["https://example.com/hkbn"],
        }
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source = root / "facts.jsonl"
            output = root / "analysis.json"
            source.write_text(json.dumps(fact, ensure_ascii=False) + "\n", encoding="utf-8")
            first = pipeline.publish_ai_analysis(agent_run_id="same-run", verified_facts_path=source, output_path=output)
            first_mtime = output.stat().st_mtime_ns
            second = pipeline.publish_ai_analysis(agent_run_id="same-run", verified_facts_path=source, output_path=output)
        self.assertTrue(first["changed"])
        self.assertFalse(second["changed"])
        self.assertEqual(first_mtime, output.stat().st_mtime_ns if output.exists() else first_mtime)

    def test_domain_sidecars_publish_only_official_agent_facts(self):
        analysis = {
            "agent_run_id": "run-official",
            "generated_at_hkt": "2026-08-04T12:00:00+08:00",
            "domains": {
                "local": [{"company": "HKBN", "source_tier": "official", "source_url": "https://example.com/hkbn"}],
                "international": [{"company": "Verizon", "source_tier": "official", "source_url": "https://example.com/verizon"}],
                "mainland": [{"company": "中国移动", "source_tier": "media", "source_url": "https://example.com/media"}],
                "cloud": [{"company": "AWS", "source_tier": "official", "source_url": "https://example.com/aws"}],
                "macro": [],
            },
        }
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            paths = {domain: root / f"{domain}.json" for domain in analysis["domains"]}
            result = pipeline.publish_domain_fact_sidecars(analysis, output_paths=paths)
            local = json.loads(paths["local"].read_text(encoding="utf-8"))
            international = json.loads(paths["international"].read_text(encoding="utf-8"))
            mainland = json.loads(paths["mainland"].read_text(encoding="utf-8"))
            cloud = json.loads(paths["cloud"].read_text(encoding="utf-8"))
        self.assertEqual(result["local"]["facts"], 1)
        self.assertEqual(local["facts"][0]["company"], "HKBN")
        self.assertEqual(international["facts"][0]["company"], "Verizon")
        self.assertEqual(mainland["facts"], [])
        self.assertEqual(cloud["facts"][0]["company"], "AWS")

    def test_domain_sidecar_does_not_claim_change_for_new_run_id_only(self):
        facts = [{
            "company": "AWS",
            "source_tier": "official",
            "source_url": "https://example.com/aws",
            "analysis": "same fact",
        }]
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            paths = {domain: root / f"{domain}.json" for domain in pipeline.FACT_DOMAIN_IDS}
            first = {
                "agent_run_id": "run-one",
                "generated_at_hkt": "2026-08-25T01:00:00+08:00",
                "domains": {domain: facts if domain == "cloud" else [] for domain in pipeline.FACT_DOMAIN_IDS},
            }
            second = {
                **first,
                "agent_run_id": "run-two",
                "generated_at_hkt": "2026-08-25T02:00:00+08:00",
            }
            pipeline.publish_domain_fact_sidecars(first, output_paths=paths)
            result = pipeline.publish_domain_fact_sidecars(second, output_paths=paths)
        self.assertFalse(result["cloud"]["changed"])
        self.assertFalse(result["cloud"]["published"])

    def test_source_recrawl_requires_live_readback_for_every_ui_domain(self):
        completed = mock.Mock(
            returncode=0,
            stdout=json.dumps({
                "official_urls": 4,
                "retrieved": 3,
                "failed": 1,
                "domains": {
                    "local": {"retrieved": 1},
                    "international": {"retrieved": 1},
                    "mainland": {"retrieved": 1},
                    "cloud": {"retrieved": 0},
                },
            }),
            stderr="",
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            script = root / "scripts" / "crawl_requested_overview_010304_official_sources.py"
            output = root / "agent_knowledge" / "requested_overview_010304_2016_2025" / "official_source_recrawl.json"
            script.parent.mkdir(parents=True)
            output.parent.mkdir(parents=True)
            script.write_text("", encoding="utf-8")
            output.write_text("{}", encoding="utf-8")
            with (
                patch.object(pipeline, "ROOT", root),
                patch("executive_intelligence_pipeline.subprocess.run", return_value=completed),
            ):
                with self.assertRaisesRegex(RuntimeError, "cloud"):
                    pipeline._run_overview_source_recrawl()

    def test_database_gate_rejects_unverified_local_rows(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "local.json"
            path.write_text(json.dumps([{"verification_count": 1, "source_url": "https://example.com"}]), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "双重验证"):
                pipeline.validate_database("local", path)

    def test_database_gate_rejects_large_row_count_regression(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            old = root / "old.json"
            new = root / "new.json"
            row = {"verification_status": "official_match", "period_end": "2026-03-31", "value": 1}
            old.write_text(json.dumps({"rows": [row] * 100}), encoding="utf-8")
            new.write_text(json.dumps({"rows": [row] * 90}), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "行数降级"):
                pipeline.validate_database("international", new, old)

    def test_model_analysis_gate_rejects_numbers_not_present_in_evidence(self):
        evidence = {
            "domains": [
                {
                    "id": domain,
                    "focuses": ([{"items": [{"value": 10, "source_url": "https://example.com/source"}]}]
                                if domain == "local" else []),
                    "agent_verified_facts": [],
                }
                for domain in pipeline.UI_DOMAIN_IDS
            ]
        }
        summaries = [
            {
                "domain": domain,
                "headline": "保持观察",
                "analysis": "现有证据显示变化。" if domain != "local" else "现有10项证据显示变化。",
                "risk": "口径不同。",
                "source_urls": ["https://example.com/source"] if domain == "local" else [],
            }
            for domain in pipeline.UI_DOMAIN_IDS
        ]
        pipeline._validate_model_summaries(summaries, evidence)
        summaries[1]["analysis"] = "出现99项变化。"
        with self.assertRaisesRegex(ValueError, "输入之外的数字"):
            pipeline._validate_model_summaries(summaries, evidence)

    def test_model_analysis_gate_rejects_unseen_source_url(self):
        evidence = {
            "domains": [
                {"id": domain, "focuses": [], "agent_verified_facts": []}
                for domain in pipeline.UI_DOMAIN_IDS
            ]
        }
        summaries = [
            {"domain": domain, "headline": "观察", "analysis": "已有变化。", "risk": "谨慎。", "source_urls": []}
            for domain in pipeline.UI_DOMAIN_IDS
        ]
        summaries[-1]["source_urls"] = ["https://invented.example.com"]
        with self.assertRaisesRegex(ValueError, "输入之外的来源"):
            pipeline._validate_model_summaries(summaries, evidence)

    def test_model_analysis_requires_every_focus_summary(self):
        evidence = {
            "domains": [
                {
                    "id": domain,
                    "focuses": [
                        {"id": f"{domain}-a", "metric": {"value": 1}, "items": []},
                        {"id": f"{domain}-b", "metric": {"value": 2}, "items": []},
                    ],
                    "agent_verified_facts": [],
                }
                for domain in ("local", "international", "cloud", "macro")
            ]
        }
        summaries = [
            {
                "domain": domain,
                "headline": "观察",
                "analysis": "证据已更新。",
                "risk": "保持口径边界。",
                "source_urls": [],
                "focuses": [
                    {"id": f"{domain}-a", "analysis": "1项竞争位置变化表明收入结构分层主要来自客户组合差异。", "risk": "保持边界。", "source_urls": []},
                    {"id": f"{domain}-b", "analysis": "2项竞争差距扩大说明客户结构差异并非同步变化。", "risk": "保持边界。", "source_urls": []},
                ],
            }
            for domain in ("local", "international", "cloud", "macro")
        ]
        validated = pipeline._validate_model_summaries(summaries, evidence)
        self.assertEqual(sum(len(item["focuses"]) for item in validated), 8)
        summaries[0]["focuses"].pop()
        with self.assertRaisesRegex(ValueError, "分类不完整"):
            pipeline._validate_model_summaries(summaries, evidence)

    def test_model_analysis_requires_every_entity_and_known_component_labels(self):
        evidence = {
            "domains": [
                {
                    "id": domain,
                    "focuses": [{
                        "id": f"{domain}-focus",
                        "items": [{
                            "name": f"{domain}-entity",
                            "value": 10,
                            "components": [{"label": "具体项目", "value": 10}],
                            "source_url": "https://example.com/source",
                        }],
                    }],
                    "agent_verified_facts": [],
                }
                for domain in ("local", "international", "cloud", "macro")
            ]
        }
        summaries = [
            {
                "domain": domain,
                "headline": "明细已更新",
                "analysis": "具体结构发生变化。",
                "risk": "保持口径边界。",
                "source_urls": ["https://example.com/source"],
                "focuses": [{
                    "id": f"{domain}-focus",
                    "analysis": "10项证据高度集中，表明产品结构差异主要来自少数核心项目。",
                    "risk": "保持边界。",
                    "source_urls": ["https://example.com/source"],
                    "entities": [{
                        "name": f"{domain}-entity",
                        "headline": "组成清晰",
                        "analysis": "具体项目包含10项，结构集中。",
                        "risk": "保持边界。",
                        "evidence_labels": ["具体项目"],
                        "source_urls": ["https://example.com/source"],
                    }],
                }],
            }
            for domain in ("local", "international", "cloud", "macro")
        ]
        validated = pipeline._validate_model_summaries(summaries, evidence)
        self.assertEqual(sum(len(focus["entities"]) for item in validated for focus in item["focuses"]), 4)
        summaries[0]["focuses"][0]["entities"][0]["evidence_labels"] = ["未知项目"]
        with self.assertRaisesRegex(ValueError, "未知明细"):
            pipeline._validate_model_summaries(summaries, evidence)

    def test_model_analysis_rejects_entity_ui_filler(self):
        evidence = {
            "domains": [{
                "id": domain,
                "focuses": [{"id": "focus", "metric": {"value": 10}, "items": [{
                    "name": "实体", "value": 10, "components": [{"label": "项目", "value": 10}],
                }]}],
                "agent_verified_facts": [],
            } for domain in ("local", "international", "cloud", "macro")]
        }
        summaries = [{
            "domain": domain, "headline": "观察", "analysis": "已有变化。", "risk": "谨慎。", "source_urls": [],
            "focuses": [{
                "id": "focus", "analysis": "10项竞争位置变化表明收入结构分层主要来自客户组合差异。", "risk": "谨慎。", "source_urls": [],
                "entities": [{
                    "name": "实体", "headline": "观察", "analysis": "数据库内按排名展示。", "risk": "谨慎。",
                    "evidence_labels": ["项目"], "source_urls": [],
                }],
            }],
        } for domain in ("local", "international", "cloud", "macro")]
        with self.assertRaisesRegex(ValueError, "界面废话"):
            pipeline._validate_model_summaries(summaries, evidence)

    def test_all_sixteen_focuses_require_numbers_and_deep_interpretation(self):
        focus_ids = ("scale", "track", "price", "overlap")
        evidence = {
            "domains": [
                {
                    "id": domain,
                    "focuses": [
                        {"id": focus_id, "metric": {"value": index + 1}, "items": []}
                        for index, focus_id in enumerate(focus_ids)
                    ],
                    "agent_verified_facts": [],
                }
                for domain in ("local", "international", "cloud", "macro")
            ]
        }
        summaries = [
            {
                "domain": domain,
                "headline": "竞争位置变化",
                "analysis": "四项证据显示竞争位置变化。",
                "risk": "保持口径边界。",
                "source_urls": [],
                "focuses": [
                    {
                        "id": focus_id,
                        "analysis": f"{index + 1}项证据显示竞争差距主要来自收入与客户结构分层。",
                        "risk": "保持口径边界。",
                        "source_urls": [],
                        "entities": [],
                    }
                    for index, focus_id in enumerate(focus_ids)
                ],
            }
            for domain in ("local", "international", "cloud", "macro")
        ]

        validated = pipeline._validate_model_summaries(summaries, evidence)
        self.assertEqual(sum(len(item["focuses"]) for item in validated), 16)
        summaries[2]["focuses"][1]["analysis"] = "该指标用于展示变化。"
        with self.assertRaisesRegex(ValueError, "cloud.track"):
            pipeline._validate_model_summaries(summaries, evidence)

    def test_focus_gate_allows_two_sentences_but_rejects_action_advice(self):
        evidence_focus = {"id": "market", "metric": {"value": 3428.5}, "items": []}
        analysis = "移动连接3428.5万已接近饱和。该水平表明增长受渗透结构约束。"
        self.assertEqual(pipeline._focus_gate_error("macro", "market", analysis, evidence_focus), "")

        advised = "移动连接3428.5万已接近饱和，建议优先关注存量客户。"
        self.assertIn("行动建议", pipeline._focus_gate_error("macro", "market", advised, evidence_focus))

        subtle_advice = "移动连接3428.5万反映市场趋于饱和，应更关注存量价值。"
        self.assertIn("行动建议", pipeline._focus_gate_error("macro", "market", subtle_advice, evidence_focus))

        shallow = "移动连接3428.5万显示用户规模领先，市场分化明显。"
        self.assertIn("结构、驱动或可比性", pipeline._focus_gate_error("macro", "market", shallow, evidence_focus))

    def test_focus_gate_accepts_not_equal_as_a_comparability_explanation(self):
        evidence_focus = {
            "id": "scale",
            "metric": {"value": 84},
            "items": [{"name": "HKBN", "value": 27, "record_count": 59, "component_count": 27}],
        }
        analysis = "HKBN有27个可区分方案；HKBN的59条记录去重后为27个，记录密度不等于产品选择更多。"

        self.assertEqual(pipeline._focus_gate_error("local", "scale", analysis, evidence_focus), "")

    def test_scoped_model_identity_is_restored_before_evidence_repair(self):
        raw = [{"domain": "", "focuses": [{"id": "", "analysis": "内容"}]}]
        pinned = pipeline._pin_scoped_model_identity(raw, "local", "scale")
        self.assertEqual(pinned[0]["domain"], "local")
        self.assertEqual(pinned[0]["focuses"][0]["id"], "scale")
        self.assertEqual(raw[0]["domain"], "")

    def test_current_fallbacks_are_deep_conclusions_without_advice(self):
        evidence = pipeline._analysis_input_snapshot()
        checked = 0
        for domain in evidence["domains"]:
            for focus in domain["focuses"]:
                analysis = pipeline._compact_grounded_focus_analysis(domain["id"], focus)
                self.assertEqual(
                    pipeline._focus_gate_error(domain["id"], focus["id"], analysis, focus),
                    "",
                    f"{domain['id']}.{focus['id']}: {analysis}",
                )
                self.assertFalse(pipeline._contains_action_advice(analysis))
                checked += 1
        self.assertEqual(checked, 15)

    def test_local_full_year_judgement_excludes_partial_year_cmhk_value(self):
        focus = {
            "id": "revenue",
            "items": [
                {"name": "HKT", "value": 36553, "unit": "百万港元", "period": "FY2025"},
                {"name": "3HK", "value": 5448, "unit": "百万港元", "period": "FY2025"},
                {"name": "CMHK", "value": 4544.6, "unit": "百万港元", "period": "2026首7月"},
            ],
            "metric": {"value": 36553, "unit": "百万港元"},
        }

        analysis = pipeline._compact_grounded_focus_analysis("local", focus)

        self.assertIn("HKT FY2025营收36553百万港元，3HK5448百万港元", analysis)
        self.assertNotIn("CMHK", analysis)

    def test_focus_gate_rejects_unfilled_difference_unit(self):
        focus = {
            "items": [
                {"name": "AWS", "value": 45606},
                {"name": "Azure", "value": 44589},
            ]
        }
        analysis = (
            "AWS与Azure经营利润分别为45606百万美元和44589百万美元，存在差距百万美元，"
            "这意味着两家形成双强竞争。"
        )

        self.assertIn("句序不完整", pipeline._focus_gate_error("cloud", "profit", analysis, focus))

    def test_mobile_price_gate_rejects_false_no_overlap_claim(self):
        focus = {
            "metric": {"value": 168, "unit": "港元/月"},
            "items": [
                {"name": "3HK", "value": 168, "low": 124, "high": 228},
                {"name": "SmarTone", "value": 239, "low": 159, "high": 549},
            ],
        }
        analysis = "3HK为168港元，SmarTone为239港元；价格区间未重合，说明竞争主要来自定位不同。"
        self.assertIn(
            "与输入价格区间矛盾",
            pipeline._focus_gate_error("local", "mobile_price", analysis, focus),
        )

    def test_focus_analysis_repair_removes_only_derived_difference(self):
        analysis = (
            "中国移动11.41%与中国电信11.18%仅差0.23个百分点，"
            "说明两者资本投入占比相近，并非形成明显分层。"
        )
        repaired, changed = pipeline._repair_generated_focus_analysis(
            analysis,
            {
                "metric": {"value": 13.28},
                "items": [{"value": 11.41}, {"value": 11.18}],
            },
        )

        self.assertTrue(changed)
        self.assertNotIn("0.23", repaired)
        self.assertIn("11.41%", repaired)
        self.assertIn("11.18%", repaired)
        self.assertIn("存在差距", repaired)

    def test_focus_analysis_repair_trims_redundant_disclosure_tail(self):
        analysis = (
            "仅3HK与SmarTone披露个人5G月费，样本限于两家；"
            "3HK价格带124–228与SmarTone 159–399在159–228区间重合，"
            "说明中位价168与239的差异主要来自SmarTone向上延伸至399，而非基础档分层，"
            "HKBN等三家未披露，不能等同市场全貌。"
        )
        repaired, changed = pipeline._repair_generated_focus_analysis(
            analysis,
            {
                "metric": {"value": 168},
                "items": [
                    {"name": "3HK", "value": 168, "detail": "价格带124–228"},
                    {"name": "SmarTone", "value": 239, "detail": "价格带159–399"},
                ],
            },
        )

        self.assertTrue(changed)
        self.assertLessEqual(len(repaired), pipeline.MAX_FOCUS_INSIGHT_CHARS)
        self.assertNotIn("HKBN等三家未披露", repaired)
        self.assertIn("价格带124–228", repaired)

    def test_overlong_ai_analysis_is_compacted_to_strongest_grounded_clauses(self):
        focus = {
            "metric": {"value": 35.8},
            "items": [
                {"name": "Google", "value": 35.8},
                {"name": "Oracle", "value": 23.9},
                {"name": "AWS", "value": 19.7},
                {"name": "Alibaba", "value": 11.0},
            ],
        }
        analysis = (
            "Google35.8%、Oracle23.9%、AWS19.7%、Alibaba11.0%均为直接披露口径，"
            "四家形成增长梯队，说明同口径厂商处于不同扩张阶段，"
            "此外还有代理分部口径不能混入排名，更多披露边界也不应被忽略，"
            "这段冗长说明只用于模拟模型把同一口径边界重复解释多次的常见异常。"
        )
        compacted, changed = pipeline._compact_generated_focus_analysis(
            "cloud", "growth", analysis, focus, focus
        )

        self.assertTrue(changed)
        self.assertLessEqual(len(compacted), pipeline.MAX_FOCUS_INSIGHT_CHARS)
        self.assertEqual(pipeline._focus_gate_error("cloud", "growth", compacted, focus), "")
        self.assertIn("35.8%", compacted)
        self.assertIn("增长梯队", compacted)

    def test_focus_headline_compacts_whole_words_instead_of_cutting_mid_phrase(self):
        headline = pipeline._normalize_fresh_focus_headline(
            "中国联通资本投入强度与移动电信分化",
            label="资本投入占比",
            recent_headlines=[],
        )

        self.assertEqual(headline, "联通投入强度与移动电信分化")
        self.assertFalse(headline.endswith("分"))

    def test_numeric_anchor_repair_keeps_ai_judgement_but_does_not_rescue_filler(self):
        evidence = {"domains": [{
            "id": "macro",
            "focuses": [{
                "id": "market",
                "metric": {"label": "移动服务订户及连接", "value": 3428.5, "unit": "万"},
            }],
        }]}
        raw = [{"domain": "macro", "focuses": [{
            "id": "market",
            "analysis": "市场饱和压力表明连接增长已受结构约束。",
        }]}]
        repaired = pipeline._repair_focus_numeric_anchors(raw, evidence)
        self.assertIn("3428.5万", repaired[0]["focuses"][0]["analysis"])
        self.assertTrue(repaired[0]["focuses"][0]["numeric_anchor_repaired"])

        filler = [{"domain": "macro", "focuses": [{"id": "market", "analysis": "该指标用于展示市场情况。"}]}]
        unchanged = pipeline._repair_focus_numeric_anchors(filler, evidence)
        self.assertNotIn("3428.5", unchanged[0]["focuses"][0]["analysis"])

    def test_focus_insight_is_repaired_to_one_short_grounded_sentence(self):
        evidence = {"domains": [{
            "id": "macro",
            "focuses": [{
                "id": "market",
                "metric": {"label": "移动连接", "value": 3428.5, "unit": "万"},
                "items": [],
            }],
        }]}
        raw = [{"domain": "macro", "focuses": [{
            "id": "market",
            "analysis": "移动连接达到3428.5万，市场饱和压力上升。新增空间收窄。该指标值得关注。",
        }]}]

        repaired = pipeline._repair_focus_conciseness(raw, evidence)
        analysis = repaired[0]["focuses"][0]["analysis"]
        self.assertLessEqual(len(analysis), pipeline.MAX_FOCUS_INSIGHT_CHARS)
        self.assertEqual(sum(analysis.count(mark) for mark in "。！？!?"), 1)
        self.assertIn("3428.5", analysis)
        self.assertTrue(pipeline._has_deep_interpretation(analysis))
        self.assertFalse(any(term in analysis for term in ("建议", "应优先", "需优先", "值得关注")))

    def test_entity_label_repair_maps_only_to_exact_input_evidence(self):
        evidence = {"domains": [{"id": "local", "focuses": [{"id": "price", "items": [{
            "name": "HKBN",
            "source_url": "https://example.com/hkbn",
            "components": [{"label": "HKBN 2.5Gbps Router Plan"}],
        }]}]}]}
        raw = [{"domain": "local", "focuses": [{"id": "price", "entities": [{
            "name": "HKBN",
            "evidence_labels": ["HKBN 2.5G Router Plan", "完全无关标签"],
            "source_urls": ["https://example.com/hkbn", "https://invented.example.com"],
        }]}]}]
        repaired = pipeline._repair_entity_evidence_labels(raw, evidence)
        entity = repaired[0]["focuses"][0]["entities"][0]
        self.assertEqual(entity["evidence_labels"], ["HKBN 2.5Gbps Router Plan"])
        self.assertEqual(entity["source_urls"], ["https://example.com/hkbn"])

    def test_model_repair_builds_missing_domain_shell_from_valid_focus_ai(self):
        evidence = {"domains": [{"id": "macro", "title": "宏观政策", "focuses": [{
            "id": "market", "metric": {"value": 3428.5, "unit": "万", "label": "移动连接"}, "items": [],
        }]}]}
        raw = [{"domain": "macro", "focuses": [{
            "id": "market", "analysis": "3428.5万连接显示市场饱和压力，表明增量空间受渗透结构约束。",
            "risk": "保持口径边界。", "source_urls": [], "entities": [],
        }]}]
        repaired = pipeline._repair_model_summaries(raw, evidence)
        self.assertIn("宏观政策", repaired[0]["headline"])
        self.assertIn("3428.5万", repaired[0]["analysis"])
        self.assertTrue(repaired[0]["risk"])

    def test_deep_interpretation_repair_requires_numeric_analytical_prose(self):
        evidence = {"domains": [{"id": "international", "focuses": [{
            "id": "momentum", "metric": {"value": -0.27, "unit": "个百分点"},
        }]}]}
        raw = [{"domain": "international", "focuses": [{
            "id": "momentum", "analysis": "最佳动量变化为-0.27个百分点，负值代表回落。",
        }]}]
        repaired = pipeline._repair_focus_business_implications(raw, evidence)
        focus = repaired[0]["focuses"][0]
        self.assertTrue(focus["deep_interpretation_repaired"])
        self.assertTrue(pipeline._has_deep_interpretation(focus["analysis"]))
        self.assertNotIn("应", focus["analysis"])

        filler = [{"domain": "international", "focuses": [{
            "id": "momentum", "analysis": "该指标用于展示增长动量。",
        }]}]
        unchanged = pipeline._repair_focus_business_implications(filler, evidence)
        self.assertNotIn("deep_interpretation_repaired", unchanged[0]["focuses"][0])

    def test_model_analysis_sanitizer_drops_only_unsupported_numeric_clause(self):
        evidence = {"domains": [{"focuses": [{"items": [{"value": 10}]}]}]}
        raw = [{
            "domain": "local",
            "headline": "保留10项事实",
            "analysis": "保留10项。删除99项。继续观察。",
            "risk": "口径需复核。",
            "source_urls": [],
        }]
        cleaned = pipeline._drop_unsupported_numeric_clauses(raw, evidence)
        self.assertEqual(cleaned[0]["analysis"], "保留10项。继续观察。")
        self.assertEqual(cleaned[0]["sanitized_clauses"], 1)

    def test_model_analysis_reuses_validated_summary_when_evidence_is_unchanged(self):
        summaries = [
            {"domain": domain, "headline": "观察", "analysis": "证据未变。", "risk": "保持边界。", "source_urls": []}
            for domain in pipeline.UI_DOMAIN_IDS
        ]
        discoveries = [
            {"from": source, "to": target, "title": title, "detail": "证据联合观察。", "kind": "AI综合研判", "source_urls": []}
            for source, target, title in (
                ("local", "international", "本地与国际联动"),
                ("international", "cloud", "国际与云联动"),
                ("local", "cloud", "本地与云联动"),
                ("mainland", "local", "内地与本地联动"),
            )
        ]
        evidence = {
            "domains": [
                {"id": domain, "focuses": [], "agent_verified_facts": []}
                for domain in pipeline.UI_DOMAIN_IDS
            ],
            "relations": [],
        }
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "analysis.json"
            path.write_text(json.dumps({"model_analysis": {
                "model": "test",
                "evidence_hash": pipeline._content_hash(evidence),
                "insight_format": pipeline.INSIGHT_FORMAT_VERSION,
                "summaries": summaries,
                "discoveries": discoveries,
            }}), encoding="utf-8")
            with (
                patch("executive_intelligence_pipeline._analysis_input_snapshot", return_value=evidence),
                patch("executive_intelligence_pipeline.generate_model_domain_summaries", side_effect=AssertionError("must reuse")),
            ):
                result = pipeline.publish_model_domain_summaries(path)
        self.assertTrue(result["reused"])
        self.assertEqual(len(result["summaries"]), 4)
        self.assertEqual(len(result["discoveries"]), 4)

    def test_old_insight_format_is_regenerated_even_when_evidence_is_unchanged(self):
        evidence = {"domains": [], "relations": []}
        summaries = [
            {"domain": domain, "headline": "观察", "analysis": "证据未变。", "risk": "保持边界。", "source_urls": []}
            for domain in ("local", "international", "cloud", "macro")
        ]
        discoveries = [
            {"from": source, "to": target, "title": title, "detail": "证据联合观察。", "kind": "AI综合研判", "source_urls": []}
            for source, target, title in (
                ("local", "international", "本地与国际联动"),
                ("international", "cloud", "国际与云联动"),
                ("local", "cloud", "本地与云联动"),
                ("macro", "local", "宏观与本地联动"),
            )
        ]
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "analysis.json"
            path.write_text(json.dumps({"model_analysis": {
                "model": "old",
                "evidence_hash": pipeline._content_hash(evidence),
                "insight_format": "single_sentence_v1",
                "summaries": summaries,
                "discoveries": discoveries,
            }}), encoding="utf-8")
            with (
                patch("executive_intelligence_pipeline._analysis_input_snapshot", return_value=evidence),
                patch("executive_intelligence_pipeline.generate_model_domain_summaries", return_value={
                    "generated_at_hkt": "now", "model": "new", "summaries": summaries,
                }) as generate_summaries,
                patch("executive_intelligence_pipeline.generate_model_discoveries", return_value={
                    "generated_at_hkt": "now", "model": "new", "discoveries": discoveries,
                }),
            ):
                result = pipeline.publish_model_domain_summaries(path)
        generate_summaries.assert_called_once()
        self.assertFalse(result["reused"])
        self.assertEqual(result["insight_format"], pipeline.INSIGHT_FORMAT_VERSION)

    def test_model_discovery_gate_requires_unique_cross_domain_pairs_and_source_evidence(self):
        evidence = {
            "domains": [
                {
                    "id": domain,
                    "focuses": [{"items": [{"value": 10, "source_url": f"https://example.com/{domain}"}]}],
                    "agent_verified_facts": [],
                }
                for domain in ("local", "international", "cloud", "macro")
            ],
            "relations": [],
        }
        discoveries = [
            {
                "from": source,
                "to": target,
                "title": title,
                "detail": "两域均为10项，说明增长结构同步，差异并非来自证据数量。",
                "kind": "AI综合研判",
                "source_urls": [f"https://example.com/{source}", f"https://example.com/{target}"],
            }
            for source, target, title in (
                ("local", "international", "本地与国际联动"),
                ("international", "cloud", "国际与云联动"),
                ("local", "cloud", "本地与云联动"),
                ("macro", "local", "宏观与本地联动"),
            )
        ]
        validated = pipeline._validate_model_discoveries(discoveries, evidence)
        self.assertEqual(len(validated), 4)
        duplicate = [dict(item) for item in discoveries]
        duplicate[3] = dict(discoveries[0])
        with self.assertRaisesRegex(ValueError, "重复关联"):
            pipeline._validate_model_discoveries(duplicate, evidence)
        missing_source = [dict(item) for item in discoveries]
        missing_source[0] = {**missing_source[0], "source_urls": ["https://example.com/local"]}
        with self.assertRaisesRegex(ValueError, "international领域来源"):
            pipeline._validate_model_discoveries(missing_source, evidence)

        advised = [dict(item) for item in discoveries]
        advised[0] = {**advised[0], "detail": "两域均为10项，建议优先关注增长差异。"}
        with self.assertRaisesRegex(ValueError, "行动建议"):
            pipeline._validate_model_discoveries(advised, evidence)

        shallow = [dict(item) for item in discoveries]
        shallow[0] = {**shallow[0], "detail": "两域均为10项，数据显示存在差异。"}
        with self.assertRaisesRegex(ValueError, "结构、驱动或跨领域关系"):
            pipeline._validate_model_discoveries(shallow, evidence)

    def test_discovery_generation_rotates_model_after_timeout(self):
        evidence = {
            "domains": [{"id": domain, "focuses": [], "agent_verified_facts": []}
                        for domain in ("local", "international", "cloud", "macro")],
            "relations": [],
        }
        discoveries = [
            {"from": source, "to": target, "title": title, "detail": "跨库证据支持联合经营研判。",
             "kind": "AI综合研判", "source_urls": []}
            for source, target, title in (
                ("local", "international", "本地与国际联动"),
                ("international", "cloud", "国际与云联动"),
                ("local", "cloud", "本地与云联动"),
                ("macro", "local", "宏观与本地联动"),
            )
        ]
        response = mock.MagicMock()
        response.__enter__.return_value.read.return_value = json.dumps({
            "choices": [{"message": {"content": json.dumps(discoveries, ensure_ascii=False)}}]
        }, ensure_ascii=False).encode("utf-8")
        with (
            patch("ai_config.load_ai_config", return_value={
                "api_key": "secret", "model": "deepseek-v4", "base_url": "http://model.local/v1",
            }),
            patch("ai_rate_limit.wait_for_internal_ai_slot"),
            patch("network_utils.urlopen_with_local_proxy_fallback", side_effect=[TimeoutError("slow"), response]) as open_url,
        ):
            result = pipeline.generate_model_discoveries(evidence)

        self.assertEqual(result["model"], "GLM")
        self.assertEqual(len(result["discoveries"]), 4)
        self.assertEqual(open_url.call_count, 2)
        request_models = [
            json.loads(call.args[0].data.decode("utf-8"))["model"]
            for call in open_url.call_args_list
        ]
        self.assertEqual(request_models, ["DeepSeek-V4-Pro", "GLM"])
        self.assertTrue(all(
            json.loads(call.args[0].data.decode("utf-8"))["max_tokens"] == 16000
            for call in open_url.call_args_list
        ))

    def test_discovery_generation_repairs_overlong_card_copy_before_gate(self):
        evidence = {
            "domains": [
                {
                    "id": domain,
                    "focuses": [{"items": [{"value": 10, "source_url": f"https://example.com/{domain}"}]}],
                    "agent_verified_facts": [],
                }
                for domain in ("local", "international", "cloud", "macro")
            ],
            "relations": [],
        }
        discoveries = [
            {
                "from": source,
                "to": target,
                "title": title + "的跨领域关系结构出现显著分层变化",
                "detail": (
                    "两域均为10项，说明增长结构同步，差异并非来自证据数量。"
                    "这一句只是模型额外展开的重复说明，不应让整轮降级。" * 4
                ),
                "kind": "AI综合研判",
                "source_urls": [f"https://example.com/{source}", f"https://example.com/{target}"],
            }
            for source, target, title in (
                ("local", "international", "本地与国际联动"),
                ("international", "cloud", "国际与云联动"),
                ("local", "cloud", "本地与云联动"),
                ("macro", "local", "宏观与本地联动"),
            )
        ]
        response = mock.MagicMock()
        response.__enter__.return_value.read.return_value = json.dumps({
            "choices": [{"message": {"content": json.dumps(discoveries, ensure_ascii=False)}}]
        }, ensure_ascii=False).encode("utf-8")
        with (
            patch("ai_config.load_ai_config", return_value={
                "api_key": "secret", "model": "deepseek-v4", "base_url": "http://model.local/v1",
            }),
            patch("ai_rate_limit.wait_for_internal_ai_slot"),
            patch("network_utils.urlopen_with_local_proxy_fallback", return_value=response) as open_url,
        ):
            result = pipeline.generate_model_discoveries(evidence)

        self.assertEqual(open_url.call_count, 1)
        self.assertEqual(len(result["discoveries"]), 4)
        self.assertTrue(all(len(item["title"]) <= 28 for item in result["discoveries"]))
        self.assertTrue(all(len(item["detail"]) <= 110 for item in result["discoveries"]))
        self.assertTrue(all(
            any(term in item["detail"] for term in pipeline._INTERPRETIVE_CONNECTORS)
            for item in result["discoveries"]
        ))

    def test_discovery_depth_repair_replaces_only_shallow_detail(self):
        evidence = {
            "domains": [
                {"id": "local", "focuses": [{"items": [{"value": 10}]}]},
                {"id": "cloud", "focuses": [{"items": [{"value": 20}]}]},
            ]
        }
        raw = [{
            "from": "local",
            "to": "cloud",
            "title": "两域规模差异",
            "detail": "这表明本地为10、云为20。",
            "kind": "AI综合研判",
            "source_urls": [],
        }]
        seed_detail = "本地10低于云20，差距表明资本结构分化，并非同一口径规模领先。"
        with patch.object(
            pipeline,
            "_deterministic_discoveries",
            return_value=[{"from": "local", "to": "cloud", "detail": seed_detail}],
        ):
            repaired, count = pipeline._repair_discovery_depth(raw, evidence)

        self.assertEqual(count, 1)
        self.assertEqual(repaired[0]["title"], raw[0]["title"])
        self.assertEqual(repaired[0]["detail"], seed_detail)

    def test_discovery_depth_repair_handles_model_selected_pair_without_seed(self):
        evidence = {
            "domains": [
                {"id": "local", "focuses": [{"items": [{"value": 10}]}]},
                {"id": "international", "focuses": [{"items": [{"value": 20}]}]},
            ]
        }
        raw = [{
            "from": "local",
            "to": "international",
            "title": "两域收入差异",
            "detail": "本地收入为10，国际收入为20。",
            "kind": "AI综合研判",
            "source_urls": [],
        }]
        with patch.object(pipeline, "_deterministic_discoveries", return_value=[]):
            repaired, count = pipeline._repair_discovery_depth(raw, evidence)

        self.assertEqual(count, 1)
        self.assertIn("收入与盈利结构", repaired[0]["detail"])
        self.assertTrue(pipeline._has_deep_interpretation(repaired[0]["detail"]))
        self.assertLessEqual(len(repaired[0]["detail"]), 110)

    def test_discovery_prompt_uses_compact_metrics_without_entity_components(self):
        evidence = {"domains": [{
            "id": "cloud", "title": "云厂商", "deterministic_insight": "增长分化。",
            "focuses": [{
                "id": "growth", "title": "增长", "metric": {"value": 35.8, "unit": "%"},
                "insight": "Google Cloud领先。",
                "items": [{
                    "name": "Google Cloud", "value": 35.8, "unit": "%",
                    "source_url": "https://example.com/cloud",
                    "components": [{"label": "FY2025", "value": 35.8}] * 20,
                    "analysis": "很长的实体分析" * 100,
                }],
            }],
        }], "relations": []}
        compact = pipeline._compact_discovery_evidence(evidence)
        item = compact["domains"][0]["focuses"][0]["items"][0]
        self.assertEqual(item["value"], 35.8)
        self.assertNotIn("components", item)
        self.assertNotIn("analysis", item)
        self.assertLess(len(json.dumps(compact, ensure_ascii=False)), 1000)

    def test_changed_evidence_hash_regenerates_all_text_summaries(self):
        evidence = {"domains": [], "relations": [], "version": "new"}
        summaries = [
            {"domain": domain, "headline": "新结论", "analysis": "新证据。", "risk": "保持边界。", "source_urls": []}
            for domain in ("local", "international", "cloud", "macro")
        ]
        discoveries = [
            {"from": source, "to": target, "title": title, "detail": "新证据联动。", "kind": "AI综合研判", "source_urls": []}
            for source, target, title in (
                ("local", "international", "本地与国际"),
                ("international", "cloud", "国际与云"),
                ("local", "cloud", "本地与云"),
                ("macro", "local", "宏观与本地"),
            )
        ]
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "analysis.json"
            path.write_text(json.dumps({"model_analysis": {
                "evidence_hash": "stale",
                "summaries": summaries,
                "discoveries": discoveries,
            }}), encoding="utf-8")
            with (
                patch("executive_intelligence_pipeline._analysis_input_snapshot", return_value=evidence),
                patch("executive_intelligence_pipeline.generate_model_domain_summaries", return_value={
                    "generated_at_hkt": "now", "model": "test", "summaries": summaries,
                }) as regenerate,
                patch("executive_intelligence_pipeline.generate_model_discoveries", return_value={
                    "generated_at_hkt": "now", "model": "test", "discoveries": discoveries,
                }),
            ):
                result = pipeline.publish_model_domain_summaries(path)
        regenerate.assert_called_once_with(evidence)
        self.assertFalse(result["reused"])
        self.assertEqual(result["evidence_hash"], pipeline._content_hash(evidence))

    def test_model_analysis_uses_evidence_only_fallback_when_model_is_invalid(self):
        evidence = {
            "domains": [
                {"id": domain, "title": domain, "deterministic_insight": "已核验证据显示变化。", "focuses": []}
                for domain in pipeline.UI_DOMAIN_IDS
            ],
            "relations": [],
        }
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "analysis.json"
            path.write_text("{}", encoding="utf-8")
            with (
                patch("executive_intelligence_pipeline._analysis_input_snapshot", return_value=evidence),
                patch("executive_intelligence_pipeline.generate_model_domain_summaries", side_effect=ValueError("bad model")),
                patch("executive_intelligence_pipeline.generate_model_discoveries", side_effect=ValueError("bad model")),
            ):
                result = pipeline.publish_model_domain_summaries(path)
        self.assertTrue(result["fallback_used"])
        self.assertEqual(result["model"], "deterministic-evidence-fallback")
        self.assertEqual(len(result["summaries"]), 4)
        self.assertEqual(len(result["discoveries"]), 4)

    def test_pages_publisher_requires_verified_public_result(self):
        completed = mock.Mock(
            returncode=0,
            stdout=json.dumps({
                "status": "published",
                "site_version": "site-123",
                "public_url": "https://example.github.io/project/",
                "commit": "abc123",
            }),
            stderr="",
        )
        with patch("executive_intelligence_pipeline.subprocess.run", return_value=completed) as run:
            result = pipeline._publish_and_verify_github_pages()

        self.assertTrue(result["ok"])
        self.assertEqual(result["site_version"], "site-123")
        self.assertIn("--force", run.call_args.args[0])

    def test_pages_publisher_waits_for_concurrent_publish_and_reverifies(self):
        busy = mock.Mock(returncode=0, stdout=json.dumps({"status": "busy"}), stderr="")
        verified = mock.Mock(
            returncode=0,
            stdout=json.dumps({
                "status": "verified",
                "site_version": "site-after-busy",
                "public_url": "https://example.github.io/project/",
            }),
            stderr="",
        )
        with (
            patch("executive_intelligence_pipeline.subprocess.run", side_effect=[busy, verified]) as run,
            patch("executive_intelligence_pipeline.time.sleep") as sleep,
        ):
            result = pipeline._publish_and_verify_github_pages()

        self.assertTrue(result["ok"])
        self.assertEqual(result["attempts"], 2)
        self.assertEqual(run.call_count, 2)
        sleep.assert_called_once_with(5)

    def test_four_database_success_triggers_pages_publish_after_ai_gate(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            evidence = {
                "domains": [
                    {"id": domain, "focuses": [], "agent_verified_facts": []}
                    for domain in pipeline.UI_DOMAIN_IDS
                ],
                "relations": [],
            }
            model_result = {
                "generated_at_hkt": "2026-08-06T04:00:00+08:00",
                "model": "deepseek-v4",
                "summaries": [{"domain": item} for item in pipeline.UI_DOMAIN_IDS],
                "evidence_hash": "evidence-hash",
                "fallback_used": False,
            }
            with (
                patch.object(pipeline, "STATE_DIR", root),
                patch.object(pipeline, "STATE_PATH", root / "latest.json"),
                patch.object(pipeline, "LOCK_PATH", root / "refresh.lock"),
                patch.object(pipeline, "LOG_PATH", root / "refresh.log"),
                patch("executive_intelligence_pipeline.publish_ai_analysis", return_value={
                    "changed": True, "domain_counts": {}, "path": str(root / "analysis.json")
                }),
                patch("executive_intelligence_pipeline.publish_domain_fact_sidecars", return_value={}),
                patch("executive_intelligence_pipeline.validate_database", return_value={"rows": 1}),
                patch("executive_intelligence_pipeline._analysis_input_snapshot", return_value=evidence),
                patch("executive_intelligence_pipeline.load_0100_source_discovery_handoff", return_value={
                    "ok": True, "available": True,
                }),
                patch("executive_intelligence_pipeline.publish_model_domain_summaries", return_value=model_result),
                patch("executive_intelligence_pipeline._publish_and_verify_github_pages", return_value={
                    "ok": True, "status": "verified", "site_version": "site-123",
                    "public_url": "https://example.github.io/project/",
                }) as publish_pages,
                patch("executive_intelligence_pipeline._task_event"),
            ):
                result = pipeline.run_pipeline(
                    agent_run_id="agent-test",
                    refresh_builders=False,
                    task_run_id="task-test",
                )

        self.assertTrue(result["ok"])
        self.assertTrue(result["pages_publish"]["ok"])
        publish_pages.assert_called_once_with()

    def test_frontend_publish_failure_keeps_four_domain_refresh_failed(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            evidence = {
                "domains": [
                    {"id": domain, "focuses": [], "agent_verified_facts": []}
                    for domain in pipeline.UI_DOMAIN_IDS
                ],
                "relations": [],
            }
            model_result = {
                "generated_at_hkt": "2026-08-06T04:00:00+08:00",
                "model": "deepseek-v4",
                "summaries": [{"domain": item} for item in pipeline.UI_DOMAIN_IDS],
                "evidence_hash": "evidence-hash",
                "fallback_used": False,
            }
            with (
                patch.object(pipeline, "STATE_DIR", root),
                patch.object(pipeline, "STATE_PATH", root / "latest.json"),
                patch.object(pipeline, "LOCK_PATH", root / "refresh.lock"),
                patch.object(pipeline, "LOG_PATH", root / "refresh.log"),
                patch("executive_intelligence_pipeline.publish_ai_analysis", return_value={
                    "changed": True, "domain_counts": {}, "path": str(root / "analysis.json")
                }),
                patch("executive_intelligence_pipeline.publish_domain_fact_sidecars", return_value={}),
                patch("executive_intelligence_pipeline.validate_database", return_value={"rows": 1}),
                patch("executive_intelligence_pipeline._analysis_input_snapshot", return_value=evidence),
                patch("executive_intelligence_pipeline.load_0100_source_discovery_handoff", return_value={
                    "ok": True, "available": True,
                }),
                patch("executive_intelligence_pipeline.publish_model_domain_summaries", return_value=model_result),
                patch(
                    "executive_intelligence_pipeline._publish_and_verify_github_pages",
                    side_effect=RuntimeError("公开回读失败"),
                ),
                patch("executive_intelligence_pipeline._task_event"),
            ):
                result = pipeline.run_pipeline(
                    agent_run_id="agent-test",
                    refresh_builders=False,
                    task_run_id="task-test",
                )

        self.assertFalse(result["ok"])
        self.assertEqual(result["status"], "failed_frontend_publish")
        self.assertTrue(result["fallback_preserved"])

    def test_scheduler_launch_failure_does_not_raise_or_change_crawl_semantics(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            log = Path(temp_dir) / "run.jsonl"
            with (
                patch.dict("os.environ", {"CMHK_FORCE_INTELLIGENCE_REFRESH_FOR_TESTS": "1"}),
                patch("executive_intelligence_pipeline.launch_pipeline_async", side_effect=RuntimeError("boom")),
            ):
                result = scheduler._launch_executive_intelligence_refresh(
                    "crawl-test", log, {"agent_run_id": "agent-test"}
                )
        self.assertFalse(result["ok"])
        self.assertFalse(result["launched"])
        self.assertEqual(result["domains"], ["local", "international", "mainland", "cloud"])
        self.assertEqual(
            result["stages"],
            ["database_refresh", "quality_gate", "official_source_recrawl", "15_focus_analysis", "homepage_ui_refresh", "public_frontend_publish"],
        )


if __name__ == "__main__":
    unittest.main()
