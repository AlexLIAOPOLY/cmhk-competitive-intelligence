from __future__ import annotations

import csv
import json
import os
import re
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo


HKT = ZoneInfo("Asia/Hong_Kong")

LOCAL_SUBJECTS = {
    "HKT": "HKT / csl / 1O1O",
    "3HK / Hutchison": "3HK / Hutchison",
    "SmarTone": "SmarTone",
    "HKBN": "HKBN",
    "i-CABLE": "i-CABLE",
}
MAINLAND_SUBJECTS = {"\u4e2d\u56fd\u79fb\u52a8", "\u4e2d\u56fd\u7535\u4fe1", "\u4e2d\u56fd\u8054\u901a", "\u4e2d\u56fd\u94c1\u5854"}
METRICS = {
    "revenue": ("revenue", "\u8425\u4e1a\u6536\u5165"),
    "\u6536\u5165": ("revenue", "\u8425\u4e1a\u6536\u5165"),
    "\u6536\u5165/\u603b\u6536\u76ca": ("revenue", "\u8425\u4e1a\u6536\u5165"),
    "\u901a\u4fe1\u670d\u52a1\u6536\u5165": ("service_revenue", "\u901a\u4fe1\u670d\u52a1\u6536\u5165"),
    "ebitda": ("ebitda", "EBITDA"),
    "ebitda\u6216\u7ecf\u8425\u5229\u6da6": ("ebitda", "EBITDA"),
    "net_profit": ("net_income", "\u51c0\u5229\u6da6"),
    "\u51c0\u5229\u6da6": ("net_income", "\u51c0\u5229\u6da6"),
    "capital_expenditure": ("capital_expenditures", "\u8d44\u672c\u5f00\u652f"),
    "\u8d44\u672c\u5f00\u652f": ("capital_expenditures", "\u8d44\u672c\u5f00\u652f"),
    "\u81ea\u7531\u73b0\u91d1\u6d41": ("free_cash_flow", "\u81ea\u7531\u73b0\u91d1\u6d41"),
}
IR_INDEXES = {
    "HKT / csl / 1O1O": "https://www.hkt.com/en/about-hkt/investor-relations/financial-results/",
    "3HK / Hutchison": "https://www.hthkh.com/en/ir/reports.php",
    "SmarTone": "https://www.smartoneholdings.com/about/investor/financial_reports/english/",
    "HKBN": "https://www.hkbn.net/group/en/investor-engagement/financial-results",
    "i-CABLE": "https://www1.hkexnews.hk/search/titlesearch.xhtml?lang=en",
}
STATUS_STRENGTH = {
    "official_match": 5,
    "official_derived_from_verified_rows": 4,
    "official_only": 3,
    "official_single_source": 2,
}


def _read_json(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default


def _atomic_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temp = Path(name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp, path)
    finally:
        temp.unlink(missing_ok=True)


def _write_csv(path: Path, rows: list[dict[str, Any]], fields: list[str] | None = None) -> None:
    if fields is None:
        fields = []
        seen: set[str] = set()
        for row in rows:
            for key in row:
                if key not in seen:
                    seen.add(key)
                    fields.append(key)
    with tempfile.TemporaryFile(mode="w+", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
        handle.seek(0)
        _atomic_text(path, handle.read())


def _period(text: str) -> str:
    match = re.search(r"(?:H1\s*(20\d{2})|(20\d{2})\s*(?:\u5e74)?\s*\u4e0a\u534a\u5e74|1H[\u2019'\s]*(\d{2,4}))", text, re.I)
    if match:
        raw = next(value for value in match.groups() if value)
        year = int(raw)
        return f"H1 {2000 + year if year < 100 else year}"
    match = re.search(r"(?:Q|\u7b2c)([1-4])(?:\u5b63\u5ea6)?\s*(20\d{2})|(?:2Q)\s*(20\d{2})", text, re.I)
    if match:
        if match.group(3):
            return f"Q2 {match.group(3)}"
        return f"Q{match.group(1)} {match.group(2)}"
    return ""


def _period_end(subject: str, period: str) -> str:
    year_match = re.search(r"(20\d{2})", period)
    if not year_match:
        return period
    year = int(year_match.group(1))
    if period.startswith("H1"):
        if subject == "SmarTone":
            end_year = year - 1
            return f"Dec '{str(end_year)[-2:]} Dec 31, {end_year}"
        if subject == "HKBN":
            return f"Feb '{str(year)[-2:]} Feb 28, {year}"
        return f"Jun '{str(year)[-2:]} Jun 30, {year}"
    quarter = re.search(r"Q([1-4])", period)
    if quarter:
        month = {1: ("Mar", 31), 2: ("Jun", 30), 3: ("Sep", 30), 4: ("Dec", 31)}[int(quarter.group(1))]
        return f"{month[0]} '{str(year)[-2:]} {month[0]} {month[1]}, {year}"
    return period


def _number_and_unit(text: str, *, local_hkd: bool = False) -> tuple[float | int | None, str]:
    patterns = (
        (r"([-+]?\d[\d,]*(?:\.\d+)?)\s*\u767e\u4e07\u5143(?:\u4eba\u6c11\u5e01)?", 1, "millions CNY"),
        (r"([-+]?\d[\d,]*(?:\.\d+)?)\s*\u4ebf\u5143(?:\u4eba\u6c11\u5e01)?", 100, "millions CNY"),
        (r"([-+]?)\s*(?:HK\$|HKD)\s*(\d[\d,]*(?:\.\d+)?)\s*(million|billion|m|bn)?", 1, "millions HKD"),
        (r"([-+]?\d[\d,]*(?:\.\d+)?)\s*\u4ebf\u6e2f\u5143", 100, "millions HKD"),
    )
    for pattern, multiplier, unit in patterns:
        match = re.search(pattern, text, re.I)
        if not match:
            continue
        if len(match.groups()) == 3:
            value = float(match.group(2).replace(",", ""))
            if match.group(1) == "-":
                value = -value
            magnitude = match.group(3)
        else:
            value = float(match.group(1).replace(",", ""))
            magnitude = match.group(2) if len(match.groups()) > 1 else ""
        if str(magnitude or "").lower() in {"billion", "bn"}:
            multiplier = 1000
        value *= multiplier
        return (int(value) if value.is_integer() else value), unit
    if local_hkd:
        match = re.search(r"([-+]?\d[\d,]*(?:\.\d+)?)", text)
        if match:
            value = float(match.group(1).replace(",", ""))
            return (int(value) if value.is_integer() else value), "millions HKD"
    return None, ""


def _source_rows(primary_url: str, index_url: str, evidence: str) -> list[dict[str, str]]:
    rows = [{"label": "\u6bcf\u65e5\u722c\u866b\u6838\u9a8c\u7684\u5b98\u65b9\u62ab\u9732", "url": primary_url, "evidence": evidence}]
    if index_url and index_url != primary_url:
        rows.append({"label": "\u53d1\u884c\u4eba\u5b98\u65b9\u8d22\u62a5\u5165\u53e3", "url": index_url, "evidence": "\u7528\u4e8e\u6838\u5bf9\u53d1\u884c\u4eba\u3001\u62ab\u9732\u671f\u95f4\u4e0e\u5b98\u65b9\u6587\u4ef6\u5f52\u5c5e\u3002"})
    return rows


def _record(*, subject: str, period: str, metric_key: str, metric_zh: str, value: float | int,
            unit: str, source_url: str, source_label: str, evidence: str,
            verification_sources: list[dict[str, str]], row_ref: str = "", evidence_hash: str = "") -> dict[str, Any]:
    return {
        "subject": subject,
        "category": "carrier",
        "legal_name": subject,
        "ticker": "",
        "period": period,
        "period_end": _period_end(subject, period),
        "grain": "half_year" if period.startswith("H") else "quarter",
        "metric_key": metric_key,
        "metric_zh": metric_zh,
        "value": value,
        "unit": unit,
        "disclosure_frequency": "semiannual" if period.startswith("H") else "quarterly",
        "quality_status": "daily_official_crawl_promoted",
        "verification_status": "official_only",
        "official_value": value,
        "official_unit": unit,
        "official_source_label": source_label,
        "official_source_url": source_url,
        "official_evidence": evidence,
        "verification_count": len(verification_sources),
        "verification_method": "daily_agent_gate_plus_issuer_report_index",
        "verification_sources": json.dumps(verification_sources, ensure_ascii=False),
        "verification_note": "\u6bcf\u65e503:00\u722c\u866b\u7ecfAgent\u5b9e\u4f53\u3001\u6307\u6807\u3001\u6570\u503c\u3001\u671f\u95f4\u548c\u5b98\u65b9\u6765\u6e90\u95e8\u7981\u540e\u664b\u5347\u3002",
        "daily_crawl_row_ref": row_ref,
        "daily_evidence_hash": evidence_hash,
    }


def _candidate_rows(local_payload: dict[str, Any], verified_lines: list[str]) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    for report in local_payload.get("reports") or []:
        subject = LOCAL_SUBJECTS.get(str(report.get("company") or ""))
        period = str(report.get("period") or "")
        primary_url = str(report.get("source_url") or "")
        if not subject or not period or not primary_url.startswith("http"):
            continue
        index_url = IR_INDEXES.get(subject, "")
        for metric in report.get("metrics") or []:
            mapped = METRICS.get(str(metric.get("metric_key") or "").casefold())
            if not mapped:
                continue
            value, unit = _number_and_unit(str(metric.get("value") or ""), local_hkd=True)
            if value is None:
                continue
            evidence = str(metric.get("evidence") or "")
            sources = _source_rows(primary_url, index_url, evidence)
            output.append(_record(subject=subject, period=period, metric_key=mapped[0], metric_zh=mapped[1],
                                  value=value, unit=unit, source_url=primary_url,
                                  source_label=str(report.get("source_title") or "\u5b98\u65b9\u8d22\u62a5"), evidence=evidence,
                                  verification_sources=sources, row_ref=f"row_{report.get('row')}",
                                  evidence_hash=str(report.get("content_hash") or "")))
    for line in verified_lines:
        try:
            fact = json.loads(line)
        except json.JSONDecodeError:
            continue
        company = str(fact.get("company") or "")
        if company not in MAINLAND_SUBJECTS or fact.get("decision") != "accepted" or fact.get("status") != "ok":
            continue
        if not all(fact.get(key) for key in ("entity_supported", "metric_supported", "value_supported")):
            continue
        mapped = METRICS.get(str(fact.get("metric") or "").casefold())
        value_text = str(fact.get("value") or "")
        period = _period(value_text + " " + str(fact.get("basis") or ""))
        value, unit = _number_and_unit(value_text)
        sources = [str(url) for url in fact.get("sources") or [] if str(url).startswith("http")]
        if not mapped or not period or value is None or len(sources) < 2:
            continue
        evidence = str(fact.get("basis") or value_text)
        verification_sources = [
            {"label": f"\u5b98\u65b9\u62ab\u9732{i + 1}", "url": url, "evidence": evidence}
            for i, url in enumerate(dict.fromkeys(sources))
        ]
        output.append(_record(subject=company, period=period, metric_key=mapped[0], metric_zh=mapped[1],
                              value=value, unit=unit, source_url=sources[0], source_label="\u6bcf\u65e5Agent\u6838\u9a8c\u5b98\u65b9\u62ab\u9732",
                              evidence=evidence, verification_sources=verification_sources,
                              row_ref=str(fact.get("row_ref") or ""), evidence_hash=str(fact.get("evidence_hash") or "")))
    return output


def promote_daily_financial_facts(*, database_path: Path, local_financial_path: Path,
                                  verified_facts_path: Path, dry_run: bool = False,
                                  generated_at: str = "") -> dict[str, Any]:
    payload = _read_json(database_path, {}) or {}
    current_rows = list(payload.get("rows") or [])
    local_payload = _read_json(local_financial_path, {}) or {}
    try:
        verified_lines = verified_facts_path.read_text(encoding="utf-8").splitlines()
    except OSError:
        verified_lines = []
    candidates = _candidate_rows(local_payload, verified_lines)
    keyed = {(str(row.get("subject") or ""), str(row.get("period") or ""), str(row.get("metric_key") or "")): row for row in current_rows}
    added = upgraded = preserved = 0
    for candidate in candidates:
        key = (candidate["subject"], candidate["period"], candidate["metric_key"])
        previous = keyed.get(key)
        if previous is None:
            keyed[key] = candidate
            added += 1
        elif STATUS_STRENGTH.get(str(previous.get("verification_status") or ""), 0) < STATUS_STRENGTH["official_only"]:
            keyed[key] = candidate
            upgraded += 1
        else:
            preserved += 1
    rows = sorted(keyed.values(), key=lambda row: (str(row.get("category") or ""), str(row.get("subject") or ""), str(row.get("metric_key") or ""), str(row.get("period_end") or row.get("period") or "")))
    changed = added > 0 or upgraded > 0
    if changed and not dry_run:
        payload["rows"] = rows
        payload["generated_at"] = generated_at or datetime.now(HKT).isoformat(timespec="seconds")
        payload["daily_official_promotion"] = {
            "generated_at_hkt": payload["generated_at"], "candidates": len(candidates),
            "added_rows": added, "upgraded_rows": upgraded, "preserved_stronger_rows": preserved,
            "local_financial_path": str(local_financial_path), "verified_facts_path": str(verified_facts_path),
        }
        subjects = {str(item.get("subject") or ""): item for item in payload.get("subjects") or []}
        for row in candidates:
            subject = subjects.get(row["subject"])
            if not subject:
                continue
            periods = subject.setdefault("periods", [])
            if not any(str(item.get("period") or "") == row["period"] for item in periods):
                periods.append({"period": row["period"], "grain": row["grain"], "period_end": row["period_end"]})
            subject.setdefault("metrics", {}).setdefault(row["metric_key"], {})[row["period"]] = row["value"]
        _atomic_text(database_path, json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
        _write_csv(database_path.with_suffix(".csv"), rows)
        human_fields = ["subject", "period", "grain", "metric_zh", "value", "unit", "verification_status", "official_value", "official_unit", "verification_count", "verification_method", "official_source_url", "verification_note"]
        _write_csv(database_path.with_name("quarterly_metrics_human_readable.csv"), rows, human_fields)
        manifest_path = database_path.with_name("manifest.json")
        manifest = _read_json(manifest_path, {}) or {}
        manifest["row_count"] = len(rows)
        if isinstance(manifest.get("quality"), dict):
            manifest["quality"]["row_count"] = len(rows)
            note = "\u6bcf\u65e503:00\u5b98\u65b9\u8d22\u62a5\u901a\u8fc7Agent\u95e8\u7981\u540e\u589e\u91cf\u664b\u5347\u5230\u4e3b\u5e93\uff1b\u66f4\u9ad8\u6838\u9a8c\u7b49\u7ea7\u7684\u65e7\u884c\u4f18\u5148\u4fdd\u7559\u3002"
            manifest["quality"].setdefault("notes", [])
            if note not in manifest["quality"]["notes"]:
                manifest["quality"]["notes"].append(note)
        _atomic_text(manifest_path, json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
    return {"ok": True, "changed": changed, "candidates": len(candidates), "added_rows": added,
            "upgraded_rows": upgraded, "preserved_stronger_rows": preserved,
            "published_rows": len(rows), "dry_run": dry_run}
