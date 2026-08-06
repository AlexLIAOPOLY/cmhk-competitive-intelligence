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
            "executive_intelligence.build_executive_intelligence_snapshot",
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

    def test_watchdog_launches_one_recovery_for_unmatched_daily_crawl(self):
        scheduled = {
            "crawl_run_id": "crawl-0300",
            "trigger": "定时爬虫",
            "run_status": "completed",
            "completed_at_hkt": "2026-08-04T03:30:00+08:00",
            "curation": {"agent_run_id": "agent-0300"},
        }
        with (
            patch("crawl_run_registry.load_index", return_value=[scheduled]),
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
        self.assertEqual(payload["domain_counts"]["international"], 1)
        self.assertEqual(payload["domains"]["international"][0]["company"], "中国移动")

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
                "international": [{"company": "中国移动", "source_tier": "media", "source_url": "https://example.com/media"}],
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
            cloud = json.loads(paths["cloud"].read_text(encoding="utf-8"))
        self.assertEqual(result["local"]["facts"], 1)
        self.assertEqual(local["facts"][0]["company"], "HKBN")
        self.assertEqual(international["facts"], [])
        self.assertEqual(cloud["facts"][0]["company"], "AWS")

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
            "domains": [{
                "id": "local",
                "focuses": [{"items": [{"value": 10, "source_url": "https://example.com/source"}]}],
                "agent_verified_facts": [],
            }]
        }
        summaries = [
            {
                "domain": domain,
                "headline": "保持观察",
                "analysis": "现有证据显示变化。" if domain != "local" else "现有10项证据显示变化。",
                "risk": "口径不同。",
                "source_urls": ["https://example.com/source"] if domain == "local" else [],
            }
            for domain in ("local", "international", "cloud", "macro")
        ]
        pipeline._validate_model_summaries(summaries, evidence)
        summaries[1]["analysis"] = "出现99项变化。"
        with self.assertRaisesRegex(ValueError, "输入之外的数字"):
            pipeline._validate_model_summaries(summaries, evidence)

    def test_model_analysis_gate_rejects_unseen_source_url(self):
        evidence = {"domains": []}
        summaries = [
            {"domain": domain, "headline": "观察", "analysis": "已有变化。", "risk": "谨慎。", "source_urls": []}
            for domain in ("local", "international", "cloud", "macro")
        ]
        summaries[2]["source_urls"] = ["https://invented.example.com"]
        with self.assertRaisesRegex(ValueError, "输入之外的来源"):
            pipeline._validate_model_summaries(summaries, evidence)

    def test_model_analysis_requires_every_focus_summary(self):
        evidence = {
            "domains": [
                {
                    "id": domain,
                    "focuses": [
                        {"id": f"{domain}-a", "items": []},
                        {"id": f"{domain}-b", "items": []},
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
                    {"id": f"{domain}-a", "analysis": "竞争位置出现变化，业务上应优先评估收入风险。", "risk": "保持边界。", "source_urls": []},
                    {"id": f"{domain}-b", "analysis": "竞争位置出现差距，业务上应优先评估客户影响。", "risk": "保持边界。", "source_urls": []},
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
                    "analysis": "10项证据显示结构集中，业务上应优先评估产品风险。",
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
                "focuses": [{"id": "focus", "items": [{"name": "实体", "components": [{"label": "项目"}]}]}],
                "agent_verified_facts": [],
            } for domain in ("local", "international", "cloud", "macro")]
        }
        summaries = [{
            "domain": domain, "headline": "观察", "analysis": "已有变化。", "risk": "谨慎。", "source_urls": [],
            "focuses": [{
                "id": "focus", "analysis": "竞争位置出现变化，业务上应优先评估收入风险。", "risk": "谨慎。", "source_urls": [],
                "entities": [{
                    "name": "实体", "headline": "观察", "analysis": "数据库内按排名展示。", "risk": "谨慎。",
                    "evidence_labels": ["项目"], "source_urls": [],
                }],
            }],
        } for domain in ("local", "international", "cloud", "macro")]
        with self.assertRaisesRegex(ValueError, "界面废话"):
            pipeline._validate_model_summaries(summaries, evidence)

    def test_all_sixteen_focuses_require_numbers_and_business_judgement(self):
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
                        "analysis": f"{index + 1}项证据显示竞争差距，业务上应优先评估收入与客户影响。",
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
            "analysis": "市场饱和压力加大，经营上应转向存量客户价值提升。",
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
            "analysis": "移动连接达到3428.5万，市场饱和压力上升。新增空间收窄。经营上应转向存量价值提升。",
        }]}]

        repaired = pipeline._repair_focus_conciseness(raw, evidence)
        analysis = repaired[0]["focuses"][0]["analysis"]
        self.assertLessEqual(len(analysis), pipeline.MAX_FOCUS_INSIGHT_CHARS)
        self.assertEqual(sum(analysis.count(mark) for mark in "。！？!?"), 1)
        self.assertIn("3428.5", analysis)
        self.assertTrue(pipeline._has_business_judgement(analysis))

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
            "id": "market", "analysis": "3428.5万连接显示市场饱和压力，经营上应优先提升存量客户价值。",
            "risk": "保持口径边界。", "source_urls": [], "entities": [],
        }]}]
        repaired = pipeline._repair_model_summaries(raw, evidence)
        self.assertIn("宏观政策", repaired[0]["headline"])
        self.assertIn("3428.5万", repaired[0]["analysis"])
        self.assertTrue(repaired[0]["risk"])

    def test_business_implication_repair_requires_numeric_analytical_prose(self):
        evidence = {"domains": [{"id": "international", "focuses": [{
            "id": "momentum", "metric": {"value": -0.27, "unit": "个百分点"},
        }]}]}
        raw = [{"domain": "international", "focuses": [{
            "id": "momentum", "analysis": "最佳动量变化为-0.27个百分点，负值代表回落。",
        }]}]
        repaired = pipeline._repair_focus_business_implications(raw, evidence)
        focus = repaired[0]["focuses"][0]
        self.assertTrue(focus["business_implication_repaired"])
        self.assertIn("经营上应", focus["analysis"])

        filler = [{"domain": "international", "focuses": [{
            "id": "momentum", "analysis": "该指标用于展示增长动量。",
        }]}]
        unchanged = pipeline._repair_focus_business_implications(filler, evidence)
        self.assertNotIn("business_implication_repaired", unchanged[0]["focuses"][0])

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
        evidence = {"domains": [], "relations": []}
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "analysis.json"
            path.write_text(json.dumps({"model_analysis": {
                "model": "test",
                "evidence_hash": pipeline._content_hash(evidence),
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

    def test_model_discovery_gate_requires_unique_cross_domain_pairs_and_source_evidence(self):
        evidence = {
            "domains": [
                {
                    "id": domain,
                    "focuses": [{"items": [{"source_url": f"https://example.com/{domain}"}]}],
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
                "detail": "已核验数据显示需联合观察。",
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
                for domain in ("local", "international", "cloud", "macro")
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
            model_result = {
                "generated_at_hkt": "2026-08-06T04:00:00+08:00",
                "model": "deepseek-v4",
                "summaries": [{"domain": item} for item in ("local", "international", "cloud", "macro")],
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


if __name__ == "__main__":
    unittest.main()
