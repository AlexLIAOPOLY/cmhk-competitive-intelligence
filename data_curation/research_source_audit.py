"""Explain missing evidence without turning searched pages into accepted sources."""
from __future__ import annotations

import re


def source_audit(item: dict, report: dict) -> dict:
    from .workflow import _metric_evidence_terms, _metric_term_position

    metric = str(item.get("metric") or "")
    reason = str(item.get("reason") or "；".join(item.get("reasons") or []))
    searches = [row for row in report.get("searches", []) if row.get("metric") == metric]
    pages = report.get("pages") or {}
    trusted = {url: page for url, page in pages.items() if page.get("opened") and page.get("official")}
    terms = _metric_evidence_terms(metric)
    checked = []
    for url, page in trusted.items():
        text = re.sub(r"\s+", " ", str(page.get("text") or ""))
        positions = [pos for term in terms if (pos := _metric_term_position(text, term)) >= 0]
        checked.append({"url": url, "metric_mentioned": bool(positions),
                        "excerpt": text[max(0, min(positions)-100):min(positions)+300] if positions else ""})
    if re.search(r"budget.*exceed|budget_exceeded|insufficient_quota", reason, re.I):
        stage, explanation = "model_quota", "模型额度不足，未完成指标提取；不是已证实没有公开资料"
    elif re.search(r"401|unauthorized|authentication", reason, re.I):
        stage, explanation = "model_auth", "模型鉴权失败，未完成指标核对；不是来源不存在"
    elif report.get("review_search_error"):
        stage, explanation = "search_failed", "补充搜索发生错误，来源覆盖不完整"
    elif not trusted:
        stage, explanation = "source_read_failed", "没有成功读取的可信原文，不能判断是否公开披露"
    elif any(marker in reason for marker in (
        "本轮读取的披露中未找到该指标的新数据",
        "最终审核已补充搜索并读取可信原文，仍未找到该指标", "预筛选未命中",
    )):
        stage, explanation = "screening_no_match", "本轮预筛选未命中指标用语，未完成语义核对；不能据此判定没有公开资料"
    else:
        stage, explanation = "extraction_or_validation", "未形成通过核对的指标证据；原始失败原因保留"
    matched = [row for row in checked if row["metric_mentioned"]]
    return {"stage": stage, "explanation": explanation,
            "metric_searches": [{"query": row.get("query", ""), "provider": row.get("provider", ""),
                                 "result_count": len(row.get("results") or [])} for row in searches],
            "company_pages": len(pages), "trusted_pages": len(trusted),
            "matched_pages": len(matched), "checked_sources": (matched or checked)[:3],
            "scope": "公司级已读取页面，仅为核查过程；不等于本指标的入库证据"}


def attach_source_audit(item: dict, report: dict) -> dict:
    """Return a projection, preserving decisions, values and accepted citations."""
    result = dict(item)
    if item.get("status") in {"verified", "no_update"} or item.get("decision") in {"accepted", "unchanged"}:
        return result
    audit = source_audit(item, report)
    result["source_diagnostics"] = audit
    if not (item.get("quote") or item.get("basis")):
        queries = audit["metric_searches"]
        lines = ["核查过程（不是已核准的指标原文）：" + audit["explanation"],
                 f"本指标搜索 {len(queries)} 次；公司报告保存 {audit['company_pages']} 个页面，其中 {audit['trusted_pages']} 个可信页面读取成功。"]
        lines += [f"搜索：{row['query']}（返回 {row['result_count']} 条）" for row in queries[:2]]
        lines += [f"已查阅：{row['url']}" + ("；相关原文片段（尚未核实数值）：" + row["excerpt"] if row["excerpt"] else "；未保存本指标匹配片段")
                  for row in audit["checked_sources"]]
        if not queries:
            lines.append("未保存该指标的独立搜索记录，不能宣称已充分检索。")
        lines.append(audit["scope"])
        result["basis"] = "\n".join(lines)
    return result


def annotate_snapshot(payload: dict) -> dict:
    reports = {}
    for agent in [*payload.get("agents", []), payload.get("final_reviewer") or {}]:
        for report in agent.get("reports", []):
            reports[report["company"]] = report
            report["items"] = [attach_source_audit(item, report) for item in report.get("items", [])]
    payload["result_items"] = [attach_source_audit(item, reports.get(item.get("company"), {}))
                               for item in payload.get("result_items") or []]
    return payload
