from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from cmhk.intelligence.executive import build_executive_intelligence_snapshot


DOMAIN_NAMES = {
    "local": "01 香港电讯市场",
    "mainland": "03 内地运营商",
    "cloud": "04 全球云厂商",
}


def build_rows() -> list[dict[str, object]]:
    snapshot = build_executive_intelligence_snapshot()
    rows: list[dict[str, object]] = []
    for domain in snapshot.get("domains") or []:
        domain_id = str(domain.get("id") or "")
        if domain_id not in DOMAIN_NAMES:
            continue
        for focus in domain.get("focuses") or []:
            metric = str(focus.get("label") or "")
            for entity in focus.get("items") or []:
                entity_name = str(entity.get("name") or "")
                for point in entity.get("trend") or []:
                    value = point.get("value")
                    source_urls = list(dict.fromkeys(str(url) for url in (point.get("source_urls") or []) if url))
                    verification_count = int(point.get("verification_count") or 0)
                    admitted = value is not None
                    if admitted and (verification_count < 3 or len(source_urls) < 3):
                        raise ValueError(
                            f"three-source gate failed: {domain_id}/{metric}/{entity_name}/{point.get('label')}"
                        )
                    rows.append(
                        {
                            "页签": DOMAIN_NAMES[domain_id],
                            "主体": entity_name,
                            "指标": metric,
                            "财年": str(point.get("label") or ""),
                            "数值": value,
                            "单位": str(point.get("unit") or ""),
                            "状态": "三来源核验通过" if admitted else "官方未单列/三来源不足，保留缺口",
                            "来源1": source_urls[0] if len(source_urls) > 0 else "",
                            "来源2": source_urls[1] if len(source_urls) > 1 else "",
                            "来源3": source_urls[2] if len(source_urls) > 2 else "",
                            "不同来源数": len(source_urls),
                            "口径说明": (
                                "只收录绝对数；移动用户总数或5G用户不替代后付费用户数。"
                                if metric == "后付费用户数"
                                else "只收录绝对数；不同页签按页面标注的统一单位展示。"
                            ),
                        }
                    )
    return rows


def main() -> None:
    rows = build_rows()
    print(json.dumps({"rows": rows}, ensure_ascii=False))


if __name__ == "__main__":
    main()
