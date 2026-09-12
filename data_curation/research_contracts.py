"""Daily research follows established series, never creates a new reporting cadence."""
from __future__ import annotations

import calendar
from collections import Counter
from datetime import date, datetime
import re

VERSION = "stored_series_only_v2"
GRAINS = {"annual": "year", "year": "year", "half_year": "half", "semiannual": "half",
          "half": "half", "quarter": "quarter", "quarterly": "quarter"}
LABELS = {"year": "全年/原生财年", "half": "完整半年", "quarter": "独立单季"}


def field_key(value):
    return {"net_profit": "net_income", "capital_expenditure": "capex", "capital_expenditures": "capex",
            "postpaid_connections": "postpaid_subscribers"}.get(value, value)


def canonical_company(name):
    return {"3HK / Hutchison": "3HK", "HKT / csl / 1O1O": "HKT",
            "NTT DOCOMO": "NTT Docomo", "NTT Group": "NTT", "SoftBank Corp.": "SoftBank",
            "Microsoft Azure / Intelligent Cloud": "Microsoft Azure",
            "Tencent Cloud / Tencent FBS proxy": "Tencent Cloud", "Huawei Cloud / Cloud Computing": "Huawei Cloud"}.get(name, name)


def formal_record_fact(row):
    from .research_freshness import metric_key
    company = canonical_company(row.get("company") or row.get("subject") or row.get("vendor"))
    metric = metric_key(row.get("original_metric") or row.get("metric_key"))
    if metric in {"用户数", "客户数/用户数"} and company in {"中国移动", "中国电信", "中国联通", "中国广电"}:
        metric = "移动客户数"
    return {"company": company, "metric": metric, "period": row.get("original_period") or row.get("period") or "FY" + str(row.get("fiscal_year", ""))}


def is_daily_row(row):
    return bool(row.get("daily_research_run_id") or row.get("daily_fact_id")
                or row.get("daily_crawl_row_ref") or row.get("daily_evidence_hash")
                or row.get("verification_method") in {
                    "daily_agent_gate_plus_issuer_report_index", "incremental_official_source_extraction"})


def row_end(row):
    from .research_freshness import period_key
    explicit = str(row.get("period_end") or "")
    try:
        return date.fromisoformat(explicit[:10])
    except ValueError:
        # Legacy tables retain display strings such as "Dec '25 Dec 31, 2025".
        # Their actual date, especially a native fiscal half, outranks the label.
        match = re.search(r"[A-Za-z]{3,9} \d{1,2},? \d{4}", explicit)
        if match:
            for fmt in ("%b %d, %Y", "%B %d, %Y", "%b %d %Y", "%B %d %Y"):
                try:
                    return datetime.strptime(match[0], fmt).date()
                except ValueError:
                    pass
        rank = period_key(row.get("period"))
        if rank:
            return date(rank[0], rank[1], calendar.monthrange(rank[0], rank[1])[1])
    return None


def build_contract(company, metric, rows):
    """Select the established physical series, excluding daily additions as schema evidence."""
    from .research_plan import ASSIGNMENTS
    from .research_freshness import period_key
    assignment = next((a for a in ASSIGNMENTS if company in a.companies), None)
    all_rows = rows
    rows = [r for r in rows if not is_daily_row(r)]
    # Annual histories own international/cloud cadence; the carrier table owns
    # HK/mainland cadence. Auxiliary annual overviews must not redefine them.
    if assignment:
        annual = "global_top5_operators_2016_2025/annual_metrics.json"
        overview = "requested_overview_010304_2016_2025/annual_facts.json"
        priorities = (["cloud_vendor_metrics_2023_2025.json", "cloud_vendor_metrics_2016_2025.json", overview]
                      if assignment.key == "cloud" else
                      ["quarterly_metrics.json", "local_financial_results.json", "local_hk_operator_operating_metrics_2016_2025/annual_metrics.json", overview]
                      if assignment.key == "hong-kong" else
                      ["quarterly_metrics.json", annual, overview] if assignment.key == "mainland" else
                      [annual, overview, "quarterly_metrics.json"])
        for preferred in priorities:
            selected = [r for r in rows if str(r.get("source_path", "")).endswith(preferred)]
            if selected:
                rows = selected
                break
    counts = Counter(GRAINS.get(r.get("grain")) or (period_key(r.get("period")) or (None, None, None))[2]
                     for r in rows)
    counts.pop(None, None)
    counts.pop("date", None)
    ordered = counts.most_common()
    if not ordered or (len(ordered) > 1 and ordered[0][1] == ordered[1][1]):
        return {"version": VERSION, "enabled": False, "company": company, "metric": metric,
                "reason": "正式库未配置明确的该公司指标序列或报告周期，本轮不新增指标/口径"}
    grain = ordered[0][0]
    matching = [r for r in rows if (GRAINS.get(r.get("grain")) or
                (period_key(r.get("period")) or (None, None, None))[2]) == grain]
    fields = sorted({field_key(r["field"]) for r in matching if r.get("field")})
    # Valid later daily rows advance freshness, but never define the schema.
    matching += [r for r in all_rows if is_daily_row(r)
                 and (GRAINS.get(r.get("grain")) or (period_key(r.get("period")) or (None, None, None))[2]) == grain
                 and (not fields or field_key(r.get("field")) in fields)]
    populated = [r for r in matching if r.get("value") not in (None, "")]
    newest = max(populated or matching, key=lambda r: row_end(r) or date.min)
    return {"version": VERSION, "enabled": True, "company": company, "metric": metric,
            "grain": grain, "has_baseline": bool(populated), "period_label": LABELS[grain], "latest_period": newest.get("period"),
            "latest_period_end": (row_end(newest).isoformat() if row_end(newest) else ""),
            "unit": newest.get("unit", ""), "currency": newest.get("currency", ""),
            "scope": newest.get("scope", ""), "source_path": rows[0].get("source_path", ""),
            "fields": fields,
            "template_periods": list(dict.fromkeys(str(r.get("period")) for r in matching))[-4:]}


def contract_for(company, metric, baseline):
    from .research_freshness import metric_key
    key = metric_key(metric)
    contracts = (baseline or {}).get("_contracts", {})
    return contracts.get(key) or build_contract(company, key, (baseline or {}).get(key, []))


def next_period_end(contract):
    try:
        previous = date.fromisoformat(contract["latest_period_end"])
        months = {"year": 12, "half": 6, "quarter": 3}[contract["grain"]]
        year, month0 = divmod(previous.year * 12 + previous.month - 1 + months, 12)
        return date(year, month0 + 1, calendar.monthrange(year, month0 + 1)[1])
    except (ValueError, KeyError):
        return None


def planning_outcome(company, metric, baseline, *, today=None):
    """No network/model work for undeclared series or a period that has not ended."""
    contract = contract_for(company, metric, baseline)
    item = {"company": company, "metric": metric, "value": "", "storage_contract": contract}
    if not contract["enabled"]:
        return {**item, "status": "out_of_scope", "freshness": "unconfigured_series", "reason": contract["reason"]}
    end = next_period_end(contract)
    if contract.get("has_baseline") and end and (today or date.today()) < end:
        return {**item, "status": "no_update", "freshness": "next_period_not_closed",
                "period": contract["latest_period"], "baseline": (baseline or {}).get(metric, []),
                "reason": f"库内已有{contract['latest_period']}；仅更新{contract['period_label']}，下个完整期间{end.isoformat()}尚未结束，无需搜索或入库"}
    return None


def candidate_error(company, metric, period, baseline):
    from .research_freshness import period_key
    contract = contract_for(company, metric, baseline)
    if not contract["enabled"]:
        return contract["reason"]
    rank = period_key(period)
    if rank and rank[2] != contract["grain"]:
        return f"本指标只接收{contract['period_label']}，候选{period}不符合库内报告周期，不纳入本轮"
    return ""


def matching_baseline(company, metric, baseline):
    from .research_freshness import metric_key, period_key
    contract = contract_for(company, metric, baseline)
    return [r for r in (baseline or {}).get(metric_key(metric), [])
            if (GRAINS.get(r.get("grain")) or (period_key(r.get("period")) or (None, None, None))[2]) == contract.get("grain")
            and (not contract.get("source_path") or r.get("source_path") == contract["source_path"] or is_daily_row(r))
            and (not contract.get("fields") or field_key(r.get("field")) in contract["fields"])]


def formal_row_error(fact, row, baseline):
    contract = contract_for(fact.get("company"), fact.get("metric"), baseline)
    error = candidate_error(fact.get("company"), fact.get("metric"), fact.get("period"), baseline)
    if error:
        return error
    if contract.get("fields") and field_key(row["metric_key"]) not in contract["fields"]:
        return "候选指标口径与正式库字段不同（如有机收入、地区ARPU不能替代既有口径），不纳入本轮"
    # Exact scale conversion is allowed, changing the currency is not.
    import re
    expected = re.findall(r"HKD|USD|CNY|RMB|SGD|AUD|JPY|KRW|EUR|GBP|INR|AED|SAR", str(contract.get("unit")) + " " + str(contract.get("currency")), re.I)
    if expected:
        currencies = {v.upper().replace("RMB", "CNY") for v in expected}
        actual = str(row.get("currency") or row.get("unit", "")).upper().replace("RMB", "CNY")
        if not any(v in actual for v in currencies):
            return "候选币种与正式库既有币种不符，不做日更汇率换算"
    return ""


def source_fact_error(item, baseline):
    """Check archived source-fact format; this never grants evidence approval."""
    from .research_freshness import period_key
    from .research_kpi import normalize_fact
    company = canonical_company(item.get("company"))
    contract_error = candidate_error(company, item.get("metric"), item.get("period"), baseline.get(company, {}))
    if contract_error:
        return contract_error
    if not period_key(item.get("period")):
        return "旁路资料未注明可匹配正式序列的报告期，不能作为入库指标"
    # Only the adapter's normalized field, period and unit are used. This clone
    # is discarded; the actual writer still verifies the original evidence.
    parsed = {**item, "company": company, "value": item.get("value", item.get("analysis", "")),
              "decision": "accepted", "status": "ok", "freshness": "new_period",
              "source_tier": "official", "quality_score": 1, "entity_supported": True,
              "metric_supported": True, "value_supported": True,
              "evidence_hash": item.get("evidence_hash") or "format-check-only",
              "sources": item.get("sources") or [item.get("source_url", "")]}
    row, _, error = normalize_fact(parsed)
    return error or formal_row_error(parsed, row, baseline.get(company, {}))


def search_qualifier(contract):
    end = next_period_end(contract)
    if not contract.get("enabled"):
        return ""
    year = end.year if end else date.today().year
    native = " native fiscal year" if "FY" in str(contract.get("latest_period", "")) else ""
    period = {"half": '"six months" interim half-year -"full year"',
              "quarter": '"three months" quarterly -"nine months"',
              "year": '"full year" annual -quarterly -interim'}[contract["grain"]]
    return f"{year}{native} {period}"
