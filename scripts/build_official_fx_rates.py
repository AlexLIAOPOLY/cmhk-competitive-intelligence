#!/usr/bin/env python3
"""Build deterministic annual-average FX inputs for international comparisons."""

from __future__ import annotations

import argparse
import json
import urllib.request
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "agent_knowledge/global_top5_operators_2016_2025/annual_fx_rates.json"
INDICATOR = "PA.NUS.FCRF"
COUNTRIES = {
    "DEU": "EUR",
    "IND": "INR",
    "JPN": "JPY",
    "KOR": "KRW",
    "SGP": "SGD",
    "USA": "USD",
}
START_YEAR = 2016
END_YEAR = 2025


def build_payload() -> dict[str, object]:
    country_codes = ";".join(COUNTRIES)
    source_url = (
        "https://api.worldbank.org/v2/country/"
        f"{country_codes}/indicator/{INDICATOR}"
        f"?date={START_YEAR}:{END_YEAR}&format=json&per_page=200"
    )
    request = urllib.request.Request(source_url, headers={"User-Agent": "CMHK-data-governance/1.0"})
    with urllib.request.urlopen(request, timeout=30) as response:
        body = json.loads(response.read().decode("utf-8"))
    observations = body[1] if isinstance(body, list) and len(body) > 1 else []
    rates: list[dict[str, object]] = []
    for item in observations:
        country = str(item.get("countryiso3code") or "")
        if country not in COUNTRIES or item.get("value") is None:
            continue
        year = int(item["date"])
        if START_YEAR <= year <= END_YEAR:
            rates.append(
                {
                    "currency": COUNTRIES[country],
                    "country": country,
                    "year": year,
                    "local_per_usd": float(item["value"]),
                    "observation_status": str(item.get("obs_status") or ""),
                }
            )
    expected = {(currency, year) for currency in COUNTRIES.values() for year in range(START_YEAR, END_YEAR + 1)}
    actual = {(str(item["currency"]), int(item["year"])) for item in rates}
    missing = sorted(expected - actual)
    if missing:
        raise RuntimeError(f"World Bank FX response is incomplete: {missing}")
    return {
        "id": "official_annual_average_fx_to_usd_2016_2025",
        "indicator": INDICATOR,
        "indicator_label": "Official exchange rate (LCU per US$, period average)",
        "publisher": "World Bank World Development Indicators",
        "source_organization": "International Monetary Fund, International Financial Statistics database",
        "source_url": source_url,
        "method": "reported local-currency value divided by the calendar-year average rate matching the metric year field",
        "period_boundary": "calendar-year average keyed by metric year; not a monthly weighted average for non-calendar fiscal years",
        "usage_policy": "analysis-only currency translation; never replaces the operator's reported value or accounting currency",
        "years": [START_YEAR, END_YEAR],
        "rates": sorted(rates, key=lambda item: (str(item["currency"]), int(item["year"]))),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=OUTPUT)
    args = parser.parse_args()
    payload = build_payload()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {args.output} rates={len(payload['rates'])}")


if __name__ == "__main__":
    main()
