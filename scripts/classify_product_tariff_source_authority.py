#!/usr/bin/env python3
"""Classify tariff rows without losing non-issuer market evidence.

Every row remains searchable.  Issuer/regulator evidence may support a current
tariff claim, while media, price-comparison, channel and member-offer evidence
is explicitly limited to market reference use.
"""

from __future__ import annotations

import csv
import os
import tempfile
from pathlib import Path
from urllib.parse import urlparse


ROOT = Path(__file__).resolve().parents[1]
CSV_PATH = ROOT / "agent_knowledge" / "competitor_product_tariffs" / "product_tariffs_formal_agent_records.csv"

ISSUER_HOST_SUFFIXES = (
    "1010.com.hk", "hkcsl.com", "hkcsl-5g.com", "hkt.com", "hkt-enterprise.com",
    "hkt-homephone.com", "hkt-sme.com", "netvigator.com", "pccwmobile.com",
    "three.com.hk", "hthkh.com", "smartone.com", "smartoneholdings.com",
    "hkbn.net", "hkbnes.net", "hkbnes.com", "sosimhk.com", "hgc.com.hk", "hgcbroadband.com", "i-cable.com",
    "i-cablebroadband-offer.com", "ofca.gov.hk",
)


def host(url: str) -> str:
    return (urlparse(url).hostname or "").lower()


def is_issuer_host(value: str) -> bool:
    return any(value == suffix or value.endswith(f".{suffix}") for suffix in ISSUER_HOST_SUFFIXES)


def classify(row: dict[str, str]) -> tuple[str, str, str]:
    status = (row.get("来源状态") or "").lower()
    source_host = host(row.get("来源URL") or "")
    if "needs_review" in status or any(token in status for token in ("media_reference", "news_release", "syndication", "market_snapshot")):
        return (
            "market_reference_tariff",
            "public_market_reference",
            "可检索和比较，但不得表述为运营商官方当前资费；回答必须显示来源性质与抓取期间。",
        )
    if is_issuer_host(source_host):
        return (
            "formal_product_tariff",
            "issuer_or_regulator_official",
            "可按来源期间用于正式资费比较；当前结论仍须遵守当前/历史时间标签。",
        )
    if "official" in status:
        return (
            "formal_product_tariff",
            "public_official_or_association",
            "可作为公开正式资料引用，但若非运营商域名，不得写成运营商官网报价。",
        )
    return (
        "market_reference_tariff",
        "public_market_reference",
        "可检索和比较，但不得表述为运营商官方当前资费；回答必须显示来源性质与抓取期间。",
    )


def main() -> int:
    with CSV_PATH.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        fields = list(reader.fieldnames or [])
        rows = list(reader)
    for field in ("source_authority", "usage_policy"):
        if field not in fields:
            fields.append(field)
    counts: dict[str, int] = {}
    for row in rows:
        record_class, authority, policy = classify(row)
        row["record_class"] = record_class
        row["source_authority"] = authority
        row["usage_policy"] = policy
        counts[authority] = counts.get(authority, 0) + 1
    with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8-sig", newline="", delete=False, dir=CSV_PATH.parent) as handle:
        temporary = Path(handle.name)
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, CSV_PATH)
    print({"rows": len(rows), **counts})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
