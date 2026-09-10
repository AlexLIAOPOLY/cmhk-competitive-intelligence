"""Item-level storage receipts, verified from current files rather than task flags."""
from __future__ import annotations

import fcntl
import hashlib
import json
import re
from pathlib import Path

from .research_freshness import metric_key, period_key

DOMAIN_PATHS = {
    "local": "agent_knowledge/hk_competitor_product_tariffs/agent_verified_facts.json",
    "international": "agent_knowledge/global_top5_operators_2016_2025/agent_verified_facts.json",
    "mainland": "agent_knowledge/quarterly_competitor_metrics_2026-06-18/agent_verified_facts.json",
    "cloud": "agent_knowledge/cloud_vendor_metrics_2026-06-17/agent_verified_facts.json",
}
DOMAIN_LABELS = {"local": "香港运营商资料库", "international": "国际运营商资料库",
                 "mainland": "内地运营商资料库", "cloud": "全球云厂商资料库"}
MAIN_PATH = "agent_knowledge/quarterly_competitor_metrics_2026-06-18/quarterly_metrics.json"


def read_object(path: Path, *, missing_ok: bool = False) -> dict:
    if missing_ok and not path.exists():
        return {}
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"Expected JSON object: {path}")
    return value


def _text(value) -> str:
    return re.sub(r"\s+", " ", str(value if value is not None else "")).strip().casefold()


def identity(item: dict) -> tuple:
    # Only established metric aliases are equivalent. Do not infer entity,
    # currency, fiscal-calendar or scale conversions in the source-fact store.
    period = period_key(item.get("period")) or _text(item.get("period"))
    return (_text(item.get("company")), metric_key(item.get("metric")),
            str(period), _text(item.get("unit")))


def equivalent(left: dict, right: dict) -> bool:
    def value(item):
        return item["value"] if "value" in item else item.get("analysis")
    return (identity(left) == identity(right) and _text(value(left)) == _text(value(right))
            and bool(left.get("evidence_hash"))
            and left.get("evidence_hash") == right.get("evidence_hash")
            and left.get("source_url") == right.get("source_url"))


def project_fact(fact: dict) -> dict:
    sources = fact.get("sources") or []
    first = sources[0] if sources else fact.get("source_url", "")
    if isinstance(first, dict):
        first = first.get("url", "")
    return {**fact, "source_url": first,
            "analysis": fact.get("value", fact.get("analysis", ""))}


def fact_id(item: dict) -> str:
    return str(item.get("id") or hashlib.sha256(json.dumps(
        [identity(item), item.get("value", item.get("analysis")), item.get("evidence_hash")],
        ensure_ascii=False, sort_keys=True).encode()).hexdigest()[:24])


def domain_for(fact: dict) -> str:
    from .research_plan import research_plan
    for task in research_plan():
        if fact.get("company") in task["companies"]:
            return {"hong-kong": "local", "hong_kong": "local", "hk": "local", "local": "local",
                    "mainland": "mainland", "cloud": "cloud"}.get(task["key"], "international")
    return ""


def merge_domain(path: Path, items: list[dict], *, domain: str, run_id: str,
                 generated_at: str, dry_run: bool = False) -> dict:
    """Append without silent drops; reject conflicts and verify the saved bytes."""
    from .six_agent_research import atomic_write_json
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.with_suffix(".lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        previous = read_object(path, missing_ok=True)
        saved = previous.get("facts", [])
        if not isinstance(saved, list) or not all(isinstance(item, dict) for item in saved):
            raise ValueError(f"Invalid fact list: {path}")
        merged = list(saved)
        receipts = []
        for item in items:
            row = {"id": fact_id(item), "company": item.get("company"),
                   "metric": item.get("metric"), "period": item.get("period"), "path": str(path)}
            same = [old for old in merged if identity(old) == identity(item)]
            if (item.get("source_tier") != "official" or not item.get("evidence_hash")
                    or not str(item.get("source_url", "")).startswith(("https://", "http://"))):
                row["status"] = "rejected_evidence"
            elif any(equivalent(item, old) for old in same):
                row["status"] = "already_saved"
            elif same:
                row["status"] = "conflict_preserved"
            else:
                merged.append(item)
                row["status"] = "would_insert" if dry_run else "inserted"
            receipts.append(row)
        changed = len(merged) != len(saved)
        if changed and not dry_run:
            atomic_write_json(path, {**previous, "schema_version": 2, "domain": domain,
                "agent_run_id": run_id, "generated_at_hkt": generated_at, "facts": merged,
                "method": "审核资料保留原报告期、单位及证据；正式指标主表单独审核写入。"})
        actual = read_object(path, missing_ok=True).get("facts", [])
        for item, row in zip(items, receipts):
            row["readback_verified"] = any(equivalent(item, old) for old in actual)
        return {"path": str(path), "facts": len(actual), "submitted_facts": len(items),
                "inserted_facts": sum(row["status"] == "inserted" for row in receipts),
                "already_saved_facts": sum(row["status"] == "already_saved" for row in receipts),
                "confirmed_facts": sum(row["readback_verified"] for row in receipts),
                "ok": all(row["readback_verified"] for row in receipts),
                "changed": changed, "published": changed and not dry_run, "items": receipts}


def audit_storage(root: Path, facts: list[dict], *, expected: int | None = None) -> dict:
    """No writes. Re-read current domain files and formal KPI rows on every call."""
    from cmhk.data.daily_financial_promotion import _incremental_rows
    from .six_agent_research import now
    errors, stores = [], {}
    for domain, relative in DOMAIN_PATHS.items():
        try:
            saved = read_object(root / relative, missing_ok=True).get("facts", [])
            if not isinstance(saved, list) or not all(isinstance(item, dict) for item in saved):
                raise ValueError("Invalid fact list")
            stores[domain] = saved
        except (OSError, ValueError) as exc:
            errors.append(f"{domain}: {type(exc).__name__}")
            stores[domain] = []
    try:
        main_rows = read_object(root / MAIN_PATH, missing_ok=True).get("rows", [])
        if not isinstance(main_rows, list) or not all(isinstance(row, dict) for row in main_rows):
            raise ValueError("Invalid main table")
    except (OSError, ValueError) as exc:
        errors.append(f"main_table: {type(exc).__name__}")
        main_rows = []
    main_index = {(row.get("subject"), row.get("period"), row.get("metric_key")): row for row in main_rows}
    items = []
    for raw in facts:
        fact = project_fact(raw)
        domain = domain_for(fact)
        found = next((old for old in stores.get(domain, []) if equivalent(fact, old)), None)
        row = {"id": fact_id(fact), "company": fact.get("company"), "metric": fact.get("metric"),
               "period": fact.get("period"), "domain": domain, "destination": DOMAIN_LABELS.get(domain, "未识别资料库"),
               "path": DOMAIN_PATHS.get(domain, ""), "status": "saved" if found is not None else "missing",
               "readback_verified": found is not None,
               "matched_metric": found.get("metric") if found is not None else None}
        candidates = _incremental_rows([json.dumps(raw, ensure_ascii=False)])
        if candidates:
            candidate = candidates[0]
            key = (candidate["subject"], candidate["period"], candidate["metric_key"])
            current = main_index.get(key)
            same = bool(current and current.get("daily_evidence_hash") == candidate.get("daily_evidence_hash")
                        and current.get("value") == candidate["value"] and current.get("unit") == candidate["unit"])
            row["main_table"] = {"status": "saved" if same else "existing_preserved" if current else "missing",
                "reason": "正式主表已回读确认" if same else "正式主表已有记录，保留原值" if current else "符合主表条件但未找到记录",
                "subject": key[0], "period": key[1], "metric_key": key[2], "path": MAIN_PATH,
                "current_value": current.get("value") if current else None,
                "candidate_value": candidate["value"], "unit": candidate["unit"]}
        else:
            row["main_table"] = {"status": "source_fact_only", "reason": "保存在资料库；指标定义、原生财年或数值单位不满足当前正式主表转换规则"}
        items.append(row)
    confirmed = sum(row["readback_verified"] for row in items)
    missing_main = sum(row["main_table"]["status"] == "missing" for row in items)
    expected = len(facts) if expected is None else expected
    return {"schema_version": 1, "checked_at": now(), "accepted": expected,
            "records_read": len(facts), "confirmed": confirmed, "missing": max(0, expected - confirmed),
            "main_missing": missing_main, "ok": not errors and len(facts) == expected and confirmed == expected and not missing_main,
            "errors": errors, "items": items,
            "domain_counts": {domain: sum(row["domain"] == domain and row["readback_verified"] for row in items) for domain in DOMAIN_PATHS}}
