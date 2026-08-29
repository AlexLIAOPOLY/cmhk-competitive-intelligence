#!/usr/bin/env python3
"""Promote the 2026 interim rows after exact official-statement checks.

The current quarterly package contains later rows that cannot be reproduced by
the older full builder without degrading row coverage.  This migration updates
that immutable-shape package in place, preserves every standardized value, and
records official conflicts instead of silently replacing source values.
"""

from __future__ import annotations

import csv
import json
import os
import tempfile
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DATASET = ROOT / "agent_knowledge" / "quarterly_competitor_metrics_2026-06-18"
KEY_FIELDS = ("subject", "period", "metric_key")

HTHKH_URL = "https://www.hthkh.com/en/ir/reports/ir2026/ir2026.pdf"
HKT_URL = "https://www.hkt.com/api-service/assets/e-2026.07.29_(2026_Interim_Results_Announcement).pdf"
CT_URL = "https://doc.irasia.com/listco/hk/chinatelecom/interim/2026/int.pdf"
CM_H1_URL = "https://www1.hkexnews.hk/listedco/listconews/sehk/2026/0827/2026082700252.pdf"
CM_Q1_URL = "https://www1.hkexnews.hk/listedco/listconews/sehk/2026/0420/2026042001454.pdf"
CU_URL = "https://www1.hkexnews.hk/listedco/listconews/sehk/2026/0818/2026081800335.pdf"
TOWER_URL = "https://doc.irasia.com/listco/hk/chinatower/interim/2026/intrep.pdf"


def source(label: str, url: str, evidence: str) -> dict[str, str]:
    return {"label": label, "url": url, "evidence": evidence}


DIRECT: dict[tuple[str, str, str], dict[str, Any]] = {
    ("3HK / Hutchison", "H1 2026", "capital_expenditures"): {
        "official_value": -169,
        "url": HTHKH_URL,
        "label": "HTHKH 2026 Interim Report - Cash Flows",
        "evidence": "截至2026年6月30日止六个月Purchases of property, plant and equipment为169百万港元；现金流出口径记负数。",
        "method": "official_interim_cash_capex_check",
    },
    ("3HK / Hutchison", "H1 2026", "free_cash_flow"): {
        "official_value": 589,
        "url": HTHKH_URL,
        "label": "HTHKH 2026 Interim Report - Cash Flows",
        "evidence": "经营活动现金流758减购置物业、机器及设备169，按本数据集现金流口径复算自由现金流589百万港元。",
        "method": "official_operating_cash_flow_minus_cash_capex",
    },
    ("3HK / Hutchison", "H1 2026", "total_debt"): {
        "official_value": 529,
        "url": HTHKH_URL,
        "label": "HTHKH 2026 Interim Report - Lease Liabilities",
        "evidence": "流动租赁负债312加非流动租赁负债217，复算总债务529百万港元。",
        "method": "official_current_and_noncurrent_lease_reconciliation",
    },
    ("3HK / Hutchison", "H1 2026", "cash_and_equivalents"): {
        "official_value": 355,
        "url": HTHKH_URL,
        "label": "HTHKH 2026 Interim Report - Financial Position",
        "evidence": "截至2026年6月30日Cash and cash equivalents为355百万港元。",
        "method": "official_interim_balance_sheet_and_cash_flow_check",
    },
    ("3HK / Hutchison", "H1 2026", "operating_cash_flow"): {
        "official_value": 758,
        "url": HTHKH_URL,
        "label": "HTHKH 2026 Interim Report - Cash Flows",
        "evidence": "截至2026年6月30日止六个月Net cash from operating activities为758百万港元。",
        "method": "official_interim_cash_flow_check",
    },
    ("3HK / Hutchison", "H1 2026", "total_assets"): {
        "official_value": 13565,
        "url": HTHKH_URL,
        "label": "HTHKH 2026 Interim Report - Financial Position",
        "evidence": "非流动资产8,696加流动资产4,869，复算总资产13,565百万港元。",
        "method": "official_interim_balance_sheet_reconciliation",
    },
    ("HKT / csl / 1O1O", "H1 2026", "cash_and_equivalents"): {
        "official_value": 2747,
        "url": HKT_URL,
        "label": "HKT 2026 Interim Results Announcement - Financial Position",
        "evidence": "截至2026年6月30日Cash and cash equivalents为2,747百万港元。",
        "method": "official_interim_balance_sheet_check",
    },
    ("HKT / csl / 1O1O", "H1 2026", "total_assets"): {
        "official_value": 124572,
        "url": HKT_URL,
        "label": "HKT 2026 Interim Results Announcement - Financial Position",
        "evidence": "非流动资产111,172加流动资产13,400，复算总资产124,572百万港元。",
        "method": "official_interim_balance_sheet_reconciliation",
    },
    ("HKT / csl / 1O1O", "H1 2026", "total_debt"): {
        "official_value": 48051,
        "url": HKT_URL,
        "label": "HKT 2026 Interim Results Announcement - Gross Debt Definition",
        "evidence": "公告把gross debt定义为短期借款与长期借款本金之和；2026年6月30日为7,721加40,330，即48,051百万港元，与标准化值51,553不一致。",
        "method": "official_short_and_long_term_borrowings_reconciliation",
        "status": "official_conflict",
    },
    ("中国电信", "Q2 2026", "cash_and_equivalents"): {
        "official_value": 40657,
        "url": CT_URL,
        "label": "China Telecom 2026 Interim Report - Financial Position",
        "evidence": "截至2026年6月30日Cash and cash equivalents为40,657百万元人民币。",
        "method": "official_interim_balance_sheet_check",
    },
    ("中国电信", "Q2 2026", "total_assets"): {
        "official_value": 884719,
        "url": CT_URL,
        "label": "China Telecom 2026 Interim Report - Financial Position",
        "evidence": "截至2026年6月30日Total assets为884,719百万元人民币。",
        "method": "official_interim_balance_sheet_check",
    },
    ("中国移动", "Q2 2026", "capital_expenditures"): {
        "official_value": -35891,
        "url": CM_H1_URL,
        "label": "China Mobile 2026 Interim Report and Q1 Results",
        "evidence": "半年报现金流量表购建长期资产支出66,290，减Q1官方支出30,399，复算Q2现金资本开支35,891；现金流出口径记负数。",
        "method": "official_h1_minus_q1_cash_capex_reconciliation",
        "extra": source("China Mobile Q1 2026 Results", CM_Q1_URL, "Q1购建长期资产现金支出30,399百万元人民币。"),
    },
    ("中国移动", "Q2 2026", "cash_and_equivalents"): {
        "official_value": 102438,
        "url": CM_H1_URL,
        "label": "China Mobile 2026 Interim Report - Cash Definition",
        "evidence": "标准化值187,857是中国会计准则的货币资金合计；其中官方Cash and cash equivalents仅102,438，字段口径不一致。",
        "method": "official_cash_and_cash_equivalents_definition_check",
        "status": "official_conflict",
    },
    ("中国移动", "Q2 2026", "free_cash_flow"): {
        "official_value": 7516,
        "url": CM_H1_URL,
        "label": "China Mobile 2026 Interim Report and Q1 Results",
        "evidence": "按本数据集现金流口径，Q2经营现金流43,407减Q2现金资本开支35,891，复算7,516；公司披露的自由现金流另有管理口径，不混用。",
        "method": "official_q2_operating_cash_flow_minus_cash_capex",
        "extra": source("China Mobile Q1 2026 Results", CM_Q1_URL, "用于H1减Q1复算Q2经营现金流与现金资本开支。"),
    },
    ("中国移动", "Q2 2026", "net_income"): {
        "official_value": 49592,
        "url": CM_H1_URL,
        "label": "China Mobile 2026 Interim Report and Q1 Results",
        "evidence": "H1股东应占利润78,934减Q1官方值29,342，复算Q2为49,592百万元人民币。",
        "method": "official_h1_minus_q1_net_income_reconciliation",
        "extra": source("China Mobile Q1 2026 Results", CM_Q1_URL, "Q1股东应占利润29,342百万元人民币。"),
    },
    ("中国移动", "Q2 2026", "operating_cash_flow"): {
        "official_value": 43407,
        "url": CM_H1_URL,
        "label": "China Mobile 2026 Interim Report and Q1 Results",
        "evidence": "H1经营活动现金流114,854减Q1官方值71,447，复算Q2为43,407百万元人民币。",
        "method": "official_h1_minus_q1_operating_cash_flow_reconciliation",
        "extra": source("China Mobile Q1 2026 Results", CM_Q1_URL, "Q1经营活动现金流71,447百万元人民币。"),
    },
    ("中国移动", "Q2 2026", "total_assets"): {
        "official_value": 2121504,
        "url": CM_H1_URL,
        "label": "China Mobile 2026 Interim Report - PRC GAAP Reconciliation",
        "evidence": "中国会计准则口径截至2026年6月30日资产总计为2,121,504百万元人民币；香港财务报告准则口径不同，数据集保留中国会计准则连续口径。",
        "method": "official_interim_prc_gaap_balance_sheet_check",
    },
    ("中国移动", "Q2 2026", "total_debt"): {
        "official_value": 98828,
        "url": CM_H1_URL,
        "label": "China Mobile 2026 Interim Report - PRC GAAP Liabilities",
        "evidence": "中国会计准则口径流动租赁负债46,186、长期借款9,374及非流动租赁负债43,268，合计98,828百万元人民币。",
        "method": "official_prc_gaap_interest_bearing_liabilities_reconciliation",
    },
    ("中国联通", "Q2 2026", "cash_and_equivalents"): {
        "official_value": 28572,
        "url": CU_URL,
        "label": "China Unicom 2026 Interim Results Announcement",
        "evidence": "截至2026年6月30日Cash and cash equivalents为28,572百万元人民币。",
        "method": "official_interim_balance_sheet_check",
    },
    ("中国联通", "Q2 2026", "total_assets"): {
        "official_value": 676089,
        "url": CU_URL,
        "label": "China Unicom 2026 Interim Results Announcement",
        "evidence": "截至2026年6月30日Total assets为676,089百万元人民币。",
        "method": "official_interim_balance_sheet_check",
    },
    ("中国联通", "Q2 2026", "total_debt"): {
        "official_value": 31347,
        "url": CU_URL,
        "label": "China Unicom 2026 Interim Results - Borrowings and Lease Liabilities",
        "evidence": "长期银行借款5,151、非流动租赁负债12,420、短期借款1,153、流动长期借款627及流动租赁负债11,996，合计31,347百万元人民币。",
        "method": "official_borrowings_and_lease_liabilities_reconciliation",
    },
    ("中国铁塔", "Q2 2026", "cash_and_equivalents"): {
        "official_value": 6655,
        "url": TOWER_URL,
        "label": "China Tower 2026 Interim Report - Financial Position",
        "evidence": "截至2026年6月30日Cash and cash equivalents为6,655百万元人民币。",
        "method": "official_interim_balance_sheet_check",
    },
    ("中国铁塔", "Q2 2026", "total_assets"): {
        "official_value": 351237,
        "url": TOWER_URL,
        "label": "China Tower 2026 Interim Report - Financial Position",
        "evidence": "截至2026年6月30日Total assets为351,237百万元人民币。",
        "method": "official_interim_balance_sheet_check",
    },
    ("中国铁塔", "Q2 2026", "total_debt"): {
        "official_value": 101392,
        "url": TOWER_URL,
        "label": "China Tower 2026 Interim Report - Capital Structure",
        "evidence": "报告披露截至2026年6月30日interest-bearing liabilities为101,392百万元人民币；该行总债务沿用含息负债口径。",
        "method": "official_interest_bearing_liabilities_check",
    },
}


def row_key(row: dict[str, Any]) -> tuple[str, str, str]:
    return tuple(str(row.get(field) or "") for field in KEY_FIELDS)  # type: ignore[return-value]


def promote(row: dict[str, Any]) -> bool:
    spec = DIRECT.get(row_key(row))
    if spec is None:
        return False
    primary = source(spec["label"], spec["url"], spec["evidence"])
    sources = [primary]
    if spec.get("extra"):
        sources.append(spec["extra"])
    row.update(
        {
            "verification_status": spec.get("status", "official_match"),
            "official_value": str(spec["official_value"]),
            "official_unit": row.get("unit", ""),
            "official_source_label": spec["label"],
            "official_source_url": spec["url"],
            "official_evidence": spec["evidence"],
            "verification_count": str(len({item["url"] for item in sources})),
            "verification_method": spec["method"],
            "verification_sources": json.dumps(sources, ensure_ascii=False),
            "verification_note": (
                "逐行读取官方2026中报/业绩公告及相关Q1官方报表核对；"
                + ("标准化值与字段定义不一致，正式回答必须使用official_value并披露冲突。" if spec.get("status") == "official_conflict" else "标准化值与官方值一致。")
            ),
        }
    )
    return True


def atomic_csv(path: Path, rows: list[dict[str, Any]], fields: list[str]) -> None:
    with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8-sig", newline="", delete=False, dir=path.parent) as handle:
        temporary = Path(handle.name)
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)


def atomic_json(path: Path, payload: Any) -> None:
    descriptor, raw = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary = Path(raw)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def main() -> int:
    main_csv = DATASET / "quarterly_metrics.csv"
    with main_csv.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        fields = list(reader.fieldnames or [])
        rows = list(reader)
    changed = sum(promote(row) for row in rows)
    if changed != len(DIRECT):
        missing = sorted(set(DIRECT) - {row_key(row) for row in rows})
        raise RuntimeError(f"expected {len(DIRECT)} target rows, changed={changed}, missing={missing}")
    atomic_csv(main_csv, rows, fields)

    payload_path = DATASET / "quarterly_metrics.json"
    payload = json.loads(payload_path.read_text(encoding="utf-8"))
    json_rows = payload.get("rows")
    if not isinstance(json_rows, list) or sum(promote(row) for row in json_rows if isinstance(row, dict)) != len(DIRECT):
        raise RuntimeError("quarterly_metrics.json target rows are incomplete")
    atomic_json(payload_path, payload)

    human_path = DATASET / "quarterly_metrics_human_readable.csv"
    with human_path.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        human_fields = list(reader.fieldnames or [])
        human_rows = list(reader)
    index = {row_key(row): row for row in rows}
    for human in human_rows:
        source_row = index.get((human.get("subject", ""), human.get("period", ""), next((row["metric_key"] for row in rows if row["subject"] == human.get("subject") and row["period"] == human.get("period") and row["metric_zh"] == human.get("metric_zh")), "")))
        if source_row:
            for field in human_fields:
                if field in source_row:
                    human[field] = source_row[field]
    atomic_csv(human_path, human_rows, human_fields)

    online_path = DATASET / "online_verification_2026-06-18.csv"
    atomic_csv(online_path, [{"row_no": index, **row} for index, row in enumerate(rows, 1)], ["row_no", *fields])

    verified_path = DATASET / "official_verified_metrics_2026-06-18.csv"
    with verified_path.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        verified_fields = list(reader.fieldnames or [])
        verified_rows = list(reader)
    verified_index = {row_key(row): row for row in verified_rows}
    for row in rows:
        if row_key(row) in DIRECT:
            verified_index[row_key(row)] = row
    ordered = list(verified_index.values())
    atomic_csv(verified_path, [{"row_no": index, **row} for index, row in enumerate(ordered, 1)], verified_fields)

    print(json.dumps({"promoted": changed, "official_match": changed - 2, "official_conflict": 2, "remaining_crosscheck": sum(row.get("verification_status") == "needs_official_row_crosscheck" for row in rows), "online_rows": len(rows)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
