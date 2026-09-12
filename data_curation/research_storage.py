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
        from .research_contracts import source_fact_error
        from .research_freshness import load_baseline
        root = next((p.parent for p in path.parents if p.name == "agent_knowledge"), None)
        baseline = load_baseline(root).get("companies", {}) if root else None
        for item in items:
            row = {"id": fact_id(item), "company": item.get("company"),
                   "metric": item.get("metric"), "period": item.get("period"), "path": str(path)}
            same = [old for old in merged if identity(old) == identity(item)]
            series_error = source_fact_error(item, baseline) if baseline is not None else ""
            if (item.get("source_tier") != "official" or not item.get("evidence_hash")
                    or not str(item.get("source_url", "")).startswith(("https://", "http://"))):
                row["status"] = "rejected_evidence"
            elif series_error:
                row.update(status="excluded_series", reason=series_error)
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
            row["readback_verified"] = (row["status"] in {"inserted", "already_saved"}
                                        and any(equivalent(item, old) for old in actual))
        return {"path": str(path), "facts": len(actual), "submitted_facts": len(items),
                "inserted_facts": sum(row["status"] == "inserted" for row in receipts),
                "already_saved_facts": sum(row["status"] == "already_saved" for row in receipts),
                "confirmed_facts": sum(row["readback_verified"] for row in receipts),
                "ok": all(row["readback_verified"] for row in receipts),
                "changed": changed, "published": changed and not dry_run, "items": receipts}


def audit_storage(root: Path, facts: list[dict], *, expected: int | None = None) -> dict:
    """No writes. Re-read current domain files and formal KPI rows on every call."""
    from .research_kpi import POLICY, CARRIER_PATH, CLOUD_PATH, normalize_fact, formal_indexes, row_key, row_matches
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
        indexes = formal_indexes(root)
    except (OSError, ValueError) as exc:
        errors.append(f"main_table: {type(exc).__name__}")
        indexes = {CARRIER_PATH: {}, CLOUD_PATH: {}}
    items = []
    for raw in facts:
        fact = project_fact(raw)
        domain = domain_for(fact)
        found = next((old for old in stores.get(domain, []) if equivalent(fact, old)), None)
        row = {"id": fact_id(fact), "company": fact.get("company"), "metric": fact.get("metric"),
               "period": fact.get("period"), "domain": domain, "destination": DOMAIN_LABELS.get(domain, "未识别资料库"),
               "evidence_path": DOMAIN_PATHS.get(domain, ""), "evidence_saved": found is not None,
               "value": raw.get("value"), "unit": raw.get("unit")}
        candidate, destination, error = normalize_fact(raw)
        if candidate:
            key = row_key(candidate, destination)
            current = indexes[destination].get(key)
            same = row_matches(current, candidate)
            reason = "正式表中的数值、单位和来源证据已回读确认" if same else "正式表出现同期间其他记录，需退回Agent核对" if current else "正式表未找到本次提交的指标记录"
            row["main_table"] = {"status": "written" if same else "not_written", "reason": reason,
                "subject": key[0], "period": key[1], "period_end": candidate.get("period_end"),
                "metric_key": key[2], "metric_zh": candidate.get("metric_zh"), "path": destination,
                "current_value": current.get("value") if current else None,
                "candidate_value": candidate["value"], "unit": candidate["unit"],
                "currency": candidate.get("currency"), "source_url": candidate.get("official_source_url"),
                "row_key": dict(zip(("vendor", "fiscal_year", "metric_key") if destination == CLOUD_PATH else ("subject", "period", "metric_key"), key))}
        else:
            row["main_table"] = {"status": "not_written", "reason": error, "path": destination}
        row.update(status=row["main_table"]["status"], readback_verified=row["main_table"]["status"] == "written",
                   path=destination, destination=DOMAIN_LABELS.get(domain, "未知数据库").replace("资料库", "正式指标表"),
                   reason=row["main_table"]["reason"])
        items.append(row)
    confirmed = sum(row["readback_verified"] for row in items)
    missing_main = sum(row["status"] == "not_written" for row in items)
    expected = len(facts) if expected is None else expected
    return {"schema_version": 2, "policy": POLICY, "checked_at": now(), "accepted": expected,
            "written": confirmed, "not_written": max(0, expected - confirmed),
            "records_read": len(facts), "confirmed": confirmed, "missing": max(0, expected - confirmed),
            "main_missing": missing_main, "ok": not errors and len(facts) == expected and confirmed == expected and not missing_main,
            "errors": errors, "items": items,
            "domain_counts": {domain: sum(row["domain"] == domain and row["readback_verified"] for row in items) for domain in DOMAIN_PATHS}}
