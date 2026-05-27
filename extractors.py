from __future__ import annotations

import re
from typing import Dict, Iterable, List, Tuple


def _common_financial_fields() -> Dict[str, List[str]]:
    return {
        "运营收入/总收益": ["revenue", "turnover", "total revenue", "operating revenue", "收益", "收入", "總收益"],
        "服务收入": ["service revenue", "customer service revenue", "services revenue", "telecommunications services", "服務收入", "服务收入"],
        "EBITDA": ["EBITDA"],
        "净利润": ["net profit", "profit attributable", "净利润", "純利", "溢利"],
        "客户数/用户数": ["customers", "subscribers", "customer base", "users", "user base", "用户", "客戶"],
        "5G用户数": ["5G customers", "5G subscribers", "5G customer base", "5G plan users", "5G用户", "5G客戶", "5G"],
        "ARPU": ["ARPU"],
        "资本开支": ["capital expenditure", "capex", "capital expenditures", "资本开支", "資本開支"],
    }


FIELD_PATTERNS: Dict[int, Dict[str, List[str]]] = {
    2: {
        **_common_financial_fields(),
        "宽频线数/家宽用户数": ["broadband", "fixed-line", "home broadband", "宽频", "寬頻"],
    },
    3: {
        "5G套餐": ["5G service plan", "5G plan", "5G套餐", "5G"],
        "产品规格": ["data", "local data", "network", "specification"],
        "合约期": ["contract", "commitment", "合约", "合約"],
        "资费": ["HK$", "$", "monthly fee", "tariff", "price", "charge"],
        "增值服务": ["value-added", "VAS", "add-on", "增值"],
        "家宽套餐": ["home broadband", "broadband", "fibre-to-the-home", "FTTH", "家宽", "寬頻"],
        "企业专线": ["enterprise", "business", "leased line", "HKT Enterprise", "企業"],
        "漫游": ["roaming", "漫游", "漫遊"],
        "促销折扣": ["promotion", "offer", "discount", "优惠", "優惠"],
    },
    4: {
        "战略合作": ["partnership", "collaboration", "strategic", "合作"],
        "中标": ["award", "contract", "tender", "中标", "中標"],
        "投资并购": ["investment", "invested", "acquisition", "M&A", "merger", "投资", "收购"],
        "5G-A": ["5G-A", "5.5G", "5G Advanced", "5G-Advanced", "5GAdvanced"],
        "网络API": ["network API", "Open API", "APIs", "API", "application programming interface"],
        "边缘计算": ["edge computing", "edge"],
        "数据中心": ["data centre", "data center", "data centre regions", "DC"],
        "高管人事": ["appointment", "director", "management", "resignation", "高管", "董事"],
    },
    5: _common_financial_fields(),
    6: {
        "5G套餐": ["5G", "plan"],
        "SoSIM/Mo+": ["SoSIM", "Mo+"],
        "企业方案": ["business", "enterprise", "3Business"],
        "漫游": ["roaming", "World Plan"],
        "促销折扣": ["promotion", "offer", "$", "HK$"],
    },
    7: {
        "战略合作": ["partnership", "collaboration"],
        "中标": ["award", "contract"],
        "5G-A": ["5G-A", "5.5G", "5G Advanced", "5G-Advanced", "5GAdvanced", "5G"],
        "企业ICT": ["ICT", "enterprise", "business solutions", "business"],
        "IoT": ["IoT", "Internet of Things", "smart"],
        "区域动作": ["Hong Kong", "Macau", "Greater Bay", "regional"],
    },
    8: _common_financial_fields(),
    9: {
        "5G套餐": ["5G", "plan"],
        "家宽": ["Home 5G Broadband", "home broadband"],
        "企业方案": ["business", "enterprise"],
        "漫游": ["roaming"],
        "促销折扣": ["offer", "promotion", "HK$", "$"],
    },
    10: {
        "战略合作": ["partnership", "collaboration", "cooperation", "teamed up", "selected", "vendor", "provider"],
        "中标": ["award", "contract", "won"],
        "5G-A": ["5G-A", "5.5G", "5G Advanced", "5G-Advanced", "5GAdvanced"],
        "家宽布局": ["home broadband", "broadband"],
        "区域动作": ["Greater Bay", "Hong Kong", "regional"],
    },
    11: {
        "总收入": ["total revenue", "revenue"],
        "板块收入分拆": ["enterprise", "residential", "mobile", "business solutions"],
        "EBITDA": ["EBITDA"],
        "净利润": ["net profit", "profit"],
        "融资成本": ["finance costs", "financing cost"],
        "资本开支": ["capital expenditure", "capex"],
        "商誉": ["goodwill", "intangible assets", "impairment", "goodwill on consolidation"],
        "资产负债率": ["debt", "gearing", "leverage"],
        "用户数": ["subscribers", "customers", "subscriptions"],
        "商业楼宇覆盖率": ["commercial buildings", "coverage"],
    },
    12: {
        "业绩报告公告": ["annual results", "interim results", "results"],
        "董事会": ["board"],
        "股东大会": ["general meeting", "AGM", "annual general meeting", "shareholders", "shareholder meeting"],
        "派息": ["dividend"],
        "持续性关联交易": ["connected transaction", "continuing connected", "continuing connected transactions", "related party", "connected"],
    },
    13: {
        "股价异动": ["stock quote", "quote", "price", "change", "volume", "获取实时报价"],
    },
    14: {
        "宽带套餐": ["broadband", "home broadband", "plan"],
        "企业ICT": ["ICT", "enterprise"],
        "云/安全": ["cloud", "security"],
        "融合产品": ["bundle", "converged", "integrated", "one-stop", "solution"],
        "重大合作": ["partnership", "collaboration"],
        "区域布局": ["coverage", "region", "Greater Bay"],
    },
    15: {
        "家宽用户数": ["broadband", "residential"],
        "网络覆盖": ["network", "coverage"],
        "企业通信": ["enterprise", "business"],
        "跨境链路": ["cross-border", "connectivity"],
        "数据中心": ["data centre", "data center", "data centre regions"],
        "云网产品": ["cloud", "network"],
    },
    16: {
        "海缆/跨境链路": ["subsea", "cross-border", "connectivity"],
        "数据中心": ["data centre", "data center", "data centre regions"],
        "企业网络": ["enterprise", "network"],
        "合作项目": ["partnership", "collaboration"],
    },
    17: {
        **_common_financial_fields(),
        "宽频线数/家宽用户数": ["broadband", "residential", "subscribers", "customers"],
        "网络覆盖": ["network coverage", "coverage", "optical", "5G networks"],
        "ARPU": ["ARPU", "average revenue per user", "average revenue"],
    },
    18: {
        "宽带套餐": ["broadband", "plan", "寬頻"],
        "电讯业务战略合作": ["telecom", "telecommunications", "partnership", "collaboration", "strategic", "service", "network leasing", "network construction", "mobile agency"],
    },
    19: {
        "AI": ["AI", "artificial intelligence"],
        "5G-A": ["5G-A", "5.5G", "5G Advanced", "5G-Advanced", "5GAdvanced"],
        "云": ["cloud", "cloud computing", "digital"],
        "企业ICT": ["enterprise", "ICT"],
        "Capex方向": ["capex", "capital expenditure", "investment"],
        "Singtel": ["Singtel"],
        "Telstra": ["Telstra"],
        "SK Telecom": ["SK Telecom", "SKT"],
        "KT": ["KT Corp", "KT"],
        "NTT Docomo": ["NTT DOCOMO", "DOCOMO"],
        "KDDI": ["KDDI"],
        "SoftBank": ["SoftBank"],
        "Jio": ["Jio", "Reliance Jio"],
        "Airtel": ["Airtel"],
    },
    20: {
        "网络API": ["network API", "Open API", "APIs", "API", "application programming interface"],
        "Open RAN": ["Open RAN", "RAN"],
        "边缘计算": ["edge"],
        "FWA": ["FWA", "fixed wireless", "fixed wireless access", "home internet"],
        "AI网络": ["AI", "network"],
        "Vodafone": ["Vodafone"],
        "Deutsche Telekom": ["Deutsche Telekom", "Telekom"],
        "Orange": ["Orange"],
        "Telefonica": ["Telefónica", "Telefonica"],
        "BT/EE": ["BT", "EE"],
        "TIM": ["TIM"],
        "Verizon": ["Verizon"],
        "AT&T": ["AT&T"],
        "T-Mobile US": ["T-Mobile"],
    },
    21: {
        "AI": ["AI", "artificial intelligence"],
        "算力网络": ["computing", "intelligent computing", "compute", "AI"],
        "云": ["cloud", "cloud computing", "digital"],
        "DICT": ["DICT", "digital", "ICT"],
        "5G-A": ["5G-A", "5.5G", "5G Advanced", "5G-Advanced", "5GAdvanced"],
        "资本开支": ["capex", "capital expenditure", "investment"],
        "e&": ["e&", "Etisalat"],
        "stc": ["stc"],
        "中国移动": ["China Mobile"],
        "中国电信": ["China Telecom"],
        "中国联通": ["China Unicom"],
    },
    22: {
        "施政报告": ["policy address", "Chief Executive"],
        "战略规划": ["strategy", "development plan"],
        "区域发展": ["regional", "Greater Bay"],
        "重大投资": ["investment", "invest", "fund"],
    },
    23: {
        "人口": ["population"],
        "零售额": ["retail", "retail sales"],
        "PMI": ["PMI", "Purchasing Managers"],
        "失业率": ["unemployment"],
    },
    24: {
        "跨境贸易": ["cross-border", "trade", "cross-boundary"],
        "科技创投": ["startup", "venture", "innovation"],
        "人工智能": ["AI", "artificial intelligence"],
        "低空经济": ["low-altitude", "low altitude", "low-altitude economy", "drone"],
        "Web3": ["Web3", "web 3", "virtual asset", "digital asset", "blockchain"],
    },
    25: {
        "本地生活咨询": ["housing", "public rental housing", "waiting time", "living"],
    },
    26: {
        "OFCA政策": ["OFCA", "Communications Authority", "policy"],
        "频谱/牌照": ["spectrum", "licence", "license"],
        "服务质量": ["quality of service", "QoS", "service quality", "quality"],
        "网络安全": ["network security", "cybersecurity", "security"],
        "PCPD/AI指引": ["PCPD", "AI", "guidance"],
        "数据跨境": ["cross-border data", "data transfer", "data flow"],
    },
    27: {
        "EU AI Act": ["AI Act"],
        "EU Data Act": ["Data Act", "European Data Act", "data economy"],
        "GDPR/DSA": ["GDPR", "DSA", "General Data Protection Regulation", "Digital Services Act"],
        "新加坡AI治理": ["AI governance", "IMDA", "PDPC"],
        "隐私法规": ["privacy", "data protection"],
    },
    28: {
        "频谱拍卖": ["spectrum", "auction"],
        "5G/6G规划": ["5G", "6G"],
        "网络共享": ["network sharing", "shared network", "sharing"],
        "覆盖义务": ["coverage obligation", "coverage", "obligation"],
        "网络安全": ["cybersecurity", "network security"],
        "卫星通信": ["satellite", "satellite communications", "space"],
        "携号转网/漫游": ["number portability", "mobile number portability", "roaming", "portability"],
    },
    29: {
        "ITU数字发展": ["ITU", "digital development"],
        "宽带指标": ["broadband", "fixed broadband", "connectivity"],
        "OECD数字经济": ["OECD", "digital economy", "AI"],
        "World Bank/IMF宏观": ["World Bank", "GDP", "indicator"],
    },
    30: {
        "访港旅客": ["visitor", "tourism"],
        "人口": ["population"],
        "零售": ["retail", "retail sales"],
        "失业率": ["unemployment", "labour force"],
        "CPI": ["CPI", "Consumer Price Index", "consumer price"],
        "利率": ["interest rate", "HIBOR", "interest"],
        "汇率": ["exchange rate", "exchange"],
    },
    31: {
        "技术动态": ["technology", "AI", "5G", "network"],
        "市场趋势": ["market", "trend"],
        "企业重大合作": ["partnership", "collaboration", "deal", "agreement"],
        "前沿产品": ["launch", "product"],
    },
    32: {
        "收购": ["acquisition", "merger", "M&A"],
        "融资": ["financing", "funding", "investment"],
        "合资": ["joint venture", "JV"],
        "股权交易": ["equity", "transaction", "share", "stake", "shares", "ownership"],
    },
    33: {
        "地缘政治": ["geopolitical", "foreign ministry", "MFA"],
        "经济": ["economy", "economic"],
        "重大政策/声明": ["policy", "statement"],
    },
    34: {
        "GDP": ["GDP"],
        "进出口": ["imports", "exports", "trade"],
        "失业率": ["unemployment"],
        "旅游业数据": ["tourism", "visitor"],
    },
}


def normalize_text(text: str) -> str:
    text = re.sub(r"\s+", " ", text or "").strip()
    return text


def snippet_around(text: str, pattern: str, radius: int = 180) -> str:
    lower = text.lower()
    idx = lower.find(pattern.lower())
    if idx < 0:
        return ""
    start = max(0, idx - radius)
    end = min(len(text), idx + len(pattern) + radius)
    return normalize_text(text[start:end])


def find_field_snippets(row: int, text: str) -> Tuple[Dict[str, List[str]], List[str]]:
    text = normalize_text(text)
    spec = FIELD_PATTERNS.get(row, {})
    extracted: Dict[str, List[str]] = {}
    missing: List[str] = []
    for field, patterns in spec.items():
        snippets: List[str] = []
        for pattern in patterns:
            snip = snippet_around(text, pattern)
            if snip and snip not in snippets:
                snippets.append(snip)
            if len(snippets) >= 2:
                break
        if snippets:
            extracted[field] = snippets
        else:
            missing.append(field)
    return extracted, missing


def compact_extracted(extracted: Dict[str, List[str]], max_chars: int = 4200) -> Dict[str, str]:
    compact: Dict[str, str] = {}
    used = 0
    for field, snippets in extracted.items():
        value = " | ".join(snippets)
        value = value[:220]
        if used + len(field) + len(value) > max_chars:
            break
        compact[field] = value
        used += len(field) + len(value)
    return compact


def row_fields(row: int) -> Iterable[str]:
    return FIELD_PATTERNS.get(row, {}).keys()
