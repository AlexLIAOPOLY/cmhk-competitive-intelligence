"""Durable stage retries for temporary failures, separate from evidence rejection."""
from __future__ import annotations

import json
import re
from datetime import datetime, timedelta

MAX_ATTEMPTS = 6
DELAYS = (120, 300, 600, 1200, 1800, 3600)


def recoverable(error):
    text = str(error).lower()
    return any(token in text for token in (
        "配置路由暂不可用", "apikeypoolunavailable", "budget", "rate limit", "rate_limit",
        "限流", "timeout", "timed out", "connection", "暂时", "暂不可用", "429", "502", "503", "504",
        "预筛选未命中", "仍无法读取可信来源", "模型未调用submit_metric",
        "urlerror", "urlopen error", "temporary failure", "temporarily unavailable",
        "nodename nor servname", "name or service not known", "network is unreachable",
        "remote end closed", "broken pipe", "unexpected eof", "http error 500", "http 500",
        "truncatedmodeloutput", "模型输出被截断", "工具参数不完整", "响应未正常完成", "未使用结构化提交工具",
    ))


def cancelled(summary):
    status = str(summary.get("status", ""))
    error = str(summary.get("publication", {}).get("error", ""))
    return bool(summary.get("publication", {}).get("cancelled_by_user")) or status in {"cancelled", "aborted", "stopped"} or bool(
        re.search(r"用户要求中止|不自动续跑|手动停止|用户.*终止", error))


def retryable_metrics(directory):
    path = directory / "candidate_facts.jsonl"
    if not path.exists():
        return 0
    count = 0
    for line in path.read_text().splitlines():
        if not line.strip():
            continue
        fact = json.loads(line)
        if fact.get("research_status") == "error" and recoverable(" ".join(fact.get("reasons") or [])):
            count += 1
    return count


def failure(summary, directory):
    pending = retryable_metrics(directory)
    if pending:
        return "final_review", f"{pending} 项临时故障或未完成语义核对，保留成功指标后续跑"
    publication = summary.get("publication") or {}
    if publication.get("status") == "completed":
        return "", ""
    if (summary.get("recovery") or {}).get("status") == "interrupted" or publication.get("status") == "running":
        phase = "final_review" if summary.get("final_review", {}).get("status") == "running" else "publication"
        return phase, "工作进程中断，保留检查点恢复未完成阶段"
    error = publication.get("error") or publication.get("model_analysis", {}).get("error") or ""
    if recoverable(error) or publication.get("result_status") == "refresh_already_running":
        return "publication", error or "另一发布任务正在执行"
    pages = publication.get("pages") or {}
    domain_errors = "; ".join(str(d.get("error") or "") for d in (publication.get("domains") or {}).values())
    if recoverable(domain_errors):
        return "publication", domain_errors
    if not pages.get("ok") and not pages.get("skipped") and recoverable(pages.get("error", "")):
        return "publication", str(pages["error"])
    return "", error


def schedule(summary, directory, reference):
    prior = summary.get("recovery") or {}
    phase, error = failure(summary, directory)
    if cancelled(summary):
        return {**prior, "status": "cancelled", "next_retry_at": ""}
    if not phase:
        return {**prior, "status": "completed" if summary.get("publication", {}).get("status") == "completed" else "needs_review",
                "next_retry_at": "", "error": error}
    attempts = int(prior.get("attempts", 0))
    exhausted = attempts >= MAX_ATTEMPTS
    return {**prior, "status": "exhausted" if exhausted else "retry_pending", "phase": phase,
            "attempts": attempts, "max_attempts": MAX_ATTEMPTS, "error": error,
            "next_retry_at": "" if exhausted else (reference + timedelta(seconds=DELAYS[min(attempts, len(DELAYS)-1)])).isoformat()}


def due(summary, reference):
    recovery = summary.get("recovery") or {}
    if cancelled(summary) or recovery.get("status") != "retry_pending":
        return False
    if int(recovery.get("attempts", 0)) >= MAX_ATTEMPTS:
        return False
    try:
        return reference >= datetime.fromisoformat(recovery["next_retry_at"])
    except (ValueError, KeyError, TypeError):
        return False
