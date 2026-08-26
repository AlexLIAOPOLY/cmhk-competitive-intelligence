from __future__ import annotations

import json
import os
import re
import tempfile
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse
from zoneinfo import ZoneInfo


ROOT = Path(__file__).resolve().parents[2]
RESULTS_DIR = ROOT / "results"
DATABASE_PATH = ROOT / "agent_knowledge" / "hk_competitor_product_tariffs" / "cmhk.data.local_financial_results.json"
HKT = ZoneInfo("Asia/Hong_Kong")

FINANCIAL_RESULT_ROWS = frozenset({2, 5, 8, 11, 15, 17})
OFFICIAL_REPORT_ROWS = frozenset({2, 5, 8, 11, 17})
ROW_COMPANIES = {
    2: "HKT",
    5: "3HK / Hutchison",
    8: "SmarTone",
    11: "HKBN",
    15: "HGC",
    17: "i-CABLE",
}
OFFICIAL_DOMAINS = {
    2: {"hkt.com", "www.hkt.com"},
    5: {"hthkh.com", "www.hthkh.com", "m.hthkh.com", "doc.irasia.com", "www1.hkexnews.hk", "www.hkexnews.hk"},
    8: {"smartoneholdings.com", "www.smartoneholdings.com"},
    11: {"hkbn.net", "www.hkbn.net", "reg.hkbn.net"},
    17: {
        "i-cablecomm.com",
        "www.i-cablecomm.com",
        "ctfme.com",
        "www.ctfme.com",
        "apps5.i-cable.com",
        "www1.hkexnews.hk",
        "www.hkexnews.hk",
        "cdn.prod.website-files.com",
    },
}

CORE_METRICS = {"revenue", "ebitda", "net_profit", "capital_expenditure", "dividend"}
METRIC_LABELS = {
    "revenue": "收入/总收益",
    "ebitda": "EBITDA",
    "net_profit": "净利润",
    "capital_expenditure": "资本开支",
    "dividend": "派息/分派",
    "5g_customers": "5G用户数",
}

AMOUNT = r"(?:HK\$|HKD|港幣|港币|港元|\$)?\s*[-(]?\d[\d,]*(?:\.\d+)?\s*(?:million|billion|mn|bn|m|億港元|亿港元|百萬港元|百万港元|港元|港仙|HK cents?|%)?\)?"
METRIC_PATTERNS: dict[str, tuple[str, ...]] = {
    "revenue": (
        rf"Results Highlights.{{0,180}}?\bRevenue.{{0,80}}?(?P<value>\$\s*\d[\d,]*(?:\.\d+)?\s*(?:million|m))",
        rf"revenues?.{{0,220}}?(?:of the Group|Group).{{0,120}}?\bto\s+(?:approximately\s+)?(?P<value>{AMOUNT})",
        rf"(?:revenues? of the Group|Group revenue|total revenue).{{0,160}}?\bto\s+(?:approximately\s+)?(?P<value>{AMOUNT})",
        rf"Financial Highlights.{{0,180}}?\bRevenue\s+{AMOUNT}\s+(?P<value>{AMOUNT})",
        rf"(?:total revenue|total turnover|group revenue|總收益|总收益|總收入|总收入).{{0,100}}?\bto\s+(?P<value>{AMOUNT})",
        rf"(?:total revenue|total turnover|group revenue|總收益|总收益|總收入|总收入)[^\d]{{0,80}}(?P<value>{AMOUNT})",
        rf"(?:revenue|turnover|收益|收入)\s+(?:increased|decreased|rose|grew|was|of|為|为)[^\d]{{0,60}}(?P<value>{AMOUNT})",
    ),
    "ebitda": (
        rf"Interim dividend.{{0,80}}?EBITDA.{{0,80}}?Stable\s+(?P<value>\$\s*\d[\d,]*(?:\.\d+)?\s*(?:million|m))",
        rf"(?:total\s+)?EBITDA.{{0,100}}?\bto\s+(?P<value>{AMOUNT})",
        rf"(?:total\s+)?EBITDA[^\d]{{0,80}}(?P<value>{AMOUNT})",
    ),
    "net_profit": (
        rf"profit attributable to shareholders.{{0,100}}?\bwas\s+(?P<value>\$\s*\d[\d,]*(?:\.\d+)?\s*(?:million|m))",
        rf"Financial Highlights.{{0,360}}?(?:Reported\s+)?Profit after tax\s+{AMOUNT}\s+(?P<value>{AMOUNT})",
        rf"(?:recorded a loss|loss attributable|loss for the year).{{0,140}}?(?P<value>HK\$\s*\d[\d,]*(?:\.\d+)?\s*(?:million|billion|mn|bn|m))",
        rf"(?:profit attributable(?: to [^.；;]{{0,80}})?|net profit|profit for the period|純利|净利润|淨利潤|股東應佔溢利|股东应占溢利).{{0,120}}?\bto\s+(?P<value>{AMOUNT})",
        rf"(?:profit attributable(?: to [^.；;]{{0,80}})?|net profit|profit for the period|純利|净利润|淨利潤|股東應佔溢利|股东应占溢利)[^\d]{{0,80}}(?P<value>{AMOUNT})",
    ),
    "capital_expenditure": (
        rf"(?:capital expenditure|capital expenditures|capex|資本開支|资本开支).{{0,500}}?(?:amounted to|totalled)\s+(?:approximately\s+)?(?P<value>{AMOUNT})",
        rf"(?:capital expenditure|capital expenditures|capex|資本開支|资本开支).{{0,180}}?\b(?:was|were|為|为)\s+(?P<value>{AMOUNT})",
        rf"(?:capital expenditure|capital expenditures|capex|資本開支|资本开支)(?: including [^.；;]{{0,60}})?[^\d]{{0,80}}(?P<value>{AMOUNT})",
    ),
    "dividend": (
        rf"(?:interim|final|total)?\s*(?:distribution|dividend|分派|股息|派息)\s+of\s+(?P<value>{AMOUNT})",
        rf"(?:Interim|Final|Full year) Dividend\s*\(cents per share\)\s+{AMOUNT}\s+(?P<value>{AMOUNT})",
        rf"(?:interim|final|total)?\s*(?:distribution|dividend|分派|股息|派息)\s+per\s+[^.；;]{{0,80}}?\s+(?:of|was|為|为)\s+(?P<value>{AMOUNT})",
        rf"(?:interim|final|total)?\s*(?:distribution|dividend|分派|股息|派息)(?: per [^.；;]{{0,60}})?[^\d]{{0,80}}(?P<value>{AMOUNT})",
    ),
    "5g_customers": (
        rf"(?:5G customer base|5G customers|5G subscribers|5G客戶|5G客户|5G用戶|5G用户).{{0,100}}?\bto\s+(?P<value>{AMOUNT})",
        rf"(?:5G customer base|5G customers|5G subscribers|5G客戶|5G客户|5G用戶|5G用户)[^\d]{{0,80}}(?P<value>{AMOUNT})",
    ),
}


def _read_json(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default


def _atomic_write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temp = Path(name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp, path)
    finally:
        temp.unlink(missing_ok=True)


def _record_text(record: dict[str, Any]) -> str:
    relative = str(record.get("evidence_path") or "").strip()
    if relative:
        path = ROOT / relative
        try:
            return path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            pass
    return str(record.get("text_sample") or "")


def _is_official_report(row: int, record: dict[str, Any]) -> bool:
    url = str(record.get("final_url") or record.get("url") or "").strip()
    if not url or not (200 <= int(record.get("status") or 0) < 400):
        return False
    host = (urlparse(url).hostname or "").casefold()
    if host not in OFFICIAL_DOMAINS.get(row, set()):
        return False
    probe = " ".join((unquote(url), str(record.get("title") or ""), _record_text(record)[:1800]))
    report_marked = bool(re.search(r"annual|interim|quarter|financial|results?|earnings|年度|全年|中期|季度|業績|业绩", probe, re.I))
    pdf = "pdf" in str(record.get("content_type") or "").casefold() or ".pdf" in url.casefold()
    official_results_page = bool(re.search(r"press-releases/.+(?:annual|interim|FY\d{2}).*results", url, re.I))
    return report_marked and (pdf or official_results_page)


def _report_period(record: dict[str, Any]) -> tuple[str, str, tuple[int, int]]:
    url = unquote(str(record.get("final_url") or record.get("url") or ""))
    title = " ".join(
        item
        for item in (
            str(record.get("discovered_title") or "").strip(),
            str(record.get("title") or "").strip(),
        )
        if item
    )
    heading = " ".join((title, url))
    probe = " ".join((heading, _record_text(record)[:4500]))
    fiscal = re.search(r"\bFY\s*(?:20)?(\d{2})\b", probe, re.I)
    fiscal_year = 2000 + int(fiscal.group(1)) if fiscal else 0
    ended_years = [
        int(value)
        for value in re.findall(
            r"(?:year|six months|period) ended.{0,45}?(20\d{2})",
            probe,
            re.I,
        )
    ]
    years = [fiscal_year] if fiscal_year else []
    if not years and ended_years:
        years = ended_years
    if not years:
        # Report titles describe the accounting period, while URLs often begin
        # with the later publication date (for example 2026.02.09_(2025_Annual...)).
        # Never let that publication year outrank an explicit year in the title.
        years = [int(value) for value in re.findall(r"(?<!\d)(20\d{2})(?!\d)", title)]
    if not years:
        years = [int(value) for value in re.findall(r"(?<!\d)(20\d{2})(?!\d)", url)]
    if not years:
        years = [int(value) for value in re.findall(r"(?<!\d)(20\d{2})(?!\d)", probe)]
    year = max((value for value in years if value <= datetime.now(HKT).year + 1), default=0)
    if re.search(r"interim|six months|half.year|中期|半年度", probe, re.I):
        return (f"H1 {year}" if year else "Interim", "interim", (year, 2))
    quarter = re.search(r"(?:Q|quarter\s*)([1-4])", probe, re.I)
    if quarter:
        number = int(quarter.group(1))
        return (f"Q{number} {year}" if year else f"Q{number}", "quarter", (year, number))
    if re.search(r"annual|full.year|全年|年度", probe, re.I):
        return (f"FY {year}" if year else "Annual", "annual", (year, 4))
    return (str(year) if year else "Unknown", "unknown", (year, 0))


def _publication_date(record: dict[str, Any]) -> str:
    url = unquote(str(record.get("final_url") or record.get("url") or ""))
    for pattern in (
        r"(?<!\d)(20\d{2})[._/-](0?[1-9]|1[0-2])[._/-]([0-3]?\d)(?!\d)",
        r"(?<!\d)(20\d{2})(0[1-9]|1[0-2])([0-3]\d)(?!\d)",
    ):
        match = re.search(pattern, url)
        if match:
            try:
                return date(*map(int, match.groups())).isoformat()
            except ValueError:
                continue
    short_date = re.search(r"(?:pre|pres|result)[-_]?(\d{2})(0[1-9]|1[0-2])([0-3]\d)", url, re.I)
    if short_date:
        try:
            return date(2000 + int(short_date.group(1)), int(short_date.group(2)), int(short_date.group(3))).isoformat()
        except ValueError:
            pass
    text = _record_text(record)[:10000]
    month_names = "January|February|March|April|May|June|July|August|September|October|November|December"
    named_dates: list[date] = []
    for match in re.finditer(rf"\b([0-3]?\d)\s+({month_names})\s+(20\d{{2}})\b", text, re.I):
        try:
            named_dates.append(datetime.strptime(" ".join(match.groups()), "%d %B %Y").date())
        except ValueError:
            continue
    if named_dates:
        eligible = [value for value in named_dates if value <= datetime.now(HKT).date()]
        if eligible:
            return max(eligible).isoformat()
    return ""


def _extract_metrics(text: str) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for metric_key, patterns in METRIC_PATTERNS.items():
        for pattern in patterns:
            match = re.search(pattern, text, re.I | re.S)
            if not match:
                continue
            value = re.sub(r"\s+", " ", match.group("value")).strip(" ;,.")
            evidence = re.sub(r"\s+", " ", match.group(0)).strip()
            if not re.search(r"\d", value):
                continue
            if metric_key in {"revenue", "ebitda", "net_profit", "capital_expenditure"}:
                if re.fullmatch(r"[-+]?\d+(?:\.\d+)?%", value):
                    continue
                if not re.search(r"HK\$|HKD|\$|港|million|billion|mn|bn|億|亿|百萬|百万", value, re.I):
                    if re.search(r"HK\$\s*million|HK\$['’]?M", evidence, re.I):
                        value = f"HK${value} million"
                    else:
                        continue
            if metric_key == "dividend":
                if re.fullmatch(r"[-+]?\d+(?:\.\d+)?%", value):
                    continue
                if not re.search(r"HK\$|HKD|\$|港元|港仙|cents?|Nil", value, re.I) and not re.search(
                    r"cents per share|港仙|每股", evidence, re.I
                ):
                    continue
            if metric_key == "dividend" and re.fullmatch(r"\d+(?:\.\d+)?", value) and "cents per share" in evidence.casefold():
                value = f"{value} HK cents"
            if value.startswith("$"):
                value = "HK" + value
            compact_millions = re.fullmatch(r"HK\$\s*([\d,.]+)\s*m", value, re.I)
            if compact_millions:
                value = f"HK${compact_millions.group(1)} million"
            if metric_key == "net_profit" and re.search(r"\bloss\b|虧損|亏损", evidence, re.I) and not value.startswith("-"):
                value = f"-{value}"
            if metric_key == "5g_customers" and not re.search(r"million|billion|萬|万|億|亿|%|customers?|subscribers?|戶|户", value, re.I):
                continue
            rows.append(
                {
                    "metric_key": metric_key,
                    "metric": METRIC_LABELS[metric_key],
                    "value": value,
                    "evidence": evidence[:500],
                }
            )
            break
    if not any(item["metric_key"] == "dividend" for item in rows) and re.search(
        r"does not recommend the payment of any dividend|不建議.{0,40}派發任何股息|不建议.{0,40}派发任何股息",
        text,
        re.I | re.S,
    ):
        rows.append(
            {
                "metric_key": "dividend",
                "metric": METRIC_LABELS["dividend"],
                "value": "HK$Nil",
                "evidence": "The Board does not recommend the payment of any dividend for the reporting period.",
            }
        )
    return rows


def _candidate_rank(record: dict[str, Any]) -> tuple[int, int, int, int]:
    _period, _kind, rank = _report_period(record)
    url = unquote(str(record.get("final_url") or record.get("url") or ""))
    text = f"{record.get('title', '')} {url}"
    announcement = int(bool(re.search(r"announcement|results?", text, re.I)))
    presentation = int(bool(re.search(r"presentation", text, re.I)))
    return (*rank, announcement, -presentation)


def _latest_report(row: int, result: dict[str, Any]) -> dict[str, Any] | None:
    records: list[dict[str, Any]] = []
    all_records = list(result.get("raw_records") or [])
    for entity in result.get("entity_results") or []:
        all_records.extend((entity or {}).get("raw_records") or [])
    discovered_titles: dict[str, str] = {}
    for record in all_records:
        for link in (record or {}).get("discovered_report_links") or []:
            url = str((link or {}).get("url") or "").strip()
            title = str((link or {}).get("title") or "").strip()
            if url and title:
                discovered_titles[url] = title
    for record in result.get("raw_records") or []:
        if isinstance(record, dict) and _is_official_report(row, record):
            record_url = str(record.get("final_url") or record.get("url") or "")
            records.append({**record, "discovered_title": discovered_titles.get(record_url, "")})
    for entity in result.get("entity_results") or []:
        for record in (entity or {}).get("raw_records") or []:
            if isinstance(record, dict) and _is_official_report(row, record):
                record_url = str(record.get("final_url") or record.get("url") or "")
                records.append({**record, "discovered_title": discovered_titles.get(record_url, "")})
    unique: dict[str, dict[str, Any]] = {}
    for record in records:
        key = str(record.get("final_url") or record.get("url") or "")
        unique[key] = record
    return max(unique.values(), key=_candidate_rank) if unique else None


def _latest_discovered_report(row: int, result: dict[str, Any]) -> dict[str, Any] | None:
    candidates: dict[str, dict[str, Any]] = {}
    all_records = list(result.get("raw_records") or [])
    for entity in result.get("entity_results") or []:
        all_records.extend((entity or {}).get("raw_records") or [])
    for record in all_records:
        for link in (record or {}).get("discovered_report_links") or []:
            url = str((link or {}).get("url") or "").strip()
            title = str((link or {}).get("title") or "").strip()
            host = (urlparse(url).hostname or "").casefold()
            if not url or host not in OFFICIAL_DOMAINS.get(row, set()):
                continue
            pseudo = {
                "url": url,
                "final_url": url,
                "title": title,
                "text_sample": title,
            }
            marker = f"{title} {unquote(url)}"
            if not re.search(
                r"annual|interim|quarter|financial|results?|earnings|年度|全年|中期|季度|業績|业绩",
                marker,
                re.I,
            ):
                continue
            candidates[url] = pseudo
    return max(candidates.values(), key=_candidate_rank) if candidates else None


def rebuild_local_financial_database(
    *,
    rows: list[int] | None = None,
    now: datetime | None = None,
    write: bool = True,
) -> dict[str, Any]:
    now = (now or datetime.now(HKT)).astimezone(HKT)
    selected = sorted(set(rows or FINANCIAL_RESULT_ROWS) & FINANCIAL_RESULT_ROWS)
    previous = _read_json(DATABASE_PATH, {})
    reports_by_row = {
        int(item.get("row")): item
        for item in previous.get("reports", [])
        if str(item.get("row") or "").isdigit()
    }
    checked: list[dict[str, Any]] = []
    failures: list[str] = []
    for row in selected:
        result = _read_json(RESULTS_DIR / f"row_{row}.json", {})
        report = _latest_report(row, result)
        discovered_report = _latest_discovered_report(row, result)
        if report is None:
            status = "not_applicable" if row not in OFFICIAL_REPORT_ROWS else "no_official_report_discovered"
            checked.append({"row": row, "company": ROW_COMPANIES[row], "status": status})
            if row in OFFICIAL_REPORT_ROWS:
                failures.append(f"第{row}行 {ROW_COMPANIES[row]} 未发现可读取的官方财报")
            continue
        extracted_period, _extracted_type, extracted_rank = _report_period(report)
        if discovered_report is not None:
            discovered_period, _discovered_type, discovered_rank = _report_period(discovered_report)
            if discovered_rank > extracted_rank:
                checked.append(
                    {
                        "row": row,
                        "company": ROW_COMPANIES[row],
                        "status": "newer_official_report_unavailable",
                        "period": discovered_period,
                        "source_url": discovered_report.get("final_url") or discovered_report.get("url"),
                        "extracted_period": extracted_period,
                    }
                )
                failures.append(
                    f"第{row}行 {ROW_COMPANIES[row]} 已发现更新一期官方财报 {discovered_period}，"
                    f"但尚未完成读取或结构化（当前仍为 {extracted_period}）"
                )
                continue
        text = _record_text(report)
        period, report_type, _rank = _report_period(report)
        publication_date = _publication_date(report)
        metrics = _extract_metrics(text)
        core_count = sum(item["metric_key"] in CORE_METRICS for item in metrics)
        url = str(report.get("final_url") or report.get("url") or "")
        item = {
            "row": row,
            "company": ROW_COMPANIES[row],
            "period": period,
            "report_type": report_type,
            "publication_date": publication_date,
            "due_at_hkt": (
                f"{(date.fromisoformat(publication_date) + timedelta(days=1)).isoformat()}T03:00:00+08:00"
                if publication_date else ""
            ),
            "source_url": url,
            "source_title": str(report.get("discovered_title") or report.get("title") or "Official financial report"),
            "content_hash": str(report.get("content_hash") or ""),
            "metrics": metrics,
            "core_metric_count": core_count,
            "fetched_at_hkt": str(result.get("fetched_at_hkt") or result.get("fetched_at") or now.isoformat()),
            "verification_status": "official_document_extracted" if core_count >= 2 else "insufficient_core_metrics",
        }
        checked.append(item)
        if core_count < 2:
            failures.append(f"第{row}行 {ROW_COMPANIES[row]} 最新官方财报 {period} 只抽取到 {core_count} 个核心指标")
        else:
            reports_by_row[row] = item

    payload = {
        "schema_version": 1,
        "generated_at_hkt": now.isoformat(timespec="seconds"),
        "schedule_policy": "official financial results are checked daily at 03:00 HKT and must be structured before publication",
        "reports": [reports_by_row[key] for key in sorted(reports_by_row)],
        "last_check": checked,
        "quality": {
            "ok": not failures,
            "checked_rows": selected,
            "failures": failures,
        },
    }
    comparable_previous = {
        "reports": previous.get("reports") or [],
        "quality": previous.get("quality") or {},
    }
    comparable_current = {
        "reports": payload["reports"],
        "quality": payload["quality"],
    }
    payload["database_changed"] = comparable_previous != comparable_current
    payload["database_updated"] = bool(write and not failures)
    try:
        database_path = str(DATABASE_PATH.relative_to(ROOT))
    except ValueError:
        database_path = str(DATABASE_PATH)
    payload["database_path"] = database_path
    if write and not failures:
        _atomic_write_json(DATABASE_PATH, payload)
    return payload


def financial_database_rows(path: Path = DATABASE_PATH) -> list[dict[str, Any]]:
    payload = _read_json(path, {})
    output: list[dict[str, Any]] = []
    for report in payload.get("reports") or []:
        for metric in report.get("metrics") or []:
            output.append({**report, **metric})
    return output
