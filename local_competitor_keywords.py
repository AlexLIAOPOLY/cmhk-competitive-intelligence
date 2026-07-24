"""Fixed Hong Kong competitor aliases used by every news discovery run.

These terms are intentionally independent from the Feishu monitoring sheet.
The sheet remains the user-editable search layer, while this module provides a
minimum recall floor for direct Hong Kong competitors and their owned brands.

Official relationship references checked on 2026-07-24:
- OFCA operator list:
  https://www.ofca.gov.hk/en/consumer_focus/operators_information/telecommunications_services_providers/index.html
- HKT group entities and operating businesses:
  https://www.hkt.com/privacy-statement/for_customers/index.page?locale=en
- HKBN group/newsroom:
  https://www.hkbn.net/group/
- SmarTone interim report (Birdie):
  https://www.smartoneholdings.com/about/investor/financial_reports/english/2024_2025_interim.pdf
- Hutchison Telecom Hong Kong brand statement:
  https://web.three.com.hk/3business/aboutus-press250925.html
- HGC group:
  https://www.hgc.com.hk/
- i-CABLE businesses:
  https://www.i-cablecomm.com/en/our-businesses
- China Telecom CTExcel brand:
  https://www.ctexcel.com/global/aboutUs-brandIntroduction-en.html
- China Unicom Hong Kong/CUniq:
  https://store.cuniq.com/en/terms/terms-and-conditions
"""

from __future__ import annotations

from typing import Any


# Keep each group at five terms or fewer. Search engines handle these compact
# exact-phrase OR queries more reliably than a single very long entity query.
LOCAL_COMPETITORS: tuple[dict[str, Any], ...] = (
    {
        "canonical": "HKT",
        "priority": 0,
        "search_groups": (
            ("HKT", "Hong Kong Telecommunications", "香港電訊", "香港电讯"),
            ("PCCW", "電訊盈科", "电讯盈科"),
            ("csl", "1O1O", "Club SIM", "1O1O HOME"),
            ("Tap & Go", "拍住賞", "拍住赏", "HKT Payment", "GoWallet"),
            ("NETVIGATOR", "網上行", "网上行", "Now TV", "Now E"),
            (
                "HKT Enterprise Solutions",
                "HKT Merchant Services",
                "HKT Business Broadband",
                "HKT Smart Living",
                "Club Care",
            ),
        ),
    },
    {
        "canonical": "HKBN",
        "priority": 1,
        "search_groups": (
            ("HKBN", "Hong Kong Broadband Network", "香港寬頻", "香港宽频"),
            ("HKBN Enterprise Solutions", "HKBNES", "HKBN JOS"),
            ("N mobile", "HKBN Mobile", "HKBN SAFE"),
        ),
    },
    {
        "canonical": "SmarTone",
        "priority": 1,
        "search_groups": (
            ("SmarTone", "數碼通", "数码通", "SmarTone Solutions"),
            ("Birdie Mobile", "SmarTone Birdie", "SmarTone Plus", "HomePhone+"),
        ),
    },
    {
        "canonical": "3 Hong Kong",
        "priority": 1,
        "search_groups": (
            ("3 Hong Kong", "Three Hong Kong", "3HK", "3香港", "3 香港"),
            (
                "Hutchison Telecom Hong Kong",
                "Hutchison Telecommunications Hong Kong",
                "HTHK",
                "和記電訊香港",
                "和记电讯香港",
            ),
            ("3Business", "3SUPREME", "SoSIM", "MO+", "SUPREME Executive"),
        ),
    },
    {
        "canonical": "HGC",
        "priority": 1,
        "search_groups": (
            (
                "HGC",
                "HGC Global Communications",
                "環球全域電訊",
                "环球全域电讯",
            ),
            ("Macroview Telecom", "HGC Macroview", "HGC GlobalCentre"),
        ),
    },
    {
        "canonical": "i-CABLE",
        "priority": 1,
        "search_groups": (
            ("i-CABLE", "i-CABLE Communications", "有線寬頻", "有线宽频"),
            (
                "Hong Kong Cable Television",
                "香港有線電視",
                "香港有线电视",
                "CTF Media & Entertainment",
                "周大福媒體娛樂",
            ),
            ("HOY TV", "HOY 76", "HOY 77", "HOY 78"),
        ),
    },
    {
        "canonical": "China Telecom Global (Hong Kong)",
        "priority": 1,
        "search_groups": (
            (
                "China Telecom Global",
                "CTG Hong Kong",
                "中國電信國際",
                "中国电信国际",
            ),
            (
                "China Telecom Hong Kong",
                "中國電信香港",
                "中国电信香港",
                "CTExcel",
                "China Telecom CTExcel",
            ),
        ),
    },
    {
        "canonical": "China Unicom Hong Kong",
        "priority": 1,
        "search_groups": (
            (
                "China Unicom Hong Kong",
                "China Unicom (Hong Kong) Operations",
                "中國聯通香港",
                "中国联通香港",
                "香港聯通",
            ),
            ("CUniq", "MyCUniq", "CUniqSIM", "中國聯通國際", "中国联通国际"),
        ),
    },
)


def mandatory_search_groups() -> tuple[dict[str, Any], ...]:
    """Return one compact, mandatory search plan per competitor alias group."""
    plans: list[dict[str, Any]] = []
    for competitor in LOCAL_COMPETITORS:
        canonical = str(competitor["canonical"])
        priority = int(competitor.get("priority", 1))
        for aliases in competitor.get("search_groups") or ():
            terms = tuple(str(term).strip() for term in aliases if str(term).strip())
            if not terms:
                continue
            plans.append(
                {
                    "canonical": canonical,
                    "priority": priority,
                    "terms": terms,
                }
            )
    return tuple(plans)


def all_aliases() -> tuple[str, ...]:
    """Return all fixed aliases without duplicates, preserving declaration order."""
    return tuple(
        dict.fromkeys(
            term
            for group in mandatory_search_groups()
            for term in group["terms"]
        )
    )


def priority_for(canonical: str) -> int:
    """Return local-competitor display priority; unknown entities sort last."""
    target = str(canonical or "").casefold()
    for competitor in LOCAL_COMPETITORS:
        if str(competitor["canonical"]).casefold() == target:
            return int(competitor.get("priority", 1))
    return 2
