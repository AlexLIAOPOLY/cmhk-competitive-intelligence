from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import executive_intelligence_pipeline as pipeline
import crawl
from data_curation.workflow import _source_rank
import scheduler


class ExecutiveIntelligencePipelineTests(unittest.TestCase):
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
                    {"id": f"{domain}-a", "analysis": "分类证据已更新。", "risk": "保持边界。", "source_urls": []},
                    {"id": f"{domain}-b", "analysis": "分类证据已更新。", "risk": "保持边界。", "source_urls": []},
                ],
            }
            for domain in ("local", "international", "cloud", "macro")
        ]
        validated = pipeline._validate_model_summaries(summaries, evidence)
        self.assertEqual(sum(len(item["focuses"]) for item in validated), 8)
        summaries[0]["focuses"].pop()
        with self.assertRaisesRegex(ValueError, "分类不完整"):
            pipeline._validate_model_summaries(summaries, evidence)

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
