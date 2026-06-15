from __future__ import annotations

import html
import json
import re
from copy import deepcopy
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from docx import Document
from docx.enum.table import WD_TABLE_ALIGNMENT, WD_CELL_VERTICAL_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Inches, Pt

from crawl_settings import enabled_rows
from company_metrics import build_company_metrics_payload


ROOT = Path(__file__).resolve().parent
RESULTS_DIR = ROOT / "results"

WEEKLY_MD = ROOT / "weekly_report.md"
WEEKLY_HTML = ROOT / "weekly_report.html"
def dated_weekly_docx_path(now: datetime | None = None) -> Path:
    value = now or datetime.now(ZoneInfo("Asia/Hong_Kong"))
    base_name = f"{value.month}月{value.day}日周报"
    path = ROOT / f"{base_name}.docx"
    if not path.exists():
        return path
    counter = 1
    while True:
        path = ROOT / f"{base_name} ({counter}).docx"
        if not path.exists():
            return path
        counter += 1


WEEKLY_DOCX = dated_weekly_docx_path()
TEMPLATE_MD = ROOT / "weekly_report_template.md"
TEMPLATE_DOCX = ROOT / "weekly_report_template.docx"
LOCAL_WORD_TEMPLATE = Path("/Users/liaowang/Downloads/模板.docx")
REPO_WORD_TEMPLATE = ROOT / "weekly_report_template.docx"
SOURCE_WORD_TEMPLATE = LOCAL_WORD_TEMPLATE if LOCAL_WORD_TEMPLATE.exists() else REPO_WORD_TEMPLATE

# Keep these aliases so older automation does not keep serving the wrong
# "agent run" report format.
AGENT_MD_ALIAS = ROOT / "agent_report.md"
AGENT_HTML_ALIAS = ROOT / "agent_report.html"

SECTION_ORDER = ["政治资讯", "行业资讯", "社会资讯", "国际资讯"]
WEEKLY_MAX_PER_SECTION = 4
WEEKLY_SECTION_LIMITS = {
    "政治资讯": 4,
    "行业资讯": 8,
    "社会资讯": 4,
    "国际资讯": 4,
}

FORBIDDEN_REPORT_PHRASES = (
    "本轮成功来源",
    "可复核字段",
    "待补充字段",
    "形成公开信息更新",
    "爬虫",
    "爬取成功",
    "抓取成功",
    "相关动态更新",
)

# Weekly reports are decision materials, not crawler diagnostics. Each entry
# below is tied to a distinctive phrase in a successfully retrieved source.
# If the evidence is absent, the entry is omitted instead of being padded with
# extraction counts or field names.
FACTUAL_ITEMS = {
    2: {
        "evidence": "HKT Trust and HKT Revenue",
        "title": "HKT 2025年收入增长至365.5亿港元",
        "detail": (
            "HKT 2025年收入为365.5亿港元，同比增长5.18%；移动服务收入受5G升级及漫游业务带动增长，"
            "5G客户规模增至174.7万户，同比增长25%。"
        ),
    },
    3: {
        "evidence": "Monthly Plan Fee",
        "title": "csl更新5G服务计划及多用户副卡安排",
        "detail": (
            "csl官网显示，指定5G月费计划月费348港元，包含100GB本地数据及3GB中国内地和澳门漫游数据；"
            "同一主计划可按阶梯月费增加副卡，强化家庭及多终端共享场景。"
        ),
    },
    4: {
        "evidence": "Open APIs Powering Hong Kong",
        "title": "HKT以开放网络API拓展企业数字化服务",
        "detail": (
            "HKT企业方案介绍开放网络API在身份验证、防欺诈和客户体验等场景的应用，"
            "推动网络能力由连接服务向可调用的企业数字化能力延伸。"
        ),
    },
    5: {
        "evidence": "2025 ANNUAL REPORT",
        "title": "和记电讯香港2025年收入增长17%",
        "detail": (
            "和记电讯香港2025年香港业务总收入为54.48亿港元，同比增长17%；客户服务净收入36.19亿港元，"
            "同比增长6%，漫游服务收入8.55亿港元，同比增长31%。"
        ),
    },
    6: {
        "evidence": "WORLD PLAN",
        "title": "3香港推出覆盖全球使用场景的World Plan",
        "detail": (
            "3香港World Plan允许套餐数据在香港及海外目的地使用，并提供免费漫游通话、到埗连接及旅游保障等权益；"
            "3Business同时提供30GB及60GB本地数据的企业5G月费方案。"
        ),
    },
    7: {
        "evidence": "Launching Three Caring 5G Service Plans",
        "title": "3香港推出三款家庭关怀5G服务计划",
        "detail": (
            "和记电讯香港于2026年5月22日推出三款围绕家庭需要设计的5G服务计划，"
            "把通信服务与家庭数字生活权益整合至单一套餐。"
        ),
    },
    8: {
        "evidence": "INTERIM REPORT 2025/26",
        "title": "SmarTone上半财年本地服务收入增至18.71亿港元",
        "detail": (
            "SmarTone 2025/26上半财年本地服务收入增至18.71亿港元；撇除一次性项目后，"
            "股东应占溢利为2.56亿港元，同比增长4%，运营成本同比下降6%。"
        ),
    },
    9: {
        "evidence": "Monthly fee from $99",
        "title": "SmarTone强化AI与5G融合套餐布局",
        "detail": (
            "SmarTone官网将AI服务入口纳入5G产品体系，并提供月费99港元起的4.5G计划及中国内地、澳门漫游数据；"
            "其服务组合进一步覆盖AI应用、5G家居宽频和数字生活内容。"
        ),
    },
    10: {
        "evidence": "FY26 Interim Results Presentation",
        "title": "SmarTone推进5G-Advanced及家居宽频业务",
        "detail": (
            "SmarTone在2025/26上半财年业绩材料中表示，已通过5G-Advanced及网络切片为高端客户提供三倍网络资源；"
            "截至2025年12月，5G家居宽频客户按年增长10%，渗透率升至70%。"
        ),
    },
    11: {
        "evidence": "Total revenue showed a strong performance",
        "title": "HKBN 2025财年收入及EBITDA同步增长",
        "detail": (
            "HKBN 2025财年总收入同比增长4%至111.29亿港元，核心服务收入同比增长7%，"
            "EBITDA同比增长4%至24.51亿港元；净利润由1,000万港元升至2.07亿港元。"
        ),
    },
    14: {
        "evidence": "Exclusive Distribution Partnership with HIKMICRO",
        "title": "HKBN与HIKMICRO建立智能安防独家分销合作",
        "detail": (
            "HKBN企业方案于2026年4月1日宣布与HIKMICRO建立独家分销合作，"
            "把红外热成像及智能安防方案纳入企业服务组合，面向设施管理和商业安全场景推广。"
        ),
    },
    19: {
        "evidence": "Singtel posts FY26 net profit",
        "title": "Singtel FY26净利润达到56.1亿新元",
        "detail": (
            "Singtel于2026年5月21日公布FY26净利润56.1亿新元；基础净利润同比增长12%至27.7亿新元。"
            "公司同时与爱立信合作推进5G-Advanced行业应用。"
        ),
    },
    20: {
        "evidence": "BT Group and Ericsson strengthen partnership",
        "title": "BT与爱立信深化合作提升企业5G服务能力",
        "detail": (
            "BT集团与爱立信深化5G合作，面向英国企业提升网络可靠性和智能化服务能力，"
            "相关合作聚焦企业连接体验及更灵活的5G能力应用。"
        ),
    },
    21: {
        "evidence": "reports AED 19.4 billion consolidated revenue",
        "title": "e& 2026年一季度合并收入达到194亿迪拉姆",
        "detail": (
            "e&公布2026年一季度合并收入194亿阿联酋迪拉姆，并继续推进企业AI、云边协同及5G-Advanced布局；"
            "其企业业务与Emergence AI建立合作，面向企业提供可灵活部署的生成式AI方案。"
        ),
    },
    22: {
        "evidence": "Accelerate the development of the Northern Metropolis",
        "title": "香港施政重点加快北部都会区及创科产业发展",
        "detail": (
            "香港2025年施政报告把加快北部都会区建设、推动产业发展与改革、促进教育科技人才一体化发展列为重点，"
            "并强调融入国家发展大局及支持本地经济。"
        ),
    },
    26: {
        "evidence": "Checklist on Guidelines for the Use of Generative AI by Employees",
        "title": "私隐专员公署发布雇员使用生成式AI指引清单",
        "detail": (
            "香港个人资料私隐专员公署发布雇员使用生成式AI指引清单，要求机构制定内部使用政策，"
            "并在应用生成式AI时遵守《个人资料（私隐）条例》；相关材料亦覆盖深度伪造风险和AI个人资料保障框架。"
        ),
    },
    27: {
        "evidence": "Data Act enters into force",
        "title": "欧盟《数据法案》确立联网产品数据访问与共享规则",
        "detail": (
            "欧盟《数据法案》建立联网产品及相关服务数据的访问、使用和共享规则，"
            "并与GDPR等数据保护制度共同构成企业在欧盟开展数据业务时需要遵循的合规框架。"
        ),
    },
    28: {
        "evidence": "Spectrum Release Plan",
        "title": "OFCA公布2026至2028年频谱释放安排",
        "detail": (
            "香港通讯事务管理局办公室列出2026至2028年频谱释放计划，并持续推进2.5/2.6 GHz、"
            "850/900 MHz、2.3 GHz及6/7 GHz等频段安排，同时实施偏远地区光纤及5G覆盖资助计划。"
        ),
    },
    29: {
        "evidence": "WSIS Forum: Renewed push for global digital development",
        "title": "ITU世界信息社会峰会论坛聚焦普惠数字发展",
        "detail": (
            "国际电信联盟于2026年6月6日至10日举行世界信息社会峰会论坛，"
            "政府与科技业界围绕以人为本的数字发展、连接普及及新兴技术治理展开讨论。"
        ),
    },
}

TAG_BY_ROW = {
    2: "运营商财报",
    3: "友商动态",
    4: "友商动态",
    5: "运营商财报",
    6: "友商动态",
    7: "友商动态",
    8: "运营商财报",
    9: "友商动态",
    10: "人工智能",
    11: "运营商财报",
    12: "公告披露",
    13: "资本市场",
    14: "友商动态",
    15: "友商动态",
    16: "友商动态",
    17: "运营商财报",
    18: "友商动态",
    19: "国际运营商",
    20: "国际运营商",
    21: "国际运营商",
    22: "政策动向",
    23: "宏观经济",
    24: "科创政策",
    25: "社会民生",
    26: "监管政策",
    27: "数据监管",
    28: "监管政策",
    29: "国际组织",
    30: "宏观经济",
    31: "行业资讯",
    32: "投融资",
    33: "政治新闻",
    34: "宏观经济",
}

SECTION_BY_ROW = {
    22: "政治资讯",
    24: "政治资讯",
    26: "政治资讯",
    27: "政治资讯",
    28: "政治资讯",
    33: "政治资讯",
    4: "行业资讯",
    7: "行业资讯",
    10: "行业资讯",
    14: "行业资讯",
    16: "行业资讯",
    18: "行业资讯",
    24: "行业资讯",
    31: "行业资讯",
    32: "行业资讯",
    2: "行业资讯",
    3: "行业资讯",
    5: "行业资讯",
    6: "行业资讯",
    8: "行业资讯",
    9: "行业资讯",
    11: "行业资讯",
    12: "行业资讯",
    13: "行业资讯",
    15: "行业资讯",
    17: "行业资讯",
    23: "政治资讯",
    25: "社会资讯",
    30: "政治资讯",
    34: "政治资讯",
    19: "国际资讯",
    20: "国际资讯",
    21: "国际资讯",
    29: "国际资讯",
}


def clean_text(value: object, limit: int | None = None) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    text = text.replace("SOURCE:", "来源：")
    if limit and len(text) > limit:
        return text[: limit - 1].rstrip("，。；,. ") + "…"
    return text


def clean_object(value: object, limit: int = 40) -> str:
    text = clean_text(value)
    text = re.sub(r"（和\d+行可能存在重合，请Alex考虑是否合并）", "", text)
    aliases = {
        "政治资讯": "香港本地政策资讯",
        "经济资讯": "香港宏观经济资讯",
        "行业资讯": "行业资讯",
        "社会资讯": "社会资讯",
        "重点国家/地区AI与数据监管": "重点国家及地区AI与数据监管",
    }
    return clean_text(aliases.get(text, text), limit)


def load_results() -> list[dict]:
    enabled = enabled_rows()
    results: list[dict] = []
    for path in sorted(RESULTS_DIR.glob("row_*.json"), key=lambda p: int(p.stem.split("_")[1])):
        row_no = int(path.stem.split("_")[1])
        if enabled is not None and row_no not in enabled:
            continue
        results.append(json.loads(path.read_text(encoding="utf-8")))
    return results


def format_date_cn(value: datetime) -> str:
    return f"{value.year}年{value.month}月{value.day}日"


def format_date_compact(value: datetime) -> str:
    return f"{value.year}-{value.month:02d}-{value.day:02d}"


def format_event_time(value: str | None) -> str:
    if not value:
        return "-"
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(ZoneInfo("Asia/Hong_Kong"))
    except Exception:
        return value
    return f"{parsed.year}/{parsed.month}/{parsed.day} {parsed.hour:02d}:{parsed.minute:02d}:{parsed.second:02d}"


def chinese_order(value: int) -> str:
    chars = ["零", "一", "二", "三", "四", "五", "六", "七", "八", "九", "十"]
    if value <= 10:
        return chars[value]
    if value < 20:
        return "十" + (chars[value - 10] if value > 10 else "")
    tens, ones = divmod(value, 10)
    return f"{chars[tens]}十{chars[ones] if ones else ''}"


def factual_item(result: dict) -> dict | None:
    row = int(result.get("row") or 0)
    configured = FACTUAL_ITEMS.get(row)
    if not configured:
        return None

    evidence = configured["evidence"].lower()
    for record in result.get("raw_records") or []:
        if record.get("status") != 200:
            continue
        haystack = f"{record.get('title') or ''} {record.get('text_sample') or ''}".lower()
        if evidence not in haystack:
            continue
        url = clean_text(record.get("url"))
        if not url.startswith(("http://", "https://")):
            continue
        return {
            "title": configured["title"],
            "detail": configured["detail"],
            "url": url,
            "publishedAt": result.get("fetched_at_hkt") or result.get("fetched_at"),
        }
    return None


def make_sources(results: list[dict]) -> list[dict]:
    sources = []
    index = 1
    for result in results:
        fact = factual_item(result)
        if not fact:
            continue
        row = int(result.get("row") or 0)
        sources.append(
            {
                "sourceId": f"S{index}",
                "row": row,
                "section": SECTION_BY_ROW.get(row, "行业资讯"),
                "title": fact["title"],
                "url": fact["url"],
                "object": clean_object(result.get("object"), 40),
                "tag": TAG_BY_ROW.get(row, "行业动态"),
                "publishedAt": fact["publishedAt"],
            }
        )
        index += 1
    return sources


GENERIC_COMPANIES = {"行业资讯", "政治新闻", "宏观指标", "政策", "香港本地监管", "通信监管机构", "国际组织", "行业权威机构"}
INTERNATIONAL_COMPANIES = {
    "Singtel",
    "Telstra",
    "SK Telecom",
    "KT",
    "NTT Docomo",
    "KDDI",
    "SoftBank",
    "Jio",
    "Airtel",
    "Vodafone",
    "Deutsche Telekom",
    "Orange",
    "Telefonica",
    "BT/EE",
    "TIM",
    "Verizon",
    "AT&T",
    "T-Mobile US",
    "e&",
    "stc",
}


def load_curated_rows() -> list[dict]:
    try:
        payload = build_company_metrics_payload()
    except Exception:
        return []
    rows = payload.get("rows") or []
    cleaned = []
    blocked = ("[REDACTED", "Skip to main content", "Log In Sign Up", "Stock Screener", "SOURCE:")
    for row in rows:
        if not row.get("sources"):
            continue
        if row.get("metric") in {"股票代码", "披露日期", "最新披露"}:
            continue
        text = f"{row.get('value') or ''} {row.get('detail') or ''}"
        if any(token in text for token in blocked):
            continue
        if any(token in text for token in ("未公开披露", "不适用", "未单独披露该项口径")):
            continue
        cleaned.append(row)
    return cleaned


def curated_section(row: dict) -> str:
    company = str(row.get("company") or "")
    group = str(row.get("group") or "")
    category = str(row.get("metricCategory") or "")
    if company in INTERNATIONAL_COMPANIES or group == "亚太运营商":
        return "国际资讯"
    if company in {"通信监管机构", "香港本地监管", "政策", "政治新闻"}:
        return "政治资讯"
    if category == "政策宏观":
        return "政治资讯"
    if category in {"财务业绩", "客户经营"}:
        return "行业资讯"
    return "行业资讯"


def curated_subject(row: dict) -> str:
    company = clean_text(row.get("company"), 40)
    group = clean_text(row.get("group"), 40)
    if company and company not in GENERIC_COMPANIES:
        return company
    if group and group not in {"mainland", "hong-kong"} and group not in GENERIC_COMPANIES:
        return group
    return ""


def localized_weekly_value(row: dict, *, limit: int = 80) -> str:
    company = clean_text(row.get("company"), 40)
    metric = clean_text(row.get("metric"), 32)
    value = clean_text(row.get("value") or row.get("detail"), 260)
    detail = clean_text(row.get("detail"), 360)
    normalized = value.lower()
    normalized_context = f"{company} {metric} {value}".lower()
    rules = [
        (
            "166 foreign-invested enterprises approved",
            "",
            "工信部已批准166家外资企业开展增值电信业务经营试点",
        ),
        (
            "promote the development of a low-altitude economy ecosystem",
            "",
            "香港施政报告提出促进低空经济生态系统发展",
        ),
        (
            "licensing regimes for digital asset dealing and custodian services",
            "",
            "香港将制定数字资产交易及托管服务发牌制度的立法建议",
        ),
        (
            "subsidy scheme to extend fibre-based networks",
            "extend 5g coverage",
            "香港推进偏远乡村光纤网络及农村和偏远地区5G覆盖资助计划",
        ),
        (
            "satellite television services",
            "",
            "通讯事务管理局持续公布卫星电视服务监管信息",
        ),
        ("sk telecom", "ai native", "SK Telecom在MWC 2026发布AI原生战略"),
        (
            "sarashina",
            "oracle alloy",
            "SoftBank将于2026年6月推出基于自研大语言模型Sarashina的生成式AI服务",
        ),
        (
            "nvidia dsx",
            "",
            "SK Telecom计划采用NVIDIA DSX平台建设千兆瓦级AI云基础设施",
        ),
        ("softbank", "telco ai cloud", "SoftBank提出面向AI时代的电信AI云愿景"),
        ("petasus ai cloud", "", "SK Telecom推进Petasus AI云服务"),
        ("lead true ai-native transformation", "", "SK Telecom推动韩国客户和企业向AI原生转型"),
        ("5g-advanced evolution", "", "e&加快推进5G-Advanced演进"),
        ("$35/mo", "", "Verizon推出月费35美元起的FWA服务"),
        ("rising adoption of cloud services", "", "印度数据中心行业受云服务采用增长带动快速发展"),
    ]
    for first, second, replacement in rules:
        if first in normalized_context and (not second or second in normalized_context):
            return clean_text(replacement, limit)
    if len(re.findall(r"[\u4e00-\u9fff]", value)) >= 6:
        return clean_text(value, limit)
    detail_chinese = re.sub(
        r"^(片段中明确提到|片段明确提到|片段明确说明|片段提到|新闻标题明确提及)[：:'“” ]*",
        "",
        detail,
    ).strip("'“”")
    if len(re.findall(r"[\u4e00-\u9fff]", detail_chinese)) >= 8:
        return clean_text(detail_chinese, limit)
    replacements = {
        "CEO Unveils": "发布",
        "Strategy": "战略",
        "Announces": "发布",
        "Vision": "愿景",
        "Build Social Infrastructure for the AI Era": "建设AI时代社会基础设施",
        "AI Native": "AI原生",
        "Telco AI Cloud": "电信AI云",
        "Cloud": "云",
    }
    localized = value
    for raw, cn in replacements.items():
        localized = localized.replace(raw, cn)
    if company and metric and localized == value and re.search(r"[A-Za-z]{4,}", value):
        localized = f"{company}{metric}公开信息已更新"
    return clean_text(localized, limit)


def curated_title(row: dict) -> str:
    subject = curated_subject(row)
    metric = clean_text(row.get("metric"), 28)
    value = localized_weekly_value(row, limit=96)
    joiner = " " if subject and re.search(r"[A-Za-z0-9]$", subject) and re.search(r"^[A-Za-z0-9]", metric) else ""
    if metric in {"战略升级", "券商观点", "市场反应"} and subject:
        return f"{subject}{joiner}{metric}更新"
    if metric in {"收益", "EBITDA / 利润", "派息", "资本开支"}:
        return f"{subject}披露{metric}：{value}"
    if subject in {metric, ""}:
        return f"{metric}：{value}"
    return f"{subject}{joiner}{metric}：{value}"


def curated_detail(row: dict) -> str:
    subject = curated_subject(row)
    metric = clean_text(row.get("metric"), 32)
    joiner = " " if subject and re.search(r"[A-Za-z0-9]$", subject) and re.search(r"^[A-Za-z0-9]", metric) else ""
    value = localized_weekly_value(row, limit=260)
    disclosure = clean_text(row.get("disclosure"), 80)
    disclosure_date = clean_text(row.get("disclosureDate"), 40)
    value = (
        value.replace("片段中明确提到", "")
        .replace("片段明确提到", "")
        .replace("片段明确说明", "")
        .replace("片段中", "")
        .replace("片段提到", "")
        .replace("片段标题和内容明确提及", "")
        .replace("新闻标题明确提及", "")
        .replace("直接说明", "显示")
        .replace("“", "")
        .replace("”", "")
        .strip(" ：，。")
    )
    if disclosure or disclosure_date:
        prefix = f"{subject}{disclosure_date or ''}{disclosure or ''}显示，"
    elif subject:
        prefix = f"{subject}{joiner}{metric}方面，"
    else:
        prefix = f"{metric}方面，"
    sentence = value.rstrip("。；;,.，")
    return f"{prefix}{sentence}。"


def curated_row_score(row: dict, section: str) -> tuple[int, int, str]:
    metric = str(row.get("metric") or "")
    source_type = str(row.get("sourceType") or "")
    priority_by_section = {
        "政治资讯": [
            "重大政策/声明",
            "频谱拍卖",
            "频谱/牌照",
            "低空经济",
            "Web3",
            "覆盖义务",
            "卫星通信",
            "经济",
            "GDP",
        ],
        "行业资讯": [
            "战略升级",
            "收益",
            "EBITDA / 利润",
            "派息",
            "资本开支",
            "5G用户数",
            "ARPU",
            "AI",
            "5G-A",
            "企业ICT",
            "5G套餐",
            "产品规格",
            "重大合作",
        ],
        "社会资讯": ["本地生活咨询", "人口", "零售额", "失业率", "住房", "消费"],
        "国际资讯": ["AI", "云", "企业ICT", "5G-A", "FWA", "网络API"],
    }.get(section, [])
    try:
        metric_rank = priority_by_section.index(metric)
    except ValueError:
        metric_rank = len(priority_by_section)
    source_rank = 0 if source_type == "verified-performance" and section == "行业资讯" else 1
    if source_type == "public-crawl" and section in {"政治资讯", "行业资讯", "国际资讯"}:
        source_rank = 0
    if section == "行业资讯" and metric == "战略升级" and source_type == "verified-performance":
        source_rank = -1
    return (source_rank, metric_rank, f"{row.get('company') or ''}|{metric}|{row.get('value') or ''}")


def build_curated_weekly_model() -> dict | None:
    rows = load_curated_rows()
    if not rows:
        return None
    now = datetime.now(ZoneInfo("Asia/Hong_Kong"))
    start = now - timedelta(days=7)
    grouped_rows: dict[str, list[dict]] = defaultdict(list)
    for row in rows:
        section = curated_section(row)
        grouped_rows[section].append(row)

    sources = []
    source_index = 1
    toc = []
    sections = []
    global_index = 1
    for section_name in SECTION_ORDER:
        selected = []
        seen_keys = set()
        seen_events = set()
        metric_counts: dict[str, int] = defaultdict(int)
        for row in sorted(grouped_rows.get(section_name, []), key=lambda item: curated_row_score(item, section_name)):
            key = (curated_subject(row), row.get("metric"))
            event_key = localized_weekly_value(row, limit=180).casefold()
            if key in seen_keys or event_key in seen_events:
                continue
            metric = str(row.get("metric") or "")
            if section_name == "行业资讯" and metric_counts[metric] >= 4:
                continue
            seen_keys.add(key)
            seen_events.add(event_key)
            selected.append(row)
            metric_counts[metric] += 1
            if len(selected) >= WEEKLY_SECTION_LIMITS.get(section_name, WEEKLY_MAX_PER_SECTION):
                break

        items = []
        for local_index, row in enumerate(selected, start=1):
            first_source = (row.get("sources") or [{}])[0]
            source_id = f"S{source_index}"
            source_index += 1
            sources.append(
                {
                    "sourceId": source_id,
                    "row": row.get("rowRef") or "",
                    "section": section_name,
                    "title": curated_title(row),
                    "url": first_source.get("url") or "",
                    "object": curated_subject(row),
                    "tag": clean_text(row.get("metric"), 24),
                    "publishedAt": row.get("disclosureDate") or row.get("generatedAt") or "",
                }
            )
            item = {
                "row": row.get("rowRef") or "",
                "tag": clean_text(row.get("metric"), 24),
                "title": curated_title(row),
                "detail": curated_detail(row),
                "eventAt": row.get("disclosureDate") or "",
                "sourceIds": [source_id],
                "index": global_index,
                "localIndex": local_index,
            }
            items.append(item)
            toc.append(
                {
                    "index": global_index,
                    "section": section_name,
                    "tag": item["tag"],
                    "title": item["title"],
                }
            )
            global_index += 1
        tag_names = "、".join(sorted({item["tag"] for item in items})) or "无"
        if items:
            narrative = (
                f"统计区间为{format_date_compact(start)}至{format_date_compact(now)}。"
                f"本期{section_name}基于已通过质量门禁的公开信息和核验业绩字段形成，"
                f"共收录{len(items)}条事件，涉及主题：{tag_names}。"
            )
        else:
            narrative = f"统计区间为{format_date_compact(start)}至{format_date_compact(now)}。{section_name}暂无纳入条目。"
        if items:
            sections.append({"name": section_name, "narrative": narrative, "items": items})

    return {
        "company": "中国移动香港公司",
        "department": "中国移动香港公司战略部",
        "generatedDate": format_date_cn(now),
        "title": "战略内参",
        "range": {"start": format_date_compact(start), "end": format_date_compact(now)},
        "toc": toc,
        "sections": sections,
        "sources": sources,
    }


def build_weekly_model(results: list[dict]) -> dict:
    curated_model = build_curated_weekly_model()
    if curated_model:
        return curated_model

    now = datetime.now(ZoneInfo("Asia/Hong_Kong"))
    start = now - timedelta(days=7)
    sources = make_sources(results)
    source_by_row = {source["row"]: source for source in sources}

    grouped: dict[str, list[dict]] = defaultdict(list)
    for result in results:
        row = int(result.get("row") or 0)
        if result.get("status") not in {"ok", "partial"}:
            continue
        fact = factual_item(result)
        if not fact:
            continue
        section = SECTION_BY_ROW.get(row, "行业资讯")
        if len(grouped[section]) >= WEEKLY_SECTION_LIMITS.get(section, WEEKLY_MAX_PER_SECTION):
            continue
        source = source_by_row.get(row)
        grouped[section].append(
            {
                "row": row,
                "tag": TAG_BY_ROW.get(row, "行业动态"),
                "title": fact["title"],
                "detail": fact["detail"],
                "eventAt": result.get("fetched_at_hkt") or result.get("fetched_at"),
                "sourceIds": [source["sourceId"]] if source else [],
            }
        )

    toc = []
    global_index = 1
    sections = []
    for section_name in SECTION_ORDER:
        items = []
        for local_index, item in enumerate(grouped.get(section_name, []), start=1):
            item = dict(item)
            item["index"] = global_index
            item["localIndex"] = local_index
            items.append(item)
            toc.append(
                {
                    "index": global_index,
                    "section": section_name,
                    "tag": item["tag"],
                    "title": item["title"],
                }
            )
            global_index += 1
        tag_names = "、".join(sorted({item["tag"] for item in items}))
        if items:
            event_times = [format_date_compact(now)] * len(items)
            narrative = (
                f"统计区间为{format_date_compact(start)}至{format_date_compact(now)}。"
                f"本期{section_name}共收录{len(items)}条事件，涉及主题：{tag_names}，"
                f"事件时间范围为{event_times[0]}至{event_times[-1]}。"
            )
        else:
            narrative = f"统计区间为{format_date_compact(start)}至{format_date_compact(now)}。{section_name}暂无纳入条目。"
        if items:
            sections.append({"name": section_name, "narrative": narrative, "items": items})

    return {
        "company": "中国移动香港公司",
        "department": "中国移动香港公司战略部",
        "generatedDate": format_date_cn(now),
        "title": "战略内参",
        "range": {"start": format_date_compact(start), "end": format_date_compact(now)},
        "toc": toc,
        "sections": sections,
        "sources": sources,
    }


def validate_report_model(model: dict) -> None:
    errors = []
    for section in model["sections"]:
        for item in section["items"]:
            content = f"{item['title']} {item['detail']}"
            found = [phrase for phrase in FORBIDDEN_REPORT_PHRASES if phrase in content]
            if found:
                errors.append(f"{section['name']} / {item['title']}: {', '.join(found)}")
            if not item["sourceIds"]:
                errors.append(f"{section['name']} / {item['title']}: 缺少来源")
            if "…" in item["title"] or item["title"].endswith("..."):
                errors.append(f"{section['name']} / {item['title']}: 标题被截断")
            if section["name"] == "社会资讯" and item["tag"] in {
                "收益",
                "EBITDA / 利润",
                "运营商财报",
                "派息",
                "资本开支",
                "5G用户数",
                "ARPU",
            }:
                errors.append(f"{section['name']} / {item['title']}: 运营商业绩不应归入社会资讯")
    if errors:
        raise ValueError("周报内容校验失败：\n" + "\n".join(errors))


def validate_report_text(text: str) -> None:
    found = [phrase for phrase in FORBIDDEN_REPORT_PHRASES if phrase in text]
    if found:
        raise ValueError(f"周报含有禁止的技术话术：{', '.join(found)}")


def weekly_to_markdown(model: dict) -> str:
    lines = [
        model["company"],
        "",
        f"{model['department']}    {model['generatedDate']}",
        "",
        "目 录",
        "",
    ]
    for section in model["sections"]:
        lines.append(section["name"])
        if section["items"]:
            for item in section["items"]:
                lines.append(f"{item['index']}.【{item['tag']}】{item['title']}")
        else:
            lines.append("（本期暂无更新）")
        lines.append("")

    for section in model["sections"]:
        lines.append(section["name"])
        if not section["items"]:
            lines.extend(["（本期暂无更新）", ""])
            continue
        for item in section["items"]:
            lines.append(f"{chinese_order(item['index'])}、{item['title']}")
            lines.append(item["detail"])
            lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def weekly_template_markdown() -> str:
    return """中国移动香港公司

中国移动香港公司战略部    YYYY年M月D日

目 录

政治资讯
1.【标签】一句话事件标题
（本期暂无更新）

行业资讯
1.【标签】一句话事件标题
（本期暂无更新）

社会资讯
1.【标签】一句话事件标题
（本期暂无更新）

国际资讯
1.【标签】一句话事件标题
（本期暂无更新）

政治资讯
一、一句话事件标题
事件事实正文。只写公开来源可复核的事件、数据和影响。

行业资讯
二、一句话事件标题
事件事实正文。

社会资讯
三、一句话事件标题
事件事实正文。

国际资讯
四、一句话事件标题
事件事实正文。
"""


def build_template_model() -> dict:
    now = datetime.now(ZoneInfo("Asia/Hong_Kong"))
    sections = []
    toc = []
    for idx, section_name in enumerate(SECTION_ORDER, start=1):
        item = {
            "index": idx,
            "localIndex": 1,
            "tag": "标签",
            "title": "一句话事件标题",
            "detail": "事件事实正文。只写公开来源可复核的事件、数据和影响。",
            "eventAt": "YYYY/M/D HH:MM:SS",
            "sourceIds": [f"S{idx}"],
        }
        toc.append({"index": idx, "section": section_name, "tag": item["tag"], "title": item["title"]})
        sections.append(
            {
                "name": section_name,
                "narrative": (
                    f"统计区间为YYYY-MM-DD至YYYY-MM-DD。本期{section_name}共收录N条事件，"
                    "涉及主题：主题A、主题B，事件时间范围为YYYY-MM-DD至YYYY-MM-DD。"
                ),
                "items": [item],
            }
        )
    return {
        "company": "中国移动香港公司",
        "department": "中国移动香港公司战略部",
        "generatedDate": "YYYY年M月D日",
        "title": "战略内参",
        "range": {"start": "YYYY-MM-DD", "end": "YYYY-MM-DD"},
        "toc": toc,
        "sections": sections,
        "sources": [
            {
                "sourceId": f"S{idx}",
                "row": idx,
                "section": section_name,
                "title": "一句话事件标题",
                "url": "URL",
                "object": "主体",
                "tag": "标签",
                "publishedAt": "YYYY/M/D HH:MM:SS",
            }
            for idx, section_name in enumerate(SECTION_ORDER, start=1)
        ],
    }


def weekly_to_html(model: dict) -> str:
    toc_html = []
    for section in model["sections"]:
        items = "".join(
            f"<div class='weekly-toc__item'>{item['index']}.【{html.escape(item['tag'])}】{html.escape(item['title'])}</div>"
            for item in section["items"]
        )
        toc_html.append(
            f"<div class='weekly-toc__group'><div class='weekly-toc__group-title'>{html.escape(section['name'])}</div>"
            f"{items or '<div class=\"weekly-toc__empty\">（本期暂无更新）</div>'}</div>"
        )

    sections_html = []
    for section in model["sections"]:
        items_html = []
        for item in section["items"]:
            items_html.append(
                "<article class='weekly-item'>"
                f"<h4>{chinese_order(item['index'])}、{html.escape(item['title'])}</h4>"
                f"<p>{html.escape(item['detail'])}</p>"
                "</article>"
            )
        sections_html.append(
            f"<section class='weekly-section'><h3>{html.escape(section['name'])}</h3>"
            f"{''.join(items_html) if items_html else '<article class=\"weekly-item\"><p>（本期暂无更新）</p></article>'}</section>"
        )

    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <title>{html.escape(model['title'])}</title>
  <style>
    body {{ margin: 36px auto; max-width: 920px; font-family: "Microsoft YaHei", "Noto Sans CJK SC", Arial, sans-serif; color: #172033; line-height: 1.65; }}
    .cover-company {{ text-align: center; font-size: 25px; font-weight: 700; margin-bottom: 8px; }}
    .cover-dept {{ text-align: center; font-size: 16px; margin-bottom: 14px; }}
    h1 {{ text-align: center; font-size: 24px; margin: 0 0 22px; }}
    h2, h3 {{ font-size: 19px; margin: 24px 0 8px; }}
    .weekly-toc__group-title {{ font-weight: 700; margin-top: 12px; }}
    .weekly-toc__item, .weekly-toc__empty {{ margin-left: 24px; margin-top: 4px; }}
    .weekly-section {{ margin-top: 26px; }}
    .weekly-item {{ margin: 14px 0 22px; }}
    .weekly-item h4 {{ font-size: 16px; margin: 0 0 8px; }}
    .weekly-item__tag {{ font-weight: 700; margin: 0 0 4px; }}
    a {{ color: #1d4ed8; }}
  </style>
</head>
<body>
  <div class="cover-company">{html.escape(model['company'])}</div>
  <div class="cover-dept">{html.escape(model['department'])}    {html.escape(model['generatedDate'])}</div>
  <h1>{html.escape(model['title'])}</h1>
  <section class="weekly-section weekly-section--toc"><h2>目 录</h2>{''.join(toc_html)}</section>
  {''.join(sections_html)}
</body>
</html>
"""


def set_cell_shading(cell, fill: str) -> None:
    tc_pr = cell._tc.get_or_add_tcPr()
    shd = OxmlElement("w:shd")
    shd.set(qn("w:fill"), fill)
    tc_pr.append(shd)


def set_cell_text(cell, text: str, bold: bool = False) -> None:
    cell.vertical_alignment = WD_CELL_VERTICAL_ALIGNMENT.CENTER
    para = cell.paragraphs[0]
    para.alignment = WD_ALIGN_PARAGRAPH.LEFT
    run = para.add_run(clean_text(text))
    run.font.name = "Microsoft YaHei"
    run._element.rPr.rFonts.set(qn("w:eastAsia"), "Microsoft YaHei")
    run.font.size = Pt(10)
    run.bold = bold


def add_p(doc: Document, text: str, *, size: int = 11, bold: bool = False, align=None, before=0, after=6, indent=0):
    para = doc.add_paragraph()
    para.paragraph_format.space_before = Pt(before)
    para.paragraph_format.space_after = Pt(after)
    if indent:
        para.paragraph_format.left_indent = Pt(indent / 20)
    if align is not None:
        para.alignment = align
    run = para.add_run(text)
    run.font.name = "Microsoft YaHei"
    run._element.rPr.rFonts.set(qn("w:eastAsia"), "Microsoft YaHei")
    run.font.size = Pt(size)
    run.bold = bold
    return para


def weekly_to_docx(model: dict, path: Path) -> None:
    doc = render_into_source_template(model)
    doc.save(path)


def has_drawing(paragraph) -> bool:
    return bool(
        paragraph._p.xpath(".//*[local-name()='drawing']")
        or paragraph._p.xpath(".//*[local-name()='pict']")
    )


def has_page_break(paragraph) -> bool:
    return bool(paragraph._p.xpath(".//w:br[@w:type='page']"))


def clear_paragraph(paragraph) -> None:
    for child in list(paragraph._p):
        if child.tag == qn("w:pPr"):
            continue
        paragraph._p.remove(child)


def paragraph_format_snapshot(paragraph):
    p_pr = paragraph._p.pPr
    r_pr = paragraph.runs[0]._r.rPr if paragraph.runs and paragraph.runs[0]._r.rPr is not None else None
    return deepcopy(p_pr) if p_pr is not None else None, deepcopy(r_pr) if r_pr is not None else None


def apply_snapshot(paragraph, snapshot) -> None:
    p_pr, _ = snapshot
    existing_p_pr = paragraph._p.pPr
    if existing_p_pr is not None:
        paragraph._p.remove(existing_p_pr)
    if p_pr is not None:
        paragraph._p.insert(0, deepcopy(p_pr))


def set_template_paragraph(paragraph, text: str, snapshot) -> None:
    clear_paragraph(paragraph)
    apply_snapshot(paragraph, snapshot)
    if text:
        run = paragraph.add_run(text)
        _, r_pr = snapshot
        if r_pr is not None:
            existing = run._r.rPr
            if existing is not None:
                run._r.remove(existing)
            run._r.insert(0, deepcopy(r_pr))


def find_paragraph_index(doc: Document, text: str | tuple[str, ...], partial: bool = False) -> int:
    if isinstance(text, str):
        text = (text,)
    for index, paragraph in enumerate(doc.paragraphs):
        p_text = paragraph.text.strip()
        for t in text:
            if (not partial and p_text == t) or (partial and p_text.startswith(t)):
                return index
    raise ValueError(f"Template paragraph not found: {text}")


def template_slots(doc: Document, start: int, end: int | None = None) -> list:
    paragraphs = doc.paragraphs[start:end]
    return [
        paragraph
        for paragraph in paragraphs
        if not has_drawing(paragraph) and not has_page_break(paragraph)
    ]


def add_or_reuse(slot_iter, doc: Document, text: str, snapshot):
    try:
        paragraph = next(slot_iter)
    except StopIteration:
        paragraph = doc.add_paragraph()
    set_template_paragraph(paragraph, text, snapshot)
    return paragraph


def remove_paragraph(paragraph) -> None:
    parent = paragraph._element.getparent()
    if parent is not None:
        parent.remove(paragraph._element)


def render_into_source_template(model: dict) -> Document:
    if not SOURCE_WORD_TEMPLATE.exists():
        raise FileNotFoundError(f"Word template not found: {SOURCE_WORD_TEMPLATE}")

    doc = Document(str(SOURCE_WORD_TEMPLATE))
    company_idx = find_paragraph_index(doc, "中国移动香港公司")
    dept_idx = find_paragraph_index(doc, "中国移动香港公司战略部", partial=True)
    toc_idx = find_paragraph_index(doc, "目 录")
    body_idx = find_paragraph_index(doc, "政治资讯")
    body_idx = next(
        index
        for index in range(body_idx + 1, len(doc.paragraphs))
        if doc.paragraphs[index].text.strip() == "政治资讯"
    )
    body_anchor_element = doc.paragraphs[body_idx]._p

    snapshots = {
        "company": paragraph_format_snapshot(doc.paragraphs[company_idx]),
        "dept": paragraph_format_snapshot(doc.paragraphs[dept_idx]),
        "toc_title": paragraph_format_snapshot(doc.paragraphs[toc_idx]),
        "toc_section": paragraph_format_snapshot(doc.paragraphs[find_paragraph_index(doc, "行业资讯")]),
        "toc_item": paragraph_format_snapshot(doc.paragraphs[find_paragraph_index(doc, ("1.【香港施政治理】李家超：今年内完成首份“香港五年规划”，全面对接国家“十五五”规划", "1.【标签】一句话事件标题"))]),
        "body_section": paragraph_format_snapshot(doc.paragraphs[body_idx]),
        "body_tag": paragraph_format_snapshot(doc.paragraphs[body_idx + 1]),
        "body_title": paragraph_format_snapshot(doc.paragraphs[body_idx + 2]),
        "body_text": paragraph_format_snapshot(doc.paragraphs[body_idx + 3]),
    }

    for paragraph in doc.paragraphs:
        if not has_drawing(paragraph) and not has_page_break(paragraph):
            clear_paragraph(paragraph)

    set_template_paragraph(doc.paragraphs[company_idx], model["company"], snapshots["company"])
    set_template_paragraph(
        doc.paragraphs[dept_idx],
        f"{model['department']}                                                    {model['generatedDate']}",
        snapshots["dept"],
    )
    toc_paragraph = doc.paragraphs[toc_idx]
    set_template_paragraph(toc_paragraph, "目 录", snapshots["toc_title"])

    toc_slot_list = template_slots(doc, toc_idx + 2, body_idx)
    toc_slots = iter(toc_slot_list)
    for section_model in model["sections"]:
        section_paragraph = add_or_reuse(toc_slots, doc, section_model["name"], snapshots["toc_section"])
        section_paragraph.paragraph_format.space_before = Pt(6)
        section_paragraph.paragraph_format.space_after = Pt(2)
        section_paragraph.paragraph_format.line_spacing = 1.0
        for item in section_model["items"]:
            item_paragraph = add_or_reuse(
                toc_slots,
                doc,
                f"{item['index']}.【{item['tag']}】{item['title']}",
                snapshots["toc_item"],
            )
            item_paragraph.paragraph_format.space_before = Pt(0)
            item_paragraph.paragraph_format.space_after = Pt(1)
            item_paragraph.paragraph_format.line_spacing = 1.05
        spacer = add_or_reuse(toc_slots, doc, "", snapshots["body_text"])
        spacer.paragraph_format.space_before = Pt(0)
        spacer.paragraph_format.space_after = Pt(0)
        spacer.paragraph_format.line_spacing = 1.0
    for paragraph in list(toc_slots):
        remove_paragraph(paragraph)

    # The source template contains a fixed red separator inside the original
    # short table of contents. It overlaps text once the TOC grows, so remove
    # drawings only from the TOC range while preserving the cover artwork.
    for paragraph in list(doc.paragraphs[toc_idx + 1 : body_idx]):
        if has_drawing(paragraph):
            remove_paragraph(paragraph)

    body_idx = next(
        index
        for index in range(toc_idx + 1, len(doc.paragraphs))
        if doc.paragraphs[index]._p is body_anchor_element
    )
    body_slots = iter(template_slots(doc, body_idx, None))
    for section_model in model["sections"]:
        add_or_reuse(body_slots, doc, section_model["name"], snapshots["body_section"])
        for item in section_model["items"]:
            add_or_reuse(body_slots, doc, f"{chinese_order(item['index'])}、{item['title']}", snapshots["body_title"])
            add_or_reuse(body_slots, doc, item["detail"], snapshots["body_text"])
            add_or_reuse(body_slots, doc, "", snapshots["body_text"])

    # Removing text is not enough here: unused template paragraphs retain
    # spacing and pagination properties and can create completely blank pages.
    for paragraph in list(body_slots):
        remove_paragraph(paragraph)
    while doc.paragraphs and not doc.paragraphs[-1].text.strip() and not has_drawing(doc.paragraphs[-1]):
        remove_paragraph(doc.paragraphs[-1])
    return doc


def main() -> None:
    print("============== 开始生成战略内参周报 ==============")
    results = load_results()
    print(f"已加载 {len(results)} 条底层爬取数据。")
    model = build_weekly_model(results)
    validate_report_model(model)
    
    print("\n--- 报告内容统计 ---")
    for section in model["sections"]:
        print(f"[{section['name']}]: 收录 {len(section['items'])} 条事件")
        
    print("\n--- 正在渲染并导出各格式文件 ---")
    markdown = weekly_to_markdown(model)
    validate_report_text(markdown)
    WEEKLY_MD.write_text(markdown, encoding="utf-8")
    TEMPLATE_MD.write_text(weekly_template_markdown(), encoding="utf-8")
    html_text = weekly_to_html(model)
    WEEKLY_HTML.write_text(html_text, encoding="utf-8")
    AGENT_MD_ALIAS.write_text(markdown, encoding="utf-8")
    AGENT_HTML_ALIAS.write_text(html_text, encoding="utf-8")
    weekly_to_docx(model, WEEKLY_DOCX)
    # SOURCE_WORD_TEMPLATE is an input asset. Never overwrite the repository
    # fallback template while generating a report.
    
    print("\n[生成成功] 最终输出文件：")
    print(" ->", WEEKLY_MD)
    print(" ->", WEEKLY_HTML)
    print(" ->", WEEKLY_DOCX)
    print(" ->", TEMPLATE_MD)
    
    # Archiving logic
    import shutil
    import datetime
    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    archive_dir = ROOT / "archives" / timestamp
    archive_dir.mkdir(parents=True, exist_ok=True)
    
    shutil.copy2(WEEKLY_MD, archive_dir / WEEKLY_MD.name)
    shutil.copy2(WEEKLY_HTML, archive_dir / WEEKLY_HTML.name)
    shutil.copy2(WEEKLY_DOCX, archive_dir / WEEKLY_DOCX.name)
    
    print(f"\n[归档成功] 已自动备份此次报告至: archives/{timestamp}/")
    print("==================================================")


if __name__ == "__main__":
    main()
