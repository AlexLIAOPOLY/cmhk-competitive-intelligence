#!/usr/bin/env python3
"""Run a side-effect-free retry replay for every internal-AI workflow family."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from ai_response_compat import (  # noqa: E402
    final_chat_message_text,
    load_json_response,
    prepare_structured_chat_body,
    unwrap_items_payload,
)


WORKFLOWS: tuple[tuple[str, str], ...] = (
    ("战略新闻审核与去重", "items"),
    ("Agentic Search规划", "items"),
    ("主爬虫事实清洗", "items"),
    ("Agent证据审核", "object"),
    ("四库Supervisor", "object"),
    ("17项AI洞察", "items"),
    ("跨库AI洞察", "items"),
    ("周报写作", "items"),
    ("周报审稿", "items"),
    ("运营商业绩摘要", "items"),
    ("运维告警诊断", "object"),
    ("飞书传播数据校验", "object"),
    ("小竞AI推荐追问", "object"),
    ("小竞AI普通回答", "text"),
    ("RAG问答", "text"),
    ("图片识别", "text"),
    ("竞对指标洞察", "text"),
    ("语音摘要", "text"),
)


STRUCTURED_SOURCE_GATES: dict[str, tuple[str, ...]] = {
    "strategic_briefing.py": ("load_json_response", "response_format"),
    "normalize_company_metrics_ai.py": ("prepare_structured_chat_body", "load_json_response"),
    "cmhk.crawl.verification.py": ("response_format", "load_json_response"),
    "executive_intelligence_pipeline.py": ("prepare_structured_chat_body", "load_json_response"),
    "generate_weekly_report.py": ("prepare_structured_chat_body", "load_json_response"),
    "generate_carrier_performance_report.py": ("prepare_structured_chat_body", "load_json_response"),
    "project_monitor.py": ("prepare_structured_chat_body", "load_json_response"),
    "scripts/feishu_media_metrics_report.py": ("prepare_structured_chat_body", "load_json_response"),
    "agent.py": ("response_format", "load_json_response"),
}


def _payload(content: str, *, finish_reason: str = "stop", reasoning: str = "") -> dict[str, Any]:
    return {
        "choices": [{
            "finish_reason": finish_reason,
            "message": {"content": content, "reasoning_content": reasoning},
        }]
    }


def _success_content(name: str, kind: str) -> str:
    if kind == "items":
        return json.dumps({"items": [{"workflow": name, "ok": True}]}, ensure_ascii=False)[:-2]
    if kind == "object":
        return json.dumps({"workflow": name, "ok": True}, ensure_ascii=False)[:-1]
    return f"{name}最终正文"


def simulate_workflow(name: str, kind: str) -> dict[str, Any]:
    attempts = [
        _payload("", reasoning='{"ok":true}'),
        _payload('{"items":[{"detail":"半截', finish_reason="length", reasoning="继续推理"),
        _payload(_success_content(name, kind), reasoning="不得作为最终答案"),
    ]
    rejected: list[str] = []
    result: Any = None
    repaired = False
    for index, payload in enumerate(attempts, start=1):
        try:
            text = final_chat_message_text(payload, operation=name)
            if kind == "text":
                result = text
            else:
                raw_valid = True
                try:
                    json.loads(text)
                except json.JSONDecodeError:
                    raw_valid = False
                parsed = load_json_response(text, operation=name)
                repaired = not raw_valid
                if kind == "items":
                    result = unwrap_items_payload(parsed, operation=name)
                elif not isinstance(parsed, dict):
                    raise ValueError(f"{name}未返回对象")
                else:
                    result = parsed
            return {
                "workflow": name,
                "kind": kind,
                "attempts": index,
                "rejected": rejected,
                "repaired_terminal_delimiters": repaired,
                "ok": bool(result),
            }
        except (ValueError, TypeError) as exc:
            rejected.append(str(exc))
    raise AssertionError(f"{name}三次模拟均失败: {rejected}")


def run_matrix(root: Path = ROOT) -> dict[str, Any]:
    request_contract = prepare_structured_chat_body({"model": "deepseek-v4"})
    assert request_contract["thinking"] == {"type": "disabled"}
    assert request_contract["response_format"] == {"type": "json_object"}
    source_gates: list[dict[str, Any]] = []
    for relative, markers in STRUCTURED_SOURCE_GATES.items():
        text = (root / relative).read_text(encoding="utf-8")
        missing = [marker for marker in markers if marker not in text]
        source_gates.append({"path": relative, "ok": not missing, "missing": missing})
    if not all(item["ok"] for item in source_gates):
        raise AssertionError(f"结构化入口未接入共享门禁: {source_gates}")
    results = [simulate_workflow(name, kind) for name, kind in WORKFLOWS]
    return {
        "ok": all(item["ok"] and item["attempts"] == 3 for item in results),
        "workflow_count": len(results),
        "structured_source_gate_count": len(source_gates),
        "results": results,
        "source_gates": source_gates,
        "side_effects": {"crawler_started": False, "feishu_written": False, "message_sent": False},
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    report = run_matrix(args.root.resolve())
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print(f"重试矩阵：{report['workflow_count']}条链路全部通过")
        for item in report["results"]:
            repair = "，安全补齐末端括号" if item["repaired_terminal_delimiters"] else ""
            print(f"- {item['workflow']}: 第1/2次拒绝，第{item['attempts']}次成功{repair}")
        print("副作用：未启动爬虫、未写飞书、未发送消息")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
