#!/usr/bin/env python3
"""Repair the July 28, 2026 review-sheet column shift with exact readback."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import news_review_sheet as review  # noqa: E402


BACKUP_PATH = Path(
    "/Users/liaowang/cmhk_public_crawl_app/curation_data/backups/"
    "news_review_sheet_before_3hk_exact_cleanup_20260727_105345.json"
)
DISCOVERY_PATH = Path(
    "/Users/liaowang/cmhk_public_crawl_app/strategy_briefing/"
    "news_discovery_latest.json"
)

DROP_TITLES = {
    "香港AI产品出口创新高": "与同批香港出口新闻重复且未找到当日对应原文",
    "美国埃尔帕索市通过数据中心政策框架": "查到的政策事件发生于此前月份，无法验证表内发布日期",
    "AI发展需关注自然环境影响与成本": "未找到表内日期及来源对应的独立新闻，且内容仅为泛泛评论",
    "Verizon门店参与Erie社区返校季背包赠送活动": "无法验证表内日期对应的原文",
    "MSNBC评论员分析特朗普对伊战争150天影响": (
        "仅为评论节目对局势的泛泛分析，未包含可验证的新政策、市场或经营事件"
    ),
    "AI抛售潮：中国的技术突破是否正在改变这一交易格局？": (
        "股市情绪与假设性分析，不是独立战略事件"
    ),
    "市场不再买单 AI 资本支出？辉达大跌 台股崩回4万2千点 台积电跌破2,300元": (
        "仅描述股价和市场情绪，没有独立业务或政策动作"
    ),
    "笔是机场｜如禁用中国AI模型 美国企业会受重创？": (
        "假设性评论文章，没有发生可验证的新监管动作"
    ),
    "韩股一度重挫逾7% AI相关疑虑造成晶片股价暴跌": (
        "仅描述股市波动与情绪，没有独立战略事件"
    ),
    "中国AI四强追赶美国": "泛趋势标题，缺少可验证的新动作或数据变化",
    "泽连斯基访美与俄乌战争地缘影响": (
        "来源媒体名被误识别为运营商Globe，且现有摘要不足以证明电信业务影响"
    ),
    "工业和信息化部发文提升中小企业数字化转型服务供给": (
        "地域被误标为香港本地，删除后按内地政策证据重新审核"
    ),
}

RECOVERY: dict[str, dict[str, str]] = {
    "工信部推动中小企业AI深度融合与数字化转型": {
        "url": "https://news.google.com/rss/articles/CBMicEFVX3lxTFBEXy14WUgxLUlXem5Ebm95amtkRjYyTVdhTlEzSmRzQW5jZjlHNjR0SEZqNWZpaTJJbE00VkVlWDE5R3ZseUhydEFrdG9RclhHRmdYZjNyeTJHeUdKSkJWR2J0SE9KbGQ4QW4zb091aVo?oc=5",
        "keywords": "工信部、人工智能、数字化转型",
    },
    "桥水基金：政府加强干预或增AI投资不确定性": {
        "match": "AI丨橋水基金:政府加強干預或增AI投資不確定性",
        "keywords": "AI、人工智能",
    },
    "香港出口创42年最大增幅AI需求成最大推手": {
        "url": "https://news.google.com/rss/articles/CBMid0FVX3lxTE9PN2k0YVh4VnFWN2FvNVRXc0s3b1pmNEY0RUVfT2J2bFdRU1pkOHJHWmd0SkNCYXNibkNTWW5pdDVWS3RHVW1YUXJrcGdhUGlHSFdOanVXWTl5czktUDMxeTROOUFaYzFjVG11VUdtRF9WUHdXR1NF?oc=5",
        "keywords": "AI、人工智能、香港GDP",
    },
    "AI公司SSI获英伟达投资算力将提升十倍": {
        "match": "NVIDIA砸50億美元投資AI新創SSI 強化算力與研發力",
        "source": "DIGITIMES",
        "source_date": "2026-07-28",
        "keywords": "AI、人工智能、算力",
    },
    "Kimi开源K3大模型权重并公布技术报告": {
        "url": "https://news.google.com/rss/articles/CBMiZkFVX3lxTE4yQzAxenhmaWFVenE1ZllIU2FDc0pQeGlFbjVMQkVrUEpDRUU1enJxR0ozbWRTYzVfRXo1R0hidUJveklwcjdxSElyRXRrRjBQMkUtLVA1UkwtaHVDbTRXT2hMbGRlUQ?oc=5",
        "keywords": "AI、大模型",
    },
    "OpenAI扩建都柏林总部释放AI算力需求信号": {
        "url": "https://hk.investing.com/news/stock-market-news/article-1571986",
        "keywords": "AI、人工智能、算力",
    },
    "AI技术监管与地缘政治风险信号": {
        "url": "https://www.investing.com/news/economy-news/openais-sam-altman-to-meet-with-senate-intelligence-committees-top-democrat-4814715",
        "source": "Investing.com",
        "source_date": "2026-07-27",
        "keywords": "AI、人工智能、技术制裁",
    },
    "沃达丰西班牙推出Finetwork服务应对品牌纠纷": {
        "match": "Vodafone Spain launches rival Finetwork offer amid brand dispute",
        "keywords": "Vodafone、MVNO",
    },
    "3香港推出三星Galaxy手机优惠最快8月初取机": {
        "match": "3香港推新Samsung Galaxy手機優惠",
        "keywords": "3香港、3HK",
    },
    "香港宽频沙田专门店开幕送Global SIM+旅游数据卡": {
        "match": "HKBN 香港寬頻沙田專門店開幕送 Global SIM+",
        "keywords": "HKBN、香港宽频",
    },
    "刘治经辞任有线宽频财务总裁何展文接任": {
        "match": "劉治經辭任有線寬頻財務總裁 何展文接任",
        "keywords": "i-cable、有线宽频",
    },
    "T-Mobile美国数千用户遭遇服务中断": {
        "match": "Downdetector數據顯示，T-Mobile在美國數千名用戶遭遇服務中斷",
        "keywords": "T-Mobile",
    },
    "Singtel获Opensignal评为新加坡最佳移动网络": {
        "match": "Singtel named Singapore’s best mobile network: Opensignal",
        "keywords": "Singtel、5G",
    },
    "Telstra扩展卫星能力覆盖澳大利亚全境": {
        "url": "https://www.telstra.com.au/exchange/satellite-to-mobile-lite-data-",
        "source": "Telstra",
        "keywords": "Telstra、Satellite communication、卫星通信",
    },
    "AT&T进军欧洲债市发行多币种债券": {
        "match": "AT&T 進軍歐洲債市，推出多重貨幣債券銷售",
        "keywords": "AT&T",
    },
    "AT&T扩大与D-Wave量子计算合作关系": {
        "match": "AT&T擴大與D-Wave的量子計算合作夥伴關係",
        "keywords": "AT&T、AI",
    },
    "SoftBank拟收购Blackstone旗下SP.LINKS股权": {
        "url": "https://es.marketscreener.com/noticias/blackstone-ultima-la-venta-de-su-participacion-en-sp-links-con-softbank-como-licitador-preferente-ce7f51dcda80ff23",
        "source": "MarketScreener",
        "keywords": "SoftBank",
    },
    "Orange收购法国5G专网专家Obvios": {
        "match": "Orange rescues French 5G private network specialist Obvios",
        "keywords": "Orange、5G private network、5G专网",
    },
    "Evercore维持Verizon买入评级，目标价50美元": {
        "match": "Evercore維持Verizon(VZ.US)買入評級",
        "keywords": "Verizon",
    },
    "软银为OpenAI持股的贷款引入新贷款人": {
        "url": "https://www.japantimes.co.jp/business/2026/07/27/companies/softbank-openai-stake-new-lenders/",
        "source": "The Japan Times",
        "source_date": "2026-07-27",
        "keywords": "SoftBank、AI",
    },
    "Scotiabank上调Verizon目标价至52.50美元": {
        "match": "Verizon Price Target Raised to $52.50/Share From $51.50 by Scotiabank",
        "keywords": "Verizon",
    },
    "AT&T携手打造美国智慧社区新未来": {
        "match": "感謝 AT&T 的信任與支持 攜手打造美國智慧社區新未來",
        "keywords": "AT&T、Smart City、智慧城市",
    },
    "沃达丰首季总收入按年增长9.7%": {
        "match": "Vodafone首季總收入按年增長9.7%",
        "keywords": "Vodafone",
    },
    "HKT举办2026科技周 共建香港AI创新枢纽": {
        "match": "HKT 科技周2026盛大啟幕",
        "source": "Yahoo",
        "source_date": "2026-07-27",
        "keywords": "HKT、AI、人工智能",
    },
    "Vodacom上调中期目标，Vodafone旗下业务增长强劲": {
        "url": "https://ca.marketscreener.com/news/south-africa-s-vodacom-lifts-medium-term-targets-after-safaricom-deal-ce7f51dcdb81f520",
        "source": "MarketScreener",
        "keywords": "Vodafone、Vodacom",
    },
    "全球资本押注AI，SoftBank获400亿美元巨额融资": {
        "match": "狂熱資金全面押注AI：從中國記憶體飆股到SoftBank 400億美元巨額融資",
        "keywords": "SoftBank、AI、人工智能",
    },
}


def _values(payload: Any) -> list[list[Any]]:
    rows = review._walk_for_key(payload, "values") or []
    output = [
        (list(row) + [""] * len(review.HEADERS))[: len(review.HEADERS)]
        for row in rows
        if isinstance(row, list) and any(str(cell or "").strip() for cell in row)
    ]
    return output


def _read_raw(sheet_id: str) -> list[list[Any]]:
    payload = review._lark(
        "sheets",
        "+read",
        "--spreadsheet-token",
        review.SPREADSHEET_TOKEN,
        "--sheet-id",
        sheet_id,
        "--range",
        f"A2:N{review.MAX_SHEET_ROWS}",
        "--value-render-option",
        "ToString",
    )
    return _values(payload)


def _backup_rows() -> list[list[Any]]:
    payload = json.loads(BACKUP_PATH.read_text(encoding="utf-8"))
    if isinstance(payload, list):
        return payload
    rows = payload.get("rows") if isinstance(payload, dict) else None
    if isinstance(rows, list):
        return rows
    for value in payload.values():
        if isinstance(value, list) and value and isinstance(value[0], list):
            return value
    raise RuntimeError("恢复备份中未找到行数据")


def _discovery_items() -> list[dict[str, Any]]:
    payload = json.loads(DISCOVERY_PATH.read_text(encoding="utf-8"))
    return [item for item in payload.get("items") or [] if isinstance(item, dict)]


def _match_discovery(config: dict[str, str], items: list[dict[str, Any]]) -> dict[str, Any]:
    marker = config.get("match", "")
    if not marker:
        return {}
    matches = [
        item
        for item in items
        if marker.casefold() in str(item.get("title") or "").casefold()
    ]
    exact_matches = [
        item
        for item in matches
        if marker.casefold() == str(item.get("title") or "").casefold()
    ]
    if len(exact_matches) == 1:
        return exact_matches[0]
    if len(matches) != 1:
        raise RuntimeError(f"本地发现结果 {marker!r} 匹配到 {len(matches)} 条")
    return matches[0]


def build_repaired_rows(current: list[list[Any]]) -> tuple[list[list[Any]], dict[str, Any]]:
    backup_by_title = {
        str((list(row) + [""] * 14)[6]).strip(): (list(row) + [""] * 14)[:14]
        for row in _backup_rows()
    }
    discovery = _discovery_items()
    repaired: list[list[Any]] = []
    audit = {
        "preserved_current": 0,
        "restored_from_backup": 0,
        "reconstructed": 0,
        "dropped": [],
        "duplicate_dropped": [],
    }
    for row_number, raw in enumerate(current, start=2):
        row = (list(raw) + [""] * 14)[:14]
        current_title = str(row[6]).strip()
        if current_title in DROP_TITLES:
            audit["dropped"].append(
                {
                    "row": row_number,
                    "title": current_title,
                    "reason": DROP_TITLES[current_title],
                }
            )
            continue
        if str(row[10]).startswith(("http://", "https://")):
            repaired.append(row)
            audit["preserved_current"] += 1
            continue
        shifted_title = str(row[9]).strip()
        if shifted_title in backup_by_title:
            restored = list(backup_by_title[shifted_title])
            restored[:3] = row[:3]
            repaired.append(restored)
            audit["restored_from_backup"] += 1
            continue
        if shifted_title in DROP_TITLES:
            audit["dropped"].append(
                {
                    "row": row_number,
                    "title": shifted_title,
                    "reason": DROP_TITLES[shifted_title],
                }
            )
            continue
        config = RECOVERY.get(shifted_title)
        if not config:
            raise RuntimeError(f"第{row_number}行缺少恢复配置：{shifted_title}")
        source_item = _match_discovery(config, discovery)
        url = config.get("url") or str(source_item.get("url") or "")
        source = config.get("source") or str(source_item.get("source") or row[11])
        source_date = (
            config.get("source_date")
            or review._publication_date(source_item.get("published_at"))
            or review._publication_date(row[12])
        )
        keywords = config["keywords"]
        is_competitor = str(row[8]).strip() == "竞对动态"
        reason = (
            f"正式监控竞对是事件主体；命中：{keywords}"
            if is_competitor
            else f"命中正式监控词且事件具有具体战略影响；命中：{keywords}"
        )
        rebuilt = [
            row[0],
            row[1],
            row[2],
            review._publication_date(row[5]),
            row[6],
            row[8],
            row[9],
            row[10],
            source,
            source_date,
            url,
            keywords,
            reason,
            f"历史新闻搜索（列恢复核验；命中：{keywords}）",
        ]
        repaired.append(rebuilt)
        audit["reconstructed"] += 1
    unique_rows: list[list[Any]] = []
    seen_urls: dict[str, str] = {}
    for row in repaired:
        canonical_url = review._canonical_news_url(row[10])
        if canonical_url in seen_urls:
            audit["duplicate_dropped"].append(
                {
                    "title": str(row[6]),
                    "duplicate_of": seen_urls[canonical_url],
                    "url": canonical_url,
                }
            )
            continue
        seen_urls[canonical_url] = str(row[6])
        unique_rows.append(row)
    review._validate_sheet_rows(unique_rows, context="修复结果")
    return unique_rows, audit


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    state = json.loads(review.STATE_PATH.read_text(encoding="utf-8"))
    sheet_id = str(state["sheet_id"])
    current = _read_raw(sheet_id)
    repaired, audit = build_repaired_rows(current)
    timestamp = datetime.now(review.HKT).strftime("%Y%m%d_%H%M%S")
    report = {
        "sheet_id": sheet_id,
        "current_count": len(current),
        "repaired_count": len(repaired),
        **audit,
    }
    if not args.apply:
        print(json.dumps({"mode": "dry-run", **report}, ensure_ascii=False, indent=2))
        return 0
    backup_dir = ROOT / "curation_data" / "backups"
    backup_dir.mkdir(parents=True, exist_ok=True)
    corrupted_backup = backup_dir / f"news_review_sheet_corrupted_{timestamp}.json"
    corrupted_backup.write_text(
        json.dumps(
            {
                "created_at": datetime.now(review.HKT).isoformat(timespec="seconds"),
                "sheet_id": sheet_id,
                "rows": current,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    for offset in range(0, len(repaired), 40):
        chunk = repaired[offset : offset + 40]
        start = 2 + offset
        review._write(sheet_id, f"A{start}:N{start + len(chunk) - 1}", chunk)
    if len(repaired) < len(current):
        start = 2 + len(repaired)
        count = len(current) - len(repaired)
        review._write(
            sheet_id,
            f"A{start}:N{start + count - 1}",
            [[""] * 14 for _ in range(count)],
        )
    readback = _read_raw(sheet_id)
    expected = [[review._text(cell, 5000) for cell in row] for row in repaired]
    actual = [[review._text(cell, 5000) for cell in row] for row in readback]
    if actual != expected:
        raise RuntimeError("修复写入后逐格回读不一致")
    state["last_candidate_count"] = len(repaired)
    review._write_json(review.STATE_PATH, state)
    print(
        json.dumps(
            {
                "mode": "applied",
                "backup": str(corrupted_backup),
                "readback_exact": True,
                **report,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
