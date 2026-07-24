from __future__ import annotations

import copy
import re
import unicodedata
from difflib import SequenceMatcher
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import news_discovery_digest as digest
import news_vote_service


_original_build_cards = digest._build_cards
_news_id_pattern = re.compile(r"<font color='grey'>([^<>]+)</font>")
_accepted_news_ids = {
    "NEWS-20260715-df05a2bb6c",
    "NEWS-20260715-a69cc4fd49",
    "NEWS-20260715-239e57cc38",
    "NEWS-20260714-bbc4a31093",
}
_carrier_terms = {
    "hkt", "pccw", "csl", "hkbn", "hgc", "smartone", "3hk",
    "3 hong kong", "icable", "i-cable", "中國移動香港", "中国移动香港",
    "cmhk", "中國聯通香港", "中国联通香港", "cuniq", "中國電信國際",
    "中国电信国际", "ctg", "ofca", "通訊事務管理局", "通讯事务管理局",
}
_strategic_terms = {
    "電訊", "电讯", "電信", "电信", "通訊", "通讯", "運營商", "运营商",
    "寬頻", "宽频", "光纖", "光纤", "頻譜", "频谱", "牌照", "漫遊", "漫游",
    "網絡", "网络", "5g", "6g", "衛星", "卫星", "數據中心", "数据中心",
    "算力", "人工智能", "ai", "大模型", "雲服務", "云服务", "網絡安全",
    "网络安全", "詐騙", "诈骗", "私隱", "隐私", "跨境數據", "跨境数据",
    "監管", "监管", "政策", "法規", "法规", "國安", "国安", "關稅", "关税",
    "制裁", "財報", "财报", "業績", "业绩", "收入", "盈利", "ebitda",
    "投資", "投资", "收購", "收购", "合併", "合并", "合作", "戰略", "战略",
    "供應鏈", "供应链", "裁員", "裁员", "高管", "資料外洩", "数据泄露",
    "創科", "创科", "數字經濟", "数字经济", "河套", "北部都會區",
    "北部都会区", "新田科技城", "大灣區", "大湾区", "數碼港", "数码港",
    "科學園", "科学园",
}
_local_sources = {
    "有線新聞", "有线新闻", "i-cable", "icable", "香港01", "明報", "明报",
    "星島", "星岛", "東方日報", "东方日报", "大公文匯", "大公文汇",
    "文匯報", "文汇报", "香港電台", "香港电台", "rthk", "now新聞", "now新闻",
}
_local_noise_terms = {
    "天文台", "暴雨", "颱風", "台风", "三伏天", "每日樓市", "每日楼市",
    "樓市成交", "楼市成交", "六合彩", "賽馬", "赛马", "交通意外", "娛樂",
    "娱乐", "明星", "飲食", "饮食", "旅遊攻略", "旅游攻略", "足球", "籃球",
    "球員", "球员", "亞運", "亚运",
}
_consumer_devices = {
    "iphone", "ipad", "macbook", "galaxy", "huawei pura", "華為 pura",
    "华为 pura", "xiaomi", "小米", "oppo", "vivo", "手機", "手机",
    "智能手錶", "智能手表", "耳機", "耳机",
}
_ad_terms = {
    "發布", "发布", "發表", "发表", "上市", "開賣", "开卖", "預售", "预售",
    "首發", "首发", "藍圖流出", "蓝图流出", "規格曝光", "规格曝光",
    "價格曝光", "价格曝光", "優惠", "优惠", "折扣", "促銷", "促销",
    "要來了", "要来了", "回歸5g", "回归5g", "港版", "國際版", "国际版",
    "規格現身", "规格现身", "正式發表", "正式发表", "官網", "官网",
}


def _vote_button(label: str, decision: str, news_id: str, button_type: str) -> dict[str, Any]:
    return {
        "tag": "button",
        "text": {"tag": "plain_text", "content": label},
        "type": button_type,
        "value": {
            "action": "news_vote",
            "decision": decision,
            "news_id": news_id,
        },
    }


def _normalized_title(title: str) -> str:
    text = unicodedata.normalize("NFKC", title).lower()
    text = re.sub(r"\s*[-–—|｜]\s*[^-–—|｜]{1,32}$", "", text)
    return re.sub(r"[^0-9a-z\u3400-\u9fff]+", "", text)


def _canonical_url(url: str) -> str:
    try:
        parts = urlsplit(url)
        query = urlencode(
            (key, value)
            for key, value in parse_qsl(parts.query, keep_blank_values=True)
            if not key.lower().startswith("utm_") and key.lower() not in {"oc", "gclid"}
        )
        return urlunsplit((parts.scheme.lower(), parts.netloc.lower(), parts.path.rstrip("/"), query, ""))
    except Exception:
        return url


def _contains_any(text: str, terms: set[str]) -> bool:
    lowered = text.lower()
    return any(term in lowered for term in terms)


def _is_noise(item: dict[str, Any]) -> bool:
    news_id = str(item.get("news_id", ""))
    if news_id in _accepted_news_ids:
        return False
    title = str(item.get("title", ""))
    snippet = str(item.get("snippet", ""))
    source = str(item.get("source", ""))
    snippet_for_relevance = snippet.lower()
    if source:
        snippet_for_relevance = snippet_for_relevance.replace(source.lower(), " ")
    content = f"{title.lower()} {snippet_for_relevance}"
    has_1010_brand = bool(re.search(r"(?<!\d)1010(?:\s*(?:hk|香港|mobile)|\b)", content))
    has_carrier = (
        bool(str(item.get("canonical_competitor") or "").strip())
        or _contains_any(content, _carrier_terms)
        or has_1010_brand
    )
    has_strategy = has_carrier or _contains_any(content, _strategic_terms)

    matched_keywords = {str(value).lower() for value in item.get("keywords", [])}
    if "1010" in matched_keywords and not has_1010_brand and not has_strategy:
        return True

    if (
        _contains_any(content, _consumer_devices)
        and not has_carrier
        and not _contains_any(content, {"監管", "监管", "供應鏈", "供应链", "投資", "投资", "數據中心", "数据中心"})
    ):
        return True
    if _contains_any(content, _local_noise_terms) and not has_strategy:
        return True
    if _contains_any(source, _local_sources) and not has_strategy:
        return True
    return False


def _curate_items(items: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], dict[str, int]]:
    kept: list[dict[str, Any]] = []
    seen_urls: set[str] = set()
    seen_titles: list[str] = []
    noise_count = 0
    duplicate_count = 0
    for item in items:
        if _is_noise(item):
            noise_count += 1
            continue
        title_key = _normalized_title(str(item.get("title", "")))
        url_key = _canonical_url(str(item.get("url", "")))
        duplicate = bool(url_key and url_key in seen_urls)
        if not duplicate and title_key:
            duplicate = any(
                title_key == previous
                or (
                    min(len(title_key), len(previous)) >= 16
                    and SequenceMatcher(None, title_key, previous).ratio() >= 0.90
                )
                for previous in seen_titles
            )
        if duplicate:
            duplicate_count += 1
            continue
        kept.append(item)
        if url_key:
            seen_urls.add(url_key)
        if title_key:
            seen_titles.append(title_key)
    return kept, {
        "original": len(items),
        "kept": len(kept),
        "duplicates": duplicate_count,
        "noise": noise_count,
    }


def _inject_vote_controls(card: dict[str, Any]) -> dict[str, Any]:
    card = copy.deepcopy(card)
    current_news_id = ""
    for element in card.get("elements", []):
        if element.get("tag") == "div":
            content = str(element.get("text", {}).get("content", ""))
            matches = _news_id_pattern.findall(content)
            if matches:
                current_news_id = matches[-1].strip()
        elif element.get("tag") == "action" and current_news_id:
            actions = element.setdefault("actions", [])
            if not any((action.get("value") or {}).get("action") == "news_vote" for action in actions):
                actions.extend(
                    [
                        _vote_button("确认进入滚动", "approve", current_news_id, "primary"),
                        _vote_button("暂缓", "hold", current_news_id, "default"),
                        _vote_button("不采纳", "reject", current_news_id, "danger"),
                    ]
                )
            current_news_id = ""
    for element in card.get("elements", []):
        if element.get("tag") == "note":
            notes = element.get("elements", [])
            if notes:
                notes[0]["content"] = (
                    "确认操作按成员分别记录，可重复点击修改个人选择；"
                    "多人结果不会由第一位点击者直接决定。"
                )
    return card


def _build_cards_with_votes(*args: Any, **kwargs: Any) -> list[dict[str, Any]]:
    call_kwargs = dict(kwargs)
    source_items = list(call_kwargs.get("items", []))
    curated, stats = _curate_items(source_items)
    call_kwargs["items"] = curated
    cards = [_inject_vote_controls(card) for card in _original_build_cards(*args, **call_kwargs)]
    if cards:
        for element in cards[0].get("elements", []):
            if element.get("tag") == "div":
                text = element.get("text", {})
                text["content"] = (
                    text.get("content", "")
                    + f"\n<font color='grey'>原始检索 {stats['original']} 条；去重/降噪后 {stats['kept']} 条；"
                    + f"重复 {stats['duplicates']} 条，产品广告或非战略本地生活 {stats['noise']} 条。</font>"
                )
                break
    return cards


digest._build_cards = _build_cards_with_votes


def send_digest(*args: Any, **kwargs: Any) -> dict[str, Any]:
    news_vote_service.ensure_started()
    return digest.send_digest(*args, **kwargs)


def main() -> None:
    news_vote_service.ensure_started()
    digest.main()


def _build_sheet_notice_cards(*args: Any, **kwargs: Any) -> list[dict[str, Any]]:
    curated, stats = _curate_items(
        [item for item in kwargs.get("items") or [] if isinstance(item, dict)]
    )
    updated = dict(kwargs)
    updated["items"] = curated
    from news_review_sheet import build_notice_cards

    return build_notice_cards(*args, curation_stats=stats, **updated)


def send_digest(*args: Any, **kwargs: Any) -> dict[str, Any]:
    digest._build_cards = _build_sheet_notice_cards
    return digest.send_digest(*args, **kwargs)


def main() -> None:
    digest._build_cards = _build_sheet_notice_cards
    digest.main()


if __name__ == "__main__":
    main()
