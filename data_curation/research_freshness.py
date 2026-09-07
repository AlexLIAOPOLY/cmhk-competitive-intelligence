"""Trusted database baseline and conservative incremental-disclosure decisions.

Existing rows are inputs, never verification targets. New observations cannot
replace a stored same-period value through the daily discovery workflow.
"""
from __future__ import annotations
import json
import re
from datetime import datetime
from pathlib import Path

POLICY = "latest_disclosure_incremental_v1"


def metric_key(value):
    text = str(value or "").strip()
    aliases = {"收入/总收益": "收入", "运营收入/总收益": "收入", "总收入": "收入", "云收入/云相关分部收入": "云收入", "营收": "收入", "revenue": "收入", "total_revenue": "收入",
               "net_income": "净利润", "net_profit": "净利润", "ebitda": "EBITDA",
               "capital_expenditures": "资本开支", "capital_expenditure": "资本开支",
               "cloud_revenue": "云收入", "capex": "资本开支", "mobile_arpu": "ARPU"}
    return aliases.get(text, text)


def period_key(value):
    text = str(value or "").lower().replace("’", "'")
    text = re.sub(r"([hq][1-4])[' ’]?(\d{2})(?!\d)", lambda m: m[1] + " 20" + m[2], text)
    years = re.findall(r"20\d{2}", text)
    if not years:
        return None
    year = int(years[-1])
    month_words = "january february march april may june july august september october november december".split()
    span = re.search(r"(january|april|july|october)\s*[-–]\s*(march|june|september|december)\s+(20\d{2})", text)
    if span and ("quarter" in text or re.search(r"\bq[1-4]\b", text)):
        return int(span[3]), month_words.index(span[2]) + 1, "quarter"
    ended = re.search(r"(?:ended|ending|to) (?:on )?(?:\d{1,2} )?([a-z]+)(?: \d{1,2},?)? (20\d{2})", text)
    if ended and ended[1] in month_words:
        year = int(ended[2])
        month = month_words.index(ended[1]) + 1
        grain = "half" if "six months" in text else "quarter" if "quarter" in text or "three months" in text or "three-month" in text else "year" if "year" in text else "date"
        return year, month, grain
    text = re.sub(r"(first|second|third|fourth) quarter", lambda m: "q" + str(["first", "second", "third", "fourth"].index(m[1])+1), text)
    q = re.search(r"q([1-4])|([1-4])q|第([一二三四1-4])季", text)
    if q:
        token = next(v for v in q.groups() if v)
        quarter = "一二三四".index(token) + 1 if token in "一二三四" else int(token)
        return year, quarter * 3, "quarter"
    if re.search(r"h1|1h|first half|six months|上半年|中期", text):
        return year, 6, "half"
    if re.search(r"h2|2h|second half|下半年", text):
        return year, 12, "half"
    if re.search(r"fy|annual|全年|年度", text) or re.fullmatch(r"20\d{2}", text):
        return year, 12, "year"
    iso = re.search(r"20\d{2}-(\d{2})-\d{2}", text)
    if iso:
        return year, int(iso.group(1)), "date"
    return None


def load_baseline(root: Path) -> dict:
    """Read the four existing databases and their published fact layers, without gating old rows."""
    base = root / "agent_knowledge"
    paths = [base / name for name in (
        "hk_competitor_product_tariffs/local_financial_results.json",
        "hk_competitor_product_tariffs/cmhk.data.local_financial_results.json",
        "quarterly_competitor_metrics_2026-06-18/quarterly_metrics.json",
        "global_top5_operators_2016_2025/annual_metrics.json",
        "local_hk_operator_operating_metrics_2016_2025/annual_metrics.json",
        "cloud_vendor_metrics_2026-06-17/cloud_vendor_metrics_2016_2025.json",
        "requested_overview_010304_2016_2025/annual_facts.json",
        "cloud_vendor_metrics_2026-06-17/cloud_vendor_metrics_2023_2025.json",
        "hk_competitor_product_tariffs/agent_verified_facts.json",
        "quarterly_competitor_metrics_2026-06-18/agent_verified_facts.json",
        "global_top5_operators_2016_2025/agent_verified_facts.json",
        "cloud_vendor_metrics_2026-06-17/agent_verified_facts.json")]
    index = {}
    aliases = {"3HK / Hutchison": "3HK", "HKT / csl / 1O1O": "HKT",
               "NTT DOCOMO": "NTT Docomo", "NTT Group": "NTT", "SoftBank Corp.": "SoftBank"}
    def visit(row, inherited=None):
        if isinstance(row, list):
            for value in row:
                visit(value, inherited)
        elif isinstance(row, dict):
            context = {**(inherited or {}), **{k: v for k, v in row.items() if k in
                ("company", "subject", "operator", "vendor", "entity", "period", "unit", "source_url", "publication_date", "fiscal_year", "year")}}
            if row.get("fiscal_year") is not None and not row.get("period"):
                context["period"] = "FY" + str(row["fiscal_year"])
            name = context.get("company") or context.get("subject") or context.get("operator") or context.get("vendor") or context.get("entity")
            company = aliases.get(name, name)
            metric = metric_key(row.get("metric") or row.get("metric_zh") or row.get("metric_key"))
            # Overview focus IDs are domain-dependent (cloud revenue is not group revenue).
            domain = str(row.get("domain") or "")
            focus = row.get("metric")
            if domain in {"01", "02", "03", "04", "local", "international", "mainland", "cloud"}:
                if focus == "revenue" and domain in {"04", "cloud"}:
                    metric = "云收入"
                elif focus == "postpaid":
                    metric = "移动客户数" if domain in {"03", "mainland"} else "后付费用户数"
                elif focus == "investment":
                    metric = "资本开支"
                elif focus == "profit" and domain in {"04", "cloud"}:
                    metric = "经营利润"
            value = row.get("value", row.get("analysis"))
            if company and metric and value not in (None, ""):
                item = {"period": context.get("period") or str(context.get("fiscal_year") or context.get("year") or ""), "value": value,
                        "unit": context.get("unit", ""), "source_url": context.get("source_url") or row.get("official_source_url") or row.get("primary_source_url") or next(iter(row.get("source_urls") or []), ""),
                        "scope": row.get("scope") or row.get("scope_note", "")}
                bucket = index.setdefault(company, {}).setdefault(metric, [])
                if item not in bucket:
                    bucket.append(item)
            for key in ("rows", "facts", "reports", "metrics"):
                if isinstance(row.get(key), list):
                    visit(row[key], context)
    loaded = []
    for path in paths:
        if not path.exists():
            continue
        # An unreadable existing database must not look like an empty baseline.
        visit(json.loads(path.read_text(encoding="utf-8")))
        loaded.append(str(path.relative_to(root)))
    return {"policy": POLICY, "sources": loaded, "companies": index}


def compare_candidate(item: dict, baseline: dict) -> dict:
    """Only a new metric/period qualifies. Preserve stored values at identical or older periods."""
    if item.get("status") != "verified":
        return item
    existing = baseline.get(metric_key(item.get("metric")), [])
    period = period_key(item.get("period"))
    result = dict(item)
    result["baseline"] = existing
    if not existing:
        if period is None or period[0] < datetime.now().year - 1:
            result.update(status="conflict", freshness="freshness_unconfirmed",
                          reason="库内没有该指标可比较的基线，且披露期间不明确或明显陈旧；不能算作最新数据写入。")
        else:
            result["freshness"] = "new_metric"
        return result
    known = [period_key(row.get("period")) for row in existing]
    same = any(str(row.get("period", "")).casefold() == str(item.get("period", "")).casefold()
               or (period is not None and rank == period) for row, rank in zip(existing, known))
    if same:
        result.update(status="no_update", freshness="existing_period",
                      reason="库内已保存该指标同期间数据，沿用可信基线；本轮不重审、不覆盖，不计新增。")
    elif period is None or any(rank is None for rank in known):
        result.update(status="conflict", freshness="period_unresolved",
                      reason="新披露与库内期间无法可靠比较；保留候选供处理，不覆盖已有数据。")
    elif period[:2] < max(rank[:2] for rank in known):
        result.update(status="no_update", freshness="older_period",
                      reason="该披露早于库内最新期间，保留已有数据，不计本轮更新。")
    elif period[0] < datetime.now().year - 1:
        result.update(status="conflict", freshness="stale_disclosure",
                      reason="该披露虽晚于该指标的旧基线，但报告期间明显陈旧；只能作为历史补录候选，不能计为本轮最新披露。")
    else:
        result["freshness"] = "new_period"
    return result
