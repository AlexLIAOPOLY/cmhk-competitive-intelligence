"""Exact cell extraction for issuer tables whose period columns are explicit."""
import re
from datetime import date
from urllib.parse import urlparse

LABELS = {"收入": "Operating Revenue", "EBITDA": "EBITDA",
          "净利润": "Profit Attributable to Equity Shareholders of the Company"}
NUMBER = r"-?\d{1,3}(?:,\d{3})*(?:\.\d+)?|-?\d+(?:\.\d+)?"


def quarterly_cells(company, metric, url, text):
    """Never infer a column from proximity or calculate a standalone quarter."""
    parsed = urlparse(url)
    if (company != "中国联通" or metric not in LABELS or parsed.hostname != "www.chinaunicom.com.hk"
            or parsed.path != "/en/ir/highlights.php" or parsed.query):
        return []
    body = re.sub(r"\s+", " ", text).strip()
    if "China Unicom (Hong Kong) Limited" not in body[:1500]:
        return []
    headers = list(re.finditer(r"(?:[1-4]Q20\d{2}\s+){2,}(?=Operating Revenue)", body))
    if len(headers) != 1:
        return []
    header = headers[0]
    periods = header.group().split()
    if len(periods) != len(set(periods)):
        return []
    pattern = re.escape(LABELS[metric]) + r" \(RMB Millions\) (?P<values>(?:(?:" + NUMBER + r")(?:\s+|$))+)"
    rows = list(re.finditer(pattern, body[header.end():]))
    if len(rows) != 1:
        return []
    row = rows[0]
    values = row['values'].split()
    if len(values) != len(periods):
        return []
    quote = row.group().strip()
    return [{"company": company, "metric": metric, "status": "verified", "period": period,
             "value": value, "unit": "RMB Millions", "source_url": url, "quote": quote,
             "context_quote": body[:header.end()].strip(),
             "reason": "发行人季度表的期间列与指标行逐列对应，保留原始表头和完整数值行"}
            for period, value in zip(periods, values)]


def table_value_is_bound(item, body):
    return any(all(cell[key] == item.get(key) for key in ("period", "value", "unit"))
               and cell["quote"] in item.get("quote", "")
               for cell in quarterly_cells(item["company"], item["metric"], item["source_url"], body))


def extract_configured_table(company, metric, pages, baseline):
    from .research_contracts import contract_for, planning_outcome
    from .research_freshness import compare_candidate, period_key
    from .six_agent_research import validate_fact
    contract = contract_for(company, metric, baseline)
    if planning_outcome(company, metric, baseline) or contract.get("grain") != "quarter":
        return None
    target = contract.get("target_period_end", "")
    if not target or date.fromisoformat(target) > date.today():
        return None
    year, month = int(target[:4]), int(target[5:7])
    candidates = []
    for url, page in pages.items():
        if not page.get("opened") or not page.get("official"):
            continue
        for cell in quarterly_cells(company, metric, url, page.get("text", "")):
            if period_key(cell["period"]) != (year, month, "quarter"):
                continue
            checked = compare_candidate(validate_fact(cell, company, [metric], pages,
                storage_contract=contract), baseline)
            if checked["status"] == "verified":
                candidates.append(checked)
    return candidates[0] if len(candidates) == 1 else None
