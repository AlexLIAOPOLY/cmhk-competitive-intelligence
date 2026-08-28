"""Evidence-backed data shaping for the competitor intelligence map workspace."""

from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path


ENTITY_ALIASES = {
    "HKT / csl": ("hkt", "csl", "香港电讯", "香港電訊", "电讯盈科", "電訊盈科", "pccw"),
    "HKBN": ("hkbn", "香港宽频", "香港寬頻"),
    "SmarTone": ("smartone", "数码通", "數碼通"),
    "3香港": ("3香港", "3hk", "和记电讯", "和記電訊", "hutchison"),
    "i-CABLE": ("i-cable", "有线宽频", "有線寬頻"),
    "CMHK": ("cmhk", "中国移动香港", "中國移動香港"),
    "华为": ("华为", "華為", "huawei"),
    "中兴通讯": ("中兴", "中興", "zte"),
    "AWS": ("aws", "amazon web services"),
    "Microsoft": ("microsoft", "微软", "微軟", "azure"),
    "Google": ("google", "谷歌", "google cloud"),
}

CONCEPT_ALIASES = {
    "AI / 算力": ("ai", "人工智能", "人工智慧", "大模型", "算力", "gpu"),
    "5G / 6G": ("5g", "6g"),
    "云服务": ("云服务", "雲服務", "云计算", "雲計算", "cloud"),
    "资费套餐": ("资费", "資費", "套餐", "月费", "月費"),
    "数据中心": ("数据中心", "數據中心", "data center", "datacentre"),
    "网络建设": ("网络建设", "網絡建設", "基站", "频谱", "頻譜", "网络覆盖", "網絡覆蓋"),
    "政策监管": ("政策", "监管", "監管", "牌照", "规管", "規管"),
    "边缘计算": ("边缘计算", "邊緣計算", "edge computing"),
    "企业服务": ("企业服务", "企業服務", "b2b", "企业客户", "企業客戶"),
}


def _load_json(path: Path) -> dict:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _date(value: object) -> str:
    raw = str(value or "").strip()
    match = re.search(r"\d{4}-\d{2}-\d{2}", raw)
    return match.group(0) if match else ""


def _matches(text: str, aliases: tuple[str, ...]) -> bool:
    folded = text.casefold()
    return any(alias.casefold() in folded for alias in aliases)


def _labels(text: str, aliases: dict[str, tuple[str, ...]]) -> list[str]:
    return [label for label, terms in aliases.items() if _matches(text, terms)]


def build_competitor_intelligence_map(root: Path) -> dict:
    """Return approved intelligence records with explicit graph classifications."""

    source_path = root / "strategy_briefing" / "published.json"
    payload = _load_json(source_path)
    raw_items = payload.get("items") if isinstance(payload.get("items"), list) else []
    items: list[dict] = []
    for index, raw in enumerate(raw_items):
        if not isinstance(raw, dict):
            continue
        title = str(raw.get("title") or "").strip()
        summary = str(raw.get("summary") or "").strip()
        keywords = str(raw.get("keywords") or "").strip()
        source_date = _date(raw.get("source_date") or raw.get("published_at") or raw.get("approved_at"))
        if not title or not source_date:
            continue
        evidence_text = " ".join((title, summary, keywords))
        items.append({
            "id": str(raw.get("id") or f"approved-{index + 1}"),
            "title": title,
            "summary": summary,
            "category": str(raw.get("category") or "其他情报").strip(),
            "region": str(raw.get("region") or "未标注地区").strip(),
            "source": str(raw.get("source") or "未标注来源").strip(),
            "sourceDate": source_date,
            "sourceUrl": str(raw.get("source_url") or "").strip(),
            "keywords": keywords,
            "entities": _labels(evidence_text, ENTITY_ALIASES),
            "concepts": _labels(evidence_text, CONCEPT_ALIASES),
        })

    items.sort(key=lambda item: (item["sourceDate"], item["id"]), reverse=True)
    dates = sorted({item["sourceDate"] for item in items})
    return {
        "ok": True,
        "source": "strategy_briefing/published.json",
        "sourceLabel": "已审核战略情报",
        "updatedAt": str(payload.get("updated_at") or datetime.now().astimezone().isoformat(timespec="seconds")),
        "coverageStart": dates[0] if dates else "",
        "coverageEnd": dates[-1] if dates else "",
        "items": items,
    }
