"""Typed, source-preserving contract between final review and the four databases.

An archived source is not a KPI write. Every submitted item either matches a
formal row on readback or has a concrete rejection reason.
"""
from __future__ import annotations

import calendar
import json
import re
from decimal import Decimal
from pathlib import Path

POLICY = "formal_kpi_binary_v1"
CARRIER_PATH = "agent_knowledge/quarterly_competitor_metrics_2026-06-18/quarterly_metrics.json"
CLOUD_PATH = "agent_knowledge/cloud_vendor_metrics_2026-06-17/cloud_vendor_metrics_2023_2025.json"
# Fiscal labels are preserved. These month ends never imply calendar quarters.
FISCAL_END = {"SmarTone": 6, "HKBN": 8, "Singtel": 3, "Telstra": 6,
              "NTT": 3, "NTT Docomo": 3, "KDDI": 3, "SoftBank": 3,
              "BT": 3, "Vodafone": 3, "Bharti Airtel": 3, "Reliance Jio": 3,
              "Microsoft Azure": 6, "Oracle Cloud": 5, "Alibaba Cloud": 3}
NUMBER = r"\d+(?:,\d{3})*(?:\.\d+)?"
CURRENCY = r"Hong Kong dollars?|Australian dollars?|Billions of yen|yen|HKD|HK\$|USD|US\$|RMB|CNY|SGD|S\$|AUD|A\$|JPY|KRW|EUR|GBP|INR|AED|SAR|€|£"
SCALE = r"trillions?|billions?|millions?|\bbil\b|\bbn\b|\bm\b|百万|百萬|亿元|億港元"


def _currency(token):
    key = token.lower()
    return {"hk$": "HKD", "us$": "USD", "s$": "SGD", "a$": "AUD", "rmb": "CNY",
            "€": "EUR", "£": "GBP", "yen": "JPY", "billions of yen": "JPY",
            "hong kong dollars": "HKD", "hong kong dollar": "HKD",
            "australian dollars": "AUD", "australian dollar": "AUD"}.get(key, token.upper())


def exact_amount(value, unit, *, per_customer=False):
    text = str(value) + " " + str(unit)
    # "Billions of yen" encodes currency AND magnitude.
    text = re.sub("Billions of yen", "JPY billion", text, flags=re.I)
    text = re.sub(r"([£$])m\b", r"\1 million", text, flags=re.I)
    codes = {_currency(t) for t in re.findall(CURRENCY, text, re.I)}
    scales = re.findall(SCALE, text, re.I)
    multipliers = {1000000 if s.lower().startswith("trillion") else 1000 if s.lower().startswith("bil") or s.lower() == "bn" else 100 if s in {"亿元", "億港元"} else 1 for s in scales}
    if per_customer and not scales:
        multipliers = {1}
    numbers = re.findall(NUMBER, str(value))
    remainder = re.sub(CURRENCY, "", text, flags=re.I)
    remainder = re.sub(SCALE, "", remainder, flags=re.I)
    remainder = re.sub(NUMBER, "", remainder).strip()
    # A bare dollar sign is accepted only beside an explicit unambiguous code.
    if len(codes) == 1:
        remainder = remainder.replace("$", "").strip()
    if len(codes) != 1 or len(multipliers) != 1 or len(numbers) != 1 or remainder not in {"", "-", "+"}:
        return None
    amount = Decimal(numbers[0].replace(",", "")) * next(iter(multipliers))
    if remainder == "-":
        amount = -amount
    return (int(amount) if amount == amount.to_integral() else float(amount)), next(iter(codes))


def formal_period(company, raw):
    from .research_freshness import period_key
    text = str(raw or "")
    rank = period_key(text)
    end_month = FISCAL_END.get(company, 12)
    # Explicit native FY/Q labels require an explicit company fiscal adapter.
    fiscal_q = re.search(r"FY\s*(20\d{2})\s*[/ -]\s*(?:Q([1-4])|([1-4])Q)", text, re.I)
    if fiscal_q and company in FISCAL_END:
        year, q = int(fiscal_q[1]), int(fiscal_q[2] or fiscal_q[3])
        # Japanese issuers label the fiscal year by its starting calendar year.
        end_year = year + 1 if company in {"NTT", "NTT Docomo", "KDDI", "SoftBank"} else year
        month_total = end_year * 12 + end_month - (4 - q) * 3
        year_end, month_end = divmod(month_total - 1, 12)
        month_end += 1
        return f"Q{q} FY{year}", f"{year_end:04d}-{month_end:02d}-{calendar.monthrange(year_end, month_end)[1]}", "quarter", str(year)
    if not rank:
        return None
    year, month, grain = rank
    explicit_end = bool(re.search(r"ended|ending|截至|止年度|\d{4}-\d{2}-\d{2}", text, re.I))
    if company in FISCAL_END and grain != "year" and not explicit_end:
        return None
    if company in FISCAL_END and grain == "year":
        if not explicit_end or month != end_month:
            return None
        label_year = year - 1 if company in {"NTT", "NTT Docomo", "KDDI", "SoftBank"} else year
        label = f"FY{label_year}"
    elif company in FISCAL_END and grain == "quarter":
        if (month - end_month) % 3:
            return None
        q = ((month - end_month - 1) % 12) // 3 + 1
        fy_end = year if month <= end_month else year + 1
        fy = fy_end - 1 if company in {"NTT", "NTT Docomo", "KDDI", "SoftBank"} else fy_end
        label = f"Q{q} FY{fy}"
    elif company in FISCAL_END and grain == "half":
        if (month - end_month) % 6:
            return None
        fy_end = year if month <= end_month else year + 1
        fy = fy_end - 1 if company in {"NTT", "NTT Docomo", "KDDI", "SoftBank"} else fy_end
        label = f"H{2 if month == end_month else 1} FY{fy}"
    else:
        label = f"FY{year}" if grain == "year" else f"H{month // 6} {year}" if grain == "half" and month in {6, 12} else f"Q{month // 3} {year}" if grain == "quarter" and month in {3, 6, 9, 12} else ""
    if not label:
        return None
    return label, f"{year:04d}-{month:02d}-{calendar.monthrange(year, month)[1]}", "annual" if grain == "year" else "half_year" if grain == "half" else grain, str(label.replace("FY", "").split()[-1])


def normalize_fact(fact):
    """Return (formal row, destination, error). Never guess an amount or a scope."""
    from .research_plan import ASSIGNMENTS
    from .research_freshness import metric_key
    from cmhk.data.daily_financial_promotion import METRICS, _record
    company = fact.get("company")
    assignment = next((t for t in ASSIGNMENTS if company in t.companies), None)
    destination = CLOUD_PATH if assignment and assignment.key == "cloud" else CARRIER_PATH
    if not assignment:
        return None, destination, "公司未配置正式数据库归属"
    if (fact.get("decision") != "accepted" or fact.get("status") != "ok"
            or fact.get("freshness") not in {"new_metric", "new_period"}
            or fact.get("source_tier") != "official" or float(fact.get("quality_score") or 0) < .85
            or not all(fact.get(k) for k in ("entity_supported", "metric_supported", "value_supported", "evidence_hash"))):
        return None, destination, "未通过公司、指标、数值、来源或新增期间审核"
    sources = [u for u in fact.get("sources", []) if isinstance(u, str) and u.startswith("https://")]
    if not sources:
        return None, destination, "缺少可追溯的官方原文链接"
    metric = metric_key(fact.get("metric"))
    basis = str(fact.get("basis", ""))
    mapped = METRICS.get(str(metric).casefold())
    kind = "money"
    if metric == "EBITDA或经营利润":
        return None, destination, "指标同时写为EBITDA和经营利润，须在Agent终审明确具体口径后提交"
    if metric == "云收入":
        mapped = ("cloud_revenue", "云收入")
    elif metric in {"经营利润", "营业利润"}:
        mapped = ("operating_income", "经营利润")
    elif metric in {"ARPU", "移动ARPU"}:
        mapped, kind = ("arpu", "ARPU（原文口径）"), "arpu"
    elif metric in {"客户数/用户数", "用户数", "客户数", "移动客户数"}:
        mapped, kind = ("subscribers", "用户数（原文口径）"), "count"
    elif metric == "站址数":
        mapped, kind = ("tower_sites", "站址数"), "count"
    elif metric == "Open RAN" and re.search(r"of wireless traffic|无线流量", basis, re.I):
        mapped, kind = ("open_ran_traffic_share", "Open RAN无线流量占比"), "percent"
    elif metric == "AI":
        if re.search(r"AIDC revenue", basis, re.I) and "year-on-year" not in str(fact.get("value", "")):
            mapped = ("ai_data_center_revenue", "AI数据中心收入")
        elif re.search(r"AI-related business revenues:\s*Up\s*\d", basis, re.I):
            mapped, kind = ("ai_revenue_growth_yoy", "AI相关业务收入同比增长"), "percent"
    if not mapped:
        reason = "只披露宽带速率范围，缺少可写入资费表的具体套餐、价格和合约" if metric == "家宽套餐" else f"指标“{metric}”尚无明确的正式表字段，须在Agent终审补齐指标定义"
        return None, destination, reason
    # Keep regional, postpaid and aggregate operating definitions in distinct fields.
    explanation = " ".join(fact.get("reasons") or [])
    if kind == "arpu":
        if re.search(r"postpaid.*(?:ARPU|mobile)|ARPU.*postpaid", explanation + " " + basis, re.I):
            mapped = ("postpaid_mobile_arpu", "后付费移动ARPU")
        elif "excluding MVNO" in explanation:
            mapped = ("mobile_arpu_excluding_mvno", "移动ARPU（不含MVNO）")
        elif re.search(r"Telef[oó]nica Espa[nñ]a", explanation, re.I):
            mapped = ("spain_arpu", "西班牙业务ARPU")
        elif re.search(r"Mobile ARPU", explanation, re.I):
            mapped = ("mobile_arpu", "移动ARPU")
    if kind == "count" and mapped[0] == "subscribers":
        if re.search(r"stc KSA.s mobile subscribers", basis, re.I):
            mapped = ("ksa_mobile_subscribers", "沙特业务移动用户数")
        elif re.search(r"aggregate subscriber", explanation, re.I):
            mapped = ("aggregate_subscribers", "合计用户数")
    period = formal_period(company, fact.get("period"))
    if not period:
        return None, destination, "报告期缺少可确认的起止时间或原生财年定义"
    if destination == CLOUD_PATH and period[2] != "annual":
        return None, destination, "云厂商正式年度表需要全年口径，本条不是全年数据"
    if destination == CLOUD_PATH and kind != "money":
        return None, destination, "本条不是云厂商年度财务指标，需明确对应表和字段后提交"
    value, unit = str(fact.get("value", "")), str(fact.get("unit", ""))
    if kind in {"money", "arpu"}:
        amount = exact_amount(value, unit, per_customer=kind == "arpu")
        if amount is None:
            return None, destination, "金额不是精确单值，或币种/数量级未明确（超过、范围、单独$符号不能当作精确金额）"
        number, currency = amount
        formal_unit = currency if kind == "arpu" else f"millions {currency}"
    else:
        numbers = re.findall(NUMBER, value)
        if len(numbers) != 1:
            return None, destination, "数值不是可独立写入的精确单值"
        remainder = re.sub(NUMBER, "", value + " " + unit)
        if kind == "count":
            scale_tokens = re.findall(r"million|billion|thousand|千|万|百萬|百万", value + " " + unit, re.I)
            scales = {1000000 if s.lower() in {"million", "百萬", "百万"} else 1000000000 if s.lower() == "billion" else 10000 if s == "万" else 1000 for s in scale_tokens}
            remainder = re.sub(r"million|billion|thousand|subscribers?|customers?|sites?|人|户|戶|个|千|万|百萬|百万", "", remainder, flags=re.I).strip()
            if remainder or len(scales) > 1:
                return None, destination, "用户数或站址数的数量级/单位不明确"
            number = Decimal(numbers[0].replace(",", "")) * next(iter(scales), 1)
            formal_unit = "sites" if kind == "count" and mapped[0] == "tower_sites" else "subscribers"
        else:
            remainder = re.sub(r"%|percent|of wireless traffic|year-on-year|up", "", remainder, flags=re.I).strip()
            if remainder or not re.search(r"%|percent", value + " " + unit, re.I):
                return None, destination, "比例数值或对应的统计口径不明确"
            number, formal_unit = Decimal(numbers[0].replace(",", "")), "percent"
        number = int(number) if number == int(number) else float(number)
    subject = {"HKT": "HKT / csl / 1O1O", "3HK": "3HK / Hutchison"}.get(company, company)
    row = _record(subject=subject, period=period[0], metric_key=mapped[0], metric_zh=mapped[1], value=number,
                  unit=formal_unit, source_url=sources[0], source_label="本轮终审通过的官方数据", evidence=basis,
                  verification_sources=[{"url": u, "label": "官方原文", "evidence": basis} for u in sources],
                  row_ref=fact.get("row_ref", ""), evidence_hash=fact["evidence_hash"])
    row.update(period_end=period[1], grain=period[2], disclosure_frequency=period[2],
               original_period=fact.get("period"), original_metric=fact.get("metric"),
               original_value=fact.get("value"), original_unit=fact.get("unit"),
               scope_note="；".join(fact.get("reasons") or []), daily_fact_id=fact.get("id", ""),
               daily_research_run_id=fact.get("research_run_id", ""))
    if destination == CLOUD_PATH:
        row.update(vendor=company, category="cloud", fiscal_year=period[3], fiscal_year_end=period[1][5:],
                   currency=currency, unit="millions", official_unit="millions", primary_source_url=sources[0])
    return row, destination, ""


def row_key(row, destination):
    return (row.get("vendor") if destination == CLOUD_PATH else row.get("subject"),
            row.get("fiscal_year") if destination == CLOUD_PATH else row.get("period"), row.get("metric_key"))


def row_matches(current, candidate):
    return bool(current and current.get("daily_evidence_hash") == candidate.get("daily_evidence_hash")
                and current.get("value") == candidate.get("value") and current.get("unit") == candidate.get("unit")
                and current.get("currency") == candidate.get("currency"))


def formal_indexes(root):
    from .research_storage import read_object
    indexes = {}
    for path in (CARRIER_PATH, CLOUD_PATH):
        rows = read_object(root / path, missing_ok=True).get("rows", [])
        if not isinstance(rows, list) or not all(isinstance(row, dict) for row in rows):
            raise ValueError(f"Invalid formal table: {path}")
        index = {row_key(row, path): row for row in rows}
        if len(index) != len(rows):
            raise ValueError(f"Duplicate formal keys: {path}")
        indexes[path] = index
    return indexes


def prepare_facts(root, facts, run_id, *, allow_replay=False):
    """Agent-side last check: remove existing periods and aliases before writing."""
    from .research_freshness import load_baseline, metric_key, period_key
    indexes = formal_indexes(root)
    baseline = load_baseline(root).get("companies", {})
    seen, output, decisions = {}, [], []
    for original in facts:
        fact = dict(original)
        if allow_replay and fact.get("preflight_original"):
            fact.update(fact["preflight_original"])
        if fact.get("decision") != "accepted":
            if fact.get("research_status") == "no_update":
                previous = baseline.get(fact.get("company"), {}).get(metric_key(fact.get("metric")), [])
                fact.setdefault("preflight_original", {k: fact.get(k) for k in
                                ("decision", "status", "research_status", "freshness", "reasons")})
                if previous:
                    fact["latest_baseline"] = max(previous, key=lambda r: period_key(r.get("period")) or (0, 0, ""))
                    fact["write_preflight"] = {"status": "existing", "reason": "Agent已回查正式数据，库内已有该指标；本条不提交写入"}
                else:
                    reason = "此前标为库内已有，但本次未查到正式指标记录；需重新研究核实"
                    fact.update(decision="review", research_status="conflict", status="unavailable", reasons=[reason],
                                write_preflight={"status": "rejected", "reason": reason})
            output.append(fact)
            continue
        fact.setdefault("preflight_original", {k: fact.get(k) for k in
                        ("decision", "status", "research_status", "freshness", "reasons")})
        fact["research_run_id"] = run_id
        fact["research_status"] = "verified"
        row, path, error = normalize_fact(fact)
        state, reason = "ready", "终审通过，提交正式数据库写入"
        target = {"path": path}
        if error:
            state, reason = "rejected", error
        else:
            key = (path, *row_key(row, path))
            current = indexes[path].get(row_key(row, path))
            target.update(field=row["metric_key"], field_label=row["metric_zh"], period=row["period"],
                          period_end=row["period_end"], value=row["value"], unit=row["unit"],
                          previous_value=current.get("value") if current else None)
            reason = f"官方原文支持主体、数值和期间；已明确对应 {row['metric_zh']}（{row['metric_key']}），{row['period']}，{row['value']} {row['unit']}"
            if key in seen:
                previous = seen[key]
                if not previous.get("batch_conflict") and previous["value"] == row["value"] and previous["unit"] == row["unit"]:
                    state, reason = "duplicate", "本轮同一公司、指标和期间重复提交，已由另一条记录代表，本条不再提交写入"
                    target["represented_by"] = previous.get("daily_fact_id")
                else:
                    state, reason = "rejected", "本轮同一指标期间提交了不同数值，需终审解决冲突"
                    previous["batch_conflict"] = True
                    # Neither conflicting value may be published.
                    for prior in output:
                        if prior.get("id") == previous.get("daily_fact_id") or prior.get("write_preflight", {}).get("represented_by") == previous.get("daily_fact_id"):
                            prior.update(decision="review", research_status="conflict", status="unavailable", reasons=[reason])
                            prior["write_preflight"].update(status="rejected", reason=reason)
                    for prior in decisions:
                        if prior["id"] == previous.get("daily_fact_id") or prior.get("represented_by") == previous.get("daily_fact_id"):
                            prior.update(status="rejected", reason=reason)
            elif current and not (row_matches(current, row) and (allow_replay or current.get("daily_research_run_id") == run_id)):
                state, reason = "existing", "终审已查到正式指标表同期间记录，沿用已有数据，本条不提交四库更新"
            else:
                seen[key] = row
        if state in {"existing", "duplicate"}:
            fact.update(decision="unchanged", research_status="no_update", freshness="existing_period" if state == "existing" else "duplicate_in_batch", reasons=[reason])
        elif state == "rejected":
            fact.update(decision="review", research_status="conflict", status="unavailable", reasons=[reason])
        fact["write_preflight"] = {**target, "status": state, "reason": reason}
        decisions.append({"id": fact.get("id"), "company": fact.get("company"), "metric": fact.get("metric"),
                          **fact["write_preflight"]})
        output.append(fact)
    from collections import Counter
    return output, {"policy": POLICY, "input": len(decisions), "counts": dict(Counter(d["status"] for d in decisions)), "items": decisions}


def persist_preflight(directory, results, facts, preflight, summary, *, store=None):
    """Persist the same Agent decisions in reports, final review and the writer input."""
    from collections import Counter
    from .six_agent_research import atomic_write_json, atomic_write_jsonl
    decisions = {(f["company"], f["metric"]): f for f in facts}
    for agent in results:
        for report in agent["reports"]:
            for item in report["items"]:
                decision = decisions.get((report["company"], item["metric"]), {})
                if decision.get("write_preflight"):
                    item.update(status=decision["research_status"], freshness=decision.get("freshness"),
                                reason=decision["write_preflight"]["reason"], write_preflight=decision["write_preflight"])
                    if decision.get("latest_baseline"):
                        item["latest_baseline"] = decision["latest_baseline"]
            report["status"] = "partial" if any(i["status"] not in {"verified", "no_update", "not_applicable"} for i in report["items"]) else "completed"
            if store:
                store.save(report)
        agent["status"] = "completed" if all(r["status"] == "completed" for r in agent["reports"]) else "partial"
        atomic_write_json(directory / f"{agent['key']}.json", agent)
    accepted = [f for f in facts if f["decision"] == "accepted"]
    atomic_write_jsonl(directory / "candidate_facts.jsonl", facts)
    atomic_write_jsonl(directory / "verified_facts.jsonl", accepted)
    atomic_write_json(directory / "write_preflight.json", preflight)
    counts = Counter(f["research_status"] for f in facts)
    duplicates = sum(f.get("write_preflight", {}).get("status") == "duplicate" for f in facts)
    failures = sum(n for state, n in counts.items() if state not in {"verified", "no_update"})
    summary.update(write_preflight=preflight, accepted=len(accepted), review=failures, unchanged=counts["no_update"],
                   agents=[{k: v for k, v in a.items() if k != "reports"} for a in results],
                   tasks=len(facts), metric_status_counts=dict(counts),
                   outcome_counts={"existing": counts["no_update"] - duplicates, "duplicate": duplicates, "updated": len(accepted), "failed": failures},
                   business_status="updates_available" if accepted else "needs_review" if failures else "no_new_disclosures",
                   status="partial" if failures else "completed",
                   completed_companies=sum(r["status"] == "completed" for a in results for r in a["reports"]))
    return accepted


def write_formal_facts(root, facts, *, dry_run=False):
    """One locked writer per physical table. Readback, not file presence, proves writes."""
    import fcntl
    from .research_storage import read_object
    from .six_agent_research import now
    from cmhk.data.daily_financial_promotion import _atomic_text, _write_csv
    written, rejected, domains = [], [], {}
    grouped = {CARRIER_PATH: [], CLOUD_PATH: []}
    for fact in facts:
        row, relative, error = normalize_fact(fact)
        if error:
            rejected.append({"id": fact.get("id"), "status": "not_written", "reason": error})
        else:
            grouped[relative].append(row)
    for relative, candidates in grouped.items():
        if not candidates:
            continue
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.with_suffix(".promotion.lock").open("a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            payload = read_object(path)
            rows = payload.get("rows")
            if not isinstance(rows, list):
                raise ValueError(f"Invalid formal table: {relative}")
            index = {row_key(r, relative): r for r in rows}
            if len(index) != len(rows):
                raise ValueError("正式表存在重复主键，停止写入")
            added = 0
            for candidate in candidates:
                key = row_key(candidate, relative)
                current = index.get(key)
                if current and not row_matches(current, candidate):
                    rejected.append({"id": candidate.get("daily_fact_id"), "status": "not_written",
                                     "reason": "终审后该指标期间出现其他记录，写入冲突；退回Agent重新核对"})
                    continue
                if not current:
                    index[key] = candidate
                    added += 1
                written.append(candidate)
            if not dry_run:
                payload["rows"] = list(index.values())
                if added:
                    payload["generated_at"] = now()
                # Derived indexes must always reflect the persisted row, including retries.
                for subject in payload.get("subjects", []):
                    for row in index.values():
                        if row.get("subject") != subject.get("subject"):
                            continue
                        subject.setdefault("metrics", {}).setdefault(row["metric_key"], {})[row["period"]] = row.get("value")
                        periods = subject.setdefault("periods", [])
                        if not any(p.get("period") == row["period"] for p in periods):
                            periods.append({k: row[k] for k in ("period", "period_end", "grain") if k in row})
                _atomic_text(path, json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
                _write_csv(path.with_suffix(".csv"), payload["rows"])
                if relative == CARRIER_PATH:
                    _write_csv(path.with_name("quarterly_metrics_human_readable.csv"), payload["rows"])
                    manifest_path = path.with_name("manifest.json")
                    manifest = read_object(manifest_path, missing_ok=True)
                    manifest["row_count"] = len(index)
                    if isinstance(manifest.get("quality"), dict):
                        manifest["quality"]["row_count"] = len(index)
                    _atomic_text(manifest_path, json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
                if read_object(path).get("rows") != payload["rows"]:
                    raise ValueError(f"正式表写后回读不一致：{relative}")
            domains[relative] = {"added_rows": added, "candidates": len(candidates), "rows": len(index)}
    return {"ok": not rejected, "changed": any(r["added_rows"] for r in domains.values()),
            "dry_run": dry_run, "added_rows": sum(r["added_rows"] for r in domains.values()),
            "candidates": len(facts), "written": len(written), "not_written": len(rejected), "failures": rejected, "tables": domains}
