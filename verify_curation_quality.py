from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parent
BLOCKED_TEXT_RE = re.compile(
    r"captcha|waf|forbidden|access denied|verify you are human|人机验证|访问验证|安全验证|403|429",
    re.IGNORECASE,
)
SUSPICIOUS_PROFIT_SEGMENT_RE = re.compile(
    r"并非\s*净利润|不是\s*净利润|非净利润|指标语义未通过|"
    r"分部|经营费用|營運費用|未扣除折旧|未扣除折舊|"
    r"segment (?:profit|loss)|operating expenses|before depreciation|before amortisation|before impairment",
    re.IGNORECASE,
)


def read_json(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if not path.exists():
        return rows
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            item = json.loads(line)
        except Exception:
            continue
        if isinstance(item, dict):
            rows.append(item)
    return rows


def audit_run_log(root: Path) -> dict[str, Any]:
    rows = read_json(root / "run_log.json", [])
    if not isinstance(rows, list):
        rows = []
    failures: list[dict[str, Any]] = []
    blocked: list[dict[str, Any]] = []
    fallback: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        status = int(row.get("http_status") or 0)
        text = " ".join(
            str(row.get(key) or "")
            for key in ("url", "final_url", "title", "error", "skip_reason", "fallback_reason")
        )
        is_fallback = bool(row.get("evidence_fallback_used"))
        if is_fallback:
            fallback.append(row)
        if not (200 <= status < 400) or row.get("live_fetch_status") not in {"", "success", None} or row.get("error"):
            failures.append(row)
        if BLOCKED_TEXT_RE.search(text) or status in {403, 429}:
            blocked.append(row)
    return {
        "total": len(rows),
        "failures": len(failures),
        "blocked": len(blocked),
        "fallback": len(fallback),
        "failure_samples": failures[:5],
        "blocked_samples": blocked[:5],
        "fallback_samples": fallback[:5],
    }


def audit_curation(root: Path, require_online_search: bool) -> dict[str, Any]:
    latest = read_json(root / "curation_data" / "latest.json", {})
    if not isinstance(latest, dict):
        latest = {}
    facts = read_jsonl(root / "curation_data" / "candidate_facts.jsonl")
    accepted = [item for item in facts if item.get("decision") == "accepted"]
    rejected = [item for item in facts if item.get("decision") == "rejected"]
    review = [item for item in facts if item.get("decision") == "review"]
    missing_verification = [
        item for item in accepted if not isinstance(item.get("search_verification"), dict) or not item.get("search_verification")
    ]
    verification_review = [
        item
        for item in accepted
        if (item.get("search_verification") or {}).get("decision") == "needs_review"
    ]
    weak_verification = [
        item
        for item in accepted
        if int((item.get("search_verification") or {}).get("vote_count") or 0) < 2
        or (item.get("search_verification") or {}).get("decision")
        not in {"majority_confirmed", "majority_corrected", "unchanged"}
    ]
    online_checked = sum(
        bool((item.get("search_verification") or {}).get("online_search", {}).get("enabled"))
        for item in accepted
    )
    online_votes = sum(
        1
        for item in accepted
        for vote in (item.get("search_verification") or {}).get("votes", [])
        if vote.get("kind") in {"web_search", "source_page"}
    )
    suspicious_profit_segments = [
        item
        for item in accepted
        if re.search(r"净利润|利润|溢利|profit|income|loss", str(item.get("metric") or ""), re.IGNORECASE)
        and SUSPICIOUS_PROFIT_SEGMENT_RE.search(
            f"{item.get('value', '')}\n{item.get('basis', '')}\n{item.get('note', '')}"
        )
        and (item.get("search_verification") or {}).get("decision") != "majority_corrected"
    ]
    extra = latest.get("extra") if isinstance(latest.get("extra"), dict) else {}
    return {
        "run_id": latest.get("run_id", ""),
        "tasks": int(latest.get("tasks") or 0),
        "latest_accepted": int(latest.get("accepted") or 0),
        "latest_rejected": int(latest.get("rejected") or 0),
        "latest_review": int(latest.get("review") or 0),
        "latest_gaps": int(latest.get("gaps") or 0),
        "latest_evidence_gaps": int(extra.get("evidence_gaps") or 0),
        "latest_quality_rejected": int(extra.get("quality_rejected") or 0),
        "facts": len(facts),
        "accepted": len(accepted),
        "rejected": len(rejected),
        "review": len(review),
        "missing_search_verification": len(missing_verification),
        "search_verification_review": len(verification_review),
        "weak_search_verification": len(weak_verification),
        "online_checked": online_checked,
        "online_votes": online_votes,
        "suspicious_profit_segments": len(suspicious_profit_segments),
        "require_online_search": require_online_search,
        "missing_verification_samples": missing_verification[:5],
        "weak_verification_samples": weak_verification[:5],
        "suspicious_profit_segment_samples": suspicious_profit_segments[:5],
        "review_samples": review[:5] + verification_review[:5],
    }


def build_report(root: Path, require_online_search: bool) -> dict[str, Any]:
    run_log = audit_run_log(root)
    curation = audit_curation(root, require_online_search)
    issues: list[str] = []
    if run_log["total"] <= 0:
        issues.append("爬虫运行日志为空")
    if run_log["failures"]:
        issues.append(f"仍有 {run_log['failures']} 个链接抓取失败")
    if run_log["blocked"]:
        issues.append(f"仍有 {run_log['blocked']} 个链接疑似被拦截")
    if run_log["fallback"]:
        issues.append(f"仍有 {run_log['fallback']} 个链接使用历史证据回退")
    if curation["facts"] <= 0:
        issues.append("数据整理候选事实为空")
    if curation["latest_rejected"] or curation["latest_review"] or curation["latest_gaps"]:
        issues.append("最新整理摘要仍有 rejected/review/gaps")
    if curation["latest_evidence_gaps"] or curation["latest_quality_rejected"]:
        issues.append("最新整理摘要仍有 evidence_gaps/quality_rejected")
    if curation["rejected"] or curation["review"]:
        issues.append("candidate_facts 中仍有 rejected/review")
    if curation["missing_search_verification"]:
        issues.append(f"仍有 {curation['missing_search_verification']} 条 accepted fact 未经过搜索验证")
    if curation["search_verification_review"]:
        issues.append("搜索验证存在未形成多数口径的 accepted fact")
    if curation["weak_search_verification"]:
        issues.append(f"仍有 {curation['weak_search_verification']} 条 accepted fact 搜索验证票数不足或决策不稳")
    if curation["suspicious_profit_segments"]:
        issues.append(f"仍有 {curation['suspicious_profit_segments']} 条利润类事实疑似使用分部/经营费用片段冒充")
    if require_online_search and curation["online_checked"] <= 0:
        issues.append("要求联网搜索验证，但当前 accepted fact 没有 online_search 记录")
    return {
        "ok": not issues,
        "issues": issues,
        "run_log": run_log,
        "curation": curation,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="验收爬虫与数据整理发布质量。")
    parser.add_argument("--root", default=str(ROOT))
    parser.add_argument("--require-online-search", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    report = build_report(Path(args.root), require_online_search=args.require_online_search)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
