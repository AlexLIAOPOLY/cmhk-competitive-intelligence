from __future__ import annotations

import csv
import hashlib
import json
import os
import re
import shutil
import tempfile
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any

import httpx
from bs4 import BeautifulSoup


ROOT = Path(__file__).resolve().parents[1]
BUILD_DATE = os.environ.get("CMHK_QUARTERLY_METRICS_BUILD_DATE") or date.today().isoformat()
DATASET_ID = f"quarterly_competitor_metrics_{BUILD_DATE}"
OUT_ROOT = ROOT / "agent_knowledge" / DATASET_ID
SOURCE_CACHE_ROOT = ROOT / "data" / "quarterly_sources" / "http_cache"
STOCKANALYSIS_SNAPSHOT = ROOT / "data" / "quarterly_sources" / f"stockanalysis_carriers_{BUILD_DATE}.json"


@dataclass(frozen=True)
class SubjectSpec:
    subject: str
    legal_name: str
    category: str
    ticker: str | None = None
    stockanalysis_kind: str | None = None
    stockanalysis_slug: str | None = None
    disclosure_note: str = ""


CORE_SUBJECTS = [
    SubjectSpec("中国移动", "China Mobile Limited", "carrier", "0941.HK", "hkg", "0941"),
    SubjectSpec("中国电信", "China Telecom Corporation Limited", "carrier", "0728.HK", "hkg", "0728"),
    SubjectSpec("中国联通", "China Unicom (Hong Kong) Limited", "carrier", "0762.HK", "hkg", "0762"),
    SubjectSpec("中国铁塔", "China Tower Corporation Limited", "carrier", "0788.HK", "hkg", "0788"),
    SubjectSpec("HKT / csl / 1O1O", "HKT Trust and HKT Limited", "carrier", "6823.HK", "hkg", "6823"),
    SubjectSpec("3HK / Hutchison", "Hutchison Telecommunications Hong Kong Holdings Limited", "carrier", "0215.HK", "hkg", "0215"),
    SubjectSpec("SmarTone", "SmarTone Telecommunications Holdings Limited", "carrier", "0315.HK", "hkg", "0315"),
    SubjectSpec("HKBN", "HKBN Ltd.", "carrier", "1310.HK", "hkg", "1310"),
    SubjectSpec(
        "HGC",
        "HGC Global Communications Limited",
        "carrier",
        None,
        None,
        None,
        "非上市主体，未发现稳定公开季度/半年度完整财务表；本包只记录来源缺口，不估算。",
    ),
    SubjectSpec("i-CABLE", "i-CABLE Communications Limited", "carrier", "1097.HK", "hkg", "1097"),
]

CLOUD_SUBJECTS = [
    SubjectSpec("AWS", "Amazon Web Services segment of Amazon.com, Inc.", "cloud", "AMZN", "stocks", "amzn"),
    SubjectSpec("Microsoft Azure / Intelligent Cloud", "Microsoft Corporation", "cloud", "MSFT", "stocks", "msft", "Azure 未单独披露收入；需使用 Intelligent Cloud/Server products and cloud services 代理口径。"),
    SubjectSpec("Google Cloud", "Alphabet Inc.", "cloud", "GOOGL/GOOG", "stocks", "goog"),
    SubjectSpec("Alibaba Cloud", "Alibaba Group Holding Limited", "cloud", "BABA / 9988.HK", "stocks", "baba"),
    SubjectSpec("Tencent Cloud / Tencent FBS proxy", "Tencent Holdings Limited", "cloud", "0700.HK", "hkg", "0700", "腾讯云未单独披露收入；只能使用 FinTech and Business Services 代理口径并明确说明。"),
    SubjectSpec("Huawei Cloud / Cloud Computing", "Huawei Investment & Holding Co., Ltd.", "cloud", None, None, None, "非上市公司；季度云分部收入需从官方季报/半年报/年报手工抽取，不能用估算值。"),
    SubjectSpec("Oracle Cloud", "Oracle Corporation", "cloud", "ORCL", "stocks", "orcl", "Oracle 可披露 Cloud services 产品线收入，但分部利润为 Cloud and license 口径。"),
]

CLOUD_QUARTERLY_SOURCE_HINTS: dict[str, list[dict[str, str]]] = {
    "AWS": [
        {
            "label": "Amazon quarterly results and filings",
            "url": "https://ir.aboutamazon.com/quarterly-results/default.aspx",
            "type": "official_quarterly_results_index",
        }
    ],
    "Microsoft Azure / Intelligent Cloud": [
        {
            "label": "Microsoft quarterly earnings",
            "url": "https://www.microsoft.com/en-us/Investor/earnings",
            "type": "official_quarterly_results_index",
        }
    ],
    "Google Cloud": [
        {
            "label": "Alphabet quarterly earnings",
            "url": "https://abc.xyz/investor/",
            "type": "official_quarterly_results_index",
        }
    ],
    "Alibaba Cloud": [
        {
            "label": "Alibaba quarterly results",
            "url": "https://www.alibabagroup.com/en-US/ir-financial-reports-quarterly-results",
            "type": "official_quarterly_results_index",
        }
    ],
    "Tencent Cloud / Tencent FBS proxy": [
        {
            "label": "Tencent financial reports",
            "url": "https://www.tencent.com/en-us/investors/financial-reports.html",
            "type": "official_quarterly_results_index",
        }
    ],
    "Huawei Cloud / Cloud Computing": [
        {
            "label": "Huawei annual and interim reports",
            "url": "https://www.huawei.com/en/annual-report",
            "type": "official_reports_index",
        }
    ],
    "Oracle Cloud": [
        {
            "label": "Oracle quarterly results",
            "url": "https://investor.oracle.com/financials/default.aspx",
            "type": "official_quarterly_results_index",
        }
    ],
}

AWS_QUARTERLY_RESULTS_INDEX_URL = "https://ir.aboutamazon.com/quarterly-results/default.aspx"
AWS_Q1_2024_RESULTS_URL = "https://s2.q4cdn.com/299287126/files/doc_financials/2024/q1/AMZN-Q1-2024-Earnings-Release.pdf"
AWS_Q2_2024_RESULTS_URL = "https://s2.q4cdn.com/299287126/files/doc_financials/2024/q2/AMZN-Q2-2024-Earnings-Release.pdf"
AWS_Q3_2024_RESULTS_URL = "https://s2.q4cdn.com/299287126/files/doc_financials/2024/q3/AMZN-Q3-2024-Earnings-Release.pdf"
AWS_Q4_2024_RESULTS_URL = "https://s2.q4cdn.com/299287126/files/doc_financials/2024/q4/AMZN-Q4-2024-Earnings-Release.pdf"
AWS_Q3_2023_RESULTS_URL = "https://s2.q4cdn.com/299287126/files/doc_financials/2023/q3/AMZN-Q3-2023-Earnings-Release.pdf"
AWS_Q4_2023_RESULTS_URL = "https://s2.q4cdn.com/299287126/files/doc_financials/2023/q4/AMZN-Q4-2023-Earnings-Release.pdf"
AWS_Q1_2025_RESULTS_URL = "https://s2.q4cdn.com/299287126/files/doc_financials/2025/q1/AMZN-Q1-2025-Earnings-Release.pdf"
AWS_Q2_2025_RESULTS_URL = "https://s2.q4cdn.com/299287126/files/doc_financials/2025/q2/AMZN-Q2-2025-Earnings-Release.pdf"
AWS_Q3_2025_RESULTS_URL = "https://s2.q4cdn.com/299287126/files/doc_financials/2025/q3/AMZN-Q3-2025-Earnings-Release.pdf"
AWS_Q1_2021_10Q_URL = "https://www.sec.gov/Archives/edgar/data/1018724/000101872421000010/amzn-20210331.htm"
AWS_Q2_2021_10Q_URL = "https://www.sec.gov/Archives/edgar/data/1018724/000101872421000020/amzn-20210630.htm"
AWS_Q3_2021_10Q_URL = "https://www.sec.gov/Archives/edgar/data/1018724/000101872421000028/amzn-20210930.htm"
AWS_2021_10K_URL = "https://www.sec.gov/Archives/edgar/data/1018724/000101872422000005/amzn-20211231.htm"
AWS_Q1_2020_10Q_URL = "https://www.sec.gov/Archives/edgar/data/1018724/000101872420000010/amzn-20200331x10q.htm"
AWS_Q2_2020_10Q_URL = "https://www.sec.gov/Archives/edgar/data/1018724/000101872420000021/amzn-20200630.htm"
AWS_Q3_2020_10Q_URL = "https://www.sec.gov/Archives/edgar/data/1018724/000101872420000030/amzn-20200930.htm"
AWS_2020_10K_URL = "https://www.sec.gov/Archives/edgar/data/1018724/000101872421000004/amzn-20201231.htm"
AWS_Q1_2019_10Q_URL = "https://www.sec.gov/Archives/edgar/data/1018724/000101872419000043/amzn-2019331x10q.htm"
AWS_Q2_2019_10Q_URL = "https://www.sec.gov/Archives/edgar/data/1018724/000101872419000071/amzn-2019630x10q.htm"
AWS_Q3_2019_10Q_URL = "https://www.sec.gov/Archives/edgar/data/1018724/000101872419000089/amzn-2019930x10q.htm"
AWS_2019_10K_URL = "https://www.sec.gov/Archives/edgar/data/1018724/000101872420000004/amzn-20191231x10k.htm"
AWS_Q1_2018_10Q_URL = "https://www.sec.gov/Archives/edgar/data/1018724/000101872418000072/amzn-20180331x10q.htm"
AWS_Q2_2018_10Q_URL = "https://www.sec.gov/Archives/edgar/data/1018724/000101872418000108/amzn-20180630x10q.htm"
AWS_Q3_2018_10Q_URL = "https://www.sec.gov/Archives/edgar/data/1018724/000101872418000159/amzn-20180930x10q.htm"
AWS_2018_10K_URL = "https://www.sec.gov/Archives/edgar/data/1018724/000101872419000004/amzn-20181231x10k.htm"
AWS_Q1_2017_10Q_URL = "https://www.sec.gov/Archives/edgar/data/1018724/000101872417000051/amzn-20170331x10q.htm"
AWS_Q2_2017_10Q_URL = "https://www.sec.gov/Archives/edgar/data/1018724/000101872417000100/amzn-20170630x10q.htm"
AWS_Q3_2017_10Q_URL = "https://www.sec.gov/Archives/edgar/data/1018724/000101872417000135/amzn-20170930x10q.htm"
AWS_2017_10K_URL = "https://www.sec.gov/Archives/edgar/data/1018724/000101872418000005/amzn-20171231x10k.htm"
AWS_Q1_2016_10Q_URL = "https://www.sec.gov/Archives/edgar/data/1018724/000101872416000227/amzn-20160331x10q.htm"
AWS_Q2_2016_10Q_URL = "https://www.sec.gov/Archives/edgar/data/1018724/000101872416000286/amzn-20160630x10q.htm"
AWS_Q3_2016_10Q_URL = "https://www.sec.gov/Archives/edgar/data/1018724/000101872416000324/amzn-20160930x10q.htm"
AWS_2016_10K_URL = "https://www.sec.gov/Archives/edgar/data/1018724/000101872417000011/amzn-20161231x10k.htm"
AWS_2022_10K_URL = "https://www.sec.gov/Archives/edgar/data/1018724/000101872423000004/amzn-20221231.htm"
AWS_2025_10K_URL = "https://www.sec.gov/Archives/edgar/data/1018724/000101872426000004/amzn-20251231.htm"

AWS_2025_PERIODS = [
    {"period": "Q1 2016", "period_end": "2016-03-31", "grain": "quarter"},
    {"period": "Q2 2016", "period_end": "2016-06-30", "grain": "quarter"},
    {"period": "Q3 2016", "period_end": "2016-09-30", "grain": "quarter"},
    {"period": "Q4 2016", "period_end": "2016-12-31", "grain": "quarter"},
    {"period": "Q1 2017", "period_end": "2017-03-31", "grain": "quarter"},
    {"period": "Q2 2017", "period_end": "2017-06-30", "grain": "quarter"},
    {"period": "Q3 2017", "period_end": "2017-09-30", "grain": "quarter"},
    {"period": "Q4 2017", "period_end": "2017-12-31", "grain": "quarter"},
    {"period": "Q1 2018", "period_end": "2018-03-31", "grain": "quarter"},
    {"period": "Q2 2018", "period_end": "2018-06-30", "grain": "quarter"},
    {"period": "Q3 2018", "period_end": "2018-09-30", "grain": "quarter"},
    {"period": "Q4 2018", "period_end": "2018-12-31", "grain": "quarter"},
    {"period": "Q1 2019", "period_end": "2019-03-31", "grain": "quarter"},
    {"period": "Q2 2019", "period_end": "2019-06-30", "grain": "quarter"},
    {"period": "Q3 2019", "period_end": "2019-09-30", "grain": "quarter"},
    {"period": "Q4 2019", "period_end": "2019-12-31", "grain": "quarter"},
    {"period": "Q1 2020", "period_end": "2020-03-31", "grain": "quarter"},
    {"period": "Q2 2020", "period_end": "2020-06-30", "grain": "quarter"},
    {"period": "Q3 2020", "period_end": "2020-09-30", "grain": "quarter"},
    {"period": "Q4 2020", "period_end": "2020-12-31", "grain": "quarter"},
    {"period": "Q1 2021", "period_end": "2021-03-31", "grain": "quarter"},
    {"period": "Q2 2021", "period_end": "2021-06-30", "grain": "quarter"},
    {"period": "Q3 2021", "period_end": "2021-09-30", "grain": "quarter"},
    {"period": "Q4 2021", "period_end": "2021-12-31", "grain": "quarter"},
    {"period": "Q1 2022", "period_end": "2022-03-31", "grain": "quarter"},
    {"period": "Q2 2022", "period_end": "2022-06-30", "grain": "quarter"},
    {"period": "Q3 2022", "period_end": "2022-09-30", "grain": "quarter"},
    {"period": "Q4 2022", "period_end": "2022-12-31", "grain": "quarter"},
    {"period": "Q1 2023", "period_end": "2023-03-31", "grain": "quarter"},
    {"period": "Q2 2023", "period_end": "2023-06-30", "grain": "quarter"},
    {"period": "Q3 2023", "period_end": "2023-09-30", "grain": "quarter"},
    {"period": "Q4 2023", "period_end": "2023-12-31", "grain": "quarter"},
    {"period": "Q1 2024", "period_end": "2024-03-31", "grain": "quarter"},
    {"period": "Q2 2024", "period_end": "2024-06-30", "grain": "quarter"},
    {"period": "Q3 2024", "period_end": "2024-09-30", "grain": "quarter"},
    {"period": "Q4 2024", "period_end": "2024-12-31", "grain": "quarter"},
    {"period": "Q1 2025", "period_end": "2025-03-31", "grain": "quarter"},
    {"period": "Q2 2025", "period_end": "2025-06-30", "grain": "quarter"},
    {"period": "Q3 2025", "period_end": "2025-09-30", "grain": "quarter"},
    {"period": "Q4 2025", "period_end": "2025-12-31", "grain": "quarter"},
]

AWS_2025_METRICS = {
    "revenue": {
        "Q1 2016": 2566,
        "Q2 2016": 2886,
        "Q3 2016": 3231,
        "Q4 2016": 3536,
        "Q1 2017": 3661,
        "Q2 2017": 4100,
        "Q3 2017": 4584,
        "Q4 2017": 5114,
        "Q1 2018": 5442,
        "Q2 2018": 6105,
        "Q3 2018": 6679,
        "Q4 2018": 7429,
        "Q1 2019": 7696,
        "Q2 2019": 8381,
        "Q3 2019": 8995,
        "Q4 2019": 9954,
        "Q1 2020": 10219,
        "Q2 2020": 10808,
        "Q3 2020": 11601,
        "Q4 2020": 12742,
        "Q1 2021": 13503,
        "Q2 2021": 14809,
        "Q3 2021": 16110,
        "Q4 2021": 17780,
        "Q1 2022": 18441,
        "Q2 2022": 19739,
        "Q3 2022": 20538,
        "Q4 2022": 21378,
        "Q1 2023": 21354,
        "Q2 2023": 22140,
        "Q3 2023": 23059,
        "Q4 2023": 24204,
        "Q1 2024": 25037,
        "Q2 2024": 26281,
        "Q3 2024": 27452,
        "Q4 2024": 28786,
        "Q1 2025": 29267,
        "Q2 2025": 30873,
        "Q3 2025": 33006,
        "Q4 2025": 35579,
    },
    "operating_income": {
        "Q1 2016": 604,
        "Q2 2016": 718,
        "Q3 2016": 861,
        "Q4 2016": 925,
        "Q1 2017": 890,
        "Q2 2017": 916,
        "Q3 2017": 1171,
        "Q4 2017": 1354,
        "Q1 2018": 1400,
        "Q2 2018": 1642,
        "Q3 2018": 2077,
        "Q4 2018": 2177,
        "Q1 2019": 2223,
        "Q2 2019": 2121,
        "Q3 2019": 2261,
        "Q4 2019": 2596,
        "Q1 2020": 3075,
        "Q2 2020": 3357,
        "Q3 2020": 3535,
        "Q4 2020": 3564,
        "Q1 2021": 4163,
        "Q2 2021": 4193,
        "Q3 2021": 4883,
        "Q4 2021": 5293,
        "Q1 2022": 6518,
        "Q2 2022": 5715,
        "Q3 2022": 5403,
        "Q4 2022": 5205,
        "Q1 2023": 5123,
        "Q2 2023": 5365,
        "Q3 2023": 6976,
        "Q4 2023": 7167,
        "Q1 2024": 9421,
        "Q2 2024": 9334,
        "Q3 2024": 10447,
        "Q4 2024": 10632,
        "Q1 2025": 11547,
        "Q2 2025": 10160,
        "Q3 2025": 11434,
        "Q4 2025": 12465,
    },
}

AWS_2025_SOURCE_BY_PERIOD = {
    "Q1 2016": {
        "label": "Amazon Q1 2016 Form 10-Q AWS segment table",
        "url": AWS_Q1_2016_10Q_URL,
        "type": "official_quarterly_sec_filing",
        "evidence": "Amazon Q1 2016 Form 10-Q Segment Information table lists AWS net sales 2,566 and operating income 604 million USD for the three months ended March 31, 2016.",
    },
    "Q2 2016": {
        "label": "Amazon Q2 2016 Form 10-Q AWS segment table",
        "url": AWS_Q2_2016_10Q_URL,
        "type": "official_quarterly_sec_filing",
        "evidence": "Amazon Q2 2016 Form 10-Q Segment Information table lists AWS net sales 2,886 and operating income 718 million USD for the three months ended June 30, 2016.",
    },
    "Q3 2016": {
        "label": "Amazon Q3 2016 Form 10-Q AWS segment table",
        "url": AWS_Q3_2016_10Q_URL,
        "type": "official_quarterly_sec_filing",
        "evidence": "Amazon Q3 2016 Form 10-Q Segment Information table lists AWS net sales 3,231 and operating income 861 million USD for the three months ended September 30, 2016.",
    },
    "Q4 2016": {
        "label": "Amazon 2016 Form 10-K AWS segment reconciliation",
        "url": AWS_2016_10K_URL,
        "type": "official_annual_report_reconciliation",
        "evidence": "Amazon 2016 Form 10-K Segment Information table reports AWS full-year net sales 12,219 and operating income 3,108 million USD; subtracting official Q1-Q3 AWS amounts gives Q4 net sales 3,536 and operating income 925 million USD.",
    },
    "Q1 2017": {
        "label": "Amazon Q1 2017 Form 10-Q AWS segment table",
        "url": AWS_Q1_2017_10Q_URL,
        "type": "official_quarterly_sec_filing",
        "evidence": "Amazon Q1 2017 Form 10-Q Segment Information table lists AWS net sales 3,661 and operating income 890 million USD for the three months ended March 31, 2017.",
    },
    "Q2 2017": {
        "label": "Amazon Q2 2017 Form 10-Q AWS segment table",
        "url": AWS_Q2_2017_10Q_URL,
        "type": "official_quarterly_sec_filing",
        "evidence": "Amazon Q2 2017 Form 10-Q Segment Information table lists AWS net sales 4,100 and operating income 916 million USD for the three months ended June 30, 2017.",
    },
    "Q3 2017": {
        "label": "Amazon Q3 2017 Form 10-Q AWS segment table",
        "url": AWS_Q3_2017_10Q_URL,
        "type": "official_quarterly_sec_filing",
        "evidence": "Amazon Q3 2017 Form 10-Q Segment Information table lists AWS net sales 4,584 and operating income 1,171 million USD for the three months ended September 30, 2017.",
    },
    "Q4 2017": {
        "label": "Amazon 2017 Form 10-K AWS segment reconciliation",
        "url": AWS_2017_10K_URL,
        "type": "official_annual_report_reconciliation",
        "evidence": "Amazon 2017 Form 10-K Segment Information table reports AWS full-year net sales 17,459 and operating income 4,331 million USD; subtracting official Q1-Q3 AWS amounts gives Q4 net sales 5,114 and operating income 1,354 million USD.",
    },
    "Q1 2018": {
        "label": "Amazon Q1 2018 Form 10-Q AWS segment table",
        "url": AWS_Q1_2018_10Q_URL,
        "type": "official_quarterly_sec_filing",
        "evidence": "Amazon Q1 2018 Form 10-Q Segment Information table lists AWS net sales 5,442 and operating income 1,400 million USD for the three months ended March 31, 2018.",
    },
    "Q2 2018": {
        "label": "Amazon Q2 2018 Form 10-Q AWS segment table",
        "url": AWS_Q2_2018_10Q_URL,
        "type": "official_quarterly_sec_filing",
        "evidence": "Amazon Q2 2018 Form 10-Q Segment Information table lists AWS net sales 6,105 and operating income 1,642 million USD for the three months ended June 30, 2018.",
    },
    "Q3 2018": {
        "label": "Amazon Q3 2018 Form 10-Q AWS segment table",
        "url": AWS_Q3_2018_10Q_URL,
        "type": "official_quarterly_sec_filing",
        "evidence": "Amazon Q3 2018 Form 10-Q Segment Information table lists AWS net sales 6,679 and operating income 2,077 million USD for the three months ended September 30, 2018.",
    },
    "Q4 2018": {
        "label": "Amazon 2018 Form 10-K AWS segment reconciliation",
        "url": AWS_2018_10K_URL,
        "type": "official_annual_report_reconciliation",
        "evidence": "Amazon 2018 Form 10-K Segment Information table reports AWS full-year net sales 25,655 and operating income 7,296 million USD; subtracting official Q1-Q3 AWS amounts gives Q4 net sales 7,429 and operating income 2,177 million USD.",
    },
    "Q1 2019": {
        "label": "Amazon Q1 2019 Form 10-Q AWS segment table",
        "url": AWS_Q1_2019_10Q_URL,
        "type": "official_quarterly_sec_filing",
        "evidence": "Amazon Q1 2019 Form 10-Q Segment Information table lists AWS net sales 7,696 and operating income 2,223 million USD for the three months ended March 31, 2019.",
    },
    "Q2 2019": {
        "label": "Amazon Q2 2019 Form 10-Q AWS segment table",
        "url": AWS_Q2_2019_10Q_URL,
        "type": "official_quarterly_sec_filing",
        "evidence": "Amazon Q2 2019 Form 10-Q Segment Information table lists AWS net sales 8,381 and operating income 2,121 million USD for the three months ended June 30, 2019.",
    },
    "Q3 2019": {
        "label": "Amazon Q3 2019 Form 10-Q AWS segment table",
        "url": AWS_Q3_2019_10Q_URL,
        "type": "official_quarterly_sec_filing",
        "evidence": "Amazon Q3 2019 Form 10-Q Segment Information table lists AWS net sales 8,995 and operating income 2,261 million USD for the three months ended September 30, 2019.",
    },
    "Q4 2019": {
        "label": "Amazon 2019 Form 10-K AWS segment reconciliation",
        "url": AWS_2019_10K_URL,
        "type": "official_annual_report_reconciliation",
        "evidence": "Amazon 2019 Form 10-K Segment Information table reports AWS full-year net sales 35,026 and operating income 9,201 million USD; subtracting official Q1-Q3 AWS amounts gives Q4 net sales 9,954 and operating income 2,596 million USD.",
    },
    "Q1 2020": {
        "label": "Amazon Q1 2020 Form 10-Q AWS segment table",
        "url": AWS_Q1_2020_10Q_URL,
        "type": "official_quarterly_sec_filing",
        "evidence": "Amazon Q1 2020 Form 10-Q Segment Information table lists AWS net sales 10,219 and operating income 3,075 million USD for the three months ended March 31, 2020.",
    },
    "Q2 2020": {
        "label": "Amazon Q2 2020 Form 10-Q AWS segment table",
        "url": AWS_Q2_2020_10Q_URL,
        "type": "official_quarterly_sec_filing",
        "evidence": "Amazon Q2 2020 Form 10-Q Segment Information table lists AWS net sales 10,808 and operating income 3,357 million USD for the three months ended June 30, 2020.",
    },
    "Q3 2020": {
        "label": "Amazon Q3 2020 Form 10-Q AWS segment table",
        "url": AWS_Q3_2020_10Q_URL,
        "type": "official_quarterly_sec_filing",
        "evidence": "Amazon Q3 2020 Form 10-Q Segment Information table lists AWS net sales 11,601 and operating income 3,535 million USD for the three months ended September 30, 2020.",
    },
    "Q4 2020": {
        "label": "Amazon 2020 Form 10-K AWS segment reconciliation",
        "url": AWS_2020_10K_URL,
        "type": "official_annual_report_reconciliation",
        "evidence": "Amazon 2020 Form 10-K Segment Information table reports AWS full-year net sales 45,370 and operating income 13,531 million USD; subtracting official Q1-Q3 AWS amounts gives Q4 net sales 12,742 and operating income 3,564 million USD.",
    },
    "Q1 2021": {
        "label": "Amazon Q1 2021 Form 10-Q AWS segment table",
        "url": AWS_Q1_2021_10Q_URL,
        "type": "official_quarterly_sec_filing",
        "evidence": "Amazon Q1 2021 Form 10-Q Segment Information table lists AWS net sales 13,503 and operating income 4,163 million USD for the three months ended March 31, 2021.",
    },
    "Q2 2021": {
        "label": "Amazon Q2 2021 Form 10-Q AWS segment table",
        "url": AWS_Q2_2021_10Q_URL,
        "type": "official_quarterly_sec_filing",
        "evidence": "Amazon Q2 2021 Form 10-Q Segment Information table lists AWS net sales 14,809 and operating income 4,193 million USD for the three months ended June 30, 2021.",
    },
    "Q3 2021": {
        "label": "Amazon Q3 2021 Form 10-Q AWS segment table",
        "url": AWS_Q3_2021_10Q_URL,
        "type": "official_quarterly_sec_filing",
        "evidence": "Amazon Q3 2021 Form 10-Q Segment Information table lists AWS net sales 16,110 and operating income 4,883 million USD for the three months ended September 30, 2021.",
    },
    "Q4 2021": {
        "label": "Amazon 2021 Form 10-K AWS segment reconciliation",
        "url": AWS_2021_10K_URL,
        "type": "official_annual_report_reconciliation",
        "evidence": "Amazon 2021 Form 10-K Segment Information table reports AWS full-year net sales 62,202 and operating income 18,532 million USD; subtracting official Q1-Q3 AWS amounts gives Q4 net sales 17,780 and operating income 5,293 million USD.",
    },
    "Q1 2022": {
        "label": "Amazon 2022 Form 10-K AWS segment reconciliation",
        "url": AWS_2022_10K_URL,
        "type": "official_annual_report_reconciliation",
        "evidence": "Amazon 2022 Form 10-K Segment Information table reports AWS full-year net sales 80,096 and operating income 22,841 million USD; subtracting official Q2-Q4 trailing table values gives Q1 net sales 18,441 and operating income 6,518 million USD.",
    },
    "Q2 2022": {
        "label": "Amazon Q3 2023 earnings release trailing AWS segment table",
        "url": AWS_Q3_2023_RESULTS_URL,
        "type": "official_quarterly_earnings_release_trailing_table",
        "evidence": "AWS Segment trailing table lists Q2 2022 net sales 19,739 and operating income 5,715 million USD; the trailing twelve months row also ties to 2022 full-year AWS segment totals.",
    },
    "Q3 2022": {
        "label": "Amazon Q4 2023 earnings release trailing AWS segment table",
        "url": AWS_Q4_2023_RESULTS_URL,
        "type": "official_quarterly_earnings_release_trailing_table",
        "evidence": "AWS Segment trailing table lists Q3 2022 net sales 20,538 and operating income 5,403 million USD; the same release reports the 2023 full-year AWS segment comparison.",
    },
    "Q4 2022": {
        "label": "Amazon Q4 2023 earnings release trailing AWS segment table",
        "url": AWS_Q4_2023_RESULTS_URL,
        "type": "official_quarterly_earnings_release_trailing_table",
        "evidence": "AWS Segment trailing table lists Q4 2022 net sales 21,378 and operating income 5,205 million USD; Q3/Q4 2023 trailing tables and the 2022 Form 10-K reconcile to full-year AWS net sales 80,096 and operating income 22,841 million USD.",
    },
    "Q1 2023": {
        "label": "Amazon Q4 2023 earnings release trailing AWS segment table",
        "url": AWS_Q4_2023_RESULTS_URL,
        "type": "official_quarterly_earnings_release_trailing_table",
        "evidence": "AWS Segment trailing table lists Q1 2023 net sales 21,354 and operating income 5,123 million USD; the same release reports full-year AWS net sales 90,757 and operating income 24,631 million USD.",
    },
    "Q2 2023": {
        "label": "Amazon Q4 2023 earnings release trailing AWS segment table",
        "url": AWS_Q4_2023_RESULTS_URL,
        "type": "official_quarterly_earnings_release_trailing_table",
        "evidence": "AWS Segment trailing table lists Q2 2023 net sales 22,140 and operating income 5,365 million USD; the same release reports full-year AWS net sales 90,757 and operating income 24,631 million USD.",
    },
    "Q3 2023": {
        "label": "Amazon Q3 2023 earnings release",
        "url": AWS_Q3_2023_RESULTS_URL,
        "type": "official_quarterly_earnings_release",
        "evidence": "AWS Segment table lists Q3 2023 net sales 23,059 and operating income 6,976 million USD for the three months ended September 30, 2023.",
    },
    "Q4 2023": {
        "label": "Amazon Q4 2023 earnings release",
        "url": AWS_Q4_2023_RESULTS_URL,
        "type": "official_quarterly_earnings_release",
        "evidence": "AWS Segment table lists Q4 2023 net sales 24,204 and operating income 7,167 million USD for the three months ended December 31, 2023; the same release reports full-year AWS net sales 90,757 and operating income 24,631 million USD.",
    },
    "Q1 2024": {
        "label": "Amazon Q1 2024 earnings release",
        "url": AWS_Q1_2024_RESULTS_URL,
        "type": "official_quarterly_earnings_release",
        "evidence": "Segment Information table: AWS net sales 25,037 and operating income 9,421 million USD for the three months ended March 31, 2024.",
    },
    "Q2 2024": {
        "label": "Amazon Q2 2024 earnings release",
        "url": AWS_Q2_2024_RESULTS_URL,
        "type": "official_quarterly_earnings_release",
        "evidence": "Segment Information table: AWS net sales 26,281 and operating income 9,334 million USD for the three months ended June 30, 2024.",
    },
    "Q3 2024": {
        "label": "Amazon Q3 2024 earnings release",
        "url": AWS_Q3_2024_RESULTS_URL,
        "type": "official_quarterly_earnings_release",
        "evidence": "Segment Information table: AWS net sales 27,452 and operating income 10,447 million USD for the three months ended September 30, 2024.",
    },
    "Q4 2024": {
        "label": "Amazon Q4 2024 earnings release",
        "url": AWS_Q4_2024_RESULTS_URL,
        "type": "official_quarterly_earnings_release",
        "evidence": "Segment Information table: AWS net sales 28,786 and operating income 10,632 million USD for the three months ended December 31, 2024; the same release reports full-year AWS net sales 107,556 and operating income 39,834 million USD.",
    },
    "Q1 2025": {
        "label": "Amazon Q1 2025 earnings release",
        "url": AWS_Q1_2025_RESULTS_URL,
        "type": "official_quarterly_earnings_release",
        "evidence": "Segment Information table: AWS net sales 29,267 and operating income 11,547 million USD for the three months ended March 31, 2025.",
    },
    "Q2 2025": {
        "label": "Amazon Q2 2025 earnings release",
        "url": AWS_Q2_2025_RESULTS_URL,
        "type": "official_quarterly_earnings_release",
        "evidence": "Segment Information table: AWS net sales 30,873 and operating income 10,160 million USD for the three months ended June 30, 2025.",
    },
    "Q3 2025": {
        "label": "Amazon Q3 2025 earnings release",
        "url": AWS_Q3_2025_RESULTS_URL,
        "type": "official_quarterly_earnings_release",
        "evidence": "Segment Information table: AWS net sales 33,006 and operating income 11,434 million USD for the three months ended September 30, 2025.",
    },
    "Q4 2025": {
        "label": "Amazon 2025 Form 10-K AWS segment reconciliation",
        "url": AWS_2025_10K_URL,
        "type": "official_annual_report_reconciliation",
        "evidence": "Amazon 2025 Form 10-K Segment Information table reports AWS full-year net sales 128,725 and operating income 45,606 million USD; subtracting official Q1-Q3 AWS amounts gives Q4 net sales 35,579 and operating income 12,465 million USD.",
    },
}

MICROSOFT_EARNINGS_INDEX_URL = "https://www.microsoft.com/en-us/Investor/earnings"
MICROSOFT_FY16_Q4_PRESS_URL = "https://www.microsoft.com/en-us/Investor/earnings/FY-2016-Q4/press-release-webcast"
MICROSOFT_FY16_Q4_SEGMENT_URL = "https://www.sec.gov/Archives/edgar/data/789019/000119312516662209/d187868d10k.htm"
MICROSOFT_FY17_Q1_PRESS_URL = "https://www.microsoft.com/en-us/Investor/earnings/FY-2017-Q1/press-release-webcast"
MICROSOFT_FY17_Q1_SEGMENT_URL = "https://www.sec.gov/Archives/edgar/data/789019/000119312516742796/d245252d10q.htm"
MICROSOFT_FY17_Q2_PRESS_URL = "https://www.microsoft.com/en-us/Investor/earnings/FY-2017-Q2/press-release-webcast"
MICROSOFT_FY17_Q2_SEGMENT_URL = "https://www.sec.gov/Archives/edgar/data/789019/000156459017000654/msft-10q_20161231.htm"
MICROSOFT_FY17_Q3_PRESS_URL = "https://www.microsoft.com/en-us/Investor/earnings/FY-2017-Q3/press-release-webcast"
MICROSOFT_FY17_Q3_SEGMENT_URL = "https://www.sec.gov/Archives/edgar/data/789019/000156459017007547/msft-10q_20170331.htm"
MICROSOFT_FY17_Q4_PRESS_URL = "https://www.microsoft.com/en-us/Investor/earnings/FY-2017-Q4/press-release-webcast"
MICROSOFT_FY17_Q4_SEGMENT_URL = "https://www.sec.gov/Archives/edgar/data/789019/000156459017014900/msft-10k_20170630.htm"
MICROSOFT_FY18_Q1_PRESS_URL = "https://www.microsoft.com/en-us/Investor/earnings/FY-2018-Q1/press-release-webcast"
MICROSOFT_FY18_Q1_SEGMENT_URL = "https://www.sec.gov/Archives/edgar/data/789019/000156459017020171/msft-10q_20170930.htm"
MICROSOFT_FY18_Q2_PRESS_URL = "https://www.microsoft.com/en-us/Investor/earnings/FY-2018-Q2/press-release-webcast"
MICROSOFT_FY18_Q2_SEGMENT_URL = "https://www.sec.gov/Archives/edgar/data/789019/000156459018001129/msft-10q_20171231.htm"
MICROSOFT_FY18_Q3_PRESS_URL = "https://www.microsoft.com/en-us/Investor/earnings/FY-2018-Q3/press-release-webcast"
MICROSOFT_FY18_Q3_SEGMENT_URL = "https://www.sec.gov/Archives/edgar/data/789019/000156459018009307/msft-10q_20180331.htm"
MICROSOFT_FY18_Q4_PRESS_URL = "https://www.microsoft.com/en-us/Investor/earnings/FY-2018-Q4/press-release-webcast"
MICROSOFT_FY18_Q4_SEGMENT_URL = "https://www.sec.gov/Archives/edgar/data/789019/000156459018019062/msft-10k_20180630.htm"
MICROSOFT_FY19_Q1_PRESS_URL = "https://www.microsoft.com/en-us/Investor/earnings/FY-2019-Q1/press-release-webcast"
MICROSOFT_FY19_Q1_SEGMENT_URL = "https://www.sec.gov/Archives/edgar/data/789019/000156459018024893/msft-10q_20180930.htm"
MICROSOFT_FY19_Q2_PRESS_URL = "https://www.microsoft.com/en-us/Investor/earnings/FY-2019-Q2/press-release-webcast"
MICROSOFT_FY19_Q2_SEGMENT_URL = "https://www.sec.gov/Archives/edgar/data/789019/000156459019001392/msft-10q_20181231.htm"
MICROSOFT_FY19_Q3_PRESS_URL = "https://www.microsoft.com/en-us/Investor/earnings/FY-2019-Q3/press-release-webcast"
MICROSOFT_FY19_Q3_SEGMENT_URL = "https://www.sec.gov/Archives/edgar/data/789019/000156459019012709/msft-10q_20190331.htm"
MICROSOFT_FY19_Q4_PRESS_URL = "https://www.microsoft.com/en-us/Investor/earnings/FY-2019-Q4/press-release-webcast"
MICROSOFT_FY19_Q4_SEGMENT_URL = "https://www.sec.gov/Archives/edgar/data/789019/000156459019027952/msft-10k_20190630.htm"
MICROSOFT_FY20_Q1_PRESS_URL = "https://www.microsoft.com/en-us/Investor/earnings/FY-2020-Q1/press-release-webcast"
MICROSOFT_FY20_Q1_SEGMENT_URL = "https://www.sec.gov/Archives/edgar/data/789019/000156459019037549/msft-10q_20190930.htm"
MICROSOFT_FY20_Q2_PRESS_URL = "https://www.microsoft.com/en-us/Investor/earnings/FY-2020-Q2/press-release-webcast"
MICROSOFT_FY20_Q2_SEGMENT_URL = "https://www.sec.gov/Archives/edgar/data/789019/000156459020002450/msft-10q_20191231.htm"
MICROSOFT_FY20_Q3_PRESS_URL = "https://www.microsoft.com/en-us/Investor/earnings/FY-2020-Q3/press-release-webcast"
MICROSOFT_FY20_Q3_SEGMENT_URL = "https://www.sec.gov/Archives/edgar/data/789019/000156459020019706/msft-10q_20200331.htm"
MICROSOFT_FY20_Q4_PRESS_URL = "https://www.microsoft.com/en-us/Investor/earnings/FY-2020-Q4/press-release-webcast"
MICROSOFT_FY20_Q4_SEGMENT_URL = "https://www.sec.gov/Archives/edgar/data/789019/000156459020034944/msft-10k_20200630.htm"
MICROSOFT_FY21_Q1_PRESS_URL = "https://www.microsoft.com/en-us/Investor/earnings/FY-2021-Q1/press-release-webcast"
MICROSOFT_FY21_Q1_SEGMENT_URL = "https://www.sec.gov/Archives/edgar/data/789019/000156459020047996/msft-10q_20200930.htm"
MICROSOFT_FY21_Q2_PRESS_URL = "https://www.microsoft.com/en-us/Investor/earnings/FY-2021-Q2/press-release-webcast"
MICROSOFT_FY21_Q2_SEGMENT_URL = "https://www.sec.gov/Archives/edgar/data/789019/000156459021002316/msft-10q_20201231.htm"
MICROSOFT_FY21_Q3_PRESS_URL = "https://www.microsoft.com/en-us/Investor/earnings/FY-2021-Q3/press-release-webcast"
MICROSOFT_FY21_Q3_SEGMENT_URL = "https://www.sec.gov/Archives/edgar/data/789019/000156459021020891/msft-10q_20210331.htm"
MICROSOFT_FY21_Q4_PRESS_URL = "https://www.microsoft.com/en-us/Investor/earnings/FY-2021-Q4/press-release-webcast"
MICROSOFT_FY21_Q4_SEGMENT_URL = "https://www.sec.gov/Archives/edgar/data/789019/000156459021039151/msft-10k_20210630.htm"
MICROSOFT_FY22_Q1_PRESS_URL = "https://www.microsoft.com/en-us/Investor/earnings/FY-2022-Q1/press-release-webcast"
MICROSOFT_FY22_Q1_SEGMENT_URL = "https://www.sec.gov/Archives/edgar/data/789019/000156459021051992/msft-10q_20210930.htm"
MICROSOFT_FY22_Q2_PRESS_URL = "https://www.microsoft.com/en-us/Investor/earnings/FY-2022-Q2/press-release-webcast"
MICROSOFT_FY22_Q2_SEGMENT_URL = "https://www.sec.gov/Archives/edgar/data/789019/000156459022002324/msft-10q_20211231.htm"
MICROSOFT_FY22_Q3_PRESS_URL = "https://www.microsoft.com/en-us/Investor/earnings/FY-2022-Q3/press-release-webcast"
MICROSOFT_FY22_Q3_SEGMENT_URL = "https://www.sec.gov/Archives/edgar/data/789019/000156459022015675/msft-10q_20220331.htm"
MICROSOFT_FY22_Q4_PRESS_URL = "https://www.microsoft.com/en-us/Investor/earnings/FY-2022-Q4/press-release-webcast"
MICROSOFT_FY22_Q4_SEGMENT_URL = "https://www.sec.gov/Archives/edgar/data/789019/000156459022026876/msft-10k_20220630.htm"
MICROSOFT_FY23_Q1_PRESS_URL = "https://www.microsoft.com/en-us/Investor/earnings/FY-2023-Q1/press-release-webcast"
MICROSOFT_FY23_Q1_SEGMENT_URL = "https://www.microsoft.com/en-us/Investor/earnings/FY-2023-Q1/segment-revenues"
MICROSOFT_FY23_Q2_PRESS_URL = "https://www.microsoft.com/en-us/Investor/earnings/FY-2023-Q2/press-release-webcast"
MICROSOFT_FY23_Q2_SEGMENT_URL = "https://www.microsoft.com/en-us/Investor/earnings/FY-2023-Q2/segment-revenues"
MICROSOFT_FY23_Q3_PRESS_URL = "https://www.microsoft.com/en-us/Investor/earnings/FY-2023-Q3/press-release-webcast"
MICROSOFT_FY23_Q3_SEGMENT_URL = "https://www.microsoft.com/en-us/Investor/earnings/FY-2023-Q3/segment-revenues"
MICROSOFT_FY23_Q4_PRESS_URL = "https://www.microsoft.com/en-us/Investor/earnings/FY-2023-Q4/press-release-webcast"
MICROSOFT_FY23_Q4_SEGMENT_URL = "https://www.microsoft.com/en-us/Investor/earnings/FY-2023-Q4/segment-revenues"
MICROSOFT_FY24_Q1_PRESS_URL = "https://www.microsoft.com/en-us/Investor/earnings/FY-2024-Q1/press-release-webcast"
MICROSOFT_FY24_Q1_SEGMENT_URL = "https://www.microsoft.com/en-us/Investor/earnings/FY-2024-Q1/segment-revenues"
MICROSOFT_FY24_Q2_PRESS_URL = "https://www.microsoft.com/en-us/Investor/earnings/FY-2024-Q2/press-release-webcast"
MICROSOFT_FY24_Q2_SEGMENT_URL = "https://www.microsoft.com/en-us/Investor/earnings/FY-2024-Q2/segment-revenues"
MICROSOFT_FY24_Q3_PRESS_URL = "https://www.microsoft.com/en-us/Investor/earnings/FY-2024-Q3/press-release-webcast"
MICROSOFT_FY24_Q3_SEGMENT_URL = "https://www.microsoft.com/en-us/Investor/earnings/FY-2024-Q3/segment-revenues"
MICROSOFT_FY24_Q4_PRESS_URL = "https://www.microsoft.com/en-us/Investor/earnings/FY-2024-Q4/press-release-webcast"
MICROSOFT_FY24_Q4_SEGMENT_URL = "https://www.microsoft.com/en-us/Investor/earnings/FY-2024-Q4/segment-revenues"
MICROSOFT_FY25_Q1_PRESS_URL = "https://www.microsoft.com/en-us/Investor/earnings/FY-2025-Q1/press-release-webcast"
MICROSOFT_FY25_Q1_SEGMENT_URL = "https://www.microsoft.com/en-us/Investor/earnings/FY-2025-Q1/segment-revenues"
MICROSOFT_FY25_Q2_PRESS_URL = "https://www.microsoft.com/en-us/Investor/earnings/FY-2025-Q2/press-release-webcast"
MICROSOFT_FY25_Q2_SEGMENT_URL = "https://www.microsoft.com/en-us/Investor/earnings/FY-2025-Q2/segment-revenues"
MICROSOFT_FY25_Q3_PRESS_URL = "https://www.microsoft.com/en-us/Investor/earnings/FY-2025-Q3/press-release-webcast"
MICROSOFT_FY25_Q3_SEGMENT_URL = "https://www.microsoft.com/en-us/Investor/earnings/FY-2025-Q3/segment-revenues"
MICROSOFT_FY25_Q4_PRESS_URL = "https://www.microsoft.com/en-us/Investor/earnings/FY-2025-Q4/press-release-webcast"
MICROSOFT_FY25_Q4_SEGMENT_URL = "https://www.microsoft.com/en-us/Investor/earnings/FY-2025-Q4/segment-revenues"
MICROSOFT_FY26_Q1_PRESS_URL = "https://www.microsoft.com/en-us/Investor/earnings/FY-2026-Q1/press-release-webcast"
MICROSOFT_FY26_Q1_SEGMENT_URL = "https://www.microsoft.com/en-us/Investor/earnings/FY-2026-Q1/segment-revenues"
MICROSOFT_FY26_Q2_PRESS_URL = "https://www.microsoft.com/en-us/Investor/earnings/FY-2026-Q2/press-release-webcast"
MICROSOFT_FY26_Q2_SEGMENT_URL = "https://www.microsoft.com/en-us/Investor/earnings/FY-2026-Q2/segment-revenues"
MICROSOFT_FY26_Q3_PRESS_URL = "https://www.microsoft.com/en-us/Investor/earnings/FY-2026-Q3/press-release-webcast"
MICROSOFT_FY26_Q3_SEGMENT_URL = "https://www.microsoft.com/en-us/Investor/earnings/FY-2026-Q3/segment-revenues"

MICROSOFT_2025_PERIODS = [
    {"period": "Q2 2016", "period_end": "2016-06-30", "grain": "quarter"},
    {"period": "Q3 2016", "period_end": "2016-09-30", "grain": "quarter"},
    {"period": "Q4 2016", "period_end": "2016-12-31", "grain": "quarter"},
    {"period": "Q1 2017", "period_end": "2017-03-31", "grain": "quarter"},
    {"period": "Q2 2017", "period_end": "2017-06-30", "grain": "quarter"},
    {"period": "Q3 2017", "period_end": "2017-09-30", "grain": "quarter"},
    {"period": "Q4 2017", "period_end": "2017-12-31", "grain": "quarter"},
    {"period": "Q1 2018", "period_end": "2018-03-31", "grain": "quarter"},
    {"period": "Q2 2018", "period_end": "2018-06-30", "grain": "quarter"},
    {"period": "Q3 2018", "period_end": "2018-09-30", "grain": "quarter"},
    {"period": "Q4 2018", "period_end": "2018-12-31", "grain": "quarter"},
    {"period": "Q1 2019", "period_end": "2019-03-31", "grain": "quarter"},
    {"period": "Q2 2019", "period_end": "2019-06-30", "grain": "quarter"},
    {"period": "Q3 2019", "period_end": "2019-09-30", "grain": "quarter"},
    {"period": "Q4 2019", "period_end": "2019-12-31", "grain": "quarter"},
    {"period": "Q1 2020", "period_end": "2020-03-31", "grain": "quarter"},
    {"period": "Q2 2020", "period_end": "2020-06-30", "grain": "quarter"},
    {"period": "Q3 2020", "period_end": "2020-09-30", "grain": "quarter"},
    {"period": "Q4 2020", "period_end": "2020-12-31", "grain": "quarter"},
    {"period": "Q1 2021", "period_end": "2021-03-31", "grain": "quarter"},
    {"period": "Q2 2021", "period_end": "2021-06-30", "grain": "quarter"},
    {"period": "Q3 2021", "period_end": "2021-09-30", "grain": "quarter"},
    {"period": "Q4 2021", "period_end": "2021-12-31", "grain": "quarter"},
    {"period": "Q1 2022", "period_end": "2022-03-31", "grain": "quarter"},
    {"period": "Q2 2022", "period_end": "2022-06-30", "grain": "quarter"},
    {"period": "Q3 2022", "period_end": "2022-09-30", "grain": "quarter"},
    {"period": "Q4 2022", "period_end": "2022-12-31", "grain": "quarter"},
    {"period": "Q1 2023", "period_end": "2023-03-31", "grain": "quarter"},
    {"period": "Q2 2023", "period_end": "2023-06-30", "grain": "quarter"},
    {"period": "Q3 2023", "period_end": "2023-09-30", "grain": "quarter"},
    {"period": "Q4 2023", "period_end": "2023-12-31", "grain": "quarter"},
    {"period": "Q1 2024", "period_end": "2024-03-31", "grain": "quarter"},
    {"period": "Q2 2024", "period_end": "2024-06-30", "grain": "quarter"},
    {"period": "Q3 2024", "period_end": "2024-09-30", "grain": "quarter"},
    {"period": "Q4 2024", "period_end": "2024-12-31", "grain": "quarter"},
    {"period": "Q1 2025", "period_end": "2025-03-31", "grain": "quarter"},
    {"period": "Q2 2025", "period_end": "2025-06-30", "grain": "quarter"},
    {"period": "Q3 2025", "period_end": "2025-09-30", "grain": "quarter"},
    {"period": "Q4 2025", "period_end": "2025-12-31", "grain": "quarter"},
    {"period": "Q1 2026", "period_end": "2026-03-31", "grain": "quarter"},
]

MICROSOFT_2025_METRICS = {
    "revenue": {"Q2 2016": 6711, "Q3 2016": 6382, "Q4 2016": 6861, "Q1 2017": 6763, "Q2 2017": 7434, "Q3 2017": 6922, "Q4 2017": 7795, "Q1 2018": 7896, "Q2 2018": 9606, "Q3 2018": 8567, "Q4 2018": 9378, "Q1 2019": 9649, "Q2 2019": 11391, "Q3 2019": 10845, "Q4 2019": 11869, "Q1 2020": 12281, "Q2 2020": 13371, "Q3 2020": 12986, "Q4 2020": 14601, "Q1 2021": 15118, "Q2 2021": 17375, "Q3 2021": 16964, "Q4 2021": 18327, "Q1 2022": 19051, "Q2 2022": 20909, "Q3 2022": 20325, "Q4 2022": 21508, "Q1 2023": 22081, "Q2 2023": 23993, "Q3 2023": 24259, "Q4 2023": 25880, "Q1 2024": 26708, "Q2 2024": 28515, "Q3 2024": 24092, "Q4 2024": 25544, "Q1 2025": 26751, "Q2 2025": 29878, "Q3 2025": 30897, "Q4 2025": 32907, "Q1 2026": 34681},
    "operating_income": {"Q2 2016": 2190, "Q3 2016": 2058, "Q4 2016": 2398, "Q1 2017": 2181, "Q2 2017": 2501, "Q3 2017": 2137, "Q4 2017": 2832, "Q1 2018": 2654, "Q2 2018": 3901, "Q3 2018": 2931, "Q4 2018": 3279, "Q1 2019": 3208, "Q2 2019": 4502, "Q3 2019": 3889, "Q4 2019": 4531, "Q1 2020": 4560, "Q2 2020": 5344, "Q3 2020": 5422, "Q4 2020": 6492, "Q1 2021": 6425, "Q2 2021": 7787, "Q3 2021": 7562, "Q4 2021": 8197, "Q1 2022": 8281, "Q2 2022": 8681, "Q3 2022": 8978, "Q4 2022": 8904, "Q1 2023": 9476, "Q2 2023": 10526, "Q3 2023": 11751, "Q4 2023": 12461, "Q1 2024": 12513, "Q2 2024": 12859, "Q3 2024": 10503, "Q4 2024": 10851, "Q1 2025": 11095, "Q2 2025": 12140, "Q3 2025": 13391, "Q4 2025": 13873, "Q1 2026": 13753},
    "azure_and_other_cloud_services_growth_yoy": {"Q2 2016": 102, "Q3 2016": 116, "Q4 2016": 93, "Q1 2017": 93, "Q2 2017": 97, "Q3 2017": 90, "Q4 2017": 98, "Q1 2018": 93, "Q2 2018": 89, "Q3 2018": 76, "Q4 2018": 76, "Q1 2019": 73, "Q2 2019": 64, "Q3 2019": 59, "Q4 2019": 62, "Q1 2020": 59, "Q2 2020": 47, "Q3 2020": 48, "Q4 2020": 50, "Q1 2021": 50, "Q2 2021": 51, "Q3 2021": 50, "Q4 2021": 46, "Q1 2022": 46, "Q2 2022": 40, "Q3 2022": 35, "Q4 2022": 31, "Q1 2023": 27, "Q2 2023": 26, "Q3 2023": 29, "Q4 2023": 30, "Q1 2024": 31, "Q2 2024": 29, "Q3 2024": 33, "Q4 2024": 31, "Q1 2025": 33, "Q2 2025": 39, "Q3 2025": 40, "Q4 2025": 39, "Q1 2026": 40},
}

MICROSOFT_2025_SOURCE_BY_PERIOD = {
    "Q2 2016": {
        "label": "Microsoft FY16 Q4 earnings release",
        "url": MICROSOFT_FY16_Q4_PRESS_URL,
        "segment_url": MICROSOFT_FY16_Q4_SEGMENT_URL,
        "type": "official_annual_report_reconciliation",
        "evidence": "Quarter ended June 30, 2016: Intelligent Cloud revenue 6,711 and operating income 2,190 million USD, reconciled from FY2016 Intelligent Cloud annual revenue 25,042 and operating income 9,358 minus FY16 first-nine-month revenue 18,331 and operating income 7,168; Azure revenue growth 102%.",
    },
    "Q3 2016": {
        "label": "Microsoft FY17 Q1 earnings release",
        "url": MICROSOFT_FY17_Q1_PRESS_URL,
        "segment_url": MICROSOFT_FY17_Q1_SEGMENT_URL,
        "type": "official_quarterly_earnings_release",
        "evidence": "Quarter ended September 30, 2016: Intelligent Cloud revenue 6,382 and operating income 2,058 million USD; Azure revenue growth 116%.",
    },
    "Q4 2016": {
        "label": "Microsoft FY17 Q2 earnings release",
        "url": MICROSOFT_FY17_Q2_PRESS_URL,
        "segment_url": MICROSOFT_FY17_Q2_SEGMENT_URL,
        "type": "official_quarterly_earnings_release",
        "evidence": "Quarter ended December 31, 2016: Intelligent Cloud revenue 6,861 and operating income 2,398 million USD; Azure revenue increased 93%.",
    },
    "Q1 2017": {
        "label": "Microsoft FY17 Q3 earnings release",
        "url": MICROSOFT_FY17_Q3_PRESS_URL,
        "segment_url": MICROSOFT_FY17_Q3_SEGMENT_URL,
        "type": "official_quarterly_earnings_release",
        "evidence": "Quarter ended March 31, 2017: Intelligent Cloud revenue 6,763 and operating income 2,181 million USD; Azure revenue growth 93%.",
    },
    "Q2 2017": {
        "label": "Microsoft FY17 Q4 earnings release",
        "url": MICROSOFT_FY17_Q4_PRESS_URL,
        "segment_url": MICROSOFT_FY17_Q4_SEGMENT_URL,
        "type": "official_annual_report_reconciliation",
        "evidence": "Quarter ended June 30, 2017: Intelligent Cloud revenue 7,434 and operating income 2,501 million USD, reconciled from FY2017 Intelligent Cloud annual revenue 27,440 and operating income 9,138 minus FY17 first-nine-month revenue 20,006 and operating income 6,637; Azure revenue growth 97%.",
    },
    "Q3 2017": {
        "label": "Microsoft FY18 Q1 earnings release",
        "url": MICROSOFT_FY18_Q1_PRESS_URL,
        "segment_url": MICROSOFT_FY18_Q1_SEGMENT_URL,
        "type": "official_quarterly_earnings_release",
        "evidence": "Quarter ended September 30, 2017: Intelligent Cloud revenue 6,922 and operating income 2,137 million USD; Azure revenue growth 90%.",
    },
    "Q4 2017": {
        "label": "Microsoft FY18 Q2 earnings release",
        "url": MICROSOFT_FY18_Q2_PRESS_URL,
        "segment_url": MICROSOFT_FY18_Q2_SEGMENT_URL,
        "type": "official_quarterly_earnings_release",
        "evidence": "Quarter ended December 31, 2017: Intelligent Cloud revenue 7,795 and operating income 2,832 million USD; Azure revenue growth 98%.",
    },
    "Q1 2018": {
        "label": "Microsoft FY18 Q3 earnings release",
        "url": MICROSOFT_FY18_Q3_PRESS_URL,
        "segment_url": MICROSOFT_FY18_Q3_SEGMENT_URL,
        "type": "official_quarterly_earnings_release",
        "evidence": "Quarter ended March 31, 2018: Intelligent Cloud revenue 7,896 and operating income 2,654 million USD; Azure revenue growth 93%.",
    },
    "Q2 2018": {
        "label": "Microsoft FY18 Q4 earnings release",
        "url": MICROSOFT_FY18_Q4_PRESS_URL,
        "segment_url": MICROSOFT_FY18_Q4_SEGMENT_URL,
        "type": "official_annual_report_reconciliation",
        "evidence": "Quarter ended June 30, 2018: Intelligent Cloud revenue 9,606 and operating income 3,901 million USD, reconciled from FY2018 Intelligent Cloud annual revenue 32,219 and operating income 11,524 minus FY18 first-nine-month revenue 22,613 and operating income 7,623; Azure revenue growth 89%.",
    },
    "Q3 2018": {
        "label": "Microsoft FY19 Q1 earnings release",
        "url": MICROSOFT_FY19_Q1_PRESS_URL,
        "segment_url": MICROSOFT_FY19_Q1_SEGMENT_URL,
        "type": "official_quarterly_earnings_release",
        "evidence": "Quarter ended September 30, 2018: Intelligent Cloud revenue 8,567 and operating income 2,931 million USD; Azure revenue growth 76%.",
    },
    "Q4 2018": {
        "label": "Microsoft FY19 Q2 earnings release",
        "url": MICROSOFT_FY19_Q2_PRESS_URL,
        "segment_url": MICROSOFT_FY19_Q2_SEGMENT_URL,
        "type": "official_quarterly_earnings_release",
        "evidence": "Quarter ended December 31, 2018: Intelligent Cloud revenue 9,378 and operating income 3,279 million USD; Azure revenue growth 76%.",
    },
    "Q1 2019": {
        "label": "Microsoft FY19 Q3 earnings release",
        "url": MICROSOFT_FY19_Q3_PRESS_URL,
        "segment_url": MICROSOFT_FY19_Q3_SEGMENT_URL,
        "type": "official_quarterly_earnings_release",
        "evidence": "Quarter ended March 31, 2019: Intelligent Cloud revenue 9,649 and operating income 3,208 million USD; Azure revenue growth 73%.",
    },
    "Q2 2019": {
        "label": "Microsoft FY19 Q4 earnings release",
        "url": MICROSOFT_FY19_Q4_PRESS_URL,
        "segment_url": MICROSOFT_FY19_Q4_SEGMENT_URL,
        "type": "official_annual_report_reconciliation",
        "evidence": "Quarter ended June 30, 2019: Intelligent Cloud revenue 11,391 and operating income 4,502 million USD, reconciled from FY2019 Intelligent Cloud annual revenue 38,985 and operating income 13,920 minus FY19 first-nine-month revenue 27,594 and operating income 9,418; Azure revenue growth 64%.",
    },
    "Q3 2019": {
        "label": "Microsoft FY20 Q1 earnings release",
        "url": MICROSOFT_FY20_Q1_PRESS_URL,
        "segment_url": MICROSOFT_FY20_Q1_SEGMENT_URL,
        "type": "official_quarterly_earnings_release",
        "evidence": "Quarter ended September 30, 2019: Intelligent Cloud revenue 10,845 and operating income 3,889 million USD; Azure revenue growth 59%.",
    },
    "Q4 2019": {
        "label": "Microsoft FY20 Q2 earnings release",
        "url": MICROSOFT_FY20_Q2_PRESS_URL,
        "segment_url": MICROSOFT_FY20_Q2_SEGMENT_URL,
        "type": "official_quarterly_earnings_release",
        "evidence": "Quarter ended December 31, 2019: Intelligent Cloud revenue 11,869 and operating income 4,531 million USD; Azure revenue growth 62%.",
    },
    "Q1 2020": {
        "label": "Microsoft FY20 Q3 earnings release",
        "url": MICROSOFT_FY20_Q3_PRESS_URL,
        "segment_url": MICROSOFT_FY20_Q3_SEGMENT_URL,
        "type": "official_quarterly_earnings_release",
        "evidence": "Quarter ended March 31, 2020: Intelligent Cloud revenue 12,281 and operating income 4,560 million USD; Azure revenue growth 59%.",
    },
    "Q2 2020": {
        "label": "Microsoft FY20 Q4 earnings release",
        "url": MICROSOFT_FY20_Q4_PRESS_URL,
        "segment_url": MICROSOFT_FY20_Q4_SEGMENT_URL,
        "type": "official_annual_report_reconciliation",
        "evidence": "Quarter ended June 30, 2020: Intelligent Cloud revenue 13,371 and operating income 5,344 million USD, reconciled from FY2020 Intelligent Cloud annual revenue 48,366 and operating income 18,324 minus FY20 first-nine-month revenue 34,995 and operating income 12,980; Azure revenue growth 47%.",
    },
    "Q3 2020": {
        "label": "Microsoft FY21 Q1 earnings release",
        "url": MICROSOFT_FY21_Q1_PRESS_URL,
        "segment_url": MICROSOFT_FY21_Q1_SEGMENT_URL,
        "type": "official_quarterly_earnings_release",
        "evidence": "Quarter ended September 30, 2020: Intelligent Cloud revenue 12,986 and operating income 5,422 million USD; Azure revenue growth 48%.",
    },
    "Q4 2020": {
        "label": "Microsoft FY21 Q2 earnings release",
        "url": MICROSOFT_FY21_Q2_PRESS_URL,
        "segment_url": MICROSOFT_FY21_Q2_SEGMENT_URL,
        "type": "official_quarterly_earnings_release",
        "evidence": "Quarter ended December 31, 2020: Intelligent Cloud revenue 14,601 and operating income 6,492 million USD; Azure revenue growth 50%.",
    },
    "Q1 2021": {
        "label": "Microsoft FY21 Q3 earnings release",
        "url": MICROSOFT_FY21_Q3_PRESS_URL,
        "segment_url": MICROSOFT_FY21_Q3_SEGMENT_URL,
        "type": "official_quarterly_earnings_release",
        "evidence": "Quarter ended March 31, 2021: Intelligent Cloud revenue 15,118 and operating income 6,425 million USD; Azure revenue growth 50%.",
    },
    "Q2 2021": {
        "label": "Microsoft FY21 Q4 earnings release",
        "url": MICROSOFT_FY21_Q4_PRESS_URL,
        "segment_url": MICROSOFT_FY21_Q4_SEGMENT_URL,
        "type": "official_annual_report_reconciliation",
        "evidence": "Quarter ended June 30, 2021: Intelligent Cloud revenue 17,375 and operating income 7,787 million USD, reconciled from FY2021 Intelligent Cloud annual revenue 60,080 and operating income 26,126 minus FY21 first-nine-month revenue 42,705 and operating income 18,339; Azure revenue growth 51%.",
    },
    "Q3 2021": {
        "label": "Microsoft FY22 Q1 earnings release",
        "url": MICROSOFT_FY22_Q1_PRESS_URL,
        "segment_url": MICROSOFT_FY22_Q1_SEGMENT_URL,
        "type": "official_quarterly_earnings_release",
        "evidence": "Quarter ended September 30, 2021: Intelligent Cloud revenue 16,964 and operating income 7,562 million USD from the contemporaneous FY22 Q1 Form 10-Q segment table; Azure and other cloud services revenue growth 50%. Later FY23 comparison tables restated this historical quarter to revenue 16,912 and operating income 7,681, so conclusions should cite this row's chosen contemporaneous SEC filing basis.",
    },
    "Q4 2021": {
        "label": "Microsoft FY22 Q2 earnings release",
        "url": MICROSOFT_FY22_Q2_PRESS_URL,
        "segment_url": MICROSOFT_FY22_Q2_SEGMENT_URL,
        "type": "official_quarterly_earnings_release",
        "evidence": "Quarter ended December 31, 2021: Intelligent Cloud revenue 18,327 and operating income 8,197 million USD; Azure and other cloud services revenue growth 46%.",
    },
    "Q1 2022": {
        "label": "Microsoft FY22 Q3 earnings release",
        "url": MICROSOFT_FY22_Q3_PRESS_URL,
        "segment_url": MICROSOFT_FY22_Q3_SEGMENT_URL,
        "type": "official_quarterly_earnings_release",
        "evidence": "Quarter ended March 31, 2022: Intelligent Cloud revenue 19,051 and operating income 8,281 million USD; Azure and other cloud services revenue growth 46%.",
    },
    "Q2 2022": {
        "label": "Microsoft FY22 Q4 earnings release",
        "url": MICROSOFT_FY22_Q4_PRESS_URL,
        "segment_url": MICROSOFT_FY22_Q4_SEGMENT_URL,
        "type": "official_annual_report_reconciliation",
        "evidence": "Quarter ended June 30, 2022: Intelligent Cloud revenue 20,909 and operating income 8,681 million USD, reconciled from FY2022 Intelligent Cloud annual revenue 75,251 and operating income 32,721 minus FY22 first-nine-month revenue 54,342 and operating income 24,040; Azure and other cloud services revenue growth 40%.",
    },
    "Q3 2022": {
        "label": "Microsoft FY23 Q1 earnings release",
        "url": MICROSOFT_FY23_Q1_PRESS_URL,
        "segment_url": MICROSOFT_FY23_Q1_SEGMENT_URL,
        "type": "official_quarterly_earnings_release",
        "evidence": "Quarter ended September 30, 2022: Intelligent Cloud revenue 20,325 and operating income 8,978 million USD; Azure and other cloud services revenue growth 35%.",
    },
    "Q4 2022": {
        "label": "Microsoft FY23 Q2 earnings release",
        "url": MICROSOFT_FY23_Q2_PRESS_URL,
        "segment_url": MICROSOFT_FY23_Q2_SEGMENT_URL,
        "type": "official_quarterly_earnings_release",
        "evidence": "Quarter ended December 31, 2022: Intelligent Cloud revenue 21,508 and operating income 8,904 million USD; Azure and other cloud services revenue growth 31%.",
    },
    "Q1 2023": {
        "label": "Microsoft FY23 Q3 earnings release",
        "url": MICROSOFT_FY23_Q3_PRESS_URL,
        "segment_url": MICROSOFT_FY23_Q3_SEGMENT_URL,
        "type": "official_quarterly_earnings_release",
        "evidence": "Quarter ended March 31, 2023: Intelligent Cloud revenue 22,081 and operating income 9,476 million USD; Azure and other cloud services revenue growth 27%.",
    },
    "Q2 2023": {
        "label": "Microsoft FY23 Q4 earnings release",
        "url": MICROSOFT_FY23_Q4_PRESS_URL,
        "segment_url": MICROSOFT_FY23_Q4_SEGMENT_URL,
        "type": "official_annual_report_reconciliation",
        "evidence": "Quarter ended June 30, 2023: Intelligent Cloud revenue 23,993 and operating income 10,526 million USD, reconciled from FY2023 Intelligent Cloud annual revenue 87,907 and operating income 37,884 minus FY23 first-nine-month revenue 63,914 and operating income 27,358; Azure and other cloud services revenue growth 26%.",
    },
    "Q3 2023": {
        "label": "Microsoft FY24 Q1 earnings release",
        "url": MICROSOFT_FY24_Q1_PRESS_URL,
        "segment_url": MICROSOFT_FY24_Q1_SEGMENT_URL,
        "type": "official_quarterly_earnings_release",
        "evidence": "Quarter ended September 30, 2023: Intelligent Cloud revenue 24,259 and operating income 11,751 million USD; Azure and other cloud services revenue growth 29%.",
    },
    "Q4 2023": {
        "label": "Microsoft FY24 Q2 earnings release",
        "url": MICROSOFT_FY24_Q2_PRESS_URL,
        "segment_url": MICROSOFT_FY24_Q2_SEGMENT_URL,
        "type": "official_quarterly_earnings_release",
        "evidence": "Quarter ended December 31, 2023: Intelligent Cloud revenue 25,880 and operating income 12,461 million USD; Azure and other cloud services revenue growth 30%.",
    },
    "Q1 2024": {
        "label": "Microsoft FY24 Q3 earnings release",
        "url": MICROSOFT_FY24_Q3_PRESS_URL,
        "segment_url": MICROSOFT_FY24_Q3_SEGMENT_URL,
        "type": "official_quarterly_earnings_release",
        "evidence": "Quarter ended March 31, 2024: Intelligent Cloud revenue 26,708 and operating income 12,513 million USD; Azure and other cloud services revenue growth 31%.",
    },
    "Q2 2024": {
        "label": "Microsoft FY24 Q4 earnings release",
        "url": MICROSOFT_FY24_Q4_PRESS_URL,
        "segment_url": MICROSOFT_FY24_Q4_SEGMENT_URL,
        "type": "official_quarterly_earnings_release",
        "evidence": "Quarter ended June 30, 2024: Intelligent Cloud revenue 28,515 and operating income 12,859 million USD; Azure and other cloud services revenue growth 29%.",
    },
    "Q3 2024": {
        "label": "Microsoft FY25 Q1 earnings release",
        "url": MICROSOFT_FY25_Q1_PRESS_URL,
        "segment_url": MICROSOFT_FY25_Q1_SEGMENT_URL,
        "type": "official_quarterly_earnings_release",
        "evidence": "Quarter ended September 30, 2024: Intelligent Cloud revenue 24,092 and operating income 10,503 million USD; Azure and other cloud services revenue growth 33%.",
    },
    "Q4 2024": {
        "label": "Microsoft FY25 Q2 earnings release",
        "url": MICROSOFT_FY25_Q2_PRESS_URL,
        "segment_url": MICROSOFT_FY25_Q2_SEGMENT_URL,
        "type": "official_quarterly_earnings_release",
        "evidence": "Quarter ended December 31, 2024: Intelligent Cloud revenue 25,544 and operating income 10,851 million USD; Azure and other cloud services revenue growth 31%.",
    },
    "Q1 2025": {
        "label": "Microsoft FY25 Q3 earnings release",
        "url": MICROSOFT_FY25_Q3_PRESS_URL,
        "segment_url": MICROSOFT_FY25_Q3_SEGMENT_URL,
        "type": "official_quarterly_earnings_release",
        "evidence": "Quarter ended March 31, 2025: Intelligent Cloud revenue 26,751 and operating income 11,095 million USD; Azure and other cloud services revenue growth 33%.",
    },
    "Q2 2025": {
        "label": "Microsoft FY25 Q4 earnings release",
        "url": MICROSOFT_FY25_Q4_PRESS_URL,
        "segment_url": MICROSOFT_FY25_Q4_SEGMENT_URL,
        "type": "official_quarterly_earnings_release",
        "evidence": "Quarter ended June 30, 2025: Intelligent Cloud revenue 29,878 and operating income 12,140 million USD; Azure and other cloud services revenue growth 39%.",
    },
    "Q3 2025": {
        "label": "Microsoft FY26 Q1 earnings release",
        "url": MICROSOFT_FY26_Q1_PRESS_URL,
        "segment_url": MICROSOFT_FY26_Q1_SEGMENT_URL,
        "type": "official_quarterly_earnings_release",
        "evidence": "Quarter ended September 30, 2025: Intelligent Cloud revenue 30,897 and operating income 13,391 million USD; Azure and other cloud services revenue growth 40%.",
    },
    "Q4 2025": {
        "label": "Microsoft FY26 Q2 earnings release",
        "url": MICROSOFT_FY26_Q2_PRESS_URL,
        "segment_url": MICROSOFT_FY26_Q2_SEGMENT_URL,
        "type": "official_quarterly_earnings_release",
        "evidence": "Quarter ended December 31, 2025: Intelligent Cloud revenue 32,907 and operating income 13,873 million USD; Azure and other cloud services revenue growth 39%.",
    },
    "Q1 2026": {
        "label": "Microsoft FY26 Q3 earnings release",
        "url": MICROSOFT_FY26_Q3_PRESS_URL,
        "segment_url": MICROSOFT_FY26_Q3_SEGMENT_URL,
        "type": "official_quarterly_earnings_release",
        "evidence": "Quarter ended March 31, 2026: Intelligent Cloud revenue 34,681 and operating income 13,753 million USD; Azure and other cloud services revenue growth 40%.",
    },
}

ALPHABET_EARNINGS_INDEX_URL = "https://abc.xyz/investor/earnings/"
ALPHABET_SEC_FILINGS_URL = "https://abc.xyz/investor/sec-filings/"
ALPHABET_Q4_2019_EARNINGS_EXHIBIT_URL = "https://www.sec.gov/Archives/edgar/data/1652044/000165204420000004/googexhibit991q42019.htm"
ALPHABET_2018_10K_URL = "https://www.sec.gov/Archives/edgar/data/1652044/000165204419000004/goog10-kq42018.htm"
ALPHABET_2019_10K_URL = "https://www.sec.gov/Archives/edgar/data/1652044/000165204420000008/goog10-k2019.htm"
ALPHABET_2020_10K_URL = "https://www.sec.gov/Archives/edgar/data/1652044/000165204421000010/goog-20201231.htm"
ALPHABET_2021_10K_URL = "https://www.sec.gov/Archives/edgar/data/1652044/000165204422000019/goog-20211231.htm"
ALPHABET_2022_10K_URL = "https://www.sec.gov/Archives/edgar/data/1652044/000165204423000016/goog-20221231.htm"
ALPHABET_2023_10K_URL = "https://www.sec.gov/Archives/edgar/data/1652044/000165204424000022/goog-20231231.htm"
ALPHABET_2024_10K_URL = "https://www.sec.gov/Archives/edgar/data/1652044/000165204425000014/goog-20241231.htm"
ALPHABET_2025_10K_URL = "https://www.sec.gov/Archives/edgar/data/1652044/000165204426000018/goog-20251231.htm"
ALPHABET_Q1_2020_10Q_URL = "https://www.sec.gov/Archives/edgar/data/1652044/000165204420000021/goog-20200331.htm"
ALPHABET_Q2_2020_10Q_URL = "https://www.sec.gov/Archives/edgar/data/1652044/000165204420000032/goog-20200630.htm"
ALPHABET_Q3_2020_10Q_URL = "https://www.sec.gov/Archives/edgar/data/1652044/000165204420000050/goog-20200930.htm"
ALPHABET_Q1_2021_10Q_URL = "https://www.sec.gov/Archives/edgar/data/1652044/000165204421000020/goog-20210331.htm"
ALPHABET_Q2_2021_10Q_URL = "https://www.sec.gov/Archives/edgar/data/1652044/000165204421000047/goog-20210630.htm"
ALPHABET_Q3_2021_10Q_URL = "https://www.sec.gov/Archives/edgar/data/1652044/000165204421000057/goog-20210930.htm"
ALPHABET_Q1_2022_10Q_URL = "https://www.sec.gov/Archives/edgar/data/1652044/000165204422000029/goog-20220331.htm"
ALPHABET_Q2_2022_10Q_URL = "https://www.sec.gov/Archives/edgar/data/1652044/000165204422000071/goog-20220630.htm"
ALPHABET_Q3_2022_10Q_URL = "https://www.sec.gov/Archives/edgar/data/1652044/000165204422000090/goog-20220930.htm"
ALPHABET_Q1_2023_10Q_URL = "https://www.sec.gov/Archives/edgar/data/1652044/000165204423000045/goog-20230331.htm"
ALPHABET_Q2_2023_10Q_URL = "https://www.sec.gov/Archives/edgar/data/1652044/000165204423000070/goog-20230630.htm"
ALPHABET_Q3_2023_10Q_URL = "https://www.sec.gov/Archives/edgar/data/1652044/000165204423000094/goog-20230930.htm"
ALPHABET_Q1_2024_10Q_URL = "https://www.sec.gov/Archives/edgar/data/1652044/000165204424000053/goog-20240331.htm"
ALPHABET_Q2_2024_10Q_URL = "https://www.sec.gov/Archives/edgar/data/1652044/000165204424000079/goog-20240630.htm"
ALPHABET_Q3_2024_10Q_URL = "https://www.sec.gov/Archives/edgar/data/1652044/000165204424000118/goog-20240930.htm"
ALPHABET_Q1_2025_10Q_URL = "https://www.sec.gov/Archives/edgar/data/1652044/000165204425000043/goog-20250331.htm"
ALPHABET_Q2_2025_10Q_URL = "https://www.sec.gov/Archives/edgar/data/1652044/000165204425000062/goog-20250630.htm"
ALPHABET_Q3_2025_10Q_URL = "https://www.sec.gov/Archives/edgar/data/1652044/000165204425000091/goog-20250930.htm"
ALPHABET_Q4_2025_8K_EXHIBIT_URL = "https://www.sec.gov/Archives/edgar/data/1652044/000165204426000012/googexhibit991q42025.htm"

GOOGLE_CLOUD_2025_PERIODS = [
    {"period": "Q1 2020", "period_end": "2020-03-31", "grain": "quarter"},
    {"period": "Q2 2020", "period_end": "2020-06-30", "grain": "quarter"},
    {"period": "Q3 2020", "period_end": "2020-09-30", "grain": "quarter"},
    {"period": "Q4 2020", "period_end": "2020-12-31", "grain": "quarter"},
    {"period": "Q1 2021", "period_end": "2021-03-31", "grain": "quarter"},
    {"period": "Q2 2021", "period_end": "2021-06-30", "grain": "quarter"},
    {"period": "Q3 2021", "period_end": "2021-09-30", "grain": "quarter"},
    {"period": "Q4 2021", "period_end": "2021-12-31", "grain": "quarter"},
    {"period": "Q1 2022", "period_end": "2022-03-31", "grain": "quarter"},
    {"period": "Q2 2022", "period_end": "2022-06-30", "grain": "quarter"},
    {"period": "Q3 2022", "period_end": "2022-09-30", "grain": "quarter"},
    {"period": "Q4 2022", "period_end": "2022-12-31", "grain": "quarter"},
    {"period": "Q1 2023", "period_end": "2023-03-31", "grain": "quarter"},
    {"period": "Q2 2023", "period_end": "2023-06-30", "grain": "quarter"},
    {"period": "Q3 2023", "period_end": "2023-09-30", "grain": "quarter"},
    {"period": "Q4 2023", "period_end": "2023-12-31", "grain": "quarter"},
    {"period": "Q1 2024", "period_end": "2024-03-31", "grain": "quarter"},
    {"period": "Q2 2024", "period_end": "2024-06-30", "grain": "quarter"},
    {"period": "Q3 2024", "period_end": "2024-09-30", "grain": "quarter"},
    {"period": "Q4 2024", "period_end": "2024-12-31", "grain": "quarter"},
    {"period": "Q1 2025", "period_end": "2025-03-31", "grain": "quarter"},
    {"period": "Q2 2025", "period_end": "2025-06-30", "grain": "quarter"},
    {"period": "Q3 2025", "period_end": "2025-09-30", "grain": "quarter"},
    {"period": "Q4 2025", "period_end": "2025-12-31", "grain": "quarter"},
]

GOOGLE_CLOUD_2025_METRICS = {
    "revenue": {"Q1 2020": 2777, "Q2 2020": 3007, "Q3 2020": 3444, "Q4 2020": 3831, "Q1 2021": 4047, "Q2 2021": 4628, "Q3 2021": 4990, "Q4 2021": 5541, "Q1 2022": 5821, "Q2 2022": 6276, "Q3 2022": 6868, "Q4 2022": 7315, "Q1 2023": 7454, "Q2 2023": 8031, "Q3 2023": 8411, "Q4 2023": 9192, "Q1 2024": 9574, "Q2 2024": 10347, "Q3 2024": 11353, "Q4 2024": 11955, "Q1 2025": 12260, "Q2 2025": 13624, "Q3 2025": 15157, "Q4 2025": 17664},
    "operating_income": {"Q1 2020": -1730, "Q2 2020": -1426, "Q3 2020": -1208, "Q4 2020": -1243, "Q1 2021": -974, "Q2 2021": -591, "Q3 2021": -644, "Q4 2021": -890, "Q1 2022": -931, "Q2 2022": -858, "Q3 2022": -699, "Q4 2022": -480, "Q1 2023": 191, "Q2 2023": 395, "Q3 2023": 266, "Q4 2023": 864, "Q1 2024": 900, "Q2 2024": 1172, "Q3 2024": 1947, "Q4 2024": 2093, "Q1 2025": 2177, "Q2 2025": 2826, "Q3 2025": 3594, "Q4 2025": 5313},
    "revenue_growth_yoy": {"Q1 2020": 52, "Q2 2020": 43, "Q3 2020": 45, "Q4 2020": 47, "Q1 2021": 46, "Q2 2021": 54, "Q3 2021": 45, "Q4 2021": 45, "Q1 2022": 44, "Q2 2022": 36, "Q3 2022": 38, "Q4 2022": 32, "Q1 2023": 28, "Q2 2023": 28, "Q3 2023": 22, "Q4 2023": 26, "Q1 2024": 28, "Q2 2024": 29, "Q3 2024": 35, "Q4 2024": 30, "Q1 2025": 28, "Q2 2025": 32, "Q3 2025": 34, "Q4 2025": 48},
}

GOOGLE_CLOUD_2025_SOURCE_BY_PERIOD = {
    "Q1 2020": {"label": "Alphabet Q1 2020 Form 10-Q", "url": ALPHABET_Q1_2020_10Q_URL, "annual_url": ALPHABET_2020_10K_URL, "type": "official_sec_10q_segment_table", "evidence": "Three months ended March 31, 2020: Google Cloud revenue 2,777 million USD, operating loss 1,730 million USD, and revenue growth 52%."},
    "Q2 2020": {"label": "Alphabet Q2 2020 Form 10-Q", "url": ALPHABET_Q2_2020_10Q_URL, "annual_url": ALPHABET_2020_10K_URL, "type": "official_sec_10q_segment_table", "evidence": "Three months ended June 30, 2020: Google Cloud revenue 3,007 million USD, operating loss 1,426 million USD, and revenue growth 43%."},
    "Q3 2020": {"label": "Alphabet Q3 2020 Form 10-Q", "url": ALPHABET_Q3_2020_10Q_URL, "annual_url": ALPHABET_2020_10K_URL, "type": "official_sec_10q_segment_table", "evidence": "Three months ended September 30, 2020: Google Cloud revenue 3,444 million USD, operating loss 1,208 million USD, and revenue growth 45%."},
    "Q4 2020": {"label": "Alphabet 2020 Form 10-K Google Cloud reconciliation", "url": ALPHABET_2020_10K_URL, "annual_url": ALPHABET_2020_10K_URL, "type": "official_annual_report_reconciliation", "evidence": "Quarter ended December 31, 2020: Google Cloud revenue 3,831 million USD and operating loss 1,243 million USD, reconciled from FY2020 revenue 13,059 and operating loss 5,607 minus Q1-Q3 cumulative revenue 9,228 and operating loss 4,364; revenue growth 47%."},
    "Q1 2021": {"label": "Alphabet Q1 2021 Form 10-Q", "url": ALPHABET_Q1_2021_10Q_URL, "annual_url": ALPHABET_2021_10K_URL, "type": "official_sec_10q_segment_table", "evidence": "Three months ended March 31, 2021: Google Cloud revenue 4,047 million USD, operating loss 974 million USD, and revenue growth 46%."},
    "Q2 2021": {"label": "Alphabet Q2 2021 Form 10-Q", "url": ALPHABET_Q2_2021_10Q_URL, "annual_url": ALPHABET_2021_10K_URL, "type": "official_sec_10q_segment_table", "evidence": "Three months ended June 30, 2021: Google Cloud revenue 4,628 million USD, operating loss 591 million USD, and revenue growth 54%."},
    "Q3 2021": {"label": "Alphabet Q3 2021 Form 10-Q", "url": ALPHABET_Q3_2021_10Q_URL, "annual_url": ALPHABET_2021_10K_URL, "type": "official_sec_10q_segment_table", "evidence": "Three months ended September 30, 2021: Google Cloud revenue 4,990 million USD, operating loss 644 million USD, and revenue growth 45%."},
    "Q4 2021": {"label": "Alphabet 2021 Form 10-K Google Cloud reconciliation", "url": ALPHABET_2021_10K_URL, "annual_url": ALPHABET_2021_10K_URL, "type": "official_annual_report_reconciliation", "evidence": "Quarter ended December 31, 2021: Google Cloud revenue 5,541 million USD and operating loss 890 million USD, reconciled from FY2021 revenue 19,206 and operating loss 3,099 minus Q1-Q3 cumulative revenue 13,665 and operating loss 2,209; revenue growth 45%."},
    "Q1 2022": {"label": "Alphabet Q1 2022 Form 10-Q", "url": ALPHABET_Q1_2022_10Q_URL, "annual_url": ALPHABET_2022_10K_URL, "type": "official_sec_10q_segment_table", "evidence": "Three months ended March 31, 2022: Google Cloud revenue 5,821 million USD, operating loss 931 million USD, and revenue growth 44%."},
    "Q2 2022": {"label": "Alphabet Q2 2022 Form 10-Q", "url": ALPHABET_Q2_2022_10Q_URL, "annual_url": ALPHABET_2022_10K_URL, "type": "official_sec_10q_segment_table", "evidence": "Three months ended June 30, 2022: Google Cloud revenue 6,276 million USD, operating loss 858 million USD, and revenue growth 36%."},
    "Q3 2022": {"label": "Alphabet Q3 2022 Form 10-Q", "url": ALPHABET_Q3_2022_10Q_URL, "annual_url": ALPHABET_2022_10K_URL, "type": "official_sec_10q_segment_table", "evidence": "Three months ended September 30, 2022: Google Cloud revenue 6,868 million USD, operating loss 699 million USD, and revenue growth 38%."},
    "Q4 2022": {"label": "Alphabet 2022 Form 10-K Google Cloud reconciliation", "url": ALPHABET_2022_10K_URL, "annual_url": ALPHABET_2022_10K_URL, "type": "official_annual_report_reconciliation", "evidence": "Quarter ended December 31, 2022: Google Cloud revenue 7,315 million USD and operating loss 480 million USD, reconciled from FY2022 revenue 26,280 and operating loss 2,968 minus Q1-Q3 cumulative revenue 18,965 and operating loss 2,488; revenue growth 32%."},
    "Q1 2023": {"label": "Alphabet Q1 2023 Form 10-Q", "url": ALPHABET_Q1_2023_10Q_URL, "annual_url": ALPHABET_2023_10K_URL, "type": "official_sec_10q_segment_table", "evidence": "Three months ended March 31, 2023: Google Cloud revenue 7,454 million USD, operating income 191 million USD, and revenue growth 28%."},
    "Q2 2023": {"label": "Alphabet Q2 2023 Form 10-Q", "url": ALPHABET_Q2_2023_10Q_URL, "annual_url": ALPHABET_2023_10K_URL, "type": "official_sec_10q_segment_table", "evidence": "Three months ended June 30, 2023: Google Cloud revenue 8,031 million USD, operating income 395 million USD, and revenue growth 28%."},
    "Q3 2023": {"label": "Alphabet Q3 2023 Form 10-Q", "url": ALPHABET_Q3_2023_10Q_URL, "annual_url": ALPHABET_2023_10K_URL, "type": "official_sec_10q_segment_table", "evidence": "Three months ended September 30, 2023: Google Cloud revenue 8,411 million USD, operating income 266 million USD, and revenue growth 22%."},
    "Q4 2023": {"label": "Alphabet 2023 Form 10-K Google Cloud reconciliation", "url": ALPHABET_2023_10K_URL, "annual_url": ALPHABET_2023_10K_URL, "type": "official_annual_report_reconciliation", "evidence": "Quarter ended December 31, 2023: Google Cloud revenue 9,192 million USD and operating income 864 million USD, reconciled from FY2023 revenue 33,088 and operating income 1,716 minus Q1-Q3 cumulative revenue 23,896 and operating income 852; revenue growth 26%."},
    "Q1 2024": {"label": "Alphabet Q1 2024 Form 10-Q", "url": ALPHABET_Q1_2024_10Q_URL, "annual_url": ALPHABET_2024_10K_URL, "type": "official_sec_10q_segment_table", "evidence": "Three months ended March 31, 2024: Google Cloud revenue 9,574 million USD, operating income 900 million USD, and revenue growth 28%."},
    "Q2 2024": {"label": "Alphabet Q2 2024 Form 10-Q", "url": ALPHABET_Q2_2024_10Q_URL, "annual_url": ALPHABET_2024_10K_URL, "type": "official_sec_10q_segment_table", "evidence": "Three months ended June 30, 2024: Google Cloud revenue 10,347 million USD, operating income 1,172 million USD, and revenue growth 29%."},
    "Q3 2024": {"label": "Alphabet Q3 2024 Form 10-Q", "url": ALPHABET_Q3_2024_10Q_URL, "annual_url": ALPHABET_2024_10K_URL, "type": "official_sec_10q_segment_table", "evidence": "Three months ended September 30, 2024: Google Cloud revenue 11,353 million USD, operating income 1,947 million USD, and revenue growth 35%."},
    "Q4 2024": {"label": "Alphabet 2024 Form 10-K Google Cloud reconciliation", "url": ALPHABET_2024_10K_URL, "annual_url": ALPHABET_2024_10K_URL, "type": "official_annual_report_reconciliation", "evidence": "Quarter ended December 31, 2024: Google Cloud revenue 11,955 million USD and operating income 2,093 million USD, reconciled from FY2024 revenue 43,229 and operating income 6,112 minus Q1-Q3 cumulative revenue 31,274 and operating income 4,019; revenue growth 30%."},
    "Q1 2025": {
        "label": "Alphabet Q1 2025 Form 10-Q",
        "url": ALPHABET_Q1_2025_10Q_URL,
        "annual_url": ALPHABET_2025_10K_URL,
        "type": "official_sec_10q_segment_table",
        "evidence": "Three months ended March 31, 2025: Google Cloud revenue 12,260 million USD, operating income 2,177 million USD, and revenue growth 28%.",
    },
    "Q2 2025": {
        "label": "Alphabet Q2 2025 Form 10-Q",
        "url": ALPHABET_Q2_2025_10Q_URL,
        "annual_url": ALPHABET_2025_10K_URL,
        "type": "official_sec_10q_segment_table",
        "evidence": "Three months ended June 30, 2025: Google Cloud revenue 13,624 million USD, operating income 2,826 million USD, and revenue growth 32%.",
    },
    "Q3 2025": {
        "label": "Alphabet Q3 2025 Form 10-Q",
        "url": ALPHABET_Q3_2025_10Q_URL,
        "annual_url": ALPHABET_2025_10K_URL,
        "type": "official_sec_10q_segment_table",
        "evidence": "Three months ended September 30, 2025: Google Cloud revenue 15,157 million USD, operating income 3,594 million USD, and revenue growth 34%.",
    },
    "Q4 2025": {
        "label": "Alphabet Q4 2025 earnings release exhibit",
        "url": ALPHABET_Q4_2025_8K_EXHIBIT_URL,
        "annual_url": ALPHABET_2025_10K_URL,
        "type": "official_sec_8k_earnings_exhibit",
        "evidence": "Quarter ended December 31, 2025: Google Cloud revenue 17,664 million USD, operating income 5,313 million USD, and revenue growth 48%.",
    },
}

GOOGLE_CLOUD_PRE_QUARTERLY_SEGMENT_SOURCE_GAP_PERIODS = [
    "Q1 2016",
    "Q2 2016",
    "Q3 2016",
    "Q4 2016",
    "Q1 2017",
    "Q2 2017",
    "Q3 2017",
    "Q4 2017",
    "Q1 2018",
    "Q2 2018",
    "Q3 2018",
    "Q1 2019",
    "Q2 2019",
    "Q3 2019",
]

GOOGLE_CLOUD_PRE_QUARTERLY_SEGMENT_SOURCE_GAP_CONFIRMATIONS = [
    {
        "subject": "Google Cloud",
        "period": period,
        "metric_key": "cloud_quarterly_disclosure_status",
        "source_label": "Alphabet 2019 Form 10-K",
        "source_url": ALPHABET_2019_10K_URL,
        "evidence": (
            "Alphabet 2019 Form 10-K presents annual Google Cloud revenues for 2017, 2018, and 2019, "
            "and Alphabet's Q4 2019 earnings exhibit provides Q4 2018 and Q4 2019 Google Cloud revenue, "
            "but the retained sources do not provide a complete quarterly Google Cloud revenue series or "
            "quarterly Google Cloud operating income/loss segment rows for this period. "
            "Alphabet 2018 Form 10-K only includes Google Cloud offerings inside Google other revenues. "
            "Alphabet 2020 Form 10-K is the first retained source here with Google Cloud segment revenue "
            "and operating loss tables suitable for the current quarterly segment series; therefore "
            f"{period} is retained as a disclosure-boundary source gap rather than estimated."
        ),
        "verification_method": "official_google_cloud_quarterly_segment_disclosure_gap_check",
        "verification_sources": [
            {
                "label": "Alphabet SEC filings index",
                "url": ALPHABET_SEC_FILINGS_URL,
                "type": "official_sec_filings_index",
                "evidence": "Alphabet Investor Relations SEC filings page lists annual and quarterly SEC filings used to confirm the disclosure boundary.",
            },
            {
                "label": "Alphabet 2018 Form 10-K",
                "url": ALPHABET_2018_10K_URL,
                "type": "official_sec_10k",
                "evidence": "The 2018 Form 10-K describes Google Cloud offerings inside Google other revenues and does not disclose standalone Google Cloud quarterly revenue or operating income/loss.",
            },
            {
                "label": "Alphabet 2019 Form 10-K",
                "url": ALPHABET_2019_10K_URL,
                "type": "official_sec_10k",
                "evidence": "The 2019 Form 10-K discloses annual Google Cloud revenues for 2017, 2018, and 2019, but no full quarterly Google Cloud revenue or operating income/loss segment series.",
            },
            {
                "label": "Alphabet Q4 2019 earnings exhibit",
                "url": ALPHABET_Q4_2019_EARNINGS_EXHIBIT_URL,
                "type": "official_sec_8k_earnings_exhibit",
                "evidence": "The Q4 2019 earnings exhibit provides Google Cloud revenue for Q4 2018 and Q4 2019 plus annual 2017-2019 Google Cloud revenue.",
            },
            {
                "label": "Alphabet 2020 Form 10-K",
                "url": ALPHABET_2020_10K_URL,
                "type": "official_sec_10k",
                "evidence": "The 2020 Form 10-K provides the first retained Google Cloud segment revenue and operating loss tables used for the current quarterly series and annual cross-checks.",
            },
        ],
        "verification_note": "Google Cloud pre-2020 quarters are disclosure-boundary gaps except Q4 2018 and Q4 2019 revenue, which are separately retained from Alphabet's Q4 2019 earnings exhibit. Annual-only 2017-2019 revenue evidence is preserved, but missing quarters are not estimated and do not count toward the 40-quarter cloud coverage gate.",
        "append_if_missing": True,
    }
    for period in GOOGLE_CLOUD_PRE_QUARTERLY_SEGMENT_SOURCE_GAP_PERIODS
]

GOOGLE_CLOUD_Q4_2018_2019_QUARTERLY_REVENUE_SOURCES = [
    {
        "label": "Alphabet investor relations earnings index",
        "url": ALPHABET_EARNINGS_INDEX_URL,
        "type": "official_quarterly_results_index",
        "evidence": "Alphabet official investor relations earnings index is used to locate the Q4 2019 earnings release context.",
    },
    {
        "label": "Alphabet Q4 2019 earnings exhibit",
        "url": ALPHABET_Q4_2019_EARNINGS_EXHIBIT_URL,
        "type": "official_sec_8k_earnings_exhibit",
        "evidence": "Alphabet Q4 2019 earnings exhibit expanded revenue disclosure table reports Google Cloud revenue for Q4 2018 and Q4 2019.",
    },
    {
        "label": "Alphabet 2019 Form 10-K",
        "url": ALPHABET_2019_10K_URL,
        "type": "official_sec_10k",
        "evidence": "Alphabet 2019 Form 10-K annual Google Cloud revenue table cross-checks FY2018 and FY2019 totals.",
    },
]

GOOGLE_CLOUD_Q4_2018_2019_QUARTERLY_REVENUE_OFFICIAL_VERIFICATIONS = [
    {
        "subject": "Google Cloud",
        "period": period,
        "metric_key": "revenue",
        "official_value": value,
        "unit": "millions USD",
        "source_label": "Alphabet Q4 2019 earnings exhibit - expanded Google Cloud revenue disclosure",
        "source_url": ALPHABET_Q4_2019_EARNINGS_EXHIBIT_URL,
        "evidence": evidence,
        "verification_method": "official_q4_earnings_expanded_cloud_revenue_table",
        "verification_sources": GOOGLE_CLOUD_Q4_2018_2019_QUARTERLY_REVENUE_SOURCES,
    }
    for period, value, evidence in [
        ("Q4 2018", 1709, "Alphabet Q4 2019 earnings exhibit expanded revenue disclosure table reports Google Cloud revenue of 1,709 million USD for Q4 2018. Other Q1-Q3 2018 Google Cloud quarterly revenue and quarterly operating income/loss were not disclosed, so only this Q4 revenue row is retained."),
        ("Q4 2019", 2614, "Alphabet Q4 2019 earnings exhibit expanded revenue disclosure table reports Google Cloud revenue of 2,614 million USD for Q4 2019. Other Q1-Q3 2019 Google Cloud quarterly revenue and quarterly operating income/loss were not disclosed, so only this Q4 revenue row is retained."),
    ]
]

GOOGLE_CLOUD_2017_2019_ANNUAL_ONLY_SOURCES = [
    {
        "label": "Alphabet SEC filings index",
        "url": ALPHABET_SEC_FILINGS_URL,
        "type": "official_sec_filings_index",
        "evidence": "Alphabet official investor relations SEC filings index lists the annual reports used to locate Google Cloud annual-only disclosure.",
    },
    {
        "label": "Alphabet 2019 Form 10-K",
        "url": ALPHABET_2019_10K_URL,
        "type": "official_annual_report_segment_table",
        "evidence": "Alphabet 2019 Form 10-K discloses annual Google Cloud revenues for 2017, 2018, and 2019.",
    },
    {
        "label": "Alphabet 2020 Form 10-K",
        "url": ALPHABET_2020_10K_URL,
        "type": "official_annual_report_segment_table",
        "evidence": "Alphabet 2020 Form 10-K provides the first retained Google Cloud segment revenue and operating loss tables and cross-checks the transition to quarterly segment reporting.",
    },
]

GOOGLE_CLOUD_2017_2019_ANNUAL_ONLY_OFFICIAL_VERIFICATIONS = [
    {
        "subject": "Google Cloud",
        "period": period,
        "metric_key": "revenue",
        "official_value": value,
        "unit": "millions USD",
        "source_label": "Alphabet 2019 Form 10-K Google Cloud annual revenue",
        "source_url": ALPHABET_2019_10K_URL,
        "evidence": evidence,
        "verification_method": "official_annual_only_segment_revenue_check",
        "verification_sources": GOOGLE_CLOUD_2017_2019_ANNUAL_ONLY_SOURCES,
    }
    for period, value, evidence in [
        ("FY 2017", 4056, "Alphabet 2019 Form 10-K discloses Google Cloud annual revenues of 4,056 million USD for 2017; quarterly Google Cloud revenue and operating income/loss were not disclosed, so this remains annual-only and must not be split into quarters."),
        ("FY 2018", 5838, "Alphabet 2019 Form 10-K discloses Google Cloud annual revenues of 5,838 million USD for 2018. Alphabet's Q4 2019 earnings exhibit separately discloses Q4 2018 revenue, but Q1-Q3 2018 and quarterly operating income/loss were not disclosed; the annual total must not be split into quarters."),
        ("FY 2019", 8918, "Alphabet 2019 Form 10-K discloses Google Cloud annual revenues of 8,918 million USD for 2019. Alphabet's Q4 2019 earnings exhibit separately discloses Q4 2019 revenue, but Q1-Q3 2019 and quarterly operating income/loss were not disclosed; the annual total must not be split into quarters."),
    ]
]

ORACLE_Q1_FY2022_RESULTS_URL = "https://www.oracle.com/news/announcement/q1fy22-earnings-release-2021-09-13/"
ORACLE_Q2_FY2022_RESULTS_URL = "https://www.oracle.com/news/announcement/q2fy22-earnings-release-2021-12-09/"
ORACLE_Q3_FY2022_RESULTS_URL = "https://www.oracle.com/news/announcement/q3fy22-earnings-release-2022-03-10/"
ORACLE_Q4_FY2022_RESULTS_URL = "https://www.oracle.com/news/announcement/q4fy22-earnings-release-2022-06-13/"
ORACLE_Q1_FY2023_RESULTS_URL = "https://www.oracle.com/news/announcement/q1fy23-earnings-release-2022-09-12/"
ORACLE_Q2_FY2023_RESULTS_URL = "https://www.oracle.com/news/announcement/q2fy23-earnings-release-2022-12-12/"
ORACLE_Q3_FY2023_RESULTS_URL = "https://www.oracle.com/news/announcement/q3fy23-earnings-release-2023-03-09/"
ORACLE_Q4_FY2023_RESULTS_URL = "https://www.oracle.com/news/announcement/q4fy23-earnings-release-2023-06-12/"
ORACLE_Q1_FY2024_RESULTS_URL = "https://www.oracle.com/news/announcement/q1fy24-earnings-release-2023-09-11/"
ORACLE_Q2_FY2024_RESULTS_URL = "https://www.oracle.com/news/announcement/q2fy24-earnings-release-2023-12-11/"
ORACLE_Q3_FY2024_RESULTS_URL = "https://www.oracle.com/news/announcement/q3fy24-earnings-release-2024-03-11/"
ORACLE_Q4_FY2024_RESULTS_URL = "https://www.oracle.com/news/announcement/q4fy24-earnings-release-2024-06-11/"
ORACLE_Q1_FY2025_RESULTS_URL = "https://www.oracle.com/news/announcement/q1fy25-earnings-release-2024-09-09/"
ORACLE_Q2_FY2025_RESULTS_URL = "https://www.oracle.com/news/announcement/q2fy25-earnings-release-2024-12-09/"
ORACLE_Q3_FY2025_RESULTS_URL = "https://www.oracle.com/news/announcement/q3fy25-earnings-release-2025-03-10/"
ORACLE_Q4_FY2025_RESULTS_URL = "https://www.oracle.com/news/announcement/q4fy25-earnings-release-2025-06-11/"
ORACLE_Q1_FY2026_RESULTS_URL = "https://www.oracle.com/news/announcement/q1fy26-earnings-release-2025-09-09/"
ORACLE_Q2_FY2026_RESULTS_URL = "https://www.oracle.com/news/announcement/q2fy26-earnings-release-2025-12-10/"
ORACLE_Q3_FY2026_RESULTS_URL = "https://www.oracle.com/news/announcement/q3fy26-earnings-release-2026-03-10/"
ORACLE_Q4_FY2026_RESULTS_URL = "https://www.oracle.com/news/announcement/q4fy26-earnings-release-2026-06-10/"
ORACLE_FY2021_Q4_INVESTOR_URL = "https://investor.oracle.com/investor-news/news-details/2021/Oracle-Announces-Fiscal-2021-Fourth-Quarter-and-Fiscal-Full-Year-Financial-Results/default.aspx"
ORACLE_2021_10K_URL = "https://www.sec.gov/Archives/edgar/data/1341439/000156459021033616/orcl-10k_20210531.htm"
ORACLE_2020_10K_URL = "https://www.sec.gov/Archives/edgar/data/1341439/000156459020030125/orcl-10k_20200531.htm"

ORACLE_CLOUD_PRE_IASSAAS_SOURCE_GAP_PERIODS = [
    "FY2017 Q1",
    "FY2017 Q2",
    "FY2017 Q3",
    "FY2017 Q4",
    "FY2018 Q1",
    "FY2018 Q2",
    "FY2018 Q3",
    "FY2018 Q4",
    "FY2019 Q1",
    "FY2019 Q2",
    "FY2019 Q3",
    "FY2019 Q4",
    "FY2020 Q1",
    "FY2020 Q2",
    "FY2020 Q3",
    "FY2020 Q4",
    "FY2021 Q1",
    "FY2021 Q2",
    "FY2021 Q3",
    "FY2021 Q4",
]

ORACLE_CLOUD_PERIODS = [
    {"period": "FY2022 Q1", "period_end": "2021-08-31", "grain": "quarter"},
    {"period": "FY2022 Q2", "period_end": "2021-11-30", "grain": "quarter"},
    {"period": "FY2022 Q3", "period_end": "2022-02-28", "grain": "quarter"},
    {"period": "FY2022 Q4", "period_end": "2022-05-31", "grain": "quarter"},
    {"period": "FY2023 Q1", "period_end": "2022-08-31", "grain": "quarter"},
    {"period": "FY2023 Q2", "period_end": "2022-11-30", "grain": "quarter"},
    {"period": "FY2023 Q3", "period_end": "2023-02-28", "grain": "quarter"},
    {"period": "FY2023 Q4", "period_end": "2023-05-31", "grain": "quarter"},
    {"period": "FY2024 Q1", "period_end": "2023-08-31", "grain": "quarter"},
    {"period": "FY2024 Q2", "period_end": "2023-11-30", "grain": "quarter"},
    {"period": "FY2024 Q3", "period_end": "2024-02-29", "grain": "quarter"},
    {"period": "FY2024 Q4", "period_end": "2024-05-31", "grain": "quarter"},
    {"period": "FY2025 Q1", "period_end": "2024-08-31", "grain": "quarter"},
    {"period": "FY2025 Q2", "period_end": "2024-11-30", "grain": "quarter"},
    {"period": "FY2025 Q3", "period_end": "2025-02-28", "grain": "quarter"},
    {"period": "FY2025 Q4", "period_end": "2025-05-31", "grain": "quarter"},
    {"period": "FY2026 Q1", "period_end": "2025-08-31", "grain": "quarter"},
    {"period": "FY2026 Q2", "period_end": "2025-11-30", "grain": "quarter"},
    {"period": "FY2026 Q3", "period_end": "2026-02-28", "grain": "quarter"},
    {"period": "FY2026 Q4", "period_end": "2026-05-31", "grain": "quarter"},
]

ORACLE_CLOUD_METRICS = {
    "cloud_revenue": {"FY2022 Q1": 2.5, "FY2022 Q2": 2.7, "FY2022 Q3": 2.8, "FY2022 Q4": 2.9, "FY2023 Q1": 3.6, "FY2023 Q2": 3.8, "FY2023 Q3": 4.1, "FY2023 Q4": 4.4, "FY2024 Q1": 4.6, "FY2024 Q2": 4.8, "FY2024 Q3": 5.1, "FY2024 Q4": 5.3, "FY2025 Q1": 5.6, "FY2025 Q2": 5.9, "FY2025 Q3": 6.2, "FY2025 Q4": 6.7, "FY2026 Q1": 7.2, "FY2026 Q2": 8.0, "FY2026 Q3": 8.9, "FY2026 Q4": 9.9},
    "cloud_revenue_growth_yoy": {"FY2022 Q2": 22, "FY2022 Q3": 24, "FY2022 Q4": 19, "FY2023 Q1": 45, "FY2023 Q2": 43, "FY2023 Q3": 45, "FY2023 Q4": 54, "FY2024 Q1": 30, "FY2024 Q2": 25, "FY2024 Q3": 25, "FY2024 Q4": 20, "FY2025 Q1": 21, "FY2025 Q2": 24, "FY2025 Q3": 23, "FY2025 Q4": 27, "FY2026 Q1": 28, "FY2026 Q2": 34, "FY2026 Q3": 44, "FY2026 Q4": 47},
    "cloud_infrastructure_revenue": {"FY2023 Q1": 0.9, "FY2023 Q2": 1.0, "FY2023 Q3": 1.2, "FY2023 Q4": 1.4, "FY2024 Q1": 1.5, "FY2024 Q2": 1.6, "FY2024 Q3": 1.8, "FY2024 Q4": 2.0, "FY2025 Q1": 2.2, "FY2025 Q2": 2.4, "FY2025 Q3": 2.7, "FY2025 Q4": 3.0, "FY2026 Q1": 3.3, "FY2026 Q2": 4.1, "FY2026 Q3": 4.9, "FY2026 Q4": 5.8},
    "cloud_infrastructure_revenue_growth_yoy": {"FY2023 Q1": 52, "FY2023 Q2": 53, "FY2023 Q3": 55, "FY2023 Q4": 76, "FY2024 Q1": 66, "FY2024 Q2": 52, "FY2024 Q3": 49, "FY2024 Q4": 42, "FY2025 Q1": 45, "FY2025 Q2": 52, "FY2025 Q3": 49, "FY2025 Q4": 52, "FY2026 Q1": 55, "FY2026 Q2": 68, "FY2026 Q3": 84, "FY2026 Q4": 93},
    "cloud_application_revenue": {"FY2023 Q1": 2.7, "FY2023 Q2": 2.8, "FY2023 Q3": 2.9, "FY2023 Q4": 3.0, "FY2024 Q1": 3.1, "FY2024 Q2": 3.2, "FY2024 Q3": 3.3, "FY2024 Q4": 3.3, "FY2025 Q1": 3.5, "FY2025 Q2": 3.5, "FY2025 Q3": 3.6, "FY2025 Q4": 3.7, "FY2026 Q1": 3.8, "FY2026 Q2": 3.9, "FY2026 Q3": 4.0, "FY2026 Q4": 4.1},
    "cloud_application_revenue_growth_yoy": {"FY2023 Q1": 43, "FY2023 Q2": 40, "FY2023 Q3": 42, "FY2023 Q4": 45, "FY2024 Q1": 17, "FY2024 Q2": 15, "FY2024 Q3": 14, "FY2024 Q4": 10, "FY2025 Q1": 10, "FY2025 Q2": 10, "FY2025 Q3": 9, "FY2025 Q4": 12, "FY2026 Q1": 11, "FY2026 Q2": 11, "FY2026 Q3": 13, "FY2026 Q4": 10},
}

ORACLE_CLOUD_SOURCE_BY_PERIOD = {
    "FY2022 Q1": {
        "label": "Oracle FY2022 Q1 earnings release",
        "url": ORACLE_Q1_FY2022_RESULTS_URL,
        "type": "official_quarterly_earnings_release",
        "evidence": "Oracle FY2022 Q1 release reports IaaS plus SaaS cloud revenue totaled 2.5 billion USD, or 25% of quarterly revenue. It does not disclose same-table IaaS/SaaS absolute revenue or a total cloud revenue growth percentage for this quarter, so those are not estimated.",
    },
    "FY2022 Q2": {
        "label": "Oracle FY2022 Q2 earnings release",
        "url": ORACLE_Q2_FY2022_RESULTS_URL,
        "type": "official_quarterly_earnings_release",
        "evidence": "Oracle FY2022 Q2 release reports Total Cloud Revenue (IaaS plus SaaS) 2.7 billion USD, up 22%. It does not disclose same-table IaaS/SaaS absolute revenue, so split metrics are not estimated.",
    },
    "FY2022 Q3": {
        "label": "Oracle FY2022 Q3 earnings release",
        "url": ORACLE_Q3_FY2022_RESULTS_URL,
        "type": "official_quarterly_earnings_release",
        "evidence": "Oracle FY2022 Q3 release reports Total Cloud Revenue (IaaS plus SaaS) 2.8 billion USD, up 24%. It does not disclose same-table IaaS/SaaS absolute revenue, so split metrics are not estimated.",
    },
    "FY2022 Q4": {
        "label": "Oracle FY2022 Q4 earnings release",
        "url": ORACLE_Q4_FY2022_RESULTS_URL,
        "type": "official_quarterly_earnings_release",
        "evidence": "Oracle FY2022 Q4 release reports Total Q4 Cloud Revenue (IaaS plus SaaS) 2.9 billion USD, up 19%. It discloses Infrastructure Cloud Revenue growth but not same-table IaaS/SaaS absolute revenue, so split metrics are not estimated.",
    },
    "FY2023 Q1": {
        "label": "Oracle FY2023 Q1 earnings release",
        "url": ORACLE_Q1_FY2023_RESULTS_URL,
        "type": "official_quarterly_earnings_release",
        "evidence": "Oracle FY2023 Q1 release reports Cloud Revenue (IaaS plus SaaS) 3.6 billion USD up 45%, Cloud Infrastructure (IaaS) revenue 0.9 billion USD up 52%, and Cloud Application (SaaS) revenue 2.7 billion USD up 43%. The release also states Cerner contributed 1.4 billion USD to total revenue in the first quarter.",
    },
    "FY2023 Q2": {
        "label": "Oracle FY2023 Q2 earnings release",
        "url": ORACLE_Q2_FY2023_RESULTS_URL,
        "type": "official_quarterly_earnings_release",
        "evidence": "Oracle FY2023 Q2 release reports Cloud Revenue (IaaS plus SaaS) 3.8 billion USD up 43%, Cloud Infrastructure (IaaS) revenue 1.0 billion USD up 53%, and Cloud Application (SaaS) revenue 2.8 billion USD up 40%. The release also states Cerner contributed 1.5 billion USD to total revenue in the second quarter.",
    },
    "FY2023 Q3": {
        "label": "Oracle FY2023 Q3 earnings release",
        "url": ORACLE_Q3_FY2023_RESULTS_URL,
        "type": "official_quarterly_earnings_release",
        "evidence": "Oracle FY2023 Q3 release reports Cloud Revenue (IaaS plus SaaS) 4.1 billion USD up 45%, Cloud Infrastructure (IaaS) revenue 1.2 billion USD up 55%, and Cloud Application (SaaS) revenue 2.9 billion USD up 42%. The release also states Cerner contributed 1.5 billion USD to total revenue in the third quarter.",
    },
    "FY2023 Q4": {
        "label": "Oracle FY2023 Q4 earnings release",
        "url": ORACLE_Q4_FY2023_RESULTS_URL,
        "type": "official_quarterly_earnings_release",
        "evidence": "Oracle FY2023 Q4 release reports Cloud Revenue (IaaS plus SaaS) 4.4 billion USD up 54%, Cloud Infrastructure (IaaS) revenue 1.4 billion USD up 76%, and Cloud Application (SaaS) revenue 3.0 billion USD up 45%. The release also states Cerner contributed 1.5 billion USD to total revenue in the fourth quarter.",
    },
    "FY2024 Q1": {
        "label": "Oracle FY2024 Q1 earnings release",
        "url": ORACLE_Q1_FY2024_RESULTS_URL,
        "type": "official_quarterly_earnings_release",
        "evidence": "Oracle FY2024 Q1 release reports Cloud Revenue (IaaS plus SaaS) 4.6 billion USD up 30%, Cloud Infrastructure (IaaS) revenue 1.5 billion USD up 66%, and Cloud Application (SaaS) revenue 3.1 billion USD up 17%.",
    },
    "FY2024 Q2": {
        "label": "Oracle FY2024 Q2 earnings release",
        "url": ORACLE_Q2_FY2024_RESULTS_URL,
        "type": "official_quarterly_earnings_release",
        "evidence": "Oracle FY2024 Q2 release reports Cloud Revenue (IaaS plus SaaS) 4.8 billion USD up 25%, Cloud Infrastructure (IaaS) revenue 1.6 billion USD up 52%, and Cloud Application (SaaS) revenue 3.2 billion USD up 15%.",
    },
    "FY2024 Q3": {
        "label": "Oracle FY2024 Q3 earnings release",
        "url": ORACLE_Q3_FY2024_RESULTS_URL,
        "type": "official_quarterly_earnings_release",
        "evidence": "Oracle FY2024 Q3 release reports Cloud Revenue (IaaS plus SaaS) 5.1 billion USD up 25%, Cloud Infrastructure (IaaS) revenue 1.8 billion USD up 49%, and Cloud Application (SaaS) revenue 3.3 billion USD up 14%.",
    },
    "FY2024 Q4": {
        "label": "Oracle FY2024 Q4 earnings release",
        "url": ORACLE_Q4_FY2024_RESULTS_URL,
        "type": "official_quarterly_earnings_release",
        "evidence": "Oracle FY2024 Q4 release reports Cloud Revenue (IaaS plus SaaS) 5.3 billion USD up 20%, Cloud Infrastructure (IaaS) revenue 2.0 billion USD up 42%, and Cloud Application (SaaS) revenue 3.3 billion USD up 10%.",
    },
    "FY2025 Q1": {
        "label": "Oracle FY2025 Q1 earnings release",
        "url": ORACLE_Q1_FY2025_RESULTS_URL,
        "type": "official_quarterly_earnings_release",
        "evidence": "Oracle FY2025 Q1 release reports Cloud Revenue (IaaS plus SaaS) 5.6 billion USD up 21%, Cloud Infrastructure (IaaS) revenue 2.2 billion USD up 45%, and Cloud Application (SaaS) revenue 3.5 billion USD up 10%.",
    },
    "FY2025 Q2": {
        "label": "Oracle FY2025 Q2 earnings release",
        "url": ORACLE_Q2_FY2025_RESULTS_URL,
        "type": "official_quarterly_earnings_release",
        "evidence": "Oracle FY2025 Q2 release reports Cloud Revenue (IaaS plus SaaS) 5.9 billion USD up 24%, Cloud Infrastructure (IaaS) revenue 2.4 billion USD up 52%, and Cloud Application (SaaS) revenue 3.5 billion USD up 10%.",
    },
    "FY2025 Q3": {
        "label": "Oracle FY2025 Q3 earnings release",
        "url": ORACLE_Q3_FY2025_RESULTS_URL,
        "type": "official_quarterly_earnings_release",
        "evidence": "Oracle FY2025 Q3 release reports Cloud Revenue (IaaS plus SaaS) 6.2 billion USD up 23%, Cloud Infrastructure (IaaS) revenue 2.7 billion USD up 49%, and Cloud Application (SaaS) revenue 3.6 billion USD up 9%.",
    },
    "FY2025 Q4": {
        "label": "Oracle FY2025 Q4 earnings release",
        "url": ORACLE_Q4_FY2025_RESULTS_URL,
        "type": "official_quarterly_earnings_release",
        "evidence": "Oracle FY2025 Q4 release reports Cloud Revenue 6.7 billion USD up 27%, Cloud Infrastructure revenue 3.0 billion USD up 52%, and Cloud Application revenue 3.7 billion USD up 12%.",
    },
    "FY2026 Q1": {
        "label": "Oracle FY2026 Q1 earnings release",
        "url": ORACLE_Q1_FY2026_RESULTS_URL,
        "type": "official_quarterly_earnings_release",
        "evidence": "Oracle FY2026 Q1 release reports Cloud Revenue 7.2 billion USD up 28%, Cloud Infrastructure revenue 3.3 billion USD up 55%, and Cloud Application revenue 3.8 billion USD up 11%.",
    },
    "FY2026 Q2": {
        "label": "Oracle FY2026 Q2 earnings release",
        "url": ORACLE_Q2_FY2026_RESULTS_URL,
        "type": "official_quarterly_earnings_release",
        "evidence": "Oracle FY2026 Q2 release reports Cloud Revenue 8.0 billion USD up 34%, Cloud Infrastructure revenue 4.1 billion USD up 68%, and Cloud Application revenue 3.9 billion USD up 11%.",
    },
    "FY2026 Q3": {
        "label": "Oracle FY2026 Q3 earnings release",
        "url": ORACLE_Q3_FY2026_RESULTS_URL,
        "type": "official_quarterly_earnings_release",
        "evidence": "Oracle FY2026 Q3 release reports Cloud Revenue 8.9 billion USD up 44%, Cloud Infrastructure revenue 4.9 billion USD up 84%, and Cloud Application revenue 4.0 billion USD up 13%.",
    },
    "FY2026 Q4": {
        "label": "Oracle FY2026 Q4 earnings release",
        "url": ORACLE_Q4_FY2026_RESULTS_URL,
        "type": "official_quarterly_earnings_release",
        "evidence": "Oracle FY2026 Q4 release reports Total Cloud Revenues 9.9 billion USD up 47%, Cloud Infrastructure revenue 5.8 billion USD up 93%, and Cloud Applications revenue 4.1 billion USD up 10%.",
    },
}

TENCENT_QUARTERLY_RESULTS_URL = "https://www.tencent.com/en-us/investors/quarter-result.html"
TENCENT_FINANCIAL_NEWS_URL = "https://www.tencent.com/en-us/investors/financial-news.html"
TENCENT_Q4_2018_RESULTS_URL = "https://static.www.tencent.com/storage/uploads/2019/11/09/07a7fcd8a2494c502a6edd21d4b8eb66.pdf"
TENCENT_Q1_2019_RESULTS_URL = "https://static.www.tencent.com/storage/uploads/2019/11/09/996a00a688b56c13c220845ed6f63be9.pdf"
TENCENT_Q2_2019_RESULTS_URL = "https://static.www.tencent.com/storage/uploads/2019/11/09/77248c95e2a3295269c2875c8c908f86.pdf"
TENCENT_Q3_2019_RESULTS_URL = "https://static.www.tencent.com/uploads/2019/11/13/8b98062831f2f28d9cb4616222a4d3c3.pdf"
TENCENT_Q4_2019_RESULTS_URL = "https://static.www.tencent.com/uploads/2020/03/18/7fceaf3d1b264debc61342fc1a27dd18.pdf"
TENCENT_Q1_2020_RESULTS_URL = "https://static.www.tencent.com/uploads/2020/05/18/13009f73ecab16501df9062e43e47e67.pdf"
TENCENT_Q2_2020_RESULTS_URL = "https://static.www.tencent.com/uploads/2020/08/12/00e999c23314aa085c0b48c533d4d393.pdf"
TENCENT_Q3_2020_RESULTS_URL = "https://static.www.tencent.com/uploads/2020/11/12/4c2090d5f6f00fd90ddc9bbd9a1415d1.pdf"
TENCENT_Q4_2020_RESULTS_URL = "https://static.www.tencent.com/uploads/2021/03/24/b83f5784d0579b51cf8515cf560b4256.pdf"
TENCENT_Q1_2021_RESULTS_URL = "https://static.www.tencent.com/uploads/2021/05/20/269facaab659f690ab4e262b4c0bd01d.pdf"
TENCENT_Q2_2021_RESULTS_URL = "https://static.www.tencent.com/uploads/2021/08/18/236f212d95d7402bacdbdf904a6b2b65.pdf"
TENCENT_Q3_2021_RESULTS_URL = "https://static.www.tencent.com/uploads/2021/11/10/57d32da50c1d7abe221d7f9ca9ec3dcb.pdf"
TENCENT_Q4_2021_RESULTS_URL = "https://static.www.tencent.com/uploads/2022/03/23/b107f5a267bf6a7d00fd8373cd841558.pdf"
TENCENT_Q1_2022_RESULTS_URL = "https://static.www.tencent.com/uploads/2022/05/18/f403326038a641b20465a17eff3567ce.pdf"
TENCENT_Q2_2022_RESULTS_URL = "https://static.www.tencent.com/uploads/2022/08/17/a1a39b69021bb7e4bf7f8dd238070079.pdf"
TENCENT_Q3_2022_RESULTS_URL = "https://static.www.tencent.com/uploads/2022/11/16/33aad36dea97848eb75aa988d785e9f8.pdf"
TENCENT_Q4_2022_RESULTS_URL = "https://static.www.tencent.com/uploads/2023/03/22/3b5431187fdc8a053d9fee3a4c031aa6.pdf"
TENCENT_Q1_2023_RESULTS_URL = "https://static.www.tencent.com/uploads/2023/05/17/7b07c1a2b0befc1a89a6fc4219ed6cae.pdf"
TENCENT_Q2_2023_RESULTS_URL = "https://static.www.tencent.com/uploads/2023/08/16/f283f2dfd05151ae7659e7a8e3d667ef.pdf"
TENCENT_Q3_2023_RESULTS_URL = "https://static.www.tencent.com/uploads/2023/11/15/9e4da3187104bbdf04e2cbe491b75147.pdf"
TENCENT_Q4_2023_RESULTS_URL = "https://static.www.tencent.com/uploads/2024/03/20/fe50310bf15caaab4b05dd9e8e49d316.pdf"
TENCENT_Q1_2024_RESULTS_URL = "https://static.www.tencent.com/uploads/2024/05/14/207c400f3d6e2d9894c0b9b778507cf1.pdf"
TENCENT_Q2_2024_RESULTS_URL = "https://static.www.tencent.com/uploads/2024/08/14/027889ef78b4ed2b83337dd4a7c2ffef.pdf"
TENCENT_Q3_2024_RESULTS_URL = "https://static.www.tencent.com/uploads/2024/11/13/fc23e847ab5be9093587be6b7b01c115.pdf"
TENCENT_Q4_2024_RESULTS_URL = "https://static.www.tencent.com/uploads/2025/03/19/81cb1f36bec218d27d6e0b24eec012b6.pdf"
TENCENT_Q1_2025_RESULTS_URL = "https://static.www.tencent.com/uploads/2025/05/16/2af4e73edd208df236dadd8b9df89fc4.pdf"
TENCENT_Q2_2025_RESULTS_URL = "https://static.www.tencent.com/uploads/2025/08/13/56af6c5c98acdc7bd757a7bd208d8189.pdf"
TENCENT_Q3_2025_RESULTS_URL = "https://static.www.tencent.com/uploads/2025/11/13/a33b6f19738615834787623f17d20ba3.pdf"
TENCENT_Q4_2025_RESULTS_URL = "https://static.www.tencent.com/uploads/2026/03/18/e6a646796d0d869acc76271c9ee1a6a5.pdf"
TENCENT_Q1_2026_RESULTS_URL = "https://static.www.tencent.com/uploads/2026/05/13/47382ae415a209fd161bc19a1f9b3704.pdf"

TENCENT_FBS_PERIOD_END_BY_PERIOD = {
    "Q1 2019": "2019-03-31",
    "Q2 2019": "2019-06-30",
    "Q3 2019": "2019-09-30",
    "Q4 2019": "2019-12-31",
    "Q1 2020": "2020-03-31",
    "Q2 2020": "2020-06-30",
    "Q3 2020": "2020-09-30",
    "Q4 2020": "2020-12-31",
    "Q1 2021": "2021-03-31",
    "Q2 2021": "2021-06-30",
    "Q3 2021": "2021-09-30",
    "Q4 2021": "2021-12-31",
    "Q1 2022": "2022-03-31",
    "Q2 2022": "2022-06-30",
    "Q3 2022": "2022-09-30",
    "Q4 2022": "2022-12-31",
    "Q1 2023": "2023-03-31",
    "Q2 2023": "2023-06-30",
    "Q3 2023": "2023-09-30",
    "Q4 2023": "2023-12-31",
    "Q1 2024": "2024-03-31",
    "Q2 2024": "2024-06-30",
    "Q3 2024": "2024-09-30",
    "Q4 2024": "2024-12-31",
    "Q1 2025": "2025-03-31",
    "Q2 2025": "2025-06-30",
    "Q3 2025": "2025-09-30",
    "Q4 2025": "2025-12-31",
    "Q1 2026": "2026-03-31",
}

TENCENT_FBS_SOURCE_URL_BY_PERIOD = {
    "Q1 2019": TENCENT_Q1_2019_RESULTS_URL,
    "Q2 2019": TENCENT_Q2_2019_RESULTS_URL,
    "Q3 2019": TENCENT_Q3_2019_RESULTS_URL,
    "Q4 2019": TENCENT_Q4_2019_RESULTS_URL,
    "Q1 2020": TENCENT_Q1_2020_RESULTS_URL,
    "Q2 2020": TENCENT_Q2_2020_RESULTS_URL,
    "Q3 2020": TENCENT_Q3_2020_RESULTS_URL,
    "Q4 2020": TENCENT_Q4_2020_RESULTS_URL,
    "Q1 2021": TENCENT_Q1_2021_RESULTS_URL,
    "Q2 2021": TENCENT_Q2_2021_RESULTS_URL,
    "Q3 2021": TENCENT_Q3_2021_RESULTS_URL,
    "Q4 2021": TENCENT_Q4_2021_RESULTS_URL,
    "Q1 2022": TENCENT_Q1_2022_RESULTS_URL,
    "Q2 2022": TENCENT_Q2_2022_RESULTS_URL,
    "Q3 2022": TENCENT_Q3_2022_RESULTS_URL,
    "Q4 2022": TENCENT_Q4_2022_RESULTS_URL,
    "Q1 2023": TENCENT_Q1_2023_RESULTS_URL,
    "Q2 2023": TENCENT_Q2_2023_RESULTS_URL,
    "Q3 2023": TENCENT_Q3_2023_RESULTS_URL,
    "Q4 2023": TENCENT_Q4_2023_RESULTS_URL,
    "Q1 2024": TENCENT_Q1_2024_RESULTS_URL,
    "Q2 2024": TENCENT_Q2_2024_RESULTS_URL,
    "Q3 2024": TENCENT_Q3_2024_RESULTS_URL,
    "Q4 2024": TENCENT_Q4_2024_RESULTS_URL,
    "Q1 2025": TENCENT_Q1_2025_RESULTS_URL,
    "Q2 2025": TENCENT_Q2_2025_RESULTS_URL,
    "Q3 2025": TENCENT_Q3_2025_RESULTS_URL,
    "Q4 2025": TENCENT_Q4_2025_RESULTS_URL,
    "Q1 2026": TENCENT_Q1_2026_RESULTS_URL,
}

TENCENT_FBS_PERIODS = [
    {"period": period, "period_end": period_end, "grain": "quarter"}
    for period, period_end in TENCENT_FBS_PERIOD_END_BY_PERIOD.items()
]

TENCENT_FBS_METRICS = {
    "fintech_business_services_revenue": {
        "Q1 2019": 21789,
        "Q2 2019": 22888,
        "Q3 2019": 26758,
        "Q4 2019": 29920,
        "Q1 2020": 26475,
        "Q2 2020": 29862,
        "Q3 2020": 33255,
        "Q4 2020": 38494,
        "Q1 2021": 39028,
        "Q2 2021": 41892,
        "Q3 2021": 43317,
        "Q4 2021": 47958,
        "Q1 2022": 42768,
        "Q2 2022": 42208,
        "Q3 2022": 44844,
        "Q4 2022": 47244,
        "Q1 2023": 48701,
        "Q2 2023": 48635,
        "Q3 2023": 52048,
        "Q4 2023": 54379,
        "Q1 2024": 52302,
        "Q2 2024": 50440,
        "Q3 2024": 53089,
        "Q4 2024": 56125,
        "Q1 2025": 54907,
        "Q2 2025": 55536,
        "Q3 2025": 58174,
        "Q4 2025": 60818,
        "Q1 2026": 59885,
    },
    "fintech_business_services_revenue_growth_yoy": {
        "Q1 2019": 44,
        "Q2 2019": 37,
        "Q3 2019": 36,
        "Q4 2019": 39,
        "Q1 2020": 22,
        "Q2 2020": 30,
        "Q3 2020": 24,
        "Q4 2020": 29,
        "Q1 2021": 47,
        "Q2 2021": 40,
        "Q3 2021": 30,
        "Q4 2021": 25,
        "Q1 2022": 10,
        "Q2 2022": 1,
        "Q3 2022": 4,
        "Q4 2022": -1,
        "Q1 2023": 14,
        "Q2 2023": 15,
        "Q3 2023": 16,
        "Q4 2023": 15,
        "Q1 2024": 7,
        "Q2 2024": 4,
        "Q3 2024": 2,
        "Q4 2024": 3,
        "Q1 2025": 5,
        "Q2 2025": 10,
        "Q3 2025": 10,
        "Q4 2025": 8,
        "Q1 2026": 9,
    },
}

TENCENT_FBS_SOURCE_BY_PERIOD = {
    period: {
        "label": f"Tencent {period[-4:]} {period[:2]} earnings release",
        "url": TENCENT_FBS_SOURCE_URL_BY_PERIOD[period],
        "type": "official_quarterly_earnings_release",
        "evidence": (
            f"Tencent {period} earnings release reports FinTech and Business Services revenue of "
            f"RMB{TENCENT_FBS_METRICS['fintech_business_services_revenue'][period]:,} million and "
            f"{TENCENT_FBS_METRICS['fintech_business_services_revenue_growth_yoy'][period]}% year-on-year growth."
        ),
    }
    for period in TENCENT_FBS_PERIOD_END_BY_PERIOD
}

TENCENT_FBS_PRE_DISCLOSURE_SOURCE_GAP_PERIODS = [
    "Q2 2016",
    "Q3 2016",
    "Q4 2016",
    "Q1 2017",
    "Q2 2017",
    "Q3 2017",
    "Q4 2017",
    "Q1 2018",
    "Q2 2018",
    "Q3 2018",
    "Q4 2018",
]

TENCENT_FBS_PRE_DISCLOSURE_SOURCE_GAP_CONFIRMATIONS = [
    {
        "subject": "Tencent Cloud / Tencent FBS proxy",
        "period": period,
        "metric_key": "fintech_business_services_disclosure_status",
        "source_label": "Tencent Q1 2019 earnings release",
        "source_url": TENCENT_Q1_2019_RESULTS_URL,
        "evidence": (
            "Tencent Q1 2019 earnings release states that the company began separately disclosing "
            "FinTech and Business Services as a new segment in that quarter. Earlier periods therefore "
            f"do not have a comparable public FBS proxy line for {period}; older non-FBS revenue segments are not carried forward."
        ),
        "verification_method": "official_segment_disclosure_inception_gap_check",
        "verification_sources": [
            {
                "label": "Tencent financial news earnings releases index",
                "url": TENCENT_FINANCIAL_NEWS_URL,
                "type": "official_earnings_releases_index",
                "evidence": "Tencent official financial news page lists the historical earnings release PDFs and shows the relevant pre-2019 and 2019 releases.",
            },
            {
                "label": "Tencent Q1 2019 earnings release",
                "url": TENCENT_Q1_2019_RESULTS_URL,
                "type": "official_quarterly_earnings_release",
                "evidence": "The Q1 2019 release says Tencent began separately disclosing FinTech and Business Services as a new segment in its financial reports.",
            },
            {
                "label": "Tencent 2018 fourth quarter and annual results",
                "url": TENCENT_Q4_2018_RESULTS_URL,
                "type": "official_annual_and_quarterly_earnings_release",
                "evidence": "The FY2018/Q4 2018 release predates the separate FBS segment disclosure and does not provide a comparable FinTech and Business Services quarterly proxy line.",
            },
        ],
        "verification_note": "Tencent FBS proxy coverage starts in Q1 2019. Q2 2016-Q4 2018 are disclosure-boundary gaps, not missing values to estimate; source-gap rows do not count toward the 40-quarter cloud coverage gate.",
        "append_if_missing": True,
    }
    for period in TENCENT_FBS_PRE_DISCLOSURE_SOURCE_GAP_PERIODS
]

ALIBABA_QUARTERLY_RESULTS_URL = "https://www.alibabagroup.com/en-US/ir-financial-reports-quarterly-results"
ALIBABA_JUNE_QTR_2025_DOCUMENT_URL = "https://www.alibabagroup.com/en-US/document-1897714462505304064"
ALIBABA_JUNE_QTR_2025_RESULTS_URL = "https://data.alibabagroup.com/ecms-files/1532295521/d09dd487-1a87-4e17-aa5d-9eb4da7eb56b/Alibaba%20Group%20Announces%20June%20Quarter%202025%20Results.pdf"
ALIBABA_SEPTEMBER_QTR_2025_DOCUMENT_URL = "https://www.alibabagroup.com/en-US/document-1929990445136347136"
ALIBABA_SEPTEMBER_QTR_2025_RESULTS_URL = "https://data.alibabagroup.com/ecms-files/1532295521/96ebbe16-9309-479f-b628-48b0ccc31b9c/Alibaba%20Group%20Announces%20September%20Quarter%202025%20Results%20and%20Interim%20Results%20for%20the%20Six%20Months%20Ended%20September%2030%2C%202025.pdf"
ALIBABA_DECEMBER_QTR_2025_DOCUMENT_URL = "https://www.alibabagroup.com/en-US/document-1971014025827319808"
ALIBABA_DECEMBER_QTR_2025_RESULTS_URL = "https://data.alibabagroup.com/ecms-files/1532295521/e48e70a1-e5c8-40ac-bdd2-951ebcb36946/Alibaba%20Group%20Announces%20December%20Quarter%202025%20Results.pdf"
ALIBABA_MARCH_QTR_2026_DOCUMENT_URL = "https://www.alibabagroup.com/en-US/document-1991237455038119936"
ALIBABA_MARCH_QTR_2026_RESULTS_URL = "https://data.alibabagroup.com/ecms-files/1532295521/5b1cb883-8d00-4237-a148-6631cc12a5d2/Alibaba%20Group%20Announces%20March%20Quarter%202026%20and%20Fiscal%20Year%202026%20Results.pdf"
ALIBABA_JUNE_QTR_2024_DOCUMENT_URL = "https://www.alibabagroup.com/document-1761110461375315968"
ALIBABA_JUNE_QTR_2024_RESULTS_URL = "https://www.sec.gov/Archives/edgar/data/1577552/000110465924090102/tm2421791d1_ex99-1.htm"
ALIBABA_SEPTEMBER_QTR_2024_DOCUMENT_URL = ALIBABA_QUARTERLY_RESULTS_URL
ALIBABA_SEPTEMBER_QTR_2024_RESULTS_URL = "https://www.sec.gov/Archives/edgar/data/1577552/000110465924119688/tm2428590d1_ex99-1.htm"
ALIBABA_DECEMBER_QTR_2024_DOCUMENT_URL = ALIBABA_QUARTERLY_RESULTS_URL
ALIBABA_DECEMBER_QTR_2024_RESULTS_URL = "https://www.sec.gov/Archives/edgar/data/1577552/000110465925015648/tm257183d1_ex99-1.htm"
ALIBABA_MARCH_QTR_2025_DOCUMENT_URL = "https://data.alibabagroup.com/ecms-files/1532295521/83f92d1d-d36f-4ecd-a56c-2d3c59cb251a/Alibaba%20Group%20Announces%20March%20Quarter%202025%20and%20Fiscal%20Year%202025%20Results.pdf"
ALIBABA_MARCH_QTR_2025_RESULTS_URL = "https://www.sec.gov/Archives/edgar/data/1577552/000110465925049400/tm2515233d1_ex99-1.htm"
ALIBABA_JUNE_QTR_2023_DOCUMENT_URL = ALIBABA_QUARTERLY_RESULTS_URL
ALIBABA_JUNE_QTR_2023_RESULTS_URL = "https://www.sec.gov/Archives/edgar/data/1577552/000110465923089768/tm2323406d1_ex99-1.htm"
ALIBABA_SEPTEMBER_QTR_2023_DOCUMENT_URL = ALIBABA_QUARTERLY_RESULTS_URL
ALIBABA_SEPTEMBER_QTR_2023_RESULTS_URL = "https://www.sec.gov/Archives/edgar/data/1577552/000110465923119081/tm2330915d1_ex99-1.htm"
ALIBABA_DECEMBER_QTR_2023_DOCUMENT_URL = "https://www.alibabagroup.com/en-US/document-1691989841455087616"
ALIBABA_DECEMBER_QTR_2023_RESULTS_URL = "https://www.sec.gov/Archives/edgar/data/1577552/000110465924011604/tm245446d1_ex99-1.htm"
ALIBABA_MARCH_QTR_2024_DOCUMENT_URL = "https://www.sec.gov/Archives/edgar/data/1577552/000110465924061145/tm2414429d1_ex99-1.htm"
ALIBABA_MARCH_QTR_2024_RESULTS_URL = "https://www.sec.gov/Archives/edgar/data/1577552/000110465924061145/tm2414429d1_ex99-1.htm"
ALIBABA_JUNE_QTR_2022_DOCUMENT_URL = ALIBABA_QUARTERLY_RESULTS_URL
ALIBABA_JUNE_QTR_2022_RESULTS_URL = "https://www.sec.gov/Archives/edgar/data/1577552/000110465922086110/tm2222585d1_ex99-1.htm"
ALIBABA_SEPTEMBER_QTR_2022_DOCUMENT_URL = ALIBABA_QUARTERLY_RESULTS_URL
ALIBABA_SEPTEMBER_QTR_2022_RESULTS_URL = "https://www.sec.gov/Archives/edgar/data/1577552/000110465922119884/tm2230824d3_ex99-1.htm"
ALIBABA_DECEMBER_QTR_2022_DOCUMENT_URL = ALIBABA_QUARTERLY_RESULTS_URL
ALIBABA_DECEMBER_QTR_2022_RESULTS_URL = "https://www.sec.gov/Archives/edgar/data/1577552/000110465923024752/tm237669d2_ex99-1.htm"
ALIBABA_MARCH_QTR_2023_DOCUMENT_URL = ALIBABA_QUARTERLY_RESULTS_URL
ALIBABA_MARCH_QTR_2023_RESULTS_URL = "https://www.sec.gov/Archives/edgar/data/1577552/000110465923062243/tm2316208d1_ex99-1.htm"
ALIBABA_JUNE_QTR_2021_RESULTS_URL = "https://www.businesswire.com/news/home/20210803005562/en/Alibaba-Group-Announces-June-Quarter-2021-Results"
ALIBABA_SEPTEMBER_QTR_2021_RESULTS_URL = "https://www.sec.gov/Archives/edgar/data/1577552/000110465921141204/tm2133400d1_ex99-1.htm"
ALIBABA_DECEMBER_QTR_2021_RESULTS_URL = "https://www.businesswire.com/news/home/20220223006445/en/Alibaba-Group-Announces-December-Quarter-2021-Results"
ALIBABA_MARCH_QTR_2022_RESULTS_URL = "https://www.sec.gov/Archives/edgar/data/1577552/000110465922065269/tm2217018d1_ex99-1.htm"

ALIBABA_CLOUD_PRE_RESTATED_CIG_SOURCE_GAP_PERIODS = [
    "FY2017 Q1",
    "FY2017 Q2",
    "FY2017 Q3",
    "FY2017 Q4",
    "FY2018 Q1",
    "FY2018 Q2",
    "FY2018 Q3",
    "FY2018 Q4",
    "FY2019 Q1",
    "FY2019 Q2",
    "FY2019 Q3",
    "FY2019 Q4",
    "FY2020 Q1",
    "FY2020 Q2",
    "FY2020 Q3",
    "FY2020 Q4",
    "FY2021 Q1",
    "FY2021 Q2",
    "FY2021 Q3",
    "FY2021 Q4",
    "FY2022 Q1",
    "FY2022 Q2",
    "FY2022 Q3",
    "FY2022 Q4",
]

ALIBABA_CLOUD_PERIODS = [
    {"period": "FY2022 Q1", "period_end": "2021-06-30", "grain": "quarter"},
    {"period": "FY2022 Q2", "period_end": "2021-09-30", "grain": "quarter"},
    {"period": "FY2022 Q3", "period_end": "2021-12-31", "grain": "quarter"},
    {"period": "FY2022 Q4", "period_end": "2022-03-31", "grain": "quarter"},
    {"period": "FY2023 Q1", "period_end": "2022-06-30", "grain": "quarter"},
    {"period": "FY2023 Q2", "period_end": "2022-09-30", "grain": "quarter"},
    {"period": "FY2023 Q3", "period_end": "2022-12-31", "grain": "quarter"},
    {"period": "FY2023 Q4", "period_end": "2023-03-31", "grain": "quarter"},
    {"period": "FY2024 Q1", "period_end": "2023-06-30", "grain": "quarter"},
    {"period": "FY2024 Q2", "period_end": "2023-09-30", "grain": "quarter"},
    {"period": "FY2024 Q3", "period_end": "2023-12-31", "grain": "quarter"},
    {"period": "FY2024 Q4", "period_end": "2024-03-31", "grain": "quarter"},
    {"period": "FY2025 Q1", "period_end": "2024-06-30", "grain": "quarter"},
    {"period": "FY2025 Q2", "period_end": "2024-09-30", "grain": "quarter"},
    {"period": "FY2025 Q3", "period_end": "2024-12-31", "grain": "quarter"},
    {"period": "FY2025 Q4", "period_end": "2025-03-31", "grain": "quarter"},
    {"period": "FY2026 Q1", "period_end": "2025-06-30", "grain": "quarter"},
    {"period": "FY2026 Q2", "period_end": "2025-09-30", "grain": "quarter"},
    {"period": "FY2026 Q3", "period_end": "2025-12-31", "grain": "quarter"},
    {"period": "FY2026 Q4", "period_end": "2026-03-31", "grain": "quarter"},
]

ALIBABA_CLOUD_METRICS = {
    "revenue": {
        "FY2023 Q1": 24356,
        "FY2023 Q2": 27035,
        "FY2023 Q3": 27364,
        "FY2023 Q4": 24742,
        "FY2024 Q1": 25065,
        "FY2024 Q2": 27648,
        "FY2024 Q3": 28066,
        "FY2024 Q4": 25595,
        "FY2025 Q1": 26549,
        "FY2025 Q2": 29610,
        "FY2025 Q3": 31742,
        "FY2025 Q4": 30127,
        "FY2026 Q1": 33398,
        "FY2026 Q2": 39824,
        "FY2026 Q3": 43284,
        "FY2026 Q4": 41626,
    },
    "revenue_growth_yoy": {
        "FY2024 Q1": 2.911,
        "FY2024 Q2": 2,
        "FY2024 Q3": 3,
        "FY2024 Q4": 3,
        "FY2025 Q1": 6,
        "FY2025 Q2": 7,
        "FY2025 Q3": 13,
        "FY2025 Q4": 18,
        "FY2026 Q1": 26,
        "FY2026 Q2": 34,
        "FY2026 Q3": 36,
        "FY2026 Q4": 38,
    },
    "adjusted_ebita": {
        "FY2023 Q1": 864,
        "FY2023 Q2": 981,
        "FY2023 Q3": 1269,
        "FY2023 Q4": 987,
        "FY2024 Q1": 916,
        "FY2024 Q2": 1409,
        "FY2024 Q3": 2364,
        "FY2024 Q4": 1432,
        "FY2025 Q1": 2337,
        "FY2025 Q2": 2661,
        "FY2025 Q3": 3138,
        "FY2025 Q4": 2420,
        "FY2026 Q1": 2954,
        "FY2026 Q2": 3604,
        "FY2026 Q3": 3911,
        "FY2026 Q4": 3796,
    },
    "adjusted_ebita_growth_yoy": {
        "FY2024 Q1": 6.019,
        "FY2024 Q2": 44,
        "FY2024 Q3": 86,
        "FY2024 Q4": 45,
        "FY2025 Q1": 155,
        "FY2025 Q2": 89,
        "FY2025 Q3": 33,
        "FY2025 Q4": 69,
        "FY2026 Q1": 26,
        "FY2026 Q2": 35,
        "FY2026 Q3": 25,
        "FY2026 Q4": 57,
    },
}

ALIBABA_LEGACY_CLOUD_SEGMENT_METRICS = {
    "legacy_cloud_segment_revenue_including_dingtalk": {
        "FY2022 Q1": 16051,
        "FY2022 Q2": 20007,
        "FY2022 Q3": 19539,
        "FY2022 Q4": 18971,
    },
    "legacy_cloud_segment_adjusted_ebita_including_dingtalk": {
        "FY2022 Q1": 340,
        "FY2022 Q2": 396,
        "FY2022 Q3": 134,
        "FY2022 Q4": 276,
    },
}

ALIBABA_LEGACY_CLOUD_SEGMENT_SOURCE_BY_PERIOD = {
    "FY2022 Q1": {
        "label": "Alibaba June Quarter 2021 results - legacy Cloud computing segment",
        "url": ALIBABA_JUNE_QTR_2021_RESULTS_URL,
        "type": "official_quarterly_results_legacy_cloud_segment",
        "evidence": "Alibaba June quarter 2021 results report Cloud computing revenue of RMB16,051 million and adjusted EBITA of RMB340 million. Alibaba later stated this FY2022-era Cloud segment comprised Alibaba Cloud and DingTalk, so these values are retained only as legacy non-forecast evidence.",
        "cross_check": {
            "label": "Alibaba September Quarter 2022 results - old Cloud segment boundary",
            "url": ALIBABA_SEPTEMBER_QTR_2022_RESULTS_URL,
            "type": "official_sec_6k_comparative_context",
            "evidence": "Alibaba September quarter 2022 results identify the pre-restatement Cloud segment as comprising Alibaba Cloud and DingTalk, confirming the old segment boundary before DingTalk was reclassified.",
        },
    },
    "FY2022 Q2": {
        "label": "Alibaba September Quarter 2021 results - legacy Cloud computing segment",
        "url": ALIBABA_SEPTEMBER_QTR_2021_RESULTS_URL,
        "type": "official_sec_6k_legacy_cloud_segment",
        "evidence": "Alibaba September quarter 2021 results report Cloud computing revenue of RMB20,007 million and adjusted EBITA of RMB396 million. These values belong to the old Cloud computing segment and are retained only as legacy non-forecast evidence.",
        "cross_check": {
            "label": "Alibaba September Quarter 2022 results - prior-year comparative",
            "url": ALIBABA_SEPTEMBER_QTR_2022_RESULTS_URL,
            "type": "official_sec_6k_prior_year_comparative",
            "evidence": "Alibaba September quarter 2022 results report September quarter 2022 Cloud revenue of RMB20,757 million, up 4% year-over-year, and Cloud adjusted EBITA of RMB434 million compared with RMB396 million in the same quarter of 2021, cross-checking the FY2022 Q2 legacy values.",
        },
    },
    "FY2022 Q3": {
        "label": "Alibaba December Quarter 2021 results - legacy Cloud segment",
        "url": ALIBABA_DECEMBER_QTR_2021_RESULTS_URL,
        "type": "official_quarterly_results_legacy_cloud_segment",
        "evidence": "Alibaba December quarter 2021 results report Cloud revenue after inter-segment elimination of RMB19,539 million and Cloud segment adjusted EBITA of RMB134 million. These values are retained only as legacy non-forecast evidence.",
        "cross_check": {
            "label": "Alibaba December Quarter 2022 results - old Cloud segment boundary",
            "url": ALIBABA_DECEMBER_QTR_2022_RESULTS_URL,
            "type": "official_sec_6k_comparative_context",
            "evidence": "Alibaba December quarter 2022 results remain on the pre-restatement Cloud segment presentation before the later DingTalk reclassification, supporting the legacy segment boundary check.",
        },
    },
    "FY2022 Q4": {
        "label": "Alibaba March Quarter 2022 and Fiscal Year 2022 results - legacy Cloud segment",
        "url": ALIBABA_MARCH_QTR_2022_RESULTS_URL,
        "type": "official_sec_6k_legacy_cloud_segment",
        "evidence": "Alibaba March quarter 2022 results report Cloud revenue of RMB18,971 million and Cloud adjusted EBITA of RMB276 million. The same filing states segment reporting was updated and comparative figures were reclassified for the new presentation, so these values are retained only as legacy non-forecast evidence.",
        "cross_check": {
            "label": "Alibaba March Quarter 2023 results - prior-year comparative",
            "url": ALIBABA_MARCH_QTR_2023_RESULTS_URL,
            "type": "official_sec_6k_prior_year_comparative",
            "evidence": "Alibaba March quarter 2023 results use the pre-restatement Cloud segment comparative base before the later DingTalk-to-All-others reclassification, providing a public cross-check for the old segment boundary.",
        },
    },
}

ALIBABA_CLOUD_SOURCE_BY_PERIOD = {
    "FY2023 Q1": {
        "label": "Alibaba September Quarter 2023 results - restated Cloud Intelligence Group reconciliation",
        "url": ALIBABA_SEPTEMBER_QTR_2023_RESULTS_URL,
        "document_url": ALIBABA_SEPTEMBER_QTR_2023_DOCUMENT_URL,
        "type": "official_sec_6k_restated_segment_reconciliation",
        "evidence": "Alibaba September quarter 2023 results restated DingTalk from Cloud Intelligence Group to All others and reclassified comparative figures. Restated Cloud Intelligence Group revenue for six months ended September 30, 2022 was RMB51,391 million and September quarter 2022 revenue was RMB27,035 million, so June quarter 2022 revenue is reconciled to RMB24,356 million. Restated Cloud Intelligence Group adjusted EBITA for six months ended September 30, 2022 was RMB1,845 million and September quarter 2022 adjusted EBITA was RMB981 million, so June quarter 2022 adjusted EBITA is reconciled to RMB864 million. No same-basis FY2022 quarterly comparator is retained here, so FY2023 Q1 growth metrics are not estimated.",
    },
    "FY2023 Q2": {
        "label": "Alibaba September Quarter 2023 results - restated Cloud Intelligence Group comparative",
        "url": ALIBABA_SEPTEMBER_QTR_2023_RESULTS_URL,
        "document_url": ALIBABA_SEPTEMBER_QTR_2023_DOCUMENT_URL,
        "type": "official_sec_6k_restated_segment_comparative",
        "evidence": "Alibaba September quarter 2023 results restated DingTalk from Cloud Intelligence Group to All others and reclassified comparative figures. The restated comparative table reports September quarter 2022 Cloud Intelligence Group revenue of RMB27,035 million and adjusted EBITA of RMB981 million. No same-basis FY2022 quarterly comparator is retained here, so FY2023 Q2 growth metrics are not estimated.",
    },
    "FY2023 Q3": {
        "label": "Alibaba December Quarter 2023 results - restated Cloud Intelligence Group comparative",
        "url": ALIBABA_DECEMBER_QTR_2023_RESULTS_URL,
        "document_url": ALIBABA_DECEMBER_QTR_2023_DOCUMENT_URL,
        "type": "official_sec_6k_restated_segment_comparative",
        "evidence": "Alibaba December quarter 2023 results say DingTalk was reclassified from Cloud Intelligence Group to All others and comparative figures were reclassified. The restated comparative table reports December quarter 2022 Cloud Intelligence Group revenue of RMB27,364 million and adjusted EBITA of RMB1,269 million. No same-basis FY2022 quarterly comparator is retained here, so FY2023 Q3 growth metrics are not estimated.",
    },
    "FY2023 Q4": {
        "label": "Alibaba March Quarter 2024 and Fiscal Year 2024 results - restated Cloud Intelligence Group comparative",
        "url": ALIBABA_MARCH_QTR_2024_RESULTS_URL,
        "document_url": ALIBABA_MARCH_QTR_2024_DOCUMENT_URL,
        "type": "official_sec_6k_restated_segment_comparative",
        "evidence": "Alibaba fiscal 2024 results say DingTalk was reclassified from Cloud Intelligence Group to All others and comparative figures were reclassified. The restated comparative table reports March quarter 2023 Cloud Intelligence Group revenue of RMB24,742 million and adjusted EBITA of RMB987 million. No same-basis FY2022 quarterly comparator is retained here, so FY2023 Q4 growth metrics are not estimated.",
    },
    "FY2024 Q1": {
        "label": "Alibaba September Quarter 2023 results - restated Cloud Intelligence Group reconciliation",
        "url": ALIBABA_SEPTEMBER_QTR_2023_RESULTS_URL,
        "document_url": ALIBABA_SEPTEMBER_QTR_2023_DOCUMENT_URL,
        "type": "official_sec_6k_restated_segment_reconciliation",
        "evidence": "Alibaba September quarter 2023 results restated DingTalk from Cloud Intelligence Group to All others and reclassified comparative figures. Restated Cloud Intelligence Group revenue for six months ended September 30, 2023 was RMB52,713 million and September quarter 2023 revenue was RMB27,648 million, so June quarter 2023 revenue is reconciled to RMB25,065 million. Restated Cloud Intelligence Group adjusted EBITA for six months ended September 30, 2023 was RMB2,325 million and September quarter 2023 adjusted EBITA was RMB1,409 million, so June quarter 2023 adjusted EBITA is reconciled to RMB916 million. Revenue growth and adjusted EBITA growth are computed against restated FY2023 Q1 comparatives as 2.911% and 6.019%.",
    },
    "FY2024 Q2": {
        "label": "Alibaba September Quarter 2023 results",
        "url": ALIBABA_SEPTEMBER_QTR_2023_RESULTS_URL,
        "document_url": ALIBABA_SEPTEMBER_QTR_2023_DOCUMENT_URL,
        "type": "official_sec_6k_quarterly_results",
        "evidence": "Alibaba September quarter 2023 results report Cloud Intelligence Group revenue of RMB27,648 million, up 2% year-over-year, and adjusted EBITA of RMB1,409 million, up 44% year-over-year.",
    },
    "FY2024 Q3": {
        "label": "Alibaba December Quarter 2023 results",
        "url": ALIBABA_DECEMBER_QTR_2023_RESULTS_URL,
        "document_url": ALIBABA_DECEMBER_QTR_2023_DOCUMENT_URL,
        "type": "official_sec_6k_quarterly_results",
        "evidence": "Alibaba December quarter 2023 results report Cloud Intelligence Group revenue of RMB28,066 million, up 3% year-over-year, and adjusted EBITA of RMB2,364 million, up 86% year-over-year.",
    },
    "FY2024 Q4": {
        "label": "Alibaba March Quarter 2024 and Fiscal Year 2024 results",
        "url": ALIBABA_MARCH_QTR_2024_RESULTS_URL,
        "document_url": ALIBABA_MARCH_QTR_2024_DOCUMENT_URL,
        "type": "official_sec_6k_quarterly_results",
        "evidence": "Alibaba March quarter 2024 results report Cloud Intelligence Group revenue of RMB25,595 million, up 3% year-over-year, and adjusted EBITA of RMB1,432 million, up 45% year-over-year.",
    },
    "FY2025 Q1": {
        "label": "Alibaba June Quarter 2024 results",
        "url": ALIBABA_JUNE_QTR_2024_RESULTS_URL,
        "document_url": ALIBABA_JUNE_QTR_2024_DOCUMENT_URL,
        "type": "official_sec_6k_quarterly_results",
        "evidence": "Alibaba June quarter 2024 results report Cloud Intelligence Group revenue of RMB26,549 million, up 6% year-over-year, and adjusted EBITA of RMB2,337 million, up 155% year-over-year.",
    },
    "FY2025 Q2": {
        "label": "Alibaba September Quarter 2024 results",
        "url": ALIBABA_SEPTEMBER_QTR_2024_RESULTS_URL,
        "document_url": ALIBABA_SEPTEMBER_QTR_2024_DOCUMENT_URL,
        "type": "official_sec_6k_quarterly_results",
        "evidence": "Alibaba September quarter 2024 results report Cloud Intelligence Group revenue of RMB29,610 million, up 7% year-over-year, and adjusted EBITA of RMB2,661 million, up 89% year-over-year.",
    },
    "FY2025 Q3": {
        "label": "Alibaba December Quarter 2024 results",
        "url": ALIBABA_DECEMBER_QTR_2024_RESULTS_URL,
        "document_url": ALIBABA_DECEMBER_QTR_2024_DOCUMENT_URL,
        "type": "official_sec_6k_quarterly_results",
        "evidence": "Alibaba December quarter 2024 results report Cloud Intelligence Group revenue of RMB31,742 million, up 13% year-over-year, and adjusted EBITA of RMB3,138 million, up 33% year-over-year.",
    },
    "FY2025 Q4": {
        "label": "Alibaba March Quarter 2025 and Fiscal Year 2025 results",
        "url": ALIBABA_MARCH_QTR_2025_RESULTS_URL,
        "document_url": ALIBABA_MARCH_QTR_2025_DOCUMENT_URL,
        "type": "official_sec_6k_quarterly_results",
        "evidence": "Alibaba March quarter 2025 results report Cloud Intelligence Group revenue of RMB30,127 million, up 18% year-over-year, and adjusted EBITA of RMB2,420 million, up 69% year-over-year.",
    },
    "FY2026 Q1": {
        "label": "Alibaba June Quarter 2025 results",
        "url": ALIBABA_JUNE_QTR_2025_RESULTS_URL,
        "document_url": ALIBABA_JUNE_QTR_2025_DOCUMENT_URL,
        "type": "official_quarterly_earnings_release",
        "evidence": "Alibaba June quarter 2025 results report Cloud Intelligence Group revenue of RMB33,398 million, up 26% year-over-year, and adjusted EBITA of RMB2,954 million, up 26% year-over-year.",
    },
    "FY2026 Q2": {
        "label": "Alibaba September Quarter 2025 results",
        "url": ALIBABA_SEPTEMBER_QTR_2025_RESULTS_URL,
        "document_url": ALIBABA_SEPTEMBER_QTR_2025_DOCUMENT_URL,
        "type": "official_quarterly_earnings_release",
        "evidence": "Alibaba September quarter 2025 results report Cloud Intelligence Group revenue of RMB39,824 million, up 34% year-over-year, and adjusted EBITA of RMB3,604 million, up 35% year-over-year.",
    },
    "FY2026 Q3": {
        "label": "Alibaba December Quarter 2025 results",
        "url": ALIBABA_DECEMBER_QTR_2025_RESULTS_URL,
        "document_url": ALIBABA_DECEMBER_QTR_2025_DOCUMENT_URL,
        "type": "official_quarterly_earnings_release",
        "evidence": "Alibaba December quarter 2025 results report Cloud Intelligence Group revenue of RMB43,284 million, up 36% year-over-year, and adjusted EBITA of RMB3,911 million, up 25% year-over-year.",
    },
    "FY2026 Q4": {
        "label": "Alibaba March Quarter 2026 and Fiscal Year 2026 results",
        "url": ALIBABA_MARCH_QTR_2026_RESULTS_URL,
        "document_url": ALIBABA_MARCH_QTR_2026_DOCUMENT_URL,
        "type": "official_quarterly_earnings_release",
        "evidence": "Alibaba March quarter 2026 results report Cloud Intelligence Group revenue of RMB41,626 million, up 38% year-over-year, and adjusted EBITA of RMB3,796 million, up 57% year-over-year.",
    },
}

ALIBABA_CLOUD_RESTATED_GROWTH_SOURCE_GAP_CONFIRMATIONS = [
    {
        "subject": "Alibaba Cloud",
        "period": period,
        "metric_key": metric_key,
        "source_label": ALIBABA_CLOUD_SOURCE_BY_PERIOD[period]["label"],
        "source_url": ALIBABA_CLOUD_SOURCE_BY_PERIOD[period]["url"],
        "evidence": (
            f"{ALIBABA_CLOUD_SOURCE_BY_PERIOD[period]['evidence']} "
            "The retained Alibaba Cloud series uses the later restated Cloud Intelligence Group basis after DingTalk was reclassified to All others. "
            "The same-basis prior-year quarterly comparator needed for this FY2023 growth metric is not disclosed in the retained sources, so the old Cloud segment growth rate is not comparable and is not carried forward."
        ),
        "verification_method": "official_restated_segment_growth_gap_check",
        "verification_sources": [
            {
                "label": "Alibaba quarterly results index",
                "url": ALIBABA_QUARTERLY_RESULTS_URL,
                "type": "official_quarterly_results_index",
                "evidence": "Alibaba Investor Relations pages list the official quarterly results releases used for Cloud Intelligence Group segment extraction.",
            },
            {
                "label": ALIBABA_CLOUD_SOURCE_BY_PERIOD[period]["label"],
                "url": ALIBABA_CLOUD_SOURCE_BY_PERIOD[period]["url"],
                "type": ALIBABA_CLOUD_SOURCE_BY_PERIOD[period]["type"],
                "evidence": ALIBABA_CLOUD_SOURCE_BY_PERIOD[period]["evidence"],
            },
        ],
        "verification_note": "官方重列口径保留 revenue 和 adjusted_ebita；同口径 FY2022 季度增长基数未披露，旧 Cloud segment 同比不可混用，禁止估算。",
        "append_if_missing": True,
    }
    for period in ["FY2023 Q1", "FY2023 Q2", "FY2023 Q3", "FY2023 Q4"]
    for metric_key in ["revenue_growth_yoy", "adjusted_ebita_growth_yoy"]
]

ALIBABA_CLOUD_PRE_RESTATED_CIG_SOURCE_GAP_CONFIRMATIONS = [
    {
        "subject": "Alibaba Cloud",
        "period": period,
        "metric_key": "cloud_quarterly_disclosure_status",
        "source_label": "Alibaba September Quarter 2023 results - DingTalk reclassification",
        "source_url": ALIBABA_SEPTEMBER_QTR_2023_RESULTS_URL,
        "evidence": (
            "Alibaba's FY2022-era Cloud segment disclosures comprised Alibaba Cloud and DingTalk. Starting from the "
            "quarter ended September 30, 2023, Alibaba reclassified DingTalk from Cloud Intelligence Group to All others "
            "and reclassified comparative figures. The retained Alibaba Cloud series uses this later restated Cloud "
            "Intelligence Group basis; no official/public same-basis quarterly Cloud Intelligence Group values have been "
            f"retained for {period}, so the period is recorded as a disclosure-boundary source gap rather than estimated."
        ),
        "verification_method": "official_alibaba_cloud_restated_cig_disclosure_gap_check",
        "verification_sources": [
            {
                "label": "Alibaba quarterly results index",
                "url": ALIBABA_QUARTERLY_RESULTS_URL,
                "type": "official_quarterly_results_index",
                "evidence": "Alibaba Investor Relations pages list the official quarterly results releases used for Cloud and Cloud Intelligence Group segment extraction.",
            },
            {
                "label": "Alibaba June Quarter 2022 results",
                "url": ALIBABA_JUNE_QTR_2022_RESULTS_URL,
                "type": "official_sec_6k_quarterly_results",
                "evidence": "Alibaba June quarter 2022 results state that the Cloud segment was comprised of Alibaba Cloud and DingTalk.",
            },
            {
                "label": "Alibaba September Quarter 2023 results",
                "url": ALIBABA_SEPTEMBER_QTR_2023_RESULTS_URL,
                "type": "official_sec_6k_quarterly_results",
                "evidence": "Alibaba September quarter 2023 results state that DingTalk was reclassified from Cloud Intelligence Group to All others and comparative figures were reclassified.",
            },
            {
                "label": "Alibaba March Quarter 2024 and Fiscal Year 2024 results",
                "url": ALIBABA_MARCH_QTR_2024_RESULTS_URL,
                "type": "official_sec_6k_quarterly_results",
                "evidence": "Alibaba fiscal 2024 results continue the reorganized segment reporting and DingTalk-to-All-others reclassification, with comparative figures reclassified to conform to the new presentation.",
            },
        ],
        "verification_note": "FY2017-FY2022 Alibaba Cloud periods are pre-restated Cloud Intelligence Group disclosure-boundary gaps for the retained revenue/adjusted_ebita series. Older Cloud segment rows included DingTalk and are not mixed into the post-reclassification Cloud Intelligence Group sequence; these source-gap rows do not count toward the 40-quarter cloud coverage gate.",
        "append_if_missing": True,
    }
    for period in ALIBABA_CLOUD_PRE_RESTATED_CIG_SOURCE_GAP_PERIODS
]

HGC_OFFICIAL_SOURCE_HINTS = [
    {
        "label": "HGC company profile",
        "url": "https://www.hgc.com.hk/about-hgc/about-us/company-profile",
        "type": "official_company_profile",
        "evidence": "HGC官网确认 HGC Global Communications Limited 为综合 ICT / 固网运营商，并说明其于 2017 年成为 I Squared Capital 持有的组合公司。",
    },
    {
        "label": "HGC homepage",
        "url": "https://www.hgc.com.hk/",
        "type": "official_company_site",
        "evidence": "HGC官网主页列示业务入口、新闻、ESG 和公司信息入口，但未提供上市公司式季度/半年度财务报表入口。",
    },
]

HUAWEI_CLOUD_OFFICIAL_SOURCE_HINTS = [
    {
        "label": "Huawei 2025 Annual Report quick view",
        "url": "https://www.huawei.com/en/annual-report/2025",
        "type": "official_annual_report_quick_view",
        "evidence": "Huawei 2025 Annual Report By Business Segment table reports Cloud Computing revenue of CNY32,161 million for 2025, CNY33,325 million for 2024, and YoY (3.5)%; the note states revenue derived from cloud computing business, including revenue from other Huawei segments, amounted to CNY72,075 million.",
    },
    {
        "label": "Huawei annual reports index",
        "url": "https://www.huawei.com/en/annual-report",
        "type": "official_annual_reports_index",
        "evidence": "Huawei annual reports index lists the 2025 Annual Report quick view and PDF, plus past annual reports; no quarterly or interim cloud segment financial report entry is provided on this official annual reports page.",
    },
]

METRIC_LABELS: dict[str, tuple[str, str]] = {
    "Operating Revenue": ("operating_revenue", "经营收入/运营收入"),
    "Revenue": ("revenue", "营业收入/收益"),
    "Revenue Growth (YoY)": ("revenue_growth_yoy", "收入同比增长"),
    "Cost of Revenue": ("cost_of_revenue", "营业成本/销售成本"),
    "Gross Profit": ("gross_profit", "毛利"),
    "Gross Margin": ("gross_margin", "毛利率"),
    "Operating Income": ("operating_income", "经营利润/营业利润"),
    "Operating Margin": ("operating_margin", "经营利润率"),
    "Pretax Income": ("pretax_income", "税前利润"),
    "Net Income": ("net_income", "净利润/股东应占利润"),
    "Net Income Growth": ("net_income_growth", "净利润同比增长"),
    "Net Margin": ("net_margin", "净利率"),
    "EBITDA": ("ebitda", "EBITDA"),
    "EBITDA Margin": ("ebitda_margin", "EBITDA率"),
    "Operating Cash Flow": ("operating_cash_flow", "经营现金流"),
    "Capital Expenditures": ("capital_expenditures", "资本开支"),
    "Free Cash Flow": ("free_cash_flow", "自由现金流"),
    "Cash & Equivalents": ("cash_and_equivalents", "现金及等价物"),
    "Total Assets": ("total_assets", "总资产"),
    "Total Debt": ("total_debt", "总债务"),
}

IMPORTANT_KEYS = [
    "operating_revenue",
    "revenue",
    "revenue_growth_yoy",
    "gross_profit",
    "gross_margin",
    "operating_income",
    "operating_margin",
    "net_income",
    "net_margin",
    "ebitda",
    "ebitda_margin",
    "operating_cash_flow",
    "capital_expenditures",
    "free_cash_flow",
    "cash_and_equivalents",
    "total_assets",
    "total_debt",
]

PERCENT_KEYS = {
    "revenue_growth_yoy",
    "gross_margin",
    "operating_margin",
    "net_income_growth",
    "net_margin",
    "ebitda_margin",
    "azure_and_other_cloud_services_growth_yoy",
    "cloud_revenue_growth_yoy",
    "cloud_infrastructure_revenue_growth_yoy",
    "cloud_application_revenue_growth_yoy",
    "fintech_business_services_revenue_growth_yoy",
    "adjusted_ebita_growth_yoy",
}

METRIC_ZH_BY_KEY = {metric_key: zh for metric_key, zh in METRIC_LABELS.values()}
METRIC_ZH_BY_KEY.update(
    {
        "service_revenue": "服务收入",
        "operator_business_revenue": "运营商业务收入",
        "tower_business_revenue": "塔类业务收入",
        "das_business_revenue": "室分业务收入",
        "smart_business_revenue": "智联业务收入",
        "energy_business_revenue": "能源业务收入",
        "adjusted_funds_flow": "调整后自由现金流/AFF",
        "financial_disclosure_status": "财务披露状态",
        "quarterly_financial_disclosure_status": "季度财务披露状态",
        "cloud_quarterly_disclosure_status": "云业务季度披露状态",
        "cloud_segment_extraction_status": "云分部季度抽取状态",
        "azure_and_other_cloud_services_growth_yoy": "Azure及其他云服务收入同比增长",
        "cloud_revenue": "云收入",
        "cloud_revenue_growth_yoy": "云收入同比增长",
        "cloud_infrastructure_revenue": "云基础设施收入",
        "cloud_infrastructure_revenue_growth_yoy": "云基础设施收入同比增长",
        "cloud_application_revenue": "云应用收入",
        "cloud_application_revenue_growth_yoy": "云应用收入同比增长",
        "fintech_business_services_revenue": "金融科技及企业服务收入",
        "fintech_business_services_revenue_growth_yoy": "金融科技及企业服务收入同比增长",
        "fintech_business_services_disclosure_status": "金融科技及企业服务披露状态",
        "adjusted_ebita": "调整后EBITA",
        "adjusted_ebita_growth_yoy": "调整后EBITA同比增长",
        "legacy_cloud_segment_revenue_including_dingtalk": "旧Cloud分部收入（含钉钉）",
        "legacy_cloud_segment_adjusted_ebita_including_dingtalk": "旧Cloud分部调整后EBITA（含钉钉）",
    }
)

CM_2025_OPERATION_URL = "https://www.chinamobileltd.com/en/ir/operation_q.php?year=2025"
CM_2025_Q3_HKEX_URL = "https://www1.hkexnews.hk/listedco/listconews/sehk/2025/1020/2025102001101.pdf"
CM_2025_Q3_COMPANY_URL = "https://www.chinamobileltd.com/en/file/view.php?id=325924"
CM_2025_H1_HKEX_URL = "https://www1.hkexnews.hk/listedco/listconews/sehk/2025/0829/2025082901049.pdf"
CM_2025_H1_CNINFO_URL = "https://static.cninfo.com.cn/finalpage/2025-08-08/1224425060.PDF"
CM_2025_H1_SINA_URL = "https://vip.stock.finance.sina.com.cn/corp/view/vCB_AllBulletinDetail.php?id=11284906&stockid=600941"
CM_2025_ANNUAL_HKEX_URL = "https://www1.hkexnews.hk/listedco/listconews/sehk/2026/0423/2026042300752.pdf"
CM_2025_ANNUAL_RESULTS_URL = "https://www.marketscreener.com/news/china-mobile-2025-annual-results-presentation-hk-shares-ce7e51dadb8bf523"
CM_2025_ANNUAL_CN_SUMMARY_URL = "https://paper.cnstock.com/html/2026-03/27/content_2192681.htm"
CM_2025_ANNUAL_HKEX_RESULTS_URL = "https://www1.hkexnews.hk/listedco/listconews/sehk/2026/0326/2026032602030_c.pdf"
CM_2025_ANNUAL_SINA_URL = "https://money.finance.sina.com.cn/corp/view/vCB_AllBulletinDetail.php?id=12023001&stockid=600941"
CM_2025_Q1_SSE_URL = "https://static.sse.com.cn/disclosure/listedinfo/announcement/c/new/2025-04-23/600941_20250423_97Z1.pdf"
CM_2025_Q1_SINA_URL = "https://vip.stock.finance.sina.com.cn/corp/view/vCB_AllBulletinDetail.php?id=10931075&stockid=600941"
CM_2025_Q1_EASTMONEY_URL = "https://data.eastmoney.com/notices/detail/600941/AN202504221660555817.html"
CM_2025_Q3_SINA_URL = "https://money.finance.sina.com.cn/corp/view/vCB_AllBulletinDetail.php?id=11521245&stockid=600941"
CM_2025_Q3_XUEQIU_URL = "https://stockmc.xueqiu.com/202510/600941_20251021_4Z3K.pdf"
CM_2026_Q1_CNINFO_URL = "https://dataclouds.cninfo.com.cn/shgonggao/hsomarket/2026/20260420/c34d1cf7b4794bebb3f39acf8b598c4b.PDF"
CM_2026_Q1_SINA_URL = "https://money.finance.sina.com.cn/corp/view/vCB_AllBulletinDetail.php?id=12123807&stockid=600941"
CM_2026_Q1_STHEADLINE_URL = "https://www.stheadline.com/stock-market/3564051/%E4%B8%AD%E5%9C%8B%E7%A7%BB%E5%8B%95%E9%A6%96%E5%AD%A3EBITDA%E8%B7%8C5-%E9%9B%B2%E8%A8%88%E7%AE%97%E7%AD%89%E5%85%B6%E4%BB%96%E6%A5%AD%E5%8B%99%E6%94%B6%E5%85%A5%E5%A2%9E127"
CM_2023_OPERATION_URL = "https://www.chinamobileltd.com/en/ir/operation_q.php?year=2023"
CM_2023_Q1_CNINFO_URL = "https://static.cninfo.com.cn/finalpage/2023-04-21/1216490015.PDF"
CM_2023_Q1_CNINFO_DETAIL_URL = "https://www.cninfo.com.cn/new/disclosure/detail?stockCode=600941&announcementId=1216490015&orgId=gshk0000941&announcementTime=2023-04-21"
CM_2023_H1_CNINFO_SUMMARY_URL = "https://static.cninfo.com.cn/finalpage/2023-08-11/1217509878.PDF"
CM_2023_H1_SINA_URL = "https://vip.stock.finance.sina.com.cn/corp/view/vCB_AllBulletinDetail.php?id=9397960&stockid=600941"
CM_2023_Q3_SINA_URL = "https://money.finance.sina.com.cn/corp/view/vCB_AllBulletinDetail.php?stockid=600941&id=9580251"
CM_2023_ANNUAL_SINA_URL = "https://money.finance.sina.com.cn/corp/view/vCB_AllBulletinDetail.php?id=9887182&stockid=600941"
CM_2023_ANNUAL_SSE_SUMMARY_URL = "https://www.sse.com.cn/disclosure/listedinfo/summaries/indexDetail.shtml?SEQ=334217541"
CM_2023_H1_REPORT_URL = "https://www.chinamobileltd.com/en/ir/reports/ir2023.pdf"
CM_2023_ANNUAL_REPORT_URL = "https://www.chinamobileltd.com/en/ir/reports/ar2023.pdf"
CM_2022_Q1_IRASIA_URL = "https://doc.irasia.com/listco/hk/chinamobile/interim/2022/int1q.pdf"
CM_2022_Q3_IRASIA_URL = "https://doc.irasia.com/listco/hk/chinamobile/interim/2022/int3q.pdf"
CM_2022_INTERIM_REPORT_URL = "https://doc.irasia.com/listco/hk/chinamobile/interim/2022/intrep.pdf"
CM_2022_ANNUAL_REPORT_URL = "https://doc.irasia.com/listco/hk/chinamobile/annual/2022/ar2022.pdf"
CM_2022_Q1_CNINFO_URL = "https://static.cninfo.com.cn/finalpage/2022-04-22/1213025056.PDF"
CM_2022_Q1_SINA_URL = "https://money.finance.sina.com.cn/corp/view/vCB_AllBulletinDetail.php?id=8036169&stockid=600941"
CM_2022_H1_SINA_URL = "https://money.finance.sina.com.cn/corp/view/vCB_AllBulletinDetail.php?id=8414272&stockid=600941"
CM_2022_Q3_SINA_URL = "https://money.finance.sina.com.cn/corp/view/vCB_AllBulletinDetail.php?id=8604768&stockid=600941"
CM_2022_ANNUAL_SINA_URL = "https://money.finance.sina.com.cn/corp/view/vCB_AllBulletinDetail.php?id=8905563&stockid=600941"
CM_2019_OPERATION_URL = "https://www.chinamobileltd.com/en/ir/operation_q.php?year=2019"
CM_2019_INTERIM_REPORT_URL = "https://doc.irasia.com/listco/hk/chinamobile/interim/2019/intrep.pdf"
CM_2019_INTERIM_PRESS_URL = "https://doc.irasia.com/listco/hk/chinamobile/interim/2019/intpress.pdf"
CM_2019_ANNUAL_REPORT_URL = "https://doc.irasia.com/listco/hk/chinamobile/annual/2019/ar2019.pdf"
CM_2018_OPERATION_URL = "https://www.chinamobileltd.com/en/ir/operation_q.php?year=2018"
CM_2018_INTERIM_REPORT_URL = "https://doc.irasia.com/listco/hk/chinamobile/interim/2018/intrep.pdf"
CM_2018_ANNUAL_REPORT_URL = "https://doc.irasia.com/listco/hk/chinamobile/annual/2018/ar2018.pdf"
CM_2017_OPERATION_URL = "https://www.chinamobileltd.com/en/ir/operation_q.php?year=2017"
CM_2017_INTERIM_REPORT_URL = "https://doc.irasia.com/listco/hk/chinamobile/interim/2017/intrep.pdf"
CM_2017_ANNUAL_REPORT_URL = "https://doc.irasia.com/listco/hk/chinamobile/annual/2017/ar2017.pdf"
CM_2016_OPERATION_URL = "https://www.chinamobileltd.com/en/ir/operation_q.php?year=2016"
CM_2016_INTERIM_REPORT_URL = "https://doc.irasia.com/listco/hk/chinamobile/interim/2016/intrep.pdf"
CM_2016_ANNUAL_REPORT_URL = "https://doc.irasia.com/listco/hk/chinamobile/annual/2016/ar2016.pdf"
CM_2020_OPERATION_URL = "https://www.chinamobileltd.com/en/ir/operation_q.php?year=2020"
CM_2020_Q1_HKEX_URL = "https://www1.hkexnews.hk/listedco/listconews/sehk/2020/0420/2020042001250.pdf"
CM_2020_INTERIM_REPORT_URL = "https://doc.irasia.com/listco/hk/chinamobile/interim/2020/intrep.pdf"
CM_2020_Q3_HKEX_URL = "https://www1.hkexnews.hk/listedco/listconews/sehk/2020/1020/2020102000522.pdf"
CM_2020_ANNUAL_REPORT_URL = "https://doc.irasia.com/listco/hk/chinamobile/annual/2020/ar2020.pdf"
CM_2021_INTERIM_REPORT_URL = "https://doc.irasia.com/listco/hk/chinamobile/interim/2021/intrep.pdf"
CM_2021_ANNUAL_REPORT_URL = "https://doc.irasia.com/listco/hk/chinamobile/annual/2021/ar2021.pdf"
CM_2024_OPERATION_URL = "https://www.chinamobileltd.com/en/ir/operation_q.php?year=2024"
CM_2024_Q1_CNINFO_URL = "https://static.cninfo.com.cn/finalpage/2024-04-23/1219737430.PDF"
CM_2024_Q1_SINA_URL = "https://money.finance.sina.com.cn/corp/view/vCB_AllBulletinDetail.php?id=10024494&stockid=600941"
CM_2024_H1_SINA_URL = "https://vip.stock.finance.sina.com.cn/corp/view/vCB_AllBulletinDetail.php?id=10365602&stockid=600941"
CM_2024_H1_REPORT_URL = "https://www.chinamobileltd.com/en/ir/reports/ir2024.pdf"
CM_2024_Q3_CNINFO_URL = "https://static.cninfo.com.cn/finalpage/2024-10-22/1221451112.PDF"
CM_2024_Q3_SINA_URL = "https://money.finance.sina.com.cn/corp/view/vCB_AllBulletinDetail.php?id=10534559&stockid=600941"
CM_2024_ANNUAL_SINA_URL = "https://money.finance.sina.com.cn/corp/view/vCB_AllBulletinDetail.php?id=10795365&stockid=600941"
CM_2024_ANNUAL_REPORT_URL = "https://www.chinamobileltd.com/en/ir/reports/ar2024.pdf"

CM_2023_Q1_Q2_SOURCES = [
    {"label": "中国移动官网2023单季度经营数据", "url": CM_2023_OPERATION_URL, "evidence": "官网直接列示2023/1Q和2023/2Q Operating Revenue、Revenue from Telecommunications Services、EBITDA和Profit Attributable to Equity Shareholders。"},
    {"label": "中国移动2023中期报告", "url": CM_2023_H1_REPORT_URL, "evidence": "2023中期报告披露H1 2023 Operating Revenue 530,719、Revenue from Telecommunications Services 452,238、EBITDA 183,457和股东应占利润76,173百万元，用于交叉核验Q1+Q2。"},
    {"label": "中国移动2023年报", "url": CM_2023_ANNUAL_REPORT_URL, "evidence": "2023年报披露全年Operating revenue 1,009,309、Revenue from telecommunications services 863,514、EBITDA 341,478和股东应占利润131,766百万元。"},
]

CM_2023_Q1_DETAIL_SOURCES = [
    {"label": "中国移动2023年第一季度报告（巨潮资讯原文）", "url": CM_2023_Q1_CNINFO_URL, "evidence": "一季报披露营业收入250,746百万元、营业成本189,417百万元、营业利润36,141百万元、资产负债表和现金流量表。"},
    {"label": "中国移动2023年第一季度报告（巨潮资讯公告页）", "url": CM_2023_Q1_CNINFO_DETAIL_URL, "evidence": "巨潮资讯公告详情页对应同一份2023年第一季度报告，用于核对公告编号和发布日期。"},
    {"label": "中国移动官网2023单季度经营数据", "url": CM_2023_OPERATION_URL, "evidence": "官网直接列示2023/1Q经营收入2,507亿元、主营业务收入2,093亿元、EBITDA 799亿元、归母利润281亿元，用于交叉核验核心单季口径。"},
]

CM_2023_Q2_DETAIL_SOURCES = [
    {"label": "中国移动2023年半年度报告（新浪财经同文正文）", "url": CM_2023_H1_SINA_URL, "evidence": "同文公告正文列示A股半年报完整财务表：H1营业收入530,719百万元、营业成本377,807百万元、营业利润98,000百万元、经营现金流160,525百万元、购建长期资产现金支出79,646百万元。"},
    {"label": "中国移动2023年半年度报告摘要（巨潮资讯原文）", "url": CM_2023_H1_CNINFO_SUMMARY_URL, "evidence": "巨潮摘要对应同一半年度报告，披露H1关键经营、资产和利润指标，并指向上交所、港交所及公司官网全文。"},
    {"label": "中国移动2023年第一季度报告（巨潮资讯原文）", "url": CM_2023_Q1_CNINFO_URL, "evidence": "一季报提供Q1营业收入、营业成本、营业利润、现金流和资产负债表数，用于由H1累计数拆分Q2。"},
    {"label": "中国移动官网2023单季度经营数据", "url": CM_2023_OPERATION_URL, "evidence": "官网直接列示2023/2Q核心经营数据，用于交叉核验Q2收入、EBITDA和归母利润。"},
]

CM_2023_Q3_Q4_SOURCES = [
    {"label": "中国移动官网2023单季度经营数据", "url": CM_2023_OPERATION_URL, "evidence": "官网直接列示2023/3Q和2023/4Q Operating Revenue、Revenue from Telecommunications Services、EBITDA和Profit Attributable to Equity Shareholders。"},
    {"label": "中国移动2023中期报告", "url": CM_2023_H1_REPORT_URL, "evidence": "2023上半年精确累计值用于校验全年和下半年关系。"},
    {"label": "中国移动2023年报", "url": CM_2023_ANNUAL_REPORT_URL, "evidence": "2023年报披露全年Operating revenue 1,009,309、Revenue from telecommunications services 863,514、EBITDA 341,478和股东应占利润131,766百万元，用于交叉核验全年合计。"},
]

CM_2023_Q3_DETAIL_SOURCES = [
    {"label": "中国移动2023年第三季度报告（新浪财经同文正文）", "url": CM_2023_Q3_SINA_URL, "evidence": "同文公告正文列示A股三季报完整财务表：9M营业收入775,560百万元、营业成本552,607百万元、营业利润136,912百万元、经营现金流237,678百万元、购建长期资产现金支出120,936百万元。"},
    {"label": "中国移动2023年半年度报告（新浪财经同文正文）", "url": CM_2023_H1_SINA_URL, "evidence": "A股半年报完整财务表提供H1累计数，用于由9M累计数拆分Q3。"},
    {"label": "中国移动官网2023单季度经营数据", "url": CM_2023_OPERATION_URL, "evidence": "官网直接列示2023/3Q核心经营数据，用于交叉核验Q3收入、EBITDA和归母利润。"},
]

CM_2023_Q4_DETAIL_SOURCES = [
    {"label": "中国移动2023年年度报告（新浪财经同文正文）", "url": CM_2023_ANNUAL_SINA_URL, "evidence": "同文公告正文列示A股年报完整财务表：全年营业收入1,009,309百万元、营业成本724,358百万元、营业利润168,117百万元、经营现金流303,780百万元、购建长期资产现金支出181,263百万元。"},
    {"label": "中国移动2023年年度报告（中国移动官网）", "url": CM_2023_ANNUAL_REPORT_URL, "evidence": "公司官网年报披露全年核心经营和财务数据，用于交叉核验全年合计。"},
    {"label": "中国移动2023年年度报告（上交所公告摘要）", "url": CM_2023_ANNUAL_SSE_SUMMARY_URL, "evidence": "上交所公告摘要确认600941于2024-03-22披露中国移动2023年年度报告。"},
    {"label": "中国移动2023年第三季度报告（新浪财经同文正文）", "url": CM_2023_Q3_SINA_URL, "evidence": "A股三季报完整财务表提供9M累计数，用于由全年数拆分Q4。"},
]

CM_2022_Q1_SOURCES = [
    {"label": "中国移动2022年第一季度业绩公告", "url": CM_2022_Q1_IRASIA_URL, "evidence": "公告直接披露2022Q1 Operating Revenue 227.3十亿元、EBITDA 76.1十亿元和股东应占利润25.6十亿元。"},
    {"label": "中国移动2022中期报告", "url": CM_2022_INTERIM_REPORT_URL, "evidence": "中期报告披露H1 2022 Operating revenue 496,934百万元、EBITDA 173,912百万元和股东应占利润70,275百万元，用于交叉核验Q1+Q2。"},
]

CM_2022_Q1_DETAIL_SOURCES = [
    {"label": "中国移动2022年第一季度报告（新浪财经同文正文）", "url": CM_2022_Q1_SINA_URL, "evidence": "A股一季报完整财务表披露Q1营业收入227,320百万元、营业成本172,693百万元、营业利润33,477百万元、经营现金流77,770百万元、购建长期资产现金支出40,864百万元。"},
    {"label": "中国移动2022年第一季度业绩公告", "url": CM_2022_Q1_IRASIA_URL, "evidence": "H股一季度业绩公告披露Operating revenue、EBITDA、归母净利和IFRS三表，用于交叉核验核心值。"},
]

CM_2022_Q2_SOURCES = [
    {"label": "中国移动2022中期报告", "url": CM_2022_INTERIM_REPORT_URL, "evidence": "中期报告披露H1 2022 Operating revenue 496,934百万元、EBITDA 173,912百万元和股东应占利润70,275百万元。"},
    {"label": "中国移动2022年第一季度业绩公告", "url": CM_2022_Q1_IRASIA_URL, "evidence": "一季报提供Q1累计值，用于由H1累计数拆分Q2。"},
    {"label": "中国移动2022年度报告", "url": CM_2022_ANNUAL_REPORT_URL, "evidence": "年报披露FY2022 Operating revenue 937,259百万元、EBITDA 329,176百万元和股东应占利润125,459百万元，用于全年合计交叉核验。"},
]

CM_2022_Q2_DETAIL_SOURCES = [
    {"label": "中国移动2022年半年度报告（新浪财经同文正文）", "url": CM_2022_H1_SINA_URL, "evidence": "A股半年报完整财务表披露H1营业收入496,934百万元、营业成本354,886百万元、营业利润90,910百万元、经营现金流147,272百万元、购建长期资产现金支出89,722百万元。"},
    {"label": "中国移动2022年第一季度报告（新浪财经同文正文）", "url": CM_2022_Q1_SINA_URL, "evidence": "A股一季报提供Q1累计数，用于由H1累计数拆分Q2。"},
    {"label": "中国移动2022中期报告", "url": CM_2022_INTERIM_REPORT_URL, "evidence": "H股中期报告披露H1 Operating revenue、EBITDA、归母净利和IFRS三表，用于交叉核验累计关系。"},
]

CM_2022_Q3_SOURCES = [
    {"label": "中国移动2022前三季度业绩公告", "url": CM_2022_Q3_IRASIA_URL, "evidence": "前三季度公告披露9M 2022 Operating revenue 723.5十亿元、EBITDA 251.5十亿元和股东应占利润98.5十亿元。"},
    {"label": "中国移动2022中期报告", "url": CM_2022_INTERIM_REPORT_URL, "evidence": "中期报告提供H1累计值，用于由9M累计数拆分Q3。"},
    {"label": "中国移动2022年度报告", "url": CM_2022_ANNUAL_REPORT_URL, "evidence": "年报披露全年核心经营数据，用于交叉核验9M与全年合计关系。"},
]

CM_2022_Q3_DETAIL_SOURCES = [
    {"label": "中国移动2022年第三季度报告（新浪财经同文正文）", "url": CM_2022_Q3_SINA_URL, "evidence": "A股三季报完整财务表披露9M营业收入723,487百万元、营业成本522,810百万元、营业利润127,052百万元、经营现金流227,592百万元、购建长期资产现金支出136,593百万元。"},
    {"label": "中国移动2022年半年度报告（新浪财经同文正文）", "url": CM_2022_H1_SINA_URL, "evidence": "A股半年报提供H1累计数，用于由9M累计数拆分Q3。"},
    {"label": "中国移动2022前三季度业绩公告", "url": CM_2022_Q3_IRASIA_URL, "evidence": "H股前三季度业绩公告披露Operating revenue、EBITDA、归母净利和IFRS三表，用于交叉核验核心值。"},
]

CM_2022_Q4_SOURCES = [
    {"label": "中国移动2022年度报告", "url": CM_2022_ANNUAL_REPORT_URL, "evidence": "年报披露FY2022 Operating revenue 937,259百万元、EBITDA 329,176百万元和股东应占利润125,459百万元。"},
    {"label": "中国移动2022前三季度业绩公告", "url": CM_2022_Q3_IRASIA_URL, "evidence": "前三季度公告提供9M累计值，用于由全年累计数拆分Q4。"},
    {"label": "中国移动2022中期报告", "url": CM_2022_INTERIM_REPORT_URL, "evidence": "中期报告提供H1累计值，用于交叉核验2022拆分链路。"},
]

CM_2022_Q4_DETAIL_SOURCES = [
    {"label": "中国移动2022年年度报告（新浪财经同文正文）", "url": CM_2022_ANNUAL_SINA_URL, "evidence": "A股年报完整财务表披露全年营业收入937,259百万元、营业成本676,863百万元、营业利润161,306百万元、经营现金流280,750百万元、购建长期资产现金支出189,588百万元。"},
    {"label": "中国移动2022年度报告", "url": CM_2022_ANNUAL_REPORT_URL, "evidence": "公司年报披露全年Operating revenue、EBITDA、归母净利和IFRS财务报表，用于交叉核验全年合计。"},
    {"label": "中国移动2022年第三季度报告（新浪财经同文正文）", "url": CM_2022_Q3_SINA_URL, "evidence": "A股三季报提供9M累计数，用于由全年数拆分Q4。"},
]

CM_2020_Q1_SOURCES = [
    {"label": "中国移动官网2020单季度经营数据", "url": CM_2020_OPERATION_URL, "evidence": "官网直接列示2020/1Q Operating Revenue 181.3、Telecommunications Services Revenue 168.9、EBITDA 68.5和归母利润23.5十亿元。"},
    {"label": "中国移动2020年第一季度未经审核主要经营数据（HKEX）", "url": CM_2020_Q1_HKEX_URL, "evidence": "一季度公告披露2020Q1 Operating revenue 181.3十亿元、通信服务收入168.9十亿元、EBITDA 68.5十亿元和归母利润23.5十亿元。"},
    {"label": "中国移动2020中期报告", "url": CM_2020_INTERIM_REPORT_URL, "evidence": "中期报告披露H1 2020 Operating revenue 389,863百万元、EBITDA 145,711百万元和股东应占利润55,765百万元，用于交叉核验Q1+Q2。"},
]

CM_2020_Q2_SOURCES = [
    {"label": "中国移动官网2020单季度经营数据", "url": CM_2020_OPERATION_URL, "evidence": "官网直接列示2020/2Q核心经营数据。"},
    {"label": "中国移动2020年第一季度未经审核主要经营数据（HKEX）", "url": CM_2020_Q1_HKEX_URL, "evidence": "一季度公告提供Q1累计值，用于交叉核验H1与Q2关系。"},
    {"label": "中国移动2020中期报告", "url": CM_2020_INTERIM_REPORT_URL, "evidence": "中期报告披露H1 2020 Operating revenue 389,863百万元、EBITDA 145,711百万元和股东应占利润55,765百万元，用于交叉核验Q1+Q2。"},
]

CM_2020_Q3_SOURCES = [
    {"label": "中国移动官网2020单季度经营数据", "url": CM_2020_OPERATION_URL, "evidence": "官网直接列示2020/3Q核心经营数据。"},
    {"label": "中国移动2020年前三季度未经审核主要经营数据（HKEX）", "url": CM_2020_Q3_HKEX_URL, "evidence": "前三季度公告披露2020年前三季度Operating revenue 574.4十亿元、EBITDA 216.9十亿元和归母利润81.6十亿元，用于交叉核验Q1-Q3合计。"},
    {"label": "中国移动2020中期报告", "url": CM_2020_INTERIM_REPORT_URL, "evidence": "中期报告提供H1累计值，用于交叉核验9M与Q3关系。"},
]

CM_2020_Q4_SOURCES = [
    {"label": "中国移动官网2020单季度经营数据", "url": CM_2020_OPERATION_URL, "evidence": "官网直接列示2020/4Q核心经营数据。"},
    {"label": "中国移动2020年前三季度未经审核主要经营数据（HKEX）", "url": CM_2020_Q3_HKEX_URL, "evidence": "前三季度公告提供9M累计值，用于交叉核验全年与Q4关系。"},
    {"label": "中国移动2020年度报告", "url": CM_2020_ANNUAL_REPORT_URL, "evidence": "2020年报披露FY 2020 Operating revenue 768,070百万元、EBITDA 285,110百万元和股东应占利润107,843百万元，用于交叉核验全年合计。"},
]

CM_2019_Q1_SOURCES = [
    {"label": "中国移动官网2019单季度经营数据", "url": CM_2019_OPERATION_URL, "evidence": "官网直接列示2019/1Q Operating Revenue 185.0、Telecommunications Services Revenue 165.9、EBITDA 72.7和归母利润23.7十亿元。"},
    {"label": "中国移动2019中期报告", "url": CM_2019_INTERIM_REPORT_URL, "evidence": "中期报告披露H1 2019 Operating revenue约389.4十亿元、EBITDA约151.1十亿元和股东应占利润约56.1十亿元，用于交叉核验Q1+Q2。"},
    {"label": "中国移动2019年度报告", "url": CM_2019_ANNUAL_REPORT_URL, "evidence": "2019年报披露FY 2019 Operating revenue 745,917百万元、EBITDA 296,225百万元和股东应占利润106,641百万元，用于全年合计交叉核验。"},
]

CM_2019_Q2_SOURCES = [
    {"label": "中国移动官网2019单季度经营数据", "url": CM_2019_OPERATION_URL, "evidence": "官网直接列示2019/2Q核心经营数据。"},
    {"label": "中国移动2019中期业绩新闻稿", "url": CM_2019_INTERIM_PRESS_URL, "evidence": "中期业绩新闻稿披露上半年营运收入和利润表现，用于交叉核验H1方向和披露入口。"},
    {"label": "中国移动2019中期报告", "url": CM_2019_INTERIM_REPORT_URL, "evidence": "中期报告披露H1 2019核心经营数据，用于交叉核验Q1+Q2。"},
]

CM_2019_Q3_SOURCES = [
    {"label": "中国移动官网2019单季度经营数据", "url": CM_2019_OPERATION_URL, "evidence": "官网直接列示2019/3Q核心经营数据。"},
    {"label": "中国移动2019中期报告", "url": CM_2019_INTERIM_REPORT_URL, "evidence": "中期报告提供H1累计值，用于交叉核验9M与Q3关系。"},
    {"label": "中国移动2019年度报告", "url": CM_2019_ANNUAL_REPORT_URL, "evidence": "2019年报披露全年核心经营数据，用于交叉核验全年合计。"},
]

CM_2019_Q4_SOURCES = [
    {"label": "中国移动官网2019单季度经营数据", "url": CM_2019_OPERATION_URL, "evidence": "官网直接列示2019/4Q核心经营数据。"},
    {"label": "中国移动2019年度报告", "url": CM_2019_ANNUAL_REPORT_URL, "evidence": "2019年报披露FY 2019 Operating revenue 745,917百万元、EBITDA 296,225百万元和股东应占利润106,641百万元，用于交叉核验全年合计。"},
    {"label": "中国移动2020年度报告", "url": CM_2020_ANNUAL_REPORT_URL, "evidence": "2020年报比较栏列示2019全年核心经营数据，用于交叉核验2019年报口径。"},
]

CM_2021_Q1_DETAIL_SOURCES = [
    {"label": "中国移动2022年第一季度报告（巨潮资讯原文）", "url": CM_2022_Q1_CNINFO_URL, "evidence": "A股一季报比较栏披露Q1 2021营业收入198,429百万元、营业成本147,000百万元、营业利润31,252百万元、归母净利润24,056百万元、经营现金流76,272百万元、购建长期资产现金支出33,755百万元；主要财务指标披露EBITDA 721亿元。"},
    {"label": "中国移动2022年第一季度报告（新浪财经同文正文）", "url": CM_2022_Q1_SINA_URL, "evidence": "新浪同文公告镜像提供同一份A股一季报正文和Q1 2021比较栏，用于核验巨潮PDF字段。"},
    {"label": "中国移动2021中期报告", "url": CM_2021_INTERIM_REPORT_URL, "evidence": "H股中期报告披露H1 2021 Operating revenue 443,647百万元、EBITDA 161,988百万元、股东应占利润59,118百万元，用于核验Q1+Q2累计关系。"},
    {"label": "中国移动2021年度报告", "url": CM_2021_ANNUAL_REPORT_URL, "evidence": "H股年报披露FY 2021 Operating revenue 848,258百万元、EBITDA 311,008百万元和股东应占利润116,148百万元，用于全年合计交叉核验。"},
]

CM_2021_Q2_DETAIL_SOURCES = [
    {"label": "中国移动2022年半年度报告（新浪财经同文正文）", "url": CM_2022_H1_SINA_URL, "evidence": "A股半年报比较栏披露H1 2021营业收入443,647百万元、营业成本313,138百万元、营业利润77,436百万元、经营现金流161,618百万元、购建长期资产现金支出87,575百万元。"},
    {"label": "中国移动2022年第一季度报告（新浪财经同文正文）", "url": CM_2022_Q1_SINA_URL, "evidence": "A股一季报比较栏披露Q1 2021营业收入198,429百万元、营业成本147,000百万元、营业利润31,252百万元、经营现金流76,272百万元、购建长期资产现金支出33,755百万元。"},
    {"label": "中国移动2020年第一季度未经审核主要经营数据（HKEX）", "url": CM_2020_Q1_HKEX_URL, "evidence": "2020Q1公告披露Operating revenue 181.3十亿元。"},
    {"label": "中国移动2020中期报告", "url": CM_2020_INTERIM_REPORT_URL, "evidence": "中期报告披露H1 2020 Operating revenue 389,863百万元。"},
    {"label": "中国移动2021中期报告", "url": CM_2021_INTERIM_REPORT_URL, "evidence": "H股中期报告披露H1 2021 Operating revenue 443,647百万元、EBITDA 161,988百万元、股东应占利润59,118百万元、现金274,143百万元、总资产1,800,453百万元。"},
]

CM_2021_Q3_DETAIL_SOURCES = [
    {"label": "中国移动2022年第三季度报告（新浪财经同文正文）", "url": CM_2022_Q3_SINA_URL, "evidence": "A股三季报比较栏披露Q3 2021营业收入204,983百万元、9M 2021营业收入648,630百万元、EBITDA 237,500百万元、经营现金流249,116百万元。"},
    {"label": "中国移动2022年半年度报告（新浪财经同文正文）", "url": CM_2022_H1_SINA_URL, "evidence": "A股半年报比较栏提供H1 2021累计值，用于由9M比较栏拆分Q3。"},
    {"label": "中国移动2020年前三季度未经审核主要经营数据（HKEX）", "url": CM_2020_Q3_HKEX_URL, "evidence": "2020年前三季度公告披露Operating revenue 574.4十亿元。"},
    {"label": "中国移动2020中期报告", "url": CM_2020_INTERIM_REPORT_URL, "evidence": "中期报告披露H1 2020 Operating revenue 389,863百万元。"},
    {"label": "中国移动2021中期报告", "url": CM_2021_INTERIM_REPORT_URL, "evidence": "H股中期报告披露H1 2021核心经营和财务报表，用于交叉核验拆分基数。"},
]

CM_2021_Q4_DETAIL_SOURCES = [
    {"label": "中国移动2022年年度报告（新浪财经同文正文）", "url": CM_2022_ANNUAL_SINA_URL, "evidence": "A股年报比较栏披露FY 2021营业收入848,258百万元、营业成本603,905百万元、营业利润151,994百万元、归母净利润115,937百万元、经营现金流314,764百万元、总资产1,806,027百万元。"},
    {"label": "中国移动2022年第三季度报告（新浪财经同文正文）", "url": CM_2022_Q3_SINA_URL, "evidence": "A股三季报比较栏提供9M 2021累计值，用于由全年比较栏拆分Q4。"},
    {"label": "中国移动2020年前三季度未经审核主要经营数据（HKEX）", "url": CM_2020_Q3_HKEX_URL, "evidence": "2020年前三季度公告披露Operating revenue 574.4十亿元。"},
    {"label": "中国移动2020年度报告", "url": CM_2020_ANNUAL_REPORT_URL, "evidence": "2020年报披露FY 2020 Operating revenue 768,070百万元。"},
    {"label": "中国移动2021年度报告", "url": CM_2021_ANNUAL_REPORT_URL, "evidence": "H股年报披露FY 2021 Operating revenue 848,258百万元、EBITDA 311,008百万元、现金及现金等价物243,943百万元和租赁负债等年末财务表。"},
]

CM_2021_Q3_GAP_SOURCES = [
    {"label": "中国移动2022年第三季度报告（新浪财经同文正文）", "url": CM_2022_Q3_SINA_URL, "evidence": "三季报资产负债比较栏为2022-09-30对2021-12-31，未披露2021-09-30资产负债表。"},
    {"label": "中国移动2021中期报告", "url": CM_2021_INTERIM_REPORT_URL, "evidence": "中期报告披露2021-06-30资产负债表，但不覆盖2021-09-30时点。"},
    {"label": "中国移动2021年度报告", "url": CM_2021_ANNUAL_REPORT_URL, "evidence": "年报披露2021-12-31资产负债表，但不覆盖2021-09-30时点。"},
]

CM_2024_Q1_Q2_SOURCES = [
    {"label": "中国移动官网2024单季度经营数据", "url": CM_2024_OPERATION_URL, "evidence": "官网直接列示2024/1Q和2024/2Q Operating Revenue、Revenue from Telecommunications Services、EBITDA和Profit Attributable to Equity Shareholders。"},
    {"label": "中国移动2024中期报告", "url": CM_2024_H1_REPORT_URL, "evidence": "2024中期报告披露H1 2024 Operating Revenue 546,744、Revenue from Telecommunications Services 463,589、EBITDA 182,270和股东应占利润80,201百万元，用于交叉核验Q1+Q2。"},
    {"label": "中国移动2024年报", "url": CM_2024_ANNUAL_REPORT_URL, "evidence": "2024年报披露全年Operating revenue 1,040,759、Revenue from telecommunications services 889,468、EBITDA 333,691和股东应占利润138,373百万元。"},
]

CM_2024_Q1_DETAIL_SOURCES = [
    {"label": "中国移动2024年第一季度报告（巨潮资讯原文）", "url": CM_2024_Q1_CNINFO_URL, "evidence": "一季报披露营业收入、营业成本、营业利润、资产负债表和现金流量表。"},
    {"label": "中国移动2024年第一季度报告（新浪财经正文）", "url": CM_2024_Q1_SINA_URL, "evidence": "新浪财经公告正文镜像列示同一份2024年第一季度报告，用于交叉核验表格。"},
    {"label": "中国移动官网2024单季度经营数据", "url": CM_2024_OPERATION_URL, "evidence": "官网直接列示2024/1Q核心经营数据，用于交叉核验营运收入、主营业务收入、EBITDA和归母利润。"},
]

CM_2024_Q2_DETAIL_SOURCES = [
    {"label": "中国移动2024年半年度报告（新浪财经同文正文）", "url": CM_2024_H1_SINA_URL, "evidence": "同文公告正文列示A股半年报完整财务表：H1营业收入546,744百万元、营业成本378,285百万元、营业利润102,506百万元、经营现金流131,377百万元、购建长期资产现金支出73,460百万元。"},
    {"label": "中国移动2024年中期报告（中国移动官网）", "url": CM_2024_H1_REPORT_URL, "evidence": "公司官网中期报告披露H1核心经营和财务数据，用于交叉核验累计关系。"},
    {"label": "中国移动2024年第一季度报告（巨潮资讯原文）", "url": CM_2024_Q1_CNINFO_URL, "evidence": "一季报提供Q1营业收入、营业成本、营业利润、现金流和资产负债表数，用于由H1累计数拆分Q2。"},
    {"label": "中国移动官网2024单季度经营数据", "url": CM_2024_OPERATION_URL, "evidence": "官网直接列示2024/2Q核心经营数据，用于交叉核验Q2收入、EBITDA和归母利润。"},
]

CM_2024_Q3_DETAIL_SOURCES = [
    {"label": "中国移动2024年第三季度报告（巨潮资讯原文）", "url": CM_2024_Q3_CNINFO_URL, "evidence": "三季报披露9M营业收入791,458百万元、营业成本547,590百万元、营业利润141,479百万元、经营现金流224,075百万元、购建长期资产现金支出116,855百万元。"},
    {"label": "中国移动2024年第三季度报告（新浪财经同文正文）", "url": CM_2024_Q3_SINA_URL, "evidence": "新浪财经公告正文镜像列示同一份2024年第三季度报告，用于交叉核验表格。"},
    {"label": "中国移动2024年半年度报告（新浪财经同文正文）", "url": CM_2024_H1_SINA_URL, "evidence": "A股半年报完整财务表提供H1累计数，用于由9M累计数拆分Q3。"},
    {"label": "中国移动官网2024单季度经营数据", "url": CM_2024_OPERATION_URL, "evidence": "官网直接列示2024/3Q核心经营数据，用于交叉核验Q3收入、EBITDA和归母利润。"},
]

CM_2024_Q4_DETAIL_SOURCES = [
    {"label": "中国移动2024年年度报告（新浪财经同文正文）", "url": CM_2024_ANNUAL_SINA_URL, "evidence": "同文公告正文列示A股年报完整财务表：全年营业收入1,040,759百万元、营业成本738,772百万元、营业利润176,284百万元、经营现金流315,741百万元、购建长期资产现金支出155,979百万元。"},
    {"label": "中国移动2024年年度报告（中国移动官网）", "url": CM_2024_ANNUAL_REPORT_URL, "evidence": "公司官网年报披露全年核心经营和财务数据，用于交叉核验全年合计。"},
    {"label": "中国移动2024年第三季度报告（巨潮资讯原文）", "url": CM_2024_Q3_CNINFO_URL, "evidence": "A股三季报完整财务表提供9M累计数，用于由全年数拆分Q4。"},
]

CM_2024_Q3_Q4_SOURCES = [
    {"label": "中国移动官网2024单季度经营数据", "url": CM_2024_OPERATION_URL, "evidence": "官网直接列示2024/3Q和2024/4Q Operating Revenue、Revenue from Telecommunications Services、EBITDA和Profit Attributable to Equity Shareholders。"},
    {"label": "中国移动2024第三季度报告", "url": CM_2024_Q3_CNINFO_URL, "evidence": "2024前三季度报告披露前三季度营业收入791,458百万元、净利润110,984百万元等累计财务表。"},
    {"label": "中国移动2024年报", "url": CM_2024_ANNUAL_REPORT_URL, "evidence": "2024年报披露全年Operating revenue 1,040,759、Revenue from telecommunications services 889,468、EBITDA 333,691和股东应占利润138,373百万元，用于交叉核验全年合计。"},
]

CM_2025_Q3_DIRECT_SOURCES = [
    {"label": "中国移动官网2025单季度经营数据", "url": CM_2025_OPERATION_URL, "evidence": "官网直接列示2025/3Q收入、通信服务收入、EBITDA和归母利润。"},
    {"label": "中国移动2025前三季度业绩（港交所）", "url": CM_2025_Q3_HKEX_URL, "evidence": "前三季度精确累计值及财务报表。"},
    {"label": "中国移动2025中期报告（港交所）", "url": CM_2025_H1_HKEX_URL, "evidence": "上半年精确累计值，用于从前三季度累计值复算Q3。"},
]

CM_2025_Q3_STATEMENT_SOURCES = [
    {"label": "中国移动2025前三季度业绩（港交所）", "url": CM_2025_Q3_HKEX_URL, "evidence": "前三季度资产负债表和现金流量表精确值。"},
    {"label": "中国移动官网2025前三季度业绩镜像", "url": CM_2025_Q3_COMPANY_URL, "evidence": "公司官网发布的同期官方公告镜像。"},
    {"label": "中国移动2025中期报告（港交所）", "url": CM_2025_H1_HKEX_URL, "evidence": "上半年现金流量精确累计值，用于复算Q3流量指标。"},
]

CM_2025_Q2_DETAIL_SOURCES = [
    {"label": "中国移动2025年半年度报告（巨潮资讯原文）", "url": CM_2025_H1_CNINFO_URL, "evidence": "半年报A股口径披露H1营业收入543,769百万元、营业成本371,851百万元、营业利润106,295百万元、资产总计2,092,440百万元和租赁负债明细。"},
    {"label": "中国移动2025年半年度报告摘要（新浪财经正文）", "url": CM_2025_H1_SINA_URL, "evidence": "同文摘要披露H1营业收入5,438亿元、营业利润1,063亿元、资产总额20,924亿元，用于交叉核验。"},
    {"label": "中国移动2025中期报告（港交所）", "url": CM_2025_H1_HKEX_URL, "evidence": "港交所中期报告披露H1经营现金流、购建长期资产现金支出和现金及现金等价物余额。"},
    {"label": "中国移动2025年第一季度报告（上交所）", "url": CM_2025_Q1_SSE_URL, "evidence": "一季报提供Q1营业收入、营业成本、营业利润、现金流和资产负债表数，用于由H1累计数拆分Q2。"},
    {"label": "中国移动2025年第一季度报告（新浪财经正文）", "url": CM_2025_Q1_SINA_URL, "evidence": "新浪财经公告正文镜像列示同一份一季报，用于交叉核验Q1表格。"},
]

CM_2025_Q3_DETAIL_SOURCES = [
    {"label": "中国移动2025年第三季度报告（新浪财经正文）", "url": CM_2025_Q3_SINA_URL, "evidence": "同文公告正文列示2025年前三季度营业收入794,666百万元、营业成本547,635百万元、营业利润145,704百万元、资产总计2,073,824百万元和债务项目。"},
    {"label": "中国移动2025年第三季度报告（雪球PDF镜像）", "url": CM_2025_Q3_XUEQIU_URL, "evidence": "PDF镜像列示同一份A股三季报财务表，用于交叉核验9M累计数。"},
    {"label": "中国移动2025年半年度报告（巨潮资讯原文）", "url": CM_2025_H1_CNINFO_URL, "evidence": "A股半年报完整财务表提供H1累计数，用于由9M累计数拆分Q3。"},
    {"label": "中国移动2025前三季度业绩（港交所）", "url": CM_2025_Q3_HKEX_URL, "evidence": "港交所前三季度业绩披露IFRS口径9M现金流和资产负债表，用于核验时点现金和总资产。"},
]

CM_2025_Q4_ANNUAL_SOURCES = [
    {"label": "中国移动2025年报（港交所）", "url": CM_2025_ANNUAL_HKEX_URL, "evidence": "2025全年财务报表和管理层讨论。"},
    {"label": "中国移动2025全年业绩演示", "url": CM_2025_ANNUAL_RESULTS_URL, "evidence": "列示全年营运收入1,050,187、主营业务收入895,530、净利润137,095、EBITDA338,931百万元。"},
    {"label": "中国移动2025前三季度业绩（港交所）", "url": CM_2025_Q3_HKEX_URL, "evidence": "前三季度累计值，用于由全年数复算Q4。"},
]

CM_2025_Q4_DETAIL_SOURCES = [
    {"label": "中国移动2025年年度报告（新浪财经正文）", "url": CM_2025_ANNUAL_SINA_URL, "evidence": "同文公告正文列示A股年报完整财务表：全年营业收入1,050,187百万元、营业成本747,016百万元、营业利润178,444百万元、年末资产总计2,092,882百万元和债务项目。"},
    {"label": "中国移动2025年报（港交所）", "url": CM_2025_ANNUAL_HKEX_URL, "evidence": "公司年报披露全年核心经营、利润表、资产负债表和现金流量表，用于交叉核验全年合计。"},
    {"label": "中国移动2025年第三季度报告（新浪财经正文）", "url": CM_2025_Q3_SINA_URL, "evidence": "A股三季报完整财务表提供9M累计数，用于由全年数拆分Q4。"},
    {"label": "中国移动2025年度报告摘要（上海证券报）", "url": CM_2025_ANNUAL_CN_SUMMARY_URL, "evidence": "中文摘要披露2025年营业收入10,502亿元、营业利润1,784亿元和资产总额20,929亿元。"},
]

CM_2025_Q4_CASH_FLOW_SOURCES = [
    {"label": "中国移动2025年报（港交所）", "url": CM_2025_ANNUAL_HKEX_URL, "evidence": "全年现金流量表。"},
    {"label": "中国移动2025年报正文镜像（新浪财经）", "url": CM_2025_ANNUAL_SINA_URL, "evidence": "列示经营现金流232,919、购建长期资产现金支出156,951、年末现金及现金等价物97,267百万元。"},
    {"label": "中国移动2025前三季度业绩（港交所）", "url": CM_2025_Q3_HKEX_URL, "evidence": "前三季度现金流累计值，用于复算Q4流量指标。"},
]

CM_2025_Q4_BALANCE_SHEET_SOURCES = [
    {"label": "中国移动2025年报（港交所）", "url": CM_2025_ANNUAL_HKEX_URL, "evidence": "年末资产负债表。"},
    {"label": "中国移动2025年度报告摘要（上海证券报）", "url": CM_2025_ANNUAL_CN_SUMMARY_URL, "evidence": "中文摘要列示2025年底资产总额20,929亿元、总现金及银行结存2,328亿元。"},
    {"label": "中国移动2025年度业绩公告（港交所）", "url": CM_2025_ANNUAL_HKEX_RESULTS_URL, "evidence": "公告现金流量表列示年末现金及现金等价物97,267百万元。"},
]

CM_2025_Q1_DETAIL_SOURCES = [
    {"label": "中国移动2025年第一季度报告（上交所）", "url": CM_2025_Q1_SSE_URL, "evidence": "交易所公告原文披露主要财务数据、合并利润表、合并资产负债表和合并现金流量表。"},
    {"label": "中国移动2025年第一季度报告（新浪财经正文）", "url": CM_2025_Q1_SINA_URL, "evidence": "新浪财经公告正文镜像列示同一份一季报表格，用于交叉核验具体行。"},
    {"label": "中国移动2025年第一季度报告（东方财富公告索引）", "url": CM_2025_Q1_EASTMONEY_URL, "evidence": "东方财富公告页定位同一公告，并提示以交易所公告为有效信息。"},
]

CM_2026_Q1_SOURCES = [
    {"label": "中国移动2026年第一季度报告（巨潮资讯原文）", "url": CM_2026_Q1_CNINFO_URL, "evidence": "一季报披露主要财务指标、资产负债表、利润表和现金流量表。"},
    {"label": "中国移动2026年第一季度报告（新浪财经正文）", "url": CM_2026_Q1_SINA_URL, "evidence": "新浪财经公告正文镜像列示同一份2026年第一季度报告，用于交叉核验表格。"},
    {"label": "星岛头条中国移动首季业绩报道", "url": CM_2026_Q1_STHEADLINE_URL, "evidence": "报道摘录营运收入、主营业务收入、EBITDA、净利润、资本开支和期末现金及现金等价物。"},
]

CT_2025_Q1_HKEX_URL = "https://doc.irasia.com/listco/hk/chinatelecom/interim/2025/int1q.pdf"
CT_2025_Q1_CN_URL = "https://doc.irasia.com/listco/cn/chinatelecom/announcement/sca250426c.pdf"
CT_2025_H1_HKEX_URL = "https://doc.irasia.com/listco/hk/chinatelecom/interim/2025/int.pdf"
CT_2025_H1_CN_SUMMARY_URL = "https://doc.irasia.com/listco/cn/chinatelecom/announcement/sca250815.pdf"
CT_2025_H1_SINA_SUMMARY_URL = "https://money.finance.sina.com.cn/corp/view/vCB_AllBulletinDetail.php?id=11299464&stockid=601728"
CT_2025_Q3_HKEX_URL = "https://doc.irasia.com/listco/hk/chinatelecom/interim/2025/int3q.pdf"
CT_2025_Q3_CN_URL = "https://doc.irasia.com/listco/cn/chinatelecom/announcement/sca251022.pdf"
CT_2025_Q3_SINA_URL = "https://money.finance.sina.com.cn/corp/view/vCB_AllBulletinDetail.php?id=11523338&stockid=601728"
CT_2025_ANNUAL_RESULTS_URL = "https://www.chinatelecom-h.com/en/media/press/p260324.pdf"
CT_2025_ANNUAL_ASHARE_URL = "https://www.chinatelecom-h.com/sc/ir/report/annual2025_ashare.pdf"
CT_2025_ANNUAL_SUMMARY_CNINFO_URL = "https://dataclouds.cninfo.com.cn/shgonggao/hsomarket/2026/20260324/a5332b5875774b298ffa4807c14d8f4c.PDF"
CT_2025_ANNUAL_SINA_URL = "https://vip.stock.finance.sina.com.cn/corp/view/vCB_AllBulletinDetail.php?id=12013734&stockid=601728"
CT_KEY_FINANCIAL_DATA_URL = "https://www.chinatelecom-h.com/en/ir/finhigh_keyfindata_quarterly.php"
CT_2026_Q1_CNINFO_URL = "https://static.cninfo.com.cn/finalpage/2026-04-24/1225159634.PDF"
CT_2026_Q1_XUEQIU_MIRROR_URL = "https://stockmc.xueqiu.com/202604/601728_20260424_X6X2.pdf"
CT_2026_Q1_SINA_URL = "https://money.finance.sina.com.cn/corp/view/vCB_AllBulletinDetail.php?id=12158482&stockid=601728"
CT_REPORTS_PAGE_URL = "https://www.chinatelecom-h.com/sc/ir/reports.php"
CT_2023_Q1_HKEX_URL = "https://doc.irasia.com/listco/hk/chinatelecom/interim/2023/int1q.pdf"
CT_2023_Q1_CN_URL = "https://doc.irasia.com/listco/cn/chinatelecom/announcement/sca230421b.pdf"
CT_2023_H1_HKEX_URL = "https://doc.irasia.com/listco/hk/chinatelecom/interim/2023/int.pdf"
CT_2023_H1_SINA_URL = "https://vip.stock.finance.sina.com.cn/corp/view/vCB_AllBulletinDetail.php?id=9393219&stockid=601728"
CT_2023_Q3_HKEX_URL = "https://doc.irasia.com/listco/hk/chinatelecom/interim/2023/int3q.pdf"
CT_2023_Q3_CN_URL = "https://doc.irasia.com/listco/cn/chinatelecom/announcement/sca231021e.pdf"
CT_2023_ANNUAL_RESULTS_URL = "https://doc.irasia.com/listco/hk/chinatelecom/annual/2023/res.pdf"
CT_2023_ANNUAL_ASHARE_URL = "https://www.chinatelecom-h.com/sc/ir/report/annual2023_ashare.pdf"
CT_2023_ANNUAL_SUMMARY_CN_URL = "https://doc.irasia.com/listco/cn/chinatelecom/announcement/sca240327u.pdf"
CT_2023_ANNUAL_SINA_URL = "https://money.finance.sina.com.cn/corp/view/vCB_AllBulletinDetail.php?id=9899089&stockid=601728"
CT_2022_Q1_HKEX_URL = "https://doc.irasia.com/listco/hk/chinatelecom/interim/2022/int1q.pdf"
CT_2022_H1_HKEX_URL = "https://www.chinatelecom-h.com/en/ir/report/interim2022.pdf"
CT_2022_Q3_HKEX_URL = "https://doc.irasia.com/listco/hk/chinatelecom/interim/2022/int3q.pdf"
CT_2022_ANNUAL_REPORT_URL = "https://www.chinatelecom-h.com/en/ir/report/annual2022.pdf"
CT_2021_Q1_HKEX_URL = "https://doc.irasia.com/listco/hk/chinatelecom/interim/2021/int1q.pdf"
CT_2021_H1_HKEX_URL = "https://www.chinatelecom-h.com/en/ir/report/interim2021.pdf"
CT_2021_Q3_HKEX_URL = "https://doc.irasia.com/listco/hk/chinatelecom/interim/2021/int3q.pdf"
CT_2021_ANNUAL_REPORT_URL = "https://www.chinatelecom-h.com/en/ir/report/annual2021.pdf"
CT_2020_Q1_HKEX_URL = "https://doc.irasia.com/listco/hk/chinatelecom/interim/2020/int1q.pdf"
CT_2020_H1_HKEX_URL = "https://www.chinatelecom-h.com/en/ir/report/interim2020.pdf"
CT_2020_Q3_HKEX_URL = "https://doc.irasia.com/listco/hk/chinatelecom/interim/2020/int3q.pdf"
CT_2020_ANNUAL_REPORT_URL = "https://www.chinatelecom-h.com/en/ir/report/annual2020.pdf"
CT_2020_ANNUAL_PRESENTATION_URL = "https://www.chinatelecom-h.com/en/ir/presentations/annpre210309.pdf"
CT_2019_Q1_HKEX_URL = "https://doc.irasia.com/listco/hk/chinatelecom/interim/2019/int1q.pdf"
CT_2019_H1_HKEX_URL = "https://www.chinatelecom-h.com/en/ir/report/interim2019.pdf"
CT_2019_Q3_HKEX_URL = "https://doc.irasia.com/listco/hk/chinatelecom/interim/2019/int3q.pdf"
CT_2019_ANNUAL_REPORT_URL = "https://www.chinatelecom-h.com/en/ir/report/annual2019.pdf"
CT_2019_ANNUAL_FINANCIAL_REVIEW_URL = "https://www.chinatelecom-h.com/en/ir/report/annual2019/annual2019_10.pdf"
CT_2019_ANNUAL_PRESENTATION_CHECK_URL = "https://www.chinatelecom-h.com/en/ir/presentations/annpre210309.pdf"
CT_2018_Q1_HKEX_URL = "https://doc.irasia.com/listco/hk/chinatelecom/interim/2018/int1q.pdf"
CT_2018_H1_HKEX_URL = "https://www.chinatelecom-h.com/en/ir/report/interim2018.pdf"
CT_2018_Q3_HKEX_URL = "https://doc.irasia.com/listco/hk/chinatelecom/interim/2018/int3q.pdf"
CT_2018_ANNUAL_REPORT_URL = "https://www.chinatelecom-h.com/en/ir/report/annual2018.pdf"
CT_2017_Q1_HKEX_URL = "https://doc.irasia.com/listco/hk/chinatelecom/interim/2017/int1q.pdf"
CT_2017_H1_HKEX_URL = "https://www.chinatelecom-h.com/en/ir/report/interim2017.pdf"
CT_2017_Q3_HKEX_URL = "https://doc.irasia.com/listco/hk/chinatelecom/interim/2017/int3q.pdf"
CT_2017_ANNUAL_REPORT_URL = "https://www.chinatelecom-h.com/en/ir/report/annual2017.pdf"
CT_2016_Q1_HKEX_URL = "https://doc.irasia.com/listco/hk/chinatelecom/interim/2016/int1q.pdf"
CT_2016_H1_HKEX_URL = "https://www.chinatelecom-h.com/en/ir/report/interim2016.pdf"
CT_2016_Q3_HKEX_URL = "https://doc.irasia.com/listco/hk/chinatelecom/interim/2016/int3q.pdf"
CT_2016_ANNUAL_REPORT_URL = "https://www.chinatelecom-h.com/en/ir/report/annual2016.pdf"

CT_2021_Q1_SOURCES = [
    {"label": "中国电信2021年第一季度报告（IRAsia）", "url": CT_2021_Q1_HKEX_URL, "evidence": "一季度报告直接披露Q1 operating revenues 106,873、EBITDA 31,052和股东应占利润6,441百万元。"},
    {"label": "中国电信2021中期报告（公司官网）", "url": CT_2021_H1_HKEX_URL, "evidence": "中期报告披露H1 operating revenues 219,237、EBITDA 66,348和股东应占利润17,743百万元，用于交叉核验Q1+Q2。"},
    {"label": "中国电信2021年报（公司官网）", "url": CT_2021_ANNUAL_REPORT_URL, "evidence": "年报披露FY2021 operating revenues 439,552、EBITDA 123,912和股东应占利润25,948百万元，用于全年合计交叉核验。"},
]
CT_2024_Q1_HKEX_URL = "https://doc.irasia.com/listco/hk/chinatelecom/interim/2024/int1q.pdf"
CT_2024_Q1_CN_URL = "https://doc.irasia.com/listco/cn/chinatelecom/announcement/sca240424.pdf"
CT_2024_H1_HKEX_URL = "https://doc.irasia.com/listco/hk/chinatelecom/interim/2024/int.pdf"
CT_2024_H1_ASHARE_URL = "https://www.chinatelecom-h.com/sc/ir/report/interim2024_ashare.pdf"
CT_2024_H1_SUMMARY_CN_URL = "https://doc.irasia.com/listco/cn/chinatelecom/announcement/sca240821a.pdf"
CT_2024_Q3_HKEX_URL = "https://doc.irasia.com/listco/hk/chinatelecom/interim/2024/int3q.pdf"
CT_2024_Q3_CN_URL = "https://doc.irasia.com/listco/cn/chinatelecom/announcement/sca241023.pdf"
CT_2024_Q3_SINA_URL = "https://money.finance.sina.com.cn/corp/view/vCB_AllBulletinDetail.php?id=10536200&stockid=601728"
CT_2024_ANNUAL_RESULTS_URL = "https://doc.irasia.com/listco/hk/chinatelecom/annual/2024/respress.pdf"
CT_2024_ANNUAL_ASHARE_URL = "https://www.chinatelecom-h.com/sc/ir/report/annual2024_ashare.pdf"
CT_2024_ANNUAL_SUMMARY_CN_URL = "https://doc.irasia.com/listco/cn/chinatelecom/announcement/sca250326h.pdf"

CT_2023_Q1_SOURCES = [
    {"label": "中国电信2023年第一季度报告（IRAsia）", "url": CT_2023_Q1_HKEX_URL, "evidence": "一季度报告披露Q1经营收入130,588、服务收入118,478、EBITDA 33,874和股东应占利润7,984百万元。"},
    {"label": "中国电信2023中期报告（IRAsia）", "url": CT_2023_H1_HKEX_URL, "evidence": "中期报告披露H1累计值，用于交叉核验Q1+Q2。"},
]

CT_2023_Q1_DETAIL_SOURCES = [
    {"label": "中国电信2023年第一季度报告（港交所/IRAsia）", "url": CT_2023_Q1_HKEX_URL, "evidence": "港股一季报披露Operating revenues 130,588百万元、EBITDA 33,874百万元、经营现金流28,215百万元、资本开支14,504百万元、现金及现金等价物74,642百万元、总资产823,656百万元和债务项目。"},
    {"label": "中国电信2023年第一季度报告（IRAsia中文版）", "url": CT_2023_Q1_CN_URL, "evidence": "A股中文一季报披露营业收入129,753,222,753.19元、营业成本91,508,216,720.32元、营业利润10,676,454,808.71元、经营现金流28,214,572,383.01元、购建长期资产现金支出14,507,824,903.22元、期末现金及现金等价物74,642,215,335.44元和资产负债表。"},
    {"label": "中国电信官网财务报告页", "url": CT_REPORTS_PAGE_URL, "evidence": "公司官网投资者关系财务报告页列示季度、中期和年度报告入口，用于确认披露来源体系。"},
]

CT_2023_Q2_SOURCES = [
    {"label": "中国电信2023年第一季度报告（IRAsia）", "url": CT_2023_Q1_HKEX_URL, "evidence": "一季度累计值，用于从H1累计值复核Q2。"},
    {"label": "中国电信2023中期报告（IRAsia）", "url": CT_2023_H1_HKEX_URL, "evidence": "中期报告披露H1 Operating revenues 260,664、service revenues 235,977、EBITDA 73,346和股东应占利润20,153百万元。"},
]

CT_2023_Q2_DETAIL_SOURCES = [
    {"label": "中国电信2023年第一季度报告（IRAsia中文版）", "url": CT_2023_Q1_CN_URL, "evidence": "A股一季报披露Q1营业收入129,753.223百万元、营业成本91,508.217百万元、营业利润10,676.455百万元、经营现金流28,214.572百万元、购建长期资产现金支出14,507.825百万元、现金及现金等价物和债务组成。"},
    {"label": "中国电信2023中期报告（港交所/IRAsia）", "url": CT_2023_H1_HKEX_URL, "evidence": "中期报告披露H1经营收入、服务收入、EBITDA、净利润、资本开支和自由现金流，用于交叉核验Q2拆分。"},
    {"label": "中国电信2023半年度报告（新浪财经正文）", "url": CT_2023_H1_SINA_URL, "evidence": "新浪财经公告正文镜像列示H1 A股报表，披露营业收入258,679.060百万元、营业成本179,122.365百万元、营业利润27,193.810百万元、经营现金流65,663.264百万元、购建长期资产现金支出28,325.631百万元、期末现金及现金等价物83,698.046百万元和资产负债表。"},
]

CT_2023_Q3_SOURCES = [
    {"label": "中国电信2023中期报告（IRAsia）", "url": CT_2023_H1_HKEX_URL, "evidence": "H1累计值用于从前三季度累计值复核Q3。"},
    {"label": "中国电信2023年前三季度报告（IRAsia）", "url": CT_2023_Q3_HKEX_URL, "evidence": "前三季度公告披露Operating revenues 384,254、service revenues 349,743、EBITDA 105,648和股东应占利润27,101百万元。"},
]

CT_2023_Q3_DETAIL_SOURCES = [
    {"label": "中国电信2023半年度报告（新浪财经正文）", "url": CT_2023_H1_SINA_URL, "evidence": "H1 A股累计值用于从前三季度A股累计值复算Q3营业成本、营业利润、经营现金流和资本开支。"},
    {"label": "中国电信2023年前三季度报告（港交所/IRAsia）", "url": CT_2023_Q3_HKEX_URL, "evidence": "港股前三季度报告披露Operating revenues 384,254百万元、Cash and cash equivalents 82,445百万元、Total assets 835,598百万元及债务项目。"},
    {"label": "中国电信2023年前三季度报告（IRAsia中文版）", "url": CT_2023_Q3_CN_URL, "evidence": "中文版三季报披露前三季度营业收入381,102.561百万元、营业成本266,329.187百万元、营业利润36,730.645百万元、经营现金流112,990.181百万元、购建长期资产现金支出60,719.649百万元和资产负债表。"},
]

CT_2023_Q4_SOURCES = [
    {"label": "中国电信2023年前三季度报告（IRAsia）", "url": CT_2023_Q3_HKEX_URL, "evidence": "前三季度累计值用于从全年披露复核Q4。"},
    {"label": "中国电信2023年度业绩公告（IRAsia）", "url": CT_2023_ANNUAL_RESULTS_URL, "evidence": "年度业绩公告披露全年Operating revenues 513,551、service revenues 464,965、EBITDA 136,830和股东应占利润30,446百万元。"},
]

CT_2023_Q4_DETAIL_SOURCES = [
    {"label": "中国电信2023年前三季度报告（IRAsia中文版）", "url": CT_2023_Q3_CN_URL, "evidence": "前三季度A股累计值用于从全年A股年报复算Q4营业收入、营业成本、营业利润、经营现金流和资本开支。"},
    {"label": "中国电信2023年度A股年报", "url": CT_2023_ANNUAL_ASHARE_URL, "evidence": "A股年报披露2023全年营业收入507,842.675百万元、营业成本361,422.204百万元、营业利润42,569.104百万元、经营现金流138,623.059百万元、购建长期资产现金支出90,173.725百万元、年末现金及现金等价物81,045.623百万元和资产负债表。"},
    {"label": "中国电信2023年度报告摘要（IRAsia中文版）", "url": CT_2023_ANNUAL_SUMMARY_CN_URL, "evidence": "年度报告摘要披露全年营业收入、营业成本、经营现金流等关键行，用于交叉核验A股年报。"},
    {"label": "中国电信2023年年度报告（新浪财经正文）", "url": CT_2023_ANNUAL_SINA_URL, "evidence": "新浪财经公告正文镜像列示同一份年报表格，用于交叉核验资产、现金、债务和利润表行项目。"},
]

CT_2022_Q1_SOURCES = [
    {"label": "中国电信2022年第一季度报告（IRAsia）", "url": CT_2022_Q1_HKEX_URL, "evidence": "一季报披露Q1 operating revenues 119,629、EBITDA 32,361和股东应占利润7,223百万元。"},
    {"label": "中国电信2022中期报告（公司官网）", "url": CT_2022_H1_HKEX_URL, "evidence": "中期报告披露H1 operating revenues 242,319、EBITDA 69,848和股东应占利润18,291百万元，用于交叉核验Q1+Q2。"},
]

CT_2022_Q2_SOURCES = [
    {"label": "中国电信2022年第一季度报告（IRAsia）", "url": CT_2022_Q1_HKEX_URL, "evidence": "一季报提供Q1累计值，用于从H1累计值复算Q2。"},
    {"label": "中国电信2022中期报告（公司官网）", "url": CT_2022_H1_HKEX_URL, "evidence": "中期报告披露H1 operating revenues 242,319、EBITDA 69,848和股东应占利润18,291百万元。"},
    {"label": "中国电信2022年报（公司官网）", "url": CT_2022_ANNUAL_REPORT_URL, "evidence": "年报披露FY2022 operating revenues 481,448、EBITDA 130,359和股东应占利润27,593百万元，用于全年合计交叉核验。"},
]

CT_2022_Q3_SOURCES = [
    {"label": "中国电信2022中期报告（公司官网）", "url": CT_2022_H1_HKEX_URL, "evidence": "中期报告提供H1累计值，用于从9M累计值复算Q3。"},
    {"label": "中国电信2022年前三季度报告（IRAsia）", "url": CT_2022_Q3_HKEX_URL, "evidence": "前三季度报告披露9M operating revenues 360,982、EBITDA 100,458和股东应占利润24,543百万元。"},
    {"label": "中国电信2022年报（公司官网）", "url": CT_2022_ANNUAL_REPORT_URL, "evidence": "年报披露全年核心经营数据，用于交叉核验9M与全年合计关系。"},
]

CT_2022_Q4_SOURCES = [
    {"label": "中国电信2022年前三季度报告（IRAsia）", "url": CT_2022_Q3_HKEX_URL, "evidence": "前三季度报告提供9M累计值，用于从FY累计值复算Q4。"},
    {"label": "中国电信2022年报（公司官网）", "url": CT_2022_ANNUAL_REPORT_URL, "evidence": "年报披露FY2022 operating revenues 481,448、EBITDA 130,359和股东应占利润27,593百万元。"},
    {"label": "中国电信2022中期报告（公司官网）", "url": CT_2022_H1_HKEX_URL, "evidence": "中期报告提供H1累计值，用于交叉核验2022拆分链路。"},
]

CT_2021_Q2_SOURCES = [
    {"label": "中国电信2021年第一季度报告（IRAsia）", "url": CT_2021_Q1_HKEX_URL, "evidence": "一季报披露Q1 operating revenues 106,873、EBITDA 31,052和股东应占利润6,441百万元。"},
    {"label": "中国电信2021中期报告（公司官网）", "url": CT_2021_H1_HKEX_URL, "evidence": "中期报告披露H1 operating revenues 219,237、EBITDA 66,348和股东应占利润17,743百万元。"},
    {"label": "中国电信2021年报（公司官网）", "url": CT_2021_ANNUAL_REPORT_URL, "evidence": "年报披露FY2021 operating revenues 439,552、EBITDA 123,912和股东应占利润25,948百万元，用于全年合计交叉核验。"},
]

CT_2021_Q3_SOURCES = [
    {"label": "中国电信2021中期报告（公司官网）", "url": CT_2021_H1_HKEX_URL, "evidence": "中期报告提供H1累计值，用于从9M累计值复算Q3。"},
    {"label": "中国电信2021年前三季度报告（IRAsia）", "url": CT_2021_Q3_HKEX_URL, "evidence": "前三季度报告披露9M operating revenues 329,241、EBITDA 96,348和股东应占利润23,327百万元。"},
    {"label": "中国电信2021年报（公司官网）", "url": CT_2021_ANNUAL_REPORT_URL, "evidence": "年报披露全年核心经营数据，用于交叉核验9M与全年合计关系。"},
]

CT_2021_Q4_SOURCES = [
    {"label": "中国电信2021年前三季度报告（IRAsia）", "url": CT_2021_Q3_HKEX_URL, "evidence": "前三季度报告提供9M累计值，用于从FY累计值复算Q4。"},
    {"label": "中国电信2021年报（公司官网）", "url": CT_2021_ANNUAL_REPORT_URL, "evidence": "年报披露FY2021 operating revenues 439,552、EBITDA 123,912和股东应占利润25,948百万元。"},
    {"label": "中国电信2021中期报告（公司官网）", "url": CT_2021_H1_HKEX_URL, "evidence": "中期报告提供H1累计值，用于交叉核验2021拆分链路。"},
]

CT_2020_Q1_SOURCES = [
    {"label": "中国电信2020年第一季度报告（IRAsia）", "url": CT_2020_Q1_HKEX_URL, "evidence": "一季度报告直接披露Q1 operating revenues 94,793、service revenues 92,137、EBITDA 30,161和股东应占利润5,822百万元。"},
    {"label": "中国电信2020中期报告（公司官网）", "url": CT_2020_H1_HKEX_URL, "evidence": "中期报告披露H1 operating revenues 193,803、service revenues 187,110、EBITDA 63,154和股东应占利润13,949百万元，用于交叉核验Q1+Q2。"},
    {"label": "中国电信2020全年业绩演示（公司官网）", "url": CT_2020_ANNUAL_PRESENTATION_URL, "evidence": "全年业绩演示披露FY2020 operating revenue 393,561、service revenue 373,798、EBITDA 118,880和Net Profit 20,850百万元，用于全年合计交叉核验。"},
]

CT_2020_Q2_SOURCES = [
    {"label": "中国电信2020年第一季度报告（IRAsia）", "url": CT_2020_Q1_HKEX_URL, "evidence": "一季度累计值用于从H1累计值复核Q2。"},
    {"label": "中国电信2020中期报告（公司官网）", "url": CT_2020_H1_HKEX_URL, "evidence": "中期报告披露H1 operating revenues 193,803、service revenues 187,110、EBITDA 63,154和股东应占利润13,949百万元。"},
    {"label": "中国电信2020全年业绩演示（公司官网）", "url": CT_2020_ANNUAL_PRESENTATION_URL, "evidence": "全年业绩演示披露FY2020核心经营值，用于年度链路交叉核验。"},
]

CT_2020_Q3_SOURCES = [
    {"label": "中国电信2020中期报告（公司官网）", "url": CT_2020_H1_HKEX_URL, "evidence": "H1累计值用于从前三季度累计值复核Q3。"},
    {"label": "中国电信2020年前三季度报告（IRAsia）", "url": CT_2020_Q3_HKEX_URL, "evidence": "前三季度报告披露9M operating revenues 292,614、service revenues 280,868、EBITDA 92,210和股东应占利润18,706百万元。"},
    {"label": "中国电信2020全年业绩演示（公司官网）", "url": CT_2020_ANNUAL_PRESENTATION_URL, "evidence": "全年业绩演示披露FY2020核心经营值，用于年度链路交叉核验。"},
]

CT_2020_Q4_SOURCES = [
    {"label": "中国电信2020年前三季度报告（IRAsia）", "url": CT_2020_Q3_HKEX_URL, "evidence": "前三季度报告提供9M累计值，用于从FY累计值复算Q4。"},
    {"label": "中国电信2020全年业绩演示（公司官网）", "url": CT_2020_ANNUAL_PRESENTATION_URL, "evidence": "全年业绩演示披露FY2020 operating revenue 393,561、service revenue 373,798、EBITDA 118,880和Net Profit 20,850百万元。"},
    {"label": "中国电信2020年报（公司官网）", "url": CT_2020_ANNUAL_REPORT_URL, "evidence": "年报披露2020全年经营收入和净利润等年度结果，用于交叉核验全年口径。"},
]

CT_2019_Q1_SOURCES = [
    {"label": "中国电信2019年第一季度报告（IRAsia）", "url": CT_2019_Q1_HKEX_URL, "evidence": "一季度报告直接披露Q1 operating revenues 96,135、service revenues 91,531、EBITDA 30,238和股东应占利润5,956百万元。"},
    {"label": "中国电信2019中期报告（公司官网）", "url": CT_2019_H1_HKEX_URL, "evidence": "中期报告披露H1 operating revenues 190,488、EBITDA 63,287和股东应占利润13,909百万元，用于交叉核验Q1+Q2。"},
    {"label": "中国电信2020年第一季度报告比较栏（公司官网/IRAsia）", "url": CT_2020_Q1_HKEX_URL, "evidence": "2020年一季度报告比较栏再次列示2019Q1 operating revenues 96,135、service revenues 91,531和股东应占利润5,956百万元。"},
]

CT_2019_Q2_SOURCES = [
    {"label": "中国电信2019年第一季度报告（IRAsia）", "url": CT_2019_Q1_HKEX_URL, "evidence": "一季度累计值用于从H1累计值复算Q2。"},
    {"label": "中国电信2019中期报告（公司官网）", "url": CT_2019_H1_HKEX_URL, "evidence": "中期报告披露H1 operating revenues 190,488、service revenues 182,589、EBITDA 63,287和股东应占利润13,909百万元。"},
    {"label": "中国电信2019年报财务回顾（公司官网）", "url": CT_2019_ANNUAL_FINANCIAL_REVIEW_URL, "evidence": "年报财务回顾披露FY2019 operating revenues 375,734、service revenues 357,610、EBITDA 117,215和股东应占利润20,517百万元，用于全年链路交叉核验。"},
]

CT_2019_Q3_SOURCES = [
    {"label": "中国电信2019中期报告（公司官网）", "url": CT_2019_H1_HKEX_URL, "evidence": "H1累计值用于从前三季度累计值复算Q3。"},
    {"label": "中国电信2019年前三季度报告（IRAsia）", "url": CT_2019_Q3_HKEX_URL, "evidence": "前三季度报告披露9M operating revenues 282,826、service revenues 271,484、EBITDA 91,973和股东应占利润18,389百万元。"},
    {"label": "中国电信2020年前三季度报告比较栏（公司官网/IRAsia）", "url": CT_2020_Q3_HKEX_URL, "evidence": "2020年前三季度报告比较栏再次列示2019年9M operating revenues 282,826、service revenues 271,484和股东应占利润18,389百万元。"},
]

CT_2019_Q4_SOURCES = [
    {"label": "中国电信2019年前三季度报告（IRAsia）", "url": CT_2019_Q3_HKEX_URL, "evidence": "前三季度报告提供9M累计值，用于从FY累计值复算Q4。"},
    {"label": "中国电信2019年报财务回顾（公司官网）", "url": CT_2019_ANNUAL_FINANCIAL_REVIEW_URL, "evidence": "年报财务回顾披露FY2019 operating revenues 375,734、service revenues 357,610、EBITDA 117,215和股东应占利润20,517百万元。"},
    {"label": "中国电信2020全年业绩演示比较栏（公司官网）", "url": CT_2019_ANNUAL_PRESENTATION_CHECK_URL, "evidence": "2020全年业绩演示比较栏列示2019 operating revenue 375,734、service revenue 357,610、EBITDA 117,215和Net Profit 20,517百万元。"},
]

CT_2024_Q1_SOURCES = [
    {"label": "中国电信官网Key Financial Data季度表", "url": CT_KEY_FINANCIAL_DATA_URL, "evidence": "官网季度表列示2024/Q1 Operating Revenue、Service Revenue、EBITDA和股东应占利润。"},
    {"label": "中国电信2024年第一季度报告（IRAsia）", "url": CT_2024_Q1_HKEX_URL, "evidence": "一季度报告披露Q1经营收入、服务收入、EBITDA和股东应占利润。"},
    {"label": "中国电信2024中期报告（IRAsia）", "url": CT_2024_H1_HKEX_URL, "evidence": "中期报告披露H1累计值，用于交叉核验Q1+Q2。"},
]

CT_2024_Q1_DETAIL_SOURCES = [
    {"label": "中国电信2024年第一季度报告（IRAsia英文版）", "url": CT_2024_Q1_HKEX_URL, "evidence": "一季报披露Q1经营收入、EBITDA、资产负债表和现金流量表。"},
    {"label": "中国电信2024年第一季度报告（IRAsia中文版）", "url": CT_2024_Q1_CN_URL, "evidence": "同一份一季报中文版披露营业收入、营业成本、营业利润、现金及现金等价物、借款和租赁负债。"},
    {"label": "中国电信官网Key Financial Data季度表", "url": CT_KEY_FINANCIAL_DATA_URL, "evidence": "官网季度表列示2024/Q1核心经营收入和利润指标，用于交叉核验。"},
]

CT_2024_Q2_SOURCES = [
    {"label": "中国电信官网Key Financial Data季度表", "url": CT_KEY_FINANCIAL_DATA_URL, "evidence": "官网季度表列示2024/Q2 Operating Revenue、Service Revenue、EBITDA和股东应占利润。"},
    {"label": "中国电信2024年第一季度报告（IRAsia）", "url": CT_2024_Q1_HKEX_URL, "evidence": "一季度累计值，用于从H1累计值复核Q2。"},
    {"label": "中国电信2024中期报告（IRAsia）", "url": CT_2024_H1_HKEX_URL, "evidence": "中期报告披露H1 Operating revenues 268.0十亿元、service revenues 246.2十亿元、EBITDA 76,792百万元和股东应占利润21,812百万元。"},
]

CT_2024_Q2_DETAIL_SOURCES = [
    {"label": "中国电信2024年第一季度报告（IRAsia中文版）", "url": CT_2024_Q1_CN_URL, "evidence": "A股一季报披露Q1营业收入134,494.563百万元、营业成本94,946.131百万元、营业利润12,316.258百万元、经营现金流20,861.776百万元、购建长期资产现金支出14,713.004百万元、现金及现金等价物和债务组成。"},
    {"label": "中国电信2024半年度A股报告", "url": CT_2024_H1_ASHARE_URL, "evidence": "A股半年报披露H1营业收入265,973.119百万元、营业成本183,956.774百万元、营业利润29,395.845百万元、经营现金流58,340.551百万元、购建长期资产现金支出35,034.567百万元、期末现金及现金等价物75,072.147百万元和资产负债表。"},
    {"label": "中国电信2024半年度报告摘要（IRAsia中文版）", "url": CT_2024_H1_SUMMARY_CN_URL, "evidence": "半年度报告摘要披露H1营业收入、营业成本、经营现金流和总资产，用于交叉核验完整半年报。"},
    {"label": "中国电信2024中期业绩公告（港交所/IRAsia）", "url": CT_2024_H1_HKEX_URL, "evidence": "中期业绩公告披露H1经营收入、服务收入、EBITDA、资本开支和自由现金流，用于交叉核验Q2拆分。"},
]

CT_2024_Q3_SOURCES = [
    {"label": "中国电信官网Key Financial Data季度表", "url": CT_KEY_FINANCIAL_DATA_URL, "evidence": "官网季度表列示2024/Q3 Operating Revenue、Service Revenue、EBITDA和股东应占利润。"},
    {"label": "中国电信2024中期报告（IRAsia）", "url": CT_2024_H1_HKEX_URL, "evidence": "H1累计值用于从前三季度累计值复核Q3。"},
    {"label": "中国电信2024年前三季度报告（IRAsia）", "url": CT_2024_Q3_HKEX_URL, "evidence": "前三季度公告披露经营收入、服务收入、EBITDA和利润累计值。"},
]

CT_2024_Q3_DETAIL_SOURCES = [
    {"label": "中国电信2024半年度A股报告", "url": CT_2024_H1_ASHARE_URL, "evidence": "H1 A股累计值用于从前三季度A股累计值复算Q3营业成本、营业利润、经营现金流和资本开支。"},
    {"label": "中国电信2024年前三季度报告（港交所/IRAsia）", "url": CT_2024_Q3_HKEX_URL, "evidence": "港股前三季度报告披露Operating revenues 394.7十亿元、service revenues 362.9十亿元、EBITDA 111.0十亿元和股东应占利润29.3十亿元。"},
    {"label": "中国电信2024年前三季度报告（IRAsia中文版）", "url": CT_2024_Q3_CN_URL, "evidence": "中文版三季报披露前三季度营业收入391,968.019百万元、营业成本274,412.834百万元、营业利润39,031.260百万元、经营现金流97,412.288百万元、购建长期资产现金支出58,289.667百万元和资产负债表。"},
    {"label": "中国电信2024年第三季度报告（新浪财经正文）", "url": CT_2024_Q3_SINA_URL, "evidence": "新浪财经公告正文镜像列示同一份三季报利润表、资产负债表和现金流量表，用于交叉核验。"},
]

CT_2024_Q4_SOURCES = [
    {"label": "中国电信官网Key Financial Data季度表", "url": CT_KEY_FINANCIAL_DATA_URL, "evidence": "官网季度表列示2024/Q4 Operating Revenue、Service Revenue、EBITDA和股东应占利润。"},
    {"label": "中国电信2024年前三季度报告（IRAsia）", "url": CT_2024_Q3_HKEX_URL, "evidence": "前三季度累计值用于从全年披露复核Q4。"},
    {"label": "中国电信2024年度业绩新闻稿（IRAsia）", "url": CT_2024_ANNUAL_RESULTS_URL, "evidence": "年度业绩新闻稿披露全年经营收入529.4十亿元、服务收入482.0十亿元、EBITDA 140.8十亿元和股东应占利润33.0十亿元。"},
]

CT_2024_Q4_DETAIL_SOURCES = [
    {"label": "中国电信2024年前三季度报告（IRAsia中文版）", "url": CT_2024_Q3_CN_URL, "evidence": "前三季度A股累计值用于从全年A股年报复算Q4营业收入、营业成本、营业利润、经营现金流和资本开支。"},
    {"label": "中国电信2024年度A股年报", "url": CT_2024_ANNUAL_ASHARE_URL, "evidence": "A股年报披露2024全年营业收入523,568.920百万元、营业成本373,498.407百万元、营业利润42,597.177百万元、经营现金流145,268.134百万元、购建长期资产现金支出90,271.344百万元、年末现金及现金等价物82,206.794百万元和资产负债表。"},
    {"label": "中国电信2024年度报告摘要（IRAsia中文版）", "url": CT_2024_ANNUAL_SUMMARY_CN_URL, "evidence": "年度报告摘要披露全年营业收入、营业成本、经营现金流等关键行，用于交叉核验A股年报。"},
    {"label": "中国电信2024年度业绩新闻稿（港交所/IRAsia）", "url": CT_2024_ANNUAL_RESULTS_URL, "evidence": "年度业绩新闻稿披露全年经营收入、服务收入、EBITDA、资本开支和自由现金流，用于交叉核验Q4拆分。"},
]

CT_2025_Q1_SOURCES = [
    {"label": "中国电信2025年第一季度报告（IRAsia英文版）", "url": CT_2025_Q1_HKEX_URL, "evidence": "一季报披露营业收入、营业成本、资产负债表和现金流量表。"},
    {"label": "中国电信2025年第一季度报告（IRAsia中文版）", "url": CT_2025_Q1_CN_URL, "evidence": "同一份一季报中文版披露营业收入、营业成本、现金及现金等价物、借款和租赁负债。"},
    {"label": "中国电信官网财务报告页", "url": CT_REPORTS_PAGE_URL, "evidence": "公司官网投资者关系财务报告页列示年度及中期财务报告入口，用于确认披露来源体系。"},
]

CT_2025_Q2_SOURCES = [
    {"label": "中国电信2025年第一季度报告（港交所/IRAsia）", "url": CT_2025_Q1_HKEX_URL, "evidence": "一季度IFRS累计值，用于从上半年累计值复算Q2。"},
    {"label": "中国电信2025年中期业绩公告（港交所/IRAsia）", "url": CT_2025_H1_HKEX_URL, "evidence": "上半年营业收入、服务收入、EBITDA、净利润、资本开支和自由现金流。"},
]

CT_2025_Q2_DETAIL_SOURCES = [
    {"label": "中国电信2025年第一季度报告（IRAsia中文版）", "url": CT_2025_Q1_CN_URL, "evidence": "一季报中文版披露Q1营业收入、营业成本、现金及现金等价物和债务组成。"},
    {"label": "中国电信2025年中期业绩公告（港交所/IRAsia）", "url": CT_2025_H1_HKEX_URL, "evidence": "H1公告披露2025年6月30日现金及现金等价物、总资产、短期债务、长期债务和租赁负债。"},
    {"label": "中国电信2025年半年度报告摘要（IRAsia中文版）", "url": CT_2025_H1_CN_SUMMARY_URL, "evidence": "半年度报告摘要披露H1营业收入269,421,736,705.26元、营业成本186,745,046,742.07元和经营现金流。"},
    {"label": "中国电信2025年半年度报告摘要（新浪财经正文）", "url": CT_2025_H1_SINA_SUMMARY_URL, "evidence": "新浪财经公告正文镜像列示同一份半年度报告摘要，用于交叉核验营业收入和营业成本行。"},
]

CT_2025_Q3_SOURCES = [
    {"label": "中国电信2025年中期业绩公告（港交所/IRAsia）", "url": CT_2025_H1_HKEX_URL, "evidence": "上半年IFRS累计值，用于从前三季度累计值复算Q3。"},
    {"label": "中国电信2025年前三季度报告（港交所/IRAsia）", "url": CT_2025_Q3_HKEX_URL, "evidence": "前三季度营业收入、服务收入、EBITDA、净利润、资产负债表和现金流量表。"},
]

CT_2025_Q3_DETAIL_SOURCES = [
    {"label": "中国电信2025年中期业绩公告（港交所/IRAsia）", "url": CT_2025_H1_HKEX_URL, "evidence": "H1累计值用于从前三季度累计值复算Q3经营指标。"},
    {"label": "中国电信2025年前三季度报告（港交所/IRAsia）", "url": CT_2025_Q3_HKEX_URL, "evidence": "前三季度英文公告披露Operating revenues 396,998百万元、Cash and cash equivalents 44,594百万元、Total assets 876,049百万元及债务项目。"},
    {"label": "中国电信2025年前三季度报告（IRAsia中文版）", "url": CT_2025_Q3_CN_URL, "evidence": "中文版三季报披露2025年前三季度营业收入394,269,976,324.05元、营业成本274,757,599,124.46元、营业利润39,843,463,240.55元和资产负债表。"},
    {"label": "中国电信2025年第三季度报告（新浪财经正文）", "url": CT_2025_Q3_SINA_URL, "evidence": "新浪财经公告正文镜像列示同一份三季报主要会计数据、营业收入、营业成本、现金及债务行项目。"},
]

CT_2025_Q4_SOURCES = [
    {"label": "中国电信2025年前三季度报告（港交所/IRAsia）", "url": CT_2025_Q3_HKEX_URL, "evidence": "前三季度累计值，用于从全年业绩复算Q4。"},
    {"label": "中国电信2025年度业绩新闻稿", "url": CT_2025_ANNUAL_RESULTS_URL, "evidence": "全年服务收入485,424、EBITDA143,872、净利润33,185、资本开支80,400百万元；经营收入529.6十亿元。"},
]

CT_2025_Q4_DETAIL_SOURCES = [
    {"label": "中国电信2025年前三季度报告（IRAsia中文版）", "url": CT_2025_Q3_CN_URL, "evidence": "三季报中文版披露前三季度A股口径营业收入、营业成本、营业利润和资产负债表，用于从全年数复算Q4。"},
    {"label": "中国电信2025年度A股年报", "url": CT_2025_ANNUAL_ASHARE_URL, "evidence": "A股年报披露2025全年营业收入523,924,731,368.75元、营业成本371,561,570,703.75元、营业利润45,855,348,273.99元、年末现金及现金等价物61,393,794,753.70元和资产负债表。"},
    {"label": "中国电信2025年度报告摘要（巨潮资讯）", "url": CT_2025_ANNUAL_SUMMARY_CNINFO_URL, "evidence": "年度报告摘要披露全年营业收入、营业成本和经营现金流等关键行，用于交叉核验A股年报。"},
    {"label": "中国电信2025年年度报告（新浪财经正文）", "url": CT_2025_ANNUAL_SINA_URL, "evidence": "新浪财经公告正文镜像列示同一份年报表格，用于交叉核验资产、现金、债务和利润表行项目。"},
]

CT_2026_Q1_SOURCES = [
    {"label": "中国电信2026年第一季度报告（巨潮资讯原文）", "url": CT_2026_Q1_CNINFO_URL, "evidence": "一季报披露营业收入、营业成本、经营现金流、现金及现金等价物、资产负债表和现金流量表。"},
    {"label": "中国电信2026年第一季度报告（雪球PDF镜像）", "url": CT_2026_Q1_XUEQIU_MIRROR_URL, "evidence": "PDF文本与巨潮资讯原文一致，用于交叉核验一季报行项目。"},
    {"label": "中国电信官网Key Financial Data季度表", "url": CT_KEY_FINANCIAL_DATA_URL, "evidence": "官网季度表列示2026/Q1 Operating Revenue 131,967、Service Revenue 122,694、EBITDA 33,875和股东应占利润7,350百万元。"},
    {"label": "中国电信2026年第一季度报告（新浪财经正文）", "url": CT_2026_Q1_SINA_URL, "evidence": "新浪财经公告正文镜像列示同一份一季报，用于交叉核验利润表和现金流量表行项目。"},
]

TOWER_2025_Q1_URL = "https://doc.irasia.com/listco/hk/chinatower/interim/2025/int1q.pdf"
TOWER_2025_H1_URL = "https://doc.irasia.com/listco/hk/chinatower/interim/2025/int.pdf"
TOWER_2025_Q3_URL = "https://doc.irasia.com/listco/hk/chinatower/interim/2025/int3qc.pdf"
TOWER_2025_ANNUAL_RESULTS_URL = "https://doc.irasia.com/listco/hk/chinatower/annual/2025/res.pdf"
TOWER_2025_ANNUAL_PRESENTATION_URL = "https://ir.china-tower.com/en/ir/presentation/pre260318.pdf"
TOWER_2025_ANNUAL_NEWS_URL = "https://www.china-tower.com/Index/show/catid/17/id/1648.html"
TOWER_2026_Q1_URL = "https://doc.irasia.com/listco/hk/chinatower/interim/2026/int1q.pdf"

TOWER_2023_Q1_URL = "https://doc.irasia.com/listco/hk/chinatower/interim/2023/int1qc.pdf"
TOWER_2023_H1_URL = "https://doc.irasia.com/listco/hk/chinatower/interim/2023/int.pdf"
TOWER_2023_Q3_URL = "https://doc.irasia.com/listco/hk/chinatower/interim/2023/int3qc.pdf"
TOWER_2023_ANNUAL_RESULTS_URL = "https://doc.irasia.com/listco/hk/chinatower/annual/2023/res.pdf"
TOWER_2022_Q1_URL = "https://doc.irasia.com/listco/hk/chinatower/interim/2022/int1q.pdf"
TOWER_2022_H1_URL = "https://doc.irasia.com/listco/hk/chinatower/interim/2022/intrep.pdf"
TOWER_2022_Q3_URL = "https://doc.irasia.com/listco/hk/chinatower/interim/2022/int3q.pdf"
TOWER_2022_ANNUAL_REPORT_URL = "https://doc.irasia.com/listco/hk/chinatower/annual/2022/ar2022.pdf"
TOWER_2020_Q1_URL = "https://doc.irasia.com/listco/hk/chinatower/interim/2020/int1q.pdf"
TOWER_2020_H1_URL = "https://doc.irasia.com/listco/hk/chinatower/interim/2020/intrep.pdf"
TOWER_2020_Q3_URL = "https://doc.irasia.com/listco/hk/chinatower/interim/2020/int3q.pdf"
TOWER_2020_ANNUAL_RESULTS_URL = "https://doc.irasia.com/listco/hk/chinatower/annual/2020/res.pdf"
TOWER_2020_ANNUAL_REPORT_URL = "https://doc.irasia.com/listco/hk/chinatower/annual/2020/ar2020.pdf"
TOWER_2019_Q1_URL = "https://doc.irasia.com/listco/hk/chinatower/interim/2019/int1q.pdf"
TOWER_2019_H1_URL = "https://doc.irasia.com/listco/hk/chinatower/interim/2019/intrep.pdf"
TOWER_2019_Q3_URL = "https://doc.irasia.com/listco/hk/chinatower/interim/2019/int3q.pdf"
TOWER_2019_ANNUAL_RESULTS_URL = "https://doc.irasia.com/listco/hk/chinatower/annual/2019/res.pdf"
TOWER_2019_ANNUAL_REPORT_URL = "https://doc.irasia.com/listco/hk/chinatower/annual/2019/ar2019.pdf"
TOWER_2018_PROSPECTUS_URL = "https://www.hkexnews.hk/listedco/listconews/SEHK/2018/0725/LTN20180725011.pdf"
TOWER_2018_H1_RESULTS_URL = "https://www.hkexnews.hk/listedco/listconews/SEHK/2018/0812/LTN20180812009.pdf"
TOWER_2018_H1_REPORT_URL = "https://www.hkexnews.hk/listedco/listconews/SEHK/2018/0827/LTN20180827314.pdf"
TOWER_2018_Q3_URL = "https://doc.irasia.com/listco/hk/chinatower/interim/2018/int3q.pdf"
TOWER_2018_ANNUAL_REPORT_URL = "https://doc.irasia.com/listco/hk/chinatower/annual/2018/res.pdf"
TOWER_2021_Q1_URL = "https://doc.irasia.com/listco/hk/chinatower/interim/2021/int1q.pdf"
TOWER_2021_H1_URL = "https://doc.irasia.com/listco/hk/chinatower/interim/2021/intrep.pdf"
TOWER_2021_Q3_URL = "https://doc.irasia.com/listco/hk/chinatower/interim/2021/int3q.pdf"
TOWER_2021_ANNUAL_REPORT_URL = "https://doc.irasia.com/listco/hk/chinatower/annual/2021/ar2021.pdf"

TOWER_2021_Q1_SOURCES = [
    {"label": "中国铁塔2021年第一季度未经审核主要运营数据", "url": TOWER_2021_Q1_URL, "evidence": "一季度公告直接披露营业收入21,151百万元、EBITDA 15,553百万元和归母利润1,694百万元。"},
    {"label": "中国铁塔2021中期报告", "url": TOWER_2021_H1_URL, "evidence": "中期报告披露H1营业收入42,673百万元、EBITDA 31,184百万元和归母利润3,457百万元，用于交叉核验Q1+Q2。"},
    {"label": "中国铁塔2021年度报告", "url": TOWER_2021_ANNUAL_REPORT_URL, "evidence": "年报披露FY2021营业收入86,585百万元、EBITDA 63,017百万元和归母利润7,329百万元，用于全年合计交叉核验。"},
]
TOWER_2024_Q1_URL = "https://doc.irasia.com/listco/hk/chinatower/interim/2024/int1qc.pdf"
TOWER_2024_H1_URL = "https://doc.irasia.com/listco/hk/chinatower/interim/2024/int.pdf"
TOWER_2024_Q3_URL = "https://doc.irasia.com/listco/hk/chinatower/interim/2024/int3qc.pdf"
TOWER_2024_ANNUAL_RESULTS_URL = "https://doc.irasia.com/listco/hk/chinatower/annual/2024/res.pdf"

TOWER_2023_Q1_SOURCES = [
    {"label": "中国铁塔2023年第一季度未经审核主要运营数据", "url": TOWER_2023_Q1_URL, "evidence": "一季度营业收入、业务收入拆分、EBITDA、归母利润和总资产。"},
    {"label": "中国铁塔2023中期业绩公告", "url": TOWER_2023_H1_URL, "evidence": "中期公告比较口径用于交叉核验一季度至上半年累计关系。"},
]

TOWER_2023_Q2_SOURCES = [
    {"label": "中国铁塔2023年第一季度未经审核主要运营数据", "url": TOWER_2023_Q1_URL, "evidence": "一季度累计值，用于从上半年累计值复算Q2。"},
    {"label": "中国铁塔2023中期业绩公告", "url": TOWER_2023_H1_URL, "evidence": "上半年营业收入、业务收入拆分、EBITDA、经营利润、归母利润、经营现金流、资本开支和资产负债数据。"},
]

TOWER_2023_Q3_SOURCES = [
    {"label": "中国铁塔2023中期业绩公告", "url": TOWER_2023_H1_URL, "evidence": "上半年累计值，用于从前三季度累计值复算Q3。"},
    {"label": "中国铁塔2023年前三季度未经审核主要运营数据", "url": TOWER_2023_Q3_URL, "evidence": "前三季度营业收入、业务收入拆分、EBITDA、归母利润和总资产。"},
]

TOWER_2023_Q4_SOURCES = [
    {"label": "中国铁塔2023年前三季度未经审核主要运营数据", "url": TOWER_2023_Q3_URL, "evidence": "前三季度累计值，用于从全年业绩复算Q4。"},
    {"label": "中国铁塔2023年度业绩公告", "url": TOWER_2023_ANNUAL_RESULTS_URL, "evidence": "2023年度业绩公告披露全年营业收入、业务收入拆分、经营利润、EBITDA、归母利润、经营现金流、资本开支和资产负债表。"},
]

TOWER_2022_Q1_SOURCES = [
    {"label": "中国铁塔2022年第一季度未经审核主要运营数据", "url": TOWER_2022_Q1_URL, "evidence": "一季度公告披露营业收入22,633百万元、EBITDA 15,682百万元、归母利润2,180百万元和收入同比7.0%。"},
    {"label": "中国铁塔2022中期报告", "url": TOWER_2022_H1_URL, "evidence": "中期报告披露H1营业收入45,479百万元、EBITDA 31,958百万元和归母利润4,224百万元，用于交叉核验Q1+Q2。"},
]

TOWER_2022_Q2_SOURCES = [
    {"label": "中国铁塔2022年第一季度未经审核主要运营数据", "url": TOWER_2022_Q1_URL, "evidence": "一季度累计值，用于从H1累计值复算Q2。"},
    {"label": "中国铁塔2022中期报告", "url": TOWER_2022_H1_URL, "evidence": "中期报告披露H1营业收入45,479百万元、EBITDA 31,958百万元、归母利润4,224百万元和收入同比6.6%。"},
    {"label": "中国铁塔2022年度报告", "url": TOWER_2022_ANNUAL_REPORT_URL, "evidence": "年报披露FY2022营业收入92,170百万元、EBITDA 62,844百万元和归母利润8,787百万元，用于全年合计交叉核验。"},
]

TOWER_2022_Q3_SOURCES = [
    {"label": "中国铁塔2022中期报告", "url": TOWER_2022_H1_URL, "evidence": "中期报告提供H1累计值，用于从9M累计值复算Q3。"},
    {"label": "中国铁塔2022年前三季度未经审核主要运营数据", "url": TOWER_2022_Q3_URL, "evidence": "前三季度公告披露9M营业收入68,682百万元、EBITDA 47,460百万元和归母利润6,399百万元。"},
    {"label": "中国铁塔2022年度报告", "url": TOWER_2022_ANNUAL_REPORT_URL, "evidence": "年报披露全年核心经营数据，用于交叉核验9M与全年合计关系。"},
]

TOWER_2022_Q4_SOURCES = [
    {"label": "中国铁塔2022年前三季度未经审核主要运营数据", "url": TOWER_2022_Q3_URL, "evidence": "前三季度公告提供9M累计值，用于从FY累计值复算Q4。"},
    {"label": "中国铁塔2022年度报告", "url": TOWER_2022_ANNUAL_REPORT_URL, "evidence": "年报披露FY2022营业收入92,170百万元、EBITDA 62,844百万元和归母利润8,787百万元。"},
    {"label": "中国铁塔2022中期报告", "url": TOWER_2022_H1_URL, "evidence": "中期报告提供H1累计值，用于交叉核验2022拆分链路。"},
]

TOWER_2020_Q1_SOURCES = [
    {"label": "中国铁塔2020年第一季度未经审核主要运营数据", "url": TOWER_2020_Q1_URL, "evidence": "一季度公告披露营业收入19,690百万元、EBITDA 14,532百万元、归母利润1,452百万元和EBITDA率73.8%。"},
    {"label": "中国铁塔2020中期报告", "url": TOWER_2020_H1_URL, "evidence": "中期报告披露H1营业收入39,794百万元、EBITDA 29,100百万元和归母利润2,978百万元，用于交叉核验Q1+Q2。"},
    {"label": "中国铁塔2020年度业绩公告", "url": TOWER_2020_ANNUAL_RESULTS_URL, "evidence": "年度业绩公告披露FY2020营业收入81,099百万元、EBITDA 59,527百万元和归母利润6,428百万元，用于全年合计交叉核验。"},
]

TOWER_2020_Q2_SOURCES = [
    {"label": "中国铁塔2020年第一季度未经审核主要运营数据", "url": TOWER_2020_Q1_URL, "evidence": "一季度累计值用于从H1累计值复算Q2。"},
    {"label": "中国铁塔2020中期报告", "url": TOWER_2020_H1_URL, "evidence": "中期报告披露H1营业收入39,794百万元、EBITDA 29,100百万元和归母利润2,978百万元。"},
    {"label": "中国铁塔2020年度报告", "url": TOWER_2020_ANNUAL_REPORT_URL, "evidence": "年报披露全年核心经营数据，用于交叉核验H1与全年合计关系。"},
]

TOWER_2020_Q3_SOURCES = [
    {"label": "中国铁塔2020中期报告", "url": TOWER_2020_H1_URL, "evidence": "中期报告提供H1累计值，用于从9M累计值复算Q3。"},
    {"label": "中国铁塔2020年前三季度未经审核主要运营数据", "url": TOWER_2020_Q3_URL, "evidence": "前三季度公告披露9M营业收入60,220百万元、EBITDA 44,019百万元和归母利润4,564百万元。"},
    {"label": "中国铁塔2020年度报告", "url": TOWER_2020_ANNUAL_REPORT_URL, "evidence": "年报披露全年核心经营数据，用于交叉核验9M与全年合计关系。"},
]

TOWER_2020_Q4_SOURCES = [
    {"label": "中国铁塔2020年前三季度未经审核主要运营数据", "url": TOWER_2020_Q3_URL, "evidence": "前三季度公告提供9M累计值，用于从FY累计值复算Q4。"},
    {"label": "中国铁塔2020年度业绩公告", "url": TOWER_2020_ANNUAL_RESULTS_URL, "evidence": "年度业绩公告披露FY2020营业收入81,099百万元、EBITDA 59,527百万元和归母利润6,428百万元。"},
    {"label": "中国铁塔2020年度报告", "url": TOWER_2020_ANNUAL_REPORT_URL, "evidence": "年报同口径披露全年核心经营和财务报表，用于交叉核验。"},
]

TOWER_2019_Q1_SOURCES = [
    {"label": "中国铁塔2019年第一季度未经审核主要运营数据", "url": TOWER_2019_Q1_URL, "evidence": "一季度公告披露营业收入18,897百万元、EBITDA 13,590百万元和归母利润1,284百万元。"},
    {"label": "中国铁塔2019中期报告", "url": TOWER_2019_H1_URL, "evidence": "中期报告披露H1营业收入37,980百万元、EBITDA 27,815百万元和归母利润2,548百万元，用于交叉核验Q1+Q2。"},
    {"label": "中国铁塔2019年度业绩公告", "url": TOWER_2019_ANNUAL_RESULTS_URL, "evidence": "年度业绩公告披露FY2019营业收入76,428百万元、EBITDA 56,696百万元和归母利润5,222百万元，用于全年合计交叉核验。"},
]

TOWER_2019_Q2_SOURCES = [
    {"label": "中国铁塔2019年第一季度未经审核主要运营数据", "url": TOWER_2019_Q1_URL, "evidence": "一季度累计值用于从H1累计值复算Q2。"},
    {"label": "中国铁塔2019中期报告", "url": TOWER_2019_H1_URL, "evidence": "中期报告披露H1营业收入37,980百万元、EBITDA 27,815百万元和归母利润2,548百万元。"},
    {"label": "中国铁塔2019年度报告", "url": TOWER_2019_ANNUAL_REPORT_URL, "evidence": "年报披露全年核心经营数据，用于交叉核验H1与全年合计关系。"},
]

TOWER_2019_Q3_SOURCES = [
    {"label": "中国铁塔2019中期报告", "url": TOWER_2019_H1_URL, "evidence": "中期报告提供H1累计值，用于从9M累计值复算Q3。"},
    {"label": "中国铁塔2019年前三季度未经审核主要运营数据", "url": TOWER_2019_Q3_URL, "evidence": "前三季度公告披露9M营业收入57,041百万元、EBITDA 41,774百万元和归母利润3,873百万元。"},
    {"label": "中国铁塔2019年度报告", "url": TOWER_2019_ANNUAL_REPORT_URL, "evidence": "年报披露全年核心经营数据，用于交叉核验9M与全年合计关系。"},
]

TOWER_2019_Q4_SOURCES = [
    {"label": "中国铁塔2019年前三季度未经审核主要运营数据", "url": TOWER_2019_Q3_URL, "evidence": "前三季度公告提供9M累计值，用于从FY累计值复算Q4。"},
    {"label": "中国铁塔2019年度业绩公告", "url": TOWER_2019_ANNUAL_RESULTS_URL, "evidence": "年度业绩公告披露FY2019营业收入76,428百万元、EBITDA 56,696百万元和归母利润5,222百万元。"},
    {"label": "中国铁塔2020年度业绩公告比较栏", "url": TOWER_2020_ANNUAL_RESULTS_URL, "evidence": "2020年度业绩公告比较栏重列2019全年营业收入76,428百万元和归母利润5,222百万元，用于交叉核验。"},
]

TOWER_2021_Q2_SOURCES = [
    {"label": "中国铁塔2021年第一季度未经审核主要运营数据", "url": TOWER_2021_Q1_URL, "evidence": "一季度公告披露营业收入21,151百万元、EBITDA 15,553百万元和归母利润1,694百万元，用于从H1累计值复算Q2。"},
    {"label": "中国铁塔2021中期报告", "url": TOWER_2021_H1_URL, "evidence": "中期报告披露H1营业收入42,673百万元、EBITDA 31,184百万元和归母利润3,457百万元。"},
    {"label": "中国铁塔2021年度报告", "url": TOWER_2021_ANNUAL_REPORT_URL, "evidence": "年报披露FY2021营业收入86,585百万元、EBITDA 63,017百万元和归母利润7,329百万元，用于全年合计交叉核验。"},
]

TOWER_2021_Q3_SOURCES = [
    {"label": "中国铁塔2021中期报告", "url": TOWER_2021_H1_URL, "evidence": "中期报告提供H1累计值，用于从9M累计值复算Q3。"},
    {"label": "中国铁塔2021年前三季度未经审核主要运营数据", "url": TOWER_2021_Q3_URL, "evidence": "前三季度公告披露9M营业收入64,588百万元、EBITDA 47,289百万元和归母利润5,256百万元。"},
    {"label": "中国铁塔2021年度报告", "url": TOWER_2021_ANNUAL_REPORT_URL, "evidence": "年报披露全年核心经营数据，用于交叉核验9M与全年合计关系。"},
]

TOWER_2021_Q4_SOURCES = [
    {"label": "中国铁塔2021年前三季度未经审核主要运营数据", "url": TOWER_2021_Q3_URL, "evidence": "前三季度公告提供9M累计值，用于从FY累计值复算Q4。"},
    {"label": "中国铁塔2021年度报告", "url": TOWER_2021_ANNUAL_REPORT_URL, "evidence": "年报披露FY2021营业收入86,585百万元、EBITDA 63,017百万元和归母利润7,329百万元。"},
    {"label": "中国铁塔2021中期报告", "url": TOWER_2021_H1_URL, "evidence": "中期报告提供H1累计值，用于交叉核验2021拆分链路。"},
]

TOWER_2024_Q1_SOURCES = [
    {"label": "中国铁塔2024年第一季度未经审核主要运营数据", "url": TOWER_2024_Q1_URL, "evidence": "一季度营业收入、业务收入拆分、EBITDA、归母利润和总资产。"},
    {"label": "中国铁塔2024中期业绩公告", "url": TOWER_2024_H1_URL, "evidence": "中期公告比较口径用于交叉核验一季度至上半年累计关系。"},
]

TOWER_2024_Q2_SOURCES = [
    {"label": "中国铁塔2024年第一季度未经审核主要运营数据", "url": TOWER_2024_Q1_URL, "evidence": "一季度累计经营数据，用于从上半年累计值复算Q2。"},
    {"label": "中国铁塔2024中期业绩公告", "url": TOWER_2024_H1_URL, "evidence": "上半年营业收入、业务收入拆分、EBITDA、经营利润、归母利润、经营现金流、资本开支和资产负债数据。"},
]

TOWER_2024_Q3_SOURCES = [
    {"label": "中国铁塔2024中期业绩公告", "url": TOWER_2024_H1_URL, "evidence": "上半年累计值，用于从前三季度累计值复算Q3。"},
    {"label": "中国铁塔2024年前三季度未经审核主要运营数据", "url": TOWER_2024_Q3_URL, "evidence": "前三季度营业收入、业务收入拆分、EBITDA、归母利润和总资产。"},
]

TOWER_2024_Q4_SOURCES = [
    {"label": "中国铁塔2024年前三季度未经审核主要运营数据", "url": TOWER_2024_Q3_URL, "evidence": "前三季度累计值，用于从全年业绩复算Q4。"},
    {"label": "中国铁塔2024年度业绩公告", "url": TOWER_2024_ANNUAL_RESULTS_URL, "evidence": "2024年度业绩公告披露全年营业收入、业务收入拆分、经营利润、EBITDA、归母利润、经营现金流、资本开支和资产负债表。"},
]

TOWER_2025_Q2_SOURCES = [
    {"label": "中国铁塔2025年第一季度未经审核主要运营数据", "url": TOWER_2025_Q1_URL, "evidence": "一季度累计经营数据，用于从上半年累计值复算Q2。"},
    {"label": "中国铁塔2025中期业绩公告", "url": TOWER_2025_H1_URL, "evidence": "上半年营业收入、业务收入拆分、EBITDA、归母利润和资产负债数据。"},
]

TOWER_2025_Q1_SOURCES = [
    {"label": "中国铁塔2025年第一季度未经审核主要运营数据", "url": TOWER_2025_Q1_URL, "evidence": "一季度公告披露营业收入、业务收入拆分、EBITDA、归母利润和总资产；同时确认现金流、资本开支、毛利和债务等未披露缺口。"},
    {"label": "中国铁塔2025中期业绩公告", "url": TOWER_2025_H1_URL, "evidence": "中期公告披露上半年累计经营、利润、现金流和资产负债数据，用于核对Q1至H1的披露边界和可复算项目。"},
    {"label": "中国铁塔公告列表", "url": "https://ir.china-tower.com/en/ir/announcements.php", "evidence": "公司官网公告列表定位2025Q1未经审核主要运营数据和2025中期业绩公告。"},
]

TOWER_2025_Q3_SOURCES = [
    {"label": "中国铁塔2025中期业绩公告", "url": TOWER_2025_H1_URL, "evidence": "上半年累计值，用于从前三季度累计值复算Q3。"},
    {"label": "中国铁塔2025年前三季度未经审核主要运营数据", "url": TOWER_2025_Q3_URL, "evidence": "前三季度营业收入、业务收入拆分、EBITDA、归母利润和总资产。"},
]

TOWER_2025_Q4_SOURCES = [
    {"label": "中国铁塔2025年前三季度未经审核主要运营数据", "url": TOWER_2025_Q3_URL, "evidence": "前三季度累计值，用于从全年业绩复算Q4。"},
    {"label": "中国铁塔2025年度业绩公告", "url": TOWER_2025_ANNUAL_RESULTS_URL, "evidence": "年度业绩公告披露全年综合收益表、资产负债表、现金流、资本开支和自由现金流。"},
    {"label": "中国铁塔2025年度业绩演示", "url": TOWER_2025_ANNUAL_PRESENTATION_URL, "evidence": "年度业绩演示列示2025年Operating Revenue 100.4 billion、EBITDA 65,814 million、Profit Attributable to Owners of the Company 11,630 million。"},
    {"label": "中国铁塔2025业绩新闻稿", "url": TOWER_2025_ANNUAL_NEWS_URL, "evidence": "官网新闻稿列示营业收入1004.11亿元、EBITDA 658.14亿元、归母利润116.30亿元、总资产3365.79亿元、带息负债904.60亿元，以及业务线收入拆分。"},
]

TOWER_2026_Q1_SOURCES = [
    {"label": "中国铁塔2026年第一季度未经审核主要运营数据", "url": TOWER_2026_Q1_URL, "evidence": "2026Q1公告披露收入、业务线收入、EBITDA、税前利润、归母利润、总资产、总负债和总权益；未披露单季现金流、资本开支、毛利、经营利润、现金或带息负债。"},
    {"label": "中国铁塔公告列表", "url": "https://ir.china-tower.com/en/ir/announcements.php", "evidence": "中国铁塔官网公告列表定位2026Q1未经审核主要运营数据公告和2025年度业绩公告。"},
]

CU_2025_Q1_SSE_URL = "https://static.sse.com.cn/disclosure/listedinfo/announcement/c/new/2025-04-18/600050_20250418_RJH7.pdf"
CU_2025_Q1_CNINFO_URL = "https://static.cninfo.com.cn/finalpage/2025-04-18/1223124988.PDF"
CU_2025_Q1_NANDU_URL = "https://m.mp.oeeee.com/a/BAAFRD0000202504181071155.html"
CU_2025_H1_URL = "https://www.chinaunicom.com.hk/en/ir/reports/ir2025.pdf"
CU_2025_H1_SINA_URL = "https://money.finance.sina.com.cn/corp/view/vCB_AllBulletinDetail.php?id=11294714&stockid=600050"
CU_2025_H1_IRASIA_CN_URL = "https://doc.irasia.com/listco/hk/chinaunicom/interim/2025/intc.pdf"
CU_2025_Q3_SINA_URL = "https://vip.stock.finance.sina.com.cn/corp/view/vCB_AllBulletinDetail.php?id=11526422&stockid=600050"
CU_2025_Q3_SASAC_URL = "https://wap.sasac.gov.cn/n16582853/n16582883/c34722234/content.html"
CU_2025_ANNUAL_REPORT_URL = "https://www.chinaunicom.com.hk/en/ir/reports/ar2025.pdf"
CU_2025_ANNUAL_RESULTS_URL = "https://www.chinaunicom.com.hk/en/media/press/p260319.pdf"
CU_2025_ANNUAL_SINA_URL = "https://money.finance.sina.com.cn/corp/view/vCB_AllBulletinDetail.php?id=12005771&stockid=600050"
CU_2026_Q1_SSE_URL = "https://static.sse.com.cn/disclosure/listedinfo/announcement/c/new/2026-04-22/600050_20260422_763Q.pdf"
CU_2026_Q1_XUEQIU_MIRROR_URL = "https://stockmc.xueqiu.com/202604/600050_20260422_763Q.pdf"
CU_2026_Q1_NBD_URL = "https://www.nbd.com.cn/articles/2026-04-22/4351019.html"
CU_2023_Q1_URL = "https://doc.irasia.com/listco/hk/chinaunicom/interim/2023/int1q.pdf"
CU_2023_H1_URL = "https://www.chinaunicom.com.hk/en/ir/reports/ir2023.pdf"
CU_2023_Q3_URL = "https://doc.irasia.com/listco/hk/chinaunicom/interim/2023/int3q.pdf"
CU_2023_ANNUAL_RESULTS_URL = "https://doc.irasia.com/listco/hk/chinaunicom/annual/2023/res.pdf"
CU_2022_Q1_URL = "https://doc.irasia.com/listco/hk/chinaunicom/interim/2022/int1q.pdf"
CU_2022_H1_URL = "https://www.chinaunicom.com.hk/en/ir/reports/ir2022.pdf"
CU_2022_Q3_URL = "https://doc.irasia.com/listco/hk/chinaunicom/interim/2022/int3q.pdf"
CU_2022_ANNUAL_REPORT_URL = "https://www.chinaunicom.com.hk/en/ir/reports/ar2022.pdf"
CU_2021_Q1_URL = "https://doc.irasia.com/listco/hk/chinaunicom/interim/2021/int1q.pdf"
CU_2021_H1_URL = "https://www.chinaunicom.com.hk/en/ir/reports/ir2021.pdf"
CU_2021_Q3_URL = "https://doc.irasia.com/listco/hk/chinaunicom/interim/2021/int3q.pdf"
CU_2021_ANNUAL_REPORT_URL = "https://www.chinaunicom.com.hk/en/ir/reports/ar2021.pdf"
CU_2020_Q1_URL = "https://doc.irasia.com/listco/hk/chinaunicom/interim/2020/int1q.pdf"
CU_2020_H1_PRESS_URL = "https://www.chinaunicom.com.hk/en/media/press/p200812.pdf"
CU_2020_H1_URL = "https://www.chinaunicom.com.hk/en/ir/reports/ir2020.pdf"
CU_2020_Q3_URL = "https://doc.irasia.com/listco/hk/chinaunicom/interim/2020/int3q.pdf"
CU_2020_ANNUAL_RESULTS_URL = "https://doc.irasia.com/listco/hk/chinaunicom/annual/2020/res.pdf"
CU_2020_ANNUAL_REPORT_HKEX_URL = "https://www.hkexnews.hk/listedco/listconews/sehk/2021/0408/2021040800904.pdf"
CU_2020_ANNUAL_PRESS_URL = "https://www.chinaunicom.com.hk/en/media/press/p210311.pdf"
CU_2019_Q1_URL = "https://doc.irasia.com/listco/hk/chinaunicom/interim/2019/int1q.pdf"
CU_2019_H1_URL = "https://www.chinaunicom.com.hk/en/ir/reports/ir2019/ir2019_02.pdf"
CU_2019_Q3_URL = "https://doc.irasia.com/listco/hk/chinaunicom/interim/2019/int3q.pdf"
CU_2019_ANNUAL_REPORT_URL = "https://www.chinaunicom.com.hk/en/ir/reports/ar2019.pdf"
CU_2018_Q1_URL = "https://doc.irasia.com/listco/hk/chinaunicom/interim/2018/int1q.pdf"
CU_2018_H1_URL = "https://www.chinaunicom.com.hk/en/ir/reports/ir2018.pdf"
CU_2018_Q3_URL = "https://doc.irasia.com/listco/hk/chinaunicom/interim/2018/int3q.pdf"
CU_2018_ANNUAL_REPORT_URL = "https://www.chinaunicom.com.hk/en/ir/reports/ar2018.pdf"
CU_2017_H1_URL = "https://www.chinaunicom.com.hk/en/ir/reports/ir2017.pdf"
CU_2017_ANNUAL_REPORT_URL = "https://www.chinaunicom.com.hk/en/ir/reports/ar2017.pdf"
CU_2016_H1_URL = "https://www.chinaunicom.com.hk/en/ir/reports/ir2016.pdf"
CU_2016_ANNUAL_REPORT_URL = "https://www.chinaunicom.com.hk/en/ir/reports/ar2016.pdf"

CU_2021_Q1_SOURCES = [
    {"label": "中国联通2021年第一季度主要财务数据", "url": CU_2021_Q1_URL, "evidence": "一季度公告直接披露Total revenue 82,272百万元、EBITDA 23.64十亿元和归母利润3,843百万元。"},
    {"label": "中国联通2021中期报告", "url": CU_2021_H1_URL, "evidence": "中期报告披露H1 Revenue 164,174百万元、EBITDA 49.49十亿元和归母利润9,167百万元，用于交叉核验Q1+Q2。"},
    {"label": "中国联通2021年报", "url": CU_2021_ANNUAL_REPORT_URL, "evidence": "年报披露FY2021 Revenue 327,854百万元、EBITDA 96.32十亿元和归母利润14,368百万元，用于全年合计交叉核验。"},
]

CU_2020_Q1_SOURCES = [
    {"label": "中国联通2020年第一季度主要财务数据", "url": CU_2020_Q1_URL, "evidence": "一季度公告直接披露Q1 revenue 73,824、service revenue 68,307、EBITDA 23,561和归母利润3,166百万元。"},
    {"label": "中国联通2020中期业绩新闻稿", "url": CU_2020_H1_PRESS_URL, "evidence": "中期业绩新闻稿披露H1 operating revenue 150,397、service revenue 138,335、EBITDA 49,452和净利润7,569百万元，用于交叉核验Q1+Q2。"},
    {"label": "中国联通2020年度业绩公告（IRAsia）", "url": CU_2020_ANNUAL_RESULTS_URL, "evidence": "年度业绩公告披露FY2020 revenue 303,838、service revenue 275,814和归母利润12,493百万元，用于全年链路交叉核验。"},
]

CU_2020_Q2_SOURCES = [
    {"label": "中国联通2020年第一季度主要财务数据", "url": CU_2020_Q1_URL, "evidence": "一季度累计值用于从H1累计值复算Q2。"},
    {"label": "中国联通2020中期业绩新闻稿", "url": CU_2020_H1_PRESS_URL, "evidence": "中期业绩新闻稿披露H1 operating revenue 150,397、service revenue 138,335、EBITDA 49,452和净利润7,569百万元。"},
    {"label": "中国联通2021中期报告比较栏", "url": CU_2021_H1_URL, "evidence": "2021中期报告比较栏再次列示2020 H1 revenue 150,397、service revenue 138,335、EBITDA 49,452和归母利润7,569百万元。"},
]

CU_2020_Q3_SOURCES = [
    {"label": "中国联通2020中期业绩新闻稿", "url": CU_2020_H1_PRESS_URL, "evidence": "H1累计值用于从9M累计值复算Q3。"},
    {"label": "中国联通2020年前三季度主要财务数据", "url": CU_2020_Q3_URL, "evidence": "前三季度公告披露9M revenue 225,355、service revenue 207,349、EBITDA 73,700和归母利润10,824百万元。"},
    {"label": "中国联通2021年前三季度公告比较栏", "url": CU_2021_Q3_URL, "evidence": "2021年前三季度公告比较栏再次列示2020年9M核心经营数据。"},
]

CU_2020_Q4_SOURCES = [
    {"label": "中国联通2020年前三季度主要财务数据", "url": CU_2020_Q3_URL, "evidence": "前三季度累计值用于从FY累计值复算Q4。"},
    {"label": "中国联通2020年度业绩公告（IRAsia）", "url": CU_2020_ANNUAL_RESULTS_URL, "evidence": "年度业绩公告披露FY2020 revenue 303,838、service revenue 275,814和归母利润12,493百万元。"},
    {"label": "中国联通2020年度业绩新闻稿", "url": CU_2020_ANNUAL_PRESS_URL, "evidence": "年度业绩新闻稿列示FY2020 operating revenue 303,838、service revenue 275,814、EBITDA 94,139和净利润12,492百万元；与年报/业绩公告归母利润12,493百万元仅有四舍五入差异。"},
]

CU_2019_Q1_SOURCES = [
    {"label": "中国联通2019年第一季度主要财务数据", "url": CU_2019_Q1_URL, "evidence": "一季度公告直接披露Q1 revenue 73,147、service revenue 66,802、EBITDA 25,012和归母利润3,675百万元。"},
    {"label": "中国联通2019中期报告财务概览", "url": CU_2019_H1_URL, "evidence": "中期报告财务概览披露H1 revenue 144.95十亿元、service revenue 132.96十亿元、EBITDA 49.51十亿元和净利润6.88十亿元，用于交叉核验Q1+Q2。"},
    {"label": "中国联通2019年报", "url": CU_2019_ANNUAL_REPORT_URL, "evidence": "年报披露FY2019 revenue 290,515、service revenue 264,386、EBITDA 94,358和归母利润11,330百万元，用于全年链路交叉核验。"},
]

CU_2019_Q2_SOURCES = [
    {"label": "中国联通2019年第一季度主要财务数据", "url": CU_2019_Q1_URL, "evidence": "一季度累计值用于从H1累计值复算Q2。"},
    {"label": "中国联通2019中期报告财务概览", "url": CU_2019_H1_URL, "evidence": "中期报告财务概览披露H1 revenue 144.95十亿元、service revenue 132.96十亿元、EBITDA 49.51十亿元和净利润6.88十亿元。"},
    {"label": "中国联通2019年报", "url": CU_2019_ANNUAL_REPORT_URL, "evidence": "年报披露全年核心经营值，用于年度链路交叉核验。"},
]

CU_2019_Q3_SOURCES = [
    {"label": "中国联通2019中期报告财务概览", "url": CU_2019_H1_URL, "evidence": "H1累计值用于从9M累计值复算Q3。"},
    {"label": "中国联通2019年前三季度主要财务数据", "url": CU_2019_Q3_URL, "evidence": "前三季度公告披露9M revenue 217,120、service revenue 198,532、EBITDA 73,145和归母利润9,823百万元。"},
    {"label": "中国联通2020年前三季度公告比较栏", "url": CU_2020_Q3_URL, "evidence": "2020年前三季度公告比较栏再次列示2019年9M revenue 217,120、service revenue 198,532和归母利润9,823百万元。"},
]

CU_2019_Q4_SOURCES = [
    {"label": "中国联通2019年前三季度主要财务数据", "url": CU_2019_Q3_URL, "evidence": "前三季度累计值用于从FY累计值复算Q4。"},
    {"label": "中国联通2019年报", "url": CU_2019_ANNUAL_REPORT_URL, "evidence": "年报披露FY2019 revenue 290,515、service revenue 264,386、EBITDA 94,358和归母利润11,330百万元。"},
    {"label": "中国联通2020年度业绩新闻稿比较栏", "url": CU_2020_ANNUAL_PRESS_URL, "evidence": "2020年度业绩新闻稿比较栏列示2019 operating revenue 290,515、service revenue 264,386、EBITDA 94,358和净利润11,330百万元。"},
]

CU_2018_Q1_SOURCES = [
    {"label": "中国联通2018年第一季度主要财务及运营数据", "url": CU_2018_Q1_URL, "evidence": "一季度公告直接披露2018 Q1 revenue 74,935、service revenue 66,609、EBITDA 23,909、归母利润3,005百万元，并列示2017 Q1 revenue 69,005、service revenue 61,426、归母利润862百万元比较栏。"},
    {"label": "中国联通2018中期报告", "url": CU_2018_H1_URL, "evidence": "中期报告披露H1 2018 revenue 149.11十亿元、service revenue 134.42十亿元、EBITDA 45.67十亿元和归母利润5.91十亿元，用于交叉核验Q1+Q2。"},
    {"label": "中国联通2018年报", "url": CU_2018_ANNUAL_REPORT_URL, "evidence": "年报披露FY2018 revenue 290.88十亿元、service revenue 263.68十亿元、EBITDA 84.91十亿元和归母利润10.20十亿元。"},
]

CU_2018_Q2_SOURCES = [
    {"label": "中国联通2018年第一季度主要财务及运营数据", "url": CU_2018_Q1_URL, "evidence": "Q1累计值用于从H1累计值复算Q2。"},
    {"label": "中国联通2018中期报告", "url": CU_2018_H1_URL, "evidence": "中期报告披露H1 2018 revenue 149.11十亿元、service revenue 134.42十亿元、EBITDA 45.67十亿元和归母利润5.91十亿元。"},
    {"label": "中国联通2018年报", "url": CU_2018_ANNUAL_REPORT_URL, "evidence": "年报披露全年核心经营值，用于年度链路交叉核验。"},
]

CU_2018_Q3_SOURCES = [
    {"label": "中国联通2018中期报告", "url": CU_2018_H1_URL, "evidence": "H1累计值用于从9M累计值复算Q3。"},
    {"label": "中国联通2018年前三季度主要财务及运营数据", "url": CU_2018_Q3_URL, "evidence": "前三季度公告披露9M revenue 219,712、service revenue 200,013、EBITDA 66,246和归母利润8,780百万元。"},
    {"label": "中国联通2018年报", "url": CU_2018_ANNUAL_REPORT_URL, "evidence": "年报披露全年核心经营值，用于交叉核验9M与FY。"},
]

CU_2018_Q4_SOURCES = [
    {"label": "中国联通2018年前三季度主要财务及运营数据", "url": CU_2018_Q3_URL, "evidence": "前三季度累计值用于从FY累计值复算Q4。"},
    {"label": "中国联通2018年报", "url": CU_2018_ANNUAL_REPORT_URL, "evidence": "年报披露FY2018 revenue 290.88十亿元、service revenue 263.68十亿元、EBITDA 84.91十亿元和归母利润10.20十亿元。"},
    {"label": "中国联通2019年报比较栏", "url": CU_2019_ANNUAL_REPORT_URL, "evidence": "2019年报比较栏列示2018年全年核心经营数据，用于交叉核验。"},
]

CU_2017_Q1_SOURCES = [
    {"label": "中国联通2018年第一季度主要财务及运营数据比较栏", "url": CU_2018_Q1_URL, "evidence": "2018 Q1公告比较栏列示2017 Q1 revenue 69,005、service revenue 61,426和归母利润862百万元。"},
    {"label": "中国联通2017中期报告", "url": CU_2017_H1_URL, "evidence": "中期报告披露H1 2017 revenue 138.16十亿元、service revenue 124.11十亿元和归母利润2.42十亿元，用于交叉核验Q1+Q2。"},
    {"label": "中国联通2017年报", "url": CU_2017_ANNUAL_REPORT_URL, "evidence": "年报披露FY2017 revenue 274.829十亿元、service revenue 249.015十亿元和归母利润1.83十亿元。"},
]

CU_2017_Q2_SOURCES = [
    {"label": "中国联通2018年第一季度主要财务及运营数据比较栏", "url": CU_2018_Q1_URL, "evidence": "2017 Q1比较栏用于从H1累计值复算Q2。"},
    {"label": "中国联通2017中期报告", "url": CU_2017_H1_URL, "evidence": "中期报告披露H1 2017 revenue 138.16十亿元、service revenue 124.11十亿元和归母利润2.42十亿元。"},
    {"label": "中国联通2017年报", "url": CU_2017_ANNUAL_REPORT_URL, "evidence": "年报披露全年核心经营值，用于年度链路交叉核验。"},
]

CU_2017_Q3_SOURCES = [
    {"label": "中国联通2017中期报告", "url": CU_2017_H1_URL, "evidence": "H1累计值用于从9M累计值复算Q3。"},
    {"label": "中国联通2018年前三季度主要财务及运营数据比较栏", "url": CU_2018_Q3_URL, "evidence": "2018年前三季度公告比较栏列示2017 9M revenue 205,778、service revenue 187,880和归母利润4,054百万元。"},
    {"label": "中国联通2017年报", "url": CU_2017_ANNUAL_REPORT_URL, "evidence": "年报披露全年核心经营值，用于交叉核验9M与FY。"},
]

CU_2017_Q4_SOURCES = [
    {"label": "中国联通2018年前三季度主要财务及运营数据比较栏", "url": CU_2018_Q3_URL, "evidence": "2017 9M比较栏用于从FY累计值复算Q4。"},
    {"label": "中国联通2017年报", "url": CU_2017_ANNUAL_REPORT_URL, "evidence": "年报披露FY2017 revenue 274.829十亿元、service revenue 249.015十亿元和归母利润1.83十亿元；Q4归母利润为负主要受光纤网络升级相关资产报废损失影响。"},
    {"label": "中国联通2018年报比较栏", "url": CU_2018_ANNUAL_REPORT_URL, "evidence": "2018年报比较栏再次列示2017年全年核心经营数据，用于交叉核验。"},
]

CU_2016_DISCLOSURE_GAP_SOURCES = [
    {"label": "中国联通2016中期报告", "url": CU_2016_H1_URL, "evidence": "中期报告披露H1 2016累计财务数据，但未提供Q1财务基数，不能精确拆分Q2。"},
    {"label": "中国联通2016年报", "url": CU_2016_ANNUAL_REPORT_URL, "evidence": "年报披露FY2016累计财务数据，但未提供9M财务基数，不能精确拆分Q3/Q4。"},
    {"label": "中国联通2017中期报告比较栏", "url": CU_2017_H1_URL, "evidence": "2017中期报告比较栏可交叉核验2016 H1累计值，但仍未披露2016 Q1/Q2单季财务表。"},
]
CU_2023_Q1_SINA_URL = "https://vip.stock.finance.sina.com.cn/corp/view/vCB_AllBulletinDetail.php?id=9008241&stockid=600050"
CU_2023_H1_SINA_URL = "https://vip.stock.finance.sina.com.cn/corp/view/vCB_AllBulletinDetail.php?id=9395483&stockid=600050"
CU_2023_Q3_SINA_URL = "https://vip.stock.finance.sina.com.cn/corp/view/vCB_AllBulletinDetail.php?id=9587353&stockid=600050"
CU_2023_ANNUAL_SINA_URL = "https://vip.stock.finance.sina.com.cn/corp/view/vCB_AllBulletinDetail.php?id=9883072&stockid=600050"
CU_2024_Q1_URL = "https://doc.irasia.com/listco/hk/chinaunicom/interim/2024/int1q.pdf"
CU_2024_H1_URL = "https://www.chinaunicom.com.hk/en/ir/reports/ir2024.pdf"
CU_2024_Q3_URL = "https://www1.hkexnews.hk/listedco/listconews/sehk/2024/1022/2024102200803.pdf"
CU_2024_ANNUAL_RESULTS_URL = "https://doc.irasia.com/listco/hk/chinaunicom/annual/2024/res.pdf"
CU_2024_Q1_SINA_URL = "https://vip.stock.finance.sina.com.cn/corp/view/vCB_AllBulletinDetail.php?id=10009087&stockid=600050"
CU_2024_H1_SINA_URL = "https://vip.stock.finance.sina.com.cn/corp/view/vCB_AllBulletinDetail.php?id=10379167&stockid=600050"
CU_2024_Q3_SINA_URL = "https://vip.stock.finance.sina.com.cn/corp/view/vCB_AllBulletinDetail.php?id=10537147&stockid=600050"
CU_2024_ANNUAL_SINA_URL = "https://vip.stock.finance.sina.com.cn/corp/view/vCB_AllBulletinDetail.php?id=10790581&stockid=600050"

CU_2026_Q1_SOURCES = [
    {"label": "中国联通2026年第一季度报告（上交所）", "url": CU_2026_Q1_SSE_URL, "evidence": "一季报披露营业收入、营业成本、营业利润、资产负债表和现金流量表。"},
    {"label": "中国联通2026年第一季度报告（雪球PDF镜像）", "url": CU_2026_Q1_XUEQIU_MIRROR_URL, "evidence": "同文PDF镜像可抽取一季报财务报表，用于交叉核验上交所公告。"},
    {"label": "每日经济新闻中国联通2026Q1报道", "url": CU_2026_Q1_NBD_URL, "evidence": "报道摘录营业收入1028.24亿元、利润总额61亿元和归母净利润21.37亿元。"},
]

CU_2025_Q1_SOURCES = [
    {"label": "中国联通2025年第一季度报告（上交所）", "url": CU_2025_Q1_SSE_URL, "evidence": "一季报披露主要会计数据、合并利润表、合并资产负债表和合并现金流量表。"},
    {"label": "中国联通2025年第一季度报告（巨潮资讯）", "url": CU_2025_Q1_CNINFO_URL, "evidence": "同一份一季报PDF镜像可抽取营业成本、现金及现金等价物、借款和租赁负债。"},
    {"label": "南都湾财社中国联通2025Q1报道", "url": CU_2025_Q1_NANDU_URL, "evidence": "报道摘录中国联通2025Q1营业收入1033.5亿元、同比提升3.9%和归母净利润59.3亿元。"},
]

CU_2023_Q1_SOURCES = [
    {"label": "中国联通2023年第一季度主要财务数据", "url": CU_2023_Q1_URL, "evidence": "一季度公告披露Operating revenue、Service revenue、EBITDA、归母利润和收益表成本项。"},
    {"label": "中国联通2023中期报告", "url": CU_2023_H1_URL, "evidence": "中期报告披露H1 revenue、service revenue、operating profits、EBITDA、归母利润、现金流和资产负债表。"},
]

CU_2023_Q2_SOURCES = [
    {"label": "中国联通2023年第一季度主要财务数据", "url": CU_2023_Q1_URL, "evidence": "一季度累计值，用于从H1累计值复核Q2。"},
    {"label": "中国联通2023中期报告", "url": CU_2023_H1_URL, "evidence": "中期报告披露H1 revenue、service revenue、operating profits、EBITDA和归母利润。"},
]

CU_2023_Q3_SOURCES = [
    {"label": "中国联通2023中期报告", "url": CU_2023_H1_URL, "evidence": "H1累计值用于从前三季度累计值复核Q3。"},
    {"label": "中国联通2023年前三季度业绩公告", "url": CU_2023_Q3_URL, "evidence": "前三季度公告披露Operating revenue、Service revenue、EBITDA、归母利润和收益表成本项。"},
]

CU_2023_Q4_SOURCES = [
    {"label": "中国联通2023年前三季度业绩公告", "url": CU_2023_Q3_URL, "evidence": "前三季度累计值用于从全年披露复核Q4。"},
    {"label": "中国联通2023年度业绩公告", "url": CU_2023_ANNUAL_RESULTS_URL, "evidence": "年度业绩公告披露全年revenue、service revenue、operating profits、EBITDA和归母利润。"},
]

CU_2022_Q1_SOURCES = [
    {"label": "中国联通2022年第一季度主要财务数据", "url": CU_2022_Q1_URL, "evidence": "一季度公告披露Operating revenue 89,022百万元、EBITDA 25,031百万元、归母利润4,634百万元和收入同比8.2%。"},
    {"label": "中国联通2022中期报告", "url": CU_2022_H1_URL, "evidence": "中期报告披露H1 revenue 176,261百万元、EBITDA 51.41十亿元和股东应占利润10,957百万元，用于交叉核验Q1+Q2。"},
]

CU_2022_Q2_SOURCES = [
    {"label": "中国联通2022年第一季度主要财务数据", "url": CU_2022_Q1_URL, "evidence": "一季度累计值，用于从H1累计值复核Q2。"},
    {"label": "中国联通2022中期报告", "url": CU_2022_H1_URL, "evidence": "中期报告披露H1 revenue 176,261百万元、EBITDA 51.41十亿元、股东应占利润10,957百万元和 service revenue 160,971百万元。"},
    {"label": "中国联通2022年报", "url": CU_2022_ANNUAL_REPORT_URL, "evidence": "年报披露FY2022 operating revenue 354,944百万元、EBITDA 99,169百万元和净利润16,745百万元，用于全年合计交叉核验。"},
]

CU_2022_Q3_SOURCES = [
    {"label": "中国联通2022中期报告", "url": CU_2022_H1_URL, "evidence": "中期报告提供H1累计值，用于从9M累计值复核Q3。"},
    {"label": "中国联通2022年前三季度业绩公告", "url": CU_2022_Q3_URL, "evidence": "前三季度公告披露Operating revenue 263,978百万元、EBITDA 76,735百万元和归母利润15,667百万元。"},
    {"label": "中国联通2022年报", "url": CU_2022_ANNUAL_REPORT_URL, "evidence": "年报披露全年核心经营数据，用于交叉核验9M与全年合计关系。"},
]

CU_2022_Q4_SOURCES = [
    {"label": "中国联通2022年前三季度业绩公告", "url": CU_2022_Q3_URL, "evidence": "前三季度累计值，用于从全年披露复核Q4。"},
    {"label": "中国联通2022年报", "url": CU_2022_ANNUAL_REPORT_URL, "evidence": "年报披露FY2022 operating revenue 354,944百万元、EBITDA 99,169百万元和净利润16,745百万元。"},
    {"label": "中国联通2022中期报告", "url": CU_2022_H1_URL, "evidence": "中期报告提供H1累计值，用于交叉核验2022拆分链路。"},
]

CU_2021_Q2_SOURCES = [
    {"label": "中国联通2021年第一季度主要财务数据", "url": CU_2021_Q1_URL, "evidence": "一季度公告披露Total revenue 82,272百万元、EBITDA 23.64十亿元和归母利润3,843百万元。"},
    {"label": "中国联通2021中期报告", "url": CU_2021_H1_URL, "evidence": "中期报告披露H1 Revenue 164,174百万元、EBITDA 49.49十亿元和归母利润9,167百万元。"},
    {"label": "中国联通2021年报", "url": CU_2021_ANNUAL_REPORT_URL, "evidence": "年报披露FY2021 Revenue 327,854百万元、EBITDA 96.32十亿元和归母利润14,368百万元，用于全年合计交叉核验。"},
]

CU_2021_Q3_SOURCES = [
    {"label": "中国联通2021中期报告", "url": CU_2021_H1_URL, "evidence": "中期报告提供H1累计值，用于从9M累计值复核Q3。"},
    {"label": "中国联通2021年前三季度业绩公告", "url": CU_2021_Q3_URL, "evidence": "前三季度公告披露Total revenue 244,489百万元、EBITDA 75.337十亿元和归母利润12,923百万元。"},
    {"label": "中国联通2021年报", "url": CU_2021_ANNUAL_REPORT_URL, "evidence": "年报披露全年核心经营数据，用于交叉核验9M与全年合计关系。"},
]

CU_2021_Q4_SOURCES = [
    {"label": "中国联通2021年前三季度业绩公告", "url": CU_2021_Q3_URL, "evidence": "前三季度累计值，用于从全年披露复核Q4。"},
    {"label": "中国联通2021年报", "url": CU_2021_ANNUAL_REPORT_URL, "evidence": "年报披露FY2021 Revenue 327,854百万元、EBITDA 96.32十亿元和归母利润14,368百万元。"},
    {"label": "中国联通2021中期报告", "url": CU_2021_H1_URL, "evidence": "中期报告提供H1累计值，用于交叉核验2021拆分链路。"},
]

CU_2023_Q1_DETAIL_SOURCES = [
    {"label": "中国联通2023年第一季度主要财务数据（港股公告）", "url": CU_2023_Q1_URL, "evidence": "港股一季度公告披露经营收入、EBITDA、归母利润和收益表成本项。"},
    {"label": "中国联通2023年第一季度报告（新浪财经A股公告）", "url": CU_2023_Q1_SINA_URL, "evidence": "A股一季报披露营业收入、营业成本、现金及现金等价物、资产负债表和债务科目。"},
]

CU_2023_Q2_DETAIL_SOURCES = [
    {"label": "中国联通2023年第一季度报告（新浪财经A股公告）", "url": CU_2023_Q1_SINA_URL, "evidence": "Q1 A股报表用于从H1累计值复算Q2。"},
    {"label": "中国联通2023年半年度报告（新浪财经A股公告）", "url": CU_2023_H1_SINA_URL, "evidence": "A股半年报披露H1营业收入、营业成本、现金及现金等价物、资产负债和债务科目。"},
    {"label": "中国联通2023中期报告", "url": CU_2023_H1_URL, "evidence": "港股中期报告披露H1收入、EBITDA和归母利润，用于交叉核验累计趋势。"},
]

CU_2023_Q3_DETAIL_SOURCES = [
    {"label": "中国联通2023年半年度报告（新浪财经A股公告）", "url": CU_2023_H1_SINA_URL, "evidence": "H1累计值用于从前三季度A股累计值复算Q3。"},
    {"label": "中国联通2023年第三季度报告（新浪财经A股公告）", "url": CU_2023_Q3_SINA_URL, "evidence": "A股三季报披露前三季度营业收入、营业成本、现金及现金等价物、资产负债和债务科目。"},
    {"label": "中国联通2023年前三季度业绩公告", "url": CU_2023_Q3_URL, "evidence": "港股前三季度公告披露经营收入、EBITDA和归母利润，用于交叉核验累计趋势。"},
]

CU_2023_Q4_DETAIL_SOURCES = [
    {"label": "中国联通2023年第三季度报告（新浪财经A股公告）", "url": CU_2023_Q3_SINA_URL, "evidence": "前三季度累计值用于从A股全年值复算Q4。"},
    {"label": "中国联通2023年度报告（新浪财经A股公告）", "url": CU_2023_ANNUAL_SINA_URL, "evidence": "A股年报披露全年营业收入、营业成本、现金及现金等价物、资产负债和债务科目。"},
    {"label": "中国联通2023年度业绩公告", "url": CU_2023_ANNUAL_RESULTS_URL, "evidence": "港股年度业绩公告披露全年经营收入、EBITDA和归母利润，用于交叉核验全年趋势。"},
]

CU_2024_Q1_SOURCES = [
    {"label": "中国联通2024年第一季度主要财务数据", "url": CU_2024_Q1_URL, "evidence": "一季度公告披露Operating revenue 99,496百万元、EBITDA和归母利润。"},
    {"label": "中国联通2024中期报告", "url": CU_2024_H1_URL, "evidence": "中期报告披露H1收入197.34十亿元、EBITDA 55.01十亿元和归母利润13.79十亿元，用于交叉核验Q1+Q2。"},
]

CU_2024_Q2_SOURCES = [
    {"label": "中国联通2024年第一季度主要财务数据", "url": CU_2024_Q1_URL, "evidence": "一季度累计值，用于从H1累计值复核Q2。"},
    {"label": "中国联通2024中期报告", "url": CU_2024_H1_URL, "evidence": "中期报告披露H1收入197.34十亿元、EBITDA 55.01十亿元和归母利润13.79十亿元。"},
]

CU_2024_Q3_SOURCES = [
    {"label": "中国联通2024中期报告", "url": CU_2024_H1_URL, "evidence": "H1累计值用于从前三季度累计值复核Q3。"},
    {"label": "中国联通2024年前三季度业绩公告", "url": CU_2024_Q3_URL, "evidence": "前三季度公告披露Operating revenue 290.12十亿元、EBITDA 80.40十亿元和归母利润19.03十亿元。"},
]

CU_2024_Q4_SOURCES = [
    {"label": "中国联通2024年前三季度业绩公告", "url": CU_2024_Q3_URL, "evidence": "前三季度累计值用于从全年披露复核Q4。"},
    {"label": "中国联通2024年度业绩公告", "url": CU_2024_ANNUAL_RESULTS_URL, "evidence": "年度业绩公告披露全年经营收入389.589十亿元、EBITDA 99.42十亿元和归母利润20.613十亿元。"},
]

CU_2024_Q1_DETAIL_SOURCES = [
    {"label": "中国联通2024年第一季度主要财务数据（港股公告）", "url": CU_2024_Q1_URL, "evidence": "港股一季度公告披露经营收入、EBITDA和归母利润。"},
    {"label": "中国联通2024年第一季度报告（新浪财经A股公告）", "url": CU_2024_Q1_SINA_URL, "evidence": "A股一季报披露营业收入、营业成本、营业利润、现金及现金等价物、资产负债表和同比比较数。"},
]

CU_2024_Q2_DETAIL_SOURCES = [
    {"label": "中国联通2024年第一季度报告（新浪财经A股公告）", "url": CU_2024_Q1_SINA_URL, "evidence": "Q1 A股报表用于从H1累计值复算Q2。"},
    {"label": "中国联通2024年半年度报告（新浪财经A股公告）", "url": CU_2024_H1_SINA_URL, "evidence": "A股半年报披露H1营业收入、营业成本、营业利润、净利润、现金及现金等价物、资产负债和债务科目。"},
    {"label": "中国联通2024中期报告（0762.HK）", "url": CU_2024_H1_URL, "evidence": "港股中期报告披露H1收入、EBITDA和归母利润，用于交叉核验累计趋势。"},
]

CU_2024_Q3_DETAIL_SOURCES = [
    {"label": "中国联通2024年半年度报告（新浪财经A股公告）", "url": CU_2024_H1_SINA_URL, "evidence": "H1累计值用于从前三季度A股累计值复算Q3。"},
    {"label": "中国联通2024年第三季度报告（新浪财经A股公告）", "url": CU_2024_Q3_SINA_URL, "evidence": "A股三季报披露前三季度营业收入、营业成本、营业利润、净利润、现金及现金等价物、资产负债和债务科目。"},
    {"label": "中国联通2024年前三季度业绩公告（港股公告）", "url": CU_2024_Q3_URL, "evidence": "港股前三季度公告披露经营收入、EBITDA和归母利润，用于交叉核验累计趋势。"},
]

CU_2024_Q4_DETAIL_SOURCES = [
    {"label": "中国联通2024年第三季度报告（新浪财经A股公告）", "url": CU_2024_Q3_SINA_URL, "evidence": "前三季度累计值用于从A股全年值复算Q4。"},
    {"label": "中国联通2024年度报告（新浪财经A股公告）", "url": CU_2024_ANNUAL_SINA_URL, "evidence": "A股年报披露全年营业收入、营业成本、营业利润、净利润、现金及现金等价物、资产负债和债务科目。"},
    {"label": "中国联通2024年度业绩公告", "url": CU_2024_ANNUAL_RESULTS_URL, "evidence": "港股年度业绩公告披露全年经营收入、EBITDA和归母利润，用于交叉核验全年趋势。"},
]

CU_2025_Q2_SOURCES = [
    {"label": "中国联通2025年第一季度报告（上交所，600050 A股口径）", "url": CU_2025_Q1_SSE_URL, "evidence": "一季度营业收入、营业利润、经营现金流、资本开支和总资产。"},
    {"label": "中国联通2025中期报告（0762.HK）", "url": CU_2025_H1_URL, "evidence": "上半年收入、服务收入、经营利润、EBITDA、经营现金流、资本开支、自由现金流和总资产。"},
]

CU_2025_Q2_DETAIL_SOURCES = [
    {"label": "中国联通2025年第一季度报告（上交所，600050 A股口径）", "url": CU_2025_Q1_SSE_URL, "evidence": "一季度合并利润表、资产负债表和现金流量表，用于从A股H1累计值复算Q2。"},
    {"label": "中国联通2025年半年度报告（新浪财经A股公告）", "url": CU_2025_H1_SINA_URL, "evidence": "半年度报告披露H1营业收入、营业成本、营业利润、净利润、现金及现金等价物、资产负债和债务科目。"},
    {"label": "中国联通2025中期报告（IRAsia中文）", "url": CU_2025_H1_IRASIA_CN_URL, "evidence": "港股中期报告披露收入、EBITDA、现金流、资本开支、资产和带息债务等管理层口径，用于交叉核验披露方向。"},
]

CU_2025_Q3_DETAIL_SOURCES = [
    {"label": "中国联通2025年半年度报告（新浪财经A股公告）", "url": CU_2025_H1_SINA_URL, "evidence": "H1累计值用于从前三季度A股累计值复算Q3。"},
    {"label": "中国联通2025年第三季度报告（新浪财经A股公告）", "url": CU_2025_Q3_SINA_URL, "evidence": "三季报披露Q3本期营业收入、前三季度营业成本、营业利润、净利润、现金及现金等价物、总资产和债务科目。"},
    {"label": "国务院国资委中国联通2025年前三季度经营报道", "url": CU_2025_Q3_SASAC_URL, "evidence": "报道摘录前三季度营业收入、利润总额和联网通信收入等经营结果，用作方向性交叉核验。"},
]

CU_2025_H2_SOURCES = [
    {"label": "中国联通2025中期报告（0762.HK）", "url": CU_2025_H1_URL, "evidence": "上半年累计值，用于从全年披露复算H2。"},
    {"label": "中国联通2025年度业绩公告", "url": CU_2025_ANNUAL_RESULTS_URL, "evidence": "全年经营收入、服务收入、净利润、自由现金流和资本开支。"},
    {"label": "中国联通2025年报（0762.HK）", "url": CU_2025_ANNUAL_REPORT_URL, "evidence": "全年财务报表和资产负债表。"},
]

CU_2025_Q4_DETAIL_SOURCES = [
    {"label": "中国联通2025年第三季度报告（新浪财经A股公告）", "url": CU_2025_Q3_SINA_URL, "evidence": "前三季度累计值用于从A股全年值复算Q4。"},
    {"label": "中国联通2025年度报告（新浪财经A股公告）", "url": CU_2025_ANNUAL_SINA_URL, "evidence": "年度报告披露全年营业收入、营业成本、营业利润、净利润、现金及现金等价物、总资产和债务科目。"},
    {"label": "中国联通2025年度业绩公告", "url": CU_2025_ANNUAL_RESULTS_URL, "evidence": "港股年度业绩公告披露全年经营收入、服务收入、净利润、自由现金流和资本开支。"},
    {"label": "中国联通2025年报（0762.HK）", "url": CU_2025_ANNUAL_REPORT_URL, "evidence": "港股年报披露全年财务报表和资产负债表，用于交叉核验资产负债方向。"},
]

HTHKH_2025_H1_HIGHLIGHTS_URL = "https://www.hthkh.com/en/ir/reports/ir2025/highlights.pdf"
HTHKH_2025_H1_ANALYSIS_URL = "https://www.hthkh.com/en/ir/reports/ir2025/analysis.pdf"
HTHKH_2025_H1_POSITION_URL = "https://www.hthkh.com/en/ir/reports/ir2025/financialposition.pdf"
HTHKH_2025_H1_CASHFLOW_URL = "https://www.hthkh.com/en/ir/reports/ir2025/cashflows.pdf"
HTHKH_2025_AR_HIGHLIGHTS_URL = "https://www.hthkh.com/en/ir/reports/ar2025/highlights.pdf"
HTHKH_2025_AR_ANALYSIS_URL = "https://www.hthkh.com/en/ir/reports/ar2025/analysis.pdf"
HTHKH_2025_AR_POSITION_URL = "https://www.hthkh.com/en/ir/reports/ar2025/financialposition.pdf"
HTHKH_2025_AR_CASHFLOW_URL = "https://www.hthkh.com/en/ir/reports/ar2025/cashflows.pdf"
HTHKH_2024_INTERIM_REPORT_URL = "https://www.hthkh.com/en/ir/reports/ir2024/ir2024.pdf"
HTHKH_2024_H1_ANALYSIS_URL = "https://www.hthkh.com/en/ir/reports/ir2024/analysis.pdf"
HTHKH_2024_AR_HIGHLIGHTS_URL = "https://www.hthkh.com/en/ir/reports/ar2024/highlights.pdf"
HTHKH_2024_AR_ANALYSIS_URL = "https://www.hthkh.com/en/ir/reports/ar2024/analysis.pdf"
HTHKH_2024_AR_POSITION_URL = "https://www.hthkh.com/en/ir/reports/ar2024/financialposition.pdf"
HTHKH_2024_AR_CASHFLOW_URL = "https://www.hthkh.com/en/ir/reports/ar2024/cashflows.pdf"
HTHKH_2023_INTERIM_REPORT_URL = "https://www.hthkh.com/en/ir/reports/ir2023/ir2023.pdf"
HTHKH_2023_H1_ANALYSIS_URL = "https://www.hthkh.com/en/ir/reports/ir2023/analysis.pdf"
HTHKH_2023_AR_HIGHLIGHTS_URL = "https://www.hthkh.com/en/ir/reports/ar2023/highlights.pdf"
HTHKH_2023_AR_ANALYSIS_URL = "https://www.hthkh.com/en/ir/reports/ar2023/analysis.pdf"
HTHKH_2023_AR_POSITION_URL = "https://www.hthkh.com/en/ir/reports/ar2023/financialposition.pdf"
HTHKH_2023_AR_CASHFLOW_URL = "https://www.hthkh.com/en/ir/reports/ar2023/cashflows.pdf"
HTHKH_2022_INTERIM_REPORT_URL = "https://www.hthkh.com/en/ir/reports/ir2022/ir2022.pdf"
HTHKH_2022_ANNUAL_REPORT_URL = "https://www.hthkh.com/en/ir/reports/ar2022/ar2022.pdf"
HTHKH_2021_INTERIM_REPORT_URL = "https://www.hthkh.com/en/ir/reports/ir2021/ir2021.pdf"
HTHKH_2021_ANNUAL_REPORT_URL = "https://www.hthkh.com/en/ir/reports/ar2021/ar2021.pdf"
HTHKH_2020_INTERIM_REPORT_URL = "https://www.hthkh.com/en/ir/reports/ir2020/ir2020.pdf"
HTHKH_2020_ANNUAL_REPORT_URL = "https://www.hthkh.com/en/ir/reports/ar2020/ar2020.pdf"
HTHKH_2019_INTERIM_REPORT_URL = "https://www.hthkh.com/en/ir/reports/ir2019/ir2019.pdf"
HTHKH_2019_ANNUAL_REPORT_URL = "https://www.hthkh.com/en/ir/reports/ar2019/ar2019.pdf"
HTHKH_2018_INTERIM_REPORT_URL = "https://www.hthkh.com/en/ir/reports/ir2018/ir2018.pdf"
HTHKH_2018_ANNUAL_REPORT_URL = "https://www.hthkh.com/en/ir/reports/ar2018/ar2018.pdf"
HTHKH_2017_INTERIM_REPORT_URL = "https://www.hthkh.com/en/ir/reports/ir2017/ir2017.pdf"
HTHKH_2017_ANNUAL_REPORT_URL = "https://www.hthkh.com/en/ir/reports/ar2017/ar2017.pdf"
HTHKH_2016_INTERIM_REPORT_URL = "https://www.hthkh.com/en/ir/reports/ir2016/ir2016.pdf"
HTHKH_2016_ANNUAL_REPORT_URL = "https://www.hthkh.com/en/ir/reports/ar2016/ar2016.pdf"

HTHKH_2016_2020_SOURCES_BY_PERIOD = {
    "H1 2016": [
        {"label": "HTHKH 2016 Interim Report - Highlights", "url": HTHKH_2016_INTERIM_REPORT_URL, "evidence": "1H 2016 consolidated/mobile revenue, EBITDA, EBIT and shareholder profit summary."},
        {"label": "HTHKH 2016 Interim Report - MD&A mobile business", "url": HTHKH_2016_INTERIM_REPORT_URL, "evidence": "1H 2016 mobile Total revenue and EBITDA table."},
        {"label": "HTHKH 2016 Annual Report - 2016 mobile comparison", "url": HTHKH_2016_ANNUAL_REPORT_URL, "evidence": "FY2016 mobile total revenue and EBITDA comparison for H2 reconciliation."},
    ],
    "H2 2016": [
        {"label": "HTHKH 2016 Interim Report", "url": HTHKH_2016_INTERIM_REPORT_URL, "evidence": "1H 2016 mobile metrics used to reconcile H2 from FY2016."},
        {"label": "HTHKH 2016 Annual Report - mobile business highlights", "url": HTHKH_2016_ANNUAL_REPORT_URL, "evidence": "FY2016 mobile total revenue and EBITDA."},
        {"label": "HTHKH 2017 Annual Report - restated 2016 mobile comparison", "url": HTHKH_2017_ANNUAL_REPORT_URL, "evidence": "Restated FY2016 mobile revenue and EBITDA cross-check."},
    ],
    "H1 2017": [
        {"label": "HTHKH 2017 Interim Report - Highlights", "url": HTHKH_2017_INTERIM_REPORT_URL, "evidence": "1H 2017 consolidated/mobile revenue, EBITDA and profit summary."},
        {"label": "HTHKH 2017 Interim Report - MD&A mobile business", "url": HTHKH_2017_INTERIM_REPORT_URL, "evidence": "1H 2017 mobile Total revenue and EBITDA table."},
        {"label": "HTHKH 2017 Annual Report - mobile business highlights", "url": HTHKH_2017_ANNUAL_REPORT_URL, "evidence": "FY2017 mobile revenue and EBITDA for H2 reconciliation."},
    ],
    "H2 2017": [
        {"label": "HTHKH 2017 Interim Report", "url": HTHKH_2017_INTERIM_REPORT_URL, "evidence": "1H 2017 mobile metrics used to reconcile H2 from FY2017."},
        {"label": "HTHKH 2017 Annual Report - mobile business highlights", "url": HTHKH_2017_ANNUAL_REPORT_URL, "evidence": "FY2017 mobile revenue and EBITDA excluding one-off disposal items."},
        {"label": "HTHKH 2018 Annual Report - 2017 comparison", "url": HTHKH_2018_ANNUAL_REPORT_URL, "evidence": "2017 continuing mobile revenue and EBITDA comparison after fixed-line disposal."},
    ],
    "H1 2018": [
        {"label": "HTHKH 2018 Interim Report - Highlights", "url": HTHKH_2018_INTERIM_REPORT_URL, "evidence": "1H 2018 revenue, EBITDA and profit attributable to shareholders from continuing operations."},
        {"label": "HTHKH 2018 Interim Report - MD&A", "url": HTHKH_2018_INTERIM_REPORT_URL, "evidence": "1H 2018 Business Highlights table."},
        {"label": "HTHKH 2018 Annual Report - Financial Summary", "url": HTHKH_2018_ANNUAL_REPORT_URL, "evidence": "FY2018 revenue, EBITDA and profit for H2 reconciliation."},
    ],
    "H2 2018": [
        {"label": "HTHKH 2018 Interim Report", "url": HTHKH_2018_INTERIM_REPORT_URL, "evidence": "1H 2018 metrics used to reconcile H2 from FY2018."},
        {"label": "HTHKH 2018 Annual Report - Financial Highlights", "url": HTHKH_2018_ANNUAL_REPORT_URL, "evidence": "FY2018 revenue, EBITDA and profit attributable to shareholders."},
        {"label": "HTHKH 2019 Annual Report - 2018 comparison", "url": HTHKH_2019_ANNUAL_REPORT_URL, "evidence": "2018 revenue, EBITDA and shareholder profit comparison."},
    ],
    "H1 2019": [
        {"label": "HTHKH 2019 Interim Report - Highlights", "url": HTHKH_2019_INTERIM_REPORT_URL, "evidence": "1H 2019 post-IFRS 16 revenue, EBITDA and shareholder profit."},
        {"label": "HTHKH 2019 Interim Report - Financial Summary", "url": HTHKH_2019_INTERIM_REPORT_URL, "evidence": "1H 2019 revenue and EBITDA table."},
        {"label": "HTHKH 2019 Annual Report - Financial Summary", "url": HTHKH_2019_ANNUAL_REPORT_URL, "evidence": "FY2019 revenue, EBITDA and shareholder profit for H2 reconciliation."},
    ],
    "H2 2019": [
        {"label": "HTHKH 2019 Interim Report", "url": HTHKH_2019_INTERIM_REPORT_URL, "evidence": "1H 2019 metrics used to reconcile H2 from FY2019."},
        {"label": "HTHKH 2019 Annual Report - Financial Highlights", "url": HTHKH_2019_ANNUAL_REPORT_URL, "evidence": "FY2019 post-IFRS 16 revenue, EBITDA and shareholder profit."},
        {"label": "HTHKH 2020 Annual Report - 2019 comparison", "url": HTHKH_2020_ANNUAL_REPORT_URL, "evidence": "2019 revenue, EBITDA and shareholder profit comparison."},
    ],
    "H1 2020": [
        {"label": "HTHKH 2020 Interim Report - Highlights", "url": HTHKH_2020_INTERIM_REPORT_URL, "evidence": "1H 2020 post-IFRS 16 revenue, EBITDA and shareholder profit."},
        {"label": "HTHKH 2020 Interim Report - Financial Summary", "url": HTHKH_2020_INTERIM_REPORT_URL, "evidence": "1H 2020 revenue and EBITDA table."},
        {"label": "HTHKH 2020 Annual Report - Financial Summary", "url": HTHKH_2020_ANNUAL_REPORT_URL, "evidence": "FY2020 revenue, EBITDA and shareholder profit for H2 reconciliation."},
    ],
    "H2 2020": [
        {"label": "HTHKH 2020 Interim Report", "url": HTHKH_2020_INTERIM_REPORT_URL, "evidence": "1H 2020 metrics used to reconcile H2 from FY2020."},
        {"label": "HTHKH 2020 Annual Report - Financial Highlights", "url": HTHKH_2020_ANNUAL_REPORT_URL, "evidence": "FY2020 post-IFRS 16 revenue, EBITDA and shareholder profit."},
        {"label": "HTHKH 2021 Annual Report - 2020 comparison", "url": HTHKH_2021_ANNUAL_REPORT_URL, "evidence": "2020 revenue comparison used in later-period reconciliation."},
    ],
}

HTHKH_2016_2020_METRICS = {
    "H1 2016": {
        "revenue": (3472, "2016中报MD&A Mobile business表披露1H 2016 Total revenue为3,472百万港元。"),
        "ebitda": (665, "2016中报MD&A Mobile business表披露1H 2016 EBITDA为665百万港元。"),
    },
    "H2 2016": {
        "revenue": (4860, "2016年报披露FY2016 mobile Total revenue 8,332百万港元；减1H 2016 mobile Total revenue 3,472百万港元，复算H2为4,860百万港元。"),
        "ebitda": (668, "2016年报披露FY2016 mobile EBITDA 1,333百万港元；减1H 2016 mobile EBITDA 665百万港元，复算H2为668百万港元。"),
    },
    "H1 2017": {
        "revenue": (3117, "2017中报MD&A Mobile business表披露1H 2017 Total revenue为3,117百万港元。"),
        "ebitda": (647, "2017中报MD&A Mobile business表披露1H 2017 EBITDA为647百万港元。"),
    },
    "H2 2017": {
        "revenue": (3635, "2017年报Mobile Business Highlights披露FY2017 Total mobile revenue 6,752百万港元；减1H 2017 mobile revenue 3,117百万港元，复算H2为3,635百万港元。"),
        "ebitda": (692, "2017年报Mobile Business Highlights披露FY2017 Mobile EBITDA 1,339百万港元；减1H 2017 EBITDA 647百万港元，复算H2为692百万港元。"),
    },
    "H1 2018": {
        "revenue": (4021, "2018中报Business Highlights表披露1H 2018 Revenue为4,021百万港元。"),
        "ebitda": (601, "2018中报Business Highlights表披露1H 2018 EBITDA为601百万港元。"),
        "net_income": (198, "2018中报披露1H 2018 Profit attributable to shareholders from continuing operations为198百万港元。"),
    },
    "H2 2018": {
        "revenue": (3891, "2018年报Financial Summary披露FY2018 Revenue 7,912百万港元；减1H 2018 Revenue 4,021百万港元，复算H2为3,891百万港元。"),
        "ebitda": (556, "2018年报Financial Summary披露FY2018 EBITDA 1,157百万港元；减1H 2018 EBITDA 601百万港元，复算H2为556百万港元。"),
        "net_income": (206, "2018年报披露FY2018 Profit attributable to shareholders 404百万港元；减1H 2018 continuing profit 198百万港元，复算H2为206百万港元。"),
    },
    "H1 2019": {
        "revenue": (2515, "2019中报Financial Summary披露1H 2019 Revenue为2,515百万港元。"),
        "ebitda": (787, "2019中报Post-IFRS 16 Financial Summary披露1H 2019 EBITDA为787百万港元。"),
        "net_income": (188, "2019中报披露1H 2019 Profit attributable to shareholders为188百万港元。"),
    },
    "H2 2019": {
        "revenue": (3067, "2019年报Financial Summary披露FY2019 Revenue 5,582百万港元；减1H 2019 Revenue 2,515百万港元，复算H2为3,067百万港元。"),
        "ebitda": (875, "2019年报Post-IFRS 16 Financial Highlights披露FY2019 Total EBITDA 1,662百万港元；减1H 2019 EBITDA 787百万港元，复算H2为875百万港元。"),
        "net_income": (241, "2019年报披露FY2019 Profit attributable to shareholders 429百万港元；减1H 2019利润188百万港元，复算H2为241百万港元。"),
    },
    "H1 2020": {
        "revenue": (1982, "2020中报Financial Summary披露1H 2020 Revenue为1,982百万港元。"),
        "ebitda": (778, "2020中报Post-IFRS 16 Financial Summary披露1H 2020 EBITDA为778百万港元。"),
        "net_income": (146, "2020中报披露1H 2020 Profit attributable to shareholders为146百万港元。"),
    },
    "H2 2020": {
        "revenue": (2563, "2020年报Financial Summary披露FY2020 Revenue 4,545百万港元；减1H 2020 Revenue 1,982百万港元，复算H2为2,563百万港元。"),
        "ebitda": (894, "2020年报Post-IFRS 16 Financial Highlights披露FY2020 Total EBITDA 1,672百万港元；减1H 2020 EBITDA 778百万港元，复算H2为894百万港元。"),
        "net_income": (215, "2020年报披露FY2020 Profit attributable to shareholders 361百万港元；减1H 2020利润146百万港元，复算H2为215百万港元。"),
    },
}

HTHKH_2021_H1_SOURCES = [
    {"label": "HTHKH 2021 Interim Report - Financial Highlights", "url": HTHKH_2021_INTERIM_REPORT_URL, "evidence": "1H 2021 total revenue、Total EBITDA、Total EBIT和股东应占利润。"},
    {"label": "HTHKH 2021 Interim Report - MD&A", "url": HTHKH_2021_INTERIM_REPORT_URL, "evidence": "1H 2021 revenue、net customer service revenue、total margin、CAPEX、EBITDA和经营表现。"},
    {"label": "HTHKH 2021 Interim Report - Financial Statements", "url": HTHKH_2021_INTERIM_REPORT_URL, "evidence": "1H 2021损益表、资产负债表、现金流量表及公司/子公司与合营公司调节表。"},
]

HTHKH_2021_H2_SOURCES = [
    {"label": "HTHKH 2021 Interim Report", "url": HTHKH_2021_INTERIM_REPORT_URL, "evidence": "1H累计值，用于从全年披露复算H2。"},
    {"label": "HTHKH 2021 Annual Report - Financial Highlights", "url": HTHKH_2021_ANNUAL_REPORT_URL, "evidence": "2021全年Total revenue、Total EBITDA、Total EBIT和股东应占利润。"},
    {"label": "HTHKH 2021 Annual Report - MD&A", "url": HTHKH_2021_ANNUAL_REPORT_URL, "evidence": "2021全年Revenue、net customer service revenue、total margin、EBITDA、CAPEX和利润。"},
    {"label": "HTHKH 2021 Annual Report - Cash Flows", "url": HTHKH_2021_ANNUAL_REPORT_URL, "evidence": "2021全年经营现金流和购置固定资产现金支出。"},
    {"label": "HTHKH 2021 Annual Report - Financial Position", "url": HTHKH_2021_ANNUAL_REPORT_URL, "evidence": "2021年底现金、总资产和租赁负债。"},
]

HTHKH_2022_H1_SOURCES = [
    {"label": "HTHKH 2022 Interim Report - Financial Highlights", "url": HTHKH_2022_INTERIM_REPORT_URL, "evidence": "1H 2022 total revenue、Total EBITDA、Total LBIT和股东应占亏损。"},
    {"label": "HTHKH 2022 Interim Report - MD&A", "url": HTHKH_2022_INTERIM_REPORT_URL, "evidence": "1H 2022 revenue、net customer service revenue、total margin、CAPEX、EBITDA和经营表现。"},
    {"label": "HTHKH 2022 Interim Report - Financial Statements", "url": HTHKH_2022_INTERIM_REPORT_URL, "evidence": "1H 2022损益表、资产负债表、现金流量表及公司/子公司与合营公司调节表。"},
]

HTHKH_2022_H2_SOURCES = [
    {"label": "HTHKH 2022 Interim Report", "url": HTHKH_2022_INTERIM_REPORT_URL, "evidence": "1H累计值，用于从全年披露复算H2。"},
    {"label": "HTHKH 2022 Annual Report - Financial Highlights", "url": HTHKH_2022_ANNUAL_REPORT_URL, "evidence": "2022全年Total revenue、Total EBITDA、Total LBIT和股东应占亏损。"},
    {"label": "HTHKH 2022 Annual Report - MD&A", "url": HTHKH_2022_ANNUAL_REPORT_URL, "evidence": "2022全年Revenue、net customer service revenue、total margin、EBITDA、CAPEX和利润。"},
    {"label": "HTHKH 2022 Annual Report - Cash Flows", "url": HTHKH_2022_ANNUAL_REPORT_URL, "evidence": "2022全年经营现金流和购置固定资产现金支出。"},
    {"label": "HTHKH 2022 Annual Report - Financial Position", "url": HTHKH_2022_ANNUAL_REPORT_URL, "evidence": "2022年底现金、总资产和租赁负债。"},
]

HTHKH_2023_H1_SOURCES = [
    {"label": "HTHKH 2023 Interim Report - Financial Highlights", "url": HTHKH_2023_INTERIM_REPORT_URL, "evidence": "1H 2023 total revenue、service revenue、Total EBITDA、LBIT和股东应占亏损。"},
    {"label": "HTHKH 2023 Interim Report - MD&A", "url": HTHKH_2023_H1_ANALYSIS_URL, "evidence": "1H 2023 revenue、net customer service revenue、total margin、EBITDA、CAPEX、经营表现和KPI。"},
    {"label": "HTHKH 2023 Interim Report - Financial Statements", "url": HTHKH_2023_INTERIM_REPORT_URL, "evidence": "1H 2023损益表、资产负债表、现金流量表及公司/子公司与合营公司调节表。"},
]

HTHKH_2023_H2_SOURCES = [
    {"label": "HTHKH 2023 Interim Report", "url": HTHKH_2023_INTERIM_REPORT_URL, "evidence": "1H累计值，用于从全年披露复算H2。"},
    {"label": "HTHKH 2023 Annual Report - Financial Highlights", "url": HTHKH_2023_AR_HIGHLIGHTS_URL, "evidence": "2023全年Total revenue、Total EBITDA、Total LBIT和股东应占亏损。"},
    {"label": "HTHKH 2023 Annual Report - MD&A", "url": HTHKH_2023_AR_ANALYSIS_URL, "evidence": "2023全年Revenue、net customer service revenue、total margin、EBITDA、CAPEX和利润。"},
    {"label": "HTHKH 2023 Annual Report - Cash Flows", "url": HTHKH_2023_AR_CASHFLOW_URL, "evidence": "2023全年经营现金流和购置固定资产现金支出。"},
    {"label": "HTHKH 2023 Annual Report - Financial Position", "url": HTHKH_2023_AR_POSITION_URL, "evidence": "2023年底现金、总资产和租赁负债。"},
]

HTHKH_2024_H1_SOURCES = [
    {"label": "HTHKH 2024 Interim Report - Financial Highlights", "url": HTHKH_2024_INTERIM_REPORT_URL, "evidence": "1H 2024 total revenue、service revenue、Total EBITDA、LBIT和股东应占亏损。"},
    {"label": "HTHKH 2024 Interim Report - MD&A", "url": HTHKH_2024_H1_ANALYSIS_URL, "evidence": "1H 2024 revenue、net customer service revenue、total margin、EBITDA、CAPEX、经营表现和KPI。"},
    {"label": "HTHKH 2024 Interim Report - Financial Statements", "url": HTHKH_2024_INTERIM_REPORT_URL, "evidence": "1H 2024损益表、资产负债表、现金流量表及公司/子公司与合营公司调节表。"},
]

HTHKH_2024_H2_SOURCES = [
    {"label": "HTHKH 2024 Interim Report", "url": HTHKH_2024_INTERIM_REPORT_URL, "evidence": "1H累计值，用于从全年披露复算H2。"},
    {"label": "HTHKH 2024 Annual Report - Financial Highlights", "url": HTHKH_2024_AR_HIGHLIGHTS_URL, "evidence": "2024全年Total revenue、Total EBITDA、Total LBIT和股东应占利润。"},
    {"label": "HTHKH 2024 Annual Report - MD&A", "url": HTHKH_2024_AR_ANALYSIS_URL, "evidence": "2024全年Revenue、net customer service revenue、total margin、EBITDA、CAPEX和利润。"},
    {"label": "HTHKH 2024 Annual Report - Cash Flows", "url": HTHKH_2024_AR_CASHFLOW_URL, "evidence": "2024全年经营现金流和购置固定资产现金支出。"},
    {"label": "HTHKH 2024 Annual Report - Financial Position", "url": HTHKH_2024_AR_POSITION_URL, "evidence": "2024年底现金、总资产和租赁负债。"},
]

HTHKH_2025_H1_SOURCES = [
    {"label": "HTHKH 2025 Interim Report - Financial Highlights", "url": HTHKH_2025_H1_HIGHLIGHTS_URL, "evidence": "1H 2025 total revenue、EBITDA、EBIT和股东应占利润。"},
    {"label": "HTHKH 2025 Interim Report - MD&A", "url": HTHKH_2025_H1_ANALYSIS_URL, "evidence": "1H 2025 revenue、net customer service revenue、EBITDA、CAPEX和利润表口径。"},
    {"label": "HTHKH 2025 Interim Report - Financial Position", "url": HTHKH_2025_H1_POSITION_URL, "evidence": "2025年6月30日现金、总资产和租赁负债。"},
    {"label": "HTHKH 2025 Interim Report - Cash Flows", "url": HTHKH_2025_H1_CASHFLOW_URL, "evidence": "1H 2025经营现金流和购置固定资产现金支出。"},
]

HTHKH_2025_H2_SOURCES = [
    {"label": "HTHKH 2025 Interim Report - MD&A", "url": HTHKH_2025_H1_ANALYSIS_URL, "evidence": "上半年累计值，用于从全年披露复算H2。"},
    {"label": "HTHKH 2025 Annual Report - Financial Highlights", "url": HTHKH_2025_AR_HIGHLIGHTS_URL, "evidence": "2025全年香港业务收入、EBITDA、EBIT、香港业务利润和集团股东应占亏损。"},
    {"label": "HTHKH 2025 Annual Report - MD&A", "url": HTHKH_2025_AR_ANALYSIS_URL, "evidence": "2025全年香港业务收入、net customer service revenue、EBITDA、CAPEX和利润。"},
    {"label": "HTHKH 2025 Annual Report - Cash Flows", "url": HTHKH_2025_AR_CASHFLOW_URL, "evidence": "2025全年经营现金流和购置固定资产现金支出。"},
    {"label": "HTHKH 2025 Annual Report - Financial Position", "url": HTHKH_2025_AR_POSITION_URL, "evidence": "2025年底现金、总资产和租赁负债。"},
]

DEFAULT_VERIFICATION_SOURCES_BY_SUBJECT_PERIOD = {
    ("3HK / Hutchison", "H1 2021"): HTHKH_2021_H1_SOURCES,
    ("3HK / Hutchison", "H2 2021"): HTHKH_2021_H2_SOURCES,
    ("3HK / Hutchison", "H1 2022"): HTHKH_2022_H1_SOURCES,
    ("3HK / Hutchison", "H2 2022"): HTHKH_2022_H2_SOURCES,
    ("3HK / Hutchison", "H1 2023"): HTHKH_2023_H1_SOURCES,
    ("3HK / Hutchison", "H2 2023"): HTHKH_2023_H2_SOURCES,
    ("3HK / Hutchison", "H1 2024"): HTHKH_2024_H1_SOURCES,
    ("3HK / Hutchison", "H2 2024"): HTHKH_2024_H2_SOURCES,
    ("3HK / Hutchison", "H1 2025"): HTHKH_2025_H1_SOURCES,
    ("3HK / Hutchison", "H2 2025"): HTHKH_2025_H2_SOURCES,
    ("中国电信", "Q1 2025"): CT_2025_Q1_SOURCES,
    ("中国移动", "Q1 2026"): CM_2026_Q1_SOURCES,
    ("中国移动", "Q2 2025"): CM_2025_Q2_DETAIL_SOURCES,
    ("中国联通", "Q2 2025"): CU_2025_Q2_DETAIL_SOURCES,
    ("中国联通", "H1 2025"): CU_2025_Q2_DETAIL_SOURCES,
    ("中国联通", "Q1 2026"): CU_2026_Q1_SOURCES,
    ("中国铁塔", "Q1 2025"): TOWER_2025_Q1_SOURCES,
    ("中国铁塔", "Q1 2026"): TOWER_2026_Q1_SOURCES,
    ("中国铁塔", "Q2 2025"): TOWER_2025_Q2_SOURCES,
    ("中国铁塔", "Q3 2025"): TOWER_2025_Q3_SOURCES,
}


def _merge_source_lists(*source_lists: list[dict[str, str]]) -> list[dict[str, str]]:
    merged: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for sources in source_lists:
        for source in sources:
            key = (source.get("label", ""), source.get("url", ""))
            if key in seen:
                continue
            seen.add(key)
            merged.append(source)
    return merged


def _verification_sources_for_record(verification: dict[str, Any]) -> list[dict[str, str]]:
    explicit_sources = verification.get("verification_sources") or []
    if not explicit_sources:
        explicit_sources = [
            {
                "label": verification["source_label"],
                "url": verification["source_url"],
                "evidence": verification["evidence"],
            }
        ]
    defaults = DEFAULT_VERIFICATION_SOURCES_BY_SUBJECT_PERIOD.get(
        (verification["subject"], verification["period"]),
        [],
    )
    if len(explicit_sources) >= 2 or not defaults:
        return explicit_sources
    return _merge_source_lists(explicit_sources, defaults)

HKT_2025_ANNUAL_RESULTS_URL = "https://www.hkt.com/api-service/assets/e-2026.02.09_(2025_Annual_Results_Announcement).pdf"
HKT_2025_ANNUAL_RESULTS_HKEX_URL = "https://www1.hkexnews.hk/listedco/listconews/sehk/2026/0209/2026020900404.pdf"
HKT_2025_ANNUAL_REPORT_URL = "https://www1.hkexnews.hk/listedco/listconews/sehk/2026/0401/2026040101820.pdf"
HKT_2025_INTERIM_REPORT_URL = "https://www.hkexnews.hk/listedco/listconews/sehk/2025/0904/2025090400705.pdf"
HKT_2024_ANNUAL_RESULTS_URL = "https://www1.hkexnews.hk/listedco/listconews/sehk/2025/0220/2025022000325.pdf"
HKT_2024_ANNUAL_RESULTS_PCRD_URL = "https://www.pcrd.com/public/uploads/keys/20_2_2025_-_Announcement_relating_to_HKT_Limited_2024_Annual_Results.pdf"
HKT_2024_ANNUAL_REPORT_URL = "https://www.hkexnews.hk/listedco/listconews/sehk/2025/0402/2025040200953.pdf"
HKT_2024_ANNUAL_REPORT_HKT_URL = "https://www.hkt.com/api-service/assets/e01-2024%20Annual%20Report.pdf"
HKT_2024_INTERIM_REPORT_URL = "https://www1.hkexnews.hk/listedco/listconews/sehk/2024/0905/2024090500415.pdf"
HKT_2024_INTERIM_RESULTS_PCRD_URL = "https://www.pcrd.com/public/uploads/keys/25_7_2024_-_Announcement_relating_to_HKT_Limited_2024_Interim_Results.pdf"
HKT_2023_INTERIM_REPORT_URL = "https://www.hkexnews.hk/listedco/listconews/sehk/2023/0907/2023090700442.pdf"
HKT_2023_ANNUAL_REPORT_URL = "https://www.hkexnews.hk/listedco/listconews/sehk/2024/0402/2024040202244.pdf"
HKT_2022_INTERIM_REPORT_URL = "https://www.hkexnews.hk/listedco/listconews/sehk/2022/0908/2022090800325.pdf"
HKT_2022_ANNUAL_REPORT_URL = "https://www.hkexnews.hk/listedco/listconews/sehk/2023/0331/2023033101585.pdf"
HKT_2021_INTERIM_REPORT_URL = "https://www.hkexnews.hk/listedco/listconews/sehk/2021/0902/2021090200868.pdf"
HKT_2021_ANNUAL_REPORT_URL = "https://www1.hkexnews.hk/listedco/listconews/sehk/2022/0331/2022033101300.pdf"
HKT_2020_ANNUAL_REPORT_URL = "https://www1.hkexnews.hk/listedco/listconews/sehk/2021/0331/2021033101080.pdf"
HKT_2019_ANNUAL_REPORT_URL = "https://www.hkexnews.hk/listedco/listconews/sehk/2020/0401/2020040101873.pdf"
HKT_2019_ANNUAL_RESULTS_URL = "https://www1.hkexnews.hk/listedco/listconews/sehk/2020/0212/2020021200306.pdf"
HKT_2018_ANNUAL_REPORT_URL = "https://www.hkexnews.hk/listedco/listconews/sehk/2019/0401/ltn201904011788.pdf"
HKT_2018_ANNUAL_RESULTS_URL = "https://www.hkt.com/api-service/assets/hkt-2018-annual-res.pdf"
HKT_2017_ANNUAL_REPORT_URL = "https://www.hkexnews.hk/listedco/listconews/sehk/2018/0328/LTN20180328828.pdf"
HKT_2017_ANNUAL_RESULTS_URL = "https://www1.hkexnews.hk/listedco/listconews/sehk/2018/0206/ltn20180206887.pdf"
HKT_2016_ANNUAL_REPORT_URL = "https://www.hkexnews.hk/listedco/listconews/sehk/2017/0214/LTN20170214212.pdf"
HKT_2016_ANNUAL_RESULTS_URL = "https://www.hkexnews.hk/listedco/listconews/sehk/2017/0113/LTN20170113262.pdf"

HKT_2025_SEGMENT_SOURCES = [
    {"label": "HKT 2025 Annual Results Announcement - Financial Review by Segment", "url": HKT_2025_ANNUAL_RESULTS_URL, "evidence": "2025 H1/H2 总收入、成本、EBITDA、折旧摊销、融资成本和税前利润。"},
    {"label": "HKT 2025 Annual Results Announcement - Adjusted Funds Flow", "url": HKT_2025_ANNUAL_RESULTS_URL, "evidence": "2025 H1/H2 EBITDA、资本开支、AFF和分派。"},
    {"label": "HKT 2025 Annual Results Announcement - HKEX", "url": HKT_2025_ANNUAL_RESULTS_HKEX_URL, "evidence": "HKEX披露同一份2025年度业绩公告，用于交叉核验H1/H2分部表和AFF表。"},
]

HKT_2025_BALANCE_SOURCES = [
    {"label": "HKT 2025 Annual Results Announcement - Consolidated Statement of Financial Position", "url": HKT_2025_ANNUAL_RESULTS_URL, "evidence": "2025年底现金、总资产和借款。"},
    {"label": "HKT 2025 Annual Results Announcement - Financial Review", "url": HKT_2025_ANNUAL_RESULTS_URL, "evidence": "2025 H1/H2 分部表和附注定义总债务。"},
    {"label": "HKT 2025 Annual Report - HKEX", "url": HKT_2025_ANNUAL_REPORT_URL, "evidence": "2025年报资产负债表、现金流量表和现金等价物附注。"},
]

HKT_2025_INTERIM_SOURCES = [
    {"label": "HKT 2025 Interim Report - HKEX", "url": HKT_2025_INTERIM_REPORT_URL, "evidence": "2025 H1损益表、资产负债表和现金流量表。"},
    {"label": "HKT 2025 Annual Results Announcement - HKEX", "url": HKT_2025_ANNUAL_RESULTS_HKEX_URL, "evidence": "2025年度业绩公告同表披露2025 H1/H2分部结果和AFF。"},
]

HKT_2023_ANNUAL_REPORT_SOURCES = [
    {"label": "HKT 2023 Annual Report - HKEX Financial Review", "url": HKT_2023_ANNUAL_REPORT_URL, "evidence": "2022/2023 H1/H2 Total revenue和分部结果。"},
    {"label": "HKT 2024 Annual Results Announcement", "url": HKT_2024_ANNUAL_RESULTS_URL, "evidence": "2023/2024 H1/H2 Total revenue，用于与2023年报基数交叉核验。"},
]

HKT_2024_SEGMENT_SOURCES = [
    {"label": "HKT 2024 Annual Results Announcement - Financial Review by Segment", "url": HKT_2024_ANNUAL_RESULTS_URL, "evidence": "2023/2024 H1/H2 总收入、成本、EBITDA、折旧摊销、融资成本和税前利润。"},
    {"label": "HKT 2024 Annual Results Announcement - Adjusted Funds Flow", "url": HKT_2024_ANNUAL_RESULTS_URL, "evidence": "2023/2024 H1/H2 EBITDA、资本开支、AFF和分派。"},
    {"label": "PCRD Announcement relating to HKT Limited 2024 Annual Results", "url": HKT_2024_ANNUAL_RESULTS_PCRD_URL, "evidence": "PCRD同步披露同一份HKT 2024年度业绩公告，用于交叉核验H1/H2分部表和AFF表。"},
]

HKT_2024_BALANCE_SOURCES = [
    {"label": "HKT 2024 Annual Results Announcement - Consolidated Statement of Financial Position", "url": HKT_2024_ANNUAL_RESULTS_URL, "evidence": "2023/2024 年末现金、总资产和借款。"},
    {"label": "HKT 2024 Annual Results Announcement - Financial Review", "url": HKT_2024_ANNUAL_RESULTS_URL, "evidence": "2023/2024 H1/H2 分部表和附注定义总债务。"},
]

HKT_2024_ANNUAL_REPORT_SOURCES = [
    {"label": "HKT 2024 Annual Report - HKEX", "url": HKT_2024_ANNUAL_REPORT_URL, "evidence": "2023/2024全年损益表、现金流量表、资产负债表和现金等价物附注。"},
    {"label": "HKT 2024 Annual Report - HKT official site", "url": HKT_2024_ANNUAL_REPORT_HKT_URL, "evidence": "HKT官网同版2024年报，用于与HKEX年报交叉核验全年值。"},
]

HKT_2024_INTERIM_SOURCES = [
    {"label": "HKT 2024 Interim Report - HKEX", "url": HKT_2024_INTERIM_REPORT_URL, "evidence": "2024 H1及2023 H1比较栏损益表、资产负债表和现金流量表。"},
    {"label": "PCRD Announcement relating to HKT Limited 2024 Interim Results", "url": HKT_2024_INTERIM_RESULTS_PCRD_URL, "evidence": "PCRD同步披露HKT 2024中期业绩公告，用于交叉核验H1分部及财务信息。"},
    {"label": "HKT 2024 Annual Results Announcement", "url": HKT_2024_ANNUAL_RESULTS_URL, "evidence": "2024年度业绩公告同表披露2024 H1/H2和2023 H1/H2分部结果。"},
]

HKT_2023_INTERIM_SOURCES = [
    {"label": "HKT 2023 Interim Report - HKEX", "url": HKT_2023_INTERIM_REPORT_URL, "evidence": "2023 H1损益表、资产负债表和现金流量表。"},
    {"label": "HKT 2024 Interim Report - HKEX comparative column", "url": HKT_2024_INTERIM_REPORT_URL, "evidence": "2024中报比较栏重列2023 H1归母利润、经营现金流和期末现金。"},
    {"label": "HKT 2024 Annual Results Announcement", "url": HKT_2024_ANNUAL_RESULTS_URL, "evidence": "2024年度业绩公告同表披露2023 H1/H2分部结果。"},
]

HKT_2022_ANNUAL_REPORT_SOURCES = [
    {"label": "HKT 2022 Annual Report - HKEX Financial Review", "url": HKT_2022_ANNUAL_REPORT_URL, "evidence": "2021/2022 H1/H2 Total revenue、cost of sales、EBITDA、折旧摊销、PBT、capex和AFF。"},
    {"label": "HKT 2023 Annual Report - HKEX comparative base", "url": HKT_2023_ANNUAL_REPORT_URL, "evidence": "2023年报重列2022 H1/H2 Total revenue，用于交叉核验2022基数。"},
]

HKT_2022_INTERIM_SOURCES = [
    {"label": "HKT 2022 Interim Report - HKEX", "url": HKT_2022_INTERIM_REPORT_URL, "evidence": "2022 H1损益表、资产负债表、现金流量表和gross debt。"},
    {"label": "HKT 2022 Annual Report - HKEX", "url": HKT_2022_ANNUAL_REPORT_URL, "evidence": "2022年报重列H1/H2分部结果和全年现金流，用于交叉核验H1与复算H2。"},
]

HKT_2021_ANNUAL_REPORT_SOURCES = [
    {"label": "HKT 2021 Annual Report - HKEX Financial Review", "url": HKT_2021_ANNUAL_REPORT_URL, "evidence": "2020/2021 H1/H2 Total revenue、cost of sales、EBITDA、折旧摊销、PBT、capex和AFF。"},
    {"label": "HKT 2022 Annual Report - HKEX comparative base", "url": HKT_2022_ANNUAL_REPORT_URL, "evidence": "2022年报重列2021 H1/H2 Total revenue和分部表，用于交叉核验2021基数。"},
]

HKT_2021_INTERIM_SOURCES = [
    {"label": "HKT 2021 Interim Report - HKEX", "url": HKT_2021_INTERIM_REPORT_URL, "evidence": "2021 H1损益表、资产负债表、现金流量表和gross debt。"},
    {"label": "HKT 2021 Annual Report - HKEX", "url": HKT_2021_ANNUAL_REPORT_URL, "evidence": "2021年报重列H1/H2分部结果和全年现金流，用于交叉核验H1与复算H2。"},
]

SMARTONE_REPORTS_INDEX_URL = "https://www.smartoneholdings.com/jsp/site/investor_relations/financial_reports/english/index.jsp"
SMARTONE_2016_H1_REPORT_URL = "https://www.smartoneholdings.com/about/investor/financial_reports/english/2015_2016_interim.pdf"
SMARTONE_2016_H2_REPORT_URL = "https://www.smartoneholdings.com/about/investor/financial_reports/english/2015_2016_annual.pdf"
SMARTONE_2017_H1_REPORT_URL = "https://www.smartoneholdings.com/about/investor/financial_reports/english/2016_2017_interim.pdf"
SMARTONE_2017_H2_REPORT_URL = "https://www.smartoneholdings.com/about/investor/financial_reports/english/2016_2017_annual.pdf"
SMARTONE_2018_H1_REPORT_URL = "https://www.smartoneholdings.com/about/investor/financial_reports/english/2017_2018_interim.pdf"
SMARTONE_2018_H2_REPORT_URL = "https://www.smartoneholdings.com/about/investor/financial_reports/english/2017_2018_annual.pdf"
SMARTONE_2019_H1_REPORT_URL = "https://www.smartoneholdings.com/about/investor/financial_reports/english/2018_2019_interim.pdf"
SMARTONE_2019_H2_REPORT_URL = "https://www.smartoneholdings.com/about/investor/financial_reports/english/2018_2019_annual.pdf"
SMARTONE_2020_H1_REPORT_URL = "https://www.smartoneholdings.com/about/investor/financial_reports/english/2019_2020_interim.pdf"
SMARTONE_2020_H2_REPORT_URL = "https://www.smartoneholdings.com/about/investor/financial_reports/english/2019_2020_annual.pdf"
SMARTONE_2021_H1_REPORT_URL = "https://www.smartoneholdings.com/about/investor/financial_reports/english/2020_2021_interim.pdf"
SMARTONE_2021_H2_REPORT_URL = "https://www.smartoneholdings.com/about/investor/financial_reports/english/2020_2021_annual.pdf"
SMARTONE_2021_H2_HKEX_URL = "https://www1.hkexnews.hk/listedco/listconews/sehk/2021/0929/2021092900644.pdf"
SMARTONE_2022_H1_REPORT_URL = "https://www.smartoneholdings.com/about/investor/financial_reports/english/2021_2022_interim.pdf"
SMARTONE_2022_H1_HKEX_URL = "https://www1.hkexnews.hk/listedco/listconews/sehk/2022/0330/2022033000513.pdf"
SMARTONE_2022_H2_REPORT_URL = "https://www.smartoneholdings.com/about/investor/financial_reports/english/2021_2022_annual.pdf"
SMARTONE_2022_H2_HKEX_URL = "https://www1.hkexnews.hk/listedco/listconews/sehk/2022/0929/2022092900733.pdf"
SMARTONE_2023_H1_REPORT_URL = "https://www.smartoneholdings.com/about/investor/financial_reports/english/2022_2023_interim.pdf"
SMARTONE_2023_H1_HKEX_URL = "https://www.hkexnews.hk/listedco/listconews/sehk/2023/0330/2023033000990.pdf"
SMARTONE_2023_H2_REPORT_URL = "https://www.smartoneholdings.com/about/investor/financial_reports/english/2022_2023_annual.pdf"
SMARTONE_2023_H2_HKEX_URL = "https://www1.hkexnews.hk/listedco/listconews/sehk/2023/0926/2023092600701.pdf"
SMARTONE_2024_H1_REPORT_URL = "https://www.smartoneholdings.com/about/investor/financial_reports/english/2023_2024_interim.pdf"
SMARTONE_2024_H1_HKEX_URL = "https://www1.hkexnews.hk/listedco/listconews/sehk/2024/0327/2024032701074.pdf"
SMARTONE_2024_H2_REPORT_URL = "https://www.smartoneholdings.com/about/investor/financial_reports/english/2023_2024_annual.pdf"
SMARTONE_2024_H2_HKEX_URL = "https://www1.hkexnews.hk/listedco/listconews/sehk/2024/1007/2024100701016.pdf"
SMARTONE_2025_H1_REPORT_URL = "https://www.smartoneholdings.com/about/investor/financial_reports/english/2024_2025_interim.pdf"
SMARTONE_2025_H1_HKEX_REPORT_URL = "https://www1.hkexnews.hk/listedco/listconews/sehk/2025/0328/2025032800920.pdf"
SMARTONE_2025_H1_RESULTS_URL = "https://www.smartoneholdings.com/about/investor/results/english/2025_interim_results.pdf"
SMARTONE_2025_H1_HKEX_RESULTS_URL = "https://www1.hkexnews.hk/listedco/listconews/sehk/2025/0226/2025022600430.pdf"
SMARTONE_2025_H2_REPORT_URL = "https://www.smartoneholdings.com/about/investor/financial_reports/english/2024_2025_annual.pdf"
SMARTONE_2025_H2_HKEX_REPORT_URL = "https://www1.hkexnews.hk/listedco/listconews/sehk/2025/1009/2025100900497.pdf"
SMARTONE_2025_H2_RESULTS_URL = "https://www.smartoneholdings.com/about/investor/results/english/2025_annual_results.pdf"
SMARTONE_2025_H2_HKEX_RESULTS_URL = "https://www1.hkexnews.hk/listedco/listconews/sehk/2025/0903/2025090301160.pdf"
SMARTONE_2025_ANNUAL_PRESENTATION_URL = "https://www.smartoneholdings.com/about/investor/results/english/2025_annual_present.pdf"
SMARTONE_2026_H1_REPORT_URL = "https://www.smartoneholdings.com/about/investor/financial_reports/english/2025_2026_interim.pdf"
SMARTONE_2026_H1_HKEX_REPORT_URL = "https://www1.hkexnews.hk/listedco/listconews/sehk/2026/0330/2026033000664.pdf"
SMARTONE_2026_H1_RESULTS_URL = "https://www.smartoneholdings.com/about/investor/major_announcements/2026/02/2026_02_24_1029.pdf"
SMARTONE_2026_H1_HKEX_RESULTS_URL = "https://www1.hkexnews.hk/listedco/listconews/sehk/2026/0224/2026022400395.pdf"
SMARTONE_2026_H1_PRESENTATION_URL = "https://www.smartoneholdings.com/about/investor/results/english/2026_interim_present.pdf"

SMARTONE_2021_H2_SOURCES = [
    {"label": "SmarTone 2020/21 Interim Report - company site", "url": SMARTONE_2021_H1_REPORT_URL, "evidence": "2020/21中期报告H1累计值，用于从2020/21全年披露复算H2 2021。"},
    {"label": "SmarTone 2020/21 Annual Report - company site", "url": SMARTONE_2021_H2_REPORT_URL, "evidence": "2020/21全年损益表、资产负债表、现金流量表和EBITDA分部附注。"},
    {"label": "SmarTone 2020/21 Annual Report - HKEX", "url": SMARTONE_2021_H2_HKEX_URL, "evidence": "HKEX披露同一份2020/21年报，用于交叉核验。"},
    {"label": "SmarTone Financial Reports index", "url": SMARTONE_REPORTS_INDEX_URL, "evidence": "公司投资者关系财务报告入口，用于定位官方年报和中报。"},
]

SMARTONE_2022_H1_SOURCES = [
    {"label": "SmarTone 2021/22 Interim Report - company site", "url": SMARTONE_2022_H1_REPORT_URL, "evidence": "2021/22中期损益表、资产负债表、现金流量表和EBITDA分部附注。"},
    {"label": "SmarTone 2021/22 Interim Report - HKEX", "url": SMARTONE_2022_H1_HKEX_URL, "evidence": "HKEX披露同一份2021/22中期报告，用于交叉核验。"},
    {"label": "SmarTone Financial Reports index", "url": SMARTONE_REPORTS_INDEX_URL, "evidence": "公司投资者关系财务报告入口，用于定位官方中报。"},
]

SMARTONE_2022_H2_SOURCES = [
    {"label": "SmarTone 2021/22 Interim Report - company site", "url": SMARTONE_2022_H1_REPORT_URL, "evidence": "2022 H1累计值，用于从全年披露复算H2。"},
    {"label": "SmarTone 2021/22 Annual Report - company site", "url": SMARTONE_2022_H2_REPORT_URL, "evidence": "2021/22全年损益表、资产负债表、现金流量表和EBITDA分部附注。"},
    {"label": "SmarTone 2021/22 Annual Report - HKEX", "url": SMARTONE_2022_H2_HKEX_URL, "evidence": "HKEX披露同一份2021/22年报，用于交叉核验。"},
    {"label": "SmarTone Financial Reports index", "url": SMARTONE_REPORTS_INDEX_URL, "evidence": "公司投资者关系财务报告入口，用于定位官方年报和中报。"},
]

SMARTONE_2023_H1_SOURCES = [
    {"label": "SmarTone 2022/23 Interim Report - company site", "url": SMARTONE_2023_H1_REPORT_URL, "evidence": "2022/23中期损益表、资产负债表、现金流量表和EBITDA分部附注。"},
    {"label": "SmarTone 2022/23 Interim Report - HKEX", "url": SMARTONE_2023_H1_HKEX_URL, "evidence": "HKEX披露同一份2022/23中期报告，用于交叉核验。"},
    {"label": "SmarTone Financial Reports index", "url": SMARTONE_REPORTS_INDEX_URL, "evidence": "公司投资者关系财务报告入口，用于定位官方中报。"},
]

SMARTONE_2023_H2_SOURCES = [
    {"label": "SmarTone 2022/23 Interim Report - company site", "url": SMARTONE_2023_H1_REPORT_URL, "evidence": "2023 H1累计值，用于从全年披露复算H2。"},
    {"label": "SmarTone 2022/23 Annual Report - company site", "url": SMARTONE_2023_H2_REPORT_URL, "evidence": "2022/23全年损益表、资产负债表、现金流量表和EBITDA分部附注。"},
    {"label": "SmarTone 2022/23 Annual Report - HKEX", "url": SMARTONE_2023_H2_HKEX_URL, "evidence": "HKEX披露同一份2022/23年报，用于交叉核验。"},
    {"label": "SmarTone Financial Reports index", "url": SMARTONE_REPORTS_INDEX_URL, "evidence": "公司投资者关系财务报告入口，用于定位官方年报。"},
]

SMARTONE_2024_H1_SOURCES = [
    {"label": "SmarTone 2023/24 Interim Report - company site", "url": SMARTONE_2024_H1_REPORT_URL, "evidence": "2023/24中期损益表、资产负债表、现金流量表和EBITDA分部附注。"},
    {"label": "SmarTone 2023/24 Interim Report - HKEX", "url": SMARTONE_2024_H1_HKEX_URL, "evidence": "HKEX披露同一份2023/24中期报告，用于交叉核验。"},
    {"label": "SmarTone Financial Reports index", "url": SMARTONE_REPORTS_INDEX_URL, "evidence": "公司投资者关系财务报告入口，用于定位官方中报。"},
]

SMARTONE_2024_H2_SOURCES = [
    {"label": "SmarTone 2023/24 Interim Report - company site", "url": SMARTONE_2024_H1_REPORT_URL, "evidence": "2024 H1累计值，用于从全年披露复算H2。"},
    {"label": "SmarTone 2023/24 Annual Report - company site", "url": SMARTONE_2024_H2_REPORT_URL, "evidence": "2023/24全年损益表、资产负债表、现金流量表和资产负债表。"},
    {"label": "SmarTone 2023/24 Annual Report - HKEX", "url": SMARTONE_2024_H2_HKEX_URL, "evidence": "HKEX披露同一份2023/24年报，用于交叉核验。"},
    {"label": "SmarTone Financial Reports index", "url": SMARTONE_REPORTS_INDEX_URL, "evidence": "公司投资者关系财务报告入口，用于定位官方年报。"},
]

SMARTONE_2025_H1_SOURCES = [
    {"label": "SmarTone 2024/25 Interim Report - company site", "url": SMARTONE_2025_H1_REPORT_URL, "evidence": "2024/25中期报告披露损益表、资产负债表和现金流量表。"},
    {"label": "SmarTone 2024/25 Interim Report - HKEX", "url": SMARTONE_2025_H1_HKEX_REPORT_URL, "evidence": "HKEX披露同一份2024/25中期报告，用于交叉核验。"},
    {"label": "SmarTone 2024/25 Interim Results Announcement", "url": SMARTONE_2025_H1_RESULTS_URL, "evidence": "公司官网业绩公告披露2024/25 H1 revenue、profit、现金和借款摘要。"},
    {"label": "SmarTone 2024/25 Interim Results Announcement - HKEX", "url": SMARTONE_2025_H1_HKEX_RESULTS_URL, "evidence": "HKEX披露同一份2024/25中期业绩公告，用于交叉核验。"},
    {"label": "SmarTone Financial Reports index", "url": SMARTONE_REPORTS_INDEX_URL, "evidence": "公司投资者关系财务报告入口，用于定位官方中报。"},
]

SMARTONE_2025_H2_SOURCES = [
    {"label": "SmarTone 2024/25 Interim Report - company site", "url": SMARTONE_2025_H1_REPORT_URL, "evidence": "2025 H1累计值，用于从全年披露复算H2。"},
    {"label": "SmarTone 2024/25 Annual Report - company site", "url": SMARTONE_2025_H2_REPORT_URL, "evidence": "2024/25全年损益表、资产负债表和现金流量表。"},
    {"label": "SmarTone 2024/25 Annual Report - HKEX", "url": SMARTONE_2025_H2_HKEX_REPORT_URL, "evidence": "HKEX披露同一份2024/25年报，用于交叉核验。"},
    {"label": "SmarTone 2024/25 Annual Results Announcement", "url": SMARTONE_2025_H2_RESULTS_URL, "evidence": "公司官网业绩公告披露2024/25全年 revenue、profit、现金和借款摘要。"},
    {"label": "SmarTone 2024/25 Annual Results Announcement - HKEX", "url": SMARTONE_2025_H2_HKEX_RESULTS_URL, "evidence": "HKEX披露同一份2024/25全年业绩公告，用于交叉核验。"},
    {"label": "SmarTone FY25 Annual Results Presentation", "url": SMARTONE_2025_ANNUAL_PRESENTATION_URL, "evidence": "FY25 revenue、profit after tax、net cash等摘要指标交叉验证。"},
]

SMARTONE_2026_H1_SOURCES = [
    {"label": "SmarTone 2025/26 Interim Report - company site", "url": SMARTONE_2026_H1_REPORT_URL, "evidence": "2025/26中期报告披露损益表、资产负债表和现金流量表。"},
    {"label": "SmarTone 2025/26 Interim Report - HKEX", "url": SMARTONE_2026_H1_HKEX_REPORT_URL, "evidence": "HKEX披露同一份2025/26中期报告，用于交叉核验。"},
    {"label": "SmarTone 2025/26 Interim Results Announcement", "url": SMARTONE_2026_H1_RESULTS_URL, "evidence": "公司官网中期业绩公告披露2025/26 H1 revenue、profit、现金和借款摘要。"},
    {"label": "SmarTone 2025/26 Interim Results Announcement - HKEX", "url": SMARTONE_2026_H1_HKEX_RESULTS_URL, "evidence": "HKEX披露同一份2025/26中期业绩公告，用于交叉核验。"},
    {"label": "SmarTone FY26 Interim Results Presentation", "url": SMARTONE_2026_H1_PRESENTATION_URL, "evidence": "H1 2026 revenue、profit after tax、net cash等摘要指标交叉验证。"},
]

SMARTONE_2016_2021_SOURCES_BY_PERIOD = {
    "H2 2016": [
        {"label": "SmarTone 2015/16 Interim Report - company site", "url": SMARTONE_2016_H1_REPORT_URL, "evidence": "2015/16中期报告披露H1 2016 Revenues与EBITDA，用于从全年披露复算H2 2016。"},
        {"label": "SmarTone 2015/16 Annual Report - company site", "url": SMARTONE_2016_H2_REPORT_URL, "evidence": "2015/16年报披露FY2016 Revenues与EBITDA。"},
        {"label": "SmarTone Financial Reports index", "url": SMARTONE_REPORTS_INDEX_URL, "evidence": "公司投资者关系财务报告入口，用于定位官方年报和中报。"},
    ],
    "H1 2017": [
        {"label": "SmarTone 2016/17 Interim Report - company site", "url": SMARTONE_2017_H1_REPORT_URL, "evidence": "2016/17中期报告披露H1 2017 Revenues与EBITDA。"},
        {"label": "SmarTone 2017/18 Interim Report comparative column", "url": SMARTONE_2018_H1_REPORT_URL, "evidence": "2017/18中期报告比较栏重列H1 2017 Revenues与EBITDA。"},
        {"label": "SmarTone Financial Reports index", "url": SMARTONE_REPORTS_INDEX_URL, "evidence": "公司投资者关系财务报告入口，用于定位官方中报。"},
    ],
    "H2 2017": [
        {"label": "SmarTone 2016/17 Interim Report - company site", "url": SMARTONE_2017_H1_REPORT_URL, "evidence": "2016/17中期报告披露H1 2017累计值，用于从全年披露复算H2。"},
        {"label": "SmarTone 2016/17 Annual Report - company site", "url": SMARTONE_2017_H2_REPORT_URL, "evidence": "2016/17年报披露FY2017 Revenues与EBITDA。"},
        {"label": "SmarTone 2017/18 Annual Report comparative column", "url": SMARTONE_2018_H2_REPORT_URL, "evidence": "2017/18年报比较栏重列FY2017 Revenues与EBITDA。"},
    ],
    "H1 2018": [
        {"label": "SmarTone 2017/18 Interim Report - company site", "url": SMARTONE_2018_H1_REPORT_URL, "evidence": "2017/18中期报告披露H1 2018 Revenues与EBITDA。"},
        {"label": "SmarTone 2018/19 Interim Report comparative column", "url": SMARTONE_2019_H1_REPORT_URL, "evidence": "2018/19中期报告比较栏重列H1 2018 Revenues与EBITDA。"},
        {"label": "SmarTone Financial Reports index", "url": SMARTONE_REPORTS_INDEX_URL, "evidence": "公司投资者关系财务报告入口，用于定位官方中报。"},
    ],
    "H2 2018": [
        {"label": "SmarTone 2017/18 Interim Report - company site", "url": SMARTONE_2018_H1_REPORT_URL, "evidence": "2017/18中期报告披露H1 2018累计值，用于从全年披露复算H2。"},
        {"label": "SmarTone 2017/18 Annual Report - company site", "url": SMARTONE_2018_H2_REPORT_URL, "evidence": "2017/18年报披露FY2018 Revenues与EBITDA。"},
        {"label": "SmarTone 2018/19 Annual Report comparative column", "url": SMARTONE_2019_H2_REPORT_URL, "evidence": "2018/19年报比较栏重列FY2018 Revenues与EBITDA。"},
    ],
    "H1 2019": [
        {"label": "SmarTone 2018/19 Interim Report - company site", "url": SMARTONE_2019_H1_REPORT_URL, "evidence": "2018/19中期报告披露H1 2019 Revenues与EBITDA。"},
        {"label": "SmarTone 2019/20 Interim Report comparative column", "url": SMARTONE_2020_H1_REPORT_URL, "evidence": "2019/20中期报告比较栏重列H1 2019 Revenues与EBITDA。"},
        {"label": "SmarTone Financial Reports index", "url": SMARTONE_REPORTS_INDEX_URL, "evidence": "公司投资者关系财务报告入口，用于定位官方中报。"},
    ],
    "H2 2019": [
        {"label": "SmarTone 2018/19 Interim Report - company site", "url": SMARTONE_2019_H1_REPORT_URL, "evidence": "2018/19中期报告披露H1 2019累计值，用于从全年披露复算H2。"},
        {"label": "SmarTone 2018/19 Annual Report - company site", "url": SMARTONE_2019_H2_REPORT_URL, "evidence": "2018/19年报披露FY2019 Revenues与EBITDA。"},
        {"label": "SmarTone 2019/20 Annual Report comparative column", "url": SMARTONE_2020_H2_REPORT_URL, "evidence": "2019/20年报比较栏重列FY2019 Revenues与EBITDA。"},
    ],
    "H1 2020": [
        {"label": "SmarTone 2019/20 Interim Report - company site", "url": SMARTONE_2020_H1_REPORT_URL, "evidence": "2019/20中期报告披露H1 2020 Revenues与EBITDA。"},
        {"label": "SmarTone 2020/21 Interim Report comparative column", "url": SMARTONE_2021_H1_REPORT_URL, "evidence": "2020/21中期报告比较栏重列H1 2020 Revenues与EBITDA。"},
        {"label": "SmarTone Financial Reports index", "url": SMARTONE_REPORTS_INDEX_URL, "evidence": "公司投资者关系财务报告入口，用于定位官方中报。"},
    ],
    "H2 2020": [
        {"label": "SmarTone 2019/20 Interim Report - company site", "url": SMARTONE_2020_H1_REPORT_URL, "evidence": "2019/20中期报告披露H1 2020累计值，用于从全年披露复算H2。"},
        {"label": "SmarTone 2019/20 Annual Report - company site", "url": SMARTONE_2020_H2_REPORT_URL, "evidence": "2019/20年报披露FY2020 Revenues与EBITDA。"},
        {"label": "SmarTone 2020/21 Annual Report comparative column", "url": SMARTONE_2021_H2_REPORT_URL, "evidence": "2020/21年报比较栏重列FY2020 Revenues与EBITDA。"},
    ],
    "H1 2021": [
        {"label": "SmarTone 2020/21 Interim Report - company site", "url": SMARTONE_2021_H1_REPORT_URL, "evidence": "2020/21中期报告披露H1 2021 Revenues与EBITDA。"},
        {"label": "SmarTone 2020/21 Annual Report - company site", "url": SMARTONE_2021_H2_REPORT_URL, "evidence": "2020/21年报全年值与H1值可交叉复核。"},
        {"label": "SmarTone Financial Reports index", "url": SMARTONE_REPORTS_INDEX_URL, "evidence": "公司投资者关系财务报告入口，用于定位官方中报。"},
    ],
}

SMARTONE_2016_2021_METRICS = {
    "H2 2016": {
        "revenue": (8127.321, "2015/16年报披露FY2016 Revenues 18,355.611百万港元，减2015/16中期H1 Revenues 10,228.290百万港元，复算H2 2016为8,127.321百万港元。"),
        "ebitda": (1283.048, "2015/16年报分部附注披露FY2016 EBITDA 2,660.528百万港元，减2015/16中期H1 EBITDA 1,377.480百万港元，复算H2 2016为1,283.048百万港元。"),
    },
    "H1 2017": {
        "revenue": (5372.304, "2016/17中期报告损益表披露H1 2017 Revenues 5,372.304百万港元。"),
        "ebitda": (1248.571, "2016/17中期报告分部附注披露H1 2017 EBITDA 1,248.571百万港元。"),
    },
    "H2 2017": {
        "revenue": (3343.108, "2016/17年报披露FY2017 Revenues 8,715.412百万港元，减H1 2017 Revenues 5,372.304百万港元，复算H2 2017为3,343.108百万港元。"),
        "ebitda": (1047.691, "2016/17年报分部附注披露FY2017 EBITDA 2,296.262百万港元，减H1 2017 EBITDA 1,248.571百万港元，复算H2 2017为1,047.691百万港元。"),
    },
    "H1 2018": {
        "revenue": (4107.577, "2017/18中期报告损益表披露H1 2018 Revenues 4,107.577百万港元。"),
        "ebitda": (1080.027, "2017/18中期报告分部附注披露H1 2018 EBITDA 1,080.027百万港元。"),
    },
    "H2 2018": {
        "revenue": (5880.915, "2017/18年报披露FY2018 Revenues 9,988.492百万港元，减H1 2018 Revenues 4,107.577百万港元，复算H2 2018为5,880.915百万港元。"),
        "ebitda": (1056.187, "2017/18年报分部附注披露FY2018 EBITDA 2,136.214百万港元，减H1 2018 EBITDA 1,080.027百万港元，复算H2 2018为1,056.187百万港元。"),
    },
    "H1 2019": {
        "revenue": (5186.561, "2018/19中期报告损益表披露H1 2019 Revenues 5,186.561百万港元。"),
        "ebitda": (939.306, "2018/19中期报告分部附注披露H1 2019 EBITDA 939.306百万港元。"),
    },
    "H2 2019": {
        "revenue": (3228.476, "2018/19年报披露FY2019 Revenues 8,415.037百万港元，减H1 2019 Revenues 5,186.561百万港元，复算H2 2019为3,228.476百万港元。"),
        "ebitda": (902.483, "2018/19年报分部附注披露FY2019 EBITDA 1,841.789百万港元，减H1 2019 EBITDA 939.306百万港元，复算H2 2019为902.483百万港元。"),
    },
    "H1 2020": {
        "revenue": (4256.606, "2019/20中期报告损益表披露H1 2020 Revenues 4,256.606百万港元。"),
        "ebitda": (1273.853, "2019/20中期报告分部附注披露H1 2020 EBITDA 1,273.853百万港元。"),
    },
    "H2 2020": {
        "revenue": (2729.845, "2019/20年报披露FY2020 Revenues 6,986.451百万港元，减H1 2020 Revenues 4,256.606百万港元，复算H2 2020为2,729.845百万港元。"),
        "ebitda": (1155.374, "2019/20年报分部附注披露FY2020 EBITDA 2,429.227百万港元，减H1 2020 EBITDA 1,273.853百万港元，复算H2 2020为1,155.374百万港元。"),
    },
    "H1 2021": {
        "revenue": (3244.313, "2020/21中期报告损益表披露H1 2021 Revenues 3,244.313百万港元。"),
        "ebitda": (1272.651, "2020/21中期报告分部附注披露H1 2021 EBITDA 1,272.651百万港元。"),
    },
}

HKBN_FY23_INTERIM_URL = "https://reg.hkbn.net/WwwCMS/upload/pdf/en/e_FY23_InterimResultsAnnouncement.pdf"
HKBN_FY23_ANNUAL_RESULTS_URL = "https://reg.hkbn.net/WwwCMS/upload/pdf/en/e_FY23_AnnualResultsAnnouncement.pdf"
HKBN_FY23_PRESS_RELEASE_URL = "https://www.hkbn.net/group/en/newsroom/press-releases/20231102_FY23_AnnualResults"
HKBN_FY23_INTERIM_REPORT_URL = "https://reg.hkbn.net/WwwCMS/upload/pdf/en/e_InterimReport_2023.pdf"
HKBN_FY23_ANNUAL_REPORT_URL = "https://reg.hkbn.net/WwwCMS/upload/pdf/en/e_AnnualReport_2023.pdf"
HKBN_FY22_INTERIM_URL = "https://reg.hkbn.net/WwwCMS/upload/pdf/en/e_FY22_InterimResultsAnnouncement.pdf"
HKBN_FY22_ANNUAL_RESULTS_URL = "https://reg.hkbn.net/WwwCMS/upload/pdf/en/e_FY22_AnnualResultsAnnouncement.pdf"
HKBN_FY22_INTERIM_REPORT_URL = "https://reg.hkbn.net/WwwCMS/upload/pdf/en/e_InterimReport_2022.pdf"
HKBN_FY22_ANNUAL_REPORT_URL = "https://reg.hkbn.net/WwwCMS/upload/pdf/en/e_AnnualReport_2022.pdf"
HKBN_FY21_INTERIM_URL = "https://www1.hkexnews.hk/listedco/listconews/sehk/2021/0421/2021042100402.pdf"
HKBN_FY21_ANNUAL_RESULTS_URL = "https://reg.hkbn.net/WwwCMS/upload/pdf/en/e_FY21_AnnualResultsAnnouncement.pdf"
HKBN_FY21_ANNUAL_REPORT_URL = "https://reg.hkbn.net/WwwCMS/upload/pdf/en/e_AnnualReport_2021.pdf"
HKBN_FY24_INTERIM_URL = "https://reg.hkbn.net/WwwCMS/upload/pdf/en/e_FY24_InterimResultsAnnouncement.pdf"
HKBN_FY24_ANNUAL_RESULTS_URL = "https://reg.hkbn.net/WwwCMS/upload/pdf/en/e_FY24_AnnualResultsAnnouncement.pdf"
HKBN_FY24_PRESS_RELEASE_URL = "https://www.hkbn.net/group/en/newsroom/press-releases/20241031_FY24_Annual_Results"
HKBN_FY24_INTERIM_REPORT_URL = "https://reg.hkbn.net/WwwCMS/upload/pdf/en/e_InterimReport_2024.pdf"
HKBN_FY24_ANNUAL_REPORT_URL = "https://reg.hkbn.net/WwwCMS/upload/pdf/en/e_AnnualReport_2024.pdf"
HKBN_FINANCIAL_RESULTS_URL = "https://www.hkbn.net/group/en/investor-engagement/financial-results"
HKBN_FY25_INTERIM_URL = "https://reg.hkbn.net/WwwCMS/upload/pdf/en/e_FY25_InterimResultsAnnouncement.pdf"
HKBN_FY25_ANNUAL_RESULTS_URL = "https://reg.hkbn.net/WwwCMS/upload/pdf/en/e_FY25_AnnualResultsAnnouncement.pdf"
HKBN_FY25_PRESS_RELEASE_URL = "https://www.hkbn.net/group/en/newsroom/press-releases/20251031_FY25_Annual_Results"
HKBN_FY25_INTERIM_REPORT_URL = "https://reg.hkbn.net/WwwCMS/upload/pdf/en/e_InterimReport_2025.pdf"
HKBN_FY25_ANNUAL_REPORT_URL = "https://reg.hkbn.net/WwwCMS/upload/pdf/en/e_AnnualReport_2025.pdf"
HKBN_FY26_INTERIM_URL = "https://reg.hkbn.net/WwwCMS/upload/pdf/en/e_FY26_InterimResultsAnnouncement.pdf"
HKBN_FY26_INTERIM_REPORT_URL = "https://reg.hkbn.net/WwwCMS/upload/pdf/en/e_InterimReport_2026.pdf"
HKBN_FY16_INTERIM_URL = "https://reg.hkbn.net/WwwCMS/upload/pdf/en/e_2016InterimResultsAnnouncment(upload).pdf"
HKBN_FY16_INTERIM_REPORT_URL = "https://reg.hkbn.net/WwwCMS/upload/pdf/en/e_InterimReport2016_HKEX.pdf"
HKBN_FY16_ANNUAL_RESULTS_URL = "https://reg.hkbn.net/WwwCMS/upload/pdf/en/e_01310ann-20161109.pdf"
HKBN_FY16_ANNUAL_REPORT_URL = "https://reg.hkbn.net/WwwCMS/upload/pdf/en/e_AnnualReport2016_HKEX.pdf"
HKBN_FY17_INTERIM_URL = "https://reg.hkbn.net/WwwCMS/upload/pdf/en/e_01310ann-20170420.pdf"
HKBN_FY17_INTERIM_REPORT_URL = "https://reg.hkbn.net/WwwCMS/upload/pdf/en/e_Interim_Report_2017.pdf"
HKBN_FY17_ANNUAL_REPORT_URL = "https://reg.hkbn.net/WwwCMS/upload/pdf/en/e_AnnualReport2017_HKEX.pdf"
HKBN_FY18_INTERIM_URL = "https://reg.hkbn.net/WwwCMS/upload/pdf/en/LTN20180419241_eng.pdf"
HKBN_FY18_INTERIM_REPORT_URL = "https://reg.hkbn.net/WwwCMS/upload/pdf/en/HKBN_FY18%20Interim%20Report_e101.pdf"
HKBN_FY18_ANNUAL_REPORT_URL = "https://reg.hkbn.net/WwwCMS/upload/pdf/en/e_Annual_Report_2018.pdf"
HKBN_FY19_INTERIM_URL = "https://reg.hkbn.net/WwwCMS/upload/pdf/en/e_interim_results_FY19.pdf"
HKBN_FY19_INTERIM_REPORT_URL = "https://reg.hkbn.net/WwwCMS/upload/pdf/en/e_Interim_Report_2019.pdf"
HKBN_FY19_ANNUAL_RESULTS_URL = "https://reg.hkbn.net/WwwCMS/upload/pdf/en/e_FY19_AnnualResultsAnnouncement.pdf"
HKBN_FY19_ANNUAL_REPORT_URL = "https://reg.hkbn.net/WwwCMS/upload/pdf/en/e_AnnualReport_2019.pdf"
HKBN_FY20_INTERIM_URL = "https://reg.hkbn.net/WwwCMS/upload/pdf/en/e_InterimResultsAnnouncement_FY20.pdf"
HKBN_FY20_INTERIM_REPORT_URL = "https://reg.hkbn.net/WwwCMS/upload/pdf/en/e_InterimReport_2020.pdf"
HKBN_FY20_ANNUAL_RESULTS_URL = "https://reg.hkbn.net/WwwCMS/upload/pdf/en/e_FY20_AnnualResultsAnnouncement.pdf"
HKBN_FY20_ANNUAL_REPORT_URL = "https://reg.hkbn.net/WwwCMS/upload/pdf/en/20201112_AnnualReport2020_Eng.pdf"
HKBN_FY21_INTERIM_RESULTS_URL = "https://reg.hkbn.net/WwwCMS/upload/pdf/en/e_InterimResultsAnnouncement_FY21.pdf"

HKBN_2023_H1_SOURCES = [
    {"label": "HKBN FY23 Interim Results Announcement - Financial Highlights", "url": HKBN_FY23_INTERIM_URL, "evidence": "H1 2023 revenue、profit、EBITDA、AFF、capital expenditure及H1 2022比较数。"},
    {"label": "HKBN FY23 Interim Results Announcement - Balance Sheet and Liquidity", "url": HKBN_FY23_INTERIM_URL, "evidence": "2023年2月28日现金、总资产和gross debt。"},
    {"label": "HKBN FY23 Interim Report - cash flow statement", "url": HKBN_FY23_INTERIM_REPORT_URL, "evidence": "正式中报现金流量表披露H1 2023经营现金流和购买物业、厂房及设备付款。"},
    {"label": "HKBN FY24 Interim Results Announcement - Prior-period comparative", "url": HKBN_FY24_INTERIM_URL, "evidence": "FY24中期公告H1 2023比较栏交叉验证H1 2023 revenue、profit、EBITDA、AFF和capital expenditure。"},
    {"label": "HKBN Financial Results index", "url": HKBN_FINANCIAL_RESULTS_URL, "evidence": "公司官网业绩入口用于交叉定位FY23中期和全年业绩材料。"},
]

HKBN_2021_H2_SOURCES = [
    {"label": "HKBN FY21 Annual Results Announcement", "url": HKBN_FY21_ANNUAL_RESULTS_URL, "evidence": "FY21全年revenue、profit、EBITDA、AFF、capital expenditure、现金、资产和gross debt。"},
    {"label": "HKBN FY21 Annual Report", "url": HKBN_FY21_ANNUAL_REPORT_URL, "evidence": "FY21正式年报现金流量表、资产负债表和gross debt附注。"},
    {"label": "HKBN FY21 Interim Results Announcement", "url": HKBN_FY21_INTERIM_URL, "evidence": "H1 2021和H1 2020收入比较栏，用于从FY21/FY20全年披露复算H2 2021同比。"},
    {"label": "HKBN FY22 Interim Results Announcement comparative column", "url": HKBN_FY22_INTERIM_URL, "evidence": "H1 2021比较栏，用于从FY21全年复算H2 2021。"},
    {"label": "HKBN FY22 Interim Report comparative column", "url": HKBN_FY22_INTERIM_REPORT_URL, "evidence": "H1 2021比较栏和现金流量表，用于复算H2 2021经营现金流与FCF。"},
    {"label": "HKBN Financial Results index", "url": HKBN_FINANCIAL_RESULTS_URL, "evidence": "公司官网业绩入口用于交叉定位FY21/FY22业绩材料。"},
]

HKBN_2022_H1_SOURCES = [
    {"label": "HKBN FY22 Interim Results Announcement - Financial Highlights", "url": HKBN_FY22_INTERIM_URL, "evidence": "H1 2022 revenue、profit、EBITDA、AFF、capital expenditure及H1 2021比较数。"},
    {"label": "HKBN FY22 Interim Results Announcement - Balance Sheet and Liquidity", "url": HKBN_FY22_INTERIM_URL, "evidence": "2022年2月28日现金、总资产和gross debt。"},
    {"label": "HKBN FY22 Interim Report - cash flow statement", "url": HKBN_FY22_INTERIM_REPORT_URL, "evidence": "正式中报现金流量表披露H1 2022经营现金流和购买物业、厂房及设备付款。"},
    {"label": "HKBN FY23 Interim Results Announcement - Prior-period comparative", "url": HKBN_FY23_INTERIM_URL, "evidence": "FY23中期公告H1 2022比较栏交叉验证H1 2022 revenue、profit、EBITDA、AFF和capital expenditure。"},
    {"label": "HKBN Financial Results index", "url": HKBN_FINANCIAL_RESULTS_URL, "evidence": "公司官网业绩入口用于交叉定位FY22中期业绩材料。"},
]

HKBN_2022_H2_SOURCES = [
    {"label": "HKBN FY22 Interim Results Announcement", "url": HKBN_FY22_INTERIM_URL, "evidence": "H1 2022累计值及H1 2021比较数，用于从FY22/FY21全年披露复算H2和同比。"},
    {"label": "HKBN FY22 Annual Results Announcement", "url": HKBN_FY22_ANNUAL_RESULTS_URL, "evidence": "FY22全年revenue、profit、EBITDA、AFF、capital expenditure、现金、总资产和gross debt。"},
    {"label": "HKBN FY22 Interim Report - cash flow statement", "url": HKBN_FY22_INTERIM_REPORT_URL, "evidence": "H1 2022经营现金流和购买物业、厂房及设备付款，用于从全年现金流复算H2。"},
    {"label": "HKBN FY22 Annual Report - cash flow statement", "url": HKBN_FY22_ANNUAL_REPORT_URL, "evidence": "FY22正式年报现金流量表披露全年经营现金流和购买物业、厂房及设备付款。"},
    {"label": "HKBN FY23 Annual Results Announcement - Prior-year comparative", "url": HKBN_FY23_ANNUAL_RESULTS_URL, "evidence": "FY23全年公告FY22比较栏交叉验证全年revenue、profit、EBITDA和AFF。"},
    {"label": "HKBN Financial Results index", "url": HKBN_FINANCIAL_RESULTS_URL, "evidence": "公司官网业绩入口用于交叉定位FY22全年业绩材料。"},
]

HKBN_2023_H2_SOURCES = [
    {"label": "HKBN FY23 Interim Results Announcement", "url": HKBN_FY23_INTERIM_URL, "evidence": "H1 2023累计值及H1 2022比较数，用于从FY23/FY22全年披露复算H2和同比。"},
    {"label": "HKBN FY23 Annual Results Announcement", "url": HKBN_FY23_ANNUAL_RESULTS_URL, "evidence": "FY23全年revenue、profit/loss、EBITDA、AFF、capital expenditure、现金、总资产和gross debt。"},
    {"label": "HKBN FY23 Interim Report - cash flow statement", "url": HKBN_FY23_INTERIM_REPORT_URL, "evidence": "H1 2023经营现金流和购买物业、厂房及设备付款，用于从全年现金流复算H2。"},
    {"label": "HKBN FY23 Annual Report - cash flow statement", "url": HKBN_FY23_ANNUAL_REPORT_URL, "evidence": "正式年报现金流量表披露FY23全年经营现金流和购买物业、厂房及设备付款。"},
    {"label": "HKBN FY2023 Annual Results Press Release", "url": HKBN_FY23_PRESS_RELEASE_URL, "evidence": "公司新闻稿交叉验证FY23 revenue、EBITDA、loss和AFF摘要，并链接FY23全年公告。"},
    {"label": "HKBN Financial Results index", "url": HKBN_FINANCIAL_RESULTS_URL, "evidence": "公司官网业绩入口用于交叉定位FY23中期和全年业绩材料。"},
]

HKBN_2024_H1_SOURCES = [
    {"label": "HKBN FY24 Interim Results Announcement - Financial Highlights", "url": HKBN_FY24_INTERIM_URL, "evidence": "H1 2024 revenue、profit、EBITDA、AFF、capital expenditure及H1 2023比较数。"},
    {"label": "HKBN FY24 Interim Results Announcement - Balance Sheet and Liquidity", "url": HKBN_FY24_INTERIM_URL, "evidence": "2024年2月29日现金、总资产和gross debt。"},
    {"label": "HKBN FY24 Interim Report - cash flow statement", "url": HKBN_FY24_INTERIM_REPORT_URL, "evidence": "正式中报现金流量表披露H1 2024经营现金流和购买物业、厂房及设备付款。"},
    {"label": "HKBN Financial Results index", "url": HKBN_FINANCIAL_RESULTS_URL, "evidence": "公司官网业绩入口用于交叉定位FY24中期和全年业绩材料。"},
]

HKBN_2024_H2_SOURCES = [
    {"label": "HKBN FY24 Interim Results Announcement", "url": HKBN_FY24_INTERIM_URL, "evidence": "H1 2024累计值及H1 2023比较数，用于从FY24/FY23全年披露复算H2和同比。"},
    {"label": "HKBN FY24 Annual Results Announcement", "url": HKBN_FY24_ANNUAL_RESULTS_URL, "evidence": "FY24全年revenue、profit、EBITDA、AFF、capital expenditure、现金、总资产和gross debt。"},
    {"label": "HKBN FY24 Interim Report - cash flow statement", "url": HKBN_FY24_INTERIM_REPORT_URL, "evidence": "H1 2024经营现金流和购买物业、厂房及设备付款，用于从全年现金流复算H2。"},
    {"label": "HKBN FY24 Annual Report - cash flow statement", "url": HKBN_FY24_ANNUAL_REPORT_URL, "evidence": "正式年报现金流量表披露FY24全年经营现金流和购买物业、厂房及设备付款。"},
    {"label": "HKBN FY2024 Annual Results Press Release", "url": HKBN_FY24_PRESS_RELEASE_URL, "evidence": "公司新闻稿交叉验证FY24 revenue、EBITDA、H2 EBITDA、profit和AFF摘要，并链接FY24全年公告。"},
    {"label": "HKBN Financial Results index", "url": HKBN_FINANCIAL_RESULTS_URL, "evidence": "公司官网业绩入口用于交叉定位FY24中期和全年业绩材料。"},
]

HKBN_2025_H1_SOURCES = [
    {"label": "HKBN FY25 Interim Results Announcement - Financial Highlights", "url": HKBN_FY25_INTERIM_URL, "evidence": "H1 2025 revenue、EBITDA、AFF、profit、capital expenditure。"},
    {"label": "HKBN FY25 Interim Results Announcement - Balance Sheet and Liquidity", "url": HKBN_FY25_INTERIM_URL, "evidence": "2025年2月28日现金、总资产和gross debt。"},
    {"label": "HKBN FY25 Interim Report - cash flow statement", "url": HKBN_FY25_INTERIM_REPORT_URL, "evidence": "正式中报现金流量表披露H1 2025经营现金流和购买物业、厂房及设备付款。"},
    {"label": "HKBN Financial Results index", "url": HKBN_FINANCIAL_RESULTS_URL, "evidence": "公司官网业绩入口用于交叉定位FY25中期材料。"},
]

HKBN_2025_H2_SOURCES = [
    {"label": "HKBN FY25 Interim Results Announcement", "url": HKBN_FY25_INTERIM_URL, "evidence": "H1 2025累计值，用于从FY25全年披露复算H2。"},
    {"label": "HKBN FY25 Annual Results Announcement", "url": HKBN_FY25_ANNUAL_RESULTS_URL, "evidence": "FY25全年revenue、EBITDA、AFF、profit、capital expenditure、现金和gross debt。"},
    {"label": "HKBN FY25 Interim Report - cash flow statement", "url": HKBN_FY25_INTERIM_REPORT_URL, "evidence": "H1 2025经营现金流和购买物业、厂房及设备付款，用于从全年现金流复算H2。"},
    {"label": "HKBN FY25 Annual Report - cash flow statement", "url": HKBN_FY25_ANNUAL_REPORT_URL, "evidence": "正式年报现金流量表披露FY25全年经营现金流和购买物业、厂房及设备付款。"},
    {"label": "HKBN FY2025 Annual Results Press Release", "url": HKBN_FY25_PRESS_RELEASE_URL, "evidence": "公司新闻稿交叉验证FY25 revenue、EBITDA、AFF和net profit摘要。"},
    {"label": "HKBN Financial Results index", "url": HKBN_FINANCIAL_RESULTS_URL, "evidence": "公司官网业绩入口用于交叉定位FY25全年材料。"},
]

HKBN_2026_H1_SOURCES = [
    {"label": "HKBN FY26 Interim Results Announcement - Financial Highlights", "url": HKBN_FY26_INTERIM_URL, "evidence": "H1 2026 revenue、EBITDA、AFF、profit、capital expenditure。"},
    {"label": "HKBN FY26 Interim Results Announcement - Balance Sheet and Liquidity", "url": HKBN_FY26_INTERIM_URL, "evidence": "2026年2月28日现金、总资产和gross debt。"},
    {"label": "HKBN FY26 Interim Report - cash flow statement", "url": HKBN_FY26_INTERIM_REPORT_URL, "evidence": "正式中报现金流量表披露H1 2026经营现金流和购买物业、厂房及设备付款。"},
    {"label": "HKBN Financial Results index", "url": HKBN_FINANCIAL_RESULTS_URL, "evidence": "公司官网业绩入口用于交叉定位FY26中期材料。"},
]

HKBN_2016_2021_SOURCES_BY_PERIOD = {
    "H2 2016": [
        {"label": "HKBN FY16 Interim Results Announcement", "url": HKBN_FY16_INTERIM_URL, "evidence": "FY16 H1 revenue、EBITDA，用于从FY16全年披露复算H2。"},
        {"label": "HKBN FY16 Annual Results Announcement", "url": HKBN_FY16_ANNUAL_RESULTS_URL, "evidence": "FY16全年 revenue、EBITDA。"},
        {"label": "HKBN FY16 Annual Report", "url": HKBN_FY16_ANNUAL_REPORT_URL, "evidence": "正式年报Financial highlights和综合损益表交叉验证FY16全年收入与EBITDA。"},
        {"label": "HKBN Financial Results index", "url": HKBN_FINANCIAL_RESULTS_URL, "evidence": "公司官网业绩入口用于定位FY16公告和报告。"},
    ],
    "H1 2017": [
        {"label": "HKBN FY17 Interim Results Announcement", "url": HKBN_FY17_INTERIM_URL, "evidence": "FY17 H1 revenue、EBITDA及FY16 H1比较栏。"},
        {"label": "HKBN FY17 Interim Report", "url": HKBN_FY17_INTERIM_REPORT_URL, "evidence": "正式中报综合损益表披露FY17 H1收入。"},
        {"label": "HKBN Financial Results index", "url": HKBN_FINANCIAL_RESULTS_URL, "evidence": "公司官网业绩入口用于定位FY17中期材料。"},
    ],
    "H2 2017": [
        {"label": "HKBN FY17 Interim Results Announcement", "url": HKBN_FY17_INTERIM_URL, "evidence": "FY17 H1累计值，用于从FY17全年披露复算H2。"},
        {"label": "HKBN FY17 Annual Report", "url": HKBN_FY17_ANNUAL_REPORT_URL, "evidence": "FY17全年Financial highlights披露 revenue、EBITDA。"},
        {"label": "HKBN Financial Results index", "url": HKBN_FINANCIAL_RESULTS_URL, "evidence": "公司官网业绩入口用于定位FY17报告。"},
    ],
    "H1 2018": [
        {"label": "HKBN FY18 Interim Results Announcement", "url": HKBN_FY18_INTERIM_URL, "evidence": "FY18 H1 revenue、EBITDA及FY17 H1比较栏。"},
        {"label": "HKBN FY18 Interim Report", "url": HKBN_FY18_INTERIM_REPORT_URL, "evidence": "正式中报综合损益表披露FY18 H1收入。"},
        {"label": "HKBN Financial Results index", "url": HKBN_FINANCIAL_RESULTS_URL, "evidence": "公司官网业绩入口用于定位FY18中期材料。"},
    ],
    "H2 2018": [
        {"label": "HKBN FY18 Interim Results Announcement", "url": HKBN_FY18_INTERIM_URL, "evidence": "FY18 H1累计值，用于从FY18全年披露复算H2。"},
        {"label": "HKBN FY18 Annual Report", "url": HKBN_FY18_ANNUAL_REPORT_URL, "evidence": "FY18全年Financial highlights披露 revenue、EBITDA。"},
        {"label": "HKBN Financial Results index", "url": HKBN_FINANCIAL_RESULTS_URL, "evidence": "公司官网业绩入口用于定位FY18报告。"},
    ],
    "H1 2019": [
        {"label": "HKBN FY19 Interim Results Announcement", "url": HKBN_FY19_INTERIM_URL, "evidence": "FY19 H1 revenue、EBITDA及FY18 H1比较栏。"},
        {"label": "HKBN FY19 Interim Report", "url": HKBN_FY19_INTERIM_REPORT_URL, "evidence": "正式中报综合损益表披露FY19 H1收入。"},
        {"label": "HKBN Financial Results index", "url": HKBN_FINANCIAL_RESULTS_URL, "evidence": "公司官网业绩入口用于定位FY19中期材料。"},
    ],
    "H2 2019": [
        {"label": "HKBN FY19 Interim Results Announcement", "url": HKBN_FY19_INTERIM_URL, "evidence": "FY19 H1累计值，用于从FY19全年披露复算H2。"},
        {"label": "HKBN FY19 Annual Results Announcement", "url": HKBN_FY19_ANNUAL_RESULTS_URL, "evidence": "FY19全年 revenue、EBITDA。"},
        {"label": "HKBN FY19 Annual Report", "url": HKBN_FY19_ANNUAL_REPORT_URL, "evidence": "正式年报Financial highlights和综合损益表交叉验证FY19全年收入与EBITDA。"},
    ],
    "H1 2020": [
        {"label": "HKBN FY20 Interim Results Announcement", "url": HKBN_FY20_INTERIM_URL, "evidence": "FY20 H1 revenue、EBITDA及FY19 H1比较栏。"},
        {"label": "HKBN FY20 Interim Report", "url": HKBN_FY20_INTERIM_REPORT_URL, "evidence": "正式中报综合损益表披露FY20 H1收入。"},
        {"label": "HKBN Financial Results index", "url": HKBN_FINANCIAL_RESULTS_URL, "evidence": "公司官网业绩入口用于定位FY20中期材料。"},
    ],
    "H2 2020": [
        {"label": "HKBN FY20 Interim Results Announcement", "url": HKBN_FY20_INTERIM_URL, "evidence": "FY20 H1累计值，用于从FY20全年披露复算H2。"},
        {"label": "HKBN FY20 Annual Results Announcement", "url": HKBN_FY20_ANNUAL_RESULTS_URL, "evidence": "FY20全年 revenue、EBITDA。"},
        {"label": "HKBN FY20 Annual Report", "url": HKBN_FY20_ANNUAL_REPORT_URL, "evidence": "正式年报Financial highlights和综合损益表交叉验证FY20全年收入与EBITDA。"},
    ],
    "H1 2021": [
        {"label": "HKBN FY21 Interim Results Announcement", "url": HKBN_FY21_INTERIM_RESULTS_URL, "evidence": "FY21 H1 revenue、EBITDA及FY20 H1比较栏。"},
        {"label": "HKBN FY21 Interim Report", "url": HKBN_FY21_INTERIM_URL, "evidence": "正式中报披露FY21 H1收入；用于与中期业绩公告交叉验证。"},
        {"label": "HKBN FY21 Annual Results Announcement", "url": HKBN_FY21_ANNUAL_RESULTS_URL, "evidence": "FY21全年报告和H1数可交叉复核。"},
        {"label": "HKBN Financial Results index", "url": HKBN_FINANCIAL_RESULTS_URL, "evidence": "公司官网业绩入口用于定位FY21中期材料。"},
    ],
}

HKBN_2016_2021_METRICS = {
    "H2 2016": {
        "revenue": (1558.468, "FY16全年Revenue 2,784.007百万港元减H1 2016 Revenue 1,225.539百万港元，复算H2 2016为1,558.468百万港元。"),
        "ebitda": (495.121, "FY16全年EBITDA 1,006.387百万港元减H1 2016 EBITDA 511.266百万港元，复算H2 2016为495.121百万港元。"),
    },
    "H1 2017": {
        "revenue": (1534.726, "FY17中期业绩公告Financial highlights披露H1 2017 Revenue 1,534.726百万港元。"),
        "ebitda": (480.961, "FY17中期业绩公告Financial highlights披露H1 2017 EBITDA 480.961百万港元。"),
    },
    "H2 2017": {
        "revenue": (1697.584, "FY17全年Revenue 3,232.310百万港元减H1 2017 Revenue 1,534.726百万港元，复算H2 2017为1,697.584百万港元。"),
        "ebitda": (560.289, "FY17全年EBITDA 1,041.250百万港元减H1 2017 EBITDA 480.961百万港元，复算H2 2017为560.289百万港元。"),
    },
    "H1 2018": {
        "revenue": (1868.095, "FY18中期业绩公告Financial highlights披露H1 2018 Revenue 1,868.095百万港元。"),
        "ebitda": (593.733, "FY18中期业绩公告Financial highlights披露H1 2018 EBITDA 593.733百万港元。"),
    },
    "H2 2018": {
        "revenue": (2080.857, "FY18全年Revenue 3,948.952百万港元减H1 2018 Revenue 1,868.095百万港元，复算H2 2018为2,080.857百万港元。"),
        "ebitda": (585.855, "FY18全年EBITDA 1,179.588百万港元减H1 2018 EBITDA 593.733百万港元，复算H2 2018为585.855百万港元。"),
    },
    "H1 2019": {
        "revenue": (2218.591, "FY19中期业绩公告Financial highlights披露H1 2019 Revenue 2,218.591百万港元。"),
        "ebitda": (723.396, "FY19中期业绩公告Financial highlights披露H1 2019 EBITDA 723.396百万港元。"),
    },
    "H2 2019": {
        "revenue": (2889.046, "FY19全年Revenue 5,107.637百万港元减H1 2019 Revenue 2,218.591百万港元，复算H2 2019为2,889.046百万港元。"),
        "ebitda": (985.952, "FY19全年EBITDA 1,709.348百万港元减H1 2019 EBITDA 723.396百万港元，复算H2 2019为985.952百万港元。"),
    },
    "H1 2020": {
        "revenue": (4457.282, "FY20中期业绩公告Financial highlights披露H1 2020 Revenue 4,457.282百万港元。"),
        "ebitda": (1283.359, "FY20中期业绩公告Financial highlights披露H1 2020 EBITDA 1,283.359百万港元。"),
    },
    "H2 2020": {
        "revenue": (4995.675, "FY20全年Revenue 9,452.957百万港元减H1 2020 Revenue 4,457.282百万港元，复算H2 2020为4,995.675百万港元。"),
        "ebitda": (1222.084, "FY20全年EBITDA 2,505.443百万港元减H1 2020 EBITDA 1,283.359百万港元，复算H2 2020为1,222.084百万港元。"),
    },
    "H1 2021": {
        "revenue": (6229.584, "FY21中期业绩公告Financial highlights披露H1 2021 Revenue 6,229.584百万港元。"),
        "ebitda": (1311.817, "FY21中期业绩公告Financial highlights披露H1 2021 EBITDA 1,311.817百万港元。"),
    },
}

ICABLE_2021_INTERIM_RESULTS_URL = "https://cdn.prod.website-files.com/6435c91757d4732e4d55d786/6464ece87f9280b49553afbb_e01097_ann_0820.pdf"
ICABLE_2021_ANNUAL_RESULTS_URL = "https://cdn.prod.website-files.com/6435c91757d4732e4d55d786/6465c2e0eac561b688372ae9_2022033102651.pdf"
ICABLE_2021_INTERIM_REPORT_URL = "https://cdn.prod.website-files.com/6435c91757d4732e4d55d786/646a66d575058e8e008bb973_(09)%202021%20Interim%20Report%20of%20the%20Company%20(Eng).pdf"
ICABLE_2021_ANNUAL_REPORT_URL = "https://cdn.prod.website-files.com/6435c91757d4732e4d55d786/646a7057ffc7d3ef56e6123e_2022042602184.pdf"
ICABLE_2022_INTERIM_RESULTS_URL = "https://cdn.prod.website-files.com/6435c91757d4732e4d55d786/6465c2070a1d9566eccb37e4_2022082601937.pdf"
ICABLE_2022_ANNUAL_RESULTS_URL = "https://cdn.prod.website-files.com/6435c91757d4732e4d55d786/6465b5d2497e81dbe90238a5_2023032701882.pdf"
ICABLE_2022_INTERIM_REPORT_URL = "https://cdn.prod.website-files.com/6435c91757d4732e4d55d786/646a679a492ea69c3446c2ef_interim%202022.pdf"
ICABLE_2022_ANNUAL_REPORT_URL = "https://cdn.prod.website-files.com/6435c91757d4732e4d55d786/652fa078ae3c0fa42484d802_2023042704017%20(Eng)-compressed-02.pdf"
ICABLE_2023_INTERIM_RESULTS_URL = "https://www1.hkexnews.hk/listedco/listconews/sehk/2023/0825/2023082502129.pdf"
ICABLE_2023_ANNUAL_RESULTS_URL = "https://www1.hkexnews.hk/listedco/listconews/sehk/2024/0322/2024032201867.pdf"
ICABLE_2023_INTERIM_REPORT_URL = "https://cdn.prod.website-files.com/6435c91757d4732e4d55d786/650c442342fa6ad7b9a378a0_2023092101369.pdf"
ICABLE_2023_ANNUAL_REPORT_URL = "https://cdn.prod.website-files.com/6435c91757d4732e4d55d786/66265701c9699b6ccbd38aa4_2023%20Annual%20Report%20(Eng).pdf"
ICABLE_FINANCIAL_CALENDAR_URL = "https://www.i-cablecomm.com/en/financial-calender"
ICABLE_2024_INTERIM_RESULTS_URL = "https://cdn.prod.website-files.com/6435c91757d4732e4d55d786/66cf328ec9c87a16d90f9e84_2024082802113.pdf"
ICABLE_2024_INTERIM_REPORT_URL = "https://cdn.prod.website-files.com/6435c91757d4732e4d55d786/66f15fb50ab5cc34cd11dcdd_2024092301348%20(Eng).pdf"
ICABLE_2024_ANNUAL_REPORT_URL = "https://cdn.prod.website-files.com/6435c91757d4732e4d55d786/680782762c959f8ed84d6f9f_ANNUAL%20REPORT%202024.pdf"
ICABLE_2025_INTERIM_RESULTS_URL = "https://www1.hkexnews.hk/listedco/listconews/sehk/2025/0826/2025082601734.pdf"
ICABLE_2025_ANNUAL_RESULTS_URL = "https://www1.hkexnews.hk/listedco/listconews/sehk/2026/0327/2026032703354.pdf"
ICABLE_2025_INTERIM_REPORT_URL = "https://cdn.prod.website-files.com/6435c91757d4732e4d55d786/68d28114d4d00d3da20d58b1_2025ir-Eng.pdf"
ICABLE_2025_ANNUAL_REPORT_URL = "https://cdn.prod.website-files.com/6435c91757d4732e4d55d786/69f09c083e84ce9effada94a_2025%20Annual%20Report%20(ENG).pdf"
ICABLE_REPORTS_INDEX_URL = "https://www.i-cablecomm.com/en/annual-interim-reports"
ICABLE_2016_INTERIM_REPORT_URL = "https://cdn.prod.website-files.com/6435c91757d4732e4d55d786/646a66474df1a31225e3eb7d_e01097%20IR2016.pdf"
ICABLE_2016_ANNUAL_REPORT_URL = "https://cdn.prod.website-files.com/6435c91757d4732e4d55d786/646a6ef90500c46bb85c70d3_e01097%20Annual%20Report%202016.pdf"
ICABLE_2016_ANNUAL_REPORT_HKEX_URL = "https://www.hkexnews.hk/listedco/listconews/sehk/2017/0322/LTN20170322225.pdf"
ICABLE_2017_INTERIM_REPORT_URL = "https://cdn.prod.website-files.com/6435c91757d4732e4d55d786/646a666064dc0b5ec395666b_e01097%20IR2017.pdf"
ICABLE_2017_INTERIM_REPORT_HKEX_URL = "https://www.hkexnews.hk/listedco/listconews/SEHK/2017/0904/LTN201709041265.pdf"
ICABLE_2017_ANNUAL_REPORT_URL = "https://cdn.prod.website-files.com/6435c91757d4732e4d55d786/646a6f77b39363e2e3ca5be3_e01097%20Annual%20Report%202017.pdf"
ICABLE_2017_ANNUAL_REPORT_HKEX_URL = "https://www.hkexnews.hk/listedco/listconews/SEHK/2018/0419/LTN201804191333.pdf"
ICABLE_2018_INTERIM_REPORT_URL = "https://cdn.prod.website-files.com/6435c91757d4732e4d55d786/646a66790500c46bb854e485_e01097%20IR2018.pdf"
ICABLE_2018_ANNUAL_REPORT_URL = "https://cdn.prod.website-files.com/6435c91757d4732e4d55d786/646a6f92128f7ce7731f8ff9_e01097%20Annual%20Report%202018.pdf"
ICABLE_2019_INTERIM_REPORT_URL = "https://cdn.prod.website-files.com/6435c91757d4732e4d55d786/646a66964df1a31225e427ac_e01097%20IR2019.pdf"
ICABLE_2019_ANNUAL_REPORT_URL = "https://cdn.prod.website-files.com/6435c91757d4732e4d55d786/646a6fc6782deca0e2e3bc0b_e01097%20Annual%20Report%202019.pdf"
ICABLE_2019_ANNUAL_REPORT_HKEX_URL = "https://www.hkexnews.hk/listedco/listconews/sehk/2020/0423/2020042301955.pdf"
ICABLE_2020_INTERIM_REPORT_URL = "https://cdn.prod.website-files.com/6435c91757d4732e4d55d786/646a66adffc7d3ef56dd4389_e01097%20IR2020.pdf"
ICABLE_2020_INTERIM_REPORT_HKEX_URL = "https://www.hkexnews.hk/listedco/listconews/sehk/2020/0923/2020092300945.pdf"
ICABLE_2020_ANNUAL_REPORT_OLD_URL = "https://cdn.prod.website-files.com/6435c91757d4732e4d55d786/646a6fe80500c46bb85d24c6_(07)%202020%20Annual%20Report%20of%20the%20Company%20(Eng).pdf"
ICABLE_2020_ANNUAL_REPORT_HKEX_URL = "https://www.hkexnews.hk/listedco/listconews/sehk/2021/0426/2021042601938.pdf"
ICABLE_ANNOUNCEMENTS_2021_URL = "https://www.i-cablecomm.com/en-announcements-year/2021"
ICABLE_ANNOUNCEMENTS_2022_URL = "https://www.i-cablecomm.com/en-announcements-year/2022"
ICABLE_ANNOUNCEMENTS_2023_URL = "https://www.i-cablecomm.com/en-announcements-year/2023"
ICABLE_ANNOUNCEMENTS_2024_URL = "https://www.i-cablecomm.com/en-announcements-year/2024"
ICABLE_ANNOUNCEMENTS_2025_URL = "https://www.i-cablecomm.com/en-announcements-year/2025"

ICABLE_2021_H1_SOURCES = [
    {"label": "i-CABLE 2021 Interim Results Announcement", "url": ICABLE_2021_INTERIM_RESULTS_URL, "evidence": "2021中期业绩公告披露H1 2021收入、经营亏损、期内亏损、EBITDA近似口径、现金、总资产、可转债、借款和租赁负债。"},
    {"label": "i-CABLE 2021 Interim Report", "url": ICABLE_2021_INTERIM_REPORT_URL, "evidence": "2021中期报告披露H1 2021服务成本明细、经营现金流、购买物业厂房及设备付款和PPE资本开支。"},
    {"label": "i-CABLE Annual & Interim Reports index", "url": ICABLE_REPORTS_INDEX_URL, "evidence": "公司官网年报/中报入口列示2021 Interim Report和2021 Annual Report。"},
    {"label": "i-CABLE 2021 Announcements index", "url": ICABLE_ANNOUNCEMENTS_2021_URL, "evidence": "公司官网2021公告入口列示2021中期业绩公告。"},
]

ICABLE_2021_H2_SOURCES = [
    {"label": "i-CABLE 2021 Interim Results Announcement", "url": ICABLE_2021_INTERIM_RESULTS_URL, "evidence": "H1 2021累计值，用于从FY2021全年披露复算H2。"},
    {"label": "i-CABLE 2021 Final Results Announcement", "url": ICABLE_2021_ANNUAL_RESULTS_URL, "evidence": "2021全年公告披露FY2021收入、经营亏损、年度亏损、EBITDA近似口径、现金、总资产、可转债、借款和租赁负债。"},
    {"label": "i-CABLE 2021 Interim Report", "url": ICABLE_2021_INTERIM_REPORT_URL, "evidence": "2021中期报告披露H1服务成本明细、经营现金流和购买物业、厂房及设备付款，用于从全年复算H2。"},
    {"label": "i-CABLE 2021 Annual Report", "url": ICABLE_2021_ANNUAL_REPORT_URL, "evidence": "2021年报披露FY2021服务成本明细、经营现金流、购买物业厂房及设备付款和资产负债表。"},
    {"label": "i-CABLE Annual & Interim Reports index", "url": ICABLE_REPORTS_INDEX_URL, "evidence": "公司官网年报/中报入口列示2021年报和2021中报。"},
    {"label": "i-CABLE 2022 Announcements index", "url": ICABLE_ANNOUNCEMENTS_2022_URL, "evidence": "公司官网2022公告入口列示2021全年业绩公告。"},
]

ICABLE_2022_H1_SOURCES = [
    {"label": "i-CABLE 2022 Interim Results Announcement", "url": ICABLE_2022_INTERIM_RESULTS_URL, "evidence": "2022中期业绩公告披露H1 2022收入、经营亏损、期内亏损、EBITDA近似口径、现金、总资产、可转债、借款和租赁负债。"},
    {"label": "i-CABLE 2022 Interim Report", "url": ICABLE_2022_INTERIM_REPORT_URL, "evidence": "2022中期报告披露H1 2022服务成本明细、经营现金流、购买物业厂房及设备付款和PPE资本开支。"},
    {"label": "i-CABLE Annual & Interim Reports index", "url": ICABLE_REPORTS_INDEX_URL, "evidence": "公司官网年报/中报入口列示2022 Interim Report和2022 Annual Report。"},
    {"label": "i-CABLE 2022 Announcements index", "url": ICABLE_ANNOUNCEMENTS_2022_URL, "evidence": "公司官网2022公告入口列示2022中期业绩公告。"},
]

ICABLE_2022_H2_SOURCES = [
    {"label": "i-CABLE 2022 Interim Results Announcement", "url": ICABLE_2022_INTERIM_RESULTS_URL, "evidence": "H1 2022累计值，用于从FY2022全年披露复算H2。"},
    {"label": "i-CABLE 2022 Final Results Announcement", "url": ICABLE_2022_ANNUAL_RESULTS_URL, "evidence": "2022全年公告披露FY2022收入、经营亏损、年度亏损、EBITDA近似口径、现金、总资产、可转债、借款和租赁负债。"},
    {"label": "i-CABLE 2022 Interim Report", "url": ICABLE_2022_INTERIM_REPORT_URL, "evidence": "2022中期报告披露H1服务成本明细、经营现金流和购买物业、厂房及设备付款，用于从全年复算H2。"},
    {"label": "i-CABLE 2022 Annual Report", "url": ICABLE_2022_ANNUAL_REPORT_URL, "evidence": "2022年报披露FY2022服务成本明细、经营现金流、购买物业厂房及设备付款和资产负债表。"},
    {"label": "i-CABLE Annual & Interim Reports index", "url": ICABLE_REPORTS_INDEX_URL, "evidence": "公司官网年报/中报入口列示2022年报和2022中报。"},
    {"label": "i-CABLE 2023 Announcements index", "url": ICABLE_ANNOUNCEMENTS_2023_URL, "evidence": "公司官网2023公告入口列示2022全年业绩公告。"},
]

ICABLE_2023_H1_SOURCES = [
    {"label": "i-CABLE 2023 Interim Results Announcement - HKEX", "url": ICABLE_2023_INTERIM_RESULTS_URL, "evidence": "2023中期业绩公告披露H1 2023收入、经营亏损、期内亏损、分部表、资本开支、现金、总资产、可转债、借款和租赁负债。"},
    {"label": "i-CABLE 2023 Interim Report", "url": ICABLE_2023_INTERIM_REPORT_URL, "evidence": "2023中期报告损益表和现金流量表披露H1收入、服务成本明细、经营现金流和购买物业、厂房及设备付款。"},
    {"label": "i-CABLE Annual & Interim Reports index", "url": ICABLE_REPORTS_INDEX_URL, "evidence": "公司官网年报/中报入口列示2023 Interim Report和2023 Annual Report。"},
    {"label": "i-CABLE Financial Calendar", "url": ICABLE_FINANCIAL_CALENDAR_URL, "evidence": "公司官网财务日历列示2023 Interim Results Announcement日期为2023-08-25。"},
]

ICABLE_2023_H2_SOURCES = [
    {"label": "i-CABLE 2023 Interim Results Announcement - HKEX", "url": ICABLE_2023_INTERIM_RESULTS_URL, "evidence": "H1 2023累计值，用于从FY2023全年披露复算H2。"},
    {"label": "i-CABLE 2023 Final Results Announcement - HKEX", "url": ICABLE_2023_ANNUAL_RESULTS_URL, "evidence": "2023全年公告披露FY2023全年收入、经营亏损、年度亏损、分部表、资本开支、现金、总资产、可转债、借款和租赁负债。"},
    {"label": "i-CABLE 2023 Interim Report", "url": ICABLE_2023_INTERIM_REPORT_URL, "evidence": "2023中期报告披露H1服务成本明细、经营现金流和购买物业、厂房及设备付款，用于从全年复算H2。"},
    {"label": "i-CABLE 2023 Annual Report", "url": ICABLE_2023_ANNUAL_REPORT_URL, "evidence": "2023年报损益表和现金流量表披露FY2023收入、服务成本明细、经营现金流和购买物业、厂房及设备付款。"},
    {"label": "i-CABLE Annual & Interim Reports index", "url": ICABLE_REPORTS_INDEX_URL, "evidence": "公司官网年报/中报入口列示2023 Annual Report和2023 Interim Report。"},
    {"label": "i-CABLE Financial Calendar", "url": ICABLE_FINANCIAL_CALENDAR_URL, "evidence": "公司官网财务日历列示2023 Final Results Announcement日期为2024-03-22。"},
]

ICABLE_2025_H1_SOURCES = [
    {"label": "i-CABLE 2025 Interim Results Announcement - HKEX", "url": ICABLE_2025_INTERIM_RESULTS_URL, "evidence": "2025中期业绩公告披露H1 2025收入、经营亏损、期内亏损、分部表、资本开支、现金、总资产、可转债、借款和租赁负债。"},
    {"label": "i-CABLE 2025 Interim Report", "url": ICABLE_2025_INTERIM_REPORT_URL, "evidence": "2025中期报告损益表和现金流量表披露H1收入、服务成本明细、经营现金流和购买物业、厂房及设备付款。"},
    {"label": "i-CABLE Annual & Interim Reports index", "url": ICABLE_REPORTS_INDEX_URL, "evidence": "公司官网年报/中报入口列示2025 Interim Report。"},
    {"label": "i-CABLE 2025 Announcements index", "url": ICABLE_ANNOUNCEMENTS_2025_URL, "evidence": "公司官网公告入口用于交叉定位2025年中期业绩公告。"},
]

ICABLE_2025_H2_SOURCES = [
    {"label": "i-CABLE 2025 Interim Results Announcement - HKEX", "url": ICABLE_2025_INTERIM_RESULTS_URL, "evidence": "H1 2025累计值，用于从FY2025全年披露复算H2。"},
    {"label": "i-CABLE 2025 Final Results Announcement - HKEX", "url": ICABLE_2025_ANNUAL_RESULTS_URL, "evidence": "资产负债表披露2025年12月31日现金、总资产、可转债、计息借款和租赁负债。"},
    {"label": "i-CABLE 2025 Interim Report", "url": ICABLE_2025_INTERIM_REPORT_URL, "evidence": "2025中期报告披露H1服务成本明细、经营现金流和购买物业、厂房及设备付款，用于从全年复算H2。"},
    {"label": "i-CABLE 2025 Annual Report", "url": ICABLE_2025_ANNUAL_REPORT_URL, "evidence": "2025年报损益表和现金流量表披露FY2025收入、服务成本明细、经营现金流和购买物业、厂房及设备付款。"},
    {"label": "i-CABLE Annual & Interim Reports index", "url": ICABLE_REPORTS_INDEX_URL, "evidence": "公司官网年报/中报入口，列示2025年报和2025中期报告。"},
    {"label": "i-CABLE 2025 Announcements index", "url": ICABLE_ANNOUNCEMENTS_2025_URL, "evidence": "公司官网公告入口，用于交叉定位2025年官方公告。"},
]

ICABLE_2024_H1_COMPARATIVE_SOURCES = [
    {"label": "i-CABLE 2025 Interim Results Announcement - HKEX", "url": ICABLE_2025_INTERIM_RESULTS_URL, "evidence": "2025中期公告披露H1 2024比较栏，包含收入、经营亏损、期内亏损、分部扣除折旧摊销及减值前亏损和PPE additions。"},
    {"label": "i-CABLE 2024 Interim Results Announcement", "url": ICABLE_2024_INTERIM_RESULTS_URL, "evidence": "2024中期业绩公告披露H1 2024收入、经营亏损、资产负债表和PPE additions。"},
    {"label": "i-CABLE 2024 Interim Report", "url": ICABLE_2024_INTERIM_REPORT_URL, "evidence": "2024中期报告损益表、资产负债表和现金流量表披露H1收入、服务成本明细、现金、总资产、债务、经营现金流和PPE付款。"},
    {"label": "i-CABLE Annual & Interim Reports index", "url": ICABLE_REPORTS_INDEX_URL, "evidence": "公司官网年报/中报入口列示2025 Interim Report和2024 Interim Report，用于交叉定位官方中报。"},
    {"label": "i-CABLE 2024 Announcements index", "url": ICABLE_ANNOUNCEMENTS_2024_URL, "evidence": "公司官网2024公告入口列示2024 Interim Results Announcement，日期为2024-08-28。"},
    {"label": "i-CABLE 2025 Announcements index", "url": ICABLE_ANNOUNCEMENTS_2025_URL, "evidence": "公司官网公告入口用于交叉定位2025年中期业绩公告。"},
]

ICABLE_2024_H2_COMPARATIVE_SOURCES = [
    {"label": "i-CABLE 2025 Interim Results Announcement - HKEX", "url": ICABLE_2025_INTERIM_RESULTS_URL, "evidence": "H1 2024比较栏，用于从FY2024全年比较栏复算H2。"},
    {"label": "i-CABLE 2025 Final Results Announcement - HKEX", "url": ICABLE_2025_ANNUAL_RESULTS_URL, "evidence": "2025全年公告披露FY2024比较栏和2024年12月31日资产负债表比较数。"},
    {"label": "i-CABLE 2024 Interim Report", "url": ICABLE_2024_INTERIM_REPORT_URL, "evidence": "2024中期报告披露H1服务成本明细、经营现金流和购买物业、厂房及设备付款，用于从全年复算H2。"},
    {"label": "i-CABLE 2024 Annual Report", "url": ICABLE_2024_ANNUAL_REPORT_URL, "evidence": "2024年报损益表和现金流量表披露FY2024收入、服务成本明细、经营现金流和购买物业、厂房及设备付款。"},
    {"label": "i-CABLE 2025 Annual Report", "url": ICABLE_2025_ANNUAL_REPORT_URL, "evidence": "2025年报FY2024比较栏披露重列后的2024经营现金流和PPE付款，用于同口径复算H2 2024普通自由现金流。"},
    {"label": "i-CABLE Annual & Interim Reports index", "url": ICABLE_REPORTS_INDEX_URL, "evidence": "公司官网年报/中报入口列示2025年报、2025中报和2024年报/中报。"},
    {"label": "i-CABLE 2024 Announcements index", "url": ICABLE_ANNOUNCEMENTS_2024_URL, "evidence": "公司官网2024公告入口用于交叉定位2024年中期业绩公告。"},
    {"label": "i-CABLE 2025 Announcements index", "url": ICABLE_ANNOUNCEMENTS_2025_URL, "evidence": "公司官网公告入口用于交叉定位2025年官方公告。"},
]

ICABLE_2016_2020_SOURCES_BY_PERIOD = {
    "H1 2016": [
        {"label": "i-CABLE 2016 Interim Report - company site", "url": ICABLE_2016_INTERIM_REPORT_URL, "evidence": "2016中期报告损益表披露H1 2016收入和期内亏损。"},
        {"label": "i-CABLE Annual & Interim Reports index", "url": ICABLE_REPORTS_INDEX_URL, "evidence": "公司官网年报/中报入口列示2016 Interim Report和2016 Annual Report。"},
        {"label": "i-CABLE 2016 Annual Report - HKEX", "url": ICABLE_2016_ANNUAL_REPORT_HKEX_URL, "evidence": "HKEX披露2016年报，用于交叉定位同一报告年度。"},
    ],
    "H2 2016": [
        {"label": "i-CABLE 2016 Interim Report - company site", "url": ICABLE_2016_INTERIM_REPORT_URL, "evidence": "H1 2016累计值，用于从FY2016全年披露复算H2。"},
        {"label": "i-CABLE 2016 Annual Report - company site", "url": ICABLE_2016_ANNUAL_REPORT_URL, "evidence": "2016年报损益表披露FY2016收入和年度亏损。"},
        {"label": "i-CABLE 2016 Annual Report - HKEX", "url": ICABLE_2016_ANNUAL_REPORT_HKEX_URL, "evidence": "HKEX披露同一份2016年报，用于交叉核验。"},
        {"label": "i-CABLE Annual & Interim Reports index", "url": ICABLE_REPORTS_INDEX_URL, "evidence": "公司官网年报/中报入口用于定位2016报告。"},
    ],
    "H1 2017": [
        {"label": "i-CABLE 2017 Interim Report - company site", "url": ICABLE_2017_INTERIM_REPORT_URL, "evidence": "2017中期报告损益表披露H1 2017收入和期内亏损。"},
        {"label": "i-CABLE 2017 Interim Report - HKEX", "url": ICABLE_2017_INTERIM_REPORT_HKEX_URL, "evidence": "HKEX披露同一份2017中报，用于交叉核验。"},
        {"label": "i-CABLE Annual & Interim Reports index", "url": ICABLE_REPORTS_INDEX_URL, "evidence": "公司官网年报/中报入口用于定位2017中报。"},
    ],
    "H2 2017": [
        {"label": "i-CABLE 2017 Interim Report - company site", "url": ICABLE_2017_INTERIM_REPORT_URL, "evidence": "H1 2017累计值，用于从FY2017全年披露复算H2。"},
        {"label": "i-CABLE 2017 Annual Report - company site", "url": ICABLE_2017_ANNUAL_REPORT_URL, "evidence": "2017年报损益表披露FY2017收入和年度亏损。"},
        {"label": "i-CABLE 2017 Annual Report - HKEX", "url": ICABLE_2017_ANNUAL_REPORT_HKEX_URL, "evidence": "HKEX披露同一份2017年报，用于交叉核验。"},
    ],
    "H1 2018": [
        {"label": "i-CABLE 2018 Interim Report - company site", "url": ICABLE_2018_INTERIM_REPORT_URL, "evidence": "2018中期报告损益表披露H1 2018收入和期内亏损。"},
        {"label": "i-CABLE 2017 Annual Report - HKEX", "url": ICABLE_2017_ANNUAL_REPORT_HKEX_URL, "evidence": "HKEX披露前一年度年报，配合官网报告入口确认发行人和报告序列。"},
        {"label": "i-CABLE Annual & Interim Reports index", "url": ICABLE_REPORTS_INDEX_URL, "evidence": "公司官网年报/中报入口列示2018 Interim Report和2018 Annual Report。"},
    ],
    "H2 2018": [
        {"label": "i-CABLE 2018 Interim Report - company site", "url": ICABLE_2018_INTERIM_REPORT_URL, "evidence": "H1 2018累计值，用于从FY2018全年披露复算H2。"},
        {"label": "i-CABLE 2018 Annual Report - company site", "url": ICABLE_2018_ANNUAL_REPORT_URL, "evidence": "2018年报损益表披露FY2018收入和年度亏损。"},
        {"label": "i-CABLE Annual & Interim Reports index", "url": ICABLE_REPORTS_INDEX_URL, "evidence": "公司官网年报/中报入口用于定位2018报告。"},
    ],
    "H1 2019": [
        {"label": "i-CABLE 2019 Interim Report - company site", "url": ICABLE_2019_INTERIM_REPORT_URL, "evidence": "2019中期报告损益表披露H1 2019收入和期内亏损。"},
        {"label": "i-CABLE 2019 Annual Report - HKEX", "url": ICABLE_2019_ANNUAL_REPORT_HKEX_URL, "evidence": "HKEX披露2019年报，配合官网报告入口确认发行人和报告序列。"},
        {"label": "i-CABLE Annual & Interim Reports index", "url": ICABLE_REPORTS_INDEX_URL, "evidence": "公司官网年报/中报入口列示2019 Interim Report和2019 Annual Report。"},
    ],
    "H2 2019": [
        {"label": "i-CABLE 2019 Interim Report - company site", "url": ICABLE_2019_INTERIM_REPORT_URL, "evidence": "H1 2019累计值，用于从FY2019全年披露复算H2。"},
        {"label": "i-CABLE 2019 Annual Report - company site", "url": ICABLE_2019_ANNUAL_REPORT_URL, "evidence": "2019年报损益表披露FY2019收入和年度亏损。"},
        {"label": "i-CABLE 2019 Annual Report - HKEX", "url": ICABLE_2019_ANNUAL_REPORT_HKEX_URL, "evidence": "HKEX披露同一份2019年报，用于交叉核验。"},
    ],
    "H1 2020": [
        {"label": "i-CABLE 2020 Interim Report - company site", "url": ICABLE_2020_INTERIM_REPORT_URL, "evidence": "2020中期报告损益表披露H1 2020收入和期内亏损。"},
        {"label": "i-CABLE 2020 Interim Report - HKEX", "url": ICABLE_2020_INTERIM_REPORT_HKEX_URL, "evidence": "HKEX披露同一份2020中报，用于交叉核验。"},
        {"label": "i-CABLE Annual & Interim Reports index", "url": ICABLE_REPORTS_INDEX_URL, "evidence": "公司官网年报/中报入口用于定位2020中报。"},
    ],
    "H2 2020": [
        {"label": "i-CABLE 2020 Interim Report - company site", "url": ICABLE_2020_INTERIM_REPORT_URL, "evidence": "H1 2020累计值，用于从FY2020全年披露复算H2。"},
        {"label": "i-CABLE 2020 Annual Report - company site", "url": ICABLE_2020_ANNUAL_REPORT_OLD_URL, "evidence": "2020年报损益表披露FY2020收入和年度亏损。"},
        {"label": "i-CABLE 2020 Annual Report - HKEX", "url": ICABLE_2020_ANNUAL_REPORT_HKEX_URL, "evidence": "HKEX披露同一份2020年报，用于交叉核验。"},
    ],
}

ICABLE_2016_2020_METRICS = {
    "H1 2016": {
        "revenue": (709.876, "2016中期报告损益表披露H1 2016 Revenue 709.876百万港元。"),
        "net_income": (-134.782, "2016中期报告损益表披露H1 2016 Loss for the period 134.782百万港元，净利润口径记为负数。"),
    },
    "H2 2016": {
        "revenue": (696.492, "2016年报披露FY2016 Revenue 1,406.368百万港元，减H1 2016 Revenue 709.876百万港元，复算H2 2016为696.492百万港元。"),
        "net_income": (-178.008, "2016年报披露FY2016 Loss for the year 312.790百万港元，减H1 2016亏损134.782百万港元，复算H2 2016亏损178.008百万港元，净利润口径记为负数。"),
    },
    "H1 2017": {
        "revenue": (641.112, "2017中期报告损益表披露H1 2017 Revenue 641.112百万港元。"),
        "net_income": (-141.137, "2017中期报告损益表披露H1 2017 Loss for the period 141.137百万港元，净利润口径记为负数。"),
    },
    "H2 2017": {
        "revenue": (617.318, "2017年报披露FY2017 Revenue 1,258.430百万港元，减H1 2017 Revenue 641.112百万港元，复算H2 2017为617.318百万港元。"),
        "net_income": (-221.690, "2017年报披露FY2017 Loss for the year 362.827百万港元，减H1 2017亏损141.137百万港元，复算H2 2017亏损221.690百万港元，净利润口径记为负数。"),
    },
    "H1 2018": {
        "revenue": (587.468, "2018中期报告损益表披露H1 2018 Revenue 587.468百万港元。"),
        "net_income": (-253.563, "2018中期报告损益表披露H1 2018 Loss for the period 253.563百万港元，净利润口径记为负数。"),
    },
    "H2 2018": {
        "revenue": (575.842, "2018年报披露FY2018 Revenue 1,163.310百万港元，减H1 2018 Revenue 587.468百万港元，复算H2 2018为575.842百万港元。"),
        "net_income": (-202.025, "2018年报披露FY2018 Loss for the year 455.588百万港元，减H1 2018亏损253.563百万港元，复算H2 2018亏损202.025百万港元，净利润口径记为负数。"),
    },
    "H1 2019": {
        "revenue": (571.880, "2019中期报告损益表披露H1 2019 Revenue 571.880百万港元。"),
        "net_income": (-209.600, "2019中期报告损益表披露H1 2019 Loss for the period 209.600百万港元，净利润口径记为负数。"),
    },
    "H2 2019": {
        "revenue": (588.957, "2019年报披露FY2019 Revenue 1,160.837百万港元，减H1 2019 Revenue 571.880百万港元，复算H2 2019为588.957百万港元。"),
        "net_income": (-187.366, "2019年报披露FY2019 Loss for the year 396.966百万港元，减H1 2019亏损209.600百万港元，复算H2 2019亏损187.366百万港元，净利润口径记为负数。"),
    },
    "H1 2020": {
        "revenue": (524.893, "2020中期报告损益表披露H1 2020 Revenue 524.893百万港元。"),
        "net_income": (-176.223, "2020中期报告损益表披露H1 2020 Loss for the period 176.223百万港元，净利润口径记为负数。"),
    },
    "H2 2020": {
        "revenue": (544.084, "2020年报披露FY2020 Revenue 1,068.977百万港元，减H1 2020 Revenue 524.893百万港元，复算H2 2020为544.084百万港元。"),
        "net_income": (-99.164, "2020年报披露FY2020 Loss for the year 275.387百万港元，减H1 2020亏损176.223百万港元，复算H2 2020亏损99.164百万港元，净利润口径记为负数。"),
    },
}


def _official_record(
    subject: str,
    period: str,
    metric_key: str,
    official_value: float,
    unit: str,
    source_label: str,
    source_url: str,
    evidence: str,
    verification_method: str,
    verification_sources: list[dict[str, str]],
) -> dict[str, Any]:
    return {
        "subject": subject,
        "period": period,
        "metric_key": metric_key,
        "official_value": official_value,
        "unit": unit,
        "source_label": source_label,
        "source_url": source_url,
        "evidence": evidence,
        "verification_method": verification_method,
        "verification_sources": verification_sources,
    }


SMARTONE_2016_2021_OFFICIAL_VERIFICATIONS = [
    _official_record(
        "SmarTone",
        period,
        metric_key,
        value,
        "millions HKD",
        f"SmarTone official reports for {period}",
        SMARTONE_2016_2021_SOURCES_BY_PERIOD[period][0]["url"],
        evidence,
        "official_interim_or_annual_minus_interim_reconciliation",
        SMARTONE_2016_2021_SOURCES_BY_PERIOD[period],
    )
    for period, metrics in SMARTONE_2016_2021_METRICS.items()
    for metric_key, (value, evidence) in metrics.items()
]

HKBN_2016_2021_OFFICIAL_VERIFICATIONS = [
    _official_record(
        "HKBN",
        period,
        metric_key,
        value,
        "millions HKD",
        f"HKBN official reports for {period}",
        HKBN_2016_2021_SOURCES_BY_PERIOD[period][0]["url"],
        evidence,
        "official_interim_or_annual_minus_interim_reconciliation",
        HKBN_2016_2021_SOURCES_BY_PERIOD[period],
    )
    for period, metrics in HKBN_2016_2021_METRICS.items()
    for metric_key, (value, evidence) in metrics.items()
]

ICABLE_2016_2020_OFFICIAL_VERIFICATIONS = [
    _official_record(
        "i-CABLE",
        period,
        metric_key,
        value,
        "millions HKD",
        f"i-CABLE official reports for {period}",
        ICABLE_2016_2020_SOURCES_BY_PERIOD[period][0]["url"],
        evidence,
        "official_interim_or_annual_minus_interim_reconciliation",
        ICABLE_2016_2020_SOURCES_BY_PERIOD[period],
    )
    for period, metrics in ICABLE_2016_2020_METRICS.items()
    for metric_key, (value, evidence) in metrics.items()
]


HTHKH_2016_2020_OFFICIAL_VERIFICATIONS = [
    _official_record(
        "3HK / Hutchison",
        period,
        metric_key,
        value,
        "millions HKD",
        f"HTHKH official reports for {period}",
        HTHKH_2016_2020_SOURCES_BY_PERIOD[period][0]["url"],
        evidence,
        "official_interim_or_annual_minus_interim_reconciliation",
        HTHKH_2016_2020_SOURCES_BY_PERIOD[period],
    )
    for period, metrics in HTHKH_2016_2020_METRICS.items()
    for metric_key, (value, evidence) in metrics.items()
]


HTHKH_2021_2022_PERIOD_SOURCE = {
    "H1 2021": ("HTHKH 2021 Interim Report", HTHKH_2021_INTERIM_REPORT_URL, "official_interim_report_multi_section_check", HTHKH_2021_H1_SOURCES, "2021中期报告直接披露或同表复核"),
    "H2 2021": ("HTHKH 2021 Annual Report minus 2021 Interim Report", HTHKH_2021_ANNUAL_REPORT_URL, "official_full_year_minus_h1_reconciliation", HTHKH_2021_H2_SOURCES, "2021年报全年值减2021中期报告H1值复算H2"),
    "H1 2022": ("HTHKH 2022 Interim Report", HTHKH_2022_INTERIM_REPORT_URL, "official_interim_report_multi_section_check", HTHKH_2022_H1_SOURCES, "2022中期报告直接披露或同表复核"),
    "H2 2022": ("HTHKH 2022 Annual Report minus 2022 Interim Report", HTHKH_2022_ANNUAL_REPORT_URL, "official_full_year_minus_h1_reconciliation", HTHKH_2022_H2_SOURCES, "2022年报全年值减2022中期报告H1值复算H2"),
}

HTHKH_2021_2022_PERIOD_METRICS = {
    "H1 2021": {
        "revenue": (2565, "millions HKD", "Financial Highlights、MD&A和损益表均披露1H 2021 Revenue/Total revenue为2,565百万港元。"),
        "revenue_growth_yoy": (29.414, "percent", "1H 2021 Revenue 2,565对比1H 2020 Revenue 1,982，复算同比增长约29.414%；Financial Highlights列示约+29%。"),
        "gross_profit": (1437, "millions HKD", "MD&A披露1H 2021 Net customer service margin 1,413和Standalone handset sales margin 24，合计Total margin 1,437百万港元。"),
        "ebitda": (718, "millions HKD", "Supplementary Financial Information调节表披露1H 2021公司及子公司EBITDA为718百万港元；含合营公司份额的Total EBITDA为747百万港元。"),
        "operating_income": (86, "millions HKD", "Supplementary Financial Information调节表披露1H 2021公司及子公司EBIT为86百万港元；含合营公司份额的Total EBIT为92百万港元。"),
        "operating_margin": (3.353, "percent", "以1H 2021公司及子公司EBIT 86除以Revenue 2,565，复算经营利润率约3.353%。"),
        "net_income": (31, "millions HKD", "Financial Highlights和综合损益表均披露1H 2021 Profit attributable to shareholders为31百万港元。"),
        "operating_cash_flow": (1150, "millions HKD", "现金流量表披露1H 2021 Net cash from operating activities为1,150百万港元。"),
        "capital_expenditures": (-324, "millions HKD", "MD&A披露1H 2021 CAPEX excluding telecommunications licences为324百万港元；现金流量表Purchases of property, plant and equipment同为324百万港元，现金流出口径记为负数。"),
        "free_cash_flow": (826, "millions HKD", "1H 2021经营现金流1,150减购置固定资产324，复算自由现金流为826百万港元。"),
        "cash_and_equivalents": (5106, "millions HKD", "2021中报资产负债表和现金流量表均披露2021年6月30日Cash and cash equivalents为5,106百万港元。"),
        "total_assets": (14886, "millions HKD", "2021中报资产负债表披露非流动资产8,778、流动资产6,108，合计总资产14,886百万港元。"),
        "total_debt": (507, "millions HKD", "2021中报资产负债表披露流动租赁负债336、非流动租赁负债171，合计租赁债务507百万港元。"),
    },
    "H2 2021": {
        "revenue": (2820, "millions HKD", "2021年报披露全年Revenue 5,385；减2021中报1H Revenue 2,565，复算H2为2,820百万港元。"),
        "revenue_growth_yoy": (10.027, "percent", "2021 H2 Revenue 2,820；2020 H2由FY2020 4,545减1H 2020 1,982得2,563，复算同比增长约10.027%。"),
        "gross_profit": (1442, "millions HKD", "2021年报披露全年Total margin 2,879；减1H Total margin 1,437，复算H2 Total margin为1,442百万港元。"),
        "ebitda": (702, "millions HKD", "2021年报调节表披露全年公司及子公司EBITDA 1,420；减1H公司及子公司EBITDA 718，复算H2为702百万港元。"),
        "operating_income": (34, "millions HKD", "2021年报调节表披露全年公司及子公司EBIT 120；减1H公司及子公司EBIT 86，复算H2为34百万港元。"),
        "operating_margin": (1.206, "percent", "以H2公司及子公司EBIT 34除以H2 Revenue 2,820，复算经营利润率约1.206%。"),
        "net_income": (-27, "millions HKD", "2021年报披露全年Profit attributable to shareholders 4；减1H利润31，复算H2股东应占亏损27百万港元。"),
        "operating_cash_flow": (2226, "millions HKD", "2021年报现金流量表披露全年Net cash from operating activities 3,376；减1H 1,150，复算H2为2,226百万港元。"),
        "capital_expenditures": (-550, "millions HKD", "2021年报披露全年CAPEX excluding telecommunications licences为874；减1H 324，复算H2资本开支550百万港元，现金流出口径记为负数。"),
        "free_cash_flow": (1676, "millions HKD", "H2经营现金流2,226减H2购置固定资产550，复算自由现金流为1,676百万港元。"),
        "cash_and_equivalents": (1414, "millions HKD", "2021年报资产负债表和现金流量表均披露2021年12月31日Cash and cash equivalents为1,414百万港元。"),
        "total_assets": (15446, "millions HKD", "2021年报资产负债表披露非流动资产10,469、流动资产4,977，合计总资产15,446百万港元。"),
        "total_debt": (417, "millions HKD", "2021年报资产负债表披露流动租赁负债289、非流动租赁负债128，合计租赁债务417百万港元。"),
    },
    "H1 2022": {
        "revenue": (2298, "millions HKD", "Financial Highlights、MD&A和损益表均披露1H 2022 Revenue/Total revenue为2,298百万港元。"),
        "revenue_growth_yoy": (-10.409, "percent", "1H 2022 Revenue 2,298对比1H 2021 Revenue 2,565，复算同比下降约10.409%；Financial Highlights列示约-10%。"),
        "gross_profit": (1390, "millions HKD", "MD&A披露1H 2022 Net customer service margin 1,373和Standalone hardware/product sales margin 17，合计Total margin 1,390百万港元。"),
        "ebitda": (667, "millions HKD", "Supplementary Financial Information调节表披露1H 2022公司及子公司EBITDA为667百万港元；含合营公司份额的Total EBITDA为695百万港元。"),
        "operating_income": (-48, "millions HKD", "Supplementary Financial Information调节表披露1H 2022公司及子公司LBIT为48百万港元亏损；含合营公司份额的Total LBIT为43百万港元。"),
        "operating_margin": (-2.089, "percent", "以1H 2022公司及子公司LBIT -48除以Revenue 2,298，复算经营利润率约-2.089%。"),
        "net_income": (-96, "millions HKD", "Financial Highlights和综合损益表均披露1H 2022 Loss attributable to shareholders为96百万港元。"),
        "operating_cash_flow": (549, "millions HKD", "现金流量表披露1H 2022 Net cash from operating activities为549百万港元。"),
        "capital_expenditures": (-157, "millions HKD", "MD&A披露1H 2022 CAPEX excluding telecommunications licences为157百万港元；现金流量表Purchases of property, plant and equipment同为157百万港元，现金流出口径记为负数。"),
        "free_cash_flow": (392, "millions HKD", "1H 2022经营现金流549减购置固定资产157，复算自由现金流为392百万港元。"),
        "cash_and_equivalents": (560, "millions HKD", "2022中报资产负债表和现金流量表均披露2022年6月30日Cash and cash equivalents为560百万港元。"),
        "total_assets": (15131, "millions HKD", "2022中报资产负债表披露非流动资产10,331、流动资产4,800，合计总资产15,131百万港元。"),
        "total_debt": (460, "millions HKD", "2022中报资产负债表披露流动租赁负债310、非流动租赁负债150，合计租赁债务460百万港元。"),
    },
    "H2 2022": {
        "revenue": (2584, "millions HKD", "2022年报披露全年Revenue 4,882；减2022中报1H Revenue 2,298，复算H2为2,584百万港元。"),
        "revenue_growth_yoy": (-8.369, "percent", "2022 H2 Revenue 2,584；2021 H2 Revenue 2,820，复算同比下降约8.369%。"),
        "gross_profit": (1470, "millions HKD", "2022年报披露全年Total margin 2,860；减1H Total margin 1,390，复算H2 Total margin为1,470百万港元。"),
        "ebitda": (695, "millions HKD", "2022年报调节表披露全年公司及子公司EBITDA 1,362；减1H公司及子公司EBITDA 667，复算H2为695百万港元。"),
        "operating_income": (-46, "millions HKD", "2022年报调节表披露全年公司及子公司LBIT 94；减1H公司及子公司LBIT 48，复算H2经营亏损46百万港元。"),
        "operating_margin": (-1.780, "percent", "以H2公司及子公司LBIT -46除以H2 Revenue 2,584，复算经营利润率约-1.780%。"),
        "net_income": (-62, "millions HKD", "2022年报披露全年Loss attributable to shareholders 158；减1H亏损96，复算H2股东应占亏损62百万港元。"),
        "operating_cash_flow": (580, "millions HKD", "2022年报现金流量表披露全年Net cash from operating activities 1,129；减1H 549，复算H2为580百万港元。"),
        "capital_expenditures": (-339, "millions HKD", "2022年报披露全年CAPEX excluding telecommunications licences为496；减1H 157，复算H2资本开支339百万港元，现金流出口径记为负数。"),
        "free_cash_flow": (241, "millions HKD", "H2经营现金流580减H2购置固定资产339，复算自由现金流为241百万港元。"),
        "cash_and_equivalents": (3087, "millions HKD", "2022年报资产负债表和现金流量表均披露2022年12月31日Cash and cash equivalents为3,087百万港元。"),
        "total_assets": (14956, "millions HKD", "2022年报资产负债表披露非流动资产10,179、流动资产4,777，合计总资产14,956百万港元。"),
        "total_debt": (456, "millions HKD", "2022年报资产负债表披露流动租赁负债305、非流动租赁负债151，合计租赁债务456百万港元。"),
    },
}

HTHKH_2021_2022_OFFICIAL_VERIFICATIONS = [
    _official_record(
        "3HK / Hutchison",
        period,
        metric_key,
        value,
        unit,
        HTHKH_2021_2022_PERIOD_SOURCE[period][0],
        HTHKH_2021_2022_PERIOD_SOURCE[period][1],
        f"{HTHKH_2021_2022_PERIOD_SOURCE[period][4]}：{evidence}",
        HTHKH_2021_2022_PERIOD_SOURCE[period][2],
        HTHKH_2021_2022_PERIOD_SOURCE[period][3],
    )
    for period, metrics in HTHKH_2021_2022_PERIOD_METRICS.items()
    for metric_key, (value, unit, evidence) in metrics.items()
]


CM_QUARTERLY_METRIC_EVIDENCE = {
    "operating_revenue": "官网单季度经营数据列示{period_label} Operating Revenue 为人民币 {display_value} 十亿元。",
    "revenue": "中国移动总收入采用 Operating Revenue 口径；官网单季度经营数据列示{period_label} Operating Revenue 为人民币 {display_value} 十亿元。",
    "service_revenue": "官网单季度经营数据列示{period_label} Revenue from Telecommunications Services 为人民币 {display_value} 十亿元。",
    "ebitda": "官网单季度经营数据列示{period_label} EBITDA 为人民币 {display_value} 十亿元。",
    "ebitda_margin": "EBITDA margin 按中国移动年报定义由 EBITDA / operating revenue 复算；{period_label}为 {display_value}%。",
    "net_income": "官网单季度经营数据列示{period_label} Profit Attributable to Equity Shareholders 为人民币 {display_value} 十亿元。",
}

CM_2020_CORE_METRICS = {
    "Q1 2020": {
        "operating_revenue": 181300,
        "revenue": 181300,
        "service_revenue": 168900,
        "ebitda": 68500,
        "ebitda_margin": 37.783,
        "net_income": 23500,
    },
    "Q2 2020": {
        "operating_revenue": 208600,
        "revenue": 208600,
        "service_revenue": 189300,
        "ebitda": 77200,
        "ebitda_margin": 37.009,
        "net_income": 32300,
    },
    "Q3 2020": {
        "operating_revenue": 184500,
        "revenue": 184500,
        "service_revenue": 167500,
        "ebitda": 71200,
        "ebitda_margin": 38.591,
        "net_income": 25800,
    },
    "Q4 2020": {
        "operating_revenue": 193700,
        "revenue": 193700,
        "service_revenue": 170000,
        "ebitda": 68200,
        "ebitda_margin": 35.209,
        "net_income": 26200,
    },
}

CM_2020_CORE_SOURCE_BY_PERIOD = {
    "Q1 2020": ("中国移动官网2020单季度经营数据", CM_2020_OPERATION_URL, CM_2020_Q1_SOURCES, "官网直接披露2020/1Q核心经营数据；EBITDA margin 由EBITDA除以Operating Revenue复算。"),
    "Q2 2020": ("中国移动官网2020单季度经营数据", CM_2020_OPERATION_URL, CM_2020_Q2_SOURCES, "官网直接披露2020/2Q核心经营数据；EBITDA margin 由EBITDA除以Operating Revenue复算。"),
    "Q3 2020": ("中国移动官网2020单季度经营数据", CM_2020_OPERATION_URL, CM_2020_Q3_SOURCES, "官网直接披露2020/3Q核心经营数据；EBITDA margin 由EBITDA除以Operating Revenue复算。"),
    "Q4 2020": ("中国移动官网2020单季度经营数据", CM_2020_OPERATION_URL, CM_2020_Q4_SOURCES, "官网直接披露2020/4Q核心经营数据；EBITDA margin 由EBITDA除以Operating Revenue复算。"),
}

CM_2020_CORE_OFFICIAL_VERIFICATIONS = [
    _official_record(
        "中国移动",
        period,
        metric_key,
        value,
        "percent" if metric_key == "ebitda_margin" else "millions CNY",
        CM_2020_CORE_SOURCE_BY_PERIOD[period][0],
        CM_2020_CORE_SOURCE_BY_PERIOD[period][1],
        f"{CM_2020_CORE_SOURCE_BY_PERIOD[period][3]}官方值：{metric_key}={value}{'%' if metric_key == 'ebitda_margin' else '百万元'}。",
        "official_quarterly_operating_data_with_interim_9m_fy_reconciliation",
        CM_2020_CORE_SOURCE_BY_PERIOD[period][2],
    )
    for period, metrics in CM_2020_CORE_METRICS.items()
    for metric_key, value in metrics.items()
]

CM_2019_CORE_METRICS = {
    "Q1 2019": {
        "operating_revenue": 185000,
        "revenue": 185000,
        "service_revenue": 165900,
        "ebitda": 72700,
        "ebitda_margin": 39.297,
        "net_income": 23700,
    },
    "Q2 2019": {
        "operating_revenue": 204400,
        "revenue": 204400,
        "service_revenue": 185500,
        "ebitda": 78400,
        "ebitda_margin": 38.356,
        "net_income": 32400,
    },
    "Q3 2019": {
        "operating_revenue": 177300,
        "revenue": 177300,
        "service_revenue": 161600,
        "ebitda": 74400,
        "ebitda_margin": 41.963,
        "net_income": 25700,
    },
    "Q4 2019": {
        "operating_revenue": 179200,
        "revenue": 179200,
        "service_revenue": 161400,
        "ebitda": 70500,
        "ebitda_margin": 39.342,
        "net_income": 24800,
    },
}

CM_2019_CORE_SOURCE_BY_PERIOD = {
    "Q1 2019": ("中国移动官网2019单季度经营数据", CM_2019_OPERATION_URL, CM_2019_Q1_SOURCES, "官网直接披露2019/1Q核心经营数据；EBITDA margin 由EBITDA除以Operating Revenue复算。"),
    "Q2 2019": ("中国移动官网2019单季度经营数据", CM_2019_OPERATION_URL, CM_2019_Q2_SOURCES, "官网直接披露2019/2Q核心经营数据；EBITDA margin 由EBITDA除以Operating Revenue复算。"),
    "Q3 2019": ("中国移动官网2019单季度经营数据", CM_2019_OPERATION_URL, CM_2019_Q3_SOURCES, "官网直接披露2019/3Q核心经营数据；EBITDA margin 由EBITDA除以Operating Revenue复算。"),
    "Q4 2019": ("中国移动官网2019单季度经营数据", CM_2019_OPERATION_URL, CM_2019_Q4_SOURCES, "官网直接披露2019/4Q核心经营数据；EBITDA margin 由EBITDA除以Operating Revenue复算。"),
}

CM_2019_CORE_OFFICIAL_VERIFICATIONS = [
    _official_record(
        "中国移动",
        period,
        metric_key,
        value,
        "percent" if metric_key == "ebitda_margin" else "millions CNY",
        CM_2019_CORE_SOURCE_BY_PERIOD[period][0],
        CM_2019_CORE_SOURCE_BY_PERIOD[period][1],
        f"{CM_2019_CORE_SOURCE_BY_PERIOD[period][3]}官方值：{metric_key}={value}{'%' if metric_key == 'ebitda_margin' else '百万元'}。",
        "official_quarterly_operating_data_with_interim_9m_fy_reconciliation",
        CM_2019_CORE_SOURCE_BY_PERIOD[period][2],
    )
    for period, metrics in CM_2019_CORE_METRICS.items()
    for metric_key, value in metrics.items()
]

CM_2022_CORE_METRICS = {
    "Q1 2022": {
        "operating_revenue": 227300,
        "revenue": 227300,
        "ebitda": 76100,
        "net_income": 25600,
    },
    "Q2 2022": {
        "operating_revenue": 269634,
        "revenue": 269634,
        "ebitda": 97812,
        "net_income": 44675,
    },
    "Q3 2022": {
        "operating_revenue": 226566,
        "revenue": 226566,
        "ebitda": 77588,
        "net_income": 28225,
    },
    "Q4 2022": {
        "operating_revenue": 213759,
        "revenue": 213759,
        "ebitda": 77676,
        "net_income": 26959,
    },
}

CM_2022_CORE_SOURCE_BY_PERIOD = {
    "Q1 2022": ("中国移动2022年第一季度业绩公告", CM_2022_Q1_IRASIA_URL, CM_2022_Q1_SOURCES, "一季报直接披露Q1核心经营数据。"),
    "Q2 2022": ("中国移动2022中期报告减一季度业绩", CM_2022_INTERIM_REPORT_URL, CM_2022_Q2_SOURCES, "中期报告H1累计值减一季报Q1累计值复算Q2核心经营数据。"),
    "Q3 2022": ("中国移动2022前三季度业绩减中期报告", CM_2022_Q3_IRASIA_URL, CM_2022_Q3_SOURCES, "前三季度9M累计值减中期报告H1累计值复算Q3核心经营数据。"),
    "Q4 2022": ("中国移动2022年报减前三季度业绩", CM_2022_ANNUAL_REPORT_URL, CM_2022_Q4_SOURCES, "年报FY累计值减前三季度9M累计值复算Q4核心经营数据。"),
}

CM_2022_CORE_OFFICIAL_VERIFICATIONS = [
    _official_record(
        "中国移动",
        period,
        metric_key,
        value,
        "millions CNY",
        CM_2022_CORE_SOURCE_BY_PERIOD[period][0],
        CM_2022_CORE_SOURCE_BY_PERIOD[period][1],
        f"{CM_2022_CORE_SOURCE_BY_PERIOD[period][3]}官方值：{metric_key}={value}百万元。",
        "official_quarterly_operating_data_with_interim_9m_fy_reconciliation",
        CM_2022_CORE_SOURCE_BY_PERIOD[period][2],
    )
    for period, metrics in CM_2022_CORE_METRICS.items()
    for metric_key, value in metrics.items()
]

CM_2022_DETAIL_PERIOD_SOURCE = {
    "Q1 2022": ("中国移动2022年第一季度报告", CM_2022_Q1_SINA_URL, "official_quarterly_statement_check", CM_2022_Q1_DETAIL_SOURCES),
    "Q2 2022": ("中国移动2022年半年度报告", CM_2022_H1_SINA_URL, "official_h1_minus_q1_reconciliation", CM_2022_Q2_DETAIL_SOURCES),
    "Q3 2022": ("中国移动2022年第三季度报告", CM_2022_Q3_SINA_URL, "official_9m_minus_h1_reconciliation", CM_2022_Q3_DETAIL_SOURCES),
    "Q4 2022": ("中国移动2022年年度报告", CM_2022_ANNUAL_SINA_URL, "official_fy_minus_9m_reconciliation", CM_2022_Q4_DETAIL_SOURCES),
}

CM_2022_DETAIL_METRICS = {
    "Q1 2022": {
        "capital_expenditures": (-40864, "millions CNY", "A股一季报现金流量表披露购建固定资产、无形资产和其他长期资产支付的现金40,864百万元，现金流出口径记为负数。"),
        "cash_and_equivalents": (283114, "millions CNY", "A股一季报现金流量表披露2022年3月31日期末现金及现金等价物余额283,114百万元。"),
        "ebitda_margin": (33.477, "percent", "2022 Q1官方EBITDA 76,100百万元除以营业收入227,320百万元，复算EBITDA率为33.477%。"),
        "free_cash_flow": (36906, "millions CNY", "Q1经营现金流77,770百万元减购建长期资产现金支出40,864百万元，复算普通自由现金流为36,906百万元。"),
        "gross_margin": (24.031, "percent", "A股一季报披露营业收入227,320百万元、营业成本172,693百万元，复算毛利54,627百万元、毛利率24.031%。"),
        "gross_profit": (54627, "millions CNY", "A股一季报披露营业收入227,320百万元、营业成本172,693百万元，复算毛利为54,627百万元。"),
        "operating_cash_flow": (77770, "millions CNY", "A股一季报现金流量表披露经营活动产生的现金流量净额77,770百万元。"),
        "operating_income": (33477, "millions CNY", "A股一季报利润表披露营业利润33,477百万元。"),
        "operating_margin": (14.727, "percent", "A股一季报营业利润33,477百万元除以营业收入227,320百万元，复算经营利润率为14.727%。"),
        "revenue_growth_yoy": (14.560, "percent", "A股一季报披露2022 Q1营业收入227,320百万元、2021 Q1营业收入198,429百万元，复算同比增长14.560%；公告摘要列示同比增长14.6%。"),
        "total_assets": (1845500, "millions CNY", "A股一季报资产负债表披露2022年3月31日资产总计1,845,500百万元。"),
        "total_debt": (61117, "millions CNY", "A股一季报资产负债表披露一年内到期的非流动负债28,444百万元、租赁负债32,673百万元，合计债务61,117百万元。"),
    },
    "Q2 2022": {
        "capital_expenditures": (-48858, "millions CNY", "A股半年报现金流量表披露H1购建长期资产现金支出89,722百万元；扣除Q1 40,864百万元后，Q2为48,858百万元，现金流出口径记为负数。"),
        "cash_and_equivalents": (272350, "millions CNY", "A股半年报现金流量表披露2022年6月30日期末现金及现金等价物余额272,350百万元。"),
        "ebitda_margin": (36.279, "percent", "Q2官方EBITDA 97,812百万元除以Q2营业收入269,614百万元，复算EBITDA率为36.279%。"),
        "free_cash_flow": (20644, "millions CNY", "Q2经营现金流69,502百万元减购建长期资产现金支出48,858百万元，复算普通自由现金流为20,644百万元。"),
        "gross_margin": (32.425, "percent", "H1营业收入496,934百万元、营业成本354,886百万元扣除Q1营业收入227,320百万元、营业成本172,693百万元后，复算Q2毛利87,421百万元、毛利率32.425%。"),
        "gross_profit": (87421, "millions CNY", "H1毛利142,048百万元扣除Q1毛利54,627百万元，复算Q2毛利为87,421百万元。"),
        "operating_cash_flow": (69502, "millions CNY", "A股半年报现金流量表披露H1经营现金流147,272百万元；扣除Q1 77,770百万元后，Q2为69,502百万元。"),
        "operating_income": (57433, "millions CNY", "A股半年报利润表披露H1营业利润90,910百万元；扣除Q1 33,477百万元后，Q2营业利润为57,433百万元。"),
        "operating_margin": (21.302, "percent", "Q2营业利润57,433百万元除以Q2营业收入269,614百万元，复算经营利润率为21.302%。"),
        "revenue_growth_yoy": (9.949, "percent", "H1 2022营业收入496,934百万元扣除Q1 2022的227,320百万元得Q2 269,614百万元；H1 2021营业收入443,647百万元扣除Q1 2021的198,429百万元得Q2 245,218百万元，复算同比增长9.949%。"),
        "total_assets": (1875081, "millions CNY", "A股半年报资产负债表披露2022年6月30日资产总计1,875,081百万元。"),
        "total_debt": (60479, "millions CNY", "A股半年报资产负债表披露一年内到期的非流动负债24,988百万元、租赁负债35,491百万元，合计债务60,479百万元。"),
    },
    "Q3 2022": {
        "capital_expenditures": (-46871, "millions CNY", "A股三季报现金流量表披露9M购建长期资产现金支出136,593百万元；扣除H1 89,722百万元后，Q3为46,871百万元，现金流出口径记为负数。"),
        "cash_and_equivalents": (205294, "millions CNY", "A股三季报现金流量表披露2022年9月30日期末现金及现金等价物余额205,294百万元。"),
        "ebitda_margin": (34.247, "percent", "Q3官方EBITDA 77,588百万元除以Q3营业收入226,553百万元，复算EBITDA率为34.247%。"),
        "free_cash_flow": (33449, "millions CNY", "Q3经营现金流80,320百万元减购建长期资产现金支出46,871百万元，复算普通自由现金流为33,449百万元。"),
        "gross_margin": (25.879, "percent", "9M营业收入723,487百万元、营业成本522,810百万元扣除H1营业收入496,934百万元、营业成本354,886百万元后，复算Q3毛利58,629百万元、毛利率25.879%。"),
        "gross_profit": (58629, "millions CNY", "9M毛利200,677百万元扣除H1毛利142,048百万元，复算Q3毛利为58,629百万元。"),
        "operating_cash_flow": (80320, "millions CNY", "A股三季报现金流量表披露9M经营现金流227,592百万元；扣除H1 147,272百万元后，Q3为80,320百万元。"),
        "operating_income": (36142, "millions CNY", "A股三季报利润表披露9M营业利润127,052百万元；扣除H1 90,910百万元后，Q3营业利润为36,142百万元。"),
        "operating_margin": (15.953, "percent", "Q3营业利润36,142百万元除以Q3营业收入226,553百万元，复算经营利润率为15.953%。"),
        "revenue_growth_yoy": (10.523, "percent", "9M 2022营业收入723,487百万元扣除H1 2022的496,934百万元得Q3 226,553百万元；9M 2021营业收入648,630百万元扣除H1 2021的443,647百万元得Q3 204,983百万元，复算同比增长10.523%。"),
        "total_assets": (1858447, "millions CNY", "A股三季报资产负债表披露2022年9月30日资产总计1,858,447百万元。"),
        "total_debt": (58998, "millions CNY", "A股三季报资产负债表披露一年内到期的非流动负债22,118百万元、租赁负债36,880百万元，合计债务58,998百万元。"),
    },
    "Q4 2022": {
        "capital_expenditures": (-52995, "millions CNY", "A股年报现金流量表披露全年购建长期资产现金支出189,588百万元；扣除9M 136,593百万元后，Q4为52,995百万元，现金流出口径记为负数。"),
        "cash_and_equivalents": (167106, "millions CNY", "A股年报现金流量表披露2022年12月31日年末现金及现金等价物余额167,106百万元。"),
        "ebitda_margin": (36.336, "percent", "Q4官方EBITDA 77,676百万元除以Q4营业收入213,772百万元，复算EBITDA率为36.336%。"),
        "free_cash_flow": (163, "millions CNY", "Q4经营现金流53,158百万元减购建长期资产现金支出52,995百万元，复算普通自由现金流为163百万元。"),
        "gross_margin": (27.936, "percent", "全年营业收入937,259百万元、营业成本676,863百万元扣除9M营业收入723,487百万元、营业成本522,810百万元后，复算Q4毛利59,719百万元、毛利率27.936%。"),
        "gross_profit": (59719, "millions CNY", "全年毛利260,396百万元扣除9M毛利200,677百万元，复算Q4毛利为59,719百万元。"),
        "operating_cash_flow": (53158, "millions CNY", "A股年报现金流量表披露全年经营现金流280,750百万元；扣除9M 227,592百万元后，Q4为53,158百万元。"),
        "operating_income": (34254, "millions CNY", "A股年报利润表披露全年营业利润161,306百万元；扣除9M 127,052百万元后，Q4营业利润为34,254百万元。"),
        "operating_margin": (16.024, "percent", "Q4营业利润34,254百万元除以Q4营业收入213,772百万元，复算经营利润率为16.024%。"),
        "revenue_growth_yoy": (7.085, "percent", "全年2022营业收入937,259百万元扣除9M 2022的723,487百万元得Q4 213,772百万元；全年2021营业收入848,258百万元扣除9M 2021的648,630百万元得Q4 199,628百万元，复算同比增长7.085%。"),
        "total_assets": (1900238, "millions CNY", "A股年报资产负债表披露2022年12月31日资产总计1,900,238百万元。"),
        "total_debt": (112660, "millions CNY", "A股年报资产负债表披露一年内到期的非流动负债30,919百万元、租赁负债81,741百万元，合计债务112,660百万元。"),
    },
}

CM_2022_DETAIL_OFFICIAL_VERIFICATIONS = [
    _official_record(
        "中国移动",
        period,
        metric_key,
        value,
        unit,
        CM_2022_DETAIL_PERIOD_SOURCE[period][0],
        CM_2022_DETAIL_PERIOD_SOURCE[period][1],
        evidence,
        CM_2022_DETAIL_PERIOD_SOURCE[period][2],
        CM_2022_DETAIL_PERIOD_SOURCE[period][3],
    )
    for period, metrics in CM_2022_DETAIL_METRICS.items()
    for metric_key, (value, unit, evidence) in metrics.items()
]

CM_2021_DETAIL_PERIOD_SOURCE = {
    "Q1 2021": ("中国移动2022一季报比较栏", CM_2022_Q1_CNINFO_URL, "official_prior_period_comparative_quarter_check", CM_2021_Q1_DETAIL_SOURCES),
    "Q2 2021": ("中国移动2021中期及2022比较栏复算", CM_2022_H1_SINA_URL, "official_h1_minus_q1_reconciliation", CM_2021_Q2_DETAIL_SOURCES),
    "Q3 2021": ("中国移动2022三季报比较栏减2021中期", CM_2022_Q3_SINA_URL, "official_9m_minus_h1_reconciliation", CM_2021_Q3_DETAIL_SOURCES),
    "Q4 2021": ("中国移动2022年报比较栏减2022三季报比较栏", CM_2022_ANNUAL_SINA_URL, "official_fy_minus_9m_reconciliation", CM_2021_Q4_DETAIL_SOURCES),
}

CM_2021_DETAIL_METRICS = {
    "Q1 2021": {
        "capital_expenditures": (-33755, "millions CNY", "A股2022年一季报比较栏披露2021Q1购建长期资产现金支出33,755百万元，现金流出口径记为负数。"),
        "ebitda": (72100, "millions CNY", "A股2022年一季报主要财务指标比较栏披露2021Q1 EBITDA 721亿元，即72,100百万元。"),
        "ebitda_margin": (36.335, "percent", "Q1 EBITDA 72,100百万元除以Q1营业收入198,429百万元，复算EBITDA率为36.335%，与公告36.3%四舍五入一致。"),
        "free_cash_flow": (42517, "millions CNY", "Q1经营现金流76,272百万元减购建长期资产现金支出33,755百万元，复算普通自由现金流为42,517百万元。"),
        "gross_margin": (25.918, "percent", "Q1毛利51,429百万元除以营业收入198,429百万元，复算毛利率为25.918%。"),
        "gross_profit": (51429, "millions CNY", "A股2022年一季报比较栏披露2021Q1营业收入198,429百万元、营业成本147,000百万元，复算毛利51,429百万元。"),
        "net_income": (24056, "millions CNY", "A股2022年一季报比较栏披露2021Q1归属于母公司股东的净利润24,056百万元；H股中报H1归母利润59,118百万元与Q2拆分值交叉核验。"),
        "operating_cash_flow": (76272, "millions CNY", "A股2022年一季报比较栏披露2021Q1经营活动产生的现金流量净额76,272百万元。"),
        "operating_income": (31252, "millions CNY", "A股2022年一季报比较栏披露2021Q1营业利润31,252百万元。"),
        "operating_margin": (15.750, "percent", "Q1营业利润31,252百万元除以Q1营业收入198,429百万元，复算经营利润率为15.750%。"),
        "operating_revenue": (198429, "millions CNY", "A股2022年一季报比较栏披露2021Q1营业收入198,429百万元。"),
        "revenue": (198429, "millions CNY", "中国移动总收入采用营业收入/Operating revenue口径；A股2022年一季报比较栏披露2021Q1营业收入198,429百万元。"),
        "revenue_growth_yoy": (9.5, "percent", "A股2022年一季报比较栏披露2021Q1营业收入198,429百万元；2020Q1公告披露Operating revenue 181.3十亿元，按披露口径同比约9.5%。"),
    },
    "Q2 2021": {
        "capital_expenditures": (-53820, "millions CNY", "A股半年报比较栏H1 2021购建长期资产现金支出87,575百万元，扣除Q1 2021的33,755百万元后，Q2为53,820百万元，现金流出口径记为负数。"),
        "cash_and_equivalents": (274143, "millions CNY", "A股半年报及H股中期报告披露2021年6月30日期末现金及现金等价物274,143百万元。"),
        "ebitda": (89888, "millions CNY", "H股中期报告披露H1 2021 EBITDA 161,988百万元；扣除Q1 2021 EBITDA 72,100百万元后，Q2为89,888百万元。"),
        "ebitda_margin": (36.656, "percent", "Q2 EBITDA 89,888百万元除以Q2营业收入245,218百万元，复算EBITDA率为36.656%。"),
        "free_cash_flow": (31526, "millions CNY", "Q2经营现金流85,346百万元减购建长期资产现金支出53,820百万元，复算普通自由现金流为31,526百万元。"),
        "gross_margin": (32.249, "percent", "H1毛利130,509百万元扣除Q1毛利51,429百万元，复算Q2毛利79,080百万元、毛利率32.249%。"),
        "gross_profit": (79080, "millions CNY", "H1营业收入443,647百万元、营业成本313,138百万元扣除Q1营业收入198,429百万元、营业成本147,000百万元后，复算Q2毛利79,080百万元。"),
        "net_income": (35062, "millions CNY", "H1 2021归母净利润59,118百万元扣除Q1 2021归母净利润24,056百万元，Q2为35,062百万元。"),
        "operating_cash_flow": (85346, "millions CNY", "A股半年报比较栏H1 2021经营现金流161,618百万元；扣除Q1 2021的76,272百万元后，Q2为85,346百万元。"),
        "operating_income": (46184, "millions CNY", "A股半年报比较栏H1 2021营业利润77,436百万元；扣除Q1 2021的31,252百万元后，Q2营业利润为46,184百万元。"),
        "operating_margin": (18.834, "percent", "Q2营业利润46,184百万元除以Q2营业收入245,218百万元，复算经营利润率为18.834%。"),
        "operating_revenue": (245218, "millions CNY", "H1 2021营业收入443,647百万元扣除Q1 2021营业收入198,429百万元后，Q2营业收入为245,218百万元。"),
        "revenue": (245218, "millions CNY", "中国移动总收入采用营业收入/Operating revenue口径；H1 2021扣除Q1 2021复算Q2为245,218百万元。"),
        "revenue_growth_yoy": (17.575, "percent", "2021Q2营业收入245,218百万元；2020H1营业收入389,863百万元减2020Q1营业收入181.3十亿元，复算2020Q2约208,563百万元，Q2同比约17.575%。"),
        "total_assets": (1800453, "millions CNY", "A股半年报及H股中期报告披露2021年6月30日资产总计1,800,453百万元。"),
        "total_debt": (63149, "millions CNY", "H股中期报告披露2021年6月30日流动租赁负债25,621百万元、非流动租赁负债37,528百万元，合计63,149百万元。"),
    },
    "Q3 2021": {
        "capital_expenditures": (-42224, "millions CNY", "A股三季报比较栏9M 2021购建长期资产现金支出129,799百万元，扣除H1 2021的87,575百万元后，Q3为42,224百万元，现金流出口径记为负数。"),
        "cash_and_equivalents": (251494, "millions CNY", "A股三季报比较栏现金流量表披露2021年9月30日期末现金及现金等价物251,494百万元。"),
        "ebitda": (75512, "millions CNY", "A股三季报比较栏披露9M 2021 EBITDA 237,500百万元；扣除H1 2021 EBITDA 161,988百万元后，Q3为75,512百万元。"),
        "ebitda_margin": (36.838, "percent", "Q3 EBITDA 75,512百万元除以Q3营业收入204,983百万元，复算EBITDA率为36.838%。"),
        "free_cash_flow": (45274, "millions CNY", "Q3经营现金流87,498百万元减购建长期资产现金支出42,224百万元，复算普通自由现金流为45,274百万元。"),
        "gross_margin": (27.694, "percent", "9M毛利187,277百万元扣除H1毛利130,509百万元，复算Q3毛利56,768百万元、毛利率27.694%。"),
        "gross_profit": (56768, "millions CNY", "9M营业收入648,630百万元、营业成本461,353百万元扣除H1营业收入443,647百万元、营业成本313,138百万元后，复算Q3毛利56,768百万元。"),
        "net_income": (27844, "millions CNY", "A股三季报比较栏9M 2021归母净利润86,962百万元，扣除H1 2021归母净利润59,118百万元后，Q3为27,844百万元。"),
        "operating_cash_flow": (87498, "millions CNY", "A股三季报比较栏9M 2021经营现金流249,116百万元；扣除H1 2021的161,618百万元后，Q3为87,498百万元。"),
        "operating_income": (36555, "millions CNY", "A股三季报比较栏9M 2021营业利润113,991百万元；扣除H1 2021营业利润77,436百万元后，Q3营业利润为36,555百万元。"),
        "operating_margin": (17.833, "percent", "Q3营业利润36,555百万元除以Q3营业收入204,983百万元，复算经营利润率为17.833%。"),
        "operating_revenue": (204983, "millions CNY", "A股三季报比较栏9M 2021营业收入648,630百万元扣除H1 2021营业收入443,647百万元后，Q3营业收入为204,983百万元。"),
        "revenue": (204983, "millions CNY", "中国移动总收入采用营业收入/Operating revenue口径；9M 2021扣除H1 2021复算Q3为204,983百万元。"),
        "revenue_growth_yoy": (11.080, "percent", "2021Q3营业收入204,983百万元；2020年前三季度营业收入574.4十亿元减H1 2020营业收入389,863百万元，复算2020Q3约184,537百万元，Q3同比约11.080%。"),
    },
    "Q4 2021": {
        "capital_expenditures": (-77512, "millions CNY", "A股年报比较栏全年2021购建长期资产现金支出207,311百万元，扣除9M 2021的129,799百万元后，Q4为77,512百万元，现金流出口径记为负数。"),
        "cash_and_equivalents": (243943, "millions CNY", "A股年报及H股年报披露2021年12月31日期末现金及现金等价物243,943百万元。"),
        "ebitda": (73508, "millions CNY", "H股年报披露FY 2021 EBITDA 311,008百万元；扣除9M 2021 EBITDA 237,500百万元后，Q4为73,508百万元。"),
        "ebitda_margin": (36.822, "percent", "Q4 EBITDA 73,508百万元除以Q4营业收入199,628百万元，复算EBITDA率为36.822%。"),
        "free_cash_flow": (-11864, "millions CNY", "Q4经营现金流65,648百万元减购建长期资产现金支出77,512百万元，复算普通自由现金流为-11,864百万元。"),
        "gross_margin": (28.591, "percent", "全年毛利244,353百万元扣除9M毛利187,277百万元，复算Q4毛利57,076百万元、毛利率28.591%。"),
        "gross_profit": (57076, "millions CNY", "全年营业收入848,258百万元、营业成本603,905百万元扣除9M营业收入648,630百万元、营业成本461,353百万元后，复算Q4毛利57,076百万元。"),
        "net_income": (28975, "millions CNY", "A股年报比较栏全年2021归母净利润115,937百万元，扣除9M 2021归母净利润86,962百万元后，Q4为28,975百万元；H股IFRS归母利润存在小幅口径差异。"),
        "operating_cash_flow": (65648, "millions CNY", "A股年报比较栏全年2021经营现金流314,764百万元；扣除9M 2021的249,116百万元后，Q4为65,648百万元。"),
        "operating_income": (38003, "millions CNY", "A股年报比较栏全年2021营业利润151,994百万元；扣除9M 2021营业利润113,991百万元后，Q4营业利润为38,003百万元。"),
        "operating_margin": (19.037, "percent", "Q4营业利润38,003百万元除以Q4营业收入199,628百万元，复算经营利润率为19.037%。"),
        "operating_revenue": (199628, "millions CNY", "A股年报比较栏全年2021营业收入848,258百万元扣除9M 2021营业收入648,630百万元后，Q4营业收入为199,628百万元。"),
        "revenue": (199628, "millions CNY", "中国移动总收入采用营业收入/Operating revenue口径；FY 2021扣除9M 2021复算Q4为199,628百万元。"),
        "revenue_growth_yoy": (3.076, "percent", "2021Q4营业收入199,628百万元；FY 2020营业收入768,070百万元减2020年前三季度营业收入574.4十亿元，复算2020Q4约193,670百万元，Q4同比约3.076%。"),
        "total_assets": (1806027, "millions CNY", "A股年报比较栏披露2021年12月31日资产总计1,806,027百万元；H股年报存在IFRS口径差异。"),
        "total_debt": (56981, "millions CNY", "H股年报披露2021年12月31日流动租赁负债26,059百万元、非流动租赁负债30,922百万元，合计56,981百万元。"),
    },
}

CM_2021_DETAIL_OFFICIAL_VERIFICATIONS = [
    _official_record(
        "中国移动",
        period,
        metric_key,
        value,
        unit,
        CM_2021_DETAIL_PERIOD_SOURCE[period][0],
        CM_2021_DETAIL_PERIOD_SOURCE[period][1],
        evidence,
        CM_2021_DETAIL_PERIOD_SOURCE[period][2],
        CM_2021_DETAIL_PERIOD_SOURCE[period][3],
    )
    for period, metrics in CM_2021_DETAIL_METRICS.items()
    for metric_key, (value, unit, evidence) in metrics.items()
]

CM_2021_SOURCE_GAP_CONFIRMATIONS = [
    {
        "subject": "中国移动",
        "period": "Q3 2021",
        "metric_key": metric_key,
        "source_label": "中国移动2021年三季度资产负债表披露缺口",
        "source_url": CM_2022_Q3_SINA_URL,
        "evidence": (
            f"已核验中国移动2022年三季报比较栏、2021中期报告及2021年度报告；"
            f"公开文件未披露2021年9月30日同口径 {METRIC_ZH_BY_KEY.get(metric_key, metric_key)}。"
            "该期间保留为披露缺口，不用标准化表估算。"
        ),
        "verification_method": "official_disclosure_gap_check",
        "verification_sources": CM_2021_Q3_GAP_SOURCES,
        "verification_note": "官方公告未披露2021-09-30资产负债表同口径数；正式回答只能说明披露缺口，不得引用标准化表占位值。",
    }
    for metric_key in ["total_assets", "total_debt"]
]


CM_2023_QUARTERLY_METRICS = {
    "Q1 2023": {
        "operating_revenue": 250700,
        "revenue": 250700,
        "service_revenue": 209800,
        "ebitda": 79900,
        "ebitda_margin": 31.87,
        "net_income": 28100,
    },
    "Q2 2023": {
        "operating_revenue": 280000,
        "revenue": 280000,
        "service_revenue": 242400,
        "ebitda": 103600,
        "ebitda_margin": 37.00,
        "net_income": 48100,
    },
    "Q3 2023": {
        "operating_revenue": 244900,
        "revenue": 244900,
        "service_revenue": 212400,
        "ebitda": 85000,
        "ebitda_margin": 34.71,
        "net_income": 29300,
    },
    "Q4 2023": {
        "operating_revenue": 233700,
        "revenue": 233700,
        "service_revenue": 198900,
        "ebitda": 73000,
        "ebitda_margin": 31.24,
        "net_income": 26300,
    },
}

CM_2023_OFFICIAL_VERIFICATIONS = [
    _official_record(
        "中国移动",
        period,
        metric_key,
        value,
        "percent" if metric_key == "ebitda_margin" else "millions CNY",
        "中国移动官网2023单季度经营数据",
        CM_2023_OPERATION_URL,
        CM_QUARTERLY_METRIC_EVIDENCE[metric_key].format(
            period_label=period.replace(" ", "/"),
            display_value=(value if metric_key == "ebitda_margin" else value / 1000),
        ),
        "official_quarterly_operating_data_with_h1_fy_reconciliation",
        CM_2023_Q1_Q2_SOURCES if period in {"Q1 2023", "Q2 2023"} else CM_2023_Q3_Q4_SOURCES,
    )
    for period, metrics in CM_2023_QUARTERLY_METRICS.items()
    for metric_key, value in metrics.items()
]

CM_2023_DETAIL_OFFICIAL_VERIFICATIONS = [
    _official_record("中国移动", "Q1 2023", "capital_expenditures", -37246, "millions CNY", "中国移动2023年第一季度报告", CM_2023_Q1_CNINFO_URL, "合并现金流量表披露购建固定资产、无形资产和其他长期资产支付的现金37,246百万元；现金流出口径记为负数。", "official_cash_flow_statement_row_check", CM_2023_Q1_DETAIL_SOURCES),
    _official_record("中国移动", "Q1 2023", "cash_and_equivalents", 193648, "millions CNY", "中国移动2023年第一季度报告", CM_2023_Q1_CNINFO_URL, "合并现金流量表披露期末现金及现金等价物余额193,648百万元；该口径不同于资产负债表货币资金225,812百万元。", "official_cash_flow_statement_cash_equivalents_check", CM_2023_Q1_DETAIL_SOURCES),
    _official_record("中国移动", "Q1 2023", "free_cash_flow", 37959, "millions CNY", "中国移动2023年第一季度报告", CM_2023_Q1_CNINFO_URL, "合并现金流量表披露经营现金流75,205百万元、购建长期资产现金支出37,246百万元；普通自由现金流复算为37,959百万元。", "official_operating_cash_flow_minus_capex_reconciliation", CM_2023_Q1_DETAIL_SOURCES),
    _official_record("中国移动", "Q1 2023", "gross_profit", 61329, "millions CNY", "中国移动2023年第一季度报告", CM_2023_Q1_CNINFO_URL, "合并利润表披露营业收入250,746百万元、营业成本189,417百万元；按收入减营业成本复算毛利为61,329百万元。", "official_revenue_minus_operating_cost_reconciliation", CM_2023_Q1_DETAIL_SOURCES),
    _official_record("中国移动", "Q1 2023", "gross_margin", 24.460, "percent", "中国移动2023年第一季度报告", CM_2023_Q1_CNINFO_URL, "以官方复算毛利61,329百万元除以营业收入250,746百万元，毛利率为24.460%。", "official_gross_profit_divided_by_revenue_reconciliation", CM_2023_Q1_DETAIL_SOURCES),
    _official_record("中国移动", "Q1 2023", "operating_cash_flow", 75205, "millions CNY", "中国移动2023年第一季度报告", CM_2023_Q1_CNINFO_URL, "合并现金流量表披露经营活动产生的现金流量净额75,205百万元。", "official_cash_flow_statement_row_check", CM_2023_Q1_DETAIL_SOURCES),
    _official_record("中国移动", "Q1 2023", "operating_income", 36141, "millions CNY", "中国移动2023年第一季度报告", CM_2023_Q1_CNINFO_URL, "合并利润表披露营业利润36,141百万元。", "official_income_statement_row_check", CM_2023_Q1_DETAIL_SOURCES),
    _official_record("中国移动", "Q1 2023", "operating_margin", 14.414, "percent", "中国移动2023年第一季度报告", CM_2023_Q1_CNINFO_URL, "以营业利润36,141百万元除以营业收入250,746百万元，经营利润率为14.414%。", "official_operating_income_divided_by_revenue_reconciliation", CM_2023_Q1_DETAIL_SOURCES),
    _official_record("中国移动", "Q1 2023", "revenue_growth_yoy", 10.300, "percent", "中国移动2023年第一季度报告", CM_2023_Q1_CNINFO_URL, "一季报主要会计数据表披露营业收入250,746百万元、同比增长10.3%；官网季度经营数据列示1Q 2023 Operating Revenue 2,507亿元。", "official_current_prior_period_recalculation", CM_2023_Q1_DETAIL_SOURCES),
    _official_record("中国移动", "Q1 2023", "total_assets", 1957557, "millions CNY", "中国移动2023年第一季度报告", CM_2023_Q1_CNINFO_URL, "合并资产负债表披露2023年3月31日资产总计1,957,557百万元。", "official_balance_sheet_row_check", CM_2023_Q1_DETAIL_SOURCES),
    _official_record("中国移动", "Q1 2023", "total_debt", 115508, "millions CNY", "中国移动2023年第一季度报告", CM_2023_Q1_CNINFO_URL, "合并资产负债表披露一年内到期的非流动负债31,677百万元、租赁负债83,831百万元，未列短期或长期借款，合计总债务115,508百万元。", "official_borrowings_plus_lease_liabilities_reconciliation", CM_2023_Q1_DETAIL_SOURCES),
    _official_record("中国移动", "Q2 2023", "capital_expenditures", -42400, "millions CNY", "中国移动2023年半年度报告", CM_2023_H1_SINA_URL, "A股半年报现金流量表披露H1购建固定资产、无形资产和其他长期资产支付的现金79,646百万元；扣除Q1官方37,246百万元后，Q2为42,400百万元，现金流出口径记为负数。", "official_h1_minus_q1_cash_flow_reconciliation", CM_2023_Q2_DETAIL_SOURCES),
    _official_record("中国移动", "Q2 2023", "cash_and_equivalents", 204928, "millions CNY", "中国移动2023年半年度报告", CM_2023_H1_SINA_URL, "A股半年报现金流量表披露2023年6月30日期末现金及现金等价物余额204,928百万元；该口径不同于资产负债表货币资金227,983百万元。", "official_cash_flow_statement_cash_equivalents_check", CM_2023_Q2_DETAIL_SOURCES),
    _official_record("中国移动", "Q2 2023", "free_cash_flow", 42920, "millions CNY", "中国移动2023年半年度报告", CM_2023_H1_SINA_URL, "H1经营现金流160,525百万元、购建长期资产现金支出79,646百万元，普通自由现金流为80,879百万元；扣除Q1官方37,959百万元后，Q2自由现金流为42,920百万元。", "official_h1_minus_q1_operating_cash_flow_minus_capex_reconciliation", CM_2023_Q2_DETAIL_SOURCES),
    _official_record("中国移动", "Q2 2023", "gross_profit", 91583, "millions CNY", "中国移动2023年半年度报告", CM_2023_H1_SINA_URL, "A股半年报披露H1营业收入530,719百万元、营业成本377,807百万元，H1毛利152,912百万元；扣除Q1官方毛利61,329百万元后，Q2毛利为91,583百万元。", "official_h1_minus_q1_revenue_minus_operating_cost_reconciliation", CM_2023_Q2_DETAIL_SOURCES),
    _official_record("中国移动", "Q2 2023", "gross_margin", 32.711, "percent", "中国移动2023年半年度报告", CM_2023_H1_SINA_URL, "以官方复算Q2毛利91,583百万元除以Q2营业收入279,973百万元，毛利率为32.711%。", "official_gross_profit_divided_by_revenue_reconciliation", CM_2023_Q2_DETAIL_SOURCES),
    _official_record("中国移动", "Q2 2023", "operating_cash_flow", 85320, "millions CNY", "中国移动2023年半年度报告", CM_2023_H1_SINA_URL, "A股半年报现金流量表披露H1经营活动产生的现金流量净额160,525百万元；扣除Q1官方75,205百万元后，Q2经营现金流为85,320百万元。", "official_h1_minus_q1_cash_flow_reconciliation", CM_2023_Q2_DETAIL_SOURCES),
    _official_record("中国移动", "Q2 2023", "operating_income", 61859, "millions CNY", "中国移动2023年半年度报告", CM_2023_H1_SINA_URL, "A股半年报利润表披露H1营业利润98,000百万元；扣除Q1官方36,141百万元后，Q2营业利润为61,859百万元。", "official_h1_minus_q1_income_statement_reconciliation", CM_2023_Q2_DETAIL_SOURCES),
    _official_record("中国移动", "Q2 2023", "operating_margin", 22.095, "percent", "中国移动2023年半年度报告", CM_2023_H1_SINA_URL, "以官方复算Q2营业利润61,859百万元除以Q2营业收入279,973百万元，经营利润率为22.095%。", "official_operating_income_divided_by_revenue_reconciliation", CM_2023_Q2_DETAIL_SOURCES),
    _official_record("中国移动", "Q2 2023", "revenue_growth_yoy", 3.842, "percent", "中国移动2023年半年度报告", CM_2023_H1_SINA_URL, "H1 2023营业收入530,719百万元扣除Q1 2023的250,746百万元得Q2 279,973百万元；H1 2022营业收入496,934百万元扣除Q1 2022的227,320百万元得Q2 269,614百万元，复算同比为3.842%。", "official_current_prior_period_recalculation", CM_2023_Q2_DETAIL_SOURCES),
    _official_record("中国移动", "Q2 2023", "total_assets", 1956296, "millions CNY", "中国移动2023年半年度报告", CM_2023_H1_SINA_URL, "A股半年报合并资产负债表披露2023年6月30日资产总计1,956,296百万元。", "official_balance_sheet_row_check", CM_2023_Q2_DETAIL_SOURCES),
    _official_record("中国移动", "Q2 2023", "total_debt", 112328, "millions CNY", "中国移动2023年半年度报告", CM_2023_H1_SINA_URL, "A股半年报合并资产负债表披露一年内到期的非流动负债35,290百万元、租赁负债77,038百万元，未列短期或长期借款，合计总债务112,328百万元。", "official_borrowings_plus_lease_liabilities_reconciliation", CM_2023_Q2_DETAIL_SOURCES),
    _official_record("中国移动", "Q3 2023", "capital_expenditures", -41290, "millions CNY", "中国移动2023年第三季度报告", CM_2023_Q3_SINA_URL, "A股三季报现金流量表披露9M购建固定资产、无形资产和其他长期资产支付的现金120,936百万元；扣除H1官方79,646百万元后，Q3为41,290百万元，现金流出口径记为负数。", "official_9m_minus_h1_cash_flow_reconciliation", CM_2023_Q3_DETAIL_SOURCES),
    _official_record("中国移动", "Q3 2023", "cash_and_equivalents", 177383, "millions CNY", "中国移动2023年第三季度报告", CM_2023_Q3_SINA_URL, "A股三季报现金流量表披露2023年9月30日期末现金及现金等价物余额177,383百万元；该口径不同于资产负债表货币资金225,285百万元。", "official_cash_flow_statement_cash_equivalents_check", CM_2023_Q3_DETAIL_SOURCES),
    _official_record("中国移动", "Q3 2023", "free_cash_flow", 35863, "millions CNY", "中国移动2023年第三季度报告", CM_2023_Q3_SINA_URL, "9M经营现金流237,678百万元、购建长期资产现金支出120,936百万元，普通自由现金流116,742百万元；扣除H1官方80,879百万元后，Q3自由现金流为35,863百万元。", "official_9m_minus_h1_operating_cash_flow_minus_capex_reconciliation", CM_2023_Q3_DETAIL_SOURCES),
    _official_record("中国移动", "Q3 2023", "gross_profit", 70041, "millions CNY", "中国移动2023年第三季度报告", CM_2023_Q3_SINA_URL, "A股三季报披露9M营业收入775,560百万元、营业成本552,607百万元，9M毛利222,953百万元；扣除H1官方毛利152,912百万元后，Q3毛利为70,041百万元。", "official_9m_minus_h1_revenue_minus_operating_cost_reconciliation", CM_2023_Q3_DETAIL_SOURCES),
    _official_record("中国移动", "Q3 2023", "gross_margin", 28.607, "percent", "中国移动2023年第三季度报告", CM_2023_Q3_SINA_URL, "以官方复算Q3毛利70,041百万元除以Q3营业收入244,841百万元，毛利率为28.607%。", "official_gross_profit_divided_by_revenue_reconciliation", CM_2023_Q3_DETAIL_SOURCES),
    _official_record("中国移动", "Q3 2023", "operating_cash_flow", 77153, "millions CNY", "中国移动2023年第三季度报告", CM_2023_Q3_SINA_URL, "A股三季报现金流量表披露9M经营活动产生的现金流量净额237,678百万元；扣除H1官方160,525百万元后，Q3经营现金流为77,153百万元。", "official_9m_minus_h1_cash_flow_reconciliation", CM_2023_Q3_DETAIL_SOURCES),
    _official_record("中国移动", "Q3 2023", "operating_income", 38912, "millions CNY", "中国移动2023年第三季度报告", CM_2023_Q3_SINA_URL, "A股三季报利润表披露9M营业利润136,912百万元；扣除H1官方98,000百万元后，Q3营业利润为38,912百万元。", "official_9m_minus_h1_income_statement_reconciliation", CM_2023_Q3_DETAIL_SOURCES),
    _official_record("中国移动", "Q3 2023", "operating_margin", 15.893, "percent", "中国移动2023年第三季度报告", CM_2023_Q3_SINA_URL, "以官方复算Q3营业利润38,912百万元除以Q3营业收入244,841百万元，经营利润率为15.893%。", "official_operating_income_divided_by_revenue_reconciliation", CM_2023_Q3_DETAIL_SOURCES),
    _official_record("中国移动", "Q3 2023", "revenue_growth_yoy", 8.072, "percent", "中国移动2023年第三季度报告", CM_2023_Q3_SINA_URL, "9M 2023营业收入775,560百万元扣除H1 2023的530,719百万元得Q3 244,841百万元；9M 2022营业收入723,487百万元扣除H1 2022的496,934百万元得Q3 226,553百万元，复算同比为8.072%。", "official_current_prior_period_recalculation", CM_2023_Q3_DETAIL_SOURCES),
    _official_record("中国移动", "Q3 2023", "total_assets", 1949176, "millions CNY", "中国移动2023年第三季度报告", CM_2023_Q3_SINA_URL, "A股三季报合并资产负债表披露2023年9月30日资产总计1,949,176百万元。", "official_balance_sheet_row_check", CM_2023_Q3_DETAIL_SOURCES),
    _official_record("中国移动", "Q3 2023", "total_debt", 106220, "millions CNY", "中国移动2023年第三季度报告", CM_2023_Q3_SINA_URL, "A股三季报合并资产负债表披露一年内到期的非流动负债33,010百万元、租赁负债73,210百万元，未列短期或长期借款，合计总债务106,220百万元。", "official_borrowings_plus_lease_liabilities_reconciliation", CM_2023_Q3_DETAIL_SOURCES),
    _official_record("中国移动", "Q4 2023", "capital_expenditures", -60327, "millions CNY", "中国移动2023年年度报告", CM_2023_ANNUAL_SINA_URL, "A股年报现金流量表披露全年购建固定资产、无形资产和其他长期资产支付的现金181,263百万元；扣除9M官方120,936百万元后，Q4为60,327百万元，现金流出口径记为负数。", "official_fy_minus_9m_cash_flow_reconciliation", CM_2023_Q4_DETAIL_SOURCES),
    _official_record("中国移动", "Q4 2023", "cash_and_equivalents", 141559, "millions CNY", "中国移动2023年年度报告", CM_2023_ANNUAL_SINA_URL, "A股年报现金流量表披露2023年12月31日年末现金及现金等价物余额141,559百万元；该口径不同于资产负债表货币资金178,772百万元。", "official_cash_flow_statement_cash_equivalents_check", CM_2023_Q4_DETAIL_SOURCES),
    _official_record("中国移动", "Q4 2023", "free_cash_flow", 5775, "millions CNY", "中国移动2023年年度报告", CM_2023_ANNUAL_SINA_URL, "全年经营现金流303,780百万元、购建长期资产现金支出181,263百万元，普通自由现金流122,517百万元；扣除9M官方116,742百万元后，Q4自由现金流为5,775百万元。", "official_fy_minus_9m_operating_cash_flow_minus_capex_reconciliation", CM_2023_Q4_DETAIL_SOURCES),
    _official_record("中国移动", "Q4 2023", "gross_profit", 61998, "millions CNY", "中国移动2023年年度报告", CM_2023_ANNUAL_SINA_URL, "A股年报披露全年营业收入1,009,309百万元、营业成本724,358百万元，全年毛利284,951百万元；扣除9M官方毛利222,953百万元后，Q4毛利为61,998百万元。", "official_fy_minus_9m_revenue_minus_operating_cost_reconciliation", CM_2023_Q4_DETAIL_SOURCES),
    _official_record("中国移动", "Q4 2023", "gross_margin", 26.523, "percent", "中国移动2023年年度报告", CM_2023_ANNUAL_SINA_URL, "以官方复算Q4毛利61,998百万元除以Q4营业收入233,749百万元，毛利率为26.523%。", "official_gross_profit_divided_by_revenue_reconciliation", CM_2023_Q4_DETAIL_SOURCES),
    _official_record("中国移动", "Q4 2023", "operating_cash_flow", 66102, "millions CNY", "中国移动2023年年度报告", CM_2023_ANNUAL_SINA_URL, "A股年报现金流量表披露全年经营活动产生的现金流量净额303,780百万元；扣除9M官方237,678百万元后，Q4经营现金流为66,102百万元。", "official_fy_minus_9m_cash_flow_reconciliation", CM_2023_Q4_DETAIL_SOURCES),
    _official_record("中国移动", "Q4 2023", "operating_income", 31205, "millions CNY", "中国移动2023年年度报告", CM_2023_ANNUAL_SINA_URL, "A股年报利润表披露全年营业利润168,117百万元；扣除9M官方136,912百万元后，Q4营业利润为31,205百万元。", "official_fy_minus_9m_income_statement_reconciliation", CM_2023_Q4_DETAIL_SOURCES),
    _official_record("中国移动", "Q4 2023", "operating_margin", 13.350, "percent", "中国移动2023年年度报告", CM_2023_ANNUAL_SINA_URL, "以官方复算Q4营业利润31,205百万元除以Q4营业收入233,749百万元，经营利润率为13.350%。", "official_operating_income_divided_by_revenue_reconciliation", CM_2023_Q4_DETAIL_SOURCES),
    _official_record("中国移动", "Q4 2023", "revenue_growth_yoy", 9.345, "percent", "中国移动2023年年度报告", CM_2023_ANNUAL_SINA_URL, "全年2023营业收入1,009,309百万元扣除9M 2023的775,560百万元得Q4 233,749百万元；全年2022营业收入937,259百万元扣除9M 2022的723,487百万元得Q4 213,772百万元，复算同比为9.345%。", "official_current_prior_period_recalculation", CM_2023_Q4_DETAIL_SOURCES),
    _official_record("中国移动", "Q4 2023", "total_assets", 1957357, "millions CNY", "中国移动2023年年度报告", CM_2023_ANNUAL_SINA_URL, "A股年报合并资产负债表披露2023年12月31日资产总计1,957,357百万元。", "official_balance_sheet_row_check", CM_2023_Q4_DETAIL_SOURCES),
    _official_record("中国移动", "Q4 2023", "total_debt", 102934, "millions CNY", "中国移动2023年年度报告", CM_2023_ANNUAL_SINA_URL, "A股年报合并资产负债表披露一年内到期的非流动负债35,175百万元、租赁负债67,759百万元，未列短期或长期借款，合计总债务102,934百万元。", "official_borrowings_plus_lease_liabilities_reconciliation", CM_2023_Q4_DETAIL_SOURCES),
]


CM_2024_QUARTERLY_METRICS = {
    "Q1 2024": {
        "operating_revenue": 263700,
        "revenue": 263700,
        "service_revenue": 219300,
        "ebitda": 78000,
        "ebitda_margin": 29.58,
        "net_income": 29600,
    },
    "Q2 2024": {
        "operating_revenue": 283000,
        "revenue": 283000,
        "service_revenue": 244300,
        "ebitda": 104300,
        "ebitda_margin": 36.86,
        "net_income": 50600,
    },
    "Q3 2024": {
        "operating_revenue": 244800,
        "revenue": 244800,
        "service_revenue": 214400,
        "ebitda": 80800,
        "ebitda_margin": 33.01,
        "net_income": 30700,
    },
    "Q4 2024": {
        "operating_revenue": 249300,
        "revenue": 249300,
        "service_revenue": 211500,
        "ebitda": 70600,
        "ebitda_margin": 28.32,
        "net_income": 27500,
    },
}

CM_2024_METRIC_EVIDENCE = {
    "operating_revenue": "官网单季度经营数据列示{period_label} Operating Revenue 为人民币 {display_value} 十亿元。",
    "revenue": "中国移动总收入采用 Operating Revenue 口径；官网单季度经营数据列示{period_label} Operating Revenue 为人民币 {display_value} 十亿元。",
    "service_revenue": "官网单季度经营数据列示{period_label} Revenue from Telecommunications Services 为人民币 {display_value} 十亿元。",
    "ebitda": "官网单季度经营数据列示{period_label} EBITDA 为人民币 {display_value} 十亿元。",
    "ebitda_margin": "EBITDA margin 按中国移动年报定义由 EBITDA / operating revenue 复算；{period_label}为 {display_value}%。",
    "net_income": "官网单季度经营数据列示{period_label} Profit Attributable to Equity Shareholders 为人民币 {display_value} 十亿元。",
}

CM_2024_OFFICIAL_VERIFICATIONS = [
    _official_record(
        "中国移动",
        period,
        metric_key,
        value,
        "percent" if metric_key == "ebitda_margin" else "millions CNY",
        "中国移动官网2024单季度经营数据",
        CM_2024_OPERATION_URL,
        CM_2024_METRIC_EVIDENCE[metric_key].format(
            period_label=period.replace(" ", "/"),
            display_value=(value if metric_key == "ebitda_margin" else value / 1000),
        ),
        "official_quarterly_operating_data_with_h1_fy_reconciliation",
        CM_2024_Q1_Q2_SOURCES if period in {"Q1 2024", "Q2 2024"} else CM_2024_Q3_Q4_SOURCES,
    )
    for period, metrics in CM_2024_QUARTERLY_METRICS.items()
    for metric_key, value in metrics.items()
]

CM_2024_DETAIL_OFFICIAL_VERIFICATIONS = [
    _official_record("中国移动", "Q2 2024", "capital_expenditures", -38982, "millions CNY", "中国移动2024年半年度报告", CM_2024_H1_SINA_URL, "A股半年报现金流量表披露H1购建长期资产现金支出73,460百万元；扣除Q1官方34,478百万元后，Q2为38,982百万元，现金流出口径记为负数。", "official_h1_minus_q1_cash_flow_reconciliation", CM_2024_Q2_DETAIL_SOURCES),
    _official_record("中国移动", "Q2 2024", "cash_and_equivalents", 132073, "millions CNY", "中国移动2024年半年度报告", CM_2024_H1_SINA_URL, "A股半年报现金流量表披露2024年6月30日期末现金及现金等价物余额132,073百万元；该口径不同于资产负债表货币资金172,891百万元。", "official_cash_flow_statement_cash_equivalents_check", CM_2024_Q2_DETAIL_SOURCES),
    _official_record("中国移动", "Q2 2024", "free_cash_flow", 35491, "millions CNY", "中国移动2024年半年度报告", CM_2024_H1_SINA_URL, "H1经营现金流131,377百万元、购建长期资产现金支出73,460百万元，普通自由现金流57,917百万元；扣除Q1官方22,426百万元后，Q2自由现金流为35,491百万元。", "official_h1_minus_q1_operating_cash_flow_minus_capex_reconciliation", CM_2024_Q2_DETAIL_SOURCES),
    _official_record("中国移动", "Q2 2024", "gross_profit", 99442, "millions CNY", "中国移动2024年半年度报告", CM_2024_H1_SINA_URL, "A股半年报披露H1营业收入546,744百万元、营业成本378,285百万元，H1毛利168,459百万元；扣除Q1官方毛利69,017百万元后，Q2毛利为99,442百万元。", "official_h1_minus_q1_revenue_minus_operating_cost_reconciliation", CM_2024_Q2_DETAIL_SOURCES),
    _official_record("中国移动", "Q2 2024", "gross_margin", 35.134, "percent", "中国移动2024年半年度报告", CM_2024_H1_SINA_URL, "以官方复算Q2毛利99,442百万元除以Q2营业收入283,037百万元，毛利率为35.134%。", "official_gross_profit_divided_by_revenue_reconciliation", CM_2024_Q2_DETAIL_SOURCES),
    _official_record("中国移动", "Q2 2024", "operating_cash_flow", 74473, "millions CNY", "中国移动2024年半年度报告", CM_2024_H1_SINA_URL, "A股半年报现金流量表披露H1经营活动产生的现金流量净额131,377百万元；扣除Q1官方56,904百万元后，Q2经营现金流为74,473百万元。", "official_h1_minus_q1_cash_flow_reconciliation", CM_2024_Q2_DETAIL_SOURCES),
    _official_record("中国移动", "Q2 2024", "operating_income", 64372, "millions CNY", "中国移动2024年半年度报告", CM_2024_H1_SINA_URL, "A股半年报利润表披露H1营业利润102,506百万元；扣除Q1官方38,134百万元后，Q2营业利润为64,372百万元。", "official_h1_minus_q1_income_statement_reconciliation", CM_2024_Q2_DETAIL_SOURCES),
    _official_record("中国移动", "Q2 2024", "operating_margin", 22.743, "percent", "中国移动2024年半年度报告", CM_2024_H1_SINA_URL, "以官方复算Q2营业利润64,372百万元除以Q2营业收入283,037百万元，经营利润率为22.743%。", "official_operating_income_divided_by_revenue_reconciliation", CM_2024_Q2_DETAIL_SOURCES),
    _official_record("中国移动", "Q2 2024", "revenue_growth_yoy", 1.094, "percent", "中国移动2024年半年度报告", CM_2024_H1_SINA_URL, "H1 2024营业收入546,744百万元扣除Q1 2024的263,707百万元得Q2 283,037百万元；H1 2023营业收入530,719百万元扣除Q1 2023的250,746百万元得Q2 279,973百万元，复算同比为1.094%。", "official_current_prior_period_recalculation", CM_2024_Q2_DETAIL_SOURCES),
    _official_record("中国移动", "Q2 2024", "total_assets", 1986307, "millions CNY", "中国移动2024年半年度报告", CM_2024_H1_SINA_URL, "A股半年报合并资产负债表披露2024年6月30日资产总计1,986,307百万元。", "official_balance_sheet_row_check", CM_2024_Q2_DETAIL_SOURCES),
    _official_record("中国移动", "Q2 2024", "total_debt", 95670, "millions CNY", "中国移动2024年半年度报告", CM_2024_H1_SINA_URL, "A股半年报合并资产负债表披露一年内到期的非流动负债33,448百万元、租赁负债62,222百万元，未列短期或长期借款，合计总债务95,670百万元。", "official_borrowings_plus_lease_liabilities_reconciliation", CM_2024_Q2_DETAIL_SOURCES),
    _official_record("中国移动", "Q3 2024", "capital_expenditures", -43395, "millions CNY", "中国移动2024年第三季度报告", CM_2024_Q3_CNINFO_URL, "A股三季报现金流量表披露9M购建长期资产现金支出116,855百万元；扣除H1官方73,460百万元后，Q3为43,395百万元，现金流出口径记为负数。", "official_9m_minus_h1_cash_flow_reconciliation", CM_2024_Q3_DETAIL_SOURCES),
    _official_record("中国移动", "Q3 2024", "cash_and_equivalents", 121279, "millions CNY", "中国移动2024年第三季度报告", CM_2024_Q3_CNINFO_URL, "A股三季报现金流量表披露2024年9月30日期末现金及现金等价物余额121,279百万元；该口径不同于资产负债表货币资金168,281百万元。", "official_cash_flow_statement_cash_equivalents_check", CM_2024_Q3_DETAIL_SOURCES),
    _official_record("中国移动", "Q3 2024", "free_cash_flow", 49303, "millions CNY", "中国移动2024年第三季度报告", CM_2024_Q3_CNINFO_URL, "9M经营现金流224,075百万元、购建长期资产现金支出116,855百万元，普通自由现金流107,220百万元；扣除H1官方57,917百万元后，Q3自由现金流为49,303百万元。", "official_9m_minus_h1_operating_cash_flow_minus_capex_reconciliation", CM_2024_Q3_DETAIL_SOURCES),
    _official_record("中国移动", "Q3 2024", "gross_profit", 75409, "millions CNY", "中国移动2024年第三季度报告", CM_2024_Q3_CNINFO_URL, "A股三季报披露9M营业收入791,458百万元、营业成本547,590百万元，9M毛利243,868百万元；扣除H1官方毛利168,459百万元后，Q3毛利为75,409百万元。", "official_9m_minus_h1_revenue_minus_operating_cost_reconciliation", CM_2024_Q3_DETAIL_SOURCES),
    _official_record("中国移动", "Q3 2024", "gross_margin", 30.815, "percent", "中国移动2024年第三季度报告", CM_2024_Q3_CNINFO_URL, "以官方复算Q3毛利75,409百万元除以Q3营业收入244,714百万元，毛利率为30.815%。", "official_gross_profit_divided_by_revenue_reconciliation", CM_2024_Q3_DETAIL_SOURCES),
    _official_record("中国移动", "Q3 2024", "operating_cash_flow", 92698, "millions CNY", "中国移动2024年第三季度报告", CM_2024_Q3_CNINFO_URL, "A股三季报现金流量表披露9M经营活动产生的现金流量净额224,075百万元；扣除H1官方131,377百万元后，Q3经营现金流为92,698百万元。", "official_9m_minus_h1_cash_flow_reconciliation", CM_2024_Q3_DETAIL_SOURCES),
    _official_record("中国移动", "Q3 2024", "operating_income", 38973, "millions CNY", "中国移动2024年第三季度报告", CM_2024_Q3_CNINFO_URL, "A股三季报利润表披露9M营业利润141,479百万元；扣除H1官方102,506百万元后，Q3营业利润为38,973百万元。", "official_9m_minus_h1_income_statement_reconciliation", CM_2024_Q3_DETAIL_SOURCES),
    _official_record("中国移动", "Q3 2024", "operating_margin", 15.926, "percent", "中国移动2024年第三季度报告", CM_2024_Q3_CNINFO_URL, "以官方复算Q3营业利润38,973百万元除以Q3营业收入244,714百万元，经营利润率为15.926%。", "official_operating_income_divided_by_revenue_reconciliation", CM_2024_Q3_DETAIL_SOURCES),
    _official_record("中国移动", "Q3 2024", "revenue_growth_yoy", -0.052, "percent", "中国移动2024年第三季度报告", CM_2024_Q3_CNINFO_URL, "9M 2024营业收入791,458百万元扣除H1 2024的546,744百万元得Q3 244,714百万元；9M 2023营业收入775,560百万元扣除H1 2023的530,719百万元得Q3 244,841百万元，复算同比为-0.052%。", "official_current_prior_period_recalculation", CM_2024_Q3_DETAIL_SOURCES),
    _official_record("中国移动", "Q3 2024", "total_assets", 1983343, "millions CNY", "中国移动2024年第三季度报告", CM_2024_Q3_CNINFO_URL, "A股三季报合并资产负债表披露2024年9月30日资产总计1,983,343百万元。", "official_balance_sheet_row_check", CM_2024_Q3_DETAIL_SOURCES),
    _official_record("中国移动", "Q3 2024", "total_debt", 92624, "millions CNY", "中国移动2024年第三季度报告", CM_2024_Q3_CNINFO_URL, "A股三季报合并资产负债表披露一年内到期的非流动负债30,806百万元、租赁负债61,818百万元，未列短期或长期借款，合计总债务92,624百万元。", "official_borrowings_plus_lease_liabilities_reconciliation", CM_2024_Q3_DETAIL_SOURCES),
    _official_record("中国移动", "Q4 2024", "capital_expenditures", -39124, "millions CNY", "中国移动2024年年度报告", CM_2024_ANNUAL_SINA_URL, "A股年报现金流量表披露全年购建长期资产现金支出155,979百万元；扣除9M官方116,855百万元后，Q4为39,124百万元，现金流出口径记为负数。", "official_fy_minus_9m_cash_flow_reconciliation", CM_2024_Q4_DETAIL_SOURCES),
    _official_record("中国移动", "Q4 2024", "cash_and_equivalents", 167309, "millions CNY", "中国移动2024年年度报告", CM_2024_ANNUAL_SINA_URL, "A股年报现金流量表披露2024年12月31日年末现金及现金等价物余额167,309百万元；该口径不同于资产负债表货币资金242,275百万元。", "official_cash_flow_statement_cash_equivalents_check", CM_2024_Q4_DETAIL_SOURCES),
    _official_record("中国移动", "Q4 2024", "free_cash_flow", 52542, "millions CNY", "中国移动2024年年度报告", CM_2024_ANNUAL_SINA_URL, "全年经营现金流315,741百万元、购建长期资产现金支出155,979百万元，普通自由现金流159,762百万元；扣除9M官方107,220百万元后，Q4自由现金流为52,542百万元。", "official_fy_minus_9m_operating_cash_flow_minus_capex_reconciliation", CM_2024_Q4_DETAIL_SOURCES),
    _official_record("中国移动", "Q4 2024", "gross_profit", 58119, "millions CNY", "中国移动2024年年度报告", CM_2024_ANNUAL_SINA_URL, "A股年报披露全年营业收入1,040,759百万元、营业成本738,772百万元，全年毛利301,987百万元；扣除9M官方毛利243,868百万元后，Q4毛利为58,119百万元。", "official_fy_minus_9m_revenue_minus_operating_cost_reconciliation", CM_2024_Q4_DETAIL_SOURCES),
    _official_record("中国移动", "Q4 2024", "gross_margin", 23.313, "percent", "中国移动2024年年度报告", CM_2024_ANNUAL_SINA_URL, "以官方复算Q4毛利58,119百万元除以Q4营业收入249,301百万元，毛利率为23.313%。", "official_gross_profit_divided_by_revenue_reconciliation", CM_2024_Q4_DETAIL_SOURCES),
    _official_record("中国移动", "Q4 2024", "operating_cash_flow", 91666, "millions CNY", "中国移动2024年年度报告", CM_2024_ANNUAL_SINA_URL, "A股年报现金流量表披露全年经营活动产生的现金流量净额315,741百万元；扣除9M官方224,075百万元后，Q4经营现金流为91,666百万元。", "official_fy_minus_9m_cash_flow_reconciliation", CM_2024_Q4_DETAIL_SOURCES),
    _official_record("中国移动", "Q4 2024", "operating_income", 34805, "millions CNY", "中国移动2024年年度报告", CM_2024_ANNUAL_SINA_URL, "A股年报利润表披露全年营业利润176,284百万元；扣除9M官方141,479百万元后，Q4营业利润为34,805百万元。", "official_fy_minus_9m_income_statement_reconciliation", CM_2024_Q4_DETAIL_SOURCES),
    _official_record("中国移动", "Q4 2024", "operating_margin", 13.961, "percent", "中国移动2024年年度报告", CM_2024_ANNUAL_SINA_URL, "以官方复算Q4营业利润34,805百万元除以Q4营业收入249,301百万元，经营利润率为13.961%。", "official_operating_income_divided_by_revenue_reconciliation", CM_2024_Q4_DETAIL_SOURCES),
    _official_record("中国移动", "Q4 2024", "revenue_growth_yoy", 6.653, "percent", "中国移动2024年年度报告", CM_2024_ANNUAL_SINA_URL, "全年2024营业收入1,040,759百万元扣除9M 2024的791,458百万元得Q4 249,301百万元；全年2023营业收入1,009,309百万元扣除9M 2023的775,560百万元得Q4 233,749百万元，复算同比为6.653%。", "official_current_prior_period_recalculation", CM_2024_Q4_DETAIL_SOURCES),
    _official_record("中国移动", "Q4 2024", "total_assets", 2072827, "millions CNY", "中国移动2024年年度报告", CM_2024_ANNUAL_SINA_URL, "A股年报合并资产负债表披露2024年12月31日资产总计2,072,827百万元。", "official_balance_sheet_row_check", CM_2024_Q4_DETAIL_SOURCES),
    _official_record("中国移动", "Q4 2024", "total_debt", 88442, "millions CNY", "中国移动2024年年度报告", CM_2024_ANNUAL_SINA_URL, "A股年报合并资产负债表披露一年内到期的非流动负债32,512百万元、租赁负债55,930百万元，未列短期或长期借款，合计总债务88,442百万元。", "official_borrowings_plus_lease_liabilities_reconciliation", CM_2024_Q4_DETAIL_SOURCES),
]


CT_QUARTERLY_METRIC_EVIDENCE = {
    "revenue": "中国电信官方Q1/H1/9M/FY披露复核{period_label} Operating Revenue 为人民币 {display_value} 百万元。",
    "service_revenue": "中国电信官方Q1/H1/9M/FY披露复核{period_label} Service Revenue 为人民币 {display_value} 百万元。",
    "ebitda": "中国电信官方Q1/H1/9M/FY披露复核{period_label} EBITDA 为人民币 {display_value} 百万元。",
    "ebitda_margin": "EBITDA margin 按中国电信公告定义由 EBITDA / service revenue 复算；{period_label}为 {display_value}%。",
    "net_income": "中国电信官方Q1/H1/9M/FY披露复核{period_label} Profit attributable to Equity Holders of the Company 为人民币 {display_value} 百万元。",
}


CT_2023_QUARTERLY_METRICS = {
    "Q1 2023": {
        "revenue": 130588,
        "service_revenue": 118478,
        "ebitda": 33874,
        "ebitda_margin": 28.59,
        "net_income": 7984,
    },
    "Q2 2023": {
        "revenue": 130076,
        "service_revenue": 117499,
        "ebitda": 39472,
        "ebitda_margin": 33.59,
        "net_income": 12169,
    },
    "Q3 2023": {
        "revenue": 123590,
        "service_revenue": 113766,
        "ebitda": 32302,
        "ebitda_margin": 28.39,
        "net_income": 6948,
    },
    "Q4 2023": {
        "revenue": 129297,
        "service_revenue": 115222,
        "ebitda": 31182,
        "ebitda_margin": 27.06,
        "net_income": 3345,
    },
}

CT_2022_QUARTERLY_METRICS = {
    "Q1 2022": {
        "revenue": 119629,
        "ebitda": 32361,
        "net_income": 7223,
    },
    "Q2 2022": {
        "revenue": 122690,
        "ebitda": 37487,
        "net_income": 11068,
    },
    "Q3 2022": {
        "revenue": 118663,
        "ebitda": 30610,
        "net_income": 6252,
    },
    "Q4 2022": {
        "revenue": 120466,
        "ebitda": 29901,
        "net_income": 3050,
    },
}

CT_2022_SOURCES_BY_PERIOD = {
    "Q1 2022": CT_2022_Q1_SOURCES,
    "Q2 2022": CT_2022_Q2_SOURCES,
    "Q3 2022": CT_2022_Q3_SOURCES,
    "Q4 2022": CT_2022_Q4_SOURCES,
}

CT_2022_SOURCE_LABEL_BY_PERIOD = {
    "Q1 2022": ("中国电信2022年第一季度报告", CT_2022_Q1_HKEX_URL, "一季报直接披露Q1核心经营数据。"),
    "Q2 2022": ("中国电信2022中期报告减一季度报告", CT_2022_H1_HKEX_URL, "H1累计值减Q1累计值复算Q2核心经营数据。"),
    "Q3 2022": ("中国电信2022前三季度报告减中期报告", CT_2022_Q3_HKEX_URL, "9M累计值减H1累计值复算Q3核心经营数据。"),
    "Q4 2022": ("中国电信2022年报减前三季度报告", CT_2022_ANNUAL_REPORT_URL, "FY累计值减9M累计值复算Q4核心经营数据。"),
}

CT_2022_OFFICIAL_VERIFICATIONS = [
    _official_record(
        "中国电信",
        period,
        metric_key,
        value,
        "millions CNY",
        CT_2022_SOURCE_LABEL_BY_PERIOD[period][0],
        CT_2022_SOURCE_LABEL_BY_PERIOD[period][1],
        f"{CT_2022_SOURCE_LABEL_BY_PERIOD[period][2]}官方值：{metric_key}={value}百万元。",
        "official_cumulative_report_quarter_reconciliation",
        CT_2022_SOURCES_BY_PERIOD[period],
    )
    for period, metrics in CT_2022_QUARTERLY_METRICS.items()
    for metric_key, value in metrics.items()
]

CT_2022_DETAIL_PERIOD_SOURCE = {
    "Q1 2022": ("中国电信2022年第一季度报告", CT_2022_Q1_HKEX_URL, "official_quarterly_statement_check", CT_2022_Q1_SOURCES),
    "Q2 2022": ("中国电信2022中期报告减一季度报告", CT_2022_H1_HKEX_URL, "official_h1_minus_q1_reconciliation", CT_2022_Q2_SOURCES),
    "Q3 2022": ("中国电信2022前三季度报告减中期报告", CT_2022_Q3_HKEX_URL, "official_9m_minus_h1_reconciliation", CT_2022_Q3_SOURCES),
    "Q4 2022": ("中国电信2022年报减前三季度报告", CT_2022_ANNUAL_REPORT_URL, "official_fy_minus_9m_reconciliation", CT_2022_Q4_SOURCES),
}

CT_2022_DETAIL_METRICS = {
    "Q1 2022": {
        "capital_expenditures": (-15669, "millions CNY", "一季报现金流量表披露Q1资本开支15,669百万元，现金流出口径记为负数。"),
        "cash_and_equivalents": (69698, "millions CNY", "一季报合并资产负债表及现金流量表披露2022年3月31日现金及现金等价物69,698百万元。"),
        "ebitda_margin": (29.413, "percent", "一季报披露Q1 EBITDA 32,361百万元、服务收入110,024百万元；按中国电信定义EBITDA/service revenue复算为29.413%，公告列示29.4%。"),
        "free_cash_flow": (11944, "millions CNY", "Q1经营现金流27,613百万元减资本开支15,669百万元，复算普通自由现金流为11,944百万元。"),
        "operating_cash_flow": (27613, "millions CNY", "一季报现金流量表披露Q1经营活动现金流净额27,613百万元。"),
        "operating_income": (9112, "millions CNY", "一季报利润表披露Q1经营利润9,112百万元。"),
        "operating_margin": (7.617, "percent", "Q1经营利润9,112百万元除以营业收入119,629百万元，复算经营利润率为7.617%。"),
        "revenue_growth_yoy": (11.94, "percent", "一季报主要财务资料表披露Q1营业收入119,629百万元，同比增加11.94%。"),
        "total_assets": (768146, "millions CNY", "一季报资产负债表披露2022年3月31日资产总计768,146百万元。"),
        "total_debt": (50749, "millions CNY", "一季报资产负债表披露短期债务2,851、流动长期债务3,122、长期债务4,930、流动租赁负债12,735、非流动租赁负债27,111百万元，合计50,749百万元。"),
    },
    "Q2 2022": {
        "capital_expenditures": (-11514, "millions CNY", "中期报告现金流量表披露H1资本开支27,183百万元；扣除Q1 15,669百万元后，Q2为11,514百万元，现金流出口径记为负数。"),
        "cash_and_equivalents": (76836, "millions CNY", "中期报告资产负债表及现金流量表披露2022年6月30日现金及现金等价物76,836百万元。"),
        "ebitda_margin": (33.660, "percent", "H1 EBITDA 69,848百万元扣除Q1 32,361百万元后，Q2 EBITDA为37,487百万元；H1服务收入221,384百万元扣除Q1 110,024百万元后，Q2服务收入111,360百万元，复算EBITDA率33.660%。"),
        "free_cash_flow": (25970, "millions CNY", "Q2经营现金流37,484百万元减资本开支11,514百万元，复算普通自由现金流为25,970百万元。"),
        "operating_cash_flow": (37484, "millions CNY", "H1经营现金流65,097百万元扣除Q1 27,613百万元后，Q2为37,484百万元。"),
        "operating_income": (14001, "millions CNY", "H1经营利润23,113百万元扣除Q1经营利润9,112百万元后，Q2经营利润为14,001百万元。"),
        "operating_margin": (11.411, "percent", "Q2经营利润14,001百万元除以Q2营业收入122,690百万元，复算经营利润率为11.411%。"),
        "revenue_growth_yoy": (9.190, "percent", "H1 2022营业收入242,319百万元扣除Q1 119,629百万元得Q2 122,690百万元；H1 2021营业收入219,237百万元扣除Q1 106,873百万元得Q2 112,364百万元，复算同比9.190%。"),
        "total_assets": (783849, "millions CNY", "中期报告资产负债表披露2022年6月30日资产总计783,849百万元。"),
        "total_debt": (49196, "millions CNY", "中期报告披露短期债务2,841、流动长期债务3,135、长期债务4,921、流动租赁负债11,362、非流动租赁负债26,937百万元，合计49,196百万元。"),
    },
    "Q3 2022": {
        "capital_expenditures": (-33068, "millions CNY", "前三季度报告现金流量表披露9M资本开支60,251百万元；扣除H1 27,183百万元后，Q3为33,068百万元，现金流出口径记为负数。"),
        "cash_and_equivalents": (79412, "millions CNY", "前三季度报告资产负债表及现金流量表披露2022年9月30日现金及现金等价物79,412百万元。"),
        "ebitda_margin": (28.550, "percent", "9M EBITDA 100,458百万元扣除H1 69,848百万元后，Q3 EBITDA为30,610百万元；9M服务收入328,601百万元扣除H1 221,384百万元后，Q3服务收入107,217百万元，复算EBITDA率28.550%。"),
        "free_cash_flow": (17853, "millions CNY", "Q3经营现金流50,921百万元减资本开支33,068百万元，复算普通自由现金流为17,853百万元。"),
        "operating_cash_flow": (50921, "millions CNY", "9M经营现金流116,018百万元扣除H1 65,097百万元后，Q3为50,921百万元。"),
        "operating_income": (7204, "millions CNY", "9M经营利润30,317百万元扣除H1经营利润23,113百万元后，Q3经营利润为7,204百万元。"),
        "operating_margin": (6.071, "percent", "Q3经营利润7,204百万元除以Q3营业收入118,663百万元，复算经营利润率为6.071%。"),
        "revenue_growth_yoy": (7.9, "percent", "前三季度报告主要财务资料表披露Q3营业收入118,663百万元，同比增加7.9%。"),
        "total_assets": (784593, "millions CNY", "前三季度报告资产负债表披露2022年9月30日资产总计784,593百万元。"),
        "total_debt": (44538, "millions CNY", "前三季度报告披露短期债务2,791、流动长期债务3,147、长期债务4,516、流动租赁负债10,075、非流动租赁负债24,009百万元，合计44,538百万元。"),
    },
    "Q4 2022": {
        "capital_expenditures": (-29454, "millions CNY", "年报现金流量表披露全年资本开支89,705百万元；扣除9M 60,251百万元后，Q4为29,454百万元，现金流出口径记为负数。"),
        "cash_and_equivalents": (72465, "millions CNY", "年报资产负债表及现金流量表披露2022年12月31日现金及现金等价物72,465百万元。"),
        "ebitda_margin": (28.122, "percent", "FY EBITDA 130,359百万元扣除9M 100,458百万元后，Q4 EBITDA为29,901百万元；FY服务收入434,928百万元扣除9M 328,601百万元后，Q4服务收入106,327百万元，复算EBITDA率28.122%。"),
        "free_cash_flow": (-9040, "millions CNY", "Q4经营现金流20,414百万元减资本开支29,454百万元，复算普通自由现金流为-9,040百万元。"),
        "operating_cash_flow": (20414, "millions CNY", "全年经营现金流136,432百万元扣除9M 116,018百万元后，Q4为20,414百万元。"),
        "operating_income": (3110, "millions CNY", "全年经营利润33,427百万元扣除9M经营利润30,317百万元后，Q4经营利润为3,110百万元。"),
        "operating_margin": (2.581, "percent", "Q4经营利润3,110百万元除以Q4营业收入120,466百万元，复算经营利润率为2.581%。"),
        "revenue_growth_yoy": (9.203, "percent", "FY 2022营业收入481,448百万元扣除9M 2022的360,982百万元得Q4 120,466百万元；FY 2021营业收入439,553百万元扣除9M 2021的329,241百万元得Q4 110,312百万元，复算同比9.203%。"),
        "total_assets": (807698, "millions CNY", "年报资产负债表披露2022年12月31日资产总计807,698百万元。"),
        "total_debt": (77380, "millions CNY", "年报披露总有息债务10,484百万元，资本结构附注披露租赁负债66,896百万元；按标准化总债务口径合计77,380百万元。"),
    },
}

CT_2022_DETAIL_OFFICIAL_VERIFICATIONS = [
    _official_record(
        "中国电信",
        period,
        metric_key,
        value,
        unit,
        CT_2022_DETAIL_PERIOD_SOURCE[period][0],
        CT_2022_DETAIL_PERIOD_SOURCE[period][1],
        evidence,
        CT_2022_DETAIL_PERIOD_SOURCE[period][2],
        CT_2022_DETAIL_PERIOD_SOURCE[period][3],
    )
    for period, metrics in CT_2022_DETAIL_METRICS.items()
    for metric_key, (value, unit, evidence) in metrics.items()
]

CT_2022_SOURCE_GAP_CONFIRMATIONS = [
    {
        "subject": "中国电信",
        "period": period,
        "metric_key": metric_key,
        "source_label": CT_2022_DETAIL_PERIOD_SOURCE[period][0],
        "source_url": CT_2022_DETAIL_PERIOD_SOURCE[period][1],
        "evidence": (
            f"{period} 中国电信官方Q1/H1/9M/FY财务报表已核验；"
            f"公司按电信运营商口径披露营业收入、运营费用、经营利润、EBITDA、资本开支和现金流，"
            f"未披露可直接对应 {METRIC_ZH_BY_KEY.get(metric_key, metric_key)} 的同口径毛利表项。"
        ),
        "verification_method": "official_disclosure_gap_check",
        "verification_sources": CT_2022_DETAIL_PERIOD_SOURCE[period][3],
        "verification_note": "中国电信官方报表未披露同口径毛利/毛利率；正式回答只能说明披露缺口，不得引用标准化表估算值。",
    }
    for period in ["Q1 2022", "Q2 2022", "Q3 2022", "Q4 2022"]
    for metric_key in ["gross_profit", "gross_margin"]
]

CT_2021_QUARTERLY_METRICS = {
    "Q1 2021": {
        "revenue": 106873,
        "ebitda": 31052,
        "net_income": 6441,
    },
    "Q2 2021": {
        "revenue": 112364,
        "ebitda": 35296,
        "net_income": 11302,
    },
    "Q3 2021": {
        "revenue": 110004,
        "ebitda": 30000,
        "net_income": 5584,
    },
    "Q4 2021": {
        "revenue": 110311,
        "ebitda": 27564,
        "net_income": 2621,
    },
}

CT_2021_SOURCES_BY_PERIOD = {
    "Q1 2021": CT_2021_Q1_SOURCES,
    "Q2 2021": CT_2021_Q2_SOURCES,
    "Q3 2021": CT_2021_Q3_SOURCES,
    "Q4 2021": CT_2021_Q4_SOURCES,
}

CT_2021_SOURCE_LABEL_BY_PERIOD = {
    "Q1 2021": ("中国电信2021年第一季度报告", CT_2021_Q1_HKEX_URL, "一季度报告直接披露Q1核心经营数据。"),
    "Q2 2021": ("中国电信2021中期报告减一季度报告", CT_2021_H1_HKEX_URL, "H1累计值减Q1累计值复算Q2核心经营数据。"),
    "Q3 2021": ("中国电信2021前三季度报告减中期报告", CT_2021_Q3_HKEX_URL, "9M累计值减H1累计值复算Q3核心经营数据。"),
    "Q4 2021": ("中国电信2021年报减前三季度报告", CT_2021_ANNUAL_REPORT_URL, "FY累计值减9M累计值复算Q4核心经营数据。"),
}

CT_2021_OFFICIAL_VERIFICATIONS = [
    _official_record(
        "中国电信",
        period,
        metric_key,
        value,
        "millions CNY",
        CT_2021_SOURCE_LABEL_BY_PERIOD[period][0],
        CT_2021_SOURCE_LABEL_BY_PERIOD[period][1],
        f"{CT_2021_SOURCE_LABEL_BY_PERIOD[period][2]}官方值：{metric_key}={value}百万元。",
        "official_cumulative_report_quarter_reconciliation",
        CT_2021_SOURCES_BY_PERIOD[period],
    )
    for period, metrics in CT_2021_QUARTERLY_METRICS.items()
    for metric_key, value in metrics.items()
]

CT_2021_DETAIL_PERIOD_SOURCE = {
    "Q2 2021": ("中国电信2021中期报告减一季度/比较栏", CT_2021_H1_HKEX_URL, "official_h1_minus_q1_reconciliation", [*CT_2021_Q2_SOURCES, *CT_2022_Q1_SOURCES]),
    "Q3 2021": ("中国电信2021前三季度报告减中期报告", CT_2021_Q3_HKEX_URL, "official_9m_minus_h1_reconciliation", CT_2021_Q3_SOURCES),
    "Q4 2021": ("中国电信2021年报减前三季度报告", CT_2021_ANNUAL_REPORT_URL, "official_fy_minus_9m_reconciliation", CT_2021_Q4_SOURCES),
}

CT_2021_DETAIL_METRICS = {
    "Q2 2021": {
        "capital_expenditures": (-16293, "millions CNY", "中期报告现金流量表披露H1资本开支26,843百万元；2022年一季报比较栏披露Q1 2021资本开支10,550百万元，扣除后Q2为16,293百万元，现金流出口径记为负数。"),
        "cash_and_equivalents": (35130, "millions CNY", "中期报告资产负债表及现金流量表披露2021年6月30日现金及现金等价物35,130百万元。"),
        "ebitda_margin": (34.128, "percent", "H1 EBITDA 66,348百万元扣除Q1 31,052百万元后，Q2 EBITDA为35,296百万元；H1服务收入203,502百万元扣除Q1 100,078百万元后，Q2服务收入103,424百万元，复算EBITDA率34.128%。"),
        "free_cash_flow": (23576, "millions CNY", "Q2经营现金流40,869百万元减资本开支16,293百万元，复算普通自由现金流为23,576百万元。"),
        "operating_cash_flow": (40869, "millions CNY", "H1经营现金流67,635百万元扣除Q1 26,766百万元后，Q2为40,869百万元。"),
        "operating_income": (12715, "millions CNY", "H1经营利润21,251百万元扣除Q1经营利润8,536百万元后，Q2经营利润为12,715百万元。"),
        "operating_margin": (11.315, "percent", "Q2经营利润12,715百万元除以Q2营业收入112,364百万元，复算经营利润率为11.315%。"),
        "revenue_growth_yoy": (13.487, "percent", "H1 2021营业收入219,237百万元扣除Q1 106,873百万元得Q2 112,364百万元；H1 2020营业收入193,803百万元扣除Q1 94,793百万元得Q2 99,010百万元，复算同比13.487%。"),
        "total_assets": (706478, "millions CNY", "中期报告资产负债表披露2021年6月30日资产总计706,478百万元。"),
        "total_debt": (69044, "millions CNY", "中期报告披露短期债务14,726、流动长期债务6,132、长期债务11,782、流动租赁负债13,185、非流动租赁负债23,219百万元，合计69,044百万元。"),
    },
    "Q3 2021": {
        "capital_expenditures": (-30262, "millions CNY", "前三季度报告现金流量表披露9M资本开支57,105百万元；扣除H1 26,843百万元后，Q3为30,262百万元，现金流出口径记为负数。"),
        "cash_and_equivalents": (85644, "millions CNY", "前三季度报告资产负债表及现金流量表披露2021年9月30日现金及现金等价物85,644百万元。"),
        "ebitda_margin": (29.771, "percent", "9M EBITDA 96,348百万元扣除H1 66,348百万元后，Q3 EBITDA为30,000百万元；9M服务收入304,271百万元扣除H1 203,502百万元后，Q3服务收入100,769百万元，复算EBITDA率29.771%。"),
        "free_cash_flow": (22033, "millions CNY", "Q3经营现金流52,295百万元减资本开支30,262百万元，复算普通自由现金流为22,033百万元。"),
        "operating_cash_flow": (52295, "millions CNY", "9M经营现金流119,930百万元扣除H1 67,635百万元后，Q3为52,295百万元。"),
        "operating_income": (7003, "millions CNY", "9M经营利润28,254百万元扣除H1经营利润21,251百万元后，Q3经营利润为7,003百万元。"),
        "operating_margin": (6.366, "percent", "Q3经营利润7,003百万元除以Q3营业收入110,004百万元，复算经营利润率为6.366%。"),
        "revenue_growth_yoy": (11.3, "percent", "前三季度报告主要财务资料表披露Q3营业收入110,004百万元，同比增加11.3%。"),
        "total_assets": (763268, "millions CNY", "前三季度报告资产负债表披露2021年9月30日资产总计763,268百万元。"),
        "total_debt": (52676, "millions CNY", "前三季度报告披露短期债务4,883、流动长期债务6,133、长期债务7,362、流动租赁负债11,505、非流动租赁负债22,793百万元，合计52,676百万元。"),
    },
    "Q4 2021": {
        "capital_expenditures": (-27742, "millions CNY", "年报现金流量表披露全年资本开支84,847百万元；扣除9M 57,105百万元后，Q4为27,742百万元，现金流出口径记为负数。"),
        "cash_and_equivalents": (73281, "millions CNY", "年报资产负债表及现金流量表披露2021年12月31日现金及现金等价物73,281百万元。"),
        "ebitda_margin": (27.968, "percent", "FY EBITDA 123,912百万元扣除9M 96,348百万元后，Q4 EBITDA为27,564百万元；FY服务收入402,827百万元扣除9M 304,271百万元后，Q4服务收入98,556百万元，复算EBITDA率27.968%。"),
        "free_cash_flow": (-10139, "millions CNY", "Q4经营现金流17,603百万元减资本开支27,742百万元，复算普通自由现金流为-10,139百万元。"),
        "operating_cash_flow": (17603, "millions CNY", "全年经营现金流137,533百万元扣除9M 119,930百万元后，Q4为17,603百万元。"),
        "operating_income": (2693, "millions CNY", "全年经营利润30,947百万元扣除9M经营利润28,254百万元后，Q4经营利润为2,693百万元。"),
        "operating_margin": (2.441, "percent", "Q4经营利润2,693百万元除以Q4营业收入110,311百万元，复算经营利润率为2.441%。"),
        "revenue_growth_yoy": (9.276, "percent", "FY 2021营业收入439,552百万元扣除9M 2021的329,241百万元得Q4 110,311百万元；FY 2020营业收入393,561百万元扣除9M 2020的292,614百万元得Q4 100,947百万元，复算同比9.276%。"),
        "total_assets": (762234, "millions CNY", "年报资产负债表披露2021年12月31日资产总计762,234百万元。"),
        "total_debt": (58898, "millions CNY", "年报披露短期债务2,821、流动长期债务6,280、长期债务7,395、流动租赁负债13,809、非流动租赁负债28,593百万元，合计58,898百万元。"),
    },
}

CT_2021_DETAIL_OFFICIAL_VERIFICATIONS = [
    _official_record(
        "中国电信",
        period,
        metric_key,
        value,
        unit,
        CT_2021_DETAIL_PERIOD_SOURCE[period][0],
        CT_2021_DETAIL_PERIOD_SOURCE[period][1],
        evidence,
        CT_2021_DETAIL_PERIOD_SOURCE[period][2],
        CT_2021_DETAIL_PERIOD_SOURCE[period][3],
    )
    for period, metrics in CT_2021_DETAIL_METRICS.items()
    for metric_key, (value, unit, evidence) in metrics.items()
]

CT_2021_SOURCE_GAP_CONFIRMATIONS = [
    {
        "subject": "中国电信",
        "period": period,
        "metric_key": metric_key,
        "source_label": CT_2021_DETAIL_PERIOD_SOURCE[period][0],
        "source_url": CT_2021_DETAIL_PERIOD_SOURCE[period][1],
        "evidence": (
            f"{period} 中国电信官方Q1/H1/9M/FY财务报表已核验；"
            f"公司未披露可直接对应 {METRIC_ZH_BY_KEY.get(metric_key, metric_key)} 的同口径毛利表项。"
        ),
        "verification_method": "official_disclosure_gap_check",
        "verification_sources": CT_2021_DETAIL_PERIOD_SOURCE[period][3],
        "verification_note": "中国电信官方报表未披露同口径毛利/毛利率；正式回答只能说明披露缺口，不得引用标准化表估算值。",
    }
    for period in ["Q2 2021", "Q3 2021", "Q4 2021"]
    for metric_key in ["gross_profit", "gross_margin"]
]

CT_2020_QUARTERLY_METRICS = {
    "Q1 2020": {
        "revenue": 94793,
        "service_revenue": 92137,
        "ebitda": 30161,
        "ebitda_margin": 32.735,
        "net_income": 5822,
    },
    "Q2 2020": {
        "revenue": 99010,
        "service_revenue": 94973,
        "ebitda": 32993,
        "ebitda_margin": 34.739,
        "net_income": 8127,
    },
    "Q3 2020": {
        "revenue": 98811,
        "service_revenue": 93758,
        "ebitda": 29056,
        "ebitda_margin": 30.990,
        "net_income": 4757,
    },
    "Q4 2020": {
        "revenue": 100947,
        "service_revenue": 92930,
        "ebitda": 26670,
        "ebitda_margin": 28.699,
        "net_income": 2144,
    },
}

CT_2020_SOURCES_BY_PERIOD = {
    "Q1 2020": CT_2020_Q1_SOURCES,
    "Q2 2020": CT_2020_Q2_SOURCES,
    "Q3 2020": CT_2020_Q3_SOURCES,
    "Q4 2020": CT_2020_Q4_SOURCES,
}

CT_2020_SOURCE_LABEL_BY_PERIOD = {
    "Q1 2020": ("中国电信2020年第一季度报告", CT_2020_Q1_HKEX_URL, "一季度报告直接披露Q1核心经营数据。"),
    "Q2 2020": ("中国电信2020中期报告减一季度报告", CT_2020_H1_HKEX_URL, "H1累计值减Q1累计值复算Q2核心经营数据。"),
    "Q3 2020": ("中国电信2020前三季度报告减中期报告", CT_2020_Q3_HKEX_URL, "9M累计值减H1累计值复算Q3核心经营数据。"),
    "Q4 2020": ("中国电信2020全年业绩减前三季度报告", CT_2020_ANNUAL_PRESENTATION_URL, "FY累计值减9M累计值复算Q4核心经营数据。"),
}

CT_2020_METRIC_EVIDENCE = {
    "revenue": "{source_note}官方值：operating revenue={value}百万元。",
    "service_revenue": "{source_note}官方值：service revenue={value}百万元。",
    "ebitda": "{source_note}官方值：EBITDA={value}百万元。",
    "ebitda_margin": "{source_note}按中国电信定义 EBITDA/service revenue 复算 EBITDA margin={value}%。",
    "net_income": "{source_note}官方值：profit attributable to equity holders={value}百万元。",
}

CT_2020_OFFICIAL_VERIFICATIONS = [
    _official_record(
        "中国电信",
        period,
        metric_key,
        value,
        "percent" if metric_key == "ebitda_margin" else "millions CNY",
        CT_2020_SOURCE_LABEL_BY_PERIOD[period][0],
        CT_2020_SOURCE_LABEL_BY_PERIOD[period][1],
        CT_2020_METRIC_EVIDENCE[metric_key].format(
            source_note=CT_2020_SOURCE_LABEL_BY_PERIOD[period][2],
            value=value,
        ),
        "official_cumulative_report_quarter_reconciliation",
        CT_2020_SOURCES_BY_PERIOD[period],
    )
    for period, metrics in CT_2020_QUARTERLY_METRICS.items()
    for metric_key, value in metrics.items()
]

CT_2016_2018_SOURCES_BY_PERIOD = {
    "Q1 2016": [
        {"label": "中国电信2016年第一季度报告（IRAsia）", "url": CT_2016_Q1_HKEX_URL, "evidence": "一季度报告直接披露Q1 operating revenues 86,426、service revenues 76,359、EBITDA 23,811和股东应占利润5,119百万元。"},
        {"label": "中国电信2016中期报告（公司官网）", "url": CT_2016_H1_HKEX_URL, "evidence": "中期报告披露H1 operating revenues 176,828、EBITDA 50,555和股东应占利润11,673百万元，用于交叉核验Q1+Q2。"},
        {"label": "中国电信2016年报（公司官网）", "url": CT_2016_ANNUAL_REPORT_URL, "evidence": "年报披露FY2016 operating revenues 352,285、service revenues 309,644、EBITDA 95,139和股东应占利润18,004百万元，用于全年链路交叉核验。"},
    ],
    "Q2 2016": [
        {"label": "中国电信2016年第一季度报告（IRAsia）", "url": CT_2016_Q1_HKEX_URL, "evidence": "一季度累计值用于从H1累计值复算Q2。"},
        {"label": "中国电信2016中期报告（公司官网）", "url": CT_2016_H1_HKEX_URL, "evidence": "中期报告披露H1 operating revenues 176,828、EBITDA 50,555和股东应占利润11,673百万元。"},
        {"label": "中国电信2016年报（公司官网）", "url": CT_2016_ANNUAL_REPORT_URL, "evidence": "年报披露全年核心值，用于交叉核验H1与全年合计。"},
    ],
    "Q3 2016": [
        {"label": "中国电信2016中期报告（公司官网）", "url": CT_2016_H1_HKEX_URL, "evidence": "H1累计值用于从9M累计值复算Q3。"},
        {"label": "中国电信2016年前三季度报告（IRAsia）", "url": CT_2016_Q3_HKEX_URL, "evidence": "前三季度报告披露9M operating revenues 263,816、service revenues 233,494、EBITDA 76,033和股东应占利润17,543百万元。"},
        {"label": "中国电信2016年报（公司官网）", "url": CT_2016_ANNUAL_REPORT_URL, "evidence": "年报披露全年核心值，用于交叉核验9M与全年合计。"},
    ],
    "Q4 2016": [
        {"label": "中国电信2016年前三季度报告（IRAsia）", "url": CT_2016_Q3_HKEX_URL, "evidence": "前三季度累计值用于从FY累计值复算Q4。"},
        {"label": "中国电信2016年报（公司官网）", "url": CT_2016_ANNUAL_REPORT_URL, "evidence": "年报披露FY2016 operating revenues 352,285、service revenues 309,644、EBITDA 95,139和股东应占利润18,004百万元。"},
        {"label": "中国电信2017年报比较栏（公司官网）", "url": CT_2017_ANNUAL_REPORT_URL, "evidence": "2017年报财务回顾比较栏列示2016全年 operating revenue、service revenue、EBITDA 和股东应占利润，用于年度值交叉核验。"},
    ],
    "Q1 2017": [
        {"label": "中国电信2017年第一季度报告（IRAsia）", "url": CT_2017_Q1_HKEX_URL, "evidence": "一季度报告直接披露Q1 operating revenues 91,428、service revenues 82,094、EBITDA 24,815和股东应占利润5,348百万元。"},
        {"label": "中国电信2017中期报告（公司官网）", "url": CT_2017_H1_HKEX_URL, "evidence": "中期报告披露H1 operating revenues 184,118、service revenues 165.8十亿元、EBITDA 52,414和股东应占利润12,537百万元。"},
        {"label": "中国电信2017年前三季度报告（IRAsia）", "url": CT_2017_Q3_HKEX_URL, "evidence": "前三季度报告披露9M核心累计值，用于全年链路交叉核验。"},
    ],
    "Q2 2017": [
        {"label": "中国电信2017年第一季度报告（IRAsia）", "url": CT_2017_Q1_HKEX_URL, "evidence": "一季度累计值用于从H1累计值复算Q2。"},
        {"label": "中国电信2017中期报告（公司官网）", "url": CT_2017_H1_HKEX_URL, "evidence": "中期报告披露H1 operating revenues 184,118、service revenues 165.8十亿元、EBITDA 52,414和股东应占利润12,537百万元。"},
        {"label": "中国电信2017年报（公司官网）", "url": CT_2017_ANNUAL_REPORT_URL, "evidence": "年报披露FY2017 operating revenues 366,229、service revenues 331,044、EBITDA 102,171和股东应占利润18,617百万元。"},
    ],
    "Q3 2017": [
        {"label": "中国电信2017中期报告（公司官网）", "url": CT_2017_H1_HKEX_URL, "evidence": "H1累计值用于从9M累计值复算Q3。"},
        {"label": "中国电信2017年前三季度报告（IRAsia）", "url": CT_2017_Q3_HKEX_URL, "evidence": "前三季度报告披露9M operating revenues 274,702、service revenues 249,722、EBITDA 78,844和股东应占利润18,502百万元。"},
        {"label": "中国电信2017年报（公司官网）", "url": CT_2017_ANNUAL_REPORT_URL, "evidence": "年报披露全年核心值，用于交叉核验9M与全年合计。"},
    ],
    "Q4 2017": [
        {"label": "中国电信2017年前三季度报告（IRAsia）", "url": CT_2017_Q3_HKEX_URL, "evidence": "前三季度累计值用于从FY累计值复算Q4。"},
        {"label": "中国电信2017年报（公司官网）", "url": CT_2017_ANNUAL_REPORT_URL, "evidence": "年报披露FY2017 operating revenues 366,229、service revenues 331,044、EBITDA 102,171和股东应占利润18,617百万元。"},
        {"label": "中国电信2018年报比较栏（公司官网）", "url": CT_2018_ANNUAL_REPORT_URL, "evidence": "2018年报比较栏列示2017全年核心值；2018采用IFRS 15，当期2017比较数只作交叉核验，不混入口径。"},
    ],
    "Q1 2018": [
        {"label": "中国电信2018年第一季度报告（IRAsia）", "url": CT_2018_Q1_HKEX_URL, "evidence": "一季度报告直接披露Q1 operating revenues 96,613、service revenues 87,967、EBITDA 26,508和股东应占利润5,698百万元。"},
        {"label": "中国电信2018中期报告（公司官网）", "url": CT_2018_H1_HKEX_URL, "evidence": "中期报告披露H1 operating revenues 193,029、service revenues 177,588、EBITDA 55,858和股东应占利润13,570百万元。"},
        {"label": "中国电信2018年前三季度报告（IRAsia）", "url": CT_2018_Q3_HKEX_URL, "evidence": "前三季度报告披露9M核心累计值，用于全年链路交叉核验。"},
    ],
    "Q2 2018": [
        {"label": "中国电信2018年第一季度报告（IRAsia）", "url": CT_2018_Q1_HKEX_URL, "evidence": "一季度累计值用于从H1累计值复算Q2。"},
        {"label": "中国电信2018中期报告（公司官网）", "url": CT_2018_H1_HKEX_URL, "evidence": "中期报告披露H1 operating revenues 193,029、service revenues 177,588、EBITDA 55,858和股东应占利润13,570百万元。"},
        {"label": "中国电信2018年报（公司官网）", "url": CT_2018_ANNUAL_REPORT_URL, "evidence": "年报披露FY2018 operating revenues 377,124、service revenues 350,434、EBITDA 104,207和股东应占利润21,210百万元。"},
    ],
    "Q3 2018": [
        {"label": "中国电信2018中期报告（公司官网）", "url": CT_2018_H1_HKEX_URL, "evidence": "H1累计值用于从9M累计值复算Q3。"},
        {"label": "中国电信2018年前三季度报告（IRAsia）", "url": CT_2018_Q3_HKEX_URL, "evidence": "前三季度报告披露9M operating revenues 284,971、service revenues 264,934、EBITDA 80,819和股东应占利润19,034百万元。"},
        {"label": "中国电信2018年报（公司官网）", "url": CT_2018_ANNUAL_REPORT_URL, "evidence": "年报披露全年核心值，用于交叉核验9M与全年合计。"},
    ],
    "Q4 2018": [
        {"label": "中国电信2018年前三季度报告（IRAsia）", "url": CT_2018_Q3_HKEX_URL, "evidence": "前三季度累计值用于从FY累计值复算Q4。"},
        {"label": "中国电信2018年报（公司官网）", "url": CT_2018_ANNUAL_REPORT_URL, "evidence": "年报披露FY2018 operating revenues 377,124、service revenues 350,434、EBITDA 104,207和股东应占利润21,210百万元。"},
        {"label": "中国电信2019年报财务回顾（公司官网）", "url": CT_2019_ANNUAL_FINANCIAL_REVIEW_URL, "evidence": "2019年报财务回顾列示2018全年核心值，用于年度值交叉核验。"},
    ],
}

CT_2016_2018_SOURCE_LABEL_BY_PERIOD = {
    "Q1 2016": ("中国电信2016年第一季度报告", CT_2016_Q1_HKEX_URL, "一季度报告直接披露Q1核心经营数据。"),
    "Q2 2016": ("中国电信2016中期报告减一季度报告", CT_2016_H1_HKEX_URL, "H1累计值减Q1累计值复算Q2核心经营数据。"),
    "Q3 2016": ("中国电信2016前三季度报告减中期报告", CT_2016_Q3_HKEX_URL, "9M累计值减H1累计值复算Q3核心经营数据；2016 H1 service revenue 仅以RMB155.2 billion四舍五入披露，因此不写入2016 Q2/Q3 service_revenue与EBITDA margin。"),
    "Q4 2016": ("中国电信2016年报减前三季度报告", CT_2016_ANNUAL_REPORT_URL, "FY累计值减9M累计值复算Q4核心经营数据。"),
    "Q1 2017": ("中国电信2017年第一季度报告", CT_2017_Q1_HKEX_URL, "一季度报告直接披露Q1核心经营数据。"),
    "Q2 2017": ("中国电信2017中期报告减一季度报告", CT_2017_H1_HKEX_URL, "H1累计值减Q1累计值复算Q2核心经营数据。"),
    "Q3 2017": ("中国电信2017前三季度报告减中期报告", CT_2017_Q3_HKEX_URL, "9M累计值减H1累计值复算Q3核心经营数据。"),
    "Q4 2017": ("中国电信2017年报减前三季度报告", CT_2017_ANNUAL_REPORT_URL, "FY累计值减9M累计值复算Q4核心经营数据。"),
    "Q1 2018": ("中国电信2018年第一季度报告", CT_2018_Q1_HKEX_URL, "一季度报告直接披露Q1核心经营数据。"),
    "Q2 2018": ("中国电信2018中期报告减一季度报告", CT_2018_H1_HKEX_URL, "H1累计值减Q1累计值复算Q2核心经营数据。"),
    "Q3 2018": ("中国电信2018前三季度报告减中期报告", CT_2018_Q3_HKEX_URL, "9M累计值减H1累计值复算Q3核心经营数据。"),
    "Q4 2018": ("中国电信2018年报减前三季度报告", CT_2018_ANNUAL_REPORT_URL, "FY累计值减9M累计值复算Q4核心经营数据。"),
}

CT_2016_2018_QUARTERLY_METRICS = {
    "Q1 2016": {"revenue": 86426, "service_revenue": 76359, "ebitda": 23811, "ebitda_margin": 31.183, "net_income": 5119},
    "Q2 2016": {"revenue": 90402, "ebitda": 26744, "net_income": 6554},
    "Q3 2016": {"revenue": 86988, "ebitda": 25478, "net_income": 5870},
    "Q4 2016": {"revenue": 88469, "service_revenue": 76150, "ebitda": 19106, "ebitda_margin": 25.090, "net_income": 461},
    "Q1 2017": {"revenue": 91428, "service_revenue": 82094, "ebitda": 24815, "ebitda_margin": 30.228, "net_income": 5348},
    "Q2 2017": {"revenue": 92690, "service_revenue": 83706, "ebitda": 27599, "ebitda_margin": 32.971, "net_income": 7189},
    "Q3 2017": {"revenue": 90584, "service_revenue": 83922, "ebitda": 26430, "ebitda_margin": 31.494, "net_income": 5965},
    "Q4 2017": {"revenue": 91527, "service_revenue": 81322, "ebitda": 23327, "ebitda_margin": 28.685, "net_income": 115},
    "Q1 2018": {"revenue": 96613, "service_revenue": 87967, "ebitda": 26508, "ebitda_margin": 30.134, "net_income": 5698},
    "Q2 2018": {"revenue": 96416, "service_revenue": 89621, "ebitda": 29350, "ebitda_margin": 32.749, "net_income": 7872},
    "Q3 2018": {"revenue": 91942, "service_revenue": 87346, "ebitda": 24961, "ebitda_margin": 28.577, "net_income": 5464},
    "Q4 2018": {"revenue": 92153, "service_revenue": 85500, "ebitda": 23388, "ebitda_margin": 27.354, "net_income": 2176},
}

CT_2016_2018_METRIC_EVIDENCE = {
    "revenue": "{source_note}官方Q1/H1/9M/FY累计披露复核该季度 operating revenue={value}百万元。",
    "service_revenue": "{source_note}官方Q1/H1/9M/FY累计披露复核该季度 service revenue={value}百万元。",
    "ebitda": "{source_note}官方Q1/H1/9M/FY累计披露复核该季度 EBITDA={value}百万元。",
    "ebitda_margin": "{source_note}按中国电信定义 EBITDA/service revenue 复算 EBITDA margin={value}%。",
    "net_income": "{source_note}官方Q1/H1/9M/FY累计披露复核该季度 profit attributable to equity holders={value}百万元。",
}

CT_2016_2018_OFFICIAL_VERIFICATIONS = [
    _official_record(
        "中国电信",
        period,
        metric_key,
        value,
        "percent" if metric_key == "ebitda_margin" else "millions CNY",
        CT_2016_2018_SOURCE_LABEL_BY_PERIOD[period][0],
        CT_2016_2018_SOURCE_LABEL_BY_PERIOD[period][1],
        CT_2016_2018_METRIC_EVIDENCE[metric_key].format(
            source_note=CT_2016_2018_SOURCE_LABEL_BY_PERIOD[period][2],
            value=value,
        ),
        "official_cumulative_report_quarter_reconciliation",
        CT_2016_2018_SOURCES_BY_PERIOD[period],
    )
    for period, metrics in CT_2016_2018_QUARTERLY_METRICS.items()
    for metric_key, value in metrics.items()
]

CT_2019_QUARTERLY_METRICS = {
    "Q1 2019": {
        "revenue": 96135,
        "service_revenue": 91531,
        "ebitda": 30238,
        "ebitda_margin": 33.036,
        "net_income": 5956,
    },
    "Q2 2019": {
        "revenue": 94353,
        "service_revenue": 91058,
        "ebitda": 33049,
        "ebitda_margin": 36.294,
        "net_income": 7953,
    },
    "Q3 2019": {
        "revenue": 92338,
        "service_revenue": 88895,
        "ebitda": 28686,
        "ebitda_margin": 32.270,
        "net_income": 4480,
    },
    "Q4 2019": {
        "revenue": 92908,
        "service_revenue": 86126,
        "ebitda": 25242,
        "ebitda_margin": 29.308,
        "net_income": 2128,
    },
}

CT_2019_SOURCES_BY_PERIOD = {
    "Q1 2019": CT_2019_Q1_SOURCES,
    "Q2 2019": CT_2019_Q2_SOURCES,
    "Q3 2019": CT_2019_Q3_SOURCES,
    "Q4 2019": CT_2019_Q4_SOURCES,
}

CT_2019_SOURCE_LABEL_BY_PERIOD = {
    "Q1 2019": ("中国电信2019年第一季度报告", CT_2019_Q1_HKEX_URL, "一季度报告直接披露Q1核心经营数据。"),
    "Q2 2019": ("中国电信2019中期报告减一季度报告", CT_2019_H1_HKEX_URL, "H1累计值减Q1累计值复算Q2核心经营数据。"),
    "Q3 2019": ("中国电信2019前三季度报告减中期报告", CT_2019_Q3_HKEX_URL, "9M累计值减H1累计值复算Q3核心经营数据。"),
    "Q4 2019": ("中国电信2019年报减前三季度报告", CT_2019_ANNUAL_FINANCIAL_REVIEW_URL, "FY累计值减9M累计值复算Q4核心经营数据。"),
}

CT_2019_METRIC_EVIDENCE = {
    "revenue": "{source_note}官方值：operating revenue={value}百万元。",
    "service_revenue": "{source_note}官方值：service revenue={value}百万元。",
    "ebitda": "{source_note}官方值：EBITDA={value}百万元。",
    "ebitda_margin": "{source_note}按中国电信定义 EBITDA/service revenue 复算 EBITDA margin={value}%。",
    "net_income": "{source_note}官方值：profit attributable to equity holders={value}百万元。",
}

CT_2019_OFFICIAL_VERIFICATIONS = [
    _official_record(
        "中国电信",
        period,
        metric_key,
        value,
        "percent" if metric_key == "ebitda_margin" else "millions CNY",
        CT_2019_SOURCE_LABEL_BY_PERIOD[period][0],
        CT_2019_SOURCE_LABEL_BY_PERIOD[period][1],
        CT_2019_METRIC_EVIDENCE[metric_key].format(
            source_note=CT_2019_SOURCE_LABEL_BY_PERIOD[period][2],
            value=value,
        ),
        "official_cumulative_report_quarter_reconciliation",
        CT_2019_SOURCES_BY_PERIOD[period],
    )
    for period, metrics in CT_2019_QUARTERLY_METRICS.items()
    for metric_key, value in metrics.items()
]

CM_2016_2018_CORE_METRICS = {
    "Q1 2016": {"operating_revenue": 177504, "revenue": 177504, "service_revenue": 151599, "ebitda": 65148, "ebitda_margin": 36.702, "net_income": 23948},
    "Q2 2016": {"operating_revenue": 192847, "revenue": 192847, "service_revenue": 173824, "ebitda": 69202, "ebitda_margin": 35.884, "net_income": 36624},
    "Q3 2016": {"operating_revenue": 172313, "revenue": 172313, "service_revenue": 155791, "ebitda": 66048, "ebitda_margin": 38.330, "net_income": 27487},
    "Q4 2016": {"operating_revenue": 165757, "revenue": 165757, "service_revenue": 142208, "ebitda": 56279, "ebitda_margin": 33.952, "net_income": 20682},
    "Q1 2017": {"operating_revenue": 184000, "revenue": 184000, "service_revenue": 160900, "ebitda": 67100, "ebitda_margin": 36.467, "net_income": 24800},
    "Q2 2017": {"operating_revenue": 204900, "revenue": 204900, "service_revenue": 187100, "ebitda": 73600, "ebitda_margin": 35.920, "net_income": 37900},
    "Q3 2017": {"operating_revenue": 180600, "revenue": 180600, "service_revenue": 167300, "ebitda": 70600, "ebitda_margin": 39.091, "net_income": 29400},
    "Q4 2017": {"operating_revenue": 171000, "revenue": 171000, "service_revenue": 153100, "ebitda": 59100, "ebitda_margin": 34.561, "net_income": 22200},
    "Q1 2018": {"operating_revenue": 185500, "revenue": 185500, "service_revenue": 166700, "ebitda": 69700, "ebitda_margin": 37.574, "net_income": 25800},
    "Q2 2018": {"operating_revenue": 206300, "revenue": 206300, "service_revenue": 189400, "ebitda": 76200, "ebitda_margin": 36.937, "net_income": 39800},
    "Q3 2018": {"operating_revenue": 175900, "revenue": 175900, "service_revenue": 162300, "ebitda": 68200, "ebitda_margin": 38.772, "net_income": 29400},
    "Q4 2018": {"operating_revenue": 169100, "revenue": 169100, "service_revenue": 152500, "ebitda": 61400, "ebitda_margin": 36.310, "net_income": 22800},
}

CM_2016_2018_SOURCE_BY_PERIOD = {
    "Q1 2016": ("中国移动官网2016单季度经营数据", CM_2016_OPERATION_URL, [
        {"label": "中国移动官网2016单季度经营数据", "url": CM_2016_OPERATION_URL, "evidence": "官网直接列示2016/1Q Operating Revenue 177,504、Revenue from Telecommunications Services 151,599、EBITDA 65,148和Profit Attributable to Equity Shareholders 23,948百万元。"},
        {"label": "中国移动2016中期报告", "url": CM_2016_INTERIM_REPORT_URL, "evidence": "中期报告披露H1 2016 operating revenue 370,351、telecommunications services revenue 325,423、EBITDA 134,350和股东应占利润60,572百万元，用于交叉核验Q1+Q2。"},
        {"label": "中国移动2016年度报告", "url": CM_2016_ANNUAL_REPORT_URL, "evidence": "年报披露FY2016 operating revenue 708,421、telecommunications services revenue 623,422、EBITDA 256,677和股东应占利润108,741百万元，用于全年合计交叉核验。"},
    ], "官网直接披露2016/1Q核心经营数据；EBITDA margin 由EBITDA除以Operating Revenue复算。"),
    "Q2 2016": ("中国移动官网2016单季度经营数据", CM_2016_OPERATION_URL, [
        {"label": "中国移动官网2016单季度经营数据", "url": CM_2016_OPERATION_URL, "evidence": "官网直接列示2016/2Q核心经营数据。"},
        {"label": "中国移动2016中期报告", "url": CM_2016_INTERIM_REPORT_URL, "evidence": "H1累计值用于交叉核验Q1+Q2。"},
        {"label": "中国移动2016年度报告", "url": CM_2016_ANNUAL_REPORT_URL, "evidence": "年报全年值用于年度合计交叉核验。"},
    ], "官网直接披露2016/2Q核心经营数据；EBITDA margin 由EBITDA除以Operating Revenue复算。"),
    "Q3 2016": ("中国移动官网2016单季度经营数据", CM_2016_OPERATION_URL, [
        {"label": "中国移动官网2016单季度经营数据", "url": CM_2016_OPERATION_URL, "evidence": "官网直接列示2016/3Q核心经营数据。"},
        {"label": "中国移动2016中期报告", "url": CM_2016_INTERIM_REPORT_URL, "evidence": "中期报告披露H1核心值，用于与Q3/Q4及全年链路交叉核验。"},
        {"label": "中国移动2016年度报告", "url": CM_2016_ANNUAL_REPORT_URL, "evidence": "年报披露FY2016核心值，用于交叉核验全年四季度合计。"},
    ], "官网直接披露2016/3Q核心经营数据；EBITDA margin 由EBITDA除以Operating Revenue复算。"),
    "Q4 2016": ("中国移动官网2016单季度经营数据", CM_2016_OPERATION_URL, [
        {"label": "中国移动官网2016单季度经营数据", "url": CM_2016_OPERATION_URL, "evidence": "官网直接列示2016/4Q核心经营数据。"},
        {"label": "中国移动2016年度报告", "url": CM_2016_ANNUAL_REPORT_URL, "evidence": "年报披露FY2016核心值，四个官网季度值合计与年报核心值勾稽。"},
        {"label": "中国移动2017年度报告", "url": CM_2017_ANNUAL_REPORT_URL, "evidence": "2017年报比较栏列示2016全年核心值，用于交叉核验。"},
    ], "官网直接披露2016/4Q核心经营数据；EBITDA margin 由EBITDA除以Operating Revenue复算。"),
    "Q1 2017": ("中国移动官网2017单季度经营数据", CM_2017_OPERATION_URL, [
        {"label": "中国移动官网2017单季度经营数据", "url": CM_2017_OPERATION_URL, "evidence": "官网直接列示2017/1Q核心经营数据，单位为十亿元，已换算为百万元。"},
        {"label": "中国移动2017中期报告", "url": CM_2017_INTERIM_REPORT_URL, "evidence": "中期报告披露H1 2017 operating revenue 388,871、telecommunications services revenue 347,950、EBITDA 140,710和股东应占利润62,675百万元，用于交叉核验Q1+Q2。"},
        {"label": "中国移动2017年度报告", "url": CM_2017_ANNUAL_REPORT_URL, "evidence": "年报披露FY2017 operating revenue 740,514、telecommunications services revenue 668,351、EBITDA 270,421和股东应占利润114,279百万元，用于全年合计交叉核验。"},
    ], "官网直接披露2017/1Q核心经营数据；官网单位为十亿元，已换算为百万元；EBITDA margin 由EBITDA除以Operating Revenue复算。"),
    "Q2 2017": ("中国移动官网2017单季度经营数据", CM_2017_OPERATION_URL, [
        {"label": "中国移动官网2017单季度经营数据", "url": CM_2017_OPERATION_URL, "evidence": "官网直接列示2017/2Q核心经营数据。"},
        {"label": "中国移动2017中期报告", "url": CM_2017_INTERIM_REPORT_URL, "evidence": "H1累计值用于交叉核验Q1+Q2。"},
        {"label": "中国移动2017年度报告", "url": CM_2017_ANNUAL_REPORT_URL, "evidence": "年报全年值用于年度合计交叉核验。"},
    ], "官网直接披露2017/2Q核心经营数据；官网单位为十亿元，已换算为百万元；EBITDA margin 由EBITDA除以Operating Revenue复算。"),
    "Q3 2017": ("中国移动官网2017单季度经营数据", CM_2017_OPERATION_URL, [
        {"label": "中国移动官网2017单季度经营数据", "url": CM_2017_OPERATION_URL, "evidence": "官网直接列示2017/3Q核心经营数据。"},
        {"label": "中国移动2017中期报告", "url": CM_2017_INTERIM_REPORT_URL, "evidence": "中期报告披露H1核心值，用于与Q3/Q4及全年链路交叉核验。"},
        {"label": "中国移动2017年度报告", "url": CM_2017_ANNUAL_REPORT_URL, "evidence": "年报披露FY2017核心值，用于交叉核验全年四季度合计。"},
    ], "官网直接披露2017/3Q核心经营数据；官网单位为十亿元，已换算为百万元；EBITDA margin 由EBITDA除以Operating Revenue复算。"),
    "Q4 2017": ("中国移动官网2017单季度经营数据", CM_2017_OPERATION_URL, [
        {"label": "中国移动官网2017单季度经营数据", "url": CM_2017_OPERATION_URL, "evidence": "官网直接列示2017/4Q核心经营数据。"},
        {"label": "中国移动2017年度报告", "url": CM_2017_ANNUAL_REPORT_URL, "evidence": "年报披露FY2017核心值，四个官网季度值合计与年报核心值勾稽。"},
        {"label": "中国移动2018年度报告", "url": CM_2018_ANNUAL_REPORT_URL, "evidence": "2018年报比较栏列示2017全年核心值；2018采用新收入准则，2017比较栏只作交叉核验，不覆盖原始2017官网季度值。"},
    ], "官网直接披露2017/4Q核心经营数据；官网单位为十亿元，已换算为百万元；EBITDA margin 由EBITDA除以Operating Revenue复算。"),
    "Q1 2018": ("中国移动官网2018单季度经营数据", CM_2018_OPERATION_URL, [
        {"label": "中国移动官网2018单季度经营数据", "url": CM_2018_OPERATION_URL, "evidence": "官网直接列示2018/1Q核心经营数据，单位为十亿元，已换算为百万元。"},
        {"label": "中国移动2018中期报告", "url": CM_2018_INTERIM_REPORT_URL, "evidence": "中期报告披露H1 2018 operating revenue 391,832、telecommunications services revenue 356,120、EBITDA 145,886和股东应占利润65,641百万元，用于交叉核验Q1+Q2。"},
        {"label": "中国移动2018年度报告", "url": CM_2018_ANNUAL_REPORT_URL, "evidence": "年报披露FY2018 operating revenue 736,819、telecommunications services revenue 670,907、EBITDA 275,541和股东应占利润117,781百万元，用于全年合计交叉核验。"},
    ], "官网直接披露2018/1Q核心经营数据；官网单位为十亿元，已换算为百万元；EBITDA margin 由EBITDA除以Operating Revenue复算。"),
    "Q2 2018": ("中国移动官网2018单季度经营数据", CM_2018_OPERATION_URL, [
        {"label": "中国移动官网2018单季度经营数据", "url": CM_2018_OPERATION_URL, "evidence": "官网直接列示2018/2Q核心经营数据。"},
        {"label": "中国移动2018中期报告", "url": CM_2018_INTERIM_REPORT_URL, "evidence": "H1累计值用于交叉核验Q1+Q2。"},
        {"label": "中国移动2018年度报告", "url": CM_2018_ANNUAL_REPORT_URL, "evidence": "年报全年值用于年度合计交叉核验。"},
    ], "官网直接披露2018/2Q核心经营数据；官网单位为十亿元，已换算为百万元；EBITDA margin 由EBITDA除以Operating Revenue复算。"),
    "Q3 2018": ("中国移动官网2018单季度经营数据", CM_2018_OPERATION_URL, [
        {"label": "中国移动官网2018单季度经营数据", "url": CM_2018_OPERATION_URL, "evidence": "官网直接列示2018/3Q核心经营数据。"},
        {"label": "中国移动2018中期报告", "url": CM_2018_INTERIM_REPORT_URL, "evidence": "中期报告披露H1核心值，用于与Q3/Q4及全年链路交叉核验。"},
        {"label": "中国移动2018年度报告", "url": CM_2018_ANNUAL_REPORT_URL, "evidence": "年报披露FY2018核心值，用于交叉核验全年四季度合计。"},
    ], "官网直接披露2018/3Q核心经营数据；官网单位为十亿元，已换算为百万元；EBITDA margin 由EBITDA除以Operating Revenue复算。"),
    "Q4 2018": ("中国移动官网2018单季度经营数据", CM_2018_OPERATION_URL, [
        {"label": "中国移动官网2018单季度经营数据", "url": CM_2018_OPERATION_URL, "evidence": "官网直接列示2018/4Q核心经营数据。"},
        {"label": "中国移动2018年度报告", "url": CM_2018_ANNUAL_REPORT_URL, "evidence": "年报披露FY2018核心值，四个官网季度值合计与年报核心值勾稽。"},
        {"label": "中国移动2019年度报告", "url": CM_2019_ANNUAL_REPORT_URL, "evidence": "2019年报比较栏列示2018全年核心值，用于交叉核验。"},
    ], "官网直接披露2018/4Q核心经营数据；官网单位为十亿元，已换算为百万元；EBITDA margin 由EBITDA除以Operating Revenue复算。"),
}

CM_2016_2018_CORE_OFFICIAL_VERIFICATIONS = [
    _official_record(
        "中国移动",
        period,
        metric_key,
        value,
        "percent" if metric_key == "ebitda_margin" else "millions CNY",
        CM_2016_2018_SOURCE_BY_PERIOD[period][0],
        CM_2016_2018_SOURCE_BY_PERIOD[period][1],
        f"{CM_2016_2018_SOURCE_BY_PERIOD[period][3]}官方值：{metric_key}={value}{'%' if metric_key == 'ebitda_margin' else '百万元'}。",
        "official_quarterly_operating_data_with_interim_fy_reconciliation",
        CM_2016_2018_SOURCE_BY_PERIOD[period][2],
    )
    for period, metrics in CM_2016_2018_CORE_METRICS.items()
    for metric_key, value in metrics.items()
]

CT_2023_SOURCES_BY_PERIOD = {
    "Q1 2023": CT_2023_Q1_SOURCES,
    "Q2 2023": CT_2023_Q2_SOURCES,
    "Q3 2023": CT_2023_Q3_SOURCES,
    "Q4 2023": CT_2023_Q4_SOURCES,
}

CT_2023_OFFICIAL_VERIFICATIONS = [
    _official_record(
        "中国电信",
        period,
        metric_key,
        value,
        "percent" if metric_key == "ebitda_margin" else "millions CNY",
        "中国电信2023官方季度/累计业绩披露",
        CT_2023_SOURCES_BY_PERIOD[period][-1]["url"],
        CT_QUARTERLY_METRIC_EVIDENCE[metric_key].format(
            period_label=period.replace(" ", "/"),
            display_value=value,
        ),
        "official_cumulative_report_quarter_reconciliation",
        CT_2023_SOURCES_BY_PERIOD[period],
    )
    for period, metrics in CT_2023_QUARTERLY_METRICS.items()
    for metric_key, value in metrics.items()
]

CT_2023_DETAIL_OFFICIAL_VERIFICATIONS = [
    _official_record("中国电信", "Q2 2023", "capital_expenditures", -13817.806, "millions CNY", "中国电信2023半年度报告（新浪财经正文）", CT_2023_H1_SINA_URL, "A股H1现金流量表披露购建长期资产现金支出28,325.631百万元，减Q1 14,507.825百万元后，Q2资本开支为13,817.806百万元；现金流出口径记为负数。", "official_h1_minus_q1_capex_reconciliation", CT_2023_Q2_DETAIL_SOURCES),
    _official_record("中国电信", "Q2 2023", "cash_and_equivalents", 83698.046, "millions CNY", "中国电信2023半年度报告（新浪财经正文）", CT_2023_H1_SINA_URL, "A股H1现金流量表披露2023年6月30日期末现金及现金等价物余额83,698.046百万元。", "official_cash_flow_statement_cash_equivalents_check", CT_2023_Q2_DETAIL_SOURCES),
    _official_record("中国电信", "Q2 2023", "free_cash_flow", 23630.885, "millions CNY", "中国电信2023半年度报告（新浪财经正文）", CT_2023_H1_SINA_URL, "A股H1经营现金流65,663.264百万元减Q1经营现金流28,214.572百万元，Q2经营现金流37,448.691百万元；减Q2资本开支13,817.806百万元，普通自由现金流为23,630.885百万元。", "official_operating_cash_flow_minus_capex_reconciliation", CT_2023_Q2_DETAIL_SOURCES),
    _official_record("中国电信", "Q2 2023", "gross_profit", 41311.688, "millions CNY", "中国电信2023半年度报告（新浪财经正文）", CT_2023_H1_SINA_URL, "A股H1营业收入258,679.060百万元、营业成本179,122.365百万元，减Q1营业收入129,753.223百万元和营业成本91,508.217百万元后，Q2毛利为41,311.688百万元。该A股营业成本口径不同于标准化表。", "official_h1_minus_q1_revenue_minus_cost_reconciliation", CT_2023_Q2_DETAIL_SOURCES),
    _official_record("中国电信", "Q2 2023", "gross_margin", 32.043, "percent", "中国电信2023半年度报告（新浪财经正文）", CT_2023_H1_SINA_URL, "以A股口径Q2毛利41,311.688百万元除以Q2营业收入128,925.837百万元，毛利率为32.043%。", "official_gross_profit_divided_by_revenue_reconciliation", CT_2023_Q2_DETAIL_SOURCES),
    _official_record("中国电信", "Q2 2023", "operating_cash_flow", 37448.691, "millions CNY", "中国电信2023半年度报告（新浪财经正文）", CT_2023_H1_SINA_URL, "A股H1现金流量表披露经营现金流65,663.264百万元，减Q1经营现金流28,214.572百万元后，Q2经营现金流为37,448.691百万元。", "official_h1_minus_q1_cash_flow_reconciliation", CT_2023_Q2_DETAIL_SOURCES),
    _official_record("中国电信", "Q2 2023", "operating_income", 16517.355, "millions CNY", "中国电信2023半年度报告（新浪财经正文）", CT_2023_H1_SINA_URL, "A股H1利润表披露营业利润27,193.810百万元，减Q1营业利润10,676.455百万元后，Q2营业利润为16,517.355百万元。", "official_h1_minus_q1_operating_profit_reconciliation", CT_2023_Q2_DETAIL_SOURCES),
    _official_record("中国电信", "Q2 2023", "operating_margin", 12.812, "percent", "中国电信2023半年度报告（新浪财经正文）", CT_2023_H1_SINA_URL, "以A股口径Q2营业利润16,517.355百万元除以Q2营业收入128,925.837百万元，经营利润率为12.812%。", "official_operating_income_divided_by_revenue_reconciliation", CT_2023_Q2_DETAIL_SOURCES),
    _official_record("中国电信", "Q2 2023", "revenue_growth_yoy", 5.987, "percent", "中国电信2023半年度报告（新浪财经正文）", CT_2023_H1_SINA_URL, "A股口径2023Q2营业收入由H1 258,679.060百万元减Q1 129,753.223百万元得128,925.837百万元；2022Q2由H1 240,219.208百万元减Q1 118,576.141百万元得121,643.067百万元，复算同比为5.987%。", "official_h1_minus_q1_prior_year_reconciliation", CT_2023_Q2_DETAIL_SOURCES),
    _official_record("中国电信", "Q2 2023", "total_assets", 840386.310, "millions CNY", "中国电信2023半年度报告（新浪财经正文）", CT_2023_H1_SINA_URL, "A股H1资产负债表披露2023年6月30日资产总计840,386.310百万元。", "official_balance_sheet_row_check", CT_2023_Q2_DETAIL_SOURCES),
    _official_record("中国电信", "Q2 2023", "total_debt", 69513.239, "millions CNY", "中国电信2023半年度报告（新浪财经正文）", CT_2023_H1_SINA_URL, "A股H1资产负债表披露短期借款2,908.018百万元、一年内到期的非流动负债15,330.456百万元、长期借款4,014.763百万元、租赁负债47,260.002百万元，合计总债务69,513.239百万元。", "official_borrowings_plus_lease_liabilities_reconciliation", CT_2023_Q2_DETAIL_SOURCES),
    _official_record("中国电信", "Q3 2023", "capital_expenditures", -32394.018, "millions CNY", "中国电信2023年前三季度报告（IRAsia中文版）", CT_2023_Q3_CN_URL, "A股三季报现金流量表披露前三季度购建长期资产现金支出60,719.649百万元，减H1 28,325.631百万元后，Q3资本开支为32,394.018百万元；现金流出口径记为负数。", "official_9m_minus_h1_capex_reconciliation", CT_2023_Q3_DETAIL_SOURCES),
    _official_record("中国电信", "Q3 2023", "cash_and_equivalents", 82445.207, "millions CNY", "中国电信2023年前三季度报告（IRAsia中文版）", CT_2023_Q3_CN_URL, "A股三季报现金流量表披露2023年9月30日期末现金及现金等价物余额82,445.207百万元。", "official_cash_flow_statement_cash_equivalents_check", CT_2023_Q3_DETAIL_SOURCES),
    _official_record("中国电信", "Q3 2023", "free_cash_flow", 14932.899, "millions CNY", "中国电信2023年前三季度报告（IRAsia中文版）", CT_2023_Q3_CN_URL, "前三季度经营现金流112,990.181百万元减H1经营现金流65,663.264百万元，Q3经营现金流47,326.917百万元；减Q3资本开支32,394.018百万元，普通自由现金流为14,932.899百万元。", "official_operating_cash_flow_minus_capex_reconciliation", CT_2023_Q3_DETAIL_SOURCES),
    _official_record("中国电信", "Q3 2023", "gross_profit", 35216.679, "millions CNY", "中国电信2023年前三季度报告（IRAsia中文版）", CT_2023_Q3_CN_URL, "A股三季报披露前三季度营业收入381,102.561百万元、营业成本266,329.187百万元；减H1营业收入258,679.060百万元和营业成本179,122.365百万元后，Q3毛利为35,216.679百万元。", "official_9m_minus_h1_revenue_minus_cost_reconciliation", CT_2023_Q3_DETAIL_SOURCES),
    _official_record("中国电信", "Q3 2023", "gross_margin", 28.766, "percent", "中国电信2023年前三季度报告（IRAsia中文版）", CT_2023_Q3_CN_URL, "以A股口径Q3毛利35,216.679百万元除以Q3营业收入122,423.501百万元，毛利率为28.766%。", "official_gross_profit_divided_by_revenue_reconciliation", CT_2023_Q3_DETAIL_SOURCES),
    _official_record("中国电信", "Q3 2023", "operating_cash_flow", 47326.917, "millions CNY", "中国电信2023年前三季度报告（IRAsia中文版）", CT_2023_Q3_CN_URL, "A股三季报披露前三季度经营现金流112,990.181百万元，减H1经营现金流65,663.264百万元后，Q3经营现金流为47,326.917百万元。", "official_9m_minus_h1_cash_flow_reconciliation", CT_2023_Q3_DETAIL_SOURCES),
    _official_record("中国电信", "Q3 2023", "operating_income", 9536.836, "millions CNY", "中国电信2023年前三季度报告（IRAsia中文版）", CT_2023_Q3_CN_URL, "A股三季报披露前三季度营业利润36,730.645百万元，减H1营业利润27,193.810百万元后，Q3营业利润为9,536.836百万元。", "official_9m_minus_h1_operating_profit_reconciliation", CT_2023_Q3_DETAIL_SOURCES),
    _official_record("中国电信", "Q3 2023", "operating_margin", 7.790, "percent", "中国电信2023年前三季度报告（IRAsia中文版）", CT_2023_Q3_CN_URL, "以A股口径Q3营业利润9,536.836百万元除以Q3营业收入122,423.501百万元，经营利润率为7.790%。", "official_operating_income_divided_by_revenue_reconciliation", CT_2023_Q3_DETAIL_SOURCES),
    _official_record("中国电信", "Q3 2023", "revenue_growth_yoy", 4.081, "percent", "中国电信2023年前三季度报告（IRAsia中文版）", CT_2023_Q3_CN_URL, "A股口径2023Q3营业收入由前三季度381,102.561百万元减H1 258,679.060百万元得122,423.501百万元；2022Q3由前三季度357,842.938百万元减H1 240,219.208百万元得117,623.730百万元，复算同比为4.081%。", "official_9m_minus_h1_prior_year_reconciliation", CT_2023_Q3_DETAIL_SOURCES),
    _official_record("中国电信", "Q3 2023", "total_assets", 835598.410, "millions CNY", "中国电信2023年前三季度报告（IRAsia中文版）", CT_2023_Q3_CN_URL, "A股三季报资产负债表披露2023年9月30日资产总计835,598.410百万元。", "official_balance_sheet_row_check", CT_2023_Q3_DETAIL_SOURCES),
    _official_record("中国电信", "Q3 2023", "total_debt", 65274.288, "millions CNY", "中国电信2023年前三季度报告（IRAsia中文版）", CT_2023_Q3_CN_URL, "A股三季报资产负债表披露短期借款2,864.990百万元、一年内到期的非流动负债14,539.974百万元、长期借款3,599.429百万元、租赁负债44,269.895百万元，合计总债务65,274.288百万元。", "official_borrowings_plus_lease_liabilities_reconciliation", CT_2023_Q3_DETAIL_SOURCES),
    _official_record("中国电信", "Q4 2023", "capital_expenditures", -29454.075, "millions CNY", "中国电信2023年度A股年报", CT_2023_ANNUAL_ASHARE_URL, "A股年报现金流量表披露全年购建长期资产现金支出90,173.725百万元，减前三季度60,719.649百万元后，Q4资本开支为29,454.075百万元；现金流出口径记为负数。", "official_full_year_minus_9m_capex_reconciliation", CT_2023_Q4_DETAIL_SOURCES),
    _official_record("中国电信", "Q4 2023", "cash_and_equivalents", 81045.623, "millions CNY", "中国电信2023年度A股年报", CT_2023_ANNUAL_ASHARE_URL, "A股年报现金流量表披露年末现金及现金等价物余额81,045.623百万元。", "official_cash_flow_statement_cash_equivalents_check", CT_2023_Q4_DETAIL_SOURCES),
    _official_record("中国电信", "Q4 2023", "free_cash_flow", -3821.197, "millions CNY", "中国电信2023年度A股年报", CT_2023_ANNUAL_ASHARE_URL, "全年经营现金流138,623.059百万元减前三季度112,990.181百万元，Q4经营现金流25,632.878百万元；减Q4资本开支29,454.075百万元，普通自由现金流为-3,821.197百万元。", "official_operating_cash_flow_minus_capex_reconciliation", CT_2023_Q4_DETAIL_SOURCES),
    _official_record("中国电信", "Q4 2023", "gross_profit", 31647.098, "millions CNY", "中国电信2023年度A股年报", CT_2023_ANNUAL_ASHARE_URL, "A股年报披露全年营业收入507,842.675百万元、营业成本361,422.204百万元；减前三季度营业收入381,102.561百万元和营业成本266,329.187百万元后，Q4毛利为31,647.098百万元。", "official_full_year_minus_9m_revenue_minus_cost_reconciliation", CT_2023_Q4_DETAIL_SOURCES),
    _official_record("中国电信", "Q4 2023", "gross_margin", 24.970, "percent", "中国电信2023年度A股年报", CT_2023_ANNUAL_ASHARE_URL, "以A股口径Q4毛利31,647.098百万元除以Q4营业收入126,740.114百万元，毛利率为24.970%。", "official_gross_profit_divided_by_revenue_reconciliation", CT_2023_Q4_DETAIL_SOURCES),
    _official_record("中国电信", "Q4 2023", "operating_cash_flow", 25632.878, "millions CNY", "中国电信2023年度A股年报", CT_2023_ANNUAL_ASHARE_URL, "A股年报披露全年经营现金流138,623.059百万元，减前三季度经营现金流112,990.181百万元后，Q4经营现金流为25,632.878百万元。", "official_full_year_minus_9m_cash_flow_reconciliation", CT_2023_Q4_DETAIL_SOURCES),
    _official_record("中国电信", "Q4 2023", "operating_income", 5838.459, "millions CNY", "中国电信2023年度A股年报", CT_2023_ANNUAL_ASHARE_URL, "A股年报披露全年营业利润42,569.104百万元，减前三季度营业利润36,730.645百万元后，Q4营业利润为5,838.459百万元。", "official_full_year_minus_9m_operating_profit_reconciliation", CT_2023_Q4_DETAIL_SOURCES),
    _official_record("中国电信", "Q4 2023", "operating_margin", 4.607, "percent", "中国电信2023年度A股年报", CT_2023_ANNUAL_ASHARE_URL, "以A股口径Q4营业利润5,838.459百万元除以Q4营业收入126,740.114百万元，经营利润率为4.607%。", "official_operating_income_divided_by_revenue_reconciliation", CT_2023_Q4_DETAIL_SOURCES),
    _official_record("中国电信", "Q4 2023", "revenue_growth_yoy", 8.210, "percent", "中国电信2023年度A股年报", CT_2023_ANNUAL_ASHARE_URL, "A股口径2023Q4营业收入由全年507,842.675百万元减前三季度381,102.561百万元得126,740.114百万元；2022Q4由全年474,967.243百万元减前三季度357,842.938百万元得117,124.305百万元，复算同比为8.210%。", "official_full_year_minus_9m_prior_year_reconciliation", CT_2023_Q4_DETAIL_SOURCES),
    _official_record("中国电信", "Q4 2023", "total_assets", 835813.905, "millions CNY", "中国电信2023年度A股年报", CT_2023_ANNUAL_ASHARE_URL, "A股年报合并资产负债表披露2023年12月31日资产总计835,813.905百万元。", "official_balance_sheet_row_check", CT_2023_Q4_DETAIL_SOURCES),
    _official_record("中国电信", "Q4 2023", "total_debt", 65206.257, "millions CNY", "中国电信2023年度A股年报", CT_2023_ANNUAL_ASHARE_URL, "A股年报资产负债表披露短期借款2,866.521百万元、一年内到期的非流动负债14,547.823百万元、长期借款5,141.727百万元、租赁负债42,650.186百万元，合计总债务65,206.257百万元。", "official_borrowings_plus_lease_liabilities_reconciliation", CT_2023_Q4_DETAIL_SOURCES),
]


CT_2024_QUARTERLY_METRICS = {
    "Q1 2024": {
        "revenue": 135493,
        "service_revenue": 124347,
        "ebitda": 35100,
        "ebitda_margin": 28.23,
        "net_income": 8597,
    },
    "Q2 2024": {
        "revenue": 132518,
        "service_revenue": 121888,
        "ebitda": 41692,
        "ebitda_margin": 34.21,
        "net_income": 13215,
    },
    "Q3 2024": {
        "revenue": 126707,
        "service_revenue": 116651,
        "ebitda": 34231,
        "ebitda_margin": 29.34,
        "net_income": 7487,
    },
    "Q4 2024": {
        "revenue": 134699,
        "service_revenue": 119147,
        "ebitda": 29824,
        "ebitda_margin": 25.03,
        "net_income": 3713,
    },
}

CT_2024_SOURCES_BY_PERIOD = {
    "Q1 2024": CT_2024_Q1_SOURCES,
    "Q2 2024": CT_2024_Q2_SOURCES,
    "Q3 2024": CT_2024_Q3_SOURCES,
    "Q4 2024": CT_2024_Q4_SOURCES,
}

CT_2024_METRIC_EVIDENCE = {
    "revenue": "中国电信官网Key Financial Data季度表列示{period_label} Operating Revenue 为人民币 {display_value} 百万元。",
    "service_revenue": "中国电信官网Key Financial Data季度表列示{period_label} Service Revenue 为人民币 {display_value} 百万元。",
    "ebitda": "中国电信官网Key Financial Data季度表列示{period_label} EBITDA 为人民币 {display_value} 百万元。",
    "ebitda_margin": "EBITDA margin 按中国电信公告定义由 EBITDA / service revenue 复算；{period_label}为 {display_value}%。",
    "net_income": "中国电信官网Key Financial Data季度表列示{period_label} Profit attributable to Equity Holders of the Company 为人民币 {display_value} 百万元。",
}

CT_2024_OFFICIAL_VERIFICATIONS = [
    _official_record(
        "中国电信",
        period,
        metric_key,
        value,
        "percent" if metric_key == "ebitda_margin" else "millions CNY",
        "中国电信官网Key Financial Data季度表",
        CT_KEY_FINANCIAL_DATA_URL,
        CT_2024_METRIC_EVIDENCE[metric_key].format(
            period_label=period.replace(" ", "/"),
            display_value=value,
        ),
        "official_quarterly_key_financial_data_with_cumulative_report_reconciliation",
        CT_2024_SOURCES_BY_PERIOD[period],
    )
    for period, metrics in CT_2024_QUARTERLY_METRICS.items()
    for metric_key, value in metrics.items()
]

CT_2024_DETAIL_OFFICIAL_VERIFICATIONS = [
    _official_record("中国电信", "Q2 2024", "capital_expenditures", -20321.562, "millions CNY", "中国电信2024半年度A股报告", CT_2024_H1_ASHARE_URL, "A股半年报现金流量表披露H1购建长期资产现金支出35,034.567百万元，减Q1 14,713.004百万元后，Q2资本开支为20,321.562百万元；现金流出口径记为负数。", "official_h1_minus_q1_capex_reconciliation", CT_2024_Q2_DETAIL_SOURCES),
    _official_record("中国电信", "Q2 2024", "cash_and_equivalents", 75072.147, "millions CNY", "中国电信2024半年度A股报告", CT_2024_H1_ASHARE_URL, "A股半年报现金流量表披露2024年6月30日期末现金及现金等价物余额75,072.147百万元。", "official_cash_flow_statement_cash_equivalents_check", CT_2024_Q2_DETAIL_SOURCES),
    _official_record("中国电信", "Q2 2024", "free_cash_flow", 17157.213, "millions CNY", "中国电信2024半年度A股报告", CT_2024_H1_ASHARE_URL, "H1经营现金流58,340.551百万元减Q1经营现金流20,861.776百万元，Q2经营现金流37,478.775百万元；减Q2资本开支20,321.562百万元，普通自由现金流为17,157.213百万元。", "official_operating_cash_flow_minus_capex_reconciliation", CT_2024_Q2_DETAIL_SOURCES),
    _official_record("中国电信", "Q2 2024", "gross_profit", 42467.912, "millions CNY", "中国电信2024半年度A股报告", CT_2024_H1_ASHARE_URL, "A股半年报披露H1营业收入265,973.119百万元、营业成本183,956.774百万元；减Q1营业收入134,494.563百万元和营业成本94,946.131百万元后，Q2毛利为42,467.912百万元。", "official_h1_minus_q1_revenue_minus_cost_reconciliation", CT_2024_Q2_DETAIL_SOURCES),
    _official_record("中国电信", "Q2 2024", "gross_margin", 32.300, "percent", "中国电信2024半年度A股报告", CT_2024_H1_ASHARE_URL, "以A股口径Q2毛利42,467.912百万元除以Q2营业收入131,478.556百万元，毛利率为32.300%。", "official_gross_profit_divided_by_revenue_reconciliation", CT_2024_Q2_DETAIL_SOURCES),
    _official_record("中国电信", "Q2 2024", "operating_cash_flow", 37478.775, "millions CNY", "中国电信2024半年度A股报告", CT_2024_H1_ASHARE_URL, "A股半年报披露H1经营现金流58,340.551百万元，减Q1经营现金流20,861.776百万元后，Q2经营现金流为37,478.775百万元。", "official_h1_minus_q1_cash_flow_reconciliation", CT_2024_Q2_DETAIL_SOURCES),
    _official_record("中国电信", "Q2 2024", "operating_income", 17079.587, "millions CNY", "中国电信2024半年度A股报告", CT_2024_H1_ASHARE_URL, "A股半年报利润表披露H1营业利润29,395.845百万元，减Q1营业利润12,316.258百万元后，Q2营业利润为17,079.587百万元。", "official_h1_minus_q1_operating_profit_reconciliation", CT_2024_Q2_DETAIL_SOURCES),
    _official_record("中国电信", "Q2 2024", "operating_margin", 12.990, "percent", "中国电信2024半年度A股报告", CT_2024_H1_ASHARE_URL, "以A股口径Q2营业利润17,079.587百万元除以Q2营业收入131,478.556百万元，经营利润率为12.990%。", "official_operating_income_divided_by_revenue_reconciliation", CT_2024_Q2_DETAIL_SOURCES),
    _official_record("中国电信", "Q2 2024", "revenue_growth_yoy", 1.980, "percent", "中国电信2024半年度A股报告", CT_2024_H1_ASHARE_URL, "A股口径2024Q2营业收入由H1 265,973.119百万元减Q1 134,494.563百万元得131,478.556百万元；2023Q2为128,925.837百万元，复算同比为1.980%。", "official_h1_minus_q1_prior_year_reconciliation", CT_2024_Q2_DETAIL_SOURCES),
    _official_record("中国电信", "Q2 2024", "total_assets", 870991.270, "millions CNY", "中国电信2024半年度A股报告", CT_2024_H1_ASHARE_URL, "A股半年报资产负债表披露2024年6月30日资产总计870,991.270百万元。", "official_balance_sheet_row_check", CT_2024_Q2_DETAIL_SOURCES),
    _official_record("中国电信", "Q2 2024", "total_debt", 61428.784, "millions CNY", "中国电信2024半年度A股报告", CT_2024_H1_ASHARE_URL, "A股半年报资产负债表披露短期借款2,644.956百万元、一年内到期的非流动负债14,710.522百万元、长期借款5,823.539百万元、租赁负债38,249.767百万元，合计总债务61,428.784百万元。", "official_borrowings_plus_lease_liabilities_reconciliation", CT_2024_Q2_DETAIL_SOURCES),
    _official_record("中国电信", "Q3 2024", "capital_expenditures", -23255.101, "millions CNY", "中国电信2024年前三季度报告（IRAsia中文版）", CT_2024_Q3_CN_URL, "A股三季报现金流量表披露前三季度购建长期资产现金支出58,289.667百万元，减H1 35,034.567百万元后，Q3资本开支为23,255.101百万元；现金流出口径记为负数。", "official_9m_minus_h1_capex_reconciliation", CT_2024_Q3_DETAIL_SOURCES),
    _official_record("中国电信", "Q3 2024", "cash_and_equivalents", 73337.524, "millions CNY", "中国电信2024年前三季度报告（IRAsia中文版）", CT_2024_Q3_CN_URL, "A股三季报现金流量表披露2024年9月30日期末现金及现金等价物余额73,337.524百万元。", "official_cash_flow_statement_cash_equivalents_check", CT_2024_Q3_DETAIL_SOURCES),
    _official_record("中国电信", "Q3 2024", "free_cash_flow", 15816.637, "millions CNY", "中国电信2024年前三季度报告（IRAsia中文版）", CT_2024_Q3_CN_URL, "前三季度经营现金流97,412.288百万元减H1经营现金流58,340.551百万元，Q3经营现金流39,071.737百万元；减Q3资本开支23,255.101百万元，普通自由现金流为15,816.637百万元。", "official_operating_cash_flow_minus_capex_reconciliation", CT_2024_Q3_DETAIL_SOURCES),
    _official_record("中国电信", "Q3 2024", "gross_profit", 35538.840, "millions CNY", "中国电信2024年前三季度报告（IRAsia中文版）", CT_2024_Q3_CN_URL, "A股三季报披露前三季度营业收入391,968.019百万元、营业成本274,412.834百万元；减H1营业收入265,973.119百万元和营业成本183,956.774百万元后，Q3毛利为35,538.840百万元。", "official_9m_minus_h1_revenue_minus_cost_reconciliation", CT_2024_Q3_DETAIL_SOURCES),
    _official_record("中国电信", "Q3 2024", "gross_margin", 28.207, "percent", "中国电信2024年前三季度报告（IRAsia中文版）", CT_2024_Q3_CN_URL, "以A股口径Q3毛利35,538.840百万元除以Q3营业收入125,994.900百万元，毛利率为28.207%。", "official_gross_profit_divided_by_revenue_reconciliation", CT_2024_Q3_DETAIL_SOURCES),
    _official_record("中国电信", "Q3 2024", "operating_cash_flow", 39071.737, "millions CNY", "中国电信2024年前三季度报告（IRAsia中文版）", CT_2024_Q3_CN_URL, "A股三季报披露前三季度经营现金流97,412.288百万元，减H1经营现金流58,340.551百万元后，Q3经营现金流为39,071.737百万元。", "official_9m_minus_h1_cash_flow_reconciliation", CT_2024_Q3_DETAIL_SOURCES),
    _official_record("中国电信", "Q3 2024", "operating_income", 9635.415, "millions CNY", "中国电信2024年前三季度报告（IRAsia中文版）", CT_2024_Q3_CN_URL, "A股三季报披露前三季度营业利润39,031.260百万元，减H1营业利润29,395.845百万元后，Q3营业利润为9,635.415百万元。", "official_9m_minus_h1_operating_profit_reconciliation", CT_2024_Q3_DETAIL_SOURCES),
    _official_record("中国电信", "Q3 2024", "operating_margin", 7.647, "percent", "中国电信2024年前三季度报告（IRAsia中文版）", CT_2024_Q3_CN_URL, "以A股口径Q3营业利润9,635.415百万元除以Q3营业收入125,994.900百万元，经营利润率为7.647%。", "official_operating_income_divided_by_revenue_reconciliation", CT_2024_Q3_DETAIL_SOURCES),
    _official_record("中国电信", "Q3 2024", "revenue_growth_yoy", 2.917, "percent", "中国电信2024年前三季度报告（IRAsia中文版）", CT_2024_Q3_CN_URL, "A股口径2024Q3营业收入为125,994.900百万元；对比2023Q3营业收入122,423.501百万元，复算同比为2.917%。", "official_current_prior_period_recalculation", CT_2024_Q3_DETAIL_SOURCES),
    _official_record("中国电信", "Q3 2024", "total_assets", 865467.894, "millions CNY", "中国电信2024年前三季度报告（IRAsia中文版）", CT_2024_Q3_CN_URL, "A股三季报资产负债表披露2024年9月30日资产总计865,467.894百万元。", "official_balance_sheet_row_check", CT_2024_Q3_DETAIL_SOURCES),
    _official_record("中国电信", "Q3 2024", "total_debt", 61335.099, "millions CNY", "中国电信2024年前三季度报告（IRAsia中文版）", CT_2024_Q3_CN_URL, "A股三季报资产负债表披露短期借款2,637.579百万元、一年内到期的非流动负债15,459.353百万元、长期借款7,666.987百万元、租赁负债35,571.179百万元，合计总债务61,335.099百万元。", "official_borrowings_plus_lease_liabilities_reconciliation", CT_2024_Q3_DETAIL_SOURCES),
    _official_record("中国电信", "Q4 2024", "capital_expenditures", -31981.677, "millions CNY", "中国电信2024年度A股年报", CT_2024_ANNUAL_ASHARE_URL, "A股年报现金流量表披露全年购建长期资产现金支出90,271.344百万元，减前三季度58,289.667百万元后，Q4资本开支为31,981.677百万元；现金流出口径记为负数。", "official_full_year_minus_9m_capex_reconciliation", CT_2024_Q4_DETAIL_SOURCES),
    _official_record("中国电信", "Q4 2024", "cash_and_equivalents", 82206.794, "millions CNY", "中国电信2024年度A股年报", CT_2024_ANNUAL_ASHARE_URL, "A股年报现金流量表披露年末现金及现金等价物余额82,206.794百万元。", "official_cash_flow_statement_cash_equivalents_check", CT_2024_Q4_DETAIL_SOURCES),
    _official_record("中国电信", "Q4 2024", "free_cash_flow", 15874.169, "millions CNY", "中国电信2024年度A股年报", CT_2024_ANNUAL_ASHARE_URL, "全年经营现金流145,268.134百万元减前三季度97,412.288百万元，Q4经营现金流47,855.846百万元；减Q4资本开支31,981.677百万元，普通自由现金流为15,874.169百万元。", "official_operating_cash_flow_minus_capex_reconciliation", CT_2024_Q4_DETAIL_SOURCES),
    _official_record("中国电信", "Q4 2024", "gross_profit", 32515.328, "millions CNY", "中国电信2024年度A股年报", CT_2024_ANNUAL_ASHARE_URL, "A股年报披露全年营业收入523,568.920百万元、营业成本373,498.407百万元；减前三季度营业收入391,968.019百万元和营业成本274,412.834百万元后，Q4毛利为32,515.328百万元。", "official_full_year_minus_9m_revenue_minus_cost_reconciliation", CT_2024_Q4_DETAIL_SOURCES),
    _official_record("中国电信", "Q4 2024", "gross_margin", 24.708, "percent", "中国电信2024年度A股年报", CT_2024_ANNUAL_ASHARE_URL, "以A股口径Q4毛利32,515.328百万元除以Q4营业收入131,600.901百万元，毛利率为24.708%。", "official_gross_profit_divided_by_revenue_reconciliation", CT_2024_Q4_DETAIL_SOURCES),
    _official_record("中国电信", "Q4 2024", "operating_cash_flow", 47855.846, "millions CNY", "中国电信2024年度A股年报", CT_2024_ANNUAL_ASHARE_URL, "A股年报披露全年经营现金流145,268.134百万元，减前三季度经营现金流97,412.288百万元后，Q4经营现金流为47,855.846百万元。", "official_full_year_minus_9m_cash_flow_reconciliation", CT_2024_Q4_DETAIL_SOURCES),
    _official_record("中国电信", "Q4 2024", "operating_income", 3565.916, "millions CNY", "中国电信2024年度A股年报", CT_2024_ANNUAL_ASHARE_URL, "A股年报披露全年营业利润42,597.177百万元，减前三季度营业利润39,031.260百万元后，Q4营业利润为3,565.916百万元。", "official_full_year_minus_9m_operating_profit_reconciliation", CT_2024_Q4_DETAIL_SOURCES),
    _official_record("中国电信", "Q4 2024", "operating_margin", 2.710, "percent", "中国电信2024年度A股年报", CT_2024_ANNUAL_ASHARE_URL, "以A股口径Q4营业利润3,565.916百万元除以Q4营业收入131,600.901百万元，经营利润率为2.710%。", "official_operating_income_divided_by_revenue_reconciliation", CT_2024_Q4_DETAIL_SOURCES),
    _official_record("中国电信", "Q4 2024", "revenue_growth_yoy", 3.835, "percent", "中国电信2024年度A股年报", CT_2024_ANNUAL_ASHARE_URL, "A股年报披露2024Q4营业收入131,600.901百万元；对比2023Q4营业收入126,740.114百万元，复算同比为3.835%。", "official_current_prior_period_recalculation", CT_2024_Q4_DETAIL_SOURCES),
    _official_record("中国电信", "Q4 2024", "total_assets", 866625.201, "millions CNY", "中国电信2024年度A股年报", CT_2024_ANNUAL_ASHARE_URL, "A股年报合并资产负债表披露2024年12月31日资产总计866,625.201百万元。", "official_balance_sheet_row_check", CT_2024_Q4_DETAIL_SOURCES),
    _official_record("中国电信", "Q4 2024", "total_debt", 60873.170, "millions CNY", "中国电信2024年度A股年报", CT_2024_ANNUAL_ASHARE_URL, "A股年报资产负债表披露短期借款2,834.657百万元、一年内到期的非流动负债15,737.584百万元、长期借款7,458.654百万元、租赁负债34,842.275百万元，合计总债务60,873.170百万元。", "official_borrowings_plus_lease_liabilities_reconciliation", CT_2024_Q4_DETAIL_SOURCES),
]


CU_2023_QUARTERLY_METRICS = {
    "Q1 2023": {
        "revenue": 97222,
        "revenue_growth_yoy": 9.21,
        "ebitda": 25730,
        "ebitda_margin": 29.88,
        "net_income": 5155,
        "operating_income": 4438,
        "operating_margin": 4.56,
    },
    "Q2 2023": {
        "revenue": 94611,
        "revenue_growth_yoy": 8.45,
        "ebitda": 27820,
        "ebitda_margin": 32.76,
        "net_income": 7236,
        "operating_income": 6692,
        "operating_margin": 7.07,
    },
    "Q3 2023": {
        "revenue": 89860,
        "revenue_growth_yoy": 2.44,
        "ebitda": 25269,
        "ebitda_margin": 31.01,
        "net_income": 4855,
        "operating_income": 4228,
        "operating_margin": 4.71,
    },
    "Q4 2023": {
        "revenue": 90907,
        "revenue_growth_yoy": 0.77,
        "ebitda": 20991,
        "ebitda_margin": 25.40,
        "net_income": 1484,
        "operating_income": -388,
        "operating_margin": -0.43,
    },
}

CU_2022_QUARTERLY_METRICS = {
    "Q1 2022": {
        "revenue": 89022,
        "revenue_growth_yoy": 8.2,
        "ebitda": 25031,
        "ebitda_margin": 30.83,
        "net_income": 4634,
    },
    "Q2 2022": {
        "revenue": 87239,
        "revenue_growth_yoy": 6.52,
        "ebitda": 26379,
        "ebitda_margin": 33.07,
        "net_income": 6323,
    },
    "Q3 2022": {
        "revenue": 87717,
        "revenue_growth_yoy": 9.22,
        "ebitda": 25325,
        "ebitda_margin": 32.19,
        "net_income": 4710,
    },
    "Q4 2022": {
        "revenue": 90966,
        "revenue_growth_yoy": 9.12,
        "ebitda": 22434,
        "ebitda_margin": 28.15,
        "net_income": 1078,
    },
}

CU_2022_SOURCES_BY_PERIOD = {
    "Q1 2022": CU_2022_Q1_SOURCES,
    "Q2 2022": CU_2022_Q2_SOURCES,
    "Q3 2022": CU_2022_Q3_SOURCES,
    "Q4 2022": CU_2022_Q4_SOURCES,
}

CU_2022_SOURCE_LABEL_BY_PERIOD = {
    "Q1 2022": ("中国联通2022年第一季度主要财务数据", CU_2022_Q1_URL, "一季度公告直接披露Q1核心经营数据；EBITDA margin 由Q1 EBITDA除以Q1 service revenue复算。"),
    "Q2 2022": ("中国联通2022中期报告减一季度数据", CU_2022_H1_URL, "H1累计值减Q1累计值复算Q2核心经营数据；EBITDA margin 由Q2 EBITDA除以Q2 service revenue复算。"),
    "Q3 2022": ("中国联通2022前三季度业绩减中期报告", CU_2022_Q3_URL, "9M累计值减H1累计值复算Q3核心经营数据；EBITDA margin 由Q3 EBITDA除以Q3 service revenue复算。"),
    "Q4 2022": ("中国联通2022年报减前三季度业绩", CU_2022_ANNUAL_REPORT_URL, "FY累计值减9M累计值复算Q4核心经营数据；EBITDA margin 由Q4 EBITDA除以Q4 service revenue复算。"),
}

CU_2022_OFFICIAL_VERIFICATIONS = [
    _official_record(
        "中国联通",
        period,
        metric_key,
        value,
        "percent" if metric_key in {"revenue_growth_yoy", "ebitda_margin"} else "millions CNY",
        CU_2022_SOURCE_LABEL_BY_PERIOD[period][0],
        CU_2022_SOURCE_LABEL_BY_PERIOD[period][1],
        f"{CU_2022_SOURCE_LABEL_BY_PERIOD[period][2]}官方值：{metric_key}={value}{'%' if metric_key in {'revenue_growth_yoy', 'ebitda_margin'} else '百万元'}。",
        "official_cumulative_report_quarter_reconciliation",
        CU_2022_SOURCES_BY_PERIOD[period],
    )
    for period, metrics in CU_2022_QUARTERLY_METRICS.items()
    for metric_key, value in metrics.items()
]

CU_2020_QUARTERLY_METRICS = {
    "Q1 2020": {
        "revenue": 73824,
        "service_revenue": 68307,
        "ebitda": 23561,
        "ebitda_margin": 34.493,
        "net_income": 3166,
    },
    "Q2 2020": {
        "revenue": 76573,
        "service_revenue": 70028,
        "ebitda": 25891,
        "ebitda_margin": 36.972,
        "net_income": 4403,
    },
    "Q3 2020": {
        "revenue": 74958,
        "service_revenue": 69014,
        "ebitda": 24248,
        "ebitda_margin": 35.135,
        "net_income": 3255,
    },
    "Q4 2020": {
        "revenue": 78483,
        "service_revenue": 68465,
        "ebitda": 20439,
        "ebitda_margin": 29.853,
        "net_income": 1669,
    },
}

CU_2020_SOURCES_BY_PERIOD = {
    "Q1 2020": CU_2020_Q1_SOURCES,
    "Q2 2020": CU_2020_Q2_SOURCES,
    "Q3 2020": CU_2020_Q3_SOURCES,
    "Q4 2020": CU_2020_Q4_SOURCES,
}

CU_2020_SOURCE_LABEL_BY_PERIOD = {
    "Q1 2020": ("中国联通2020年第一季度主要财务数据", CU_2020_Q1_URL, "一季度公告直接披露Q1核心经营数据；EBITDA margin 由Q1 EBITDA除以Q1 service revenue复算。"),
    "Q2 2020": ("中国联通2020中期业绩新闻稿减一季度数据", CU_2020_H1_PRESS_URL, "H1累计值减Q1累计值复算Q2核心经营数据；EBITDA margin 由Q2 EBITDA除以Q2 service revenue复算。"),
    "Q3 2020": ("中国联通2020前三季度业绩减中期业绩", CU_2020_Q3_URL, "9M累计值减H1累计值复算Q3核心经营数据；EBITDA margin 由Q3 EBITDA除以Q3 service revenue复算。"),
    "Q4 2020": ("中国联通2020年度业绩公告减前三季度业绩", CU_2020_ANNUAL_RESULTS_URL, "FY累计值减9M累计值复算Q4核心经营数据；EBITDA margin 由Q4 EBITDA除以Q4 service revenue复算。"),
}

CU_2020_OFFICIAL_VERIFICATIONS = [
    _official_record(
        "中国联通",
        period,
        metric_key,
        value,
        "percent" if metric_key == "ebitda_margin" else "millions CNY",
        CU_2020_SOURCE_LABEL_BY_PERIOD[period][0],
        CU_2020_SOURCE_LABEL_BY_PERIOD[period][1],
        f"{CU_2020_SOURCE_LABEL_BY_PERIOD[period][2]}官方值：{metric_key}={value}{'%' if metric_key == 'ebitda_margin' else '百万元'}。",
        "official_cumulative_report_quarter_reconciliation",
        CU_2020_SOURCES_BY_PERIOD[period],
    )
    for period, metrics in CU_2020_QUARTERLY_METRICS.items()
    for metric_key, value in metrics.items()
]

CU_2019_QUARTERLY_METRICS = {
    "Q1 2019": {
        "revenue": 73147,
        "service_revenue": 66802,
        "ebitda": 25012,
        "ebitda_margin": 37.442,
        "net_income": 3675,
    },
    "Q2 2019": {
        "revenue": 71807,
        "service_revenue": 66155,
        "ebitda": 24495,
        "ebitda_margin": 37.027,
        "net_income": 3202,
    },
    "Q3 2019": {
        "revenue": 72166,
        "service_revenue": 65575,
        "ebitda": 23638,
        "ebitda_margin": 36.047,
        "net_income": 2946,
    },
    "Q4 2019": {
        "revenue": 73395,
        "service_revenue": 65854,
        "ebitda": 21213,
        "ebitda_margin": 32.212,
        "net_income": 1507,
    },
}

CU_2019_SOURCES_BY_PERIOD = {
    "Q1 2019": CU_2019_Q1_SOURCES,
    "Q2 2019": CU_2019_Q2_SOURCES,
    "Q3 2019": CU_2019_Q3_SOURCES,
    "Q4 2019": CU_2019_Q4_SOURCES,
}

CU_2019_SOURCE_LABEL_BY_PERIOD = {
    "Q1 2019": ("中国联通2019年第一季度主要财务数据", CU_2019_Q1_URL, "一季度公告直接披露Q1核心经营数据；EBITDA margin 由Q1 EBITDA除以Q1 service revenue复算。"),
    "Q2 2019": ("中国联通2019中期报告减一季度数据", CU_2019_H1_URL, "H1累计值减Q1累计值复算Q2核心经营数据；EBITDA margin 由Q2 EBITDA除以Q2 service revenue复算。"),
    "Q3 2019": ("中国联通2019前三季度业绩减中期报告", CU_2019_Q3_URL, "9M累计值减H1累计值复算Q3核心经营数据；EBITDA margin 由Q3 EBITDA除以Q3 service revenue复算。"),
    "Q4 2019": ("中国联通2019年报减前三季度业绩", CU_2019_ANNUAL_REPORT_URL, "FY累计值减9M累计值复算Q4核心经营数据；EBITDA margin 由Q4 EBITDA除以Q4 service revenue复算。"),
}

CU_2019_OFFICIAL_VERIFICATIONS = [
    _official_record(
        "中国联通",
        period,
        metric_key,
        value,
        "percent" if metric_key == "ebitda_margin" else "millions CNY",
        CU_2019_SOURCE_LABEL_BY_PERIOD[period][0],
        CU_2019_SOURCE_LABEL_BY_PERIOD[period][1],
        f"{CU_2019_SOURCE_LABEL_BY_PERIOD[period][2]}官方值：{metric_key}={value}{'%' if metric_key == 'ebitda_margin' else '百万元'}。",
        "official_cumulative_report_quarter_reconciliation",
        CU_2019_SOURCES_BY_PERIOD[period],
    )
    for period, metrics in CU_2019_QUARTERLY_METRICS.items()
    for metric_key, value in metrics.items()
]

CU_2018_QUARTERLY_METRICS = {
    "Q1 2018": {
        "revenue": 74935,
        "service_revenue": 66609,
        "ebitda": 23909,
        "ebitda_margin": 35.895,
        "net_income": 3005,
    },
    "Q2 2018": {
        "revenue": 74175,
        "service_revenue": 67811,
        "ebitda": 21761,
        "ebitda_margin": 32.091,
        "net_income": 2905,
    },
    "Q3 2018": {
        "revenue": 70602,
        "service_revenue": 65593,
        "ebitda": 20576,
        "ebitda_margin": 31.369,
        "net_income": 2870,
    },
    "Q4 2018": {
        "revenue": 71168,
        "service_revenue": 63667,
        "ebitda": 18664,
        "ebitda_margin": 29.315,
        "net_income": 1420,
    },
}

CU_2018_SOURCES_BY_PERIOD = {
    "Q1 2018": CU_2018_Q1_SOURCES,
    "Q2 2018": CU_2018_Q2_SOURCES,
    "Q3 2018": CU_2018_Q3_SOURCES,
    "Q4 2018": CU_2018_Q4_SOURCES,
}

CU_2018_SOURCE_LABEL_BY_PERIOD = {
    "Q1 2018": ("中国联通2018年第一季度主要财务及运营数据", CU_2018_Q1_URL, "一季度公告直接披露Q1核心经营数据；EBITDA margin 由Q1 EBITDA除以Q1 service revenue复算。"),
    "Q2 2018": ("中国联通2018中期报告减一季度数据", CU_2018_H1_URL, "H1累计值减Q1累计值复算Q2核心经营数据；EBITDA margin 由Q2 EBITDA除以Q2 service revenue复算。"),
    "Q3 2018": ("中国联通2018前三季度业绩减中期报告", CU_2018_Q3_URL, "9M累计值减H1累计值复算Q3核心经营数据；EBITDA margin 由Q3 EBITDA除以Q3 service revenue复算。"),
    "Q4 2018": ("中国联通2018年报减前三季度业绩", CU_2018_ANNUAL_REPORT_URL, "FY累计值减9M累计值复算Q4核心经营数据；EBITDA margin 由Q4 EBITDA除以Q4 service revenue复算。"),
}

CU_2018_OFFICIAL_VERIFICATIONS = [
    _official_record(
        "中国联通",
        period,
        metric_key,
        value,
        "percent" if metric_key == "ebitda_margin" else "millions CNY",
        CU_2018_SOURCE_LABEL_BY_PERIOD[period][0],
        CU_2018_SOURCE_LABEL_BY_PERIOD[period][1],
        f"{CU_2018_SOURCE_LABEL_BY_PERIOD[period][2]}官方值：{metric_key}={value}{'%' if metric_key == 'ebitda_margin' else '百万元'}。",
        "official_cumulative_report_quarter_reconciliation",
        CU_2018_SOURCES_BY_PERIOD[period],
    )
    for period, metrics in CU_2018_QUARTERLY_METRICS.items()
    for metric_key, value in metrics.items()
]

CU_2017_QUARTERLY_METRICS = {
    "Q1 2017": {
        "revenue": 69005,
        "service_revenue": 61426,
        "net_income": 862,
    },
    "Q2 2017": {
        "revenue": 69155,
        "service_revenue": 62684,
        "net_income": 1558,
    },
    "Q3 2017": {
        "revenue": 67618,
        "service_revenue": 63770,
        "net_income": 1634,
    },
    "Q4 2017": {
        "revenue": 69051,
        "service_revenue": 61135,
        "net_income": -2224,
    },
}

CU_2017_SOURCES_BY_PERIOD = {
    "Q1 2017": CU_2017_Q1_SOURCES,
    "Q2 2017": CU_2017_Q2_SOURCES,
    "Q3 2017": CU_2017_Q3_SOURCES,
    "Q4 2017": CU_2017_Q4_SOURCES,
}

CU_2017_SOURCE_LABEL_BY_PERIOD = {
    "Q1 2017": ("中国联通2018年第一季度主要财务及运营数据比较栏", CU_2018_Q1_URL, "2018 Q1公告比较栏直接列示2017 Q1 revenue、service revenue和归母利润。"),
    "Q2 2017": ("中国联通2017中期报告减2017 Q1比较栏", CU_2017_H1_URL, "H1累计值减2018 Q1公告中的2017 Q1比较栏复算Q2；因缺少2017 Q1 EBITDA官方基数，不写入Q2 EBITDA。"),
    "Q3 2017": ("中国联通2018前三季度公告比较栏减2017中期报告", CU_2018_Q3_URL, "2018 Q3公告中的2017 9M比较栏减H1累计值复算Q3；因缺少2017 9M EBITDA官方比较栏，不写入Q3 EBITDA。"),
    "Q4 2017": ("中国联通2017年报减2017 9M比较栏", CU_2017_ANNUAL_REPORT_URL, "FY累计值减2018 Q3公告中的2017 9M比较栏复算Q4；Q4归母利润为负，受光纤网络升级相关资产报废损失影响。"),
}

CU_2017_OFFICIAL_VERIFICATIONS = [
    _official_record(
        "中国联通",
        period,
        metric_key,
        value,
        "millions CNY",
        CU_2017_SOURCE_LABEL_BY_PERIOD[period][0],
        CU_2017_SOURCE_LABEL_BY_PERIOD[period][1],
        f"{CU_2017_SOURCE_LABEL_BY_PERIOD[period][2]}官方值：{metric_key}={value}百万元。",
        "official_cumulative_report_quarter_reconciliation",
        CU_2017_SOURCES_BY_PERIOD[period],
    )
    for period, metrics in CU_2017_QUARTERLY_METRICS.items()
    for metric_key, value in metrics.items()
]

CU_2016_2018_DISCLOSURE_GAP_CONFIRMATIONS = [
    {
        "subject": "中国联通",
        "period": period,
        "metric_key": "quarterly_financial_disclosure_status",
        "source_label": "中国联通2016中期报告及年报披露边界",
        "source_url": CU_2016_H1_URL,
        "evidence": (
            f"{period} 所需的2016年Q1或9M同口径财务基数未在已核验官方公开文件中披露；"
            "2016中期报告只披露H1累计值，2016年报只披露FY累计值，无法精确拆分该单季核心财务指标。"
        ),
        "verification_method": "official_disclosure_gap_check",
        "verification_sources": CU_2016_DISCLOSURE_GAP_SOURCES,
        "verification_note": "保留2016年早期季度披露缺口；不得用H1/FY平均、同比倒推或标准化在线表估算中国联通2016单季财务值。",
        "append_if_missing": True,
    }
    for period in ["Q2 2016", "Q3 2016", "Q4 2016"]
]

CU_2021_QUARTERLY_METRICS = {
    "Q1 2021": {
        "revenue": 82272,
        "ebitda": 23640,
        "net_income": 3843,
    },
    "Q2 2021": {
        "revenue": 81902,
        "ebitda": 25850,
        "net_income": 5324,
    },
    "Q3 2021": {
        "revenue": 80315,
        "ebitda": 25847,
        "net_income": 3756,
    },
    "Q4 2021": {
        "revenue": 83365,
        "ebitda": 20983,
        "net_income": 1445,
    },
}

CU_2021_SOURCES_BY_PERIOD = {
    "Q1 2021": CU_2021_Q1_SOURCES,
    "Q2 2021": CU_2021_Q2_SOURCES,
    "Q3 2021": CU_2021_Q3_SOURCES,
    "Q4 2021": CU_2021_Q4_SOURCES,
}

CU_2021_SOURCE_LABEL_BY_PERIOD = {
    "Q1 2021": ("中国联通2021年第一季度主要财务数据", CU_2021_Q1_URL, "一季度公告直接披露Q1核心经营数据。"),
    "Q2 2021": ("中国联通2021中期报告减一季度数据", CU_2021_H1_URL, "H1累计值减Q1累计值复算Q2核心经营数据。"),
    "Q3 2021": ("中国联通2021前三季度业绩减中期报告", CU_2021_Q3_URL, "9M累计值减H1累计值复算Q3核心经营数据。"),
    "Q4 2021": ("中国联通2021年报减前三季度业绩", CU_2021_ANNUAL_REPORT_URL, "FY累计值减9M累计值复算Q4核心经营数据。"),
}

CU_2021_OFFICIAL_VERIFICATIONS = [
    _official_record(
        "中国联通",
        period,
        metric_key,
        value,
        "millions CNY",
        CU_2021_SOURCE_LABEL_BY_PERIOD[period][0],
        CU_2021_SOURCE_LABEL_BY_PERIOD[period][1],
        f"{CU_2021_SOURCE_LABEL_BY_PERIOD[period][2]}官方值：{metric_key}={value}百万元。",
        "official_cumulative_report_quarter_reconciliation",
        CU_2021_SOURCES_BY_PERIOD[period],
    )
    for period, metrics in CU_2021_QUARTERLY_METRICS.items()
    for metric_key, value in metrics.items()
]

CU_2022_DETAIL_PERIOD_SOURCE = {
    "Q1 2022": ("中国联通2022年第一季度主要财务数据", CU_2022_Q1_URL, "official_quarterly_statement_check", CU_2022_Q1_SOURCES),
    "Q2 2022": ("中国联通2022中期报告", CU_2022_H1_URL, "official_h1_statement_check", CU_2022_Q2_SOURCES),
    "Q3 2022": ("中国联通2022年前三季度业绩公告", CU_2022_Q3_URL, "official_9m_statement_check", CU_2022_Q3_SOURCES),
    "Q4 2022": ("中国联通2022年报", CU_2022_ANNUAL_REPORT_URL, "official_fy_statement_check", CU_2022_Q4_SOURCES),
}

CU_2022_DETAIL_METRICS = {
    "Q1 2022": {
        "total_assets": (587206, "millions CNY", "一季度主要财务数据披露2022年3月31日总资产587,206百万元。"),
    },
    "Q2 2022": {
        "cash_and_equivalents": (44665, "millions CNY", "中期报告资产负债表及现金流量表披露2022年6月30日现金及现金等价物44,665百万元。"),
        "total_assets": (603617, "millions CNY", "中期报告资产负债表披露2022年6月30日总资产603,617百万元。"),
    },
    "Q3 2022": {
        "total_assets": (614850, "millions CNY", "前三季度主要财务数据披露2022年9月30日总资产614,850百万元。"),
    },
    "Q4 2022": {
        "cash_and_equivalents": (55297, "millions CNY", "年报资产负债表及现金流量表披露2022年12月31日现金及现金等价物55,297百万元。"),
        "total_assets": (642663, "millions CNY", "年报资产负债表披露2022年12月31日总资产642,663百万元。"),
    },
}

CU_2022_DETAIL_OFFICIAL_VERIFICATIONS = [
    _official_record(
        "中国联通",
        period,
        metric_key,
        value,
        unit,
        CU_2022_DETAIL_PERIOD_SOURCE[period][0],
        CU_2022_DETAIL_PERIOD_SOURCE[period][1],
        evidence,
        CU_2022_DETAIL_PERIOD_SOURCE[period][2],
        CU_2022_DETAIL_PERIOD_SOURCE[period][3],
    )
    for period, metrics in CU_2022_DETAIL_METRICS.items()
    for metric_key, (value, unit, evidence) in metrics.items()
]

CU_2021_DETAIL_PERIOD_SOURCE = {
    "Q2 2021": ("中国联通2021中期报告减一季度数据", CU_2021_H1_URL, "official_h1_minus_q1_reconciliation", CU_2021_Q2_SOURCES),
    "Q3 2021": ("中国联通2021前三季度业绩减中期报告", CU_2021_Q3_URL, "official_9m_minus_h1_reconciliation", CU_2021_Q3_SOURCES),
    "Q4 2021": ("中国联通2021年报减前三季度业绩", CU_2021_ANNUAL_REPORT_URL, "official_fy_minus_9m_reconciliation", CU_2021_Q4_SOURCES),
}

CU_2021_DETAIL_METRICS = {
    "Q2 2021": {
        "cash_and_equivalents": (22494, "millions CNY", "中期报告资产负债表及现金流量表披露2021年6月30日现金及现金等价物22,494百万元。"),
        "ebitda_margin": (34.582, "percent", "H1 EBITDA 49,490百万元扣除Q1 23,640百万元后，Q2 EBITDA为25,850百万元；H1服务收入148,674百万元扣除Q1 73,924百万元后，Q2服务收入74,750百万元，复算EBITDA率34.582%。"),
        "revenue_growth_yoy": (6.959, "percent", "H1 2021收入164,174百万元扣除Q1 2021收入82,272百万元得Q2 81,902百万元；H1 2020收入150,397百万元扣除Q1 2020收入73,824百万元得Q2 76,573百万元，复算同比6.959%。"),
        "total_assets": (571267, "millions CNY", "中期报告资产负债表披露2021年6月30日总资产571,267百万元。"),
    },
    "Q3 2021": {
        "ebitda_margin": (35.065, "percent", "9M EBITDA 75,337百万元扣除H1 49,490百万元后，Q3 EBITDA为25,847百万元；9M服务收入222,384百万元扣除H1 148,674百万元后，Q3服务收入73,710百万元，复算EBITDA率35.065%。"),
        "revenue_growth_yoy": (7.147, "percent", "9M 2021收入244,489百万元扣除H1 2021收入164,174百万元得Q3 80,315百万元；9M 2020收入225,355百万元扣除H1 2020收入150,397百万元得Q3 74,958百万元，复算同比7.147%。"),
        "total_assets": (589264, "millions CNY", "前三季度主要财务数据披露2021年9月30日总资产589,264百万元。"),
    },
    "Q4 2021": {
        "cash_and_equivalents": (34280, "millions CNY", "年报资产负债表及现金流量表披露2021年12月31日现金及现金等价物34,280百万元。"),
        "ebitda_margin": (28.444, "percent", "FY EBITDA 96,320百万元扣除9M 75,337百万元后，Q4 EBITDA为20,983百万元；FY服务收入296,153百万元扣除9M 222,384百万元后，Q4服务收入73,769百万元，复算EBITDA率28.444%。"),
        "revenue_growth_yoy": (6.221, "percent", "FY 2021收入327,854百万元扣除9M 2021收入244,489百万元得Q4 83,365百万元；FY 2020收入303,838百万元扣除9M 2020收入225,355百万元得Q4 78,483百万元，复算同比6.221%。"),
        "total_assets": (591076, "millions CNY", "年报资产负债表披露2021年12月31日总资产591,076百万元。"),
    },
}

CU_2021_DETAIL_OFFICIAL_VERIFICATIONS = [
    _official_record(
        "中国联通",
        period,
        metric_key,
        value,
        unit,
        CU_2021_DETAIL_PERIOD_SOURCE[period][0],
        CU_2021_DETAIL_PERIOD_SOURCE[period][1],
        evidence,
        CU_2021_DETAIL_PERIOD_SOURCE[period][2],
        CU_2021_DETAIL_PERIOD_SOURCE[period][3],
    )
    for period, metrics in CU_2021_DETAIL_METRICS.items()
    for metric_key, (value, unit, evidence) in metrics.items()
]

CU_2021_2022_SOURCE_GAP_CONFIRMATIONS = [
    {
        "subject": "中国联通",
        "period": period,
        "metric_key": metric_key,
        "source_label": period_source[0],
        "source_url": period_source[1],
        "evidence": (
            f"{period} 中国联通港股一季报、半年度/前三季度业绩公告及年报已核验；"
            f"公开文件未披露可直接对应 {METRIC_ZH_BY_KEY.get(metric_key, metric_key)} 的同口径官方数值。"
            "保留披露缺口，不用标准化表估算。"
        ),
        "verification_method": "official_disclosure_gap_check",
        "verification_sources": period_source[3],
        "verification_note": "中国联通该期间官方公开文件未披露同口径字段；正式回答只能说明披露缺口，不得引用标准化表估算值。",
    }
    for period, period_source, metric_keys in [
        ("Q1 2022", CU_2022_DETAIL_PERIOD_SOURCE["Q1 2022"], ["cash_and_equivalents", "gross_margin", "gross_profit", "operating_income", "operating_margin", "total_debt"]),
        ("Q2 2022", CU_2022_DETAIL_PERIOD_SOURCE["Q2 2022"], ["gross_margin", "gross_profit", "operating_income", "operating_margin", "total_debt"]),
        ("Q3 2022", CU_2022_DETAIL_PERIOD_SOURCE["Q3 2022"], ["cash_and_equivalents", "gross_margin", "gross_profit", "operating_income", "operating_margin", "total_debt"]),
        ("Q4 2022", CU_2022_DETAIL_PERIOD_SOURCE["Q4 2022"], ["gross_margin", "gross_profit", "operating_income", "operating_margin", "total_debt"]),
        ("Q2 2021", CU_2021_DETAIL_PERIOD_SOURCE["Q2 2021"], ["gross_margin", "gross_profit", "operating_income", "operating_margin", "total_debt"]),
        ("Q3 2021", CU_2021_DETAIL_PERIOD_SOURCE["Q3 2021"], ["cash_and_equivalents", "gross_margin", "gross_profit", "operating_income", "operating_margin", "total_debt"]),
        ("Q4 2021", CU_2021_DETAIL_PERIOD_SOURCE["Q4 2021"], ["gross_margin", "gross_profit", "operating_income", "operating_margin", "total_debt"]),
    ]
    for metric_key in metric_keys
]

CU_2023_SOURCES_BY_PERIOD = {
    "Q1 2023": CU_2023_Q1_SOURCES,
    "Q2 2023": CU_2023_Q2_SOURCES,
    "Q3 2023": CU_2023_Q3_SOURCES,
    "Q4 2023": CU_2023_Q4_SOURCES,
}

CU_2023_METRIC_EVIDENCE = {
    "revenue": "中国联通官方Q1/H1/9M/FY披露复核{period_label} operating revenue 为人民币 {display_value} 百万元。",
    "revenue_growth_yoy": "中国联通官方Q1/H1/9M/FY披露及累计相减复核{period_label} revenue growth yoy 为 {display_value}%。",
    "ebitda": "中国联通官方Q1/H1/9M/FY披露复核{period_label} EBITDA 为人民币 {display_value} 百万元。",
    "ebitda_margin": "EBITDA margin 按中国联通公告定义由 EBITDA / service revenue 复算；{period_label}为 {display_value}%。",
    "net_income": "中国联通官方Q1/H1/9M/FY披露复核{period_label}归属于权益股东利润为人民币 {display_value} 百万元。",
    "operating_income": "中国联通官方收益表和Financial Overview披露复核{period_label} operating profits 为人民币 {display_value} 百万元。",
    "operating_margin": "Operating margin 由中国联通官方 operating profits / operating revenue 复算；{period_label}为 {display_value}%。",
}

CU_2023_OFFICIAL_VERIFICATIONS = [
    _official_record(
        "中国联通",
        period,
        metric_key,
        value,
        "percent" if metric_key in {"revenue_growth_yoy", "ebitda_margin", "operating_margin"} else "millions CNY",
        "中国联通2023官方季度/累计业绩披露",
        CU_2023_SOURCES_BY_PERIOD[period][-1]["url"],
        CU_2023_METRIC_EVIDENCE[metric_key].format(
            period_label=period.replace(" ", "/"),
            display_value=value,
        ),
        "official_cumulative_report_quarter_reconciliation",
        CU_2023_SOURCES_BY_PERIOD[period],
    )
    for period, metrics in CU_2023_QUARTERLY_METRICS.items()
    for metric_key, value in metrics.items()
]

CU_2023_DETAIL_OFFICIAL_VERIFICATIONS = [
    _official_record("中国联通", "Q1 2023", "cash_and_equivalents", 53145.202, "millions CNY", "中国联通2023年第一季度报告（600050 A股口径）", CU_2023_Q1_SINA_URL, "A股一季报现金流量表披露2023年3月31日期末现金及现金等价物余额53,145.202百万元。", "official_cash_flow_statement_cash_equivalents_check", CU_2023_Q1_DETAIL_SOURCES),
    _official_record("中国联通", "Q1 2023", "gross_profit", 23732.345, "millions CNY", "中国联通2023年第一季度报告（600050 A股口径）", CU_2023_Q1_SINA_URL, "A股一季报披露营业收入97,221.823百万元、营业成本73,489.477百万元；按收入减成本复算毛利为23,732.345百万元。", "official_revenue_minus_operating_cost_reconciliation", CU_2023_Q1_DETAIL_SOURCES),
    _official_record("中国联通", "Q1 2023", "gross_margin", 24.411, "percent", "中国联通2023年第一季度报告（600050 A股口径）", CU_2023_Q1_SINA_URL, "以A股口径Q1毛利23,732.345百万元除以营业收入97,221.823百万元，毛利率为24.411%。", "official_gross_profit_divided_by_revenue_reconciliation", CU_2023_Q1_DETAIL_SOURCES),
    _official_record("中国联通", "Q1 2023", "total_assets", 651737.443, "millions CNY", "中国联通2023年第一季度报告（600050 A股口径）", CU_2023_Q1_SINA_URL, "A股一季报资产负债表披露2023年3月31日资产总计651,737.443百万元。", "official_balance_sheet_row_check", CU_2023_Q1_DETAIL_SOURCES),
    _official_record("中国联通", "Q1 2023", "total_debt", 49950.864, "millions CNY", "中国联通2023年第一季度报告（600050 A股口径）", CU_2023_Q1_SINA_URL, "A股一季报资产负债表披露短期借款569.968百万元、一年内到期的非流动负债12,824.067百万元、长期借款1,778.988百万元、租赁负债34,777.841百万元，合计总债务49,950.864百万元。", "official_borrowings_plus_lease_liabilities_reconciliation", CU_2023_Q1_DETAIL_SOURCES),
    _official_record("中国联通", "Q2 2023", "cash_and_equivalents", 52359.654, "millions CNY", "中国联通2023年半年度报告（600050 A股口径）", CU_2023_H1_SINA_URL, "A股半年报现金流量表披露2023年6月30日期末现金及现金等价物余额52,359.654百万元。", "official_cash_flow_statement_cash_equivalents_check", CU_2023_Q2_DETAIL_SOURCES),
    _official_record("中国联通", "Q2 2023", "gross_profit", 24406.191, "millions CNY", "中国联通2023年半年度报告（600050 A股口径）", CU_2023_H1_SINA_URL, "A股半年报披露H1营业收入191,832.687百万元、营业成本143,694.150百万元；减Q1营业收入97,221.823百万元和营业成本73,489.477百万元，复算Q2毛利为24,406.191百万元。", "official_h1_minus_q1_revenue_minus_cost_reconciliation", CU_2023_Q2_DETAIL_SOURCES),
    _official_record("中国联通", "Q2 2023", "gross_margin", 25.796, "percent", "中国联通2023年半年度报告（600050 A股口径）", CU_2023_H1_SINA_URL, "以A股口径Q2毛利24,406.191百万元除以Q2营业收入94,610.864百万元，毛利率为25.796%。", "official_gross_profit_divided_by_revenue_reconciliation", CU_2023_Q2_DETAIL_SOURCES),
    _official_record("中国联通", "Q2 2023", "total_assets", 660290.422, "millions CNY", "中国联通2023年半年度报告（600050 A股口径）", CU_2023_H1_SINA_URL, "A股半年报资产负债表披露2023年6月30日资产总计660,290.422百万元。", "official_balance_sheet_row_check", CU_2023_Q2_DETAIL_SOURCES),
    _official_record("中国联通", "Q2 2023", "total_debt", 47970.063, "millions CNY", "中国联通2023年半年度报告（600050 A股口径）", CU_2023_H1_SINA_URL, "A股半年报资产负债表披露短期借款712.776百万元、一年内到期的非流动负债12,021.990百万元、长期借款1,664.173百万元、租赁负债33,571.125百万元，合计总债务47,970.063百万元。", "official_borrowings_plus_lease_liabilities_reconciliation", CU_2023_Q2_DETAIL_SOURCES),
    _official_record("中国联通", "Q3 2023", "cash_and_equivalents", 59498.809, "millions CNY", "中国联通2023年第三季度报告（600050 A股口径）", CU_2023_Q3_SINA_URL, "A股三季报现金流量表披露2023年9月30日期末现金及现金等价物余额59,498.809百万元。", "official_cash_flow_statement_cash_equivalents_check", CU_2023_Q3_DETAIL_SOURCES),
    _official_record("中国联通", "Q3 2023", "gross_profit", 22782.899, "millions CNY", "中国联通2023年第三季度报告（600050 A股口径）", CU_2023_Q3_SINA_URL, "A股三季报披露前三季度营业收入281,692.598百万元、营业成本210,771.162百万元；减H1营业收入191,832.687百万元和营业成本143,694.150百万元，复算Q3毛利为22,782.899百万元。", "official_9m_minus_h1_revenue_minus_cost_reconciliation", CU_2023_Q3_DETAIL_SOURCES),
    _official_record("中国联通", "Q3 2023", "gross_margin", 25.354, "percent", "中国联通2023年第三季度报告（600050 A股口径）", CU_2023_Q3_SINA_URL, "以A股口径Q3毛利22,782.899百万元除以Q3营业收入89,859.911百万元，毛利率为25.354%。", "official_gross_profit_divided_by_revenue_reconciliation", CU_2023_Q3_DETAIL_SOURCES),
    _official_record("中国联通", "Q3 2023", "total_assets", 665846.210, "millions CNY", "中国联通2023年第三季度报告（600050 A股口径）", CU_2023_Q3_SINA_URL, "A股三季报资产负债表披露2023年9月30日资产总计665,846.210百万元。", "official_balance_sheet_row_check", CU_2023_Q3_DETAIL_SOURCES),
    _official_record("中国联通", "Q3 2023", "total_debt", 47411.165, "millions CNY", "中国联通2023年第三季度报告（600050 A股口径）", CU_2023_Q3_SINA_URL, "A股三季报资产负债表披露短期借款860.921百万元、一年内到期的非流动负债11,840.553百万元、长期借款1,613.809百万元、租赁负债33,095.882百万元，合计总债务47,411.165百万元。", "official_borrowings_plus_lease_liabilities_reconciliation", CU_2023_Q3_DETAIL_SOURCES),
    _official_record("中国联通", "Q4 2023", "cash_and_equivalents", 47737.212, "millions CNY", "中国联通2023年度报告（600050 A股口径）", CU_2023_ANNUAL_SINA_URL, "A股年报现金流量表披露2023年末现金及现金等价物余额47,737.212百万元。", "official_cash_flow_statement_cash_equivalents_check", CU_2023_Q4_DETAIL_SOURCES),
    _official_record("中国联通", "Q4 2023", "gross_profit", 20444.802, "millions CNY", "中国联通2023年度报告（600050 A股口径）", CU_2023_ANNUAL_SINA_URL, "A股年报披露全年营业收入372,596.794百万元、营业成本281,230.556百万元；减前三季度营业收入281,692.598百万元和营业成本210,771.162百万元，复算Q4毛利为20,444.802百万元。", "official_full_year_minus_9m_revenue_minus_cost_reconciliation", CU_2023_Q4_DETAIL_SOURCES),
    _official_record("中国联通", "Q4 2023", "gross_margin", 22.490, "percent", "中国联通2023年度报告（600050 A股口径）", CU_2023_ANNUAL_SINA_URL, "以A股口径Q4毛利20,444.802百万元除以Q4营业收入90,904.196百万元，毛利率为22.490%。", "official_gross_profit_divided_by_revenue_reconciliation", CU_2023_Q4_DETAIL_SOURCES),
    _official_record("中国联通", "Q4 2023", "total_assets", 662844.797, "millions CNY", "中国联通2023年度报告（600050 A股口径）", CU_2023_ANNUAL_SINA_URL, "A股年报资产负债表披露2023年12月31日资产总计662,844.797百万元。", "official_balance_sheet_row_check", CU_2023_Q4_DETAIL_SOURCES),
    _official_record("中国联通", "Q4 2023", "total_debt", 46426.632, "millions CNY", "中国联通2023年度报告（600050 A股口径）", CU_2023_ANNUAL_SINA_URL, "A股年报资产负债表披露短期借款680.625百万元、一年内到期的非流动负债12,995.948百万元、长期借款2,133.119百万元、租赁负债30,616.939百万元，合计总债务46,426.632百万元；年报带息债务表亦列示46,426百万元。", "official_borrowings_plus_lease_liabilities_reconciliation", CU_2023_Q4_DETAIL_SOURCES),
]


CU_2024_QUARTERLY_METRICS = {
    "Q1 2024": {"revenue": 99496, "ebitda": 26611, "net_income": 5613},
    "Q2 2024": {"revenue": 97844, "ebitda": 28399, "net_income": 8177},
    "Q3 2024": {"revenue": 92780, "ebitda": 25390, "net_income": 5240},
    "Q4 2024": {"revenue": 99469, "ebitda": 19020, "net_income": 1583},
}

CU_2024_SOURCES_BY_PERIOD = {
    "Q1 2024": CU_2024_Q1_SOURCES,
    "Q2 2024": CU_2024_Q2_SOURCES,
    "Q3 2024": CU_2024_Q3_SOURCES,
    "Q4 2024": CU_2024_Q4_SOURCES,
}

CU_2024_METRIC_EVIDENCE = {
    "revenue": "中国联通官方Q1/H1/9M/FY披露复核{period_label} operating revenue 为人民币 {display_value} 百万元。",
    "ebitda": "中国联通官方Q1/H1/9M/FY披露复核{period_label} EBITDA 为人民币 {display_value} 百万元。",
    "net_income": "中国联通官方Q1/H1/9M/FY披露复核{period_label}归属于权益股东利润为人民币 {display_value} 百万元。",
}

CU_2024_OFFICIAL_VERIFICATIONS = [
    _official_record(
        "中国联通",
        period,
        metric_key,
        value,
        "millions CNY",
        "中国联通2024官方季度/累计业绩披露",
        CU_2024_SOURCES_BY_PERIOD[period][-1]["url"],
        CU_2024_METRIC_EVIDENCE[metric_key].format(
            period_label=period.replace(" ", "/"),
            display_value=value,
        ),
        "official_cumulative_report_quarter_reconciliation",
        CU_2024_SOURCES_BY_PERIOD[period],
    )
    for period, metrics in CU_2024_QUARTERLY_METRICS.items()
    for metric_key, value in metrics.items()
]

CU_2024_DETAIL_OFFICIAL_VERIFICATIONS = [
    _official_record("中国联通", "Q1 2024", "cash_and_equivalents", 45065.738, "millions CNY", "中国联通2024年第一季度报告（600050 A股口径）", CU_2024_Q1_SINA_URL, "A股一季报现金流量表披露2024年3月31日期末现金及现金等价物余额45,065.738百万元。", "official_cash_flow_statement_cash_equivalents_check", CU_2024_Q1_DETAIL_SOURCES),
    _official_record("中国联通", "Q1 2024", "gross_profit", 24420.749, "millions CNY", "中国联通2024年第一季度报告（600050 A股口径）", CU_2024_Q1_SINA_URL, "A股一季报披露营业收入99,496.340百万元、营业成本75,075.591百万元；按收入减成本复算毛利为24,420.749百万元。", "official_revenue_minus_operating_cost_reconciliation", CU_2024_Q1_DETAIL_SOURCES),
    _official_record("中国联通", "Q1 2024", "gross_margin", 24.544, "percent", "中国联通2024年第一季度报告（600050 A股口径）", CU_2024_Q1_SINA_URL, "以A股口径Q1毛利24,420.749百万元除以营业收入99,496.340百万元，毛利率为24.544%。", "official_gross_profit_divided_by_revenue_reconciliation", CU_2024_Q1_DETAIL_SOURCES),
    _official_record("中国联通", "Q1 2024", "operating_income", 7089.224, "millions CNY", "中国联通2024年第一季度报告（600050 A股口径）", CU_2024_Q1_SINA_URL, "A股一季报合并利润表披露营业利润7,089.224百万元。", "official_income_statement_row_check", CU_2024_Q1_DETAIL_SOURCES),
    _official_record("中国联通", "Q1 2024", "operating_margin", 7.125, "percent", "中国联通2024年第一季度报告（600050 A股口径）", CU_2024_Q1_SINA_URL, "以A股口径Q1营业利润7,089.224百万元除以营业收入99,496.340百万元，经营利润率为7.125%。", "official_operating_income_divided_by_revenue_reconciliation", CU_2024_Q1_DETAIL_SOURCES),
    _official_record("中国联通", "Q1 2024", "revenue_growth_yoy", 2.340, "percent", "中国联通2024年第一季度报告（600050 A股口径）", CU_2024_Q1_SINA_URL, "A股一季报披露2024Q1营业收入99,496.340百万元、2023Q1营业收入97,221.823百万元，复算同比为2.340%。", "official_current_prior_period_recalculation", CU_2024_Q1_DETAIL_SOURCES),
    _official_record("中国联通", "Q1 2024", "total_assets", 665855.422, "millions CNY", "中国联通2024年第一季度报告（600050 A股口径）", CU_2024_Q1_SINA_URL, "A股一季报资产负债表披露2024年3月31日资产总计665,855.422百万元。", "official_balance_sheet_row_check", CU_2024_Q1_DETAIL_SOURCES),
    _official_record("中国联通", "Q1 2024", "total_debt", 45770.558, "millions CNY", "中国联通2024年第一季度报告（600050 A股口径）", CU_2024_Q1_SINA_URL, "A股一季报资产负债表披露短期借款530.542百万元、一年内到期的非流动负债13,456.803百万元、长期借款2,141.511百万元、租赁负债29,641.702百万元，合计总债务45,770.558百万元。", "official_borrowings_plus_lease_liabilities_reconciliation", CU_2024_Q1_DETAIL_SOURCES),
    _official_record("中国联通", "Q1 2024", "ebitda_margin", 26.746, "percent", "中国联通2024年第一季度主要财务数据", CU_2024_Q1_URL, "中国联通港股一季度公告披露Q1 EBITDA 26,611百万元，A股一季报披露营业收入99,496.340百万元；按EBITDA除营业收入复算为26.746%。", "official_ebitda_divided_by_revenue_reconciliation", CU_2024_Q1_DETAIL_SOURCES),
    _official_record("中国联通", "Q2 2024", "cash_and_equivalents", 45846.718, "millions CNY", "中国联通2024年半年度报告（600050 A股口径）", CU_2024_H1_SINA_URL, "A股半年报现金流量表披露2024年6月30日期末现金及现金等价物余额45,846.718百万元。", "official_cash_flow_statement_cash_equivalents_check", CU_2024_Q2_DETAIL_SOURCES),
    _official_record("中国联通", "Q2 2024", "gross_profit", 26914.858, "millions CNY", "中国联通2024年半年度报告（600050 A股口径）", CU_2024_H1_SINA_URL, "A股半年报披露H1营业收入197,340.955百万元、营业成本146,005.348百万元；减Q1营业收入99,496.340百万元和营业成本75,075.591百万元，复算Q2毛利为26,914.858百万元。", "official_h1_minus_q1_revenue_minus_cost_reconciliation", CU_2024_Q2_DETAIL_SOURCES),
    _official_record("中国联通", "Q2 2024", "gross_margin", 27.508, "percent", "中国联通2024年半年度报告（600050 A股口径）", CU_2024_H1_SINA_URL, "以A股口径Q2毛利26,914.858百万元除以Q2营业收入97,844.615百万元，毛利率为27.508%。", "official_gross_profit_divided_by_revenue_reconciliation", CU_2024_Q2_DETAIL_SOURCES),
    _official_record("中国联通", "Q2 2024", "operating_income", 8889.237, "millions CNY", "中国联通2024年半年度报告（600050 A股口径）", CU_2024_H1_SINA_URL, "A股半年报披露H1营业利润15,978.462百万元，减Q1营业利润7,089.224百万元，复算Q2营业利润8,889.237百万元。", "official_h1_minus_q1_operating_profit_reconciliation", CU_2024_Q2_DETAIL_SOURCES),
    _official_record("中国联通", "Q2 2024", "operating_margin", 9.085, "percent", "中国联通2024年半年度报告（600050 A股口径）", CU_2024_H1_SINA_URL, "以A股口径Q2营业利润8,889.237百万元除以Q2营业收入97,844.615百万元，经营利润率为9.085%。", "official_operating_income_divided_by_revenue_reconciliation", CU_2024_Q2_DETAIL_SOURCES),
    _official_record("中国联通", "Q2 2024", "revenue_growth_yoy", 3.418, "percent", "中国联通2024年半年度报告（600050 A股口径）", CU_2024_H1_SINA_URL, "A股口径2024Q2营业收入97,844.615百万元；对比2023Q2营业收入94,610.864百万元，复算同比为3.418%。", "official_h1_minus_q1_prior_quarter_reconciliation", CU_2024_Q2_DETAIL_SOURCES),
    _official_record("中国联通", "Q2 2024", "total_assets", 668339.156, "millions CNY", "中国联通2024年半年度报告（600050 A股口径）", CU_2024_H1_SINA_URL, "A股半年报资产负债表披露2024年6月30日资产总计668,339.156百万元。", "official_balance_sheet_row_check", CU_2024_Q2_DETAIL_SOURCES),
    _official_record("中国联通", "Q2 2024", "total_debt", 44085.372, "millions CNY", "中国联通2024年半年度报告（600050 A股口径）", CU_2024_H1_SINA_URL, "A股半年报资产负债表披露短期借款690.658百万元、一年内到期的非流动负债13,450.300百万元、长期借款2,002.229百万元、租赁负债27,942.185百万元，合计总债务44,085.372百万元；年报带息债务表亦列示44,085百万元。", "official_borrowings_plus_lease_liabilities_reconciliation", CU_2024_Q2_DETAIL_SOURCES),
    _official_record("中国联通", "Q2 2024", "ebitda_margin", 29.025, "percent", "中国联通2024中期报告", CU_2024_H1_URL, "中国联通中期报告披露H1 EBITDA 55,010百万元，减Q1 EBITDA 26,611百万元，复算Q2 EBITDA 28,399百万元；除以A股口径Q2营业收入97,844.615百万元，EBITDA margin为29.025%。", "official_h1_minus_q1_ebitda_divided_by_revenue_reconciliation", CU_2024_Q2_DETAIL_SOURCES),
    _official_record("中国联通", "Q3 2024", "cash_and_equivalents", 49459.744, "millions CNY", "中国联通2024年第三季度报告（600050 A股口径）", CU_2024_Q3_SINA_URL, "A股三季报现金流量表披露2024年9月30日期末现金及现金等价物余额49,459.744百万元。", "official_cash_flow_statement_cash_equivalents_check", CU_2024_Q3_DETAIL_SOURCES),
    _official_record("中国联通", "Q3 2024", "gross_profit", 24141.194, "millions CNY", "中国联通2024年第三季度报告（600050 A股口径）", CU_2024_Q3_SINA_URL, "A股三季报披露前三季度营业收入290,122.947百万元、营业成本214,646.146百万元；减H1营业收入197,340.955百万元和营业成本146,005.348百万元，复算Q3毛利为24,141.194百万元。", "official_9m_minus_h1_revenue_minus_cost_reconciliation", CU_2024_Q3_DETAIL_SOURCES),
    _official_record("中国联通", "Q3 2024", "gross_margin", 26.019, "percent", "中国联通2024年第三季度报告（600050 A股口径）", CU_2024_Q3_SINA_URL, "以A股口径Q3毛利24,141.194百万元除以Q3营业收入92,781.992百万元，毛利率为26.019%。", "official_gross_profit_divided_by_revenue_reconciliation", CU_2024_Q3_DETAIL_SOURCES),
    _official_record("中国联通", "Q3 2024", "operating_income", 5972.020, "millions CNY", "中国联通2024年第三季度报告（600050 A股口径）", CU_2024_Q3_SINA_URL, "A股三季报披露前三季度营业利润21,950.482百万元，减H1营业利润15,978.462百万元，复算Q3营业利润5,972.020百万元。", "official_9m_minus_h1_operating_profit_reconciliation", CU_2024_Q3_DETAIL_SOURCES),
    _official_record("中国联通", "Q3 2024", "operating_margin", 6.437, "percent", "中国联通2024年第三季度报告（600050 A股口径）", CU_2024_Q3_SINA_URL, "以A股口径Q3营业利润5,972.020百万元除以Q3营业收入92,781.992百万元，经营利润率为6.437%。", "official_operating_income_divided_by_revenue_reconciliation", CU_2024_Q3_DETAIL_SOURCES),
    _official_record("中国联通", "Q3 2024", "revenue_growth_yoy", 3.252, "percent", "中国联通2024年第三季度报告（600050 A股口径）", CU_2024_Q3_SINA_URL, "A股口径2024Q3营业收入92,781.992百万元；对比2023Q3营业收入89,859.911百万元，复算同比为3.252%。", "official_9m_minus_h1_prior_quarter_reconciliation", CU_2024_Q3_DETAIL_SOURCES),
    _official_record("中国联通", "Q3 2024", "total_assets", 671533.603, "millions CNY", "中国联通2024年第三季度报告（600050 A股口径）", CU_2024_Q3_SINA_URL, "A股三季报资产负债表披露2024年9月30日资产总计671,533.603百万元。", "official_balance_sheet_row_check", CU_2024_Q3_DETAIL_SOURCES),
    _official_record("中国联通", "Q3 2024", "total_debt", 42749.737, "millions CNY", "中国联通2024年第三季度报告（600050 A股口径）", CU_2024_Q3_SINA_URL, "A股三季报资产负债表披露短期借款690.579百万元、一年内到期的非流动负债13,426.170百万元、长期借款1,983.078百万元、租赁负债26,649.910百万元，合计总债务42,749.737百万元。", "official_borrowings_plus_lease_liabilities_reconciliation", CU_2024_Q3_DETAIL_SOURCES),
    _official_record("中国联通", "Q3 2024", "ebitda_margin", 27.365, "percent", "中国联通2024年前三季度业绩公告", CU_2024_Q3_URL, "中国联通前三季度公告披露9M EBITDA 80,400百万元，减H1 EBITDA 55,010百万元，复算Q3 EBITDA 25,390百万元；除以A股口径Q3营业收入92,781.992百万元，EBITDA margin为27.365%。", "official_9m_minus_h1_ebitda_divided_by_revenue_reconciliation", CU_2024_Q3_DETAIL_SOURCES),
    _official_record("中国联通", "Q4 2024", "cash_and_equivalents", 28486.565, "millions CNY", "中国联通2024年度报告（600050 A股口径）", CU_2024_ANNUAL_SINA_URL, "A股年报现金流量表披露2024年末现金及现金等价物余额28,486.565百万元。", "official_cash_flow_statement_cash_equivalents_check", CU_2024_Q4_DETAIL_SOURCES),
    _official_record("中国联通", "Q4 2024", "gross_profit", 15766.629, "millions CNY", "中国联通2024年度报告（600050 A股口径）", CU_2024_ANNUAL_SINA_URL, "A股年报披露全年营业收入389,589.220百万元、营业成本298,345.790百万元；减前三季度营业收入290,122.947百万元和营业成本214,646.146百万元，复算Q4毛利为15,766.629百万元。", "official_full_year_minus_9m_revenue_minus_cost_reconciliation", CU_2024_Q4_DETAIL_SOURCES),
    _official_record("中国联通", "Q4 2024", "gross_margin", 15.851, "percent", "中国联通2024年度报告（600050 A股口径）", CU_2024_ANNUAL_SINA_URL, "以A股口径Q4毛利15,766.629百万元除以Q4营业收入99,466.273百万元，毛利率为15.851%。", "official_gross_profit_divided_by_revenue_reconciliation", CU_2024_Q4_DETAIL_SOURCES),
    _official_record("中国联通", "Q4 2024", "operating_income", 749.075, "millions CNY", "中国联通2024年度报告（600050 A股口径）", CU_2024_ANNUAL_SINA_URL, "A股年报披露全年营业利润22,699.557百万元，减前三季度营业利润21,950.482百万元，复算Q4营业利润749.075百万元。", "official_full_year_minus_9m_operating_profit_reconciliation", CU_2024_Q4_DETAIL_SOURCES),
    _official_record("中国联通", "Q4 2024", "operating_margin", 0.753, "percent", "中国联通2024年度报告（600050 A股口径）", CU_2024_ANNUAL_SINA_URL, "以A股口径Q4营业利润749.075百万元除以Q4营业收入99,466.273百万元，经营利润率为0.753%。", "official_operating_income_divided_by_revenue_reconciliation", CU_2024_Q4_DETAIL_SOURCES),
    _official_record("中国联通", "Q4 2024", "revenue_growth_yoy", 9.419, "percent", "中国联通2024年度报告（600050 A股口径）", CU_2024_ANNUAL_SINA_URL, "A股口径2024Q4营业收入99,466.273百万元；对比2023Q4营业收入90,904.196百万元，复算同比为9.419%。", "official_full_year_minus_9m_prior_year_reconciliation", CU_2024_Q4_DETAIL_SOURCES),
    _official_record("中国联通", "Q4 2024", "total_assets", 672836.702, "millions CNY", "中国联通2024年度报告（600050 A股口径）", CU_2024_ANNUAL_SINA_URL, "A股年报资产负债表披露2024年12月31日资产总计672,836.702百万元。", "official_balance_sheet_row_check", CU_2024_Q4_DETAIL_SOURCES),
    _official_record("中国联通", "Q4 2024", "total_debt", 41208.279, "millions CNY", "中国联通2024年度报告（600050 A股口径）", CU_2024_ANNUAL_SINA_URL, "A股年报资产负债表披露短期借款710.649百万元、一年内到期的非流动负债14,147.902百万元、长期借款2,127.522百万元、租赁负债24,222.206百万元，合计总债务41,208.279百万元。", "official_borrowings_plus_lease_liabilities_reconciliation", CU_2024_Q4_DETAIL_SOURCES),
    _official_record("中国联通", "Q4 2024", "ebitda_margin", 19.122, "percent", "中国联通2024年度业绩公告", CU_2024_ANNUAL_RESULTS_URL, "中国联通年度业绩公告披露全年EBITDA 99,420百万元，减前三季度EBITDA 80,400百万元，复算Q4 EBITDA 19,020百万元；除以A股口径Q4营业收入99,466.273百万元，EBITDA margin为19.122%。", "official_full_year_minus_9m_ebitda_divided_by_revenue_reconciliation", CU_2024_Q4_DETAIL_SOURCES),
]


TOWER_2023_PERIOD_SOURCE = {
    "Q1 2023": {
        "label": "中国铁塔2023年第一季度未经审核主要运营数据",
        "url": TOWER_2023_Q1_URL,
        "method": "official_source_row_check",
        "sources": TOWER_2023_Q1_SOURCES,
        "evidence_prefix": "2023年第一季度未经审核主要运营数据披露",
    },
    "Q2 2023": {
        "label": "中国铁塔2023中期业绩公告",
        "url": TOWER_2023_H1_URL,
        "method": "official_h1_minus_q1_reconciliation",
        "sources": TOWER_2023_Q2_SOURCES,
        "evidence_prefix": "2023中期业绩公告披露上半年累计值，减2023Q1官方值复算Q2",
    },
    "Q3 2023": {
        "label": "中国铁塔2023年前三季度未经审核主要运营数据",
        "url": TOWER_2023_Q3_URL,
        "method": "official_9m_minus_h1_reconciliation",
        "sources": TOWER_2023_Q3_SOURCES,
        "evidence_prefix": "2023年前三季度未经审核主要运营数据披露9M累计值，减2023H1官方值复算Q3",
    },
    "Q4 2023": {
        "label": "中国铁塔2023年度业绩公告",
        "url": TOWER_2023_ANNUAL_RESULTS_URL,
        "method": "official_annual_minus_9m_reconciliation",
        "sources": TOWER_2023_Q4_SOURCES,
        "evidence_prefix": "2023年度业绩公告披露全年值，减2023年前三季度官方值复算Q4",
    },
}


TOWER_2023_PERIOD_METRICS = {
    "Q1 2023": {
        "revenue": (23199, "millions CNY", "营业收入23,199百万元"),
        "revenue_growth_yoy": (2.5, "percent", "营业收入同比增长2.5%"),
        "operator_business_revenue": (20533, "millions CNY", "运营商业务收入20,533百万元"),
        "tower_business_revenue": (18832, "millions CNY", "塔类业务收入18,832百万元"),
        "das_business_revenue": (1701, "millions CNY", "室分业务收入1,701百万元"),
        "smart_business_revenue": (1632, "millions CNY", "智联业务收入1,632百万元"),
        "energy_business_revenue": (949, "millions CNY", "能源业务收入949百万元"),
        "ebitda": (16112, "millions CNY", "EBITDA 16,112百万元"),
        "ebitda_margin": (69.5, "percent", "EBITDA率69.5%"),
        "net_income": (2506, "millions CNY", "归属于本公司股东的利润2,506百万元"),
        "total_assets": (308586, "millions CNY", "2023年3月31日总资产308,586百万元"),
    },
    "Q2 2023": {
        "revenue": (23262, "millions CNY", "上半年营业收入46,461减Q1 23,199，复算Q2为23,262百万元"),
        "revenue_growth_yoy": (1.82, "percent", "Q2收入23,262百万元，相对2022Q2 22,846百万元复算同比约1.82%"),
        "operator_business_revenue": (20372, "millions CNY", "上半年Tower+DAS业务40,905减Q1 20,533，复算Q2为20,372百万元"),
        "tower_business_revenue": (18649, "millions CNY", "上半年Tower business 37,481减Q1 18,832，复算Q2为18,649百万元"),
        "das_business_revenue": (1723, "millions CNY", "上半年DAS business 3,424减Q1 1,701，复算Q2为1,723百万元"),
        "smart_business_revenue": (1754, "millions CNY", "上半年Smart Tower business 3,386减Q1 1,632，复算Q2为1,754百万元"),
        "energy_business_revenue": (1026, "millions CNY", "上半年Energy business 1,975减Q1 949，复算Q2为1,026百万元"),
        "ebitda": (15909, "millions CNY", "上半年EBITDA 32,021减Q1 16,112，复算Q2为15,909百万元"),
        "ebitda_margin": (68.39, "percent", "Q2 EBITDA 15,909除以Q2营业收入23,262，复算EBITDA率约68.39%"),
        "net_income": (2335, "millions CNY", "上半年归母利润4,841减Q1 2,506，复算Q2为2,335百万元"),
        "cash_and_equivalents": (3140, "millions CNY", "2023年6月30日现金及现金等价物3,140百万元"),
        "total_assets": (318063, "millions CNY", "2023年6月30日总资产318,063百万元"),
        "total_debt": (92223, "millions CNY", "2023年6月30日借款49,513+21,191及租赁负债14,543+6,976，合计92,223百万元"),
    },
    "Q3 2023": {
        "revenue": (23690, "millions CNY", "前三季度营业收入70,151减H1 46,461，复算Q3为23,690百万元"),
        "revenue_growth_yoy": (2.10, "percent", "Q3收入23,690百万元，相对2022Q3 23,203百万元复算同比约2.10%"),
        "operator_business_revenue": (20764, "millions CNY", "前三季度运营商业务61,669减H1 40,905，复算Q3为20,764百万元"),
        "tower_business_revenue": (18916, "millions CNY", "前三季度塔类业务56,397减H1 37,481，复算Q3为18,916百万元"),
        "das_business_revenue": (1848, "millions CNY", "前三季度室分业务5,272减H1 3,424，复算Q3为1,848百万元"),
        "smart_business_revenue": (1783, "millions CNY", "前三季度智联业务5,169减H1 3,386，复算Q3为1,783百万元"),
        "energy_business_revenue": (1066, "millions CNY", "前三季度能源业务3,041减H1 1,975，复算Q3为1,066百万元"),
        "ebitda": (16082, "millions CNY", "前三季度EBITDA 48,103减H1 32,021，复算Q3为16,082百万元"),
        "ebitda_margin": (67.89, "percent", "Q3 EBITDA 16,082除以Q3营业收入23,690，复算EBITDA率约67.89%"),
        "net_income": (2506, "millions CNY", "前三季度归母利润7,347减H1 4,841，复算Q3为2,506百万元"),
        "total_assets": (324502, "millions CNY", "2023年9月30日总资产324,502百万元"),
    },
    "Q4 2023": {
        "revenue": (23858, "millions CNY", "全年营业收入94,009减9M 70,151，复算Q4为23,858百万元"),
        "revenue_growth_yoy": (1.58, "percent", "Q4收入23,858百万元，相对2022Q4 23,488百万元复算同比约1.58%"),
        "operator_business_revenue": (20494, "millions CNY", "全年Tower+DAS业务82,163减9M 61,669，复算Q4为20,494百万元"),
        "tower_business_revenue": (18626, "millions CNY", "全年Tower business 75,023减9M 56,397，复算Q4为18,626百万元"),
        "das_business_revenue": (1868, "millions CNY", "全年DAS business 7,140减9M 5,272，复算Q4为1,868百万元"),
        "smart_business_revenue": (2114, "millions CNY", "全年Smart Tower business 7,283减9M 5,169，复算Q4为2,114百万元"),
        "energy_business_revenue": (1173, "millions CNY", "全年Energy business 4,214减9M 3,041，复算Q4为1,173百万元"),
        "ebitda": (15448, "millions CNY", "全年EBITDA 63,551减9M 48,103，复算Q4为15,448百万元"),
        "ebitda_margin": (64.75, "percent", "Q4 EBITDA 15,448除以Q4营业收入23,858，复算EBITDA率约64.75%"),
        "net_income": (2403, "millions CNY", "全年归母利润9,750减9M 7,347，复算Q4为2,403百万元"),
        "cash_and_equivalents": (3955, "millions CNY", "2023年12月31日现金及现金等价物3,955百万元"),
        "total_assets": (326007, "millions CNY", "2023年12月31日总资产326,007百万元"),
        "total_debt": (94626, "millions CNY", "2023年12月31日借款49,329+23,786及租赁负债14,647+6,864，合计94,626百万元"),
    },
}

TOWER_2022_PERIOD_SOURCE = {
    "Q1 2022": {
        "label": "中国铁塔2022年第一季度未经审核主要运营数据",
        "url": TOWER_2022_Q1_URL,
        "method": "official_source_row_check",
        "sources": TOWER_2022_Q1_SOURCES,
        "evidence_prefix": "2022年第一季度未经审核主要运营数据披露",
    },
    "Q2 2022": {
        "label": "中国铁塔2022中期报告",
        "url": TOWER_2022_H1_URL,
        "method": "official_h1_minus_q1_reconciliation",
        "sources": TOWER_2022_Q2_SOURCES,
        "evidence_prefix": "2022中期报告披露上半年累计值，减2022Q1官方值复算Q2",
    },
    "Q3 2022": {
        "label": "中国铁塔2022年前三季度未经审核主要运营数据",
        "url": TOWER_2022_Q3_URL,
        "method": "official_9m_minus_h1_reconciliation",
        "sources": TOWER_2022_Q3_SOURCES,
        "evidence_prefix": "2022年前三季度未经审核主要运营数据披露9M累计值，减2022H1官方值复算Q3",
    },
    "Q4 2022": {
        "label": "中国铁塔2022年度报告",
        "url": TOWER_2022_ANNUAL_REPORT_URL,
        "method": "official_annual_minus_9m_reconciliation",
        "sources": TOWER_2022_Q4_SOURCES,
        "evidence_prefix": "2022年度报告披露全年值，减2022年前三季度官方值复算Q4",
    },
}

TOWER_2022_PERIOD_METRICS = {
    "Q1 2022": {
        "revenue": (22633, "millions CNY", "营业收入22,633百万元"),
        "revenue_growth_yoy": (7.0, "percent", "营业收入同比增长7.0%"),
        "ebitda": (15682, "millions CNY", "EBITDA 15,682百万元"),
        "net_income": (2180, "millions CNY", "归属于本公司股东的利润2,180百万元"),
    },
    "Q2 2022": {
        "revenue": (22846, "millions CNY", "上半年营业收入45,479减Q1 22,633，复算Q2为22,846百万元"),
        "revenue_growth_yoy": (6.15, "percent", "Q2收入22,846百万元，相对2021Q2 21,522百万元复算同比约6.15%"),
        "ebitda": (16276, "millions CNY", "上半年EBITDA 31,958减Q1 15,682，复算Q2为16,276百万元"),
        "net_income": (2044, "millions CNY", "上半年归母利润4,224减Q1 2,180，复算Q2为2,044百万元"),
    },
    "Q3 2022": {
        "revenue": (23203, "millions CNY", "前三季度营业收入68,682减H1 45,479，复算Q3为23,203百万元"),
        "revenue_growth_yoy": (5.88, "percent", "Q3收入23,203百万元，相对2021Q3 21,915百万元复算同比约5.88%"),
        "ebitda": (15502, "millions CNY", "前三季度EBITDA 47,460减H1 31,958，复算Q3为15,502百万元"),
        "net_income": (2175, "millions CNY", "前三季度归母利润6,399减H1 4,224，复算Q3为2,175百万元"),
    },
    "Q4 2022": {
        "revenue": (23488, "millions CNY", "全年营业收入92,170减9M 68,682，复算Q4为23,488百万元"),
        "revenue_growth_yoy": (6.78, "percent", "Q4收入23,488百万元，相对2021Q4 21,997百万元复算同比约6.78%"),
        "ebitda": (15384, "millions CNY", "全年EBITDA 62,844减9M 47,460，复算Q4为15,384百万元"),
        "net_income": (2388, "millions CNY", "全年归母利润8,787减9M 6,399，复算Q4为2,388百万元"),
    },
}

TOWER_2022_OFFICIAL_VERIFICATIONS = [
    _official_record(
        "中国铁塔",
        period,
        metric_key,
        official_value,
        unit,
        TOWER_2022_PERIOD_SOURCE[period]["label"],
        TOWER_2022_PERIOD_SOURCE[period]["url"],
        f"{TOWER_2022_PERIOD_SOURCE[period]['evidence_prefix']}：{evidence}",
        TOWER_2022_PERIOD_SOURCE[period]["method"],
        TOWER_2022_PERIOD_SOURCE[period]["sources"],
    )
    for period, metrics in TOWER_2022_PERIOD_METRICS.items()
    for metric_key, (official_value, unit, evidence) in metrics.items()
]

TOWER_2020_PERIOD_SOURCE = {
    "Q1 2020": {
        "label": "中国铁塔2020年第一季度未经审核主要运营数据",
        "url": TOWER_2020_Q1_URL,
        "method": "official_quarterly_statement_check",
        "sources": TOWER_2020_Q1_SOURCES,
        "evidence_prefix": "2020年第一季度未经审核主要运营数据直接披露Q1核心经营数据",
    },
    "Q2 2020": {
        "label": "中国铁塔2020中期报告",
        "url": TOWER_2020_H1_URL,
        "method": "official_h1_minus_q1_reconciliation",
        "sources": TOWER_2020_Q2_SOURCES,
        "evidence_prefix": "2020中期报告披露上半年累计值，减2020Q1官方值复算Q2",
    },
    "Q3 2020": {
        "label": "中国铁塔2020年前三季度未经审核主要运营数据",
        "url": TOWER_2020_Q3_URL,
        "method": "official_9m_minus_h1_reconciliation",
        "sources": TOWER_2020_Q3_SOURCES,
        "evidence_prefix": "2020年前三季度未经审核主要运营数据披露9M累计值，减2020H1官方值复算Q3",
    },
    "Q4 2020": {
        "label": "中国铁塔2020年度业绩公告",
        "url": TOWER_2020_ANNUAL_RESULTS_URL,
        "method": "official_annual_minus_9m_reconciliation",
        "sources": TOWER_2020_Q4_SOURCES,
        "evidence_prefix": "2020年度业绩公告披露全年值，减2020年前三季度官方值复算Q4",
    },
}

TOWER_2020_PERIOD_METRICS = {
    "Q1 2020": {
        "revenue": (19690, "millions CNY", "营业收入19,690百万元"),
        "ebitda": (14532, "millions CNY", "EBITDA 14,532百万元"),
        "ebitda_margin": (73.804, "percent", "EBITDA 14,532百万元除以营业收入19,690百万元，复算EBITDA率73.804%；公告列示约73.8%"),
        "net_income": (1452, "millions CNY", "归属于本公司股东的利润1,452百万元"),
    },
    "Q2 2020": {
        "revenue": (20104, "millions CNY", "H1营业收入39,794减Q1 19,690，复算Q2为20,104百万元"),
        "ebitda": (14568, "millions CNY", "H1 EBITDA 29,100减Q1 14,532，复算Q2为14,568百万元"),
        "ebitda_margin": (72.463, "percent", "Q2 EBITDA 14,568百万元除以Q2营业收入20,104百万元，复算EBITDA率72.463%"),
        "net_income": (1526, "millions CNY", "H1归母利润2,978减Q1 1,452，复算Q2为1,526百万元"),
    },
    "Q3 2020": {
        "revenue": (20426, "millions CNY", "9M营业收入60,220减H1 39,794，复算Q3为20,426百万元"),
        "ebitda": (14919, "millions CNY", "9M EBITDA 44,019减H1 29,100，复算Q3为14,919百万元"),
        "ebitda_margin": (73.039, "percent", "Q3 EBITDA 14,919百万元除以Q3营业收入20,426百万元，复算EBITDA率73.039%"),
        "net_income": (1586, "millions CNY", "9M归母利润4,564减H1 2,978，复算Q3为1,586百万元"),
    },
    "Q4 2020": {
        "revenue": (20879, "millions CNY", "全年营业收入81,099减9M 60,220，复算Q4为20,879百万元"),
        "ebitda": (15508, "millions CNY", "全年EBITDA 59,527减9M 44,019，复算Q4为15,508百万元"),
        "ebitda_margin": (74.276, "percent", "Q4 EBITDA 15,508百万元除以Q4营业收入20,879百万元，复算EBITDA率74.276%"),
        "net_income": (1864, "millions CNY", "全年归母利润6,428减9M 4,564，复算Q4为1,864百万元"),
    },
}

TOWER_2020_OFFICIAL_VERIFICATIONS = [
    _official_record(
        "中国铁塔",
        period,
        metric_key,
        official_value,
        unit,
        TOWER_2020_PERIOD_SOURCE[period]["label"],
        TOWER_2020_PERIOD_SOURCE[period]["url"],
        f"{TOWER_2020_PERIOD_SOURCE[period]['evidence_prefix']}：{evidence}",
        TOWER_2020_PERIOD_SOURCE[period]["method"],
        TOWER_2020_PERIOD_SOURCE[period]["sources"],
    )
    for period, metrics in TOWER_2020_PERIOD_METRICS.items()
    for metric_key, (official_value, unit, evidence) in metrics.items()
]

TOWER_2019_PERIOD_SOURCE = {
    "Q1 2019": {
        "label": "中国铁塔2019年第一季度未经审核主要运营数据",
        "url": TOWER_2019_Q1_URL,
        "method": "official_quarterly_statement_check",
        "sources": TOWER_2019_Q1_SOURCES,
        "evidence_prefix": "2019年第一季度未经审核主要运营数据直接披露Q1核心经营数据",
    },
    "Q2 2019": {
        "label": "中国铁塔2019中期报告",
        "url": TOWER_2019_H1_URL,
        "method": "official_h1_minus_q1_reconciliation",
        "sources": TOWER_2019_Q2_SOURCES,
        "evidence_prefix": "2019中期报告披露上半年累计值，减2019Q1官方值复算Q2",
    },
    "Q3 2019": {
        "label": "中国铁塔2019年前三季度未经审核主要运营数据",
        "url": TOWER_2019_Q3_URL,
        "method": "official_9m_minus_h1_reconciliation",
        "sources": TOWER_2019_Q3_SOURCES,
        "evidence_prefix": "2019年前三季度未经审核主要运营数据披露9M累计值，减2019H1官方值复算Q3",
    },
    "Q4 2019": {
        "label": "中国铁塔2019年度业绩公告",
        "url": TOWER_2019_ANNUAL_RESULTS_URL,
        "method": "official_annual_minus_9m_reconciliation",
        "sources": TOWER_2019_Q4_SOURCES,
        "evidence_prefix": "2019年度业绩公告披露全年值，减2019年前三季度官方值复算Q4",
    },
}

TOWER_2019_PERIOD_METRICS = {
    "Q1 2019": {
        "revenue": (18897, "millions CNY", "营业收入18,897百万元"),
        "ebitda": (13590, "millions CNY", "EBITDA 13,590百万元"),
        "ebitda_margin": (71.916, "percent", "EBITDA 13,590百万元除以营业收入18,897百万元，复算EBITDA率71.916%"),
        "net_income": (1284, "millions CNY", "归属于本公司股东的利润1,284百万元"),
    },
    "Q2 2019": {
        "revenue": (19083, "millions CNY", "H1营业收入37,980减Q1 18,897，复算Q2为19,083百万元"),
        "ebitda": (14225, "millions CNY", "H1 EBITDA 27,815减Q1 13,590，复算Q2为14,225百万元"),
        "ebitda_margin": (74.543, "percent", "Q2 EBITDA 14,225百万元除以Q2营业收入19,083百万元，复算EBITDA率74.543%"),
        "net_income": (1264, "millions CNY", "H1归母利润2,548减Q1 1,284，复算Q2为1,264百万元"),
    },
    "Q3 2019": {
        "revenue": (19061, "millions CNY", "9M营业收入57,041减H1 37,980，复算Q3为19,061百万元"),
        "ebitda": (13959, "millions CNY", "9M EBITDA 41,774减H1 27,815，复算Q3为13,959百万元"),
        "ebitda_margin": (73.233, "percent", "Q3 EBITDA 13,959百万元除以Q3营业收入19,061百万元，复算EBITDA率73.233%"),
        "net_income": (1325, "millions CNY", "9M归母利润3,873减H1 2,548，复算Q3为1,325百万元"),
    },
    "Q4 2019": {
        "revenue": (19387, "millions CNY", "全年营业收入76,428减9M 57,041，复算Q4为19,387百万元"),
        "ebitda": (14922, "millions CNY", "全年EBITDA 56,696减9M 41,774，复算Q4为14,922百万元"),
        "ebitda_margin": (76.969, "percent", "Q4 EBITDA 14,922百万元除以Q4营业收入19,387百万元，复算EBITDA率76.969%"),
        "net_income": (1349, "millions CNY", "全年归母利润5,222减9M 3,873，复算Q4为1,349百万元"),
    },
}

TOWER_2019_OFFICIAL_VERIFICATIONS = [
    _official_record(
        "中国铁塔",
        period,
        metric_key,
        official_value,
        unit,
        TOWER_2019_PERIOD_SOURCE[period]["label"],
        TOWER_2019_PERIOD_SOURCE[period]["url"],
        f"{TOWER_2019_PERIOD_SOURCE[period]['evidence_prefix']}：{evidence}",
        TOWER_2019_PERIOD_SOURCE[period]["method"],
        TOWER_2019_PERIOD_SOURCE[period]["sources"],
    )
    for period, metrics in TOWER_2019_PERIOD_METRICS.items()
    for metric_key, (official_value, unit, evidence) in metrics.items()
]

TOWER_2017_2018_Q1_SOURCES = [
    {"label": "中国铁塔2018全球发售招股书", "url": TOWER_2018_PROSPECTUS_URL, "evidence": "招股书 Accountant's Report 披露2017全年、2017Q1和2018Q1营业收入、EBITDA、EBITDA率和归母利润。"},
    {"label": "中国铁塔2018中期业绩公告", "url": TOWER_2018_H1_RESULTS_URL, "evidence": "中期业绩公告披露2018H1及2017H1累计核心指标，用于交叉核验Q1与H1关系。"},
    {"label": "中国铁塔2018年前三季度未经审核主要运营数据", "url": TOWER_2018_Q3_URL, "evidence": "三季度公告披露2018/2017 9M累计核心指标，用于交叉核验Q1至9M趋势。"},
]

TOWER_2017_2018_Q2_SOURCES = [
    {"label": "中国铁塔2018全球发售招股书", "url": TOWER_2018_PROSPECTUS_URL, "evidence": "招股书披露2017Q1和2018Q1核心财务值。"},
    {"label": "中国铁塔2018中期报告", "url": TOWER_2018_H1_REPORT_URL, "evidence": "中期报告披露2018H1及2017H1营业收入、EBITDA和归母利润，Q2由H1减Q1复算。"},
    {"label": "中国铁塔2018年前三季度未经审核主要运营数据", "url": TOWER_2018_Q3_URL, "evidence": "三季度公告披露2018/2017 9M累计核心指标，用于交叉核验H1至9M关系。"},
]

TOWER_2017_2018_Q3_SOURCES = [
    {"label": "中国铁塔2018中期报告", "url": TOWER_2018_H1_REPORT_URL, "evidence": "中期报告披露2018H1及2017H1累计值。"},
    {"label": "中国铁塔2018年前三季度未经审核主要运营数据", "url": TOWER_2018_Q3_URL, "evidence": "三季度公告披露2018/2017 9M营业收入、EBITDA和归母利润，Q3由9M减H1复算。"},
    {"label": "中国铁塔2018年报", "url": TOWER_2018_ANNUAL_REPORT_URL, "evidence": "2018年报披露2018及2017全年核心经营数据，用于全年链路交叉核验。"},
]

TOWER_2017_2018_Q4_SOURCES = [
    {"label": "中国铁塔2018年前三季度未经审核主要运营数据", "url": TOWER_2018_Q3_URL, "evidence": "三季度公告披露2018/2017 9M累计值。"},
    {"label": "中国铁塔2018年报", "url": TOWER_2018_ANNUAL_REPORT_URL, "evidence": "2018年报披露2018及2017全年营业收入、EBITDA和归母利润，Q4由FY减9M复算。"},
    {"label": "中国铁塔2018全球发售招股书", "url": TOWER_2018_PROSPECTUS_URL, "evidence": "招股书披露2017全年和Q1核心指标，用于交叉核验2017全年口径。"},
]

TOWER_2017_2018_PERIOD_SOURCE = {
    "Q1 2017": {"label": "中国铁塔2018全球发售招股书", "url": TOWER_2018_PROSPECTUS_URL, "method": "official_prospectus_quarter_statement_check", "sources": TOWER_2017_2018_Q1_SOURCES, "evidence_prefix": "招股书 Accountant's Report 直接披露2017Q1核心财务指标"},
    "Q2 2017": {"label": "中国铁塔2018中期报告减招股书Q1", "url": TOWER_2018_H1_REPORT_URL, "method": "official_h1_minus_q1_reconciliation", "sources": TOWER_2017_2018_Q2_SOURCES, "evidence_prefix": "2018中期报告比较栏披露2017H1累计值，减招股书2017Q1复算Q2"},
    "Q3 2017": {"label": "中国铁塔2018三季度公告减2018中期报告比较栏", "url": TOWER_2018_Q3_URL, "method": "official_9m_minus_h1_reconciliation", "sources": TOWER_2017_2018_Q3_SOURCES, "evidence_prefix": "2018三季度公告披露2017 9M累计值，减2017H1累计值复算Q3"},
    "Q4 2017": {"label": "中国铁塔2018年报减2018三季度公告比较栏", "url": TOWER_2018_ANNUAL_REPORT_URL, "method": "official_annual_minus_9m_reconciliation", "sources": TOWER_2017_2018_Q4_SOURCES, "evidence_prefix": "2018年报披露2017全年值，减2017 9M累计值复算Q4"},
    "Q1 2018": {"label": "中国铁塔2018全球发售招股书", "url": TOWER_2018_PROSPECTUS_URL, "method": "official_prospectus_quarter_statement_check", "sources": TOWER_2017_2018_Q1_SOURCES, "evidence_prefix": "招股书 Accountant's Report 直接披露2018Q1核心财务指标"},
    "Q2 2018": {"label": "中国铁塔2018中期报告减招股书Q1", "url": TOWER_2018_H1_REPORT_URL, "method": "official_h1_minus_q1_reconciliation", "sources": TOWER_2017_2018_Q2_SOURCES, "evidence_prefix": "2018中期报告披露2018H1累计值，减招股书2018Q1复算Q2"},
    "Q3 2018": {"label": "中国铁塔2018三季度公告减2018中期报告", "url": TOWER_2018_Q3_URL, "method": "official_9m_minus_h1_reconciliation", "sources": TOWER_2017_2018_Q3_SOURCES, "evidence_prefix": "2018三季度公告披露2018 9M累计值，减2018H1累计值复算Q3"},
    "Q4 2018": {"label": "中国铁塔2018年报减2018三季度公告", "url": TOWER_2018_ANNUAL_REPORT_URL, "method": "official_annual_minus_9m_reconciliation", "sources": TOWER_2017_2018_Q4_SOURCES, "evidence_prefix": "2018年报披露2018全年值，减2018 9M累计值复算Q4"},
}

TOWER_2017_2018_PERIOD_METRICS = {
    "Q1 2017": {
        "revenue": (16449, "millions CNY", "招股书披露2017Q1营业收入16,449百万元"),
        "ebitda": (9749, "millions CNY", "招股书披露2017Q1 EBITDA 9,749百万元"),
        "ebitda_margin": (59.268, "percent", "2017Q1 EBITDA 9,749百万元除以营业收入16,449百万元，复算EBITDA率59.268%"),
        "net_income": (484, "millions CNY", "招股书披露2017Q1归母利润484百万元"),
    },
    "Q2 2017": {
        "revenue": (16823, "millions CNY", "2017H1营业收入33,272减Q1 16,449，复算Q2为16,823百万元"),
        "ebitda": (10158, "millions CNY", "2017H1 EBITDA 19,907减Q1 9,749，复算Q2为10,158百万元"),
        "ebitda_margin": (60.382, "percent", "Q2 EBITDA 10,158百万元除以Q2营业收入16,823百万元，复算EBITDA率60.382%"),
        "net_income": (636, "millions CNY", "2017H1归母利润1,120减Q1 484，复算Q2为636百万元"),
    },
    "Q3 2017": {
        "revenue": (17279, "millions CNY", "2017 9M营业收入50,551减H1 33,272，复算Q3为17,279百万元"),
        "ebitda": (10194, "millions CNY", "2017 9M EBITDA 30,101减H1 19,907，复算Q3为10,194百万元"),
        "ebitda_margin": (58.996, "percent", "Q3 EBITDA 10,194百万元除以Q3营业收入17,279百万元，复算EBITDA率58.996%"),
        "net_income": (561, "millions CNY", "2017 9M归母利润1,681减H1 1,120，复算Q3为561百万元"),
    },
    "Q4 2017": {
        "revenue": (18114, "millions CNY", "2017全年营业收入68,665减9M 50,551，复算Q4为18,114百万元"),
        "ebitda": (10256, "millions CNY", "2017全年EBITDA 40,357减9M 30,101，复算Q4为10,256百万元"),
        "ebitda_margin": (56.619, "percent", "Q4 EBITDA 10,256百万元除以Q4营业收入18,114百万元，复算EBITDA率56.619%"),
        "net_income": (262, "millions CNY", "2017全年归母利润1,943减9M 1,681，复算Q4为262百万元"),
    },
    "Q1 2018": {
        "revenue": (17244, "millions CNY", "招股书披露2018Q1营业收入17,244百万元"),
        "ebitda": (10130, "millions CNY", "招股书披露2018Q1 EBITDA 10,130百万元"),
        "ebitda_margin": (58.745, "percent", "2018Q1 EBITDA 10,130百万元除以营业收入17,244百万元，复算EBITDA率58.745%"),
        "net_income": (380, "millions CNY", "招股书披露2018Q1归母利润380百万元"),
    },
    "Q2 2018": {
        "revenue": (18091, "millions CNY", "2018H1营业收入35,335减Q1 17,244，复算Q2为18,091百万元"),
        "ebitda": (10777, "millions CNY", "2018H1 EBITDA 20,907减Q1 10,130，复算Q2为10,777百万元"),
        "ebitda_margin": (59.571, "percent", "Q2 EBITDA 10,777百万元除以Q2营业收入18,091百万元，复算EBITDA率59.571%"),
        "net_income": (830, "millions CNY", "2018H1归母利润1,210减Q1 380，复算Q2为830百万元"),
    },
    "Q3 2018": {
        "revenue": (18307, "millions CNY", "2018 9M营业收入53,642减H1 35,335，复算Q3为18,307百万元"),
        "ebitda": (10815, "millions CNY", "2018 9M EBITDA 31,722减H1 20,907，复算Q3为10,815百万元"),
        "ebitda_margin": (59.076, "percent", "Q3 EBITDA 10,815百万元除以Q3营业收入18,307百万元，复算EBITDA率59.076%"),
        "net_income": (751, "millions CNY", "2018 9M归母利润1,961减H1 1,210，复算Q3为751百万元"),
    },
    "Q4 2018": {
        "revenue": (18177, "millions CNY", "2018全年营业收入71,819减9M 53,642，复算Q4为18,177百万元"),
        "ebitda": (10051, "millions CNY", "2018全年EBITDA 41,773减9M 31,722，复算Q4为10,051百万元"),
        "ebitda_margin": (55.295, "percent", "Q4 EBITDA 10,051百万元除以Q4营业收入18,177百万元，复算EBITDA率55.295%"),
        "net_income": (689, "millions CNY", "2018全年归母利润2,650减9M 1,961，复算Q4为689百万元"),
    },
}

TOWER_2017_2018_OFFICIAL_VERIFICATIONS = [
    _official_record(
        "中国铁塔",
        period,
        metric_key,
        official_value,
        unit,
        TOWER_2017_2018_PERIOD_SOURCE[period]["label"],
        TOWER_2017_2018_PERIOD_SOURCE[period]["url"],
        f"{TOWER_2017_2018_PERIOD_SOURCE[period]['evidence_prefix']}：{evidence}",
        TOWER_2017_2018_PERIOD_SOURCE[period]["method"],
        TOWER_2017_2018_PERIOD_SOURCE[period]["sources"],
    )
    for period, metrics in TOWER_2017_2018_PERIOD_METRICS.items()
    for metric_key, (official_value, unit, evidence) in metrics.items()
]

TOWER_2016_DISCLOSURE_GAP_SOURCES = [
    {"label": "中国铁塔2018全球发售招股书", "url": TOWER_2018_PROSPECTUS_URL, "evidence": "招股书披露2016全年核心财务指标，但未披露2016 Q1/H1/9M同口径季度基数。"},
    {"label": "中国铁塔2018中期报告", "url": TOWER_2018_H1_REPORT_URL, "evidence": "中期报告只披露2018/2017 H1比较值，不提供2016半年度或季度拆分。"},
    {"label": "中国铁塔2018年报", "url": TOWER_2018_ANNUAL_REPORT_URL, "evidence": "年报披露2018/2017全年比较值，未提供2016季度或半年度公开拆分。"},
]

TOWER_2016_DISCLOSURE_GAP_CONFIRMATIONS = [
    {
        "subject": "中国铁塔",
        "period": period,
        "metric_key": "quarterly_financial_disclosure_status",
        "source_label": "中国铁塔2016季度财务披露边界",
        "source_url": TOWER_2018_PROSPECTUS_URL,
        "evidence": (
            f"{period} 所需的2016 Q1/H1/9M同口径财务基数未在已核验公开文件中披露；"
            "招股书只披露2016全年核心财务指标，无法在不估算的情况下拆分单季。"
        ),
        "verification_method": "official_pre_listing_disclosure_gap_check",
        "verification_sources": TOWER_2016_DISCLOSURE_GAP_SOURCES,
        "verification_note": "保留中国铁塔上市前2016季度披露缺口；不得用全年平均、同比倒推或标准化在线表估算单季值。",
        "append_if_missing": True,
    }
    for period in ["Q2 2016", "Q3 2016", "Q4 2016"]
]


TOWER_2021_PERIOD_SOURCE = {
    "Q1 2021": {
        "label": "中国铁塔2021年第一季度未经审核主要运营数据",
        "url": TOWER_2021_Q1_URL,
        "method": "official_quarterly_statement_check",
        "sources": TOWER_2021_Q1_SOURCES,
        "evidence_prefix": "2021年第一季度未经审核主要运营数据直接披露Q1核心经营数据",
    },
    "Q2 2021": {
        "label": "中国铁塔2021中期报告",
        "url": TOWER_2021_H1_URL,
        "method": "official_h1_minus_q1_reconciliation",
        "sources": TOWER_2021_Q2_SOURCES,
        "evidence_prefix": "2021中期报告披露上半年累计值，减2021Q1官方值复算Q2",
    },
    "Q3 2021": {
        "label": "中国铁塔2021年前三季度未经审核主要运营数据",
        "url": TOWER_2021_Q3_URL,
        "method": "official_9m_minus_h1_reconciliation",
        "sources": TOWER_2021_Q3_SOURCES,
        "evidence_prefix": "2021年前三季度未经审核主要运营数据披露9M累计值，减2021H1官方值复算Q3",
    },
    "Q4 2021": {
        "label": "中国铁塔2021年度报告",
        "url": TOWER_2021_ANNUAL_REPORT_URL,
        "method": "official_annual_minus_9m_reconciliation",
        "sources": TOWER_2021_Q4_SOURCES,
        "evidence_prefix": "2021年度报告披露全年值，减2021年前三季度官方值复算Q4",
    },
}

TOWER_2021_PERIOD_METRICS = {
    "Q1 2021": {
        "revenue": (21151, "millions CNY", "Q1公告披露营业收入21,151百万元"),
        "ebitda": (15553, "millions CNY", "Q1公告披露EBITDA 15,553百万元"),
        "net_income": (1694, "millions CNY", "Q1公告披露归母利润1,694百万元"),
    },
    "Q2 2021": {
        "revenue": (21522, "millions CNY", "上半年营业收入42,673减Q1 21,151，复算Q2为21,522百万元"),
        "revenue_growth_yoy": (7.06, "percent", "Q2收入21,522百万元，相对2020Q2可比基数复算同比约7.06%；与StockAnalysis同比口径一致。"),
        "ebitda": (15631, "millions CNY", "上半年EBITDA 31,184减Q1 15,553，复算Q2为15,631百万元"),
        "net_income": (1763, "millions CNY", "上半年归母利润3,457减Q1 1,694，复算Q2为1,763百万元"),
    },
    "Q3 2021": {
        "revenue": (21915, "millions CNY", "前三季度营业收入64,588减H1 42,673，复算Q3为21,915百万元"),
        "revenue_growth_yoy": (7.29, "percent", "Q3收入21,915百万元，相对2020Q3可比基数复算同比约7.29%；与StockAnalysis同比口径一致。"),
        "ebitda": (16105, "millions CNY", "前三季度EBITDA 47,289减H1 31,184，复算Q3为16,105百万元"),
        "net_income": (1799, "millions CNY", "前三季度归母利润5,256减H1 3,457，复算Q3为1,799百万元"),
    },
    "Q4 2021": {
        "revenue": (21997, "millions CNY", "全年营业收入86,585减9M 64,588，复算Q4为21,997百万元"),
        "revenue_growth_yoy": (5.35, "percent", "Q4收入21,997百万元，相对2020Q4可比基数复算同比约5.35%；与StockAnalysis同比口径一致。"),
        "ebitda": (15728, "millions CNY", "全年EBITDA 63,017减9M 47,289，复算Q4为15,728百万元"),
        "net_income": (2073, "millions CNY", "全年归母利润7,329减9M 5,256，复算Q4为2,073百万元"),
    },
}

TOWER_2021_OFFICIAL_VERIFICATIONS = [
    _official_record(
        "中国铁塔",
        period,
        metric_key,
        official_value,
        unit,
        TOWER_2021_PERIOD_SOURCE[period]["label"],
        TOWER_2021_PERIOD_SOURCE[period]["url"],
        f"{TOWER_2021_PERIOD_SOURCE[period]['evidence_prefix']}：{evidence}",
        TOWER_2021_PERIOD_SOURCE[period]["method"],
        TOWER_2021_PERIOD_SOURCE[period]["sources"],
    )
    for period, metrics in TOWER_2021_PERIOD_METRICS.items()
    for metric_key, (official_value, unit, evidence) in metrics.items()
]


TOWER_2021_2022_DETAIL_PERIOD_SOURCE = {
    "Q1 2022": TOWER_2022_PERIOD_SOURCE["Q1 2022"],
    "Q2 2022": TOWER_2022_PERIOD_SOURCE["Q2 2022"],
    "Q3 2022": TOWER_2022_PERIOD_SOURCE["Q3 2022"],
    "Q4 2022": TOWER_2022_PERIOD_SOURCE["Q4 2022"],
    "Q2 2021": TOWER_2021_PERIOD_SOURCE["Q2 2021"],
    "Q3 2021": TOWER_2021_PERIOD_SOURCE["Q3 2021"],
    "Q4 2021": TOWER_2021_PERIOD_SOURCE["Q4 2021"],
}

TOWER_2021_2022_DETAIL_METRICS = {
    "Q1 2022": {
        "ebitda_margin": (69.3, "percent", "2022Q1公告披露EBITDA 15,682百万元、EBITDA率69.3%。"),
    },
    "Q2 2022": {
        "ebitda_margin": (71.242, "percent", "2022H1 EBITDA 31,958减Q1 15,682得Q2 EBITDA 16,276；除以Q2营业收入22,846，复算EBITDA率71.242%。"),
        "cash_and_equivalents": (6908, "millions CNY", "2022中期报告合并资产负债表披露2022年6月30日现金及现金等价物6,908百万元。"),
        "total_assets": (313523, "millions CNY", "2022中期报告披露2022年6月30日总资产313,523百万元。"),
        "total_debt": (92428, "millions CNY", "2022中期报告披露2022年6月30日有息负债92,428百万元。"),
    },
    "Q3 2022": {
        "ebitda_margin": (66.810, "percent", "2022前三季度EBITDA 47,460减H1 31,958得Q3 EBITDA 15,502；除以Q3营业收入23,203，复算EBITDA率66.810%。"),
    },
    "Q4 2022": {
        "ebitda_margin": (65.497, "percent", "2022全年EBITDA 62,844减9M 47,460得Q4 EBITDA 15,384；除以Q4营业收入23,488，复算EBITDA率65.497%。"),
        "cash_and_equivalents": (5117, "millions CNY", "2022年度报告合并资产负债表披露2022年12月31日现金及现金等价物5,117百万元。"),
        "total_assets": (305560, "millions CNY", "2022年度报告披露2022年12月31日总资产305,560百万元。"),
        "total_debt": (79119, "millions CNY", "2022年度报告披露2022年12月31日有息负债79,119百万元。"),
    },
    "Q2 2021": {
        "ebitda_margin": (72.628, "percent", "2021H1 EBITDA 31,184减Q1 15,553得Q2 EBITDA 15,631；除以Q2营业收入21,522，复算EBITDA率72.628%。"),
        "cash_and_equivalents": (4958, "millions CNY", "2021中期报告合并资产负债表披露2021年6月30日现金及现金等价物4,958百万元。"),
        "total_assets": (333195, "millions CNY", "2021中期报告披露2021年6月30日总资产333,195百万元。"),
        "total_debt": (114191, "millions CNY", "2021中期报告披露2021年6月30日有息负债114,191百万元。"),
    },
    "Q3 2021": {
        "ebitda_margin": (73.488, "percent", "2021前三季度EBITDA 47,289减H1 31,184得Q3 EBITDA 16,105；除以Q3营业收入21,915，复算EBITDA率73.488%。"),
    },
    "Q4 2021": {
        "ebitda_margin": (71.501, "percent", "2021全年EBITDA 63,017减9M 47,289得Q4 EBITDA 15,728；除以Q4营业收入21,997，复算EBITDA率71.501%。"),
        "cash_and_equivalents": (6471, "millions CNY", "2021年度报告合并资产负债表披露2021年12月31日现金及现金等价物6,471百万元。"),
        "total_assets": (323259, "millions CNY", "2021年度报告披露2021年12月31日总资产323,259百万元。"),
        "total_debt": (101304, "millions CNY", "2021年度报告披露2021年12月31日有息负债101,304百万元。"),
    },
}

TOWER_2021_2022_DETAIL_OFFICIAL_VERIFICATIONS = [
    _official_record(
        "中国铁塔",
        period,
        metric_key,
        official_value,
        unit,
        TOWER_2021_2022_DETAIL_PERIOD_SOURCE[period]["label"],
        TOWER_2021_2022_DETAIL_PERIOD_SOURCE[period]["url"],
        f"{TOWER_2021_2022_DETAIL_PERIOD_SOURCE[period]['evidence_prefix']}：{evidence}",
        TOWER_2021_2022_DETAIL_PERIOD_SOURCE[period]["method"],
        TOWER_2021_2022_DETAIL_PERIOD_SOURCE[period]["sources"],
    )
    for period, metrics in TOWER_2021_2022_DETAIL_METRICS.items()
    for metric_key, (official_value, unit, evidence) in metrics.items()
]

TOWER_2021_2022_SOURCE_GAP_PERIOD_SOURCES = {
    "Q1 2022": {
        "label": TOWER_2022_PERIOD_SOURCE["Q1 2022"]["label"],
        "url": TOWER_2022_PERIOD_SOURCE["Q1 2022"]["url"],
        "sources": TOWER_2022_PERIOD_SOURCE["Q1 2022"]["sources"],
    },
    "Q2 2022": {
        "label": TOWER_2022_PERIOD_SOURCE["Q2 2022"]["label"],
        "url": TOWER_2022_PERIOD_SOURCE["Q2 2022"]["url"],
        "sources": TOWER_2022_PERIOD_SOURCE["Q2 2022"]["sources"],
    },
    "Q3 2022": {
        "label": TOWER_2022_PERIOD_SOURCE["Q3 2022"]["label"],
        "url": TOWER_2022_PERIOD_SOURCE["Q3 2022"]["url"],
        "sources": TOWER_2022_PERIOD_SOURCE["Q3 2022"]["sources"],
    },
    "Q4 2022": {
        "label": TOWER_2022_PERIOD_SOURCE["Q4 2022"]["label"],
        "url": TOWER_2022_PERIOD_SOURCE["Q4 2022"]["url"],
        "sources": TOWER_2022_PERIOD_SOURCE["Q4 2022"]["sources"],
    },
    "Q2 2021": {
        "label": TOWER_2021_PERIOD_SOURCE["Q2 2021"]["label"],
        "url": TOWER_2021_PERIOD_SOURCE["Q2 2021"]["url"],
        "sources": TOWER_2021_PERIOD_SOURCE["Q2 2021"]["sources"],
    },
    "Q3 2021": {
        "label": TOWER_2021_PERIOD_SOURCE["Q3 2021"]["label"],
        "url": TOWER_2021_PERIOD_SOURCE["Q3 2021"]["url"],
        "sources": TOWER_2021_PERIOD_SOURCE["Q3 2021"]["sources"],
    },
    "Q4 2021": {
        "label": TOWER_2021_PERIOD_SOURCE["Q4 2021"]["label"],
        "url": TOWER_2021_PERIOD_SOURCE["Q4 2021"]["url"],
        "sources": TOWER_2021_PERIOD_SOURCE["Q4 2021"]["sources"],
    },
}

TOWER_2021_2022_SOURCE_GAP_METRICS_BY_PERIOD = {
    "Q1 2022": ["capital_expenditures", "cash_and_equivalents", "free_cash_flow", "gross_margin", "gross_profit", "operating_cash_flow", "operating_income", "operating_margin", "total_assets", "total_debt"],
    "Q2 2022": ["capital_expenditures", "free_cash_flow", "gross_margin", "gross_profit", "operating_cash_flow", "operating_income", "operating_margin"],
    "Q3 2022": ["capital_expenditures", "cash_and_equivalents", "free_cash_flow", "gross_margin", "gross_profit", "operating_cash_flow", "operating_income", "operating_margin", "total_assets", "total_debt"],
    "Q4 2022": ["capital_expenditures", "free_cash_flow", "gross_margin", "gross_profit", "operating_cash_flow", "operating_income", "operating_margin"],
    "Q2 2021": ["capital_expenditures", "free_cash_flow", "gross_margin", "gross_profit", "operating_cash_flow", "operating_income", "operating_margin"],
    "Q3 2021": ["capital_expenditures", "cash_and_equivalents", "free_cash_flow", "gross_margin", "gross_profit", "operating_cash_flow", "operating_income", "operating_margin", "total_assets", "total_debt"],
    "Q4 2021": ["capital_expenditures", "free_cash_flow", "gross_margin", "gross_profit", "operating_cash_flow", "operating_income", "operating_margin"],
}

TOWER_2021_2022_SOURCE_GAP_CONFIRMATIONS = [
    {
        "subject": "中国铁塔",
        "period": period,
        "metric_key": metric_key,
        "source_label": TOWER_2021_2022_SOURCE_GAP_PERIOD_SOURCES[period]["label"],
        "source_url": TOWER_2021_2022_SOURCE_GAP_PERIOD_SOURCES[period]["url"],
        "evidence": (
            f"{period} 中国铁塔官方季度/半年度/年度披露已核验；该期间未披露可用于逐季核验 "
            f"{METRIC_ZH_BY_KEY.get(metric_key, metric_key)} 的同口径官方数值，或仅披露累计值而无法在不估算的情况下拆为单季。"
            "保留披露缺口，禁止采用标准化在线表估算值作为正式事实。"
        ),
        "verification_method": "official_disclosure_gap_check",
        "verification_sources": TOWER_2021_2022_SOURCE_GAP_PERIOD_SOURCES[period]["sources"],
        "verification_note": "中国铁塔该期间官方公开文件未披露同口径单季字段或仅披露累计值；正式回答只能说明披露缺口，不得引用标准化表估算值。",
    }
    for period, metrics in TOWER_2021_2022_SOURCE_GAP_METRICS_BY_PERIOD.items()
    for metric_key in metrics
]


TOWER_2023_OFFICIAL_VERIFICATIONS = [
    _official_record(
        "中国铁塔",
        period,
        metric_key,
        official_value,
        unit,
        TOWER_2023_PERIOD_SOURCE[period]["label"],
        TOWER_2023_PERIOD_SOURCE[period]["url"],
        f"{TOWER_2023_PERIOD_SOURCE[period]['evidence_prefix']}：{evidence}",
        TOWER_2023_PERIOD_SOURCE[period]["method"],
        TOWER_2023_PERIOD_SOURCE[period]["sources"],
    )
    for period, metrics in TOWER_2023_PERIOD_METRICS.items()
    for metric_key, (official_value, unit, evidence) in metrics.items()
]


TOWER_2024_PERIOD_SOURCE = {
    "Q1 2024": {
        "label": "中国铁塔2024年第一季度未经审核主要运营数据",
        "url": TOWER_2024_Q1_URL,
        "method": "official_source_row_check",
        "sources": TOWER_2024_Q1_SOURCES,
        "evidence_prefix": "2024年第一季度未经审核主要运营数据披露",
    },
    "Q2 2024": {
        "label": "中国铁塔2024中期业绩公告",
        "url": TOWER_2024_H1_URL,
        "method": "official_h1_minus_q1_reconciliation",
        "sources": TOWER_2024_Q2_SOURCES,
        "evidence_prefix": "2024中期业绩公告披露上半年累计值，减2024Q1官方值复算Q2",
    },
    "Q3 2024": {
        "label": "中国铁塔2024年前三季度未经审核主要运营数据",
        "url": TOWER_2024_Q3_URL,
        "method": "official_9m_minus_h1_reconciliation",
        "sources": TOWER_2024_Q3_SOURCES,
        "evidence_prefix": "2024年前三季度未经审核主要运营数据披露9M累计值，减2024H1官方值复算Q3",
    },
    "Q4 2024": {
        "label": "中国铁塔2024年度业绩公告",
        "url": TOWER_2024_ANNUAL_RESULTS_URL,
        "method": "official_annual_minus_9m_reconciliation",
        "sources": TOWER_2024_Q4_SOURCES,
        "evidence_prefix": "2024年度业绩公告披露全年值，减2024年前三季度官方值复算Q4",
    },
}


TOWER_2024_PERIOD_METRICS = {
    "Q1 2024": {
        "revenue": (23974, "millions CNY", "营业收入23,974百万元"),
        "revenue_growth_yoy": (3.3, "percent", "营业收入同比增长3.3%"),
        "operator_business_revenue": (20984, "millions CNY", "运营商业务收入20,984百万元"),
        "tower_business_revenue": (18946, "millions CNY", "塔类业务收入18,946百万元"),
        "das_business_revenue": (2038, "millions CNY", "室分业务收入2,038百万元"),
        "smart_business_revenue": (1974, "millions CNY", "智联业务收入1,974百万元"),
        "energy_business_revenue": (957, "millions CNY", "能源业务收入957百万元"),
        "ebitda": (16597, "millions CNY", "EBITDA 16,597百万元"),
        "ebitda_margin": (69.2, "percent", "EBITDA率69.2%"),
        "net_income": (2784, "millions CNY", "归属于本公司股东的利润2,784百万元"),
        "total_assets": (321368, "millions CNY", "2024年3月31日总资产321,368百万元"),
    },
    "Q2 2024": {
        "revenue": (24273, "millions CNY", "上半年营业收入48,247减Q1 23,974，复算Q2为24,273百万元"),
        "revenue_growth_yoy": (4.34, "percent", "Q2收入24,273百万元，相对2023Q2 23,262百万元复算同比约4.34%"),
        "operator_business_revenue": (21137, "millions CNY", "上半年Tower+DAS业务42,121减Q1 20,984，复算Q2为21,137百万元"),
        "tower_business_revenue": (19011, "millions CNY", "上半年Tower business 37,957减Q1 18,946，复算Q2为19,011百万元"),
        "das_business_revenue": (2126, "millions CNY", "上半年DAS business 4,164减Q1 2,038，复算Q2为2,126百万元"),
        "smart_business_revenue": (2008, "millions CNY", "上半年Smart Tower business 3,982减Q1 1,974，复算Q2为2,008百万元"),
        "energy_business_revenue": (1066, "millions CNY", "上半年Energy business 2,023减Q1 957，复算Q2为1,066百万元"),
        "ebitda": (16448, "millions CNY", "上半年EBITDA 33,045减Q1 16,597，复算Q2为16,448百万元"),
        "ebitda_margin": (67.77, "percent", "Q2 EBITDA 16,448除以Q2营业收入24,273，复算EBITDA率约67.77%"),
        "net_income": (2546, "millions CNY", "上半年归母利润5,330减Q1 2,784，复算Q2为2,546百万元"),
        "cash_and_equivalents": (4049, "millions CNY", "2024年6月30日现金及现金等价物4,049百万元"),
        "total_assets": (316747, "millions CNY", "2024年6月30日总资产316,747百万元"),
        "total_debt": (85985, "millions CNY", "2024年6月30日借款40,892+24,601及租赁负债13,663+6,829，合计85,985百万元"),
    },
    "Q3 2024": {
        "revenue": (24205, "millions CNY", "前三季度营业收入72,452减H1 48,247，复算Q3为24,205百万元"),
        "revenue_growth_yoy": (2.18, "percent", "Q3收入24,205百万元，相对2023Q3约23,689百万元复算同比约2.18%"),
        "operator_business_revenue": (21003, "millions CNY", "前三季度运营商业务63,124减H1 42,121，复算Q3为21,003百万元"),
        "tower_business_revenue": (18945, "millions CNY", "前三季度塔类业务56,902减H1 37,957，复算Q3为18,945百万元"),
        "das_business_revenue": (2058, "millions CNY", "前三季度室分业务6,222减H1 4,164，复算Q3为2,058百万元"),
        "smart_business_revenue": (2091, "millions CNY", "前三季度智联业务6,073减H1 3,982，复算Q3为2,091百万元"),
        "energy_business_revenue": (1048, "millions CNY", "前三季度能源业务3,071减H1 2,023，复算Q3为1,048百万元"),
        "ebitda": (16672, "millions CNY", "前三季度EBITDA 49,717减H1 33,045，复算Q3为16,672百万元"),
        "ebitda_margin": (68.88, "percent", "Q3 EBITDA 16,672除以Q3营业收入24,205，复算EBITDA率约68.88%"),
        "net_income": (2823, "millions CNY", "前三季度归母利润8,153减H1 5,330，复算Q3为2,823百万元"),
        "total_assets": (324491, "millions CNY", "2024年9月30日总资产324,491百万元"),
    },
    "Q4 2024": {
        "revenue": (25320, "millions CNY", "全年营业收入97,772减9M 72,452，复算Q4为25,320百万元"),
        "revenue_growth_yoy": (6.13, "percent", "Q4收入25,320百万元，相对2023Q4约23,858百万元复算同比约6.13%"),
        "operator_business_revenue": (20995, "millions CNY", "全年Tower+DAS业务84,119减9M 63,124，复算Q4为20,995百万元"),
        "tower_business_revenue": (18787, "millions CNY", "全年Tower business 75,689减9M 56,902，复算Q4为18,787百万元"),
        "das_business_revenue": (2208, "millions CNY", "全年DAS business 8,430减9M 6,222，复算Q4为2,208百万元"),
        "smart_business_revenue": (2838, "millions CNY", "全年Smart Tower business 8,911减9M 6,073，复算Q4为2,838百万元"),
        "energy_business_revenue": (1406, "millions CNY", "全年Energy business 4,477减9M 3,071，复算Q4为1,406百万元"),
        "ebitda": (16842, "millions CNY", "全年EBITDA 66,559减9M 49,717，复算Q4为16,842百万元"),
        "ebitda_margin": (66.52, "percent", "Q4 EBITDA 16,842除以Q4营业收入25,320，复算EBITDA率约66.52%"),
        "net_income": (2576, "millions CNY", "全年归母利润10,729减9M 8,153，复算Q4为2,576百万元"),
        "cash_and_equivalents": (2598, "millions CNY", "2024年12月31日现金及现金等价物2,598百万元"),
        "total_assets": (332834, "millions CNY", "2024年12月31日总资产332,834百万元"),
        "total_debt": (92542, "millions CNY", "2024年12月31日借款41,084+28,525及租赁负债15,555+7,378，合计92,542百万元"),
    },
}


TOWER_2024_OFFICIAL_VERIFICATIONS = [
    _official_record(
        "中国铁塔",
        period,
        metric_key,
        official_value,
        unit,
        TOWER_2024_PERIOD_SOURCE[period]["label"],
        TOWER_2024_PERIOD_SOURCE[period]["url"],
        f"{TOWER_2024_PERIOD_SOURCE[period]['evidence_prefix']}：{evidence}",
        TOWER_2024_PERIOD_SOURCE[period]["method"],
        TOWER_2024_PERIOD_SOURCE[period]["sources"],
    )
    for period, metrics in TOWER_2024_PERIOD_METRICS.items()
    for metric_key, (official_value, unit, evidence) in metrics.items()
]

TOWER_SOURCE_GAP_PERIOD_SOURCES = {
    "Q1 2023": {
        "label": "中国铁塔2023年第一季度未经审核主要运营数据",
        "url": TOWER_2023_Q1_URL,
        "sources": TOWER_2023_Q1_SOURCES,
    },
    "Q2 2023": {
        "label": "中国铁塔2023中期业绩公告",
        "url": TOWER_2023_H1_URL,
        "sources": TOWER_2023_Q2_SOURCES,
    },
    "Q3 2023": {
        "label": "中国铁塔2023年前三季度未经审核主要运营数据",
        "url": TOWER_2023_Q3_URL,
        "sources": TOWER_2023_Q3_SOURCES,
    },
    "Q4 2023": {
        "label": "中国铁塔2023年度业绩公告",
        "url": TOWER_2023_ANNUAL_RESULTS_URL,
        "sources": TOWER_2023_Q4_SOURCES,
    },
    "Q1 2024": {
        "label": "中国铁塔2024年第一季度未经审核主要运营数据",
        "url": TOWER_2024_Q1_URL,
        "sources": TOWER_2024_Q1_SOURCES,
    },
    "Q2 2024": {
        "label": "中国铁塔2024中期业绩公告",
        "url": TOWER_2024_H1_URL,
        "sources": TOWER_2024_Q2_SOURCES,
    },
    "Q3 2024": {
        "label": "中国铁塔2024年前三季度未经审核主要运营数据",
        "url": TOWER_2024_Q3_URL,
        "sources": TOWER_2024_Q3_SOURCES,
    },
    "Q4 2024": {
        "label": "中国铁塔2024年度业绩公告",
        "url": TOWER_2024_ANNUAL_RESULTS_URL,
        "sources": TOWER_2024_Q4_SOURCES,
    },
    "Q1 2025": {
        "label": "中国铁塔2025年第一季度未经审核主要运营数据",
        "url": TOWER_2025_Q1_URL,
        "sources": TOWER_2025_Q2_SOURCES[:1],
    },
    "Q2 2025": {
        "label": "中国铁塔2025中期业绩公告",
        "url": TOWER_2025_H1_URL,
        "sources": TOWER_2025_Q2_SOURCES,
    },
    "Q3 2025": {
        "label": "中国铁塔2025年前三季度未经审核主要运营数据",
        "url": TOWER_2025_Q3_URL,
        "sources": TOWER_2025_Q3_SOURCES,
    },
    "Q4 2025": {
        "label": "中国铁塔2025年度业绩公告",
        "url": TOWER_2025_ANNUAL_RESULTS_URL,
        "sources": TOWER_2025_Q4_SOURCES,
    },
    "Q1 2026": {
        "label": "中国铁塔2026年第一季度未经审核主要运营数据",
        "url": TOWER_2026_Q1_URL,
        "sources": TOWER_2026_Q1_SOURCES,
    },
}

TOWER_SOURCE_GAP_METRICS_BY_PERIOD = {
    "Q1 2023": ["capital_expenditures", "cash_and_equivalents", "free_cash_flow", "gross_margin", "gross_profit", "operating_cash_flow", "operating_income", "operating_margin", "total_debt"],
    "Q2 2023": ["capital_expenditures", "free_cash_flow", "gross_margin", "gross_profit", "operating_cash_flow", "operating_income", "operating_margin"],
    "Q3 2023": ["capital_expenditures", "cash_and_equivalents", "free_cash_flow", "gross_margin", "gross_profit", "operating_cash_flow", "operating_income", "operating_margin", "total_debt"],
    "Q4 2023": ["capital_expenditures", "free_cash_flow", "gross_margin", "gross_profit", "operating_cash_flow", "operating_income", "operating_margin"],
    "Q1 2024": ["capital_expenditures", "cash_and_equivalents", "free_cash_flow", "gross_margin", "gross_profit", "operating_cash_flow", "operating_income", "operating_margin", "total_debt"],
    "Q2 2024": ["capital_expenditures", "free_cash_flow", "gross_margin", "gross_profit", "operating_cash_flow", "operating_income", "operating_margin"],
    "Q3 2024": ["capital_expenditures", "cash_and_equivalents", "free_cash_flow", "gross_margin", "gross_profit", "operating_cash_flow", "operating_income", "operating_margin", "total_debt"],
    "Q4 2024": ["capital_expenditures", "free_cash_flow", "gross_margin", "gross_profit", "operating_cash_flow", "operating_income", "operating_margin"],
    "Q1 2025": ["capital_expenditures", "cash_and_equivalents", "free_cash_flow", "gross_margin", "gross_profit", "operating_cash_flow", "operating_income", "operating_margin", "total_debt"],
    "Q2 2025": ["capital_expenditures", "free_cash_flow", "gross_margin", "gross_profit", "operating_cash_flow", "operating_income", "operating_margin"],
    "Q3 2025": ["capital_expenditures", "cash_and_equivalents", "free_cash_flow", "gross_margin", "gross_profit", "operating_cash_flow", "operating_income", "operating_margin", "total_debt"],
    "Q4 2025": ["capital_expenditures", "free_cash_flow", "gross_margin", "gross_profit", "operating_cash_flow", "operating_income", "operating_margin"],
    "Q1 2026": ["capital_expenditures", "cash_and_equivalents", "free_cash_flow", "gross_margin", "gross_profit", "operating_cash_flow", "operating_income", "operating_margin", "total_debt"],
}

TOWER_SOURCE_GAP_CONFIRMATIONS = [
    {
        "subject": "中国铁塔",
        "period": period,
        "metric_key": metric_key,
        "source_label": TOWER_SOURCE_GAP_PERIOD_SOURCES[period]["label"],
        "source_url": TOWER_SOURCE_GAP_PERIOD_SOURCES[period]["url"],
        "evidence": (
            f"{period} 官方公告及相邻累计业绩公告已核验；中国铁塔该期间未披露可用于"
            f"逐季核验 {METRIC_ZH_BY_KEY.get(metric_key, metric_key)} 的同口径官方数值。"
            "保留披露缺口，禁止采用标准化在线表估算值作为正式事实。"
        ),
        "verification_method": "official_disclosure_gap_check",
        "verification_sources": TOWER_SOURCE_GAP_PERIOD_SOURCES[period]["sources"],
        "verification_note": "官方季度/累计公告未披露该单季同口径指标；正式回答只能说明披露缺口，不得引用标准化表数值。",
    }
    for period, metric_keys in TOWER_SOURCE_GAP_METRICS_BY_PERIOD.items()
    for metric_key in metric_keys
]

CU_SOURCE_GAP_PERIOD_SOURCES = {
    "Q1 2025": {
        "label": "中国联通2025年第一季度报告（上交所，600050 A股口径）",
        "url": CU_2025_Q1_SSE_URL,
        "sources": CU_2025_Q1_SOURCES,
    },
    "Q2 2025": {
        "label": "中国联通2025中期报告及600050半年度报告",
        "url": CU_2025_H1_SINA_URL,
        "sources": CU_2025_Q2_DETAIL_SOURCES,
    },
    "Q3 2025": {
        "label": "中国联通2025年第三季度报告（600050 A股口径）",
        "url": CU_2025_Q3_SINA_URL,
        "sources": CU_2025_Q3_DETAIL_SOURCES,
    },
    "Q4 2025": {
        "label": "中国联通2025年度报告及三季度报告（600050 A股口径）",
        "url": CU_2025_ANNUAL_SINA_URL,
        "sources": CU_2025_Q4_DETAIL_SOURCES,
    },
    "Q1 2026": {
        "label": "中国联通2026年第一季度报告（上交所，600050 A股口径）",
        "url": CU_2026_Q1_SSE_URL,
        "sources": CU_2026_Q1_SOURCES,
    },
}

CU_SOURCE_GAP_METRICS_BY_PERIOD = {
    "Q1 2025": ["ebitda", "ebitda_margin"],
    "Q2 2025": ["ebitda", "ebitda_margin"],
    "Q3 2025": ["ebitda", "ebitda_margin"],
    "Q4 2025": ["ebitda", "ebitda_margin"],
    "Q1 2026": ["ebitda", "ebitda_margin"],
}

CU_SOURCE_GAP_CONFIRMATIONS = [
    {
        "subject": "中国联通",
        "period": period,
        "metric_key": metric_key,
        "source_label": CU_SOURCE_GAP_PERIOD_SOURCES[period]["label"],
        "source_url": CU_SOURCE_GAP_PERIOD_SOURCES[period]["url"],
        "evidence": (
            f"{period} 中国联通官方一季报、半年度/三季度/年度累计披露及港股业绩文件已核验；"
            f"该期间未披露可用于逐季核验 {METRIC_ZH_BY_KEY.get(metric_key, metric_key)} 的同口径官方数值。"
            "保留披露缺口，禁止采用标准化在线表估算值作为正式事实。"
        ),
        "verification_method": "official_disclosure_gap_check",
        "verification_sources": CU_SOURCE_GAP_PERIOD_SOURCES[period]["sources"],
        "verification_note": "中国联通官方季度/累计公告未披露该单季同口径指标；正式回答只能说明披露缺口，不得引用标准化表数值。",
    }
    for period, metric_keys in CU_SOURCE_GAP_METRICS_BY_PERIOD.items()
    for metric_key in metric_keys
]

TOWER_EXTRA_OFFICIAL_VERIFICATIONS = [
    _official_record(
        "中国铁塔",
        "Q2 2025",
        "cash_and_equivalents",
        8673,
        "millions CNY",
        "中国铁塔2025中期业绩公告",
        TOWER_2025_H1_URL,
        "2025中期业绩公告资产负债表披露2025年6月30日Cash and cash equivalents 8,673百万元。",
        "official_balance_sheet_row_check",
        TOWER_2025_Q2_SOURCES,
    ),
    _official_record(
        "中国铁塔",
        "Q2 2025",
        "total_debt",
        92639,
        "millions CNY",
        "中国铁塔2025中期业绩公告",
        TOWER_2025_H1_URL,
        "2025中期业绩公告披露2025年6月30日interest-bearing liabilities 92,639百万元；资产负债表亦可由借款24,882+44,212及租赁负债16,614+6,931复算。",
        "official_interest_bearing_liabilities_check",
        TOWER_2025_Q2_SOURCES,
    ),
    _official_record(
        "中国铁塔",
        "Q2 2025",
        "revenue_growth_yoy",
        2.30,
        "percent",
        "中国铁塔2025中期业绩公告",
        TOWER_2025_H1_URL,
        "2025H1营业收入49,601减2025Q1 24,771得Q2 24,830；2024H1 48,247减2024Q1 23,974得Q2 24,273，复算同比约2.30%。",
        "official_current_prior_period_recalculation",
        [*TOWER_2025_Q2_SOURCES, *TOWER_2024_Q2_SOURCES],
    ),
    _official_record(
        "中国铁塔",
        "Q3 2025",
        "revenue_growth_yoy",
        2.12,
        "percent",
        "中国铁塔2025年前三季度未经审核主要运营数据",
        TOWER_2025_Q3_URL,
        "2025年前三季度营业收入74,319减H1 49,601得Q3 24,718；2024年前三季度72,452减H1 48,247得Q3 24,205，复算同比约2.12%。",
        "official_current_prior_period_recalculation",
        [*TOWER_2025_Q3_SOURCES, *TOWER_2024_Q3_SOURCES],
    ),
    _official_record(
        "中国铁塔",
        "Q4 2025",
        "cash_and_equivalents",
        12312,
        "millions CNY",
        "中国铁塔2025年度业绩公告",
        TOWER_2025_ANNUAL_RESULTS_URL,
        "2025年度业绩公告资产负债表披露2025年12月31日Cash and cash equivalents 12,312百万元。",
        "official_balance_sheet_row_check",
        TOWER_2025_Q4_SOURCES,
    ),
    _official_record(
        "中国铁塔",
        "Q4 2025",
        "revenue_growth_yoy",
        3.05,
        "percent",
        "中国铁塔2025年度业绩公告",
        TOWER_2025_ANNUAL_RESULTS_URL,
        "2025全年营业收入100,411减前三季度74,319得Q4 26,092；2024全年97,772减前三季度72,452得Q4 25,320，复算同比约3.05%。",
        "official_current_prior_period_recalculation",
        [*TOWER_2025_Q4_SOURCES, *TOWER_2024_Q4_SOURCES],
    ),
    _official_record(
        "中国铁塔",
        "Q1 2026",
        "total_assets",
        343610,
        "millions CNY",
        "中国铁塔2026年第一季度未经审核主要运营数据",
        TOWER_2026_Q1_URL,
        "2026Q1未经审核主要运营数据表披露2026年3月31日Total Assets 343,610百万元。",
        "official_balance_sheet_row_check",
        TOWER_2026_Q1_SOURCES,
    ),
]


AWS_VERIFICATION_METHOD_BY_PERIOD = {
    "Q4 2016": "official_annual_minus_q1_q3_segment_reconciliation",
    "Q4 2017": "official_annual_minus_q1_q3_segment_reconciliation",
    "Q4 2018": "official_annual_minus_q1_q3_segment_reconciliation",
    "Q4 2019": "official_annual_minus_q1_q3_segment_reconciliation",
    "Q4 2020": "official_annual_minus_q1_q3_segment_reconciliation",
    "Q4 2021": "official_annual_minus_q1_q3_segment_reconciliation",
    "Q1 2022": "official_annual_minus_q2_q4_segment_reconciliation",
    "Q4 2025": "official_annual_minus_q1_q3_segment_reconciliation",
}

AWS_VERIFICATION_SOURCES_BY_PERIOD = {
    "Q4 2016": [
        AWS_2025_SOURCE_BY_PERIOD["Q1 2016"],
        AWS_2025_SOURCE_BY_PERIOD["Q2 2016"],
        AWS_2025_SOURCE_BY_PERIOD["Q3 2016"],
        AWS_2025_SOURCE_BY_PERIOD["Q4 2016"],
    ],
    "Q4 2017": [
        AWS_2025_SOURCE_BY_PERIOD["Q1 2017"],
        AWS_2025_SOURCE_BY_PERIOD["Q2 2017"],
        AWS_2025_SOURCE_BY_PERIOD["Q3 2017"],
        AWS_2025_SOURCE_BY_PERIOD["Q4 2017"],
    ],
    "Q4 2018": [
        AWS_2025_SOURCE_BY_PERIOD["Q1 2018"],
        AWS_2025_SOURCE_BY_PERIOD["Q2 2018"],
        AWS_2025_SOURCE_BY_PERIOD["Q3 2018"],
        AWS_2025_SOURCE_BY_PERIOD["Q4 2018"],
    ],
    "Q4 2019": [
        AWS_2025_SOURCE_BY_PERIOD["Q1 2019"],
        AWS_2025_SOURCE_BY_PERIOD["Q2 2019"],
        AWS_2025_SOURCE_BY_PERIOD["Q3 2019"],
        AWS_2025_SOURCE_BY_PERIOD["Q4 2019"],
    ],
    "Q4 2020": [
        AWS_2025_SOURCE_BY_PERIOD["Q1 2020"],
        AWS_2025_SOURCE_BY_PERIOD["Q2 2020"],
        AWS_2025_SOURCE_BY_PERIOD["Q3 2020"],
        AWS_2025_SOURCE_BY_PERIOD["Q4 2020"],
    ],
    "Q4 2021": [
        AWS_2025_SOURCE_BY_PERIOD["Q1 2021"],
        AWS_2025_SOURCE_BY_PERIOD["Q2 2021"],
        AWS_2025_SOURCE_BY_PERIOD["Q3 2021"],
        AWS_2025_SOURCE_BY_PERIOD["Q4 2021"],
    ],
    "Q1 2022": [
        AWS_2025_SOURCE_BY_PERIOD["Q1 2022"],
        AWS_2025_SOURCE_BY_PERIOD["Q2 2022"],
        AWS_2025_SOURCE_BY_PERIOD["Q3 2022"],
        AWS_2025_SOURCE_BY_PERIOD["Q4 2022"],
    ],
    "Q4 2025": [
        AWS_2025_SOURCE_BY_PERIOD["Q1 2025"],
        AWS_2025_SOURCE_BY_PERIOD["Q2 2025"],
        AWS_2025_SOURCE_BY_PERIOD["Q3 2025"],
        AWS_2025_SOURCE_BY_PERIOD["Q4 2025"],
    ],
}

AWS_OFFICIAL_VERIFICATIONS = [
    _official_record(
        "AWS",
        period,
        metric_key,
        official_value,
        "millions USD",
        AWS_2025_SOURCE_BY_PERIOD[period]["label"],
        AWS_2025_SOURCE_BY_PERIOD[period]["url"],
        AWS_2025_SOURCE_BY_PERIOD[period]["evidence"],
        AWS_VERIFICATION_METHOD_BY_PERIOD.get(period, "official_cloud_segment_table_check"),
        [
            {
                "label": "Amazon quarterly results and filings",
                "url": AWS_QUARTERLY_RESULTS_INDEX_URL,
                "evidence": "Amazon official investor relations quarterly results index used to locate quarterly earnings releases.",
            },
            *AWS_VERIFICATION_SOURCES_BY_PERIOD.get(period, [AWS_2025_SOURCE_BY_PERIOD[period]]),
        ],
    )
    for period in [item["period"] for item in AWS_2025_PERIODS]
    for metrics in [
        {
            metric_key: period_values[period]
            for metric_key, period_values in AWS_2025_METRICS.items()
            if period in period_values
        }
    ]
    for metric_key, official_value in metrics.items()
]


MICROSOFT_OFFICIAL_VERIFICATIONS = [
    _official_record(
        "Microsoft Azure / Intelligent Cloud",
        period,
        metric_key,
        official_value,
        "percent" if metric_key == "azure_and_other_cloud_services_growth_yoy" else "millions USD",
        MICROSOFT_2025_SOURCE_BY_PERIOD[period]["label"],
        MICROSOFT_2025_SOURCE_BY_PERIOD[period]["url"],
        MICROSOFT_2025_SOURCE_BY_PERIOD[period]["evidence"],
        "official_cloud_segment_table_check",
        [
            {
                "label": "Microsoft quarterly earnings",
                "url": MICROSOFT_EARNINGS_INDEX_URL,
                "evidence": "Microsoft official investor relations earnings index used to locate quarterly earnings releases.",
            },
            {
                "label": MICROSOFT_2025_SOURCE_BY_PERIOD[period]["label"],
                "url": MICROSOFT_2025_SOURCE_BY_PERIOD[period]["url"],
                "type": MICROSOFT_2025_SOURCE_BY_PERIOD[period]["type"],
                "evidence": MICROSOFT_2025_SOURCE_BY_PERIOD[period]["evidence"],
            },
            {
                "label": f"{MICROSOFT_2025_SOURCE_BY_PERIOD[period]['label']} - Segment results",
                "url": MICROSOFT_2025_SOURCE_BY_PERIOD[period]["segment_url"],
                "type": "official_segment_results_page",
                "evidence": "Microsoft official segment page used to cross-check Intelligent Cloud segment revenue and operating income.",
            },
        ],
    )
    for period in [item["period"] for item in MICROSOFT_2025_PERIODS]
    for metrics in [
        {
            metric_key: period_values[period]
            for metric_key, period_values in MICROSOFT_2025_METRICS.items()
            if period in period_values
        }
    ]
    for metric_key, official_value in metrics.items()
]


GOOGLE_CLOUD_OFFICIAL_VERIFICATIONS = [
    _official_record(
        "Google Cloud",
        period,
        metric_key,
        official_value,
        "percent" if metric_key == "revenue_growth_yoy" else "millions USD",
        GOOGLE_CLOUD_2025_SOURCE_BY_PERIOD[period]["label"],
        GOOGLE_CLOUD_2025_SOURCE_BY_PERIOD[period]["url"],
        GOOGLE_CLOUD_2025_SOURCE_BY_PERIOD[period]["evidence"],
        "official_sec_quarterly_segment_table_and_annual_total_reconciliation",
        [
            {
                "label": "Alphabet investor relations earnings index",
                "url": ALPHABET_EARNINGS_INDEX_URL,
                "type": "official_quarterly_results_index",
                "evidence": "Alphabet official investor relations earnings index used to locate quarterly earnings context.",
            },
            GOOGLE_CLOUD_2025_SOURCE_BY_PERIOD[period],
            {
                "label": f"{GOOGLE_CLOUD_2025_SOURCE_BY_PERIOD[period]['label']} - annual Google Cloud segment cross-check",
                "url": GOOGLE_CLOUD_2025_SOURCE_BY_PERIOD[period]["annual_url"],
                "type": "official_annual_report_segment_table",
                "evidence": "Alphabet annual report Google Cloud segment table used to cross-check annual revenue and operating income totals or Q4 annual-minus-Q1-Q3 reconciliation.",
            },
        ],
    )
    for period in [item["period"] for item in GOOGLE_CLOUD_2025_PERIODS]
    for metrics in [
        {
            metric_key: period_values[period]
            for metric_key, period_values in GOOGLE_CLOUD_2025_METRICS.items()
            if period in period_values
        }
    ]
    for metric_key, official_value in metrics.items()
]


ORACLE_CLOUD_OFFICIAL_VERIFICATIONS = [
    _official_record(
        "Oracle Cloud",
        period,
        metric_key,
        official_value,
        "percent" if metric_key in PERCENT_KEYS else "billions USD",
        ORACLE_CLOUD_SOURCE_BY_PERIOD[period]["label"],
        ORACLE_CLOUD_SOURCE_BY_PERIOD[period]["url"],
        ORACLE_CLOUD_SOURCE_BY_PERIOD[period]["evidence"],
        "official_quarterly_cloud_revenue_disclosure_check",
        [
            {
                "label": "Oracle quarterly results",
                "url": "https://investor.oracle.com/financials/default.aspx",
                "type": "official_quarterly_results_index",
                "evidence": "Oracle Investor Relations quarterly results index used to locate official earnings releases.",
            },
            ORACLE_CLOUD_SOURCE_BY_PERIOD[period],
        ],
    )
    for period in [item["period"] for item in ORACLE_CLOUD_PERIODS]
    for metrics in [
        {
            metric_key: period_values[period]
            for metric_key, period_values in ORACLE_CLOUD_METRICS.items()
            if period in period_values
        }
    ]
    for metric_key, official_value in metrics.items()
]

ORACLE_CLOUD_PRE_IASSAAS_SOURCE_GAP_CONFIRMATIONS = [
    {
        "subject": "Oracle Cloud",
        "period": period,
        "metric_key": "cloud_quarterly_disclosure_status",
        "source_label": "Oracle FY2021 Q4 earnings release",
        "source_url": ORACLE_FY2021_Q4_INVESTOR_URL,
        "evidence": (
            "Oracle FY2021 Q4/FY2021 results and FY2021 Form 10-K disclose Cloud services and license support, "
            "applications cloud services and license support, and infrastructure cloud services and license support, "
            "but do not disclose the later comparable IaaS plus SaaS Cloud Revenue quarterly line. The retained "
            "Oracle Cloud series starts at FY2022 Q1 when Oracle reported IaaS plus SaaS cloud revenue totaled "
            f"$2.5 billion; therefore {period} is retained as a disclosure-boundary source gap rather than estimated."
        ),
        "verification_method": "official_oracle_cloud_iass_saas_disclosure_gap_check",
        "verification_sources": [
            {
                "label": "Oracle FY2021 Q4 earnings release",
                "url": ORACLE_FY2021_Q4_INVESTOR_URL,
                "type": "official_quarterly_earnings_release",
                "evidence": "Oracle FY2021 Q4 release discloses Cloud services and license support plus applications and infrastructure cloud services and license support, not the later IaaS plus SaaS Cloud Revenue quarterly line.",
            },
            {
                "label": "Oracle FY2021 Form 10-K",
                "url": ORACLE_2021_10K_URL,
                "type": "official_sec_10k",
                "evidence": "Oracle FY2021 Form 10-K retains the older Cloud services and license support disclosure structure and does not provide comparable quarterly IaaS plus SaaS Cloud Revenue rows.",
            },
            {
                "label": "Oracle FY2020 Form 10-K",
                "url": ORACLE_2020_10K_URL,
                "type": "official_sec_10k",
                "evidence": "Oracle FY2020 Form 10-K confirms the pre-FY2022 cloud disclosure framework used older cloud services and license support categories.",
            },
            {
                "label": "Oracle FY2022 Q1 earnings release",
                "url": ORACLE_Q1_FY2022_RESULTS_URL,
                "type": "official_quarterly_earnings_release",
                "evidence": "Oracle FY2022 Q1 release is the first retained source in this package with IaaS plus SaaS cloud revenue totaled $2.5 billion.",
            },
        ],
        "verification_note": "Oracle FY2017-FY2021 quarters are pre-IaaS-plus-SaaS disclosure-boundary gaps for the current cloud_revenue series. Older Cloud services and license support rows are not mixed into the retained FY2022-forward Oracle Cloud Revenue sequence and do not count toward the 40-quarter cloud coverage gate.",
        "append_if_missing": True,
    }
    for period in ORACLE_CLOUD_PRE_IASSAAS_SOURCE_GAP_PERIODS
]


TENCENT_FBS_OFFICIAL_VERIFICATIONS = [
    _official_record(
        "Tencent Cloud / Tencent FBS proxy",
        period,
        metric_key,
        official_value,
        "percent" if metric_key in PERCENT_KEYS else "millions CNY",
        TENCENT_FBS_SOURCE_BY_PERIOD[period]["label"],
        TENCENT_FBS_SOURCE_BY_PERIOD[period]["url"],
        TENCENT_FBS_SOURCE_BY_PERIOD[period]["evidence"],
        "official_proxy_segment_quarterly_revenue_check",
        [
            {
                "label": "Tencent financial news earnings releases index",
                "url": TENCENT_FINANCIAL_NEWS_URL,
                "type": "official_quarterly_results_index",
                "evidence": "Tencent official financial news page lists the earnings release PDFs used for the FinTech and Business Services proxy segment extraction from 2019 onward.",
            },
            TENCENT_FBS_SOURCE_BY_PERIOD[period],
        ],
    )
    for period in [item["period"] for item in TENCENT_FBS_PERIODS]
    for metrics in [
        {
            metric_key: period_values[period]
            for metric_key, period_values in TENCENT_FBS_METRICS.items()
            if period in period_values
        }
    ]
    for metric_key, official_value in metrics.items()
]


ALIBABA_LEGACY_CLOUD_SEGMENT_OFFICIAL_VERIFICATIONS = [
    _official_record(
        "Alibaba Cloud",
        period,
        metric_key,
        official_value,
        "millions CNY",
        ALIBABA_LEGACY_CLOUD_SEGMENT_SOURCE_BY_PERIOD[period]["label"],
        ALIBABA_LEGACY_CLOUD_SEGMENT_SOURCE_BY_PERIOD[period]["url"],
        (
            f"{ALIBABA_LEGACY_CLOUD_SEGMENT_SOURCE_BY_PERIOD[period]['evidence']} "
            "Do not use this old Cloud segment row in the retained Cloud Intelligence Group forecast series."
        ),
        "official_legacy_cloud_segment_non_forecast_check",
        [
            {
                "label": "Alibaba quarterly results index",
                "url": ALIBABA_QUARTERLY_RESULTS_URL,
                "type": "official_quarterly_results_index",
                "evidence": "Alibaba Investor Relations pages list the official quarterly results releases used for legacy Cloud segment and later Cloud Intelligence Group segment extraction.",
            },
            ALIBABA_LEGACY_CLOUD_SEGMENT_SOURCE_BY_PERIOD[period],
            ALIBABA_LEGACY_CLOUD_SEGMENT_SOURCE_BY_PERIOD[period]["cross_check"],
            {
                "label": "Alibaba September Quarter 2023 results - DingTalk reclassification",
                "url": ALIBABA_SEPTEMBER_QTR_2023_RESULTS_URL,
                "type": "official_sec_6k_restated_segment_boundary",
                "evidence": "Alibaba September quarter 2023 results state DingTalk was reclassified from Cloud Intelligence Group to All others and comparative figures were reclassified, confirming that older Cloud segment rows are not comparable to the retained forecasting series.",
            },
        ],
    )
    for period in ["FY2022 Q1", "FY2022 Q2", "FY2022 Q3", "FY2022 Q4"]
    for metrics in [
        {
            metric_key: period_values[period]
            for metric_key, period_values in ALIBABA_LEGACY_CLOUD_SEGMENT_METRICS.items()
            if period in period_values
        }
    ]
    for metric_key, official_value in metrics.items()
]


ALIBABA_CLOUD_OFFICIAL_VERIFICATIONS = [
    _official_record(
        "Alibaba Cloud",
        period,
        metric_key,
        official_value,
        "percent" if metric_key in PERCENT_KEYS else "millions CNY",
        ALIBABA_CLOUD_SOURCE_BY_PERIOD[period]["label"],
        ALIBABA_CLOUD_SOURCE_BY_PERIOD[period]["url"],
        ALIBABA_CLOUD_SOURCE_BY_PERIOD[period]["evidence"],
        "official_quarterly_cloud_segment_disclosure_check",
        [
            {
                "label": "Alibaba quarterly results index",
                "url": ALIBABA_QUARTERLY_RESULTS_URL,
                "type": "official_quarterly_results_index",
                "evidence": "Alibaba Investor Relations pages list the official quarterly results press releases used for Cloud Intelligence Group segment extraction.",
            },
            {
                "label": f"{ALIBABA_CLOUD_SOURCE_BY_PERIOD[period]['label']} announcement page",
                "url": ALIBABA_CLOUD_SOURCE_BY_PERIOD[period]["document_url"],
                "type": "official_results_announcement_page",
                "evidence": "Alibaba official announcement page states the press release is available in PDF version only and links to the official PDF.",
            },
            ALIBABA_CLOUD_SOURCE_BY_PERIOD[period],
        ],
    )
    for period in [item["period"] for item in ALIBABA_CLOUD_PERIODS]
    for metrics in [
        {
            metric_key: period_values[period]
            for metric_key, period_values in ALIBABA_CLOUD_METRICS.items()
            if period in period_values
        }
    ]
    for metric_key, official_value in metrics.items()
]


HKBN_2021_2022_SOURCE_BY_PERIOD = {
    "H2 2021": ("HKBN FY21 Annual Results Announcement", HKBN_FY21_ANNUAL_RESULTS_URL, HKBN_2021_H2_SOURCES),
    "H1 2022": ("HKBN FY22 Interim Results Announcement", HKBN_FY22_INTERIM_URL, HKBN_2022_H1_SOURCES),
    "H2 2022": ("HKBN FY22 Annual Results Announcement", HKBN_FY22_ANNUAL_RESULTS_URL, HKBN_2022_H2_SOURCES),
}

HKBN_2021_2022_PERIOD_METRICS = {
    "H2 2021": {
        "revenue": (5234.161, "millions HKD", "FY21全年Revenue 11,463,745千港元减H1 2021比较栏Revenue 6,229,584千港元，复算H2 2021为5,234,161千港元。", "official_full_year_minus_h1_reconciliation"),
        "revenue_growth_yoy": (4.774, "percent", "FY21全年Revenue 11,463,745千港元减H1 2021 6,229,584得H2 2021收入5,234,161千港元；FY20全年Revenue 9,452,957千港元减H1 2020 4,457,282得H2 2020收入4,995,675千港元，复算同比增长4.774%。", "official_full_year_minus_h1_prior_period_reconciliation"),
        "net_income": (158.310, "millions HKD", "FY21全年Profit for the year 206,872千港元减H1 2021比较栏Profit 48,562千港元，复算H2 2021为158,310千港元。", "official_full_year_minus_h1_reconciliation"),
        "operating_income": (421.496, "millions HKD", "FY21全年按损益表复算经营利润837,802千港元，减H1 2021经营利润416,306千港元，复算H2 2021为421,496千港元。", "official_full_year_minus_h1_operating_profit_reconciliation"),
        "operating_margin": (8.052, "percent", "以H2 2021官方复算经营利润421,496千港元除以H2 Revenue 5,234,161千港元，复算经营利润率为8.052%。", "official_operating_income_divided_by_revenue_reconciliation"),
        "ebitda": (1256.690, "millions HKD", "FY21全年EBITDA 2,568,507千港元减H1 2021比较栏EBITDA 1,311,817千港元，复算H2 2021为1,256,690千港元。", "official_full_year_minus_h1_reconciliation"),
        "capital_expenditures": (-264.017, "millions HKD", "FY21全年Capital expenditure 589,621千港元减H1 2021比较栏325,604千港元，复算H2资本开支为264,017千港元，现金流出口径记为负数。", "official_full_year_minus_h1_aff_reconciliation"),
        "adjusted_funds_flow": (740.086, "millions HKD", "FY21全年Adjusted Free Cash Flow 1,131,543千港元减H1 2021比较栏391,457千港元，复算H2 2021为740,086千港元。该口径为HKBN定义的AFF。", "official_full_year_minus_h1_aff_reconciliation"),
        "gross_profit": (2209.553, "millions HKD", "FY21全年毛利按Revenue 11,463,745减Network costs and costs of sales 6,950,885为4,512,860千港元；减H1 2021毛利2,303,307千港元后H2为2,209,553千港元。", "official_full_year_minus_h1_gross_profit_reconciliation"),
        "operating_cash_flow": (1261.451, "millions HKD", "FY21正式年报现金流量表披露全年经营现金流2,354,286千港元；减H1 2021比较栏1,092,835千港元，复算H2为1,261,451千港元。", "official_full_year_minus_h1_cash_flow_reconciliation"),
        "free_cash_flow": (854.185, "millions HKD", "FY21全年购买物业厂房及设备付款572,352千港元；减H1 2021比较栏165,086千港元后H2资本性付款407,266千港元，H2普通自由现金流为1,261,451减407,266，即854,185千港元。", "official_operating_cash_flow_minus_ppe_reconciliation"),
        "cash_and_equivalents": (1421.124, "millions HKD", "FY21全年公告资产负债表披露2021年8月31日Cash and cash equivalents为1,421,124千港元；现金流量表期末现金为1,526,661千港元，差异来自分类口径。", "official_annual_balance_sheet_check"),
        "total_assets": (21768.433, "millions HKD", "FY21全年公告资产负债表披露非流动资产18,152,352千港元、流动资产3,616,081千港元，合计总资产21,768,433千港元。", "official_annual_balance_sheet_reconciliation"),
        "total_debt": (12124, "millions HKD", "FY21全年公告Liquidity and Capital Resources披露2021年8月31日gross debt为12,124百万港元，其中包含508百万港元租赁负债。", "official_annual_liquidity_check"),
    },
    "H1 2022": {
        "revenue": (6803.050, "millions HKD", "FY22中期公告Financial highlights和损益表均披露H1 2022 Revenue为6,803,050千港元；FY23中期公告H1 2022比较栏交叉验证。", "official_interim_statement_check"),
        "net_income": (304.330, "millions HKD", "FY22中期公告Financial highlights和损益表均披露Profit for the period为304,330千港元。", "official_interim_statement_check"),
        "operating_income": (500.645, "millions HKD", "FY22中期公告损益表披露Revenue 6,803,050、Other net income 37,085、Network costs and costs of sales 4,499,739、Other operating expenses 1,839,751千港元，复算经营利润为500,645千港元。", "official_interim_operating_profit_reconciliation"),
        "operating_margin": (7.359, "percent", "以H1 2022官方复算经营利润500,645千港元除以Revenue 6,803,050千港元，复算经营利润率为7.359%。", "official_operating_income_divided_by_revenue_reconciliation"),
        "revenue_growth_yoy": (9.207, "percent", "FY22中期公告披露H1 2022 Revenue 6,803,050千港元、H1 2021 Revenue 6,229,584千港元，复算同比增长9.207%。", "official_current_prior_period_reconciliation"),
        "ebitda": (1319.543, "millions HKD", "FY22中期公告Financial highlights和EBITDA/AFF reconciliation均披露EBITDA (Adjusted)为1,319,543千港元；FY23中期公告比较栏交叉验证。", "official_interim_statement_check"),
        "capital_expenditures": (-291.603, "millions HKD", "FY22中期公告EBITDA/AFF reconciliation披露Capital expenditure为291,603千港元，现金流出口径记为负数。", "official_interim_aff_reconciliation_check"),
        "adjusted_funds_flow": (757.750, "millions HKD", "FY22中期公告披露Adjusted Free Cash Flow为757,750千港元。该口径为HKBN定义的AFF，不等同HKFRS经营现金流。", "official_interim_aff_check"),
        "gross_profit": (2303.311, "millions HKD", "FY22中期损益表披露Revenue 6,803,050千港元、Network costs and costs of sales 4,499,739千港元，复算毛利为2,303,311千港元。", "official_revenue_minus_network_costs_reconciliation"),
        "operating_cash_flow": (812.540, "millions HKD", "FY22中期正式报告现金流量表披露Net cash generated from operating activities为812,540千港元。", "official_interim_cash_flow_statement_check"),
        "free_cash_flow": (602.553, "millions HKD", "FY22中期正式报告披露经营现金流812,540千港元、购买物业厂房及设备付款209,987千港元，复算普通自由现金流为602,553千港元。", "official_operating_cash_flow_minus_ppe_reconciliation"),
        "cash_and_equivalents": (1154.341, "millions HKD", "FY22中期公告资产负债表披露2022年2月28日Cash and cash equivalents为1,154,341千港元；Liquidity段落交叉披露约1,154百万港元。", "official_interim_balance_sheet_check"),
        "total_assets": (21007.819, "millions HKD", "FY22中期公告资产负债表披露非流动资产17,686,501千港元、流动资产3,321,318千港元，合计总资产21,007,819千港元。", "official_interim_balance_sheet_reconciliation"),
        "total_debt": (11814, "millions HKD", "FY22中期公告Liquidity and Capital Resources披露2022年2月28日gross debt为11,814百万港元，其中包含388百万港元租赁负债。", "official_interim_liquidity_check"),
    },
    "H2 2022": {
        "revenue": (4823.114, "millions HKD", "FY22全年Revenue 11,626,164千港元减H1 Revenue 6,803,050千港元，复算H2为4,823,114千港元；FY23全年公告比较栏交叉验证FY22全年收入。", "official_full_year_minus_h1_reconciliation"),
        "net_income": (248.991, "millions HKD", "FY22全年Profit for the year 553,321千港元减H1 Profit 304,330千港元，复算H2为248,991千港元。", "official_full_year_minus_h1_reconciliation"),
        "operating_income": (500.105, "millions HKD", "FY22全年按损益表复算经营利润1,000,750千港元，减H1 2022经营利润500,645千港元，复算H2为500,105千港元。", "official_full_year_minus_h1_operating_profit_reconciliation"),
        "operating_margin": (10.369, "percent", "以H2 2022官方复算经营利润500,105千港元除以H2 Revenue 4,823,114千港元，复算经营利润率为10.369%。", "official_operating_income_divided_by_revenue_reconciliation"),
        "revenue_growth_yoy": (-7.854, "percent", "FY22全年Revenue 11,626,164千港元减H1 2022 6,803,050得H2 2022收入4,823,114千港元；FY21全年11,463,745减H1 2021 6,229,584得H2 2021收入5,234,161千港元，复算同比下降7.854%。", "official_full_year_minus_h1_prior_period_reconciliation"),
        "ebitda": (1289.510, "millions HKD", "FY22全年EBITDA (Adjusted) 2,609,053千港元减H1 EBITDA 1,319,543千港元，复算H2为1,289,510千港元；FY23全年公告比较栏交叉验证FY22全年EBITDA。", "official_full_year_minus_h1_reconciliation"),
        "capital_expenditures": (-247.904, "millions HKD", "FY22全年Capital expenditure 539,507千港元减H1 291,603千港元，复算H2资本开支为247,904千港元，现金流出口径记为负数。", "official_full_year_minus_h1_aff_reconciliation"),
        "adjusted_funds_flow": (374.806, "millions HKD", "FY22全年Adjusted Free Cash Flow 1,132,556千港元减H1 AFF 757,750千港元，复算H2为374,806千港元。该口径为HKBN定义的AFF。", "official_full_year_minus_h1_aff_reconciliation"),
        "gross_profit": (2167.050, "millions HKD", "FY22全年毛利按Revenue 11,626,164减Network costs and costs of sales 7,155,803为4,470,361千港元；减H1 2,303,311后H2为2,167,050千港元。", "official_full_year_minus_h1_gross_profit_reconciliation"),
        "operating_cash_flow": (1049.469, "millions HKD", "FY22正式年报现金流量表披露全年经营现金流1,862,009千港元；减H1 812,540后H2为1,049,469千港元。", "official_full_year_minus_h1_cash_flow_reconciliation"),
        "free_cash_flow": (743.332, "millions HKD", "FY22全年购买物业厂房及设备付款516,124千港元；减H1 209,987后H2资本性付款306,137千港元，H2普通自由现金流为1,049,469减306,137，即743,332千港元。", "official_operating_cash_flow_minus_ppe_reconciliation"),
        "cash_and_equivalents": (1129.226, "millions HKD", "FY22全年公告资产负债表披露2022年8月31日Cash and cash equivalents为1,129,226千港元；Liquidity段落交叉披露约1,129百万港元。", "official_annual_balance_sheet_check"),
        "total_assets": (20427.098, "millions HKD", "FY22全年公告资产负债表披露非流动资产17,383,846千港元、流动资产3,043,252千港元，合计总资产20,427,098千港元。", "official_annual_balance_sheet_reconciliation"),
        "total_debt": (11865, "millions HKD", "FY22全年公告Liquidity and Capital Resources披露2022年8月31日gross debt为11,865百万港元，其中包含518百万港元租赁负债。", "official_annual_liquidity_check"),
    },
}

HKBN_2021_2022_OFFICIAL_VERIFICATIONS = [
    _official_record(
        "HKBN",
        period,
        metric_key,
        official_value,
        unit,
        HKBN_2021_2022_SOURCE_BY_PERIOD[period][0],
        HKBN_2021_2022_SOURCE_BY_PERIOD[period][1],
        evidence,
        verification_method,
        HKBN_2021_2022_SOURCE_BY_PERIOD[period][2],
    )
    for period, period_values in HKBN_2021_2022_PERIOD_METRICS.items()
    for metric_key, (official_value, unit, evidence, verification_method) in period_values.items()
]

HKBN_OFFICIAL_VERIFICATIONS = [
    *HKBN_2016_2021_OFFICIAL_VERIFICATIONS,
    *HKBN_2021_2022_OFFICIAL_VERIFICATIONS,
    _official_record("HKBN", "H1 2023", "revenue", 6707.216, "millions HKD", "HKBN FY23 Interim Results Announcement", HKBN_FY23_INTERIM_URL, "FY23中期公告Financial highlights和损益表均披露H1 2023 Revenue为6,707,216千港元；FY24中期公告H1 2023比较栏交叉验证。", "official_interim_statement_check", HKBN_2023_H1_SOURCES),
    _official_record("HKBN", "H1 2023", "net_income", 23.238, "millions HKD", "HKBN FY23 Interim Results Announcement", HKBN_FY23_INTERIM_URL, "FY23中期公告Financial highlights和损益表均披露Profit for the period为23,238千港元；FY24中期公告H1 2023比较栏交叉验证。", "official_interim_statement_check", HKBN_2023_H1_SOURCES),
    _official_record("HKBN", "H1 2023", "operating_income", 397.595, "millions HKD", "HKBN FY23 Interim Results Announcement", HKBN_FY23_INTERIM_URL, "FY23中期公告损益表披露Revenue 6,707,216千港元、Other net income 9,667千港元、Network costs and costs of sales 4,573,040千港元、Other operating expenses 1,746,248千港元，复算经营利润为397,595千港元。", "official_interim_operating_profit_reconciliation", HKBN_2023_H1_SOURCES),
    _official_record("HKBN", "H1 2023", "operating_margin", 5.928, "percent", "HKBN FY23 Interim Results Announcement", HKBN_FY23_INTERIM_URL, "以H1 2023官方复算经营利润397,595千港元除以Revenue 6,707,216千港元，复算经营利润率为5.928%。", "official_operating_income_divided_by_revenue_reconciliation", HKBN_2023_H1_SOURCES),
    _official_record("HKBN", "H1 2023", "revenue_growth_yoy", -1.409, "percent", "HKBN FY23 Interim Results Announcement", HKBN_FY23_INTERIM_URL, "FY23中期公告披露H1 2023 Revenue 6,707,216千港元、H1 2022 Revenue 6,803,050千港元，复算同比下降1.409%。", "official_current_prior_period_reconciliation", HKBN_2023_H1_SOURCES),
    _official_record("HKBN", "H1 2023", "ebitda", 1195.742, "millions HKD", "HKBN FY23 Interim Results Announcement", HKBN_FY23_INTERIM_URL, "FY23中期公告Financial highlights和EBITDA/AFF reconciliation均披露EBITDA (Adjusted)为1,195,742千港元；FY24中期公告H1 2023比较栏交叉验证。", "official_interim_statement_check", HKBN_2023_H1_SOURCES),
    _official_record("HKBN", "H1 2023", "capital_expenditures", -304.234, "millions HKD", "HKBN FY23 Interim Results Announcement", HKBN_FY23_INTERIM_URL, "FY23中期公告EBITDA/AFF reconciliation披露Capital expenditure为304,234千港元，现金流出口径记为负数；FY24中期公告H1 2023比较栏交叉验证。", "official_interim_aff_reconciliation_check", HKBN_2023_H1_SOURCES),
    _official_record("HKBN", "H1 2023", "adjusted_funds_flow", 367.648, "millions HKD", "HKBN FY23 Interim Results Announcement", HKBN_FY23_INTERIM_URL, "FY23中期公告披露Adjusted Free Cash Flow为367,648千港元。该口径为HKBN定义的AFF，不等同HKFRS经营现金流。", "official_interim_aff_check", HKBN_2023_H1_SOURCES),
    _official_record("HKBN", "H1 2023", "cash_and_equivalents", 979.734, "millions HKD", "HKBN FY23 Interim Results Announcement", HKBN_FY23_INTERIM_URL, "FY23中期公告资产负债表披露2023年2月28日Cash and cash equivalents为979,734千港元；Liquidity段落交叉披露约980百万港元。", "official_interim_balance_sheet_check", HKBN_2023_H1_SOURCES),
    _official_record("HKBN", "H1 2023", "total_assets", 19937.194, "millions HKD", "HKBN FY23 Interim Results Announcement", HKBN_FY23_INTERIM_URL, "FY23中期公告资产负债表披露非流动资产16,986,583千港元、流动资产2,950,611千港元，合计总资产19,937,194千港元。", "official_interim_balance_sheet_reconciliation", HKBN_2023_H1_SOURCES),
    _official_record("HKBN", "H1 2023", "total_debt", 11745, "millions HKD", "HKBN FY23 Interim Results Announcement", HKBN_FY23_INTERIM_URL, "FY23中期公告Liquidity and Capital Resources披露2023年2月28日gross debt为11,745百万港元，其中包含538百万港元租赁负债。", "official_interim_liquidity_check", HKBN_2023_H1_SOURCES),
    _official_record("HKBN", "H2 2023", "revenue", 4984.960, "millions HKD", "HKBN FY23 Annual Results Announcement", HKBN_FY23_ANNUAL_RESULTS_URL, "FY23全年Revenue 11,692,176千港元减H1 Revenue 6,707,216千港元，复算H2为4,984,960千港元；新闻稿披露全年总收入约11,692百万港元。", "official_full_year_minus_h1_reconciliation", HKBN_2023_H2_SOURCES),
    _official_record("HKBN", "H2 2023", "net_income", -1290.646, "millions HKD", "HKBN FY23 Annual Results Announcement", HKBN_FY23_ANNUAL_RESULTS_URL, "FY23全年Loss for the year 1,267,408千港元减H1 Profit 23,238千港元，复算H2亏损为1,290,646千港元。", "official_full_year_minus_h1_reconciliation", HKBN_2023_H2_SOURCES),
    _official_record("HKBN", "H2 2023", "operating_income", 343.711, "millions HKD", "HKBN FY23 Annual Results Announcement", HKBN_FY23_ANNUAL_RESULTS_URL, "FY23全年按损益表在goodwill impairment前复算经营利润741,306千港元，减H1 2023经营利润397,595千港元，复算H2为343,711千港元；goodwill impairment为一次性非现金减值，未纳入该经营利润口径。", "official_full_year_minus_h1_operating_profit_before_impairment_reconciliation", HKBN_2023_H2_SOURCES),
    _official_record("HKBN", "H2 2023", "operating_margin", 6.895, "percent", "HKBN FY23 Annual Results Announcement", HKBN_FY23_ANNUAL_RESULTS_URL, "以H2 2023官方复算经营利润343,711千港元除以H2 Revenue 4,984,960千港元，复算经营利润率为6.895%。", "official_operating_income_divided_by_revenue_reconciliation", HKBN_2023_H2_SOURCES),
    _official_record("HKBN", "H2 2023", "revenue_growth_yoy", 3.356, "percent", "HKBN FY23 Annual Results Announcement", HKBN_FY23_ANNUAL_RESULTS_URL, "FY23全年Revenue 11,692,176千港元、FY22全年11,626,164千港元；扣除H1 2023 6,707,216千港元和H1 2022 6,803,050千港元，复算H2 2023收入4,984,960千港元、H2 2022收入4,823,114千港元，同比增长3.356%。", "official_full_year_minus_h1_prior_period_reconciliation", HKBN_2023_H2_SOURCES),
    _official_record("HKBN", "H2 2023", "ebitda", 1094.172, "millions HKD", "HKBN FY23 Annual Results Announcement", HKBN_FY23_ANNUAL_RESULTS_URL, "FY23全年EBITDA (Adjusted) 2,289,914千港元减H1 EBITDA 1,195,742千港元，复算H2为1,094,172千港元；新闻稿交叉验证FY23全年EBITDA约2,290百万港元。", "official_full_year_minus_h1_reconciliation", HKBN_2023_H2_SOURCES),
    _official_record("HKBN", "H2 2023", "capital_expenditures", -207.768, "millions HKD", "HKBN FY23 Annual Results Announcement", HKBN_FY23_ANNUAL_RESULTS_URL, "FY23全年Capital expenditure 512,002千港元减H1 304,234千港元，复算H2资本开支为207,768千港元，现金流出口径记为负数。", "official_full_year_minus_h1_aff_reconciliation", HKBN_2023_H2_SOURCES),
    _official_record("HKBN", "H2 2023", "adjusted_funds_flow", 395.601, "millions HKD", "HKBN FY23 Annual Results Announcement", HKBN_FY23_ANNUAL_RESULTS_URL, "FY23全年AFF 763,249千港元减H1 AFF 367,648千港元，复算H2为395,601千港元。该口径为HKBN定义的AFF。", "official_full_year_minus_h1_aff_reconciliation", HKBN_2023_H2_SOURCES),
    _official_record("HKBN", "H2 2023", "cash_and_equivalents", 1016.769, "millions HKD", "HKBN FY23 Annual Results Announcement", HKBN_FY23_ANNUAL_RESULTS_URL, "FY23全年公告资产负债表披露2023年8月31日Cash and cash equivalents为1,016,769千港元；Liquidity段落交叉披露约1,017百万港元。", "official_annual_balance_sheet_check", HKBN_2023_H2_SOURCES),
    _official_record("HKBN", "H2 2023", "total_assets", 18147.605, "millions HKD", "HKBN FY23 Annual Results Announcement", HKBN_FY23_ANNUAL_RESULTS_URL, "FY23全年公告资产负债表披露非流动资产15,314,980千港元、流动资产2,832,625千港元，合计总资产18,147,605千港元。", "official_annual_balance_sheet_reconciliation", HKBN_2023_H2_SOURCES),
    _official_record("HKBN", "H2 2023", "total_debt", 11589, "millions HKD", "HKBN FY23 Annual Results Announcement", HKBN_FY23_ANNUAL_RESULTS_URL, "FY23全年公告Liquidity and Capital Resources披露2023年8月31日gross debt为11,589百万港元，其中包含536百万港元租赁负债。", "official_annual_liquidity_check", HKBN_2023_H2_SOURCES),
    _official_record("HKBN", "H1 2024", "revenue", 5809.091, "millions HKD", "HKBN FY24 Interim Results Announcement", HKBN_FY24_INTERIM_URL, "FY24中期公告Financial highlights披露H1 2024 Revenue为5,809,091千港元。", "official_interim_statement_check", HKBN_2024_H1_SOURCES),
    _official_record("HKBN", "H1 2024", "net_income", 1.534, "millions HKD", "HKBN FY24 Interim Results Announcement", HKBN_FY24_INTERIM_URL, "FY24中期公告Financial highlights和损益表均披露Profit for the period为1,534千港元。", "official_interim_statement_check", HKBN_2024_H1_SOURCES),
    _official_record("HKBN", "H1 2024", "operating_income", 408.665, "millions HKD", "HKBN FY24 Interim Results Announcement", HKBN_FY24_INTERIM_URL, "FY24中期公告损益表披露Revenue 5,809,091千港元、Other net loss 506千港元、Network costs and costs of sales 3,772,148千港元、Other operating expenses 1,627,772千港元，复算经营利润为408,665千港元。", "official_interim_operating_profit_reconciliation", HKBN_2024_H1_SOURCES),
    _official_record("HKBN", "H1 2024", "operating_margin", 7.035, "percent", "HKBN FY24 Interim Results Announcement", HKBN_FY24_INTERIM_URL, "以H1 2024官方复算经营利润408,665千港元除以Revenue 5,809,091千港元，复算经营利润率为7.035%。", "official_operating_income_divided_by_revenue_reconciliation", HKBN_2024_H1_SOURCES),
    _official_record("HKBN", "H1 2024", "revenue_growth_yoy", -13.390, "percent", "HKBN FY24 Interim Results Announcement", HKBN_FY24_INTERIM_URL, "FY24中期公告披露H1 2024 Revenue 5,809,091千港元、H1 2023 Revenue 6,707,216千港元，复算同比下降13.390%。", "official_current_prior_period_reconciliation", HKBN_2024_H1_SOURCES),
    _official_record("HKBN", "H1 2024", "ebitda", 1151.172, "millions HKD", "HKBN FY24 Interim Results Announcement", HKBN_FY24_INTERIM_URL, "FY24中期公告Financial highlights和EBITDA/AFF reconciliation均披露EBITDA为1,151,172千港元。", "official_interim_statement_check", HKBN_2024_H1_SOURCES),
    _official_record("HKBN", "H1 2024", "capital_expenditures", -204.240, "millions HKD", "HKBN FY24 Interim Results Announcement", HKBN_FY24_INTERIM_URL, "FY24中期公告EBITDA/AFF reconciliation披露Capital expenditure为204,240千港元，现金流出口径记为负数。", "official_interim_aff_reconciliation_check", HKBN_2024_H1_SOURCES),
    _official_record("HKBN", "H1 2024", "adjusted_funds_flow", 124.248, "millions HKD", "HKBN FY24 Interim Results Announcement", HKBN_FY24_INTERIM_URL, "FY24中期公告披露Adjusted Free Cash Flow为124,248千港元。该口径为HKBN定义的AFF，不等同HKFRS经营现金流。", "official_interim_aff_check", HKBN_2024_H1_SOURCES),
    _official_record("HKBN", "H1 2024", "cash_and_equivalents", 804.443, "millions HKD", "HKBN FY24 Interim Results Announcement", HKBN_FY24_INTERIM_URL, "FY24中期公告资产负债表披露2024年2月29日Cash and cash equivalents为804,443千港元；Liquidity段落交叉披露约804百万港元。", "official_interim_balance_sheet_check", HKBN_2024_H1_SOURCES),
    _official_record("HKBN", "H1 2024", "total_assets", 17503.242, "millions HKD", "HKBN FY24 Interim Results Announcement", HKBN_FY24_INTERIM_URL, "FY24中期公告资产负债表披露非流动资产14,907,890千港元、流动资产2,595,352千港元，合计总资产17,503,242千港元。", "official_interim_balance_sheet_reconciliation", HKBN_2024_H1_SOURCES),
    _official_record("HKBN", "H1 2024", "total_debt", 11461, "millions HKD", "HKBN FY24 Interim Results Announcement", HKBN_FY24_INTERIM_URL, "FY24中期公告Liquidity and Capital Resources披露2024年2月29日gross debt为11,461百万港元，其中包含461百万港元租赁负债。", "official_interim_liquidity_check", HKBN_2024_H1_SOURCES),
    _official_record("HKBN", "H2 2024", "revenue", 4841.831, "millions HKD", "HKBN FY24 Annual Results Announcement", HKBN_FY24_ANNUAL_RESULTS_URL, "FY24全年Revenue 10,650,922千港元减H1 Revenue 5,809,091千港元，复算H2为4,841,831千港元；新闻稿披露全年总收入约10,651百万港元。", "official_full_year_minus_h1_reconciliation", HKBN_2024_H2_SOURCES),
    _official_record("HKBN", "H2 2024", "net_income", 8.743, "millions HKD", "HKBN FY24 Annual Results Announcement", HKBN_FY24_ANNUAL_RESULTS_URL, "FY24全年Profit for the year 10,277千港元减H1 Profit 1,534千港元，复算H2为8,743千港元。", "official_full_year_minus_h1_reconciliation", HKBN_2024_H2_SOURCES),
    _official_record("HKBN", "H2 2024", "operating_income", 480.824, "millions HKD", "HKBN FY24 Annual Results Announcement", HKBN_FY24_ANNUAL_RESULTS_URL, "FY24全年按损益表复算经营利润889,489千港元，减H1 2024经营利润408,665千港元，复算H2为480,824千港元。", "official_full_year_minus_h1_operating_profit_reconciliation", HKBN_2024_H2_SOURCES),
    _official_record("HKBN", "H2 2024", "operating_margin", 9.931, "percent", "HKBN FY24 Annual Results Announcement", HKBN_FY24_ANNUAL_RESULTS_URL, "以H2 2024官方复算经营利润480,824千港元除以H2 Revenue 4,841,831千港元，复算经营利润率为9.931%。", "official_operating_income_divided_by_revenue_reconciliation", HKBN_2024_H2_SOURCES),
    _official_record("HKBN", "H2 2024", "revenue_growth_yoy", -2.871, "percent", "HKBN FY24 Annual Results Announcement", HKBN_FY24_ANNUAL_RESULTS_URL, "FY24全年Revenue 10,650,922千港元、FY23全年11,692,176千港元；扣除H1 2024 5,809,091千港元和H1 2023 6,707,216千港元，复算H2 2024收入4,841,831千港元、H2 2023收入4,984,960千港元，同比下降2.871%。", "official_full_year_minus_h1_prior_period_reconciliation", HKBN_2024_H2_SOURCES),
    _official_record("HKBN", "H2 2024", "ebitda", 1213.587, "millions HKD", "HKBN FY24 Annual Results Announcement", HKBN_FY24_ANNUAL_RESULTS_URL, "FY24全年EBITDA 2,364,759千港元减H1 EBITDA 1,151,172千港元，复算H2为1,213,587千港元；新闻稿交叉披露FY24 H2 EBITDA约1,214百万港元。", "official_full_year_minus_h1_reconciliation", HKBN_2024_H2_SOURCES),
    _official_record("HKBN", "H2 2024", "capital_expenditures", -175.096, "millions HKD", "HKBN FY24 Annual Results Announcement", HKBN_FY24_ANNUAL_RESULTS_URL, "FY24全年Capital expenditure 379,336千港元减H1 204,240千港元，复算H2资本开支为175,096千港元，现金流出口径记为负数。", "official_full_year_minus_h1_aff_reconciliation", HKBN_2024_H2_SOURCES),
    _official_record("HKBN", "H2 2024", "adjusted_funds_flow", 495.897, "millions HKD", "HKBN FY24 Annual Results Announcement", HKBN_FY24_ANNUAL_RESULTS_URL, "FY24全年AFF 620,145千港元减H1 AFF 124,248千港元，复算H2为495,897千港元。该口径为HKBN定义的AFF。", "official_full_year_minus_h1_aff_reconciliation", HKBN_2024_H2_SOURCES),
    _official_record("HKBN", "H2 2024", "cash_and_equivalents", 1217.406, "millions HKD", "HKBN FY24 Annual Results Announcement", HKBN_FY24_ANNUAL_RESULTS_URL, "FY24全年公告资产负债表披露2024年8月31日Cash and cash equivalents为1,217,406千港元；Liquidity段落交叉披露约1,217百万港元。", "official_annual_balance_sheet_check", HKBN_2024_H2_SOURCES),
    _official_record("HKBN", "H2 2024", "total_assets", 17668.832, "millions HKD", "HKBN FY24 Annual Results Announcement", HKBN_FY24_ANNUAL_RESULTS_URL, "FY24全年公告资产负债表披露非流动资产14,604,360千港元、流动资产3,064,472千港元，合计总资产17,668,832千港元。", "official_annual_balance_sheet_reconciliation", HKBN_2024_H2_SOURCES),
    _official_record("HKBN", "H2 2024", "total_debt", 11528, "millions HKD", "HKBN FY24 Annual Results Announcement", HKBN_FY24_ANNUAL_RESULTS_URL, "FY24全年公告Liquidity and Capital Resources披露2024年8月31日gross debt为11,528百万港元，其中包含494百万港元租赁负债。", "official_annual_liquidity_check", HKBN_2024_H2_SOURCES),
    _official_record("HKBN", "H1 2025", "revenue", 5734.269, "millions HKD", "HKBN FY25 Interim Results Announcement", HKBN_FY25_INTERIM_URL, "FY25中期公告Financial highlights披露Revenue为5,734,269千港元。", "official_interim_statement_check", HKBN_2025_H1_SOURCES),
    _official_record("HKBN", "H1 2025", "net_income", 107.560, "millions HKD", "HKBN FY25 Interim Results Announcement", HKBN_FY25_INTERIM_URL, "FY25中期公告Financial highlights披露Profit for the period为107,560千港元。", "official_interim_statement_check", HKBN_2025_H1_SOURCES),
    _official_record("HKBN", "H1 2025", "ebitda", 1206.122, "millions HKD", "HKBN FY25 Interim Results Announcement", HKBN_FY25_INTERIM_URL, "FY25中期公告Financial highlights和EBITDA/AFF reconciliation均披露EBITDA为1,206,122千港元。", "official_interim_statement_check", HKBN_2025_H1_SOURCES),
    _official_record("HKBN", "H1 2025", "capital_expenditures", -238.513, "millions HKD", "HKBN FY25 Interim Results Announcement", HKBN_FY25_INTERIM_URL, "FY25中期公告EBITDA/AFF reconciliation披露Capital expenditure为238,513千港元，现金流出口径记为负数。", "official_interim_aff_reconciliation_check", HKBN_2025_H1_SOURCES),
    _official_record("HKBN", "H1 2025", "adjusted_funds_flow", 126.186, "millions HKD", "HKBN FY25 Interim Results Announcement", HKBN_FY25_INTERIM_URL, "FY25中期公告披露Adjusted Free Cash Flow为126,186千港元。该口径为HKBN定义的AFF，不等同HKFRS经营现金流。", "official_interim_aff_check", HKBN_2025_H1_SOURCES),
    _official_record("HKBN", "H1 2025", "cash_and_equivalents", 1077.969, "millions HKD", "HKBN FY25 Interim Results Announcement", HKBN_FY25_INTERIM_URL, "FY25中期公告资产负债表披露2025年2月28日Cash and cash equivalents为1,077,969千港元。", "official_interim_balance_sheet_check", HKBN_2025_H1_SOURCES),
    _official_record("HKBN", "H1 2025", "total_assets", 17371.436, "millions HKD", "HKBN FY25 Interim Results Announcement", HKBN_FY25_INTERIM_URL, "FY25中期公告资产负债表披露非流动资产14,309,711、流动资产3,061,725，合计总资产17,371,436千港元。", "official_interim_balance_sheet_reconciliation", HKBN_2025_H1_SOURCES),
    _official_record("HKBN", "H1 2025", "total_debt", 11406, "millions HKD", "HKBN FY25 Interim Results Announcement", HKBN_FY25_INTERIM_URL, "FY25中期公告Liquidity and Capital Resources披露2025年2月28日gross debt为11,406百万港元，其中包含426百万港元租赁负债。", "official_interim_liquidity_check", HKBN_2025_H1_SOURCES),
    _official_record("HKBN", "H2 2025", "revenue", 5394.273, "millions HKD", "HKBN FY25 Annual Results Announcement", HKBN_FY25_ANNUAL_RESULTS_URL, "FY25全年Revenue 11,128,542千港元减H1 Revenue 5,734,269千港元，复算H2为5,394,273千港元。", "official_full_year_minus_h1_reconciliation", HKBN_2025_H2_SOURCES),
    _official_record("HKBN", "H2 2025", "net_income", 99.304, "millions HKD", "HKBN FY25 Annual Results Announcement", HKBN_FY25_ANNUAL_RESULTS_URL, "FY25全年Profit for the year 206,864千港元减H1 Profit 107,560千港元，复算H2为99,304千港元。", "official_full_year_minus_h1_reconciliation", HKBN_2025_H2_SOURCES),
    _official_record("HKBN", "H2 2025", "ebitda", 1245.038, "millions HKD", "HKBN FY25 Annual Results Announcement", HKBN_FY25_ANNUAL_RESULTS_URL, "FY25全年EBITDA 2,451,160千港元减H1 EBITDA 1,206,122千港元，复算H2为1,245,038千港元。", "official_full_year_minus_h1_reconciliation", HKBN_2025_H2_SOURCES),
    _official_record("HKBN", "H2 2025", "capital_expenditures", -272.028, "millions HKD", "HKBN FY25 Annual Results Announcement", HKBN_FY25_ANNUAL_RESULTS_URL, "FY25全年Capital expenditure 510,541千港元减H1 238,513千港元，复算H2资本开支为272,028千港元，现金流出口径记为负数。", "official_full_year_minus_h1_aff_reconciliation", HKBN_2025_H2_SOURCES),
    _official_record("HKBN", "H2 2025", "adjusted_funds_flow", 550.884, "millions HKD", "HKBN FY25 Annual Results Announcement", HKBN_FY25_ANNUAL_RESULTS_URL, "FY25全年AFF 677,070千港元减H1 AFF 126,186千港元，复算H2为550,884千港元。该口径为HKBN定义的AFF。", "official_full_year_minus_h1_aff_reconciliation", HKBN_2025_H2_SOURCES),
    _official_record("HKBN", "H2 2025", "cash_and_equivalents", 1192.160, "millions HKD", "HKBN FY25 Annual Results Announcement", HKBN_FY25_ANNUAL_RESULTS_URL, "FY25全年公告资产负债表披露2025年8月31日Cash and cash equivalents为1,192,160千港元；新闻稿摘要披露约1,192百万港元。", "official_annual_balance_sheet_check", HKBN_2025_H2_SOURCES),
    _official_record("HKBN", "H2 2025", "total_assets", 17252.747, "millions HKD", "HKBN FY25 Annual Results Announcement", HKBN_FY25_ANNUAL_RESULTS_URL, "FY25全年公告资产负债表披露非流动资产14,186,225、流动资产3,066,522，合计总资产17,252,747千港元。", "official_annual_balance_sheet_reconciliation", HKBN_2025_H2_SOURCES),
    _official_record("HKBN", "H2 2025", "total_debt", 11416, "millions HKD", "HKBN FY25 Annual Results Announcement", HKBN_FY25_ANNUAL_RESULTS_URL, "FY25全年公告Liquidity and Capital Resources披露2025年8月31日gross debt为11,416百万港元，其中包含392百万港元租赁负债。", "official_annual_liquidity_check", HKBN_2025_H2_SOURCES),
    _official_record("HKBN", "H1 2026", "revenue", 6029.202, "millions HKD", "HKBN FY26 Interim Results Announcement", HKBN_FY26_INTERIM_URL, "FY26中期公告Financial highlights披露Revenue为6,029,202千港元。", "official_interim_statement_check", HKBN_2026_H1_SOURCES),
    _official_record("HKBN", "H1 2026", "net_income", 107.672, "millions HKD", "HKBN FY26 Interim Results Announcement", HKBN_FY26_INTERIM_URL, "FY26中期公告损益表披露Profit for the period attributable to equity shareholders为107,672千港元。", "official_interim_statement_check", HKBN_2026_H1_SOURCES),
    _official_record("HKBN", "H1 2026", "ebitda", 1256.500, "millions HKD", "HKBN FY26 Interim Results Announcement", HKBN_FY26_INTERIM_URL, "FY26中期公告Financial highlights披露EBITDA为1,256,500千港元。", "official_interim_statement_check", HKBN_2026_H1_SOURCES),
    _official_record("HKBN", "H1 2026", "capital_expenditures", -269.744, "millions HKD", "HKBN FY26 Interim Results Announcement", HKBN_FY26_INTERIM_URL, "FY26中期公告EBITDA/AFF reconciliation披露Capital expenditure为269,744千港元，现金流出口径记为负数。", "official_interim_aff_reconciliation_check", HKBN_2026_H1_SOURCES),
    _official_record("HKBN", "H1 2026", "adjusted_funds_flow", 157.078, "millions HKD", "HKBN FY26 Interim Results Announcement", HKBN_FY26_INTERIM_URL, "FY26中期公告Financial highlights披露Adjusted Free Cash Flow为157,078千港元。该口径为HKBN定义的AFF。", "official_interim_aff_check", HKBN_2026_H1_SOURCES),
    _official_record("HKBN", "H1 2026", "cash_and_equivalents", 994.698, "millions HKD", "HKBN FY26 Interim Results Announcement", HKBN_FY26_INTERIM_URL, "FY26中期公告资产负债表披露2026年2月28日Cash and cash equivalents为994,698千港元。", "official_interim_balance_sheet_check", HKBN_2026_H1_SOURCES),
    _official_record("HKBN", "H1 2026", "total_assets", 16851.261, "millions HKD", "HKBN FY26 Interim Results Announcement", HKBN_FY26_INTERIM_URL, "FY26中期公告资产负债表披露非流动资产13,848,053、流动资产3,003,208，合计总资产16,851,261千港元。", "official_interim_balance_sheet_reconciliation", HKBN_2026_H1_SOURCES),
    _official_record("HKBN", "H1 2026", "total_debt", 11271, "millions HKD", "HKBN FY26 Interim Results Announcement", HKBN_FY26_INTERIM_URL, "FY26中期公告Liquidity and Capital Resources披露2026年2月28日gross debt为11,271百万港元，其中包含329百万港元租赁负债。", "official_interim_liquidity_check", HKBN_2026_H1_SOURCES),
    _official_record("HKBN", "H1 2023", "gross_profit", 2134.176, "millions HKD", "HKBN FY23 Interim Results Announcement", HKBN_FY23_INTERIM_URL, "FY23中期损益表披露Revenue 6,707,216千港元、Network costs and costs of sales 4,573,040千港元，复算毛利为2,134,176千港元。", "official_revenue_minus_network_costs_reconciliation", HKBN_2023_H1_SOURCES),
    _official_record("HKBN", "H1 2023", "operating_cash_flow", 916.998, "millions HKD", "HKBN FY23 Interim Report", HKBN_FY23_INTERIM_REPORT_URL, "FY23中期正式报告现金流量表披露Net cash generated from operating activities为916,998千港元。", "official_interim_cash_flow_statement_check", HKBN_2023_H1_SOURCES),
    _official_record("HKBN", "H1 2023", "free_cash_flow", 624.642, "millions HKD", "HKBN FY23 Interim Report", HKBN_FY23_INTERIM_REPORT_URL, "FY23中期正式报告披露经营现金流916,998千港元、购买物业厂房及设备付款292,356千港元，复算普通自由现金流为624,642千港元；区别于HKBN定义的AFF。", "official_operating_cash_flow_minus_ppe_reconciliation", HKBN_2023_H1_SOURCES),
    _official_record("HKBN", "H2 2023", "gross_profit", 2032.981, "millions HKD", "HKBN FY23 Annual Results Announcement", HKBN_FY23_ANNUAL_RESULTS_URL, "FY23全年毛利按Revenue 11,692,176减Network costs and costs of sales 7,525,019为4,167,157千港元；减H1 2,134,176后H2为2,032,981千港元。", "official_full_year_minus_h1_gross_profit_reconciliation", HKBN_2023_H2_SOURCES),
    _official_record("HKBN", "H2 2023", "operating_cash_flow", 1065.881, "millions HKD", "HKBN FY23 Annual Report", HKBN_FY23_ANNUAL_REPORT_URL, "FY23正式年报现金流量表披露全年经营现金流1,982,879千港元；减H1 916,998后H2为1,065,881千港元。", "official_full_year_minus_h1_cash_flow_reconciliation", HKBN_2023_H2_SOURCES),
    _official_record("HKBN", "H2 2023", "free_cash_flow", 868.846, "millions HKD", "HKBN FY23 Annual Report", HKBN_FY23_ANNUAL_REPORT_URL, "FY23全年购买物业厂房及设备付款489,391千港元；减H1 292,356后H2资本性付款197,035千港元，H2普通自由现金流为1,065,881减197,035，即868,846千港元。", "official_operating_cash_flow_minus_ppe_reconciliation", HKBN_2023_H2_SOURCES),
    _official_record("HKBN", "H1 2024", "gross_profit", 2036.943, "millions HKD", "HKBN FY24 Interim Results Announcement", HKBN_FY24_INTERIM_URL, "FY24中期损益表披露Revenue 5,809,091千港元、Network costs and costs of sales 3,772,148千港元，复算毛利为2,036,943千港元。", "official_revenue_minus_network_costs_reconciliation", HKBN_2024_H1_SOURCES),
    _official_record("HKBN", "H1 2024", "operating_cash_flow", 794.290, "millions HKD", "HKBN FY24 Interim Report", HKBN_FY24_INTERIM_REPORT_URL, "FY24中期正式报告现金流量表披露Net cash generated from operating activities为794,290千港元。", "official_interim_cash_flow_statement_check", HKBN_2024_H1_SOURCES),
    _official_record("HKBN", "H1 2024", "free_cash_flow", 598.367, "millions HKD", "HKBN FY24 Interim Report", HKBN_FY24_INTERIM_REPORT_URL, "FY24中期正式报告披露经营现金流794,290千港元、购买物业厂房及设备付款195,923千港元，复算普通自由现金流为598,367千港元。", "official_operating_cash_flow_minus_ppe_reconciliation", HKBN_2024_H1_SOURCES),
    _official_record("HKBN", "H2 2024", "gross_profit", 1952.301, "millions HKD", "HKBN FY24 Annual Results Announcement", HKBN_FY24_ANNUAL_RESULTS_URL, "FY24全年毛利按Revenue 10,650,922减Network costs and costs of sales 6,661,678为3,989,244千港元；减H1 2,036,943后H2为1,952,301千港元。", "official_full_year_minus_h1_gross_profit_reconciliation", HKBN_2024_H2_SOURCES),
    _official_record("HKBN", "H2 2024", "operating_cash_flow", 1264.177, "millions HKD", "HKBN FY24 Annual Report", HKBN_FY24_ANNUAL_REPORT_URL, "FY24正式年报现金流量表披露全年经营现金流2,058,467千港元；减H1 794,290后H2为1,264,177千港元。", "official_full_year_minus_h1_cash_flow_reconciliation", HKBN_2024_H2_SOURCES),
    _official_record("HKBN", "H2 2024", "free_cash_flow", 1097.389, "millions HKD", "HKBN FY24 Annual Report", HKBN_FY24_ANNUAL_REPORT_URL, "FY24全年购买物业厂房及设备付款362,711千港元；减H1 195,923后H2资本性付款166,788千港元，H2普通自由现金流为1,264,177减166,788，即1,097,389千港元。", "official_operating_cash_flow_minus_ppe_reconciliation", HKBN_2024_H2_SOURCES),
    _official_record("HKBN", "H1 2025", "gross_profit", 2014.581, "millions HKD", "HKBN FY25 Interim Results Announcement", HKBN_FY25_INTERIM_URL, "FY25中期损益表披露Revenue 5,734,269千港元、Network costs and costs of sales 3,719,688千港元，复算毛利为2,014,581千港元。", "official_revenue_minus_network_costs_reconciliation", HKBN_2025_H1_SOURCES),
    _official_record("HKBN", "H1 2025", "operating_cash_flow", 853.260, "millions HKD", "HKBN FY25 Interim Report", HKBN_FY25_INTERIM_REPORT_URL, "FY25中期正式报告现金流量表披露Net cash generated from operating activities为853,260千港元。", "official_interim_cash_flow_statement_check", HKBN_2025_H1_SOURCES),
    _official_record("HKBN", "H1 2025", "free_cash_flow", 614.747, "millions HKD", "HKBN FY25 Interim Report", HKBN_FY25_INTERIM_REPORT_URL, "FY25中期正式报告披露经营现金流853,260千港元、购买物业厂房及设备付款238,513千港元，复算普通自由现金流为614,747千港元。", "official_operating_cash_flow_minus_ppe_reconciliation", HKBN_2025_H1_SOURCES),
    _official_record("HKBN", "H1 2025", "operating_income", 479.090, "millions HKD", "HKBN FY25 Interim Results Announcement", HKBN_FY25_INTERIM_URL, "FY25中期损益表披露Revenue 5,734,269、Other net income 5,801、Network costs and costs of sales 3,719,688、Other operating expenses 1,541,292，复算经营利润为479,090千港元。", "official_interim_operating_profit_reconciliation", HKBN_2025_H1_SOURCES),
    _official_record("HKBN", "H1 2025", "operating_margin", 8.355, "percent", "HKBN FY25 Interim Results Announcement", HKBN_FY25_INTERIM_URL, "以H1 2025官方复算经营利润479,090千港元除以Revenue 5,734,269千港元，复算经营利润率为8.355%。", "official_operating_income_divided_by_revenue_reconciliation", HKBN_2025_H1_SOURCES),
    _official_record("HKBN", "H1 2025", "revenue_growth_yoy", -1.288, "percent", "HKBN FY25 Interim Results Announcement", HKBN_FY25_INTERIM_URL, "FY25中期公告披露H1 2025 Revenue 5,734,269千港元、H1 2024 Revenue 5,809,091千港元，复算同比下降1.288%。", "official_current_prior_period_reconciliation", HKBN_2025_H1_SOURCES),
    _official_record("HKBN", "H2 2025", "gross_profit", 2028.344, "millions HKD", "HKBN FY25 Annual Results Announcement", HKBN_FY25_ANNUAL_RESULTS_URL, "FY25全年毛利按Revenue 11,128,542减Network costs and costs of sales 7,085,617为4,042,925千港元；减H1 2,014,581后H2为2,028,344千港元。", "official_full_year_minus_h1_gross_profit_reconciliation", HKBN_2025_H2_SOURCES),
    _official_record("HKBN", "H2 2025", "operating_cash_flow", 1057.578, "millions HKD", "HKBN FY25 Annual Report", HKBN_FY25_ANNUAL_REPORT_URL, "FY25正式年报现金流量表披露全年经营现金流1,910,838千港元；减H1 853,260后H2为1,057,578千港元。", "official_full_year_minus_h1_cash_flow_reconciliation", HKBN_2025_H2_SOURCES),
    _official_record("HKBN", "H2 2025", "free_cash_flow", 802.516, "millions HKD", "HKBN FY25 Annual Report", HKBN_FY25_ANNUAL_REPORT_URL, "FY25全年购买物业厂房及设备付款493,575千港元；减H1 238,513后H2资本性付款255,062千港元，H2普通自由现金流为1,057,578减255,062，即802,516千港元。", "official_operating_cash_flow_minus_ppe_reconciliation", HKBN_2025_H2_SOURCES),
    _official_record("HKBN", "H2 2025", "operating_income", 447.178, "millions HKD", "HKBN FY25 Annual Results Announcement", HKBN_FY25_ANNUAL_RESULTS_URL, "FY25全年按损益表复算经营利润926,268千港元；减H1 2025经营利润479,090千港元，复算H2为447,178千港元。", "official_full_year_minus_h1_operating_profit_reconciliation", HKBN_2025_H2_SOURCES),
    _official_record("HKBN", "H2 2025", "operating_margin", 8.290, "percent", "HKBN FY25 Annual Results Announcement", HKBN_FY25_ANNUAL_RESULTS_URL, "以H2 2025官方复算经营利润447,178千港元除以H2 Revenue 5,394,273千港元，复算经营利润率为8.290%。", "official_operating_income_divided_by_revenue_reconciliation", HKBN_2025_H2_SOURCES),
    _official_record("HKBN", "H2 2025", "revenue_growth_yoy", 11.410, "percent", "HKBN FY25 Annual Results Announcement", HKBN_FY25_ANNUAL_RESULTS_URL, "FY25全年Revenue 11,128,542千港元减H1 5,734,269得H2 2025收入5,394,273千港元；FY24全年10,650,922减H1 5,809,091得H2 2024收入4,841,831千港元，复算同比增长11.410%。", "official_full_year_minus_h1_prior_period_reconciliation", HKBN_2025_H2_SOURCES),
    _official_record("HKBN", "H1 2026", "gross_profit", 2055.306, "millions HKD", "HKBN FY26 Interim Results Announcement", HKBN_FY26_INTERIM_URL, "FY26中期损益表披露Revenue 6,029,202千港元、Network costs and costs of sales 3,973,896千港元，复算毛利为2,055,306千港元。", "official_revenue_minus_network_costs_reconciliation", HKBN_2026_H1_SOURCES),
    _official_record("HKBN", "H1 2026", "operating_cash_flow", 781.218, "millions HKD", "HKBN FY26 Interim Report", HKBN_FY26_INTERIM_REPORT_URL, "FY26中期正式报告现金流量表披露Net cash generated from operating activities为781,218千港元。", "official_interim_cash_flow_statement_check", HKBN_2026_H1_SOURCES),
    _official_record("HKBN", "H1 2026", "free_cash_flow", 531.206, "millions HKD", "HKBN FY26 Interim Report", HKBN_FY26_INTERIM_REPORT_URL, "FY26中期正式报告披露经营现金流781,218千港元、购买物业厂房及设备付款250,012千港元，复算普通自由现金流为531,206千港元。", "official_operating_cash_flow_minus_ppe_reconciliation", HKBN_2026_H1_SOURCES),
    _official_record("HKBN", "H1 2026", "operating_income", 558.899, "millions HKD", "HKBN FY26 Interim Results Announcement", HKBN_FY26_INTERIM_URL, "FY26中期损益表披露Revenue 6,029,202、Other net income 2,149、Network costs and costs of sales 3,973,896、Other operating expenses 1,498,556，复算经营利润为558,899千港元。", "official_interim_operating_profit_reconciliation", HKBN_2026_H1_SOURCES),
    _official_record("HKBN", "H1 2026", "operating_margin", 9.270, "percent", "HKBN FY26 Interim Results Announcement", HKBN_FY26_INTERIM_URL, "以H1 2026官方复算经营利润558,899千港元除以Revenue 6,029,202千港元，复算经营利润率为9.270%。", "official_operating_income_divided_by_revenue_reconciliation", HKBN_2026_H1_SOURCES),
    _official_record("HKBN", "H1 2026", "revenue_growth_yoy", 5.143, "percent", "HKBN FY26 Interim Results Announcement", HKBN_FY26_INTERIM_URL, "FY26中期公告披露H1 2026 Revenue 6,029,202千港元、H1 2025 Revenue 5,734,269千港元，复算同比增长5.143%。", "official_current_prior_period_reconciliation", HKBN_2026_H1_SOURCES),
]


ICABLE_2021_2022_PERIOD_SOURCES = {
    "H1 2021": (ICABLE_2021_INTERIM_RESULTS_URL, "i-CABLE 2021 Interim Results Announcement", ICABLE_2021_H1_SOURCES),
    "H2 2021": (ICABLE_2021_ANNUAL_RESULTS_URL, "i-CABLE 2021 Final Results Announcement", ICABLE_2021_H2_SOURCES),
    "H1 2022": (ICABLE_2022_INTERIM_RESULTS_URL, "i-CABLE 2022 Interim Results Announcement", ICABLE_2022_H1_SOURCES),
    "H2 2022": (ICABLE_2022_ANNUAL_RESULTS_URL, "i-CABLE 2022 Final Results Announcement", ICABLE_2022_H2_SOURCES),
}

ICABLE_2021_2022_VALUES = {
    "H1 2021": {
        "revenue": 493.483,
        "net_income": -175.216,
        "operating_income": -154.061,
        "operating_margin": -31.219,
        "revenue_growth_yoy": -5.984,
        "ebitda": -43.185,
        "capital_expenditures": -49.691,
        "cash_and_equivalents": 195.227,
        "total_assets": 1663.800,
        "total_debt": 893.019,
        "gross_profit": -19.203,
        "operating_cash_flow": -41.101,
        "free_cash_flow": -90.792,
    },
    "H2 2021": {
        "revenue": 495.714,
        "net_income": -188.436,
        "operating_income": -154.568,
        "operating_margin": -31.181,
        "revenue_growth_yoy": -8.890,
        "ebitda": -46.412,
        "capital_expenditures": -57.421,
        "cash_and_equivalents": 70.162,
        "total_assets": 1485.592,
        "total_debt": 892.051,
        "gross_profit": -17.165,
        "operating_cash_flow": -17.702,
        "free_cash_flow": -75.123,
    },
    "H1 2022": {
        "revenue": 431.430,
        "net_income": -225.874,
        "operating_income": -148.628,
        "operating_margin": -34.450,
        "revenue_growth_yoy": -12.574,
        "ebitda": -41.633,
        "capital_expenditures": -50.305,
        "cash_and_equivalents": 62.596,
        "total_assets": 1379.712,
        "total_debt": 1049.506,
        "gross_profit": -16.990,
        "operating_cash_flow": -61.325,
        "free_cash_flow": -111.630,
    },
    "H2 2022": {
        "revenue": 463.769,
        "net_income": -659.844,
        "operating_income": -439.557,
        "operating_margin": -94.779,
        "revenue_growth_yoy": -6.444,
        "ebitda": -94.290,
        "capital_expenditures": -63.882,
        "cash_and_equivalents": 41.587,
        "total_assets": 879.494,
        "total_debt": 1182.153,
        "gross_profit": -224.604,
        "operating_cash_flow": -27.585,
        "free_cash_flow": -91.467,
    },
}

ICABLE_2021_2022_UNITS = {
    "operating_margin": "percent",
    "revenue_growth_yoy": "percent",
}

ICABLE_2021_2022_METHODS = {
    "revenue": "official_interim_or_full_year_minus_h1_reconciliation",
    "net_income": "official_interim_or_full_year_minus_h1_reconciliation",
    "operating_income": "official_interim_or_full_year_minus_h1_reconciliation",
    "operating_margin": "official_operating_income_divided_by_revenue_reconciliation",
    "revenue_growth_yoy": "official_current_prior_period_reconciliation",
    "ebitda": "official_segment_before_depreciation_amortisation_impairment_check",
    "capital_expenditures": "official_interim_or_full_year_minus_h1_capex_reconciliation",
    "cash_and_equivalents": "official_balance_sheet_check",
    "total_assets": "official_balance_sheet_check",
    "total_debt": "official_debt_reconciliation",
    "gross_profit": "official_revenue_minus_cost_of_services_reconciliation",
    "operating_cash_flow": "official_cash_flow_statement_check",
    "free_cash_flow": "official_operating_cash_flow_minus_ppe_reconciliation",
}

ICABLE_2021_2022_EVIDENCE = {
    "H1 2021": {
        "revenue": "2021中期公告和中报披露H1 2021 Revenue 493,483千港元。",
        "net_income": "2021中期公告和中报披露H1 2021 Loss for the period 175,216千港元。",
        "operating_income": "2021中期公告和中报披露H1 2021 Loss from operations 154,061千港元。",
        "operating_margin": "以H1 2021官方Loss from operations -154,061千港元除以Revenue 493,483千港元，复算经营利润率为-31.219%。",
        "revenue_growth_yoy": "2021中期公告披露H1 2021 Revenue 493,483千港元、H1 2020 Revenue 524,893千港元，复算同比下降5.984%。",
        "ebitda": "2021中期公告披露H1 2021 Loss from operations before depreciation and amortisation of other intangible assets为43,185千港元亏损。",
        "capital_expenditures": "2021中期报告现金流量表披露H1 2021 Purchase of property, plant and equipment为49,691千港元，现金流出口径记为负数。",
        "cash_and_equivalents": "2021中期公告和中报资产负债表披露2021年6月30日Cash and bank balances 195,227千港元。",
        "total_assets": "2021中期公告和中报披露2021年6月30日Total assets 1,663,800千港元。",
        "total_debt": "2021中期报告披露可转债510,382千港元、计息借款295,000千港元、租赁负债48,084+39,553千港元，合计893,019千港元。",
        "gross_profit": "2021中期报告披露Revenue 493,483千港元，Programming costs 297,541千港元、Network expenses 146,562千港元、Cost of sales 68,583千港元，复算毛利-19,203千港元。",
        "operating_cash_flow": "2021中期报告现金流量表披露Net cash used in operating activities为41,101千港元。",
        "free_cash_flow": "2021中期报告披露经营现金流净流出41,101千港元、购买PPE付款49,691千港元，复算普通自由现金流为-90,792千港元。",
    },
    "H2 2021": {
        "revenue": "2021全年Revenue 989,197千港元减H1 493,483千港元，复算H2 2021 Revenue 495,714千港元。",
        "net_income": "2021全年Loss for the year 363,652千港元减H1 Loss 175,216千港元，复算H2亏损188,436千港元。",
        "operating_income": "2021全年Loss from operations 308,629千港元减H1 154,061千港元，复算H2经营亏损154,568千港元。",
        "operating_margin": "以H2 2021官方复算Loss from operations -154,568千港元除以H2 Revenue 495,714千港元，复算经营利润率为-31.181%。",
        "revenue_growth_yoy": "2021全年Revenue 989,197千港元、2020全年1,068,977千港元，扣除H1比较数后复算H2 2021收入同比下降8.890%。",
        "ebitda": "2021全年Loss from operations before depreciation and amortisation 89,597千港元亏损减H1 43,185千港元亏损，复算H2为46,412千港元亏损。",
        "capital_expenditures": "2021年报现金流量表披露FY2021购买PPE 107,112千港元，减H1 49,691千港元，复算H2为57,421千港元；现金流出口径记为负数。",
        "cash_and_equivalents": "2021全年公告和年报资产负债表披露2021年12月31日Cash and bank balances 70,162千港元。",
        "total_assets": "2021全年公告和年报披露2021年12月31日Total assets 1,485,592千港元。",
        "total_debt": "2021年报披露可转债521,929千港元、计息借款295,000千港元、租赁负债36,192+38,930千港元，合计892,051千港元。",
        "gross_profit": "2021年报披露FY2021三项服务成本合计1,025,565千港元，全年毛利-36,368千港元；减H1毛利-19,203千港元，复算H2为-17,165千港元。",
        "operating_cash_flow": "2021年报现金流量表披露FY2021经营现金流净流出58,803千港元，减H1净流出41,101千港元，复算H2净流出17,702千港元。",
        "free_cash_flow": "2021年报披露FY2021经营现金流净流出58,803千港元、PPE付款107,112千港元；扣除H1后复算H2普通自由现金流为-75,123千港元。",
    },
    "H1 2022": {
        "revenue": "2022中期公告和中报披露H1 2022 Revenue 431,430千港元。",
        "net_income": "2022中期公告和中报披露H1 2022 Loss for the period 225,874千港元。",
        "operating_income": "2022中期公告和中报披露H1 2022 Loss from operations 148,628千港元。",
        "operating_margin": "以H1 2022官方Loss from operations -148,628千港元除以Revenue 431,430千港元，复算经营利润率为-34.450%。",
        "revenue_growth_yoy": "2022中期公告披露H1 2022 Revenue 431,430千港元、H1 2021 Revenue 493,483千港元，复算同比下降12.574%。",
        "ebitda": "2022中期公告披露H1 2022 Loss from operations before depreciation and amortisation of other intangible assets为41,633千港元亏损。",
        "capital_expenditures": "2022中期报告现金流量表披露H1 2022 Purchase of property, plant and equipment为50,305千港元，现金流出口径记为负数。",
        "cash_and_equivalents": "2022中期公告和中报资产负债表披露2022年6月30日Cash and bank balances 62,596千港元。",
        "total_assets": "2022中期公告和中报披露2022年6月30日Total assets 1,379,712千港元。",
        "total_debt": "2022中期报告披露可转债533,609千港元、计息借款166,035+295,000千港元、租赁负债18,074+36,788千港元，合计1,049,506千港元。",
        "gross_profit": "2022中期报告披露Revenue 431,430千港元，Programming costs 239,779千港元、Network expenses 149,459千港元、Cost of sales 59,182千港元，复算毛利-16,990千港元。",
        "operating_cash_flow": "2022中期报告现金流量表披露Net cash used in operating activities为61,325千港元。",
        "free_cash_flow": "2022中期报告披露经营现金流净流出61,325千港元、购买PPE付款50,305千港元，复算普通自由现金流为-111,630千港元。",
    },
    "H2 2022": {
        "revenue": "2022全年Revenue 895,199千港元减H1 431,430千港元，复算H2 2022 Revenue 463,769千港元。",
        "net_income": "2022全年Loss for the year 885,718千港元减H1 Loss 225,874千港元，复算H2亏损659,844千港元。",
        "operating_income": "2022全年Loss from operations 588,185千港元减H1 148,628千港元，复算H2经营亏损439,557千港元。",
        "operating_margin": "以H2 2022官方复算Loss from operations -439,557千港元除以H2 Revenue 463,769千港元，复算经营利润率为-94.779%。",
        "revenue_growth_yoy": "2022全年Revenue 895,199千港元、2021全年989,197千港元；扣除H1 2022和H1 2021后复算H2 2022收入同比下降6.444%。",
        "ebitda": "2022全年Loss from operations before depreciation, amortisation and impairment losses 135,923千港元亏损减H1 41,633千港元亏损，复算H2为94,290千港元亏损。",
        "capital_expenditures": "2022年报现金流量表披露FY2022购买PPE 114,187千港元，减H1 50,305千港元，复算H2为63,882千港元；现金流出口径记为负数。",
        "cash_and_equivalents": "2022全年公告和年报资产负债表披露2022年12月31日Cash and bank balances 41,587千港元。",
        "total_assets": "2022全年公告和年报披露2022年12月31日Total assets 879,494千港元。",
        "total_debt": "2022年报披露可转债546,040千港元、计息借款296,035+295,000千港元、租赁负债7,820+37,258千港元，合计1,182,153千港元。",
        "gross_profit": "2022年报披露FY2022三项服务成本合计1,136,793千港元，全年毛利-241,594千港元；减H1毛利-16,990千港元，复算H2为-224,604千港元。",
        "operating_cash_flow": "2022年报现金流量表披露FY2022经营现金流净流出88,910千港元，减H1净流出61,325千港元，复算H2净流出27,585千港元。",
        "free_cash_flow": "2022年报披露FY2022经营现金流净流出88,910千港元、PPE付款114,187千港元；扣除H1后复算H2普通自由现金流为-91,467千港元。",
    },
}

ICABLE_2021_2022_OFFICIAL_VERIFICATIONS = [
    _official_record(
        "i-CABLE",
        period,
        metric_key,
        value,
        ICABLE_2021_2022_UNITS.get(metric_key, "millions HKD"),
        source_label,
        source_url,
        ICABLE_2021_2022_EVIDENCE[period][metric_key],
        ICABLE_2021_2022_METHODS[metric_key],
        sources,
    )
    for period, metrics in ICABLE_2021_2022_VALUES.items()
    for metric_key, value in metrics.items()
    for source_url, source_label, sources in [ICABLE_2021_2022_PERIOD_SOURCES[period]]
]


ICABLE_OFFICIAL_VERIFICATIONS = [
    *ICABLE_2016_2020_OFFICIAL_VERIFICATIONS,
    *ICABLE_2021_2022_OFFICIAL_VERIFICATIONS,
    _official_record(
        "i-CABLE",
        "H1 2023",
        "revenue",
        263.393,
        "millions HKD",
        "i-CABLE 2023 Interim Results Announcement",
        ICABLE_2023_INTERIM_RESULTS_URL,
        "2023中期公告Financial Highlights和损益表均披露Revenue为263,393千港元。",
        "official_interim_statement_check",
        ICABLE_2023_H1_SOURCES,
    ),
    _official_record(
        "i-CABLE",
        "H1 2023",
        "net_income",
        -196.986,
        "millions HKD",
        "i-CABLE 2023 Interim Results Announcement",
        ICABLE_2023_INTERIM_RESULTS_URL,
        "2023中期公告Financial Highlights和损益表均披露Loss for the period为196,986千港元。",
        "official_interim_statement_check",
        ICABLE_2023_H1_SOURCES,
    ),
    _official_record(
        "i-CABLE",
        "H1 2023",
        "operating_income",
        -110.060,
        "millions HKD",
        "i-CABLE 2023 Interim Results Announcement",
        ICABLE_2023_INTERIM_RESULTS_URL,
        "2023中期公告Financial Highlights和损益表披露Loss from operations为110,060千港元。",
        "official_interim_statement_check",
        ICABLE_2023_H1_SOURCES,
    ),
    _official_record(
        "i-CABLE",
        "H1 2023",
        "operating_margin",
        -41.785,
        "percent",
        "i-CABLE 2023 Interim Results Announcement",
        ICABLE_2023_INTERIM_RESULTS_URL,
        "以官方Loss from operations -110,060千港元除以Revenue 263,393千港元，复算经营利润率为-41.785%。",
        "official_operating_income_divided_by_revenue_reconciliation",
        ICABLE_2023_H1_SOURCES,
    ),
    _official_record(
        "i-CABLE",
        "H1 2023",
        "revenue_growth_yoy",
        0.645,
        "percent",
        "i-CABLE 2023 Interim Results Announcement",
        ICABLE_2023_INTERIM_RESULTS_URL,
        "2023中期公告披露H1 2023 Revenue 263,393千港元、H1 2022 Revenue 261,704千港元，复算同比增长0.645%。",
        "official_current_prior_period_reconciliation",
        ICABLE_2023_H1_SOURCES,
    ),
    _official_record(
        "i-CABLE",
        "H1 2023",
        "ebitda",
        -44.063,
        "millions HKD",
        "i-CABLE 2023 Interim Results Announcement",
        ICABLE_2023_INTERIM_RESULTS_URL,
        "2023中期公告分部表披露Reportable segment loss/profit before depreciation and amortisation of other intangible assets合计为44,063千港元亏损；该口径作为官方EBITDA近似口径，需说明与标准化表定义可能不同。",
        "official_segment_before_depreciation_amortisation_impairment_check",
        ICABLE_2023_H1_SOURCES,
    ),
    _official_record(
        "i-CABLE",
        "H1 2023",
        "capital_expenditures",
        -34.242,
        "millions HKD",
        "i-CABLE 2023 Interim Results Announcement",
        ICABLE_2023_INTERIM_RESULTS_URL,
        "2023中期公告Note 7披露additions to property, plant and equipment为34,242千港元；现金流出口径记为负数。",
        "official_interim_capex_note_check",
        ICABLE_2023_H1_SOURCES,
    ),
    _official_record(
        "i-CABLE",
        "H1 2023",
        "cash_and_equivalents",
        68.504,
        "millions HKD",
        "i-CABLE 2023 Interim Results Announcement",
        ICABLE_2023_INTERIM_RESULTS_URL,
        "2023中期公告资产负债表披露2023年6月30日Cash and bank balances为68,504千港元。",
        "official_interim_balance_sheet_check",
        ICABLE_2023_H1_SOURCES,
    ),
    _official_record(
        "i-CABLE",
        "H1 2023",
        "total_assets",
        897.556,
        "millions HKD",
        "i-CABLE 2023 Interim Results Announcement",
        ICABLE_2023_INTERIM_RESULTS_URL,
        "2023中期公告Financial Highlights和资产负债表均披露2023年6月30日Total assets为897,556千港元。",
        "official_interim_balance_sheet_check",
        ICABLE_2023_H1_SOURCES,
    ),
    _official_record(
        "i-CABLE",
        "H1 2023",
        "total_debt",
        1418.562,
        "millions HKD",
        "i-CABLE 2023 Interim Results Announcement",
        ICABLE_2023_INTERIM_RESULTS_URL,
        "2023中期公告资产负债表披露可转债558,623千港元、计息借款536,035+295,000千港元、租赁负债7,473+21,431千港元，合计总债务1,418,562千港元。",
        "official_interim_debt_reconciliation",
        ICABLE_2023_H1_SOURCES,
    ),
    _official_record(
        "i-CABLE",
        "H2 2023",
        "revenue",
        334.505,
        "millions HKD",
        "i-CABLE 2023 Final Results Announcement",
        ICABLE_2023_ANNUAL_RESULTS_URL,
        "2023全年Revenue 597,898千港元减H1 Revenue 263,393千港元，复算H2为334,505千港元。",
        "official_full_year_minus_h1_reconciliation",
        ICABLE_2023_H2_SOURCES,
    ),
    _official_record(
        "i-CABLE",
        "H2 2023",
        "net_income",
        -392.288,
        "millions HKD",
        "i-CABLE 2023 Final Results Announcement",
        ICABLE_2023_ANNUAL_RESULTS_URL,
        "2023全年Loss for the year 589,274千港元减H1 Loss for the period 196,986千港元，复算H2亏损为392,288千港元。",
        "official_full_year_minus_h1_reconciliation",
        ICABLE_2023_H2_SOURCES,
    ),
    _official_record(
        "i-CABLE",
        "H2 2023",
        "operating_income",
        -317.706,
        "millions HKD",
        "i-CABLE 2023 Final Results Announcement",
        ICABLE_2023_ANNUAL_RESULTS_URL,
        "2023全年Loss from operations 427,766千港元减H1 Loss from operations 110,060千港元，复算H2经营亏损为317,706千港元。",
        "official_full_year_minus_h1_reconciliation",
        ICABLE_2023_H2_SOURCES,
    ),
    _official_record(
        "i-CABLE",
        "H2 2023",
        "operating_margin",
        -94.978,
        "percent",
        "i-CABLE 2023 Final Results Announcement",
        ICABLE_2023_ANNUAL_RESULTS_URL,
        "以H2官方复算Loss from operations -317,706千港元除以H2 Revenue 334,505千港元，复算经营利润率为-94.978%。",
        "official_operating_income_divided_by_revenue_reconciliation",
        ICABLE_2023_H2_SOURCES,
    ),
    _official_record(
        "i-CABLE",
        "H2 2023",
        "revenue_growth_yoy",
        11.098,
        "percent",
        "i-CABLE 2023 Final Results Announcement",
        ICABLE_2023_ANNUAL_RESULTS_URL,
        "2023全年Revenue 597,898千港元、2022全年562,794千港元；扣除H1 2023 263,393千港元和H1 2022 261,704千港元，复算H2 2023收入334,505千港元、H2 2022收入301,090千港元，同比增长约11.098%。",
        "official_full_year_minus_h1_prior_period_reconciliation",
        ICABLE_2023_H2_SOURCES,
    ),
    _official_record(
        "i-CABLE",
        "H2 2023",
        "ebitda",
        -152.318,
        "millions HKD",
        "i-CABLE 2023 Final Results Announcement",
        ICABLE_2023_ANNUAL_RESULTS_URL,
        "2023全年分部表披露Reportable segment loss before depreciation, amortisation and impairment losses合计为196,381千港元亏损；减H1同口径44,063千港元亏损，复算H2为152,318千港元亏损。该口径作为官方EBITDA近似口径，需说明与标准化表定义可能不同。",
        "official_full_year_minus_h1_segment_reconciliation",
        ICABLE_2023_H2_SOURCES,
    ),
    _official_record(
        "i-CABLE",
        "H2 2023",
        "capital_expenditures",
        -32.674,
        "millions HKD",
        "i-CABLE 2023 Final Results Announcement",
        ICABLE_2023_ANNUAL_RESULTS_URL,
        "2023全年Note 7披露additions to property, plant and equipment 66,916千港元，减H1 additions 34,242千港元，复算H2为32,674千港元；现金流出口径记为负数。",
        "official_full_year_minus_h1_capex_reconciliation",
        ICABLE_2023_H2_SOURCES,
    ),
    _official_record(
        "i-CABLE",
        "H2 2023",
        "cash_and_equivalents",
        28.919,
        "millions HKD",
        "i-CABLE 2023 Final Results Announcement",
        ICABLE_2023_ANNUAL_RESULTS_URL,
        "2023全年公告合并财务状况表披露2023年12月31日Cash and bank balances为28,919千港元。",
        "official_annual_balance_sheet_check",
        ICABLE_2023_H2_SOURCES,
    ),
    _official_record(
        "i-CABLE",
        "H2 2023",
        "total_assets",
        945.159,
        "millions HKD",
        "i-CABLE 2023 Final Results Announcement",
        ICABLE_2023_ANNUAL_RESULTS_URL,
        "2023全年公告Financial Highlights和合并财务状况表均披露2023年12月31日Total assets为945,159千港元。",
        "official_annual_balance_sheet_check",
        ICABLE_2023_H2_SOURCES,
    ),
    _official_record(
        "i-CABLE",
        "H2 2023",
        "total_debt",
        1843.024,
        "millions HKD",
        "i-CABLE 2023 Final Results Announcement",
        ICABLE_2023_ANNUAL_RESULTS_URL,
        "2023全年公告披露可转债572,005千港元、计息借款746,035+295,000千港元、租赁负债225,169+4,815千港元，合计总债务1,843,024千港元。",
        "official_annual_debt_reconciliation",
        ICABLE_2023_H2_SOURCES,
    ),
    _official_record(
        "i-CABLE",
        "H1 2024",
        "revenue",
        277.170,
        "millions HKD",
        "i-CABLE 2025 Interim Results Announcement",
        ICABLE_2025_INTERIM_RESULTS_URL,
        "2025中期公告H1 2024比较栏披露Revenue为277,170千港元。",
        "official_prior_period_comparative_statement_check",
        ICABLE_2024_H1_COMPARATIVE_SOURCES,
    ),
    _official_record(
        "i-CABLE",
        "H1 2024",
        "net_income",
        -254.929,
        "millions HKD",
        "i-CABLE 2025 Interim Results Announcement",
        ICABLE_2025_INTERIM_RESULTS_URL,
        "2025中期公告H1 2024比较栏披露Loss for the period为254,929千港元。",
        "official_prior_period_comparative_statement_check",
        ICABLE_2024_H1_COMPARATIVE_SOURCES,
    ),
    _official_record(
        "i-CABLE",
        "H1 2024",
        "operating_income",
        -188.689,
        "millions HKD",
        "i-CABLE 2025 Interim Results Announcement",
        ICABLE_2025_INTERIM_RESULTS_URL,
        "2025中期公告H1 2024比较栏披露Loss from operations为188,689千港元。",
        "official_prior_period_comparative_statement_check",
        ICABLE_2024_H1_COMPARATIVE_SOURCES,
    ),
    _official_record(
        "i-CABLE",
        "H1 2024",
        "operating_margin",
        -68.077,
        "percent",
        "i-CABLE 2025 Interim Results Announcement",
        ICABLE_2025_INTERIM_RESULTS_URL,
        "以H1 2024比较栏Loss from operations -188,689千港元除以Revenue 277,170千港元，复算经营利润率为-68.077%。",
        "official_operating_income_divided_by_revenue_reconciliation",
        ICABLE_2024_H1_COMPARATIVE_SOURCES,
    ),
    _official_record(
        "i-CABLE",
        "H1 2024",
        "ebitda",
        -115.018,
        "millions HKD",
        "i-CABLE 2025 Interim Results Announcement",
        ICABLE_2025_INTERIM_RESULTS_URL,
        "2025中期公告H1 2024比较栏分部表披露Reportable segment loss before depreciation, amortisation of other intangible assets and impairment losses合计为115,018千港元亏损；该口径作为官方EBITDA近似口径，需说明与标准化表定义可能不同。",
        "official_prior_period_segment_before_depreciation_amortisation_impairment_check",
        ICABLE_2024_H1_COMPARATIVE_SOURCES,
    ),
    _official_record(
        "i-CABLE",
        "H1 2024",
        "capital_expenditures",
        -20.945,
        "millions HKD",
        "i-CABLE 2025 Interim Results Announcement",
        ICABLE_2025_INTERIM_RESULTS_URL,
        "2025中期公告H1 2024比较栏Note 7披露additions to property, plant and equipment为20,945千港元；现金流出口径记为负数。",
        "official_prior_period_capex_note_check",
        ICABLE_2024_H1_COMPARATIVE_SOURCES,
    ),
    _official_record(
        "i-CABLE",
        "H2 2024",
        "revenue",
        307.319,
        "millions HKD",
        "i-CABLE 2025 Final Results Announcement",
        ICABLE_2025_ANNUAL_RESULTS_URL,
        "2025全年公告FY2024比较栏Revenue 584,489千港元减2025中期公告H1 2024比较栏Revenue 277,170千港元，复算H2 2024为307,319千港元。",
        "official_full_year_minus_h1_prior_period_reconciliation",
        ICABLE_2024_H2_COMPARATIVE_SOURCES,
    ),
    _official_record(
        "i-CABLE",
        "H2 2024",
        "net_income",
        -298.409,
        "millions HKD",
        "i-CABLE 2025 Final Results Announcement",
        ICABLE_2025_ANNUAL_RESULTS_URL,
        "2025全年公告FY2024比较栏Loss for the year 553,338千港元减H1 2024比较栏Loss for the period 254,929千港元，复算H2 2024亏损为298,409千港元。",
        "official_full_year_minus_h1_prior_period_reconciliation",
        ICABLE_2024_H2_COMPARATIVE_SOURCES,
    ),
    _official_record(
        "i-CABLE",
        "H2 2024",
        "operating_income",
        -221.024,
        "millions HKD",
        "i-CABLE 2025 Final Results Announcement",
        ICABLE_2025_ANNUAL_RESULTS_URL,
        "2025全年公告FY2024比较栏Loss from operations 409,713千港元减H1 2024比较栏Loss from operations 188,689千港元，复算H2 2024经营亏损为221,024千港元。",
        "official_full_year_minus_h1_prior_period_reconciliation",
        ICABLE_2024_H2_COMPARATIVE_SOURCES,
    ),
    _official_record(
        "i-CABLE",
        "H2 2024",
        "operating_margin",
        -71.920,
        "percent",
        "i-CABLE 2025 Final Results Announcement",
        ICABLE_2025_ANNUAL_RESULTS_URL,
        "以H2 2024官方复算Loss from operations -221,024千港元除以H2 Revenue 307,319千港元，复算经营利润率为-71.920%。",
        "official_operating_income_divided_by_revenue_reconciliation",
        ICABLE_2024_H2_COMPARATIVE_SOURCES,
    ),
    _official_record(
        "i-CABLE",
        "H2 2024",
        "ebitda",
        -93.292,
        "millions HKD",
        "i-CABLE 2025 Final Results Announcement",
        ICABLE_2025_ANNUAL_RESULTS_URL,
        "2025全年公告FY2024比较栏分部扣除折旧摊销及减值前亏损208,310千港元，减H1 2024同口径115,018千港元，复算H2为93,292千港元亏损。该口径作为官方EBITDA近似口径，需说明与标准化表定义可能不同。",
        "official_full_year_minus_h1_prior_period_segment_reconciliation",
        ICABLE_2024_H2_COMPARATIVE_SOURCES,
    ),
    _official_record(
        "i-CABLE",
        "H2 2024",
        "capital_expenditures",
        -33.055,
        "millions HKD",
        "i-CABLE 2025 Final Results Announcement",
        ICABLE_2025_ANNUAL_RESULTS_URL,
        "2025全年公告比较栏披露2024年资本开支约54百万港元；减H1 2024 additions to PPE 20,945千港元，复算H2约33.055百万港元；现金流出口径记为负数。",
        "official_full_year_minus_h1_approx_capex_reconciliation",
        ICABLE_2024_H2_COMPARATIVE_SOURCES,
    ),
    _official_record(
        "i-CABLE",
        "H2 2024",
        "cash_and_equivalents",
        53.771,
        "millions HKD",
        "i-CABLE 2025 Final Results Announcement",
        ICABLE_2025_ANNUAL_RESULTS_URL,
        "2025全年公告合并财务状况表2024年12月31日比较栏披露Cash and bank balances为53,771千港元。",
        "official_prior_year_balance_sheet_comparative_check",
        ICABLE_2024_H2_COMPARATIVE_SOURCES,
    ),
    _official_record(
        "i-CABLE",
        "H2 2024",
        "total_assets",
        882.525,
        "millions HKD",
        "i-CABLE 2025 Final Results Announcement",
        ICABLE_2025_ANNUAL_RESULTS_URL,
        "2025全年公告Financial Highlights和合并财务状况表2024年12月31日比较栏均披露Total assets为882,525千港元。",
        "official_prior_year_balance_sheet_comparative_check",
        ICABLE_2024_H2_COMPARATIVE_SOURCES,
    ),
    _official_record(
        "i-CABLE",
        "H2 2024",
        "total_debt",
        2276.834,
        "millions HKD",
        "i-CABLE 2025 Final Results Announcement",
        ICABLE_2025_ANNUAL_RESULTS_URL,
        "2025全年公告2024年12月31日比较栏披露可转债600,064千港元、非流动计息借款866,035千港元、流动计息借款525,000千港元、租赁负债249,468+36,267千港元，合计总债务2,276,834千港元。",
        "official_prior_year_debt_reconciliation",
        ICABLE_2024_H2_COMPARATIVE_SOURCES,
    ),
    _official_record(
        "i-CABLE",
        "H1 2025",
        "revenue",
        277.511,
        "millions HKD",
        "i-CABLE 2025 Interim Results Announcement",
        ICABLE_2025_INTERIM_RESULTS_URL,
        "2025中期公告Financial Highlights和损益表均披露Revenue为277,511千港元。",
        "official_interim_statement_check",
        ICABLE_2025_H1_SOURCES,
    ),
    _official_record(
        "i-CABLE",
        "H1 2025",
        "net_income",
        -216.816,
        "millions HKD",
        "i-CABLE 2025 Interim Results Announcement",
        ICABLE_2025_INTERIM_RESULTS_URL,
        "2025中期公告Financial Highlights和损益表均披露Loss for the period为216,816千港元。",
        "official_interim_statement_check",
        ICABLE_2025_H1_SOURCES,
    ),
    _official_record(
        "i-CABLE",
        "H1 2025",
        "operating_income",
        -156.894,
        "millions HKD",
        "i-CABLE 2025 Interim Results Announcement",
        ICABLE_2025_INTERIM_RESULTS_URL,
        "2025中期公告Financial Highlights和损益表披露Loss from operations为156,894千港元。",
        "official_interim_statement_check",
        ICABLE_2025_H1_SOURCES,
    ),
    _official_record(
        "i-CABLE",
        "H1 2025",
        "operating_margin",
        -56.536,
        "percent",
        "i-CABLE 2025 Interim Results Announcement",
        ICABLE_2025_INTERIM_RESULTS_URL,
        "以官方Loss from operations -156,894千港元除以Revenue 277,511千港元，复算经营利润率为-56.536%。",
        "official_operating_income_divided_by_revenue_reconciliation",
        ICABLE_2025_H1_SOURCES,
    ),
    _official_record(
        "i-CABLE",
        "H1 2025",
        "revenue_growth_yoy",
        0.123,
        "percent",
        "i-CABLE 2025 Interim Results Announcement",
        ICABLE_2025_INTERIM_RESULTS_URL,
        "2025中期公告披露H1 2025 Revenue 277,511千港元、H1 2024 Revenue 277,170千港元；复算同比增长约0.123%。",
        "official_current_prior_period_reconciliation",
        ICABLE_2025_H1_SOURCES,
    ),
    _official_record(
        "i-CABLE",
        "H1 2025",
        "ebitda",
        -68.566,
        "millions HKD",
        "i-CABLE 2025 Interim Results Announcement",
        ICABLE_2025_INTERIM_RESULTS_URL,
        "2025中期公告分部表披露Reportable segment loss before depreciation, amortisation of other intangible assets and impairment losses合计为68,566千港元亏损；该口径作为官方EBITDA近似口径，需说明与标准化表定义可能不同。",
        "official_segment_before_depreciation_amortisation_impairment_check",
        ICABLE_2025_H1_SOURCES,
    ),
    _official_record(
        "i-CABLE",
        "H1 2025",
        "capital_expenditures",
        -27.234,
        "millions HKD",
        "i-CABLE 2025 Interim Results Announcement",
        ICABLE_2025_INTERIM_RESULTS_URL,
        "2025中期公告Note 7披露additions to property, plant and equipment为27,234千港元；现金流出口径记为负数。",
        "official_interim_capex_note_check",
        ICABLE_2025_H1_SOURCES,
    ),
    _official_record(
        "i-CABLE",
        "H1 2025",
        "cash_and_equivalents",
        71.889,
        "millions HKD",
        "i-CABLE 2025 Interim Results Announcement",
        ICABLE_2025_INTERIM_RESULTS_URL,
        "2025中期公告资产负债表披露2025年6月30日Cash and bank balances为71,889千港元。",
        "official_interim_balance_sheet_check",
        ICABLE_2025_H1_SOURCES,
    ),
    _official_record(
        "i-CABLE",
        "H1 2025",
        "total_assets",
        851.757,
        "millions HKD",
        "i-CABLE 2025 Interim Results Announcement",
        ICABLE_2025_INTERIM_RESULTS_URL,
        "2025中期公告Financial Highlights和资产负债表均披露2025年6月30日Total assets为851,757千港元。",
        "official_interim_balance_sheet_check",
        ICABLE_2025_H1_SOURCES,
    ),
    _official_record(
        "i-CABLE",
        "H1 2025",
        "total_debt",
        2466.722,
        "millions HKD",
        "i-CABLE 2025 Interim Results Announcement",
        ICABLE_2025_INTERIM_RESULTS_URL,
        "2025中期公告资产负债表披露可转债614,669千港元、计息借款1,044,145+535,000千港元、租赁负债226,971+45,937千港元，合计总债务2,466,722千港元。",
        "official_interim_debt_reconciliation",
        ICABLE_2025_H1_SOURCES,
    ),
    _official_record(
        "i-CABLE",
        "H2 2025",
        "revenue",
        261.228,
        "millions HKD",
        "i-CABLE 2025 Final Results Announcement",
        ICABLE_2025_ANNUAL_RESULTS_URL,
        "2025全年Revenue 538,739千港元减H1 Revenue 277,511千港元，复算H2为261,228千港元。",
        "official_full_year_minus_h1_reconciliation",
        ICABLE_2025_H2_SOURCES,
    ),
    _official_record(
        "i-CABLE",
        "H2 2025",
        "net_income",
        -273.162,
        "millions HKD",
        "i-CABLE 2025 Final Results Announcement",
        ICABLE_2025_ANNUAL_RESULTS_URL,
        "2025全年Loss for the year 489,978千港元减H1 Loss for the period 216,816千港元，复算H2亏损为273,162千港元。",
        "official_full_year_minus_h1_reconciliation",
        ICABLE_2025_H2_SOURCES,
    ),
    _official_record(
        "i-CABLE",
        "H2 2025",
        "operating_income",
        -203.407,
        "millions HKD",
        "i-CABLE 2025 Final Results Announcement",
        ICABLE_2025_ANNUAL_RESULTS_URL,
        "2025全年Loss from operations 360,301千港元减H1 Loss from operations 156,894千港元，复算H2经营亏损为203,407千港元。",
        "official_full_year_minus_h1_reconciliation",
        ICABLE_2025_H2_SOURCES,
    ),
    _official_record(
        "i-CABLE",
        "H2 2025",
        "operating_margin",
        -77.865,
        "percent",
        "i-CABLE 2025 Final Results Announcement",
        ICABLE_2025_ANNUAL_RESULTS_URL,
        "以H2官方复算Loss from operations -203,407千港元除以H2 Revenue 261,228千港元，复算经营利润率为-77.865%。",
        "official_operating_income_divided_by_revenue_reconciliation",
        ICABLE_2025_H2_SOURCES,
    ),
    _official_record(
        "i-CABLE",
        "H2 2025",
        "revenue_growth_yoy",
        -15.012,
        "percent",
        "i-CABLE 2025 Final Results Announcement",
        ICABLE_2025_ANNUAL_RESULTS_URL,
        "2025全年Revenue 538,739千港元、2024全年584,489千港元；扣除H1 2025 277,511千港元和H1 2024 277,170千港元，复算H2 2025收入261,228千港元、H2 2024收入307,319千港元，同比下降约15.012%。",
        "official_full_year_minus_h1_prior_period_reconciliation",
        ICABLE_2025_H2_SOURCES,
    ),
    _official_record(
        "i-CABLE",
        "H2 2025",
        "ebitda",
        -110.076,
        "millions HKD",
        "i-CABLE 2025 Final Results Announcement",
        ICABLE_2025_ANNUAL_RESULTS_URL,
        "2025全年分部表披露Reportable segment loss before depreciation, amortisation and impairment losses合计为178,642千港元亏损；减H1同口径68,566千港元亏损，复算H2为110,076千港元亏损。该口径作为官方EBITDA近似口径，需说明与标准化表定义可能不同。",
        "official_full_year_minus_h1_segment_reconciliation",
        ICABLE_2025_H2_SOURCES,
    ),
    _official_record(
        "i-CABLE",
        "H2 2025",
        "capital_expenditures",
        -24.766,
        "millions HKD",
        "i-CABLE 2025 Final Results Announcement",
        ICABLE_2025_ANNUAL_RESULTS_URL,
        "2025全年资本开支约52,000千港元减H1 additions to property, plant and equipment 27,234千港元，复算H2为24,766千港元；现金流出口径记为负数。",
        "official_full_year_minus_h1_capex_reconciliation",
        ICABLE_2025_H2_SOURCES,
    ),
    _official_record(
        "i-CABLE",
        "H2 2025",
        "cash_and_equivalents",
        113.732,
        "millions HKD",
        "i-CABLE 2025 Final Results Announcement",
        ICABLE_2025_ANNUAL_RESULTS_URL,
        "2025全年公告合并财务状况表披露2025年12月31日Cash and bank balances为113,732千港元。",
        "official_annual_balance_sheet_check",
        ICABLE_2025_H2_SOURCES,
    ),
    _official_record(
        "i-CABLE",
        "H2 2025",
        "total_assets",
        867.055,
        "millions HKD",
        "i-CABLE 2025 Final Results Announcement",
        ICABLE_2025_ANNUAL_RESULTS_URL,
        "2025全年公告Financial Highlights和合并财务状况表均披露2025年12月31日Total assets为867,055千港元。",
        "official_annual_balance_sheet_check",
        ICABLE_2025_H2_SOURCES,
    ),
    _official_record(
        "i-CABLE",
        "H2 2025",
        "total_debt",
        2724.368,
        "millions HKD",
        "i-CABLE 2025 Final Results Announcement",
        ICABLE_2025_ANNUAL_RESULTS_URL,
        "2025全年公告披露可转债630,186千港元、计息借款1,840,316千港元、租赁负债202,518+51,348千港元，合计总债务2,724,368千港元。",
        "official_annual_debt_reconciliation",
        ICABLE_2025_H2_SOURCES,
    ),
    _official_record("i-CABLE", "H1 2023", "gross_profit", -39.675, "millions HKD", "i-CABLE 2023 Interim Report", ICABLE_2023_INTERIM_REPORT_URL, "2023中期报告损益表披露Revenue 263,393千港元，Programming costs 126,605千港元、Network expenses 106,255千港元、Cost of sales 70,208千港元，复算毛利为-39,675千港元。", "official_revenue_minus_cost_of_services_reconciliation", ICABLE_2023_H1_SOURCES),
    _official_record("i-CABLE", "H2 2023", "gross_profit", -178.474, "millions HKD", "i-CABLE 2023 Annual Report", ICABLE_2023_ANNUAL_REPORT_URL, "2023年报披露FY2023 Revenue 597,898千港元、三项服务成本合计816,047千港元，全年毛利-218,149千港元；减H1毛利-39,675千港元，复算H2为-178,474千港元。", "official_full_year_minus_h1_gross_profit_reconciliation", ICABLE_2023_H2_SOURCES),
    _official_record("i-CABLE", "H1 2024", "gross_profit", -95.933, "millions HKD", "i-CABLE 2024 Interim Report", ICABLE_2024_INTERIM_REPORT_URL, "2024中期报告损益表披露Revenue 277,170千港元，Programming costs 175,580千港元、Network expenses 118,201千港元、Cost of sales 79,322千港元，复算毛利为-95,933千港元。", "official_revenue_minus_cost_of_services_reconciliation", ICABLE_2024_H1_COMPARATIVE_SOURCES),
    _official_record("i-CABLE", "H2 2024", "gross_profit", -78.828, "millions HKD", "i-CABLE 2024 Annual Report", ICABLE_2024_ANNUAL_REPORT_URL, "2024年报披露FY2024 Revenue 584,489千港元、三项服务成本合计759,250千港元，全年毛利-174,761千港元；减H1毛利-95,933千港元，复算H2为-78,828千港元。", "official_full_year_minus_h1_gross_profit_reconciliation", ICABLE_2024_H2_COMPARATIVE_SOURCES),
    _official_record("i-CABLE", "H1 2025", "gross_profit", -74.658, "millions HKD", "i-CABLE 2025 Interim Report", ICABLE_2025_INTERIM_REPORT_URL, "2025中期报告损益表披露Revenue 277,511千港元，Programming costs 171,159千港元、Network expenses 113,444千港元、Cost of sales 67,566千港元，复算毛利为-74,658千港元。", "official_revenue_minus_cost_of_services_reconciliation", ICABLE_2025_H1_SOURCES),
    _official_record("i-CABLE", "H2 2025", "gross_profit", -90.709, "millions HKD", "i-CABLE 2025 Annual Report", ICABLE_2025_ANNUAL_REPORT_URL, "2025年报披露FY2025 Revenue 538,739千港元、三项服务成本合计704,106千港元，全年毛利-165,367千港元；减H1毛利-74,658千港元，复算H2为-90,709千港元。", "official_full_year_minus_h1_gross_profit_reconciliation", ICABLE_2025_H2_SOURCES),
    _official_record("i-CABLE", "H1 2023", "operating_cash_flow", -114.882, "millions HKD", "i-CABLE 2023 Interim Report", ICABLE_2023_INTERIM_REPORT_URL, "2023中期报告现金流量表披露Net cash used in operating activities为114,882千港元。", "official_interim_cash_flow_statement_check", ICABLE_2023_H1_SOURCES),
    _official_record("i-CABLE", "H2 2023", "operating_cash_flow", -172.365, "millions HKD", "i-CABLE 2023 Annual Report", ICABLE_2023_ANNUAL_REPORT_URL, "2023年报现金流量表披露FY2023经营现金流净流出287,247千港元；减H1净流出114,882千港元，复算H2为172,365千港元净流出。", "official_full_year_minus_h1_cash_flow_reconciliation", ICABLE_2023_H2_SOURCES),
    _official_record("i-CABLE", "H1 2024", "operating_cash_flow", -151.307, "millions HKD", "i-CABLE 2024 Interim Report", ICABLE_2024_INTERIM_REPORT_URL, "2024中期报告现金流量表披露Net cash used in operating activities为151,307千港元。", "official_interim_cash_flow_statement_check", ICABLE_2024_H1_COMPARATIVE_SOURCES),
    _official_record("i-CABLE", "H2 2024", "operating_cash_flow", -69.347, "millions HKD", "i-CABLE 2025 Annual Report", ICABLE_2025_ANNUAL_REPORT_URL, "2025年报比较栏披露重列后FY2024经营现金流净流出220,654千港元；减2024中期报告H1净流出151,307千港元，复算H2为69,347千港元净流出。2024年报原列示FY2024为221,192千港元，差异为租赁利息呈列调整。", "official_latest_comparative_full_year_minus_h1_cash_flow_reconciliation", ICABLE_2024_H2_COMPARATIVE_SOURCES),
    _official_record("i-CABLE", "H1 2025", "operating_cash_flow", -95.152, "millions HKD", "i-CABLE 2025 Interim Report", ICABLE_2025_INTERIM_REPORT_URL, "2025中期报告现金流量表披露Net cash used in operating activities为95,152千港元。", "official_interim_cash_flow_statement_check", ICABLE_2025_H1_SOURCES),
    _official_record("i-CABLE", "H2 2025", "operating_cash_flow", -118.764, "millions HKD", "i-CABLE 2025 Annual Report", ICABLE_2025_ANNUAL_REPORT_URL, "2025年报现金流量表披露FY2025经营现金流净流出213,916千港元；减H1净流出95,152千港元，复算H2为118,764千港元净流出。", "official_full_year_minus_h1_cash_flow_reconciliation", ICABLE_2025_H2_SOURCES),
    _official_record("i-CABLE", "H1 2023", "free_cash_flow", -153.826, "millions HKD", "i-CABLE 2023 Interim Report", ICABLE_2023_INTERIM_REPORT_URL, "2023中期报告披露经营现金流净流出114,882千港元、购买物业厂房及设备付款38,944千港元，复算普通自由现金流为-153,826千港元。", "official_operating_cash_flow_minus_ppe_reconciliation", ICABLE_2023_H1_SOURCES),
    _official_record("i-CABLE", "H2 2023", "free_cash_flow", -210.174, "millions HKD", "i-CABLE 2023 Annual Report", ICABLE_2023_ANNUAL_REPORT_URL, "2023年报披露FY2023经营现金流净流出287,247千港元、PPE付款76,753千港元；扣除H1后H2经营现金流净流出172,365千港元、PPE付款37,809千港元，复算普通自由现金流为-210,174千港元。", "official_operating_cash_flow_minus_ppe_reconciliation", ICABLE_2023_H2_SOURCES),
    _official_record("i-CABLE", "H1 2024", "free_cash_flow", -180.414, "millions HKD", "i-CABLE 2024 Interim Report", ICABLE_2024_INTERIM_REPORT_URL, "2024中期报告披露经营现金流净流出151,307千港元、购买物业厂房及设备付款29,107千港元，复算普通自由现金流为-180,414千港元。", "official_operating_cash_flow_minus_ppe_reconciliation", ICABLE_2024_H1_COMPARATIVE_SOURCES),
    _official_record("i-CABLE", "H2 2024", "free_cash_flow", -106.936, "millions HKD", "i-CABLE 2025 Annual Report", ICABLE_2025_ANNUAL_REPORT_URL, "2025年报比较栏披露重列后FY2024经营现金流净流出220,654千港元、PPE付款66,696千港元；扣除H1后H2经营现金流净流出69,347千港元、PPE付款37,589千港元，复算普通自由现金流为-106,936千港元。", "official_operating_cash_flow_minus_ppe_reconciliation", ICABLE_2024_H2_COMPARATIVE_SOURCES),
    _official_record("i-CABLE", "H1 2025", "free_cash_flow", -121.528, "millions HKD", "i-CABLE 2025 Interim Report", ICABLE_2025_INTERIM_REPORT_URL, "2025中期报告披露经营现金流净流出95,152千港元、购买物业厂房及设备付款26,376千港元，复算普通自由现金流为-121,528千港元。", "official_operating_cash_flow_minus_ppe_reconciliation", ICABLE_2025_H1_SOURCES),
    _official_record("i-CABLE", "H2 2025", "free_cash_flow", -144.403, "millions HKD", "i-CABLE 2025 Annual Report", ICABLE_2025_ANNUAL_REPORT_URL, "2025年报披露FY2025经营现金流净流出213,916千港元、PPE付款52,015千港元；扣除H1后H2经营现金流净流出118,764千港元、PPE付款25,639千港元，复算普通自由现金流为-144,403千港元。", "official_operating_cash_flow_minus_ppe_reconciliation", ICABLE_2025_H2_SOURCES),
    _official_record("i-CABLE", "H1 2024", "revenue_growth_yoy", 5.231, "percent", "i-CABLE 2024 Interim Report", ICABLE_2024_INTERIM_REPORT_URL, "2024中期报告损益表披露H1 2024 Revenue 277,170千港元、H1 2023 Revenue 263,393千港元，复算同比增长5.231%。", "official_current_prior_period_reconciliation", ICABLE_2024_H1_COMPARATIVE_SOURCES),
    _official_record("i-CABLE", "H2 2024", "revenue_growth_yoy", -8.127, "percent", "i-CABLE 2024 Annual Report", ICABLE_2024_ANNUAL_REPORT_URL, "2024年报披露FY2024 Revenue 584,489千港元、FY2023 Revenue 597,898千港元；扣除H1 2024 277,170千港元和H1 2023 263,393千港元，复算H2 2024收入307,319千港元、H2 2023收入334,505千港元，同比下降8.127%。", "official_full_year_minus_h1_prior_period_reconciliation", ICABLE_2024_H2_COMPARATIVE_SOURCES),
    _official_record("i-CABLE", "H1 2024", "cash_and_equivalents", 65.719, "millions HKD", "i-CABLE 2024 Interim Report", ICABLE_2024_INTERIM_REPORT_URL, "2024中期报告资产负债表披露2024年6月30日Cash and bank balances为65,719千港元。", "official_interim_balance_sheet_check", ICABLE_2024_H1_COMPARATIVE_SOURCES),
    _official_record("i-CABLE", "H1 2024", "total_assets", 950.801, "millions HKD", "i-CABLE 2024 Interim Report", ICABLE_2024_INTERIM_REPORT_URL, "2024中期报告Financial Highlights和资产负债表均披露2024年6月30日Total assets为950,801千港元。", "official_interim_balance_sheet_check", ICABLE_2024_H1_COMPARATIVE_SOURCES),
    _official_record("i-CABLE", "H1 2024", "total_debt", 2129.158, "millions HKD", "i-CABLE 2024 Interim Report", ICABLE_2024_INTERIM_REPORT_URL, "2024中期报告资产负债表披露可转债585,666千港元、计息借款820,000+461,035千港元、租赁负债257,736+4,721千港元，合计总债务2,129,158千港元。", "official_interim_debt_reconciliation", ICABLE_2024_H1_COMPARATIVE_SOURCES),
]

HKT_2016_2020_SOURCES_BY_YEAR = {
    2016: [
        {"label": "HKT 2016 Annual Report - HKEX", "url": HKT_2016_ANNUAL_REPORT_URL, "evidence": "2016年报 Management's Discussion and Analysis 披露2015/2016 H1/H2 Total revenue 与 Total EBITDA。"},
        {"label": "HKT 2016 Annual Results Announcement - HKEX", "url": HKT_2016_ANNUAL_RESULTS_URL, "evidence": "2016年度业绩公告同表披露2015/2016 H1/H2 Total revenue 与 Total EBITDA。"},
        {"label": "HKT 2017 Annual Report - HKEX comparative base", "url": HKT_2017_ANNUAL_REPORT_URL, "evidence": "2017年报重列2016 H1/H2 Total revenue 与 Total EBITDA，用于交叉核验。"},
    ],
    2017: [
        {"label": "HKT 2017 Annual Report - HKEX", "url": HKT_2017_ANNUAL_REPORT_URL, "evidence": "2017年报 Management's Discussion and Analysis 披露2016/2017 H1/H2 Total revenue 与 Total EBITDA。"},
        {"label": "HKT 2017 Annual Results Announcement - HKEX", "url": HKT_2017_ANNUAL_RESULTS_URL, "evidence": "2017年度业绩公告同表披露2016/2017 H1/H2 Total revenue 与 Total EBITDA。"},
        {"label": "HKT 2018 Annual Report - HKEX comparative base", "url": HKT_2018_ANNUAL_REPORT_URL, "evidence": "2018年报重列2017 H1/H2 Total revenue 与 Total EBITDA，用于交叉核验。"},
    ],
    2018: [
        {"label": "HKT 2018 Annual Report - HKEX", "url": HKT_2018_ANNUAL_REPORT_URL, "evidence": "2018年报 Management's Discussion and Analysis 披露2017/2018 H1/H2 Total revenue 与 Total EBITDA。"},
        {"label": "HKT 2018 Annual Results Presentation - HKT official site", "url": HKT_2018_ANNUAL_RESULTS_URL, "evidence": "HKT官网2018年度业绩材料披露2018全年收入、EBITDA及相关基数。"},
        {"label": "HKT 2019 Annual Report - HKEX comparative base", "url": HKT_2019_ANNUAL_REPORT_URL, "evidence": "2019年报重列2018 H1/H2 Total revenue 与 Total EBITDA，用于交叉核验。"},
    ],
    2019: [
        {"label": "HKT 2019 Annual Report - HKEX", "url": HKT_2019_ANNUAL_REPORT_URL, "evidence": "2019年报 Management's Discussion and Analysis 披露2018/2019 H1/H2 Total revenue 与 Total EBITDA。"},
        {"label": "HKT 2019 Annual Results Announcement - HKEX", "url": HKT_2019_ANNUAL_RESULTS_URL, "evidence": "2019年度业绩公告同表披露2018/2019 H1/H2 Total revenue 与 Total EBITDA。"},
        {"label": "HKT 2020 Annual Report - HKEX comparative base", "url": HKT_2020_ANNUAL_REPORT_URL, "evidence": "2020年报重列2019 H1/H2 Total revenue 与 Total EBITDA，用于交叉核验。"},
    ],
    2020: [
        {"label": "HKT 2020 Annual Report - HKEX", "url": HKT_2020_ANNUAL_REPORT_URL, "evidence": "2020年报 Management's Discussion and Analysis 披露2019/2020 H1/H2 Total revenue 与 Total EBITDA。"},
        {"label": "HKT 2021 Annual Report - HKEX comparative base", "url": HKT_2021_ANNUAL_REPORT_URL, "evidence": "2021年报重列2020/2021 H1/H2 Total revenue 与 Total EBITDA，用于交叉核验。"},
    ],
}

HKT_2016_2020_METRICS = {
    "H1 2016": {"year": 2016, "revenue": 16388, "ebitda": 5865},
    "H2 2016": {"year": 2016, "revenue": 17459, "ebitda": 6819},
    "H1 2017": {"year": 2017, "revenue": 15649, "ebitda": 5968},
    "H2 2017": {"year": 2017, "revenue": 17609, "ebitda": 7029},
    "H1 2018": {"year": 2018, "revenue": 17022, "ebitda": 5639},
    "H2 2018": {"year": 2018, "revenue": 18165, "ebitda": 6919},
    "H1 2019": {"year": 2019, "revenue": 15109, "ebitda": 5733},
    "H2 2019": {"year": 2019, "revenue": 17994, "ebitda": 7084},
    "H1 2020": {"year": 2020, "revenue": 14606, "ebitda": 5546},
    "H2 2020": {"year": 2020, "revenue": 17783, "ebitda": 6981},
}

HKT_2016_2020_OFFICIAL_VERIFICATIONS = [
    _official_record(
        "HKT / csl / 1O1O",
        period,
        metric_key,
        value,
        "millions HKD",
        f"HKT {metrics['year']} Annual Report and comparative annual reports",
        HKT_2016_2020_SOURCES_BY_YEAR[metrics["year"]][0]["url"],
        (
            f"HKT {metrics['year']} 年报/年度业绩公告的 H1/H2 Financial Review 表披露 {period} "
            f"{'Total revenue' if metric_key == 'revenue' else 'Total EBITDA'} 为 {value:,} 百万港元；"
            "后续年度年报比较栏重列同一半年度数，用于交叉核验。"
        ),
        "official_annual_segment_half_year_check",
        HKT_2016_2020_SOURCES_BY_YEAR[metrics["year"]],
    )
    for period, metrics in HKT_2016_2020_METRICS.items()
    for metric_key, value in metrics.items()
    if metric_key != "year"
]

HKT_2021_2022_OFFICIAL_VERIFICATIONS = [
    *[
        _official_record(
            "HKT / csl / 1O1O",
            period,
            metric_key,
            official_value,
            "percent" if metric_key in {"revenue_growth_yoy", "operating_margin"} else "millions HKD",
            source_label,
            source_url,
            evidence,
            verification_method,
            sources,
        )
        for period, source_label, source_url, annual_sources, interim_sources, period_values in [
            (
                "H1 2021",
                "HKT 2021 Interim Report",
                HKT_2021_INTERIM_REPORT_URL,
                HKT_2021_ANNUAL_REPORT_SOURCES,
                HKT_2021_INTERIM_SOURCES,
                {
                    "revenue": (15643, "2021中报和2021年报分部表均披露2021 H1 Total revenue为15,643百万港元。", "official_interim_and_annual_segment_check", None),
                    "revenue_growth_yoy": (7.100, "2021年报分部表披露2020 H1 Total revenue 14,606、2021 H1 15,643，复算同比增长约7.100%。", "official_prior_period_revenue_recalculation", None),
                    "gross_profit": (8093, "2021 H1 Total revenue 15,643减Cost of sales 7,550，复算毛利为8,093百万港元。", "official_revenue_minus_cost_of_sales", None),
                    "ebitda": (5715, "2021中报和2021年报分部表均披露2021 H1 Total EBITDA为5,715百万港元。", "official_interim_and_annual_segment_check", None),
                    "capital_expenditures": (-1170, "2021中报和2021年报Adjusted Funds Flow表披露2021 H1 capital expenditures现金流出为1,170百万港元，记为负数。", "official_adjusted_funds_flow_capex_check", None),
                    "adjusted_funds_flow": (2326, "2021中报和2021年报Adjusted Funds Flow表均披露2021 H1 adjusted funds flow为2,326百万港元。该口径不是HKFRS经营现金流，也不能等同普通自由现金流。", "official_adjusted_funds_flow_check", None),
                    "net_income": (1900, "2021中报披露2021 H1 holders of Share Stapled Units/shares of the Company应占利润为1,900百万港元。", "official_interim_statement_check", "interim"),
                    "operating_income": (2966, "2021 H1 EBITDA 5,715、折旧摊销2,751、处置收益2，复算经营利润为2,966百万港元。", "official_segment_ebitda_less_da_reconciliation", None),
                    "operating_margin": (18.960, "2021 H1经营利润2,966除以Total revenue 15,643，复算经营利润率约18.960%。", "official_operating_income_margin_recalculation", None),
                    "operating_cash_flow": (4593, "2021中报现金流量表披露2021 H1 Net cash generated from operating activities为4,593百万港元。", "official_interim_cashflow_check", "interim"),
                    "free_cash_flow": (3423, "普通自由现金流按2021 H1经营现金流4,593减Adjusted Funds Flow表资本开支现金流出1,170复算为3,423百万港元；HKT官方AFF为独立口径，不等同普通FCF。", "official_operating_cash_flow_minus_capex_reconciliation", "both"),
                    "cash_and_equivalents": (1681, "2021中报资产负债表和现金流量表披露2021年6月30日现金及现金等价物为1,681百万港元。", "official_interim_balance_sheet_and_cashflow_check", "interim"),
                    "total_assets": (104285, "2021中报资产负债表披露2021年6月30日非流动资产95,203、流动资产9,082，合计总资产104,285百万港元。", "official_interim_balance_sheet_reconciliation", "interim"),
                    "total_debt": (43327, "2021中报管理层流动性披露2021年6月30日gross debt为43,327百万港元；gross debt定义为短期及长期借款本金，不含租赁负债。", "official_interim_gross_debt_principal_check", "interim"),
                },
            ),
            (
                "H2 2021",
                "HKT 2021 Annual Report",
                HKT_2021_ANNUAL_REPORT_URL,
                HKT_2021_ANNUAL_REPORT_SOURCES,
                HKT_2021_INTERIM_SOURCES,
                {
                    "revenue": (18318, "2021年报分部表披露2021 H2 Total revenue为18,318百万港元。", "official_annual_segment_half_year_check", None),
                    "revenue_growth_yoy": (3.009, "2021年报分部表披露2020 H2 Total revenue 17,783、2021 H2 18,318，复算同比增长约3.009%。", "official_prior_period_revenue_recalculation", None),
                    "gross_profit": (9139, "2021 H2 Total revenue 18,318减Cost of sales 9,179，复算毛利为9,139百万港元。", "official_revenue_minus_cost_of_sales", None),
                    "ebitda": (7018, "2021年报分部表和Adjusted Funds Flow表均披露2021 H2 Total EBITDA为7,018百万港元。", "official_annual_segment_and_aff_check", None),
                    "capital_expenditures": (-1208, "2021年报Adjusted Funds Flow表披露2021 H2 capital expenditures现金流出为1,208百万港元，记为负数。", "official_adjusted_funds_flow_capex_check", None),
                    "adjusted_funds_flow": (3187, "2021年报Adjusted Funds Flow表披露2021 H2 adjusted funds flow为3,187百万港元。该口径不是HKFRS经营现金流，也不能等同普通自由现金流。", "official_adjusted_funds_flow_check", None),
                    "net_income": (2908, "2021年报损益表披露全年归母利润4,808百万港元，减2021 H1中报归母利润1,900，复算2021 H2为2,908百万港元。", "official_annual_minus_interim_statement_reconciliation", "both"),
                    "operating_income": (4139, "2021 H2 EBITDA 7,018、折旧摊销2,901、处置收益22，复算经营利润为4,139百万港元。", "official_segment_ebitda_less_da_reconciliation", None),
                    "operating_margin": (22.595, "2021 H2经营利润4,139除以Total revenue 18,318，复算经营利润率约22.595%。", "official_operating_income_margin_recalculation", None),
                    "operating_cash_flow": (6048, "2021年报现金流量表披露全年经营现金流10,641百万港元，减2021 H1中报4,593，复算2021 H2为6,048百万港元。", "official_annual_minus_interim_cashflow_reconciliation", "both"),
                    "free_cash_flow": (4840, "普通自由现金流按2021 H2经营现金流6,048减Adjusted Funds Flow表资本开支现金流出1,208复算为4,840百万港元；HKT官方AFF为独立口径，不等同普通FCF。", "official_operating_cash_flow_minus_capex_reconciliation", "both"),
                    "cash_and_equivalents": (2411, "2021年报资产负债表和现金流量表披露2021年12月31日现金及现金等价物为2,411百万港元。", "official_annual_balance_sheet_and_cashflow_check", None),
                    "total_assets": (109612, "2021年报资产负债表披露2021年12月31日非流动资产98,477、流动资产11,135，合计总资产109,612百万港元。", "official_annual_balance_sheet_reconciliation", None),
                    "total_debt": (43886, "2021年报管理层流动性披露2021年12月31日gross debt为43,886百万港元；gross debt定义为短期及长期借款本金，不含租赁负债。", "official_annual_gross_debt_principal_check", None),
                },
            ),
            (
                "H1 2022",
                "HKT 2022 Interim Report",
                HKT_2022_INTERIM_REPORT_URL,
                HKT_2022_ANNUAL_REPORT_SOURCES,
                HKT_2022_INTERIM_SOURCES,
                {
                    "revenue": (16157, "2022中报和2022年报分部表均披露2022 H1 Total revenue为16,157百万港元。", "official_interim_and_annual_segment_check", None),
                    "revenue_growth_yoy": (3.286, "2022年报分部表披露2021 H1 Total revenue 15,643、2022 H1 16,157，复算同比增长约3.286%。", "official_current_prior_period_recalculation", None),
                    "gross_profit": (8023, "2022 H1 Total revenue 16,157减Cost of sales 8,134，复算毛利为8,023百万港元。", "official_revenue_minus_cost_of_sales", None),
                    "ebitda": (5834, "2022中报和2022年报分部表均披露2022 H1 Total EBITDA为5,834百万港元。", "official_interim_and_annual_segment_check", None),
                    "capital_expenditures": (-1140, "2022中报和2022年报Adjusted Funds Flow表披露2022 H1 capital expenditures现金流出为1,140百万港元，记为负数。", "official_adjusted_funds_flow_capex_check", None),
                    "adjusted_funds_flow": (2377, "2022中报和2022年报Adjusted Funds Flow表均披露2022 H1 adjusted funds flow为2,377百万港元。该口径不是HKFRS经营现金流，也不能等同普通自由现金流。", "official_adjusted_funds_flow_check", None),
                    "net_income": (1910, "2022中报披露2022 H1 holders of Share Stapled Units/shares of the Company应占利润为1,910百万港元。", "official_interim_statement_check", "interim"),
                    "operating_income": (3009, "2022 H1 EBITDA 5,834、折旧摊销2,825、处置收益0，复算经营利润为3,009百万港元。", "official_segment_ebitda_less_da_reconciliation", None),
                    "operating_margin": (18.624, "2022 H1经营利润3,009除以Total revenue 16,157，复算经营利润率约18.624%。", "official_operating_income_margin_recalculation", None),
                    "operating_cash_flow": (4689, "2022中报现金流量表披露2022 H1 Net cash generated from operating activities为4,689百万港元。", "official_interim_cashflow_check", "interim"),
                    "free_cash_flow": (3549, "普通自由现金流按2022 H1经营现金流4,689减Adjusted Funds Flow表资本开支现金流出1,140复算为3,549百万港元；HKT官方AFF为独立口径，不等同普通FCF。", "official_operating_cash_flow_minus_capex_reconciliation", "both"),
                    "cash_and_equivalents": (1568, "2022中报资产负债表和现金流量表披露2022年6月30日现金及现金等价物为1,568百万港元。", "official_interim_balance_sheet_and_cashflow_check", "interim"),
                    "total_assets": (109916, "2022中报资产负债表披露2022年6月30日非流动资产99,431、流动资产10,485，合计总资产109,916百万港元。", "official_interim_balance_sheet_reconciliation", "interim"),
                    "total_debt": (44343, "2022中报管理层流动性披露2022年6月30日gross debt为44,343百万港元；gross debt定义为短期及长期借款本金，不含租赁负债。", "official_interim_gross_debt_principal_check", "interim"),
                },
            ),
            (
                "H2 2022",
                "HKT 2022 Annual Report",
                HKT_2022_ANNUAL_REPORT_URL,
                HKT_2022_ANNUAL_REPORT_SOURCES,
                HKT_2022_INTERIM_SOURCES,
                {
                    "revenue": (17968, "2022年报分部表披露2022 H2 Total revenue为17,968百万港元。", "official_annual_segment_half_year_check", None),
                    "revenue_growth_yoy": (-1.911, "2022年报分部表披露2021 H2 Total revenue 18,318、2022 H2 17,968，复算同比下降约1.911%。", "official_current_prior_period_recalculation", None),
                    "gross_profit": (9008, "2022 H2 Total revenue 17,968减Cost of sales 8,960，复算毛利为9,008百万港元。", "official_revenue_minus_cost_of_sales", None),
                    "ebitda": (7230, "2022年报分部表和Adjusted Funds Flow表均披露2022 H2 Total EBITDA为7,230百万港元。", "official_annual_segment_and_aff_check", None),
                    "capital_expenditures": (-1113, "2022年报Adjusted Funds Flow表披露2022 H2 capital expenditures现金流出为1,113百万港元，记为负数。", "official_adjusted_funds_flow_capex_check", None),
                    "adjusted_funds_flow": (3271, "2022年报Adjusted Funds Flow表披露2022 H2 adjusted funds flow为3,271百万港元。该口径不是HKFRS经营现金流，也不能等同普通自由现金流。", "official_adjusted_funds_flow_check", None),
                    "net_income": (2991, "2022年报损益表披露全年归母利润4,901百万港元，减2022 H1中报归母利润1,910，复算2022 H2为2,991百万港元。", "official_annual_minus_interim_statement_reconciliation", "both"),
                    "operating_income": (4245, "2022 H2 EBITDA 7,230、折旧摊销2,982、处置亏损3，复算经营利润为4,245百万港元。", "official_segment_ebitda_less_da_reconciliation", None),
                    "operating_margin": (23.625, "2022 H2经营利润4,245除以Total revenue 17,968，复算经营利润率约23.625%。", "official_operating_income_margin_recalculation", None),
                    "operating_cash_flow": (6002, "2022年报现金流量表披露全年经营现金流10,691百万港元，减2022 H1中报4,689，复算2022 H2为6,002百万港元。", "official_annual_minus_interim_cashflow_reconciliation", "both"),
                    "free_cash_flow": (4889, "普通自由现金流按2022 H2经营现金流6,002减Adjusted Funds Flow表资本开支现金流出1,113复算为4,889百万港元；HKT官方AFF为独立口径，不等同普通FCF。", "official_operating_cash_flow_minus_capex_reconciliation", "both"),
                    "cash_and_equivalents": (1997, "2022年报资产负债表和现金流量表披露2022年12月31日现金及现金等价物为1,997百万港元。", "official_annual_balance_sheet_and_cashflow_check", None),
                    "total_assets": (111195, "2022年报资产负债表披露2022年12月31日非流动资产100,035、流动资产11,160，合计总资产111,195百万港元。", "official_annual_balance_sheet_reconciliation", None),
                    "total_debt": (44179, "2022年报管理层流动性披露2022年12月31日gross debt为44,179百万港元；gross debt定义为短期及长期借款本金，不含租赁负债。", "official_annual_gross_debt_principal_check", None),
                },
            ),
        ]
        for metric_key, (official_value, evidence, verification_method, source_scope) in period_values.items()
        for sources in [
            interim_sources if source_scope == "interim"
            else annual_sources + interim_sources if source_scope == "both"
            else annual_sources + interim_sources if period.startswith("H1 ")
            else annual_sources
        ]
    ],
]


OFFICIAL_VERIFICATIONS: list[dict[str, Any]] = [
    *AWS_OFFICIAL_VERIFICATIONS,
    *MICROSOFT_OFFICIAL_VERIFICATIONS,
    *GOOGLE_CLOUD_Q4_2018_2019_QUARTERLY_REVENUE_OFFICIAL_VERIFICATIONS,
    *GOOGLE_CLOUD_2017_2019_ANNUAL_ONLY_OFFICIAL_VERIFICATIONS,
    *GOOGLE_CLOUD_OFFICIAL_VERIFICATIONS,
    *ORACLE_CLOUD_OFFICIAL_VERIFICATIONS,
    *TENCENT_FBS_OFFICIAL_VERIFICATIONS,
    *ALIBABA_LEGACY_CLOUD_SEGMENT_OFFICIAL_VERIFICATIONS,
    *ALIBABA_CLOUD_OFFICIAL_VERIFICATIONS,
    *CT_2016_2018_OFFICIAL_VERIFICATIONS,
    *CM_2016_2018_CORE_OFFICIAL_VERIFICATIONS,
    *CM_2019_CORE_OFFICIAL_VERIFICATIONS,
    *CM_2020_CORE_OFFICIAL_VERIFICATIONS,
    *CM_2021_DETAIL_OFFICIAL_VERIFICATIONS,
    *CM_2022_CORE_OFFICIAL_VERIFICATIONS,
    *CM_2022_DETAIL_OFFICIAL_VERIFICATIONS,
    *CM_2023_OFFICIAL_VERIFICATIONS,
    *CM_2023_DETAIL_OFFICIAL_VERIFICATIONS,
    *CM_2024_OFFICIAL_VERIFICATIONS,
    *CM_2024_DETAIL_OFFICIAL_VERIFICATIONS,
    *CT_2019_OFFICIAL_VERIFICATIONS,
    *CT_2020_OFFICIAL_VERIFICATIONS,
    *CT_2021_OFFICIAL_VERIFICATIONS,
    *CT_2021_DETAIL_OFFICIAL_VERIFICATIONS,
    *CT_2022_OFFICIAL_VERIFICATIONS,
    *CT_2022_DETAIL_OFFICIAL_VERIFICATIONS,
    _official_record("中国移动", "Q1 2026", "cash_and_equivalents", 155287, "millions CNY", "中国移动2026年第一季度报告", CM_2026_Q1_CNINFO_URL, "合并现金流量表披露期末现金及现金等价物余额155,287百万元；该口径不同于资产负债表货币资金205,262百万元。", "official_cash_flow_statement_cash_equivalents_check", CM_2026_Q1_SOURCES),
    _official_record("中国移动", "Q1 2026", "gross_profit", 67554, "millions CNY", "中国移动2026年第一季度报告", CM_2026_Q1_CNINFO_URL, "合并利润表披露营业收入266,478百万元、营业成本198,924百万元；按收入减营业成本复算毛利为67,554百万元。", "official_revenue_minus_operating_cost_reconciliation", CM_2026_Q1_SOURCES),
    _official_record("中国移动", "Q1 2026", "gross_margin", 25.350, "percent", "中国移动2026年第一季度报告", CM_2026_Q1_CNINFO_URL, "以官方复算毛利67,554百万元除以营业收入266,478百万元，毛利率为25.350%。", "official_gross_profit_divided_by_revenue_reconciliation", CM_2026_Q1_SOURCES),
    _official_record("中国移动", "Q1 2026", "operating_income", 37300, "millions CNY", "中国移动2026年第一季度报告", CM_2026_Q1_CNINFO_URL, "合并利润表披露营业利润37,300百万元。", "official_income_statement_row_check", CM_2026_Q1_SOURCES),
    _official_record("中国移动", "Q1 2026", "operating_margin", 13.997, "percent", "中国移动2026年第一季度报告", CM_2026_Q1_CNINFO_URL, "以营业利润37,300百万元除以营业收入266,478百万元，经营利润率为13.997%。", "official_operating_income_divided_by_revenue_reconciliation", CM_2026_Q1_SOURCES),
    _official_record("中国移动", "Q1 2026", "revenue_growth_yoy", 1.031, "percent", "中国移动2026年第一季度报告", CM_2026_Q1_CNINFO_URL, "一季报披露2026Q1营业收入266,478百万元、2025Q1营业收入263,760百万元，复算同比为1.031%；主要财务指标表列示同比增长1.0%。", "official_current_prior_period_recalculation", CM_2026_Q1_SOURCES),
    _official_record("中国移动", "Q1 2026", "total_assets", 2153534, "millions CNY", "中国移动2026年第一季度报告", CM_2026_Q1_CNINFO_URL, "合并资产负债表披露2026年3月31日资产总计2,153,534百万元。", "official_balance_sheet_row_check", CM_2026_Q1_SOURCES),
    _official_record("中国移动", "Q1 2026", "total_debt", 102327, "millions CNY", "中国移动2026年第一季度报告", CM_2026_Q1_CNINFO_URL, "合并资产负债表披露一年内到期的非流动负债45,366百万元、长期借款9,474百万元、租赁负债47,487百万元，合计总债务102,327百万元。", "official_borrowings_plus_lease_liabilities_reconciliation", CM_2026_Q1_SOURCES),
    _official_record("中国移动", "Q1 2024", "capital_expenditures", -34478, "millions CNY", "中国移动2024年第一季度报告", CM_2024_Q1_CNINFO_URL, "合并现金流量表披露购建固定资产、无形资产和其他长期资产支付的现金34,478百万元；现金流出口径记为负数。", "official_cash_flow_statement_row_check", CM_2024_Q1_DETAIL_SOURCES),
    _official_record("中国移动", "Q1 2024", "cash_and_equivalents", 166026, "millions CNY", "中国移动2024年第一季度报告", CM_2024_Q1_CNINFO_URL, "合并现金流量表披露期末现金及现金等价物余额166,026百万元；该口径不同于资产负债表货币资金199,813百万元。", "official_cash_flow_statement_cash_equivalents_check", CM_2024_Q1_DETAIL_SOURCES),
    _official_record("中国移动", "Q1 2024", "free_cash_flow", 22426, "millions CNY", "中国移动2024年第一季度报告", CM_2024_Q1_CNINFO_URL, "合并现金流量表披露经营现金流56,904百万元、购建长期资产现金支出34,478百万元；普通自由现金流复算为22,426百万元。", "official_operating_cash_flow_minus_capex_reconciliation", CM_2024_Q1_DETAIL_SOURCES),
    _official_record("中国移动", "Q1 2024", "gross_profit", 69017, "millions CNY", "中国移动2024年第一季度报告", CM_2024_Q1_CNINFO_URL, "合并利润表披露营业收入263,707百万元、营业成本194,690百万元；按收入减营业成本复算毛利为69,017百万元。", "official_revenue_minus_operating_cost_reconciliation", CM_2024_Q1_DETAIL_SOURCES),
    _official_record("中国移动", "Q1 2024", "gross_margin", 26.172, "percent", "中国移动2024年第一季度报告", CM_2024_Q1_CNINFO_URL, "以官方复算毛利69,017百万元除以营业收入263,707百万元，毛利率为26.172%。", "official_gross_profit_divided_by_revenue_reconciliation", CM_2024_Q1_DETAIL_SOURCES),
    _official_record("中国移动", "Q1 2024", "operating_cash_flow", 56904, "millions CNY", "中国移动2024年第一季度报告", CM_2024_Q1_CNINFO_URL, "合并现金流量表披露经营活动产生的现金流量净额56,904百万元。", "official_cash_flow_statement_row_check", CM_2024_Q1_DETAIL_SOURCES),
    _official_record("中国移动", "Q1 2024", "operating_income", 38134, "millions CNY", "中国移动2024年第一季度报告", CM_2024_Q1_CNINFO_URL, "合并利润表披露营业利润38,134百万元。", "official_income_statement_row_check", CM_2024_Q1_DETAIL_SOURCES),
    _official_record("中国移动", "Q1 2024", "operating_margin", 14.461, "percent", "中国移动2024年第一季度报告", CM_2024_Q1_CNINFO_URL, "以营业利润38,134百万元除以营业收入263,707百万元，经营利润率为14.461%。", "official_operating_income_divided_by_revenue_reconciliation", CM_2024_Q1_DETAIL_SOURCES),
    _official_record("中国移动", "Q1 2024", "revenue_growth_yoy", 5.169, "percent", "中国移动2024年第一季度报告", CM_2024_Q1_CNINFO_URL, "一季报披露2024Q1营业收入263,707百万元、2023Q1营业收入250,746百万元，复算同比为5.169%；主要财务指标表列示同比增长5.2%。", "official_current_prior_period_recalculation", CM_2024_Q1_DETAIL_SOURCES),
    _official_record("中国移动", "Q1 2024", "total_assets", 1995601, "millions CNY", "中国移动2024年第一季度报告", CM_2024_Q1_CNINFO_URL, "合并资产负债表披露2024年3月31日资产总计1,995,601百万元。", "official_balance_sheet_row_check", CM_2024_Q1_DETAIL_SOURCES),
    _official_record("中国移动", "Q1 2024", "total_debt", 98943, "millions CNY", "中国移动2024年第一季度报告", CM_2024_Q1_CNINFO_URL, "合并资产负债表披露一年内到期的非流动负债32,930百万元、租赁负债66,013百万元，未列短期或长期借款，合计总债务98,943百万元。", "official_borrowings_plus_lease_liabilities_reconciliation", CM_2024_Q1_DETAIL_SOURCES),
    *CT_2023_OFFICIAL_VERIFICATIONS,
    *CT_2023_DETAIL_OFFICIAL_VERIFICATIONS,
    *CT_2024_OFFICIAL_VERIFICATIONS,
    *CT_2024_DETAIL_OFFICIAL_VERIFICATIONS,
    _official_record("中国电信", "Q1 2023", "capital_expenditures", -14507.825, "millions CNY", "中国电信2023年第一季度报告（IRAsia中文版）", CT_2023_Q1_CN_URL, "A股中文一季报现金流量表披露购建固定资产、无形资产和其他长期资产支付的现金14,507,824,903.22元；现金流出口径记为负数。港股一季报披露Capital expenditure 14,504百万元，差异来自披露四舍五入。", "official_cash_flow_statement_row_check", CT_2023_Q1_DETAIL_SOURCES),
    _official_record("中国电信", "Q1 2023", "cash_and_equivalents", 74642.215, "millions CNY", "中国电信2023年第一季度报告（IRAsia中文版）", CT_2023_Q1_CN_URL, "A股中文一季报现金流量表披露期末现金及现金等价物余额74,642,215,335.44元；港股一季报同表列示Cash and cash equivalents as at 31 March为74,642百万元。", "official_cash_flow_statement_cash_equivalents_check", CT_2023_Q1_DETAIL_SOURCES),
    _official_record("中国电信", "Q1 2023", "free_cash_flow", 13706.747, "millions CNY", "中国电信2023年第一季度报告（IRAsia中文版）", CT_2023_Q1_CN_URL, "A股中文一季报披露经营现金流28,214.572百万元、购建长期资产现金支出14,507.825百万元；普通自由现金流复算为13,706.747百万元。", "official_operating_cash_flow_minus_capex_reconciliation", CT_2023_Q1_DETAIL_SOURCES),
    _official_record("中国电信", "Q1 2023", "gross_profit", 38245.006, "millions CNY", "中国电信2023年第一季度报告（IRAsia中文版）", CT_2023_Q1_CN_URL, "A股中文一季报披露营业收入129,753.223百万元、营业成本91,508.217百万元；按收入减营业成本复算毛利为38,245.006百万元。该A股营业成本口径不同于标准化表。", "official_revenue_minus_operating_cost_reconciliation", CT_2023_Q1_DETAIL_SOURCES),
    _official_record("中国电信", "Q1 2023", "gross_margin", 29.475, "percent", "中国电信2023年第一季度报告（IRAsia中文版）", CT_2023_Q1_CN_URL, "以A股口径Q1毛利38,245.006百万元除以A股口径营业收入129,753.223百万元，毛利率为29.475%；该口径不同于标准化表。", "official_gross_profit_divided_by_revenue_reconciliation", CT_2023_Q1_DETAIL_SOURCES),
    _official_record("中国电信", "Q1 2023", "operating_cash_flow", 28214.572, "millions CNY", "中国电信2023年第一季度报告（IRAsia中文版）", CT_2023_Q1_CN_URL, "A股中文一季报现金流量表披露经营活动产生的现金流量净额28,214,572,383.01元；港股一季报列示Net cash from operating activities 28,215百万元。", "official_cash_flow_statement_row_check", CT_2023_Q1_DETAIL_SOURCES),
    _official_record("中国电信", "Q1 2023", "operating_income", 10676.455, "millions CNY", "中国电信2023年第一季度报告（IRAsia中文版）", CT_2023_Q1_CN_URL, "A股中文一季报合并利润表披露营业利润10,676,454,808.71元；港股一季报Operating profit为10,002百万元，二者为不同报表口径。", "official_income_statement_row_check", CT_2023_Q1_DETAIL_SOURCES),
    _official_record("中国电信", "Q1 2023", "operating_margin", 8.228, "percent", "中国电信2023年第一季度报告（IRAsia中文版）", CT_2023_Q1_CN_URL, "以A股口径营业利润10,676.455百万元除以营业收入129,753.223百万元，经营利润率为8.228%；该口径不同于标准化表。", "official_operating_income_divided_by_revenue_reconciliation", CT_2023_Q1_DETAIL_SOURCES),
    _official_record("中国电信", "Q1 2023", "revenue_growth_yoy", 9.400, "percent", "中国电信2023年第一季度报告（IRAsia中文版）", CT_2023_Q1_CN_URL, "A股中文一季报主要会计数据表披露2023Q1营业收入129,753,222,753.19元、同比增长9.4%；合并利润表上年同期营业收入118,576,141,111.63元。", "official_reported_yoy_and_prior_period_check", CT_2023_Q1_DETAIL_SOURCES),
    _official_record("中国电信", "Q1 2023", "total_assets", 823655.760, "millions CNY", "中国电信2023年第一季度报告（IRAsia中文版）", CT_2023_Q1_CN_URL, "A股中文一季报资产负债表披露2023年3月31日资产总计823,655,760,327.95元；港股一季报列示Total assets 823,656百万元。", "official_balance_sheet_row_check", CT_2023_Q1_DETAIL_SOURCES),
    _official_record("中国电信", "Q1 2023", "total_debt", 72298.237, "millions CNY", "中国电信2023年第一季度报告（IRAsia中文版）", CT_2023_Q1_CN_URL, "A股中文一季报资产负债表披露短期借款2,914.101百万元、一年内到期的非流动负债15,899.334百万元、长期借款4,069.727百万元、租赁负债49,415.075百万元，合计总债务72,298.237百万元。", "official_borrowings_plus_lease_liabilities_reconciliation", CT_2023_Q1_DETAIL_SOURCES),
    _official_record("中国电信", "Q1 2026", "capital_expenditures", -14692.492, "millions CNY", "中国电信2026年第一季度报告", CT_2026_Q1_CNINFO_URL, "合并现金流量表披露购建固定资产、无形资产和其他长期资产支付的现金14,692,492,358.74元；现金流出口径记为负数。", "official_cash_flow_statement_row_check", CT_2026_Q1_SOURCES),
    _official_record("中国电信", "Q1 2026", "cash_and_equivalents", 45662.846, "millions CNY", "中国电信2026年第一季度报告", CT_2026_Q1_CNINFO_URL, "合并现金流量表披露期末现金及现金等价物余额45,662,845,826.50元；该口径不同于资产负债表货币资金83,340,320,421.18元。", "official_cash_flow_statement_cash_equivalents_check", CT_2026_Q1_SOURCES),
    _official_record("中国电信", "Q1 2026", "ebitda", 33875, "millions CNY", "中国电信官网Key Financial Data季度表", CT_KEY_FINANCIAL_DATA_URL, "中国电信官网季度Key Financial Data列示2026/Q1 EBITDA为33,875百万元。", "official_quarterly_key_financial_data_check", CT_2026_Q1_SOURCES),
    _official_record("中国电信", "Q1 2026", "ebitda_margin", 25.669, "percent", "中国电信官网Key Financial Data季度表", CT_KEY_FINANCIAL_DATA_URL, "以官网季度表披露的2026/Q1 EBITDA 33,875百万元除以Operating Revenue 131,967百万元，EBITDA率为25.669%。", "official_ebitda_divided_by_revenue_reconciliation", CT_2026_Q1_SOURCES),
    _official_record("中国电信", "Q1 2026", "free_cash_flow", 8522.574, "millions CNY", "中国电信2026年第一季度报告", CT_2026_Q1_CNINFO_URL, "合并现金流量表披露经营现金流23,215.066百万元、购建长期资产现金支出14,692.492百万元；普通自由现金流复算为8,522.574百万元。", "official_operating_cash_flow_minus_capex_reconciliation", CT_2026_Q1_SOURCES),
    _official_record("中国电信", "Q1 2026", "gross_profit", 36952.797, "millions CNY", "中国电信2026年第一季度报告", CT_2026_Q1_CNINFO_URL, "合并利润表披露营业收入131,393.926百万元、营业成本94,441.130百万元；按收入减营业成本复算毛利为36,952.797百万元。", "official_revenue_minus_operating_cost_reconciliation", CT_2026_Q1_SOURCES),
    _official_record("中国电信", "Q1 2026", "gross_margin", 28.124, "percent", "中国电信2026年第一季度报告", CT_2026_Q1_CNINFO_URL, "以官方复算毛利36,952.797百万元除以营业收入131,393.926百万元，毛利率为28.124%。", "official_gross_profit_divided_by_revenue_reconciliation", CT_2026_Q1_SOURCES),
    _official_record("中国电信", "Q1 2026", "revenue_growth_yoy", -2.316, "percent", "中国电信2026年第一季度报告", CT_2026_Q1_CNINFO_URL, "一季报披露2026Q1营业收入131,393,926,307.26元、2025Q1营业收入134,508,815,336.06元，复算同比为-2.316%；主要会计数据表列示同比(2.32)%。", "official_current_prior_period_recalculation", CT_2026_Q1_SOURCES),
    _official_record("中国电信", "Q1 2026", "total_assets", 879079.074, "millions CNY", "中国电信2026年第一季度报告", CT_2026_Q1_CNINFO_URL, "合并资产负债表披露2026年3月31日资产总计879,079,073,895.15元。", "official_balance_sheet_row_check", CT_2026_Q1_SOURCES),
    _official_record("中国电信", "Q1 2026", "total_debt", 45696.975, "millions CNY", "中国电信2026年第一季度报告", CT_2026_Q1_CNINFO_URL, "合并资产负债表披露短期借款2,253.274百万元、一年内到期的非流动负债17,070.403百万元、长期借款5,596.990百万元、租赁负债20,776.308百万元，合计总债务45,696.975百万元。", "official_borrowings_plus_lease_liabilities_reconciliation", CT_2026_Q1_SOURCES),
    _official_record("中国电信", "Q1 2025", "cash_and_equivalents", 52811.129, "millions CNY", "中国电信2025年第一季度报告", CT_2025_Q1_CN_URL, "合并现金流量表披露期末现金及现金等价物余额52,811,129,449.13元；该口径不同于资产负债表货币资金89,788,544,306.86元。", "official_cash_flow_statement_cash_equivalents_check", CT_2025_Q1_SOURCES),
    _official_record("中国电信", "Q1 2025", "gross_profit", 39637.473, "millions CNY", "中国电信2025年第一季度报告", CT_2025_Q1_CN_URL, "合并利润表披露营业收入134,508.815百万元、营业成本94,871.343百万元；按收入减营业成本复算毛利为39,637.473百万元。", "official_revenue_minus_operating_cost_reconciliation", CT_2025_Q1_SOURCES),
    _official_record("中国电信", "Q1 2025", "gross_margin", 29.468, "percent", "中国电信2025年第一季度报告", CT_2025_Q1_CN_URL, "以官方复算毛利39,637.473百万元除以营业收入134,508.815百万元，毛利率为29.468%。", "official_gross_profit_divided_by_revenue_reconciliation", CT_2025_Q1_SOURCES),
    _official_record("中国电信", "Q1 2025", "revenue_growth_yoy", 0.011, "percent", "中国电信2025年第一季度报告", CT_2025_Q1_CN_URL, "一季报披露2025Q1营业收入134,508,815,336.06元、2024Q1营业收入134,494,562,936.36元，复算同比为0.011%；主要会计数据表列示同比0.01%。", "official_current_prior_period_recalculation", CT_2025_Q1_SOURCES),
    _official_record("中国电信", "Q1 2025", "total_debt", 57533.062, "millions CNY", "中国电信2025年第一季度报告", CT_2025_Q1_CN_URL, "合并资产负债表披露短期借款2,687.706百万元、一年内到期的非流动负债15,344.510百万元、长期借款7,260.081百万元、租赁负债32,240.764百万元，合计总债务57,533.062百万元。", "official_borrowings_plus_lease_liabilities_reconciliation", CT_2025_Q1_SOURCES),
    _official_record("中国电信", "Q2 2025", "cash_and_equivalents", 52959, "millions CNY", "中国电信2025年中期业绩公告", CT_2025_H1_HKEX_URL, "中期业绩公告资产负债表披露2025年6月30日Cash and cash equivalents为52,959百万元。", "official_interim_balance_sheet_point_check", CT_2025_Q2_DETAIL_SOURCES),
    _official_record("中国电信", "Q2 2025", "gross_profit", 43039.217, "millions CNY", "中国电信2025年半年度报告摘要", CT_2025_H1_CN_SUMMARY_URL, "半年度报告摘要披露H1营业收入269,421.737百万元、营业成本186,745.047百万元，H1毛利82,676.690百万元；减Q1官方毛利39,637.473百万元，复算Q2毛利为43,039.217百万元。该A股营业成本口径不同于标准化表。", "official_h1_minus_q1_revenue_minus_cost_reconciliation", CT_2025_Q2_DETAIL_SOURCES),
    _official_record("中国电信", "Q2 2025", "gross_margin", 31.901, "percent", "中国电信2025年半年度报告摘要", CT_2025_H1_CN_SUMMARY_URL, "以A股口径Q2毛利43,039.217百万元除以A股口径Q2营业收入134,912.921百万元，毛利率为31.901%；该口径不同于标准化表。", "official_gross_profit_divided_by_revenue_reconciliation", CT_2025_Q2_DETAIL_SOURCES),
    _official_record("中国电信", "Q2 2025", "revenue_growth_yoy", 2.606, "percent", "中国电信2025年中期业绩公告", CT_2025_H1_HKEX_URL, "H1经营收入271,469百万元减Q1经营收入135,498百万元，复算Q2经营收入135,971百万元；对比中国电信官网季度表2024/Q2 Operating Revenue 132,518百万元，Q2同比为2.606%。", "official_h1_minus_q1_prior_quarter_reconciliation", CT_2025_Q2_SOURCES),
    _official_record("中国电信", "Q2 2025", "total_assets", 887224, "millions CNY", "中国电信2025年中期业绩公告", CT_2025_H1_HKEX_URL, "中期业绩公告资产负债表披露2025年6月30日Total assets为887,224百万元。", "official_interim_balance_sheet_point_check", CT_2025_Q2_DETAIL_SOURCES),
    _official_record("中国电信", "Q2 2025", "total_debt", 56221, "millions CNY", "中国电信2025年中期业绩公告", CT_2025_H1_HKEX_URL, "中期业绩公告披露短期债务2,348百万元、一年内到期长期债务1,548百万元、一年内到期租赁负债13,995百万元、长期债务8,800百万元、租赁负债29,530百万元，合计总债务56,221百万元。", "official_borrowings_plus_lease_liabilities_reconciliation", CT_2025_Q2_DETAIL_SOURCES),
    _official_record("中国电信", "Q3 2025", "gross_profit", 36835.687, "millions CNY", "中国电信2025年前三季度报告（IRAsia中文版）", CT_2025_Q3_CN_URL, "三季报中文版披露前三季度营业收入394,269.976百万元、营业成本274,757.599百万元；减H1营业收入269,421.737百万元和营业成本186,745.047百万元后，Q3毛利为36,835.687百万元。该A股营业成本口径不同于标准化表。", "official_9m_minus_h1_revenue_minus_cost_reconciliation", CT_2025_Q3_DETAIL_SOURCES),
    _official_record("中国电信", "Q3 2025", "gross_margin", 29.504, "percent", "中国电信2025年前三季度报告（IRAsia中文版）", CT_2025_Q3_CN_URL, "以A股口径Q3毛利36,835.687百万元除以A股口径Q3营业收入124,848.240百万元，毛利率为29.504%；该口径不同于标准化表。", "official_gross_profit_divided_by_revenue_reconciliation", CT_2025_Q3_DETAIL_SOURCES),
    _official_record("中国电信", "Q3 2025", "revenue_growth_yoy", -0.930, "percent", "中国电信2025年前三季度报告（港交所/IRAsia）", CT_2025_Q3_HKEX_URL, "港股前三季度Operating revenues 396,998百万元减H1经营收入271,469百万元，复算Q3经营收入125,529百万元；对比中国电信官网季度表2024/Q3 Operating Revenue 126,707百万元，Q3同比为-0.930%。", "official_9m_minus_h1_prior_quarter_reconciliation", CT_2025_Q3_DETAIL_SOURCES),
    _official_record("中国电信", "Q3 2025", "total_debt", 53059.100, "millions CNY", "中国电信2025年前三季度报告（IRAsia中文版）", CT_2025_Q3_CN_URL, "三季报资产负债表披露短期借款2,289.176百万元、一年内到期的非流动负债15,806.661百万元、长期借款7,551.291百万元、租赁负债27,411.972百万元，合计总债务53,059.100百万元。", "official_borrowings_plus_lease_liabilities_reconciliation", CT_2025_Q3_DETAIL_SOURCES),
    _official_record("中国电信", "Q4 2025", "cash_and_equivalents", 61393.795, "millions CNY", "中国电信2025年度A股年报", CT_2025_ANNUAL_ASHARE_URL, "A股年报现金流量表披露年末现金及现金等价物余额61,393,794,753.70元；该口径不同于标准化表。", "official_cash_flow_statement_cash_equivalents_check", CT_2025_Q4_DETAIL_SOURCES),
    _official_record("中国电信", "Q4 2025", "gross_profit", 32850.783, "millions CNY", "中国电信2025年度A股年报", CT_2025_ANNUAL_ASHARE_URL, "A股年报披露全年营业收入523,924.731百万元、营业成本371,561.571百万元；减前三季度营业收入394,269.976百万元和营业成本274,757.599百万元后，Q4毛利为32,850.783百万元。", "official_full_year_minus_9m_revenue_minus_cost_reconciliation", CT_2025_Q4_DETAIL_SOURCES),
    _official_record("中国电信", "Q4 2025", "gross_margin", 25.337, "percent", "中国电信2025年度A股年报", CT_2025_ANNUAL_ASHARE_URL, "以A股口径Q4毛利32,850.783百万元除以A股口径Q4营业收入129,654.755百万元，毛利率为25.337%。", "official_gross_profit_divided_by_revenue_reconciliation", CT_2025_Q4_DETAIL_SOURCES),
    _official_record("中国电信", "Q4 2025", "operating_income", 6011.885, "millions CNY", "中国电信2025年度A股年报", CT_2025_ANNUAL_ASHARE_URL, "A股年报披露全年营业利润45,855.348百万元；减三季报前三季度营业利润39,843.463百万元，Q4营业利润为6,011.885百万元。", "official_full_year_minus_9m_operating_profit_reconciliation", CT_2025_Q4_DETAIL_SOURCES),
    _official_record("中国电信", "Q4 2025", "operating_margin", 4.637, "percent", "中国电信2025年度A股年报", CT_2025_ANNUAL_ASHARE_URL, "以A股口径Q4营业利润6,011.885百万元除以Q4营业收入129,654.755百万元，经营利润率为4.637%。", "official_operating_income_divided_by_revenue_reconciliation", CT_2025_Q4_DETAIL_SOURCES),
    _official_record("中国电信", "Q4 2025", "revenue_growth_yoy", -1.479, "percent", "中国电信2025年度A股年报", CT_2025_ANNUAL_ASHARE_URL, "A股口径2025Q4营业收入由全年523,924.731百万元减前三季度394,269.976百万元得129,654.755百万元；2024Q4由全年523,568.920百万元减前三季度391,968.019百万元得131,600.901百万元，复算同比为-1.479%。", "official_full_year_minus_9m_prior_year_reconciliation", CT_2025_Q4_DETAIL_SOURCES),
    _official_record("中国电信", "Q4 2025", "total_assets", 870643.643, "millions CNY", "中国电信2025年度A股年报", CT_2025_ANNUAL_ASHARE_URL, "A股年报合并资产负债表披露2025年12月31日资产总计870,643,642,518.74元。", "official_balance_sheet_row_check", CT_2025_Q4_DETAIL_SOURCES),
    _official_record("中国电信", "Q4 2025", "total_debt", 49676.795, "millions CNY", "中国电信2025年度A股年报", CT_2025_ANNUAL_ASHARE_URL, "A股年报资产负债表披露短期借款2,448.392百万元、一年内到期的非流动负债16,067.835百万元、长期借款6,109.172百万元、租赁负债25,051.396百万元，合计总债务49,676.795百万元。", "official_borrowings_plus_lease_liabilities_reconciliation", CT_2025_Q4_DETAIL_SOURCES),
    _official_record("中国电信", "Q1 2024", "capital_expenditures", -14713.004, "millions CNY", "中国电信2024年第一季度报告", CT_2024_Q1_CN_URL, "合并现金流量表披露购建固定资产、无形资产和其他长期资产支付的现金14,713,004,349.22元；现金流出口径记为负数。", "official_cash_flow_statement_row_check", CT_2024_Q1_DETAIL_SOURCES),
    _official_record("中国电信", "Q1 2024", "cash_and_equivalents", 71552.946, "millions CNY", "中国电信2024年第一季度报告", CT_2024_Q1_CN_URL, "合并现金流量表披露期末现金及现金等价物余额71,552,945,610.96元；该口径不同于资产负债表货币资金87,925,041,457.33元。", "official_cash_flow_statement_cash_equivalents_check", CT_2024_Q1_DETAIL_SOURCES),
    _official_record("中国电信", "Q1 2024", "free_cash_flow", 6148.771, "millions CNY", "中国电信2024年第一季度报告", CT_2024_Q1_CN_URL, "合并现金流量表披露经营现金流20,861.776百万元、购建长期资产现金支出14,713.004百万元；普通自由现金流复算为6,148.771百万元。", "official_operating_cash_flow_minus_capex_reconciliation", CT_2024_Q1_DETAIL_SOURCES),
    _official_record("中国电信", "Q1 2024", "gross_profit", 39548.432, "millions CNY", "中国电信2024年第一季度报告", CT_2024_Q1_CN_URL, "合并利润表披露营业收入134,494.563百万元、营业成本94,946.131百万元；按收入减营业成本复算毛利为39,548.432百万元。", "official_revenue_minus_operating_cost_reconciliation", CT_2024_Q1_DETAIL_SOURCES),
    _official_record("中国电信", "Q1 2024", "gross_margin", 29.405, "percent", "中国电信2024年第一季度报告", CT_2024_Q1_CN_URL, "以官方复算毛利39,548.432百万元除以营业收入134,494.563百万元，毛利率为29.405%。", "official_gross_profit_divided_by_revenue_reconciliation", CT_2024_Q1_DETAIL_SOURCES),
    _official_record("中国电信", "Q1 2024", "operating_cash_flow", 20861.776, "millions CNY", "中国电信2024年第一季度报告", CT_2024_Q1_CN_URL, "合并现金流量表披露经营活动产生的现金流量净额20,861,775,770.24元。", "official_cash_flow_statement_row_check", CT_2024_Q1_DETAIL_SOURCES),
    _official_record("中国电信", "Q1 2024", "operating_income", 12316.258, "millions CNY", "中国电信2024年第一季度报告", CT_2024_Q1_CN_URL, "合并利润表披露营业利润12,316,258,235.55元。", "official_income_statement_row_check", CT_2024_Q1_DETAIL_SOURCES),
    _official_record("中国电信", "Q1 2024", "operating_margin", 9.157, "percent", "中国电信2024年第一季度报告", CT_2024_Q1_CN_URL, "以营业利润12,316.258百万元除以营业收入134,494.563百万元，经营利润率为9.157%。", "official_operating_income_divided_by_revenue_reconciliation", CT_2024_Q1_DETAIL_SOURCES),
    _official_record("中国电信", "Q1 2024", "revenue_growth_yoy", 3.654, "percent", "中国电信2024年第一季度报告", CT_2024_Q1_CN_URL, "合并利润表披露2024Q1营业收入134,494,562,936.36元、2023Q1营业收入129,753,222,753.19元，复算同比为3.654%；主要会计数据表列示同比3.7%。", "official_current_prior_period_recalculation", CT_2024_Q1_DETAIL_SOURCES),
    _official_record("中国电信", "Q1 2024", "total_assets", 848805.995, "millions CNY", "中国电信2024年第一季度报告", CT_2024_Q1_CN_URL, "合并资产负债表披露2024年3月31日资产总计848,805,995,409.05元。", "official_balance_sheet_row_check", CT_2024_Q1_DETAIL_SOURCES),
    _official_record("中国电信", "Q1 2024", "total_debt", 62996.364, "millions CNY", "中国电信2024年第一季度报告", CT_2024_Q1_CN_URL, "合并资产负债表披露短期借款2,887.727百万元、一年内到期的非流动负债14,389.087百万元、长期借款5,183.815百万元、租赁负债40,535.734百万元，合计总债务62,996.364百万元。", "official_borrowings_plus_lease_liabilities_reconciliation", CT_2024_Q1_DETAIL_SOURCES),
    *CU_2019_OFFICIAL_VERIFICATIONS,
    *CU_2020_OFFICIAL_VERIFICATIONS,
    *CU_2021_OFFICIAL_VERIFICATIONS,
    *CU_2021_DETAIL_OFFICIAL_VERIFICATIONS,
    *CU_2022_OFFICIAL_VERIFICATIONS,
    *CU_2022_DETAIL_OFFICIAL_VERIFICATIONS,
    *CU_2017_OFFICIAL_VERIFICATIONS,
    *CU_2018_OFFICIAL_VERIFICATIONS,
    *CU_2023_OFFICIAL_VERIFICATIONS,
    *CU_2023_DETAIL_OFFICIAL_VERIFICATIONS,
    *CU_2024_OFFICIAL_VERIFICATIONS,
    *CU_2024_DETAIL_OFFICIAL_VERIFICATIONS,
    _official_record("中国联通", "Q1 2026", "cash_and_equivalents", 22378.803, "millions CNY", "中国联通2026年第一季度报告", CU_2026_Q1_SSE_URL, "合并现金流量表披露期末现金及现金等价物余额22,378,803,128元；该口径不同于资产负债表货币资金37,855,988,296元。", "official_cash_flow_statement_cash_equivalents_check", CU_2026_Q1_SOURCES),
    _official_record("中国联通", "Q1 2026", "gross_profit", 24398.058, "millions CNY", "中国联通2026年第一季度报告", CU_2026_Q1_SSE_URL, "合并利润表披露营业收入102,824.251百万元、营业成本78,426.193百万元；按收入减营业成本复算毛利为24,398.058百万元。", "official_revenue_minus_operating_cost_reconciliation", CU_2026_Q1_SOURCES),
    _official_record("中国联通", "Q1 2026", "gross_margin", 23.728, "percent", "中国联通2026年第一季度报告", CU_2026_Q1_SSE_URL, "以官方复算毛利24,398.058百万元除以营业收入102,824.251百万元，毛利率为23.728%。", "official_gross_profit_divided_by_revenue_reconciliation", CU_2026_Q1_SOURCES),
    _official_record("中国联通", "Q1 2026", "operating_income", 5871.361, "millions CNY", "中国联通2026年第一季度报告", CU_2026_Q1_SSE_URL, "合并利润表披露营业利润5,871,361,201元。", "official_income_statement_row_check", CU_2026_Q1_SOURCES),
    _official_record("中国联通", "Q1 2026", "operating_margin", 5.710, "percent", "中国联通2026年第一季度报告", CU_2026_Q1_SSE_URL, "以营业利润5,871.361百万元除以营业收入102,824.251百万元，经营利润率为5.710%。", "official_operating_income_divided_by_revenue_reconciliation", CU_2026_Q1_SOURCES),
    _official_record("中国联通", "Q1 2026", "total_assets", 670198.478, "millions CNY", "中国联通2026年第一季度报告", CU_2026_Q1_SSE_URL, "合并资产负债表披露2026年3月31日资产总计670,198,478,474元。", "official_balance_sheet_row_check", CU_2026_Q1_SOURCES),
    _official_record("中国联通", "Q1 2026", "total_debt", 33036.873, "millions CNY", "中国联通2026年第一季度报告", CU_2026_Q1_SSE_URL, "合并资产负债表披露短期借款1,019.696百万元、一年内到期的非流动负债12,374.740百万元、长期借款4,708.034百万元、租赁负债14,934.404百万元，合计总债务33,036.873百万元。", "official_borrowings_plus_lease_liabilities_reconciliation", CU_2026_Q1_SOURCES),
    *TOWER_2019_OFFICIAL_VERIFICATIONS,
    *TOWER_2017_2018_OFFICIAL_VERIFICATIONS,
    *TOWER_2020_OFFICIAL_VERIFICATIONS,
    *TOWER_2021_OFFICIAL_VERIFICATIONS,
    *TOWER_2021_2022_DETAIL_OFFICIAL_VERIFICATIONS,
    *TOWER_2022_OFFICIAL_VERIFICATIONS,
    *TOWER_2023_OFFICIAL_VERIFICATIONS,
    *TOWER_2024_OFFICIAL_VERIFICATIONS,
    *TOWER_EXTRA_OFFICIAL_VERIFICATIONS,
    {
        "subject": "中国移动",
        "period": "Q1 2026",
        "metric_key": "revenue",
        "official_value": 266478,
        "unit": "millions CNY",
        "source_label": "中国移动2026年第一季度报告",
        "source_url": "https://dataclouds.cninfo.com.cn/shgonggao/hsomarket/2026/20260420/c34d1cf7b4794bebb3f39acf8b598c4b.PDF",
        "evidence": "合并利润表：营业收入 266,478 百万元。",
    },
    {
        "subject": "中国移动",
        "period": "Q1 2026",
        "metric_key": "operating_revenue",
        "official_value": 219900,
        "unit": "millions CNY",
        "source_label": "中国移动2026年第一季度报告",
        "source_url": "https://dataclouds.cninfo.com.cn/shgonggao/hsomarket/2026/20260420/c34d1cf7b4794bebb3f39acf8b598c4b.PDF",
        "evidence": "主要会计数据：主营业务收入 2,199 亿元。",
    },
    {
        "subject": "中国移动",
        "period": "Q1 2026",
        "metric_key": "net_income",
        "official_value": 29342,
        "unit": "millions CNY",
        "source_label": "中国移动2026年第一季度报告",
        "source_url": "https://dataclouds.cninfo.com.cn/shgonggao/hsomarket/2026/20260420/c34d1cf7b4794bebb3f39acf8b598c4b.PDF",
        "evidence": "合并利润表：归属于母公司股东的净利润 29,342 百万元。",
    },
    {
        "subject": "中国移动",
        "period": "Q1 2026",
        "metric_key": "operating_cash_flow",
        "official_value": 71447,
        "unit": "millions CNY",
        "source_label": "中国移动2026年第一季度报告",
        "source_url": "https://dataclouds.cninfo.com.cn/shgonggao/hsomarket/2026/20260420/c34d1cf7b4794bebb3f39acf8b598c4b.PDF",
        "evidence": "合并现金流量表：经营活动产生的现金流量净额 71,447 百万元。",
    },
    {
        "subject": "中国移动",
        "period": "Q1 2026",
        "metric_key": "capital_expenditures",
        "official_value": -30399,
        "unit": "millions CNY",
        "source_label": "中国移动2026年第一季度报告",
        "source_url": "https://dataclouds.cninfo.com.cn/shgonggao/hsomarket/2026/20260420/c34d1cf7b4794bebb3f39acf8b598c4b.PDF",
        "evidence": "合并现金流量表：购建固定资产、无形资产和其他长期资产支付的现金 -30,399 百万元。",
    },
    {
        "subject": "中国移动",
        "period": "Q1 2026",
        "metric_key": "free_cash_flow",
        "official_value": 41048,
        "unit": "millions CNY",
        "source_label": "中国移动2026年第一季度报告",
        "source_url": "https://dataclouds.cninfo.com.cn/shgonggao/hsomarket/2026/20260420/c34d1cf7b4794bebb3f39acf8b598c4b.PDF",
        "evidence": "合并现金流量表披露经营现金流71,447百万元、购建长期资产现金支出30,399百万元；自由现金流按经营现金流减资本开支复算为41,048百万元。",
        "verification_method": "official_operating_cash_flow_minus_capex_reconciliation",
    },
    {
        "subject": "中国移动",
        "period": "Q1 2026",
        "metric_key": "ebitda",
        "official_value": 76700,
        "unit": "millions CNY",
        "source_label": "中国移动2026年第一季度报告",
        "source_url": "https://dataclouds.cninfo.com.cn/shgonggao/hsomarket/2026/20260420/c34d1cf7b4794bebb3f39acf8b598c4b.PDF",
        "evidence": "主要财务指标：EBITDA 767 亿元。",
    },
    {
        "subject": "中国电信",
        "period": "Q1 2026",
        "metric_key": "revenue",
        "official_value": 131393.926,
        "unit": "millions CNY",
        "source_label": "中国电信2026年第一季度报告",
        "source_url": CT_2026_Q1_CNINFO_URL,
        "evidence": "主要会计数据/合并利润表：营业收入 131,393,926,307.26 元。",
        "verification_sources": CT_2026_Q1_SOURCES,
    },
    {
        "subject": "中国电信",
        "period": "Q1 2026",
        "metric_key": "service_revenue",
        "official_value": 122700,
        "unit": "millions CNY",
        "source_label": "中国电信2026年第一季度报告",
        "source_url": CT_2026_Q1_CNINFO_URL,
        "evidence": "经营回顾：服务收入为人民币 1,227 亿元。",
        "verification_sources": CT_2026_Q1_SOURCES,
    },
    {
        "subject": "中国电信",
        "period": "Q1 2026",
        "metric_key": "net_income",
        "official_value": 7350.128,
        "unit": "millions CNY",
        "source_label": "中国电信2026年第一季度报告",
        "source_url": CT_2026_Q1_CNINFO_URL,
        "evidence": "主要会计数据：归属于上市公司股东的净利润 7,350,127,688.98 元。",
        "verification_sources": CT_2026_Q1_SOURCES,
    },
    {
        "subject": "中国电信",
        "period": "Q1 2026",
        "metric_key": "operating_cash_flow",
        "official_value": 23215.066,
        "unit": "millions CNY",
        "source_label": "中国电信2026年第一季度报告",
        "source_url": CT_2026_Q1_CNINFO_URL,
        "evidence": "主要会计数据：经营活动产生的现金流量净额 23,215,066,427.94 元。",
        "verification_sources": CT_2026_Q1_SOURCES,
    },
    {
        "subject": "中国电信",
        "period": "Q1 2026",
        "metric_key": "operating_income",
        "official_value": 9477.563,
        "unit": "millions CNY",
        "source_label": "中国电信2026年第一季度报告",
        "source_url": CT_2026_Q1_CNINFO_URL,
        "evidence": "合并利润表：营业利润 9,477,562,556.67 元。",
        "verification_sources": CT_2026_Q1_SOURCES,
    },
    {
        "subject": "中国联通",
        "period": "Q1 2026",
        "metric_key": "revenue",
        "official_value": 102824.251,
        "unit": "millions CNY",
        "source_label": "中国联通2026年第一季度报告（上交所）",
        "source_url": "https://static.sse.com.cn/disclosure/listedinfo/announcement/c/new/2026-04-22/600050_20260422_763Q.pdf",
        "evidence": "主要会计数据/合并利润表：营业收入 102,824,251,223 元。",
    },
    {
        "subject": "中国联通",
        "period": "Q1 2026",
        "metric_key": "revenue_growth_yoy",
        "official_value": -0.5,
        "unit": "percent",
        "source_label": "中国联通2026年第一季度报告（上交所）",
        "source_url": "https://static.sse.com.cn/disclosure/listedinfo/announcement/c/new/2026-04-22/600050_20260422_763Q.pdf",
        "evidence": "主要会计数据：营业收入本报告期 102,824,251,223 元，上年同期 103,353,771,882 元，同期增减 -0.5%。",
    },
    {
        "subject": "中国联通",
        "period": "Q1 2026",
        "metric_key": "net_income",
        "official_value": 4857.161,
        "unit": "millions CNY",
        "source_label": "中国联通2026年第一季度报告（上交所）",
        "source_url": "https://static.sse.com.cn/disclosure/listedinfo/announcement/c/new/2026-04-22/600050_20260422_763Q.pdf",
        "evidence": "合并利润表：净利润 4,857,160,535 元；同一摘要页另披露归属于上市公司股东的净利润 2,136,922,138 元（A股股东口径）。",
    },
    {
        "subject": "中国联通",
        "period": "Q1 2026",
        "metric_key": "operating_cash_flow",
        "official_value": 7543.905,
        "unit": "millions CNY",
        "source_label": "中国联通2026年第一季度报告（上交所）",
        "source_url": "https://static.sse.com.cn/disclosure/listedinfo/announcement/c/new/2026-04-22/600050_20260422_763Q.pdf",
        "evidence": "主要会计数据：经营活动产生的现金流量净额 7,543,904,777 元。",
    },
    {
        "subject": "中国联通",
        "period": "Q1 2026",
        "metric_key": "capital_expenditures",
        "official_value": -13653.265,
        "unit": "millions CNY",
        "source_label": "中国联通2026年第一季度报告（上交所）",
        "source_url": "https://static.sse.com.cn/disclosure/listedinfo/announcement/c/new/2026-04-22/600050_20260422_763Q.pdf",
        "evidence": "合并现金流量表：购建固定资产、无形资产和其他长期资产支付的现金 13,653,264,522 元；现金流出口径在本数据包中记为负数。",
    },
    {
        "subject": "中国联通",
        "period": "Q1 2026",
        "metric_key": "free_cash_flow",
        "official_value": -6109.360,
        "unit": "millions CNY",
        "source_label": "中国联通2026年第一季度报告（上交所）",
        "source_url": "https://static.sse.com.cn/disclosure/listedinfo/announcement/c/new/2026-04-22/600050_20260422_763Q.pdf",
        "evidence": "合并现金流量表披露经营现金流7,543.905百万元、购建长期资产现金支出13,653.265百万元；自由现金流按经营现金流减资本开支复算为-6,109.360百万元。",
        "verification_method": "official_operating_cash_flow_minus_capex_reconciliation",
    },
    {
        "subject": "中国铁塔",
        "period": "Q1 2026",
        "metric_key": "revenue",
        "official_value": 25146,
        "unit": "millions CNY",
        "source_label": "中国铁塔2026年第一季度未经审核的主要运营数据",
        "source_url": "https://doc.irasia.com/listco/hk/chinatower/interim/2026/int1q.pdf",
        "evidence": "2026年第一季度，公司营业收入实现人民币251.46亿元；表格列示营业收入 25,146 百万元。",
    },
    {
        "subject": "中国铁塔",
        "period": "Q1 2026",
        "metric_key": "revenue_growth_yoy",
        "official_value": 1.5,
        "unit": "percent",
        "source_label": "中国铁塔2026年第一季度未经审核的主要运营数据",
        "source_url": "https://doc.irasia.com/listco/hk/chinatower/interim/2026/int1q.pdf",
        "evidence": "2026年第一季度，公司营业收入实现人民币251.46亿元，同比增长1.5%。",
    },
    {
        "subject": "中国铁塔",
        "period": "Q1 2026",
        "metric_key": "operator_business_revenue",
        "official_value": 21089,
        "unit": "millions CNY",
        "source_label": "中国铁塔2026年第一季度未经审核的主要运营数据",
        "source_url": "https://doc.irasia.com/listco/hk/chinatower/interim/2026/int1q.pdf",
        "evidence": "2026年第一季度，运营商业务收入实现人民币210.89亿元；表格列示运营商业务 21,089 百万元。",
    },
    {
        "subject": "中国铁塔",
        "period": "Q1 2026",
        "metric_key": "tower_business_revenue",
        "official_value": 18560,
        "unit": "millions CNY",
        "source_label": "中国铁塔2026年第一季度未经审核的主要运营数据",
        "source_url": "https://doc.irasia.com/listco/hk/chinatower/interim/2026/int1q.pdf",
        "evidence": "表格列示塔类业务收入 18,560 百万元。",
    },
    {
        "subject": "中国铁塔",
        "period": "Q1 2026",
        "metric_key": "das_business_revenue",
        "official_value": 2529,
        "unit": "millions CNY",
        "source_label": "中国铁塔2026年第一季度未经审核的主要运营数据",
        "source_url": "https://doc.irasia.com/listco/hk/chinatower/interim/2026/int1q.pdf",
        "evidence": "表格列示室分业务收入 2,529 百万元。",
    },
    {
        "subject": "中国铁塔",
        "period": "Q1 2026",
        "metric_key": "smart_business_revenue",
        "official_value": 2643,
        "unit": "millions CNY",
        "source_label": "中国铁塔2026年第一季度未经审核的主要运营数据",
        "source_url": "https://doc.irasia.com/listco/hk/chinatower/interim/2026/int1q.pdf",
        "evidence": "2026年第一季度，智联业务收入实现人民币26.43亿元；表格列示智联业务 2,643 百万元。",
    },
    {
        "subject": "中国铁塔",
        "period": "Q1 2026",
        "metric_key": "energy_business_revenue",
        "official_value": 1307,
        "unit": "millions CNY",
        "source_label": "中国铁塔2026年第一季度未经审核的主要运营数据",
        "source_url": "https://doc.irasia.com/listco/hk/chinatower/interim/2026/int1q.pdf",
        "evidence": "2026年第一季度，能源业务收入实现人民币13.07亿元；表格列示能源业务 1,307 百万元。",
    },
    {
        "subject": "中国铁塔",
        "period": "Q1 2026",
        "metric_key": "ebitda",
        "official_value": 15366,
        "unit": "millions CNY",
        "source_label": "中国铁塔2026年第一季度未经审核的主要运营数据",
        "source_url": "https://doc.irasia.com/listco/hk/chinatower/interim/2026/int1q.pdf",
        "evidence": "2026年第一季度，EBITDA实现人民币153.66亿元；表格列示 EBITDA 15,366 百万元。",
    },
    {
        "subject": "中国铁塔",
        "period": "Q1 2026",
        "metric_key": "ebitda_margin",
        "official_value": 61.1,
        "unit": "percent",
        "source_label": "中国铁塔2026年第一季度未经审核的主要运营数据",
        "source_url": "https://doc.irasia.com/listco/hk/chinatower/interim/2026/int1q.pdf",
        "evidence": "2026年第一季度，EBITDA率为61.1%。",
    },
    {
        "subject": "中国铁塔",
        "period": "Q1 2026",
        "metric_key": "net_income",
        "official_value": 3985,
        "unit": "millions CNY",
        "source_label": "中国铁塔2026年第一季度未经审核的主要运营数据",
        "source_url": "https://doc.irasia.com/listco/hk/chinatower/interim/2026/int1q.pdf",
        "evidence": "归属于本公司股东的利润为人民币39.85亿元；表格列示归属于本公司股东的利润 3,985 百万元。",
    },
    {
        "subject": "中国移动",
        "period": "Q1 2025",
        "metric_key": "revenue",
        "official_value": 263760,
        "unit": "millions CNY",
        "source_label": "中国移动2025年第一季度报告（上交所）",
        "source_url": CM_2025_Q1_SSE_URL,
        "evidence": "合并利润表：营业收入 263,760 百万元。",
        "verification_sources": CM_2025_Q1_DETAIL_SOURCES,
    },
    {
        "subject": "中国移动",
        "period": "Q1 2025",
        "metric_key": "operating_revenue",
        "official_value": 222400,
        "unit": "millions CNY",
        "source_label": "中国移动2025年第一季度报告（上交所）",
        "source_url": CM_2025_Q1_SSE_URL,
        "evidence": "主要财务数据：主营业务收入 2,224 亿元。",
        "verification_sources": CM_2025_Q1_DETAIL_SOURCES,
    },
    {
        "subject": "中国移动",
        "period": "Q1 2025",
        "metric_key": "net_income",
        "official_value": 30631,
        "unit": "millions CNY",
        "source_label": "中国移动2025年第一季度报告（上交所）",
        "source_url": CM_2025_Q1_SSE_URL,
        "evidence": "合并利润表：归属于母公司股东的净利润 30,631 百万元。",
        "verification_sources": CM_2025_Q1_DETAIL_SOURCES,
    },
    {
        "subject": "中国移动",
        "period": "Q1 2025",
        "metric_key": "operating_cash_flow",
        "official_value": 31317,
        "unit": "millions CNY",
        "source_label": "中国移动2025年第一季度报告（上交所）",
        "source_url": CM_2025_Q1_SSE_URL,
        "evidence": "合并现金流量表：经营活动产生的现金流量净额 31,317 百万元。",
        "verification_sources": CM_2025_Q1_DETAIL_SOURCES,
    },
    {
        "subject": "中国移动",
        "period": "Q1 2025",
        "metric_key": "capital_expenditures",
        "official_value": -36382,
        "unit": "millions CNY",
        "source_label": "中国移动2025年第一季度报告（上交所）",
        "source_url": CM_2025_Q1_SSE_URL,
        "evidence": "合并现金流量表：购建固定资产、无形资产和其他长期资产支付的现金 -36,382 百万元。",
        "verification_sources": CM_2025_Q1_DETAIL_SOURCES,
    },
    {
        "subject": "中国移动",
        "period": "Q1 2025",
        "metric_key": "free_cash_flow",
        "official_value": -5065,
        "unit": "millions CNY",
        "source_label": "中国移动2025年第一季度报告（上交所）",
        "source_url": CM_2025_Q1_SSE_URL,
        "evidence": "合并现金流量表披露经营现金流31,317百万元、购建长期资产现金支出36,382百万元；自由现金流按经营现金流减资本开支复算为-5,065百万元。",
        "verification_method": "official_operating_cash_flow_minus_capex_reconciliation",
        "verification_sources": CM_2025_Q1_DETAIL_SOURCES,
    },
    {
        "subject": "中国移动",
        "period": "Q1 2025",
        "metric_key": "ebitda",
        "official_value": 80700,
        "unit": "millions CNY",
        "source_label": "中国移动2025年第一季度报告（上交所）",
        "source_url": CM_2025_Q1_SSE_URL,
        "evidence": "主要财务指标：EBITDA 807 亿元。",
        "verification_sources": CM_2025_Q1_DETAIL_SOURCES,
    },
    {
        "subject": "中国移动",
        "period": "Q1 2025",
        "metric_key": "operating_income",
        "official_value": 39016,
        "unit": "millions CNY",
        "source_label": "中国移动2025年第一季度报告（上交所）",
        "source_url": CM_2025_Q1_SSE_URL,
        "evidence": "合并利润表：营业利润 39,016 百万元；该中国会计准则口径可能与标准化表的 operating income 定义不同。",
        "verification_sources": CM_2025_Q1_DETAIL_SOURCES,
    },
    {
        "subject": "中国移动",
        "period": "Q1 2025",
        "metric_key": "total_assets",
        "official_value": 2090272,
        "unit": "millions CNY",
        "source_label": "中国移动2025年第一季度报告（上交所）",
        "source_url": CM_2025_Q1_SSE_URL,
        "evidence": "合并资产负债表：总资产 2,090,272 百万元。",
        "verification_sources": CM_2025_Q1_DETAIL_SOURCES,
    },
    _official_record("中国移动", "Q1 2025", "cash_and_equivalents", 125078, "millions CNY", "中国移动2025年第一季度报告（上交所）", CM_2025_Q1_SSE_URL, "合并现金流量表披露期末现金及现金等价物余额125,078百万元；该口径不同于资产负债表货币资金220,208百万元。", "official_cash_flow_statement_cash_equivalents_check", CM_2025_Q1_DETAIL_SOURCES),
    _official_record("中国移动", "Q1 2025", "gross_profit", 71018, "millions CNY", "中国移动2025年第一季度报告（上交所）", CM_2025_Q1_SSE_URL, "合并利润表披露营业收入263,760百万元、营业成本192,742百万元；按收入减营业成本复算毛利为71,018百万元。", "official_revenue_minus_operating_cost_reconciliation", CM_2025_Q1_DETAIL_SOURCES),
    _official_record("中国移动", "Q1 2025", "gross_margin", 26.925, "percent", "中国移动2025年第一季度报告（上交所）", CM_2025_Q1_SSE_URL, "以官方复算毛利71,018百万元除以营业收入263,760百万元，毛利率为26.925%。", "official_gross_profit_divided_by_revenue_reconciliation", CM_2025_Q1_DETAIL_SOURCES),
    _official_record("中国移动", "Q1 2025", "revenue_growth_yoy", 0.020, "percent", "中国移动2025年第一季度报告（上交所）", CM_2025_Q1_SSE_URL, "一季报披露2025Q1营业收入263,760百万元、2024Q1营业收入263,707百万元，复算同比为0.020%；主要财务指标表列示同比增长0.0%。", "official_current_prior_period_recalculation", CM_2025_Q1_DETAIL_SOURCES),
    _official_record("中国移动", "Q1 2025", "total_debt", 94802, "millions CNY", "中国移动2025年第一季度报告（上交所）", CM_2025_Q1_SSE_URL, "合并资产负债表披露一年内到期的非流动负债33,563百万元、租赁负债61,239百万元，未列短期或长期借款，合计总债务94,802百万元。", "official_borrowings_plus_lease_liabilities_reconciliation", CM_2025_Q1_DETAIL_SOURCES),
    _official_record("中国移动", "Q2 2025", "cash_and_equivalents", 94566, "millions CNY", "中国移动2025中期报告（港交所，现金流口径）", CM_2025_H1_HKEX_URL, "中期报告现金流量表披露2025年6月30日现金及现金等价物余额94,566百万元；该口径不同于资产负债表货币资金190,262百万元。", "official_cash_flow_statement_cash_equivalents_check", CM_2025_Q2_DETAIL_SOURCES),
    _official_record("中国移动", "Q2 2025", "gross_profit", 100900, "millions CNY", "中国移动2025年半年度报告（巨潮资讯原文）", CM_2025_H1_CNINFO_URL, "A股半年报披露H1营业收入543,769百万元、营业成本371,851百万元；减Q1营业收入263,760百万元和营业成本192,742百万元后，Q2毛利为100,900百万元。", "official_h1_minus_q1_revenue_minus_cost_reconciliation", CM_2025_Q2_DETAIL_SOURCES),
    _official_record("中国移动", "Q2 2025", "gross_margin", 36.034, "percent", "中国移动2025年半年度报告（巨潮资讯原文）", CM_2025_H1_CNINFO_URL, "以A股口径Q2毛利100,900百万元除以Q2营业收入280,009百万元，毛利率为36.034%。", "official_gross_profit_divided_by_revenue_reconciliation", CM_2025_Q2_DETAIL_SOURCES),
    _official_record("中国移动", "Q2 2025", "operating_income", 67279, "millions CNY", "中国移动2025年半年度报告（巨潮资讯原文）", CM_2025_H1_CNINFO_URL, "A股半年报披露H1营业利润106,295百万元；减Q1营业利润39,016百万元，复算Q2营业利润为67,279百万元。", "official_h1_minus_q1_operating_profit_reconciliation", CM_2025_Q2_DETAIL_SOURCES),
    _official_record("中国移动", "Q2 2025", "operating_margin", 24.027, "percent", "中国移动2025年半年度报告（巨潮资讯原文）", CM_2025_H1_CNINFO_URL, "以A股口径Q2营业利润67,279百万元除以Q2营业收入280,009百万元，经营利润率为24.027%。", "official_operating_income_divided_by_revenue_reconciliation", CM_2025_Q2_DETAIL_SOURCES),
    _official_record("中国移动", "Q2 2025", "revenue_growth_yoy", -1.070, "percent", "中国移动2025年半年度报告（巨潮资讯原文）", CM_2025_H1_CNINFO_URL, "A股口径2025Q2营业收入由H1 543,769减Q1 263,760得280,009百万元；对比2024Q2官方营业收入283,037百万元，复算同比为-1.070%。", "official_h1_minus_q1_prior_quarter_reconciliation", CM_2025_Q2_DETAIL_SOURCES),
    _official_record("中国移动", "Q2 2025", "total_assets", 2092440, "millions CNY", "中国移动2025年半年度报告（巨潮资讯原文）", CM_2025_H1_CNINFO_URL, "A股半年报合并资产负债表披露2025年6月30日资产总计2,092,440百万元；摘要披露资产总额20,924亿元。", "official_balance_sheet_row_check", CM_2025_Q2_DETAIL_SOURCES),
    _official_record("中国移动", "Q2 2025", "total_debt", 91932, "millions CNY", "中国移动2025年半年度报告（巨潮资讯原文）", CM_2025_H1_CNINFO_URL, "半年报附注披露租赁负债91,932百万元，其中一年内到期37,495百万元、非流动租赁负债54,437百万元，未列短期或长期借款，合计总债务91,932百万元。", "official_borrowings_plus_lease_liabilities_reconciliation", CM_2025_Q2_DETAIL_SOURCES),
    _official_record("中国移动", "Q3 2025", "gross_profit", 75113, "millions CNY", "中国移动2025年第三季度报告（新浪财经正文）", CM_2025_Q3_SINA_URL, "A股三季报披露9M营业收入794,666百万元、营业成本547,635百万元；减H1营业收入543,769百万元和营业成本371,851百万元后，Q3毛利为75,113百万元。", "official_9m_minus_h1_revenue_minus_cost_reconciliation", CM_2025_Q3_DETAIL_SOURCES),
    _official_record("中国移动", "Q3 2025", "gross_margin", 29.938, "percent", "中国移动2025年第三季度报告（新浪财经正文）", CM_2025_Q3_SINA_URL, "以A股口径Q3毛利75,113百万元除以Q3营业收入250,897百万元，毛利率为29.938%。", "official_gross_profit_divided_by_revenue_reconciliation", CM_2025_Q3_DETAIL_SOURCES),
    _official_record("中国移动", "Q3 2025", "operating_income", 39409, "millions CNY", "中国移动2025年第三季度报告（新浪财经正文）", CM_2025_Q3_SINA_URL, "A股三季报披露9M营业利润145,704百万元；减H1营业利润106,295百万元，复算Q3营业利润为39,409百万元。", "official_9m_minus_h1_operating_profit_reconciliation", CM_2025_Q3_DETAIL_SOURCES),
    _official_record("中国移动", "Q3 2025", "operating_margin", 15.708, "percent", "中国移动2025年第三季度报告（新浪财经正文）", CM_2025_Q3_SINA_URL, "以A股口径Q3营业利润39,409百万元除以Q3营业收入250,897百万元，经营利润率为15.708%。", "official_operating_income_divided_by_revenue_reconciliation", CM_2025_Q3_DETAIL_SOURCES),
    _official_record("中国移动", "Q3 2025", "revenue_growth_yoy", 2.526, "percent", "中国移动2025年第三季度报告（新浪财经正文）", CM_2025_Q3_SINA_URL, "A股口径2025Q3营业收入250,897百万元，对比2024Q3官方营业收入244,714百万元，复算同比为2.526%；主要财务数据表列示单季度同比2.5%。", "official_current_prior_period_recalculation", CM_2025_Q3_DETAIL_SOURCES),
    _official_record("中国移动", "Q4 2025", "gross_profit", 56140, "millions CNY", "中国移动2025年年度报告（新浪财经正文）", CM_2025_ANNUAL_SINA_URL, "A股年报披露全年营业收入1,050,187百万元、营业成本747,016百万元；减前三季度营业收入794,666百万元和营业成本547,635百万元后，Q4毛利为56,140百万元。", "official_full_year_minus_9m_revenue_minus_cost_reconciliation", CM_2025_Q4_DETAIL_SOURCES),
    _official_record("中国移动", "Q4 2025", "gross_margin", 21.972, "percent", "中国移动2025年年度报告（新浪财经正文）", CM_2025_ANNUAL_SINA_URL, "以A股口径Q4毛利56,140百万元除以Q4营业收入255,521百万元，毛利率为21.972%。", "official_gross_profit_divided_by_revenue_reconciliation", CM_2025_Q4_DETAIL_SOURCES),
    _official_record("中国移动", "Q4 2025", "operating_income", 32740, "millions CNY", "中国移动2025年年度报告（新浪财经正文）", CM_2025_ANNUAL_SINA_URL, "A股年报披露全年营业利润178,444百万元；减三季报9M营业利润145,704百万元，复算Q4营业利润为32,740百万元。", "official_full_year_minus_9m_operating_profit_reconciliation", CM_2025_Q4_DETAIL_SOURCES),
    _official_record("中国移动", "Q4 2025", "operating_margin", 12.813, "percent", "中国移动2025年年度报告（新浪财经正文）", CM_2025_ANNUAL_SINA_URL, "以A股口径Q4营业利润32,740百万元除以Q4营业收入255,521百万元，经营利润率为12.813%。", "official_operating_income_divided_by_revenue_reconciliation", CM_2025_Q4_DETAIL_SOURCES),
    _official_record("中国移动", "Q4 2025", "revenue_growth_yoy", 2.495, "percent", "中国移动2025年年度报告（新浪财经正文）", CM_2025_ANNUAL_SINA_URL, "A股口径2025Q4营业收入由全年1,050,187减前三季度794,666得255,521百万元；对比2024Q4官方营业收入249,301百万元，复算同比为2.495%。", "official_full_year_minus_9m_prior_year_reconciliation", CM_2025_Q4_DETAIL_SOURCES),
    _official_record("中国移动", "Q4 2025", "total_debt", 101197, "millions CNY", "中国移动2025年年度报告（新浪财经正文）", CM_2025_ANNUAL_SINA_URL, "A股年报披露长期借款9,748百万元、一年内到期的非流动负债42,507百万元、租赁负债48,942百万元，合计总债务101,197百万元；租赁负债附注列示租赁负债总额91,449百万元。", "official_borrowings_plus_lease_liabilities_reconciliation", CM_2025_Q4_DETAIL_SOURCES),
    {
        "subject": "中国电信",
        "period": "Q1 2025",
        "metric_key": "revenue",
        "official_value": 135498,
        "unit": "millions CNY",
        "source_label": "中国电信2025年第一季度报告（港交所/IRAsia）",
        "source_url": CT_2025_Q1_HKEX_URL,
        "evidence": "港股IFRS公告列示一季度Operating revenues 135,498百万元；该口径与0728.HK标准化表更匹配。",
        "verification_method": "official_hkex_ifrs_row_check",
        "verification_sources": CT_2025_Q2_SOURCES[:1],
    },
    {
        "subject": "中国电信",
        "period": "Q1 2025",
        "metric_key": "service_revenue",
        "official_value": 124700,
        "unit": "millions CNY",
        "source_label": "中国电信2025年第一季度报告（港交所/IRAsia）",
        "source_url": CT_2025_Q1_HKEX_URL,
        "evidence": "港股IFRS公告列示一季度service revenues 124.7十亿元。",
        "verification_method": "official_hkex_ifrs_row_check",
        "verification_sources": CT_2025_Q2_SOURCES[:1],
    },
    {
        "subject": "中国电信",
        "period": "Q1 2025",
        "metric_key": "ebitda",
        "official_value": 36700,
        "unit": "millions CNY",
        "source_label": "中国电信2025年第一季度报告（港交所/IRAsia）",
        "source_url": CT_2025_Q1_HKEX_URL,
        "evidence": "港股IFRS公告列示一季度EBITDA 36.7十亿元。",
        "verification_method": "official_hkex_ifrs_row_check",
        "verification_sources": CT_2025_Q2_SOURCES[:1],
    },
    {
        "subject": "中国电信",
        "period": "Q1 2025",
        "metric_key": "net_income",
        "official_value": 8864,
        "unit": "millions CNY",
        "source_label": "中国电信2025年第一季度报告（港交所/IRAsia）",
        "source_url": CT_2025_Q1_HKEX_URL,
        "evidence": "港股IFRS公告列示一季度Profit attributable to equity holders of the Company 8,864百万元。",
        "verification_method": "official_hkex_ifrs_row_check",
        "verification_sources": CT_2025_Q2_SOURCES[:1],
    },
    {
        "subject": "中国电信",
        "period": "Q1 2025",
        "metric_key": "operating_cash_flow",
        "official_value": 10327,
        "unit": "millions CNY",
        "source_label": "中国电信2025年第一季度报告（港交所/IRAsia）",
        "source_url": CT_2025_Q1_HKEX_URL,
        "evidence": "港股IFRS公告现金流量表：Net cash from operating activities 10,327百万元。",
        "verification_method": "official_hkex_ifrs_row_check",
        "verification_sources": CT_2025_Q2_SOURCES[:1],
    },
    {
        "subject": "中国电信",
        "period": "Q1 2025",
        "metric_key": "capital_expenditures",
        "official_value": -13710,
        "unit": "millions CNY",
        "source_label": "中国电信2025年第一季度报告（港交所/IRAsia）",
        "source_url": CT_2025_Q1_HKEX_URL,
        "evidence": "港股IFRS公告现金流量表：Capital expenditure (13,710)百万元；现金流出口径记为负数。",
        "verification_method": "official_hkex_ifrs_row_check",
        "verification_sources": CT_2025_Q2_SOURCES[:1],
    },
    {
        "subject": "中国电信",
        "period": "Q1 2025",
        "metric_key": "free_cash_flow",
        "official_value": -3383,
        "unit": "millions CNY",
        "source_label": "中国电信2025年第一季度报告（港交所/IRAsia）",
        "source_url": CT_2025_Q1_HKEX_URL,
        "evidence": "港股IFRS公告披露经营现金流10,327百万元、资本开支13,710百万元；自由现金流按经营现金流减资本开支复算为-3,383百万元。",
        "verification_method": "official_operating_cash_flow_minus_capex_reconciliation",
        "verification_sources": CT_2025_Q2_SOURCES[:1],
    },
    {
        "subject": "中国电信",
        "period": "Q1 2025",
        "metric_key": "operating_income",
        "official_value": 10748,
        "unit": "millions CNY",
        "source_label": "中国电信2025年第一季度报告（港交所/IRAsia）",
        "source_url": CT_2025_Q1_HKEX_URL,
        "evidence": "港股IFRS公告综合收益表：Operating profit 10,748百万元。",
        "verification_method": "official_hkex_ifrs_row_check",
        "verification_sources": CT_2025_Q2_SOURCES[:1],
    },
    {
        "subject": "中国电信",
        "period": "Q1 2025",
        "metric_key": "total_assets",
        "official_value": 858457,
        "unit": "millions CNY",
        "source_label": "中国电信2025年第一季度报告（港交所/IRAsia）",
        "source_url": CT_2025_Q1_HKEX_URL,
        "evidence": "港股IFRS公告资产负债表：Total assets 858,457百万元。",
        "verification_method": "official_hkex_ifrs_row_check",
        "verification_sources": CT_2025_Q2_SOURCES[:1],
    },
    {
        "subject": "中国电信", "period": "Q2 2025", "metric_key": "revenue",
        "official_value": 135971, "unit": "millions CNY",
        "source_label": "中国电信2025中期业绩（港交所/IRAsia）", "source_url": CT_2025_H1_HKEX_URL,
        "evidence": "上半年Operating revenues 271,469减Q1 135,498，复算Q2为135,971百万元。",
        "verification_method": "official_h1_minus_q1_reconciliation", "verification_sources": CT_2025_Q2_SOURCES,
    },
    {
        "subject": "中国电信", "period": "Q2 2025", "metric_key": "service_revenue",
        "official_value": 124412, "unit": "millions CNY",
        "source_label": "中国电信2025中期业绩（港交所/IRAsia）", "source_url": CT_2025_H1_HKEX_URL,
        "evidence": "上半年Service revenues 249,112减Q1 124,700，复算Q2为124,412百万元。",
        "verification_method": "official_h1_minus_q1_reconciliation", "verification_sources": CT_2025_Q2_SOURCES,
    },
    {
        "subject": "中国电信", "period": "Q2 2025", "metric_key": "ebitda",
        "official_value": 43888, "unit": "millions CNY",
        "source_label": "中国电信2025中期业绩（港交所/IRAsia）", "source_url": CT_2025_H1_HKEX_URL,
        "evidence": "上半年EBITDA按80.6十亿元披露并按80,588百万元精确复算，减Q1 36,700，Q2为43,888百万元；四舍五入披露会产生轻微差异。",
        "verification_method": "official_h1_minus_q1_reconciliation", "verification_sources": CT_2025_Q2_SOURCES,
    },
    {
        "subject": "中国电信", "period": "Q2 2025", "metric_key": "net_income",
        "official_value": 14153, "unit": "millions CNY",
        "source_label": "中国电信2025中期业绩（港交所/IRAsia）", "source_url": CT_2025_H1_HKEX_URL,
        "evidence": "上半年股东应占利润23,017减Q1 8,864，复算Q2为14,153百万元。",
        "verification_method": "official_h1_minus_q1_reconciliation", "verification_sources": CT_2025_Q2_SOURCES,
    },
    {
        "subject": "中国电信", "period": "Q2 2025", "metric_key": "operating_income",
        "official_value": 17801, "unit": "millions CNY",
        "source_label": "中国电信2025中期业绩（港交所/IRAsia）", "source_url": CT_2025_H1_HKEX_URL,
        "evidence": "上半年Operating profit 28,549减Q1 10,748，复算Q2为17,801百万元。",
        "verification_method": "official_h1_minus_q1_reconciliation", "verification_sources": CT_2025_Q2_SOURCES,
    },
    {
        "subject": "中国电信", "period": "Q2 2025", "metric_key": "operating_cash_flow",
        "official_value": 36973, "unit": "millions CNY",
        "source_label": "中国电信2025中期业绩（港交所/IRAsia）", "source_url": CT_2025_H1_HKEX_URL,
        "evidence": "中期业绩披露自由现金流13.1十亿元、资本开支34.2十亿元，复算上半年经营现金流约47.3十亿元；减Q1 10,327，Q2约36,973百万元。",
        "verification_method": "official_h1_minus_q1_cash_flow_reconciliation", "verification_sources": CT_2025_Q2_SOURCES,
    },
    {
        "subject": "中国电信", "period": "Q2 2025", "metric_key": "capital_expenditures",
        "official_value": -20490, "unit": "millions CNY",
        "source_label": "中国电信2025中期业绩（港交所/IRAsia）", "source_url": CT_2025_H1_HKEX_URL,
        "evidence": "中期业绩披露资本开支34.2十亿元；减Q1现金流表资本开支13.710十亿元，Q2约20.49十亿元，记为现金流出。",
        "verification_method": "official_h1_minus_q1_capex_reconciliation", "verification_sources": CT_2025_Q2_SOURCES,
    },
    {
        "subject": "中国电信", "period": "Q2 2025", "metric_key": "free_cash_flow",
        "official_value": 16483, "unit": "millions CNY",
        "source_label": "中国电信2025中期业绩（港交所/IRAsia）", "source_url": CT_2025_H1_HKEX_URL,
        "evidence": "Q2经营现金流按上半年复算为36,973百万元，Q2资本开支按上半年资本开支减Q1复算为20,490百万元；自由现金流为16,483百万元。",
        "verification_method": "official_operating_cash_flow_minus_capex_reconciliation", "verification_sources": CT_2025_Q2_SOURCES,
    },
    {
        "subject": "中国电信", "period": "Q3 2025", "metric_key": "revenue",
        "official_value": 125529, "unit": "millions CNY",
        "source_label": "中国电信2025年前三季度报告（港交所/IRAsia）", "source_url": CT_2025_Q3_HKEX_URL,
        "evidence": "前三季度Operating revenues 396,998减上半年271,469，复算Q3为125,529百万元。",
        "verification_method": "official_9m_minus_h1_reconciliation", "verification_sources": CT_2025_Q3_SOURCES,
    },
    {
        "subject": "中国电信", "period": "Q3 2025", "metric_key": "service_revenue",
        "official_value": 117188, "unit": "millions CNY",
        "source_label": "中国电信2025年前三季度报告（港交所/IRAsia）", "source_url": CT_2025_Q3_HKEX_URL,
        "evidence": "前三季度Service revenues 366.3十亿元，减上半年249,112百万元，复算Q3约117,188百万元。",
        "verification_method": "official_9m_minus_h1_reconciliation", "verification_sources": CT_2025_Q3_SOURCES,
    },
    {
        "subject": "中国电信", "period": "Q3 2025", "metric_key": "ebitda",
        "official_value": 35012, "unit": "millions CNY",
        "source_label": "中国电信2025年前三季度报告（港交所/IRAsia）", "source_url": CT_2025_Q3_HKEX_URL,
        "evidence": "前三季度EBITDA按115.6十亿元披露并按115,600百万元估算，减上半年80,588，Q3约35,012百万元；披露四舍五入会带来轻微误差。",
        "verification_method": "official_9m_minus_h1_reconciliation", "verification_sources": CT_2025_Q3_SOURCES,
    },
    {
        "subject": "中国电信", "period": "Q3 2025", "metric_key": "net_income",
        "official_value": 7756, "unit": "millions CNY",
        "source_label": "中国电信2025年前三季度报告（港交所/IRAsia）", "source_url": CT_2025_Q3_HKEX_URL,
        "evidence": "前三季度股东应占利润30,773减上半年23,017，复算Q3为7,756百万元。",
        "verification_method": "official_9m_minus_h1_reconciliation", "verification_sources": CT_2025_Q3_SOURCES,
    },
    {
        "subject": "中国电信", "period": "Q3 2025", "metric_key": "operating_income",
        "official_value": 9190, "unit": "millions CNY",
        "source_label": "中国电信2025年前三季度报告（港交所/IRAsia）", "source_url": CT_2025_Q3_HKEX_URL,
        "evidence": "前三季度Operating profit 37,739减上半年28,549，复算Q3为9,190百万元。",
        "verification_method": "official_9m_minus_h1_reconciliation", "verification_sources": CT_2025_Q3_SOURCES,
    },
    {
        "subject": "中国电信", "period": "Q3 2025", "metric_key": "operating_cash_flow",
        "official_value": 40121, "unit": "millions CNY",
        "source_label": "中国电信2025年前三季度报告（港交所/IRAsia）", "source_url": CT_2025_Q3_HKEX_URL,
        "evidence": "前三季度Net cash from operating activities 87,421，减上半年按自由现金流13.1十亿元+资本开支34.2十亿元复算约47,300，Q3约40,121百万元。",
        "verification_method": "official_9m_minus_h1_cash_flow_reconciliation", "verification_sources": CT_2025_Q3_SOURCES,
    },
    {
        "subject": "中国电信", "period": "Q3 2025", "metric_key": "capital_expenditures",
        "official_value": -10610, "unit": "millions CNY",
        "source_label": "中国电信2025年前三季度报告（港交所/IRAsia）", "source_url": CT_2025_Q3_HKEX_URL,
        "evidence": "前三季度现金流量表Capital expenditure (44,810)百万元，减上半年业绩披露资本开支34.2十亿元，Q3约10.61十亿元，记为现金流出。",
        "verification_method": "official_9m_minus_h1_capex_reconciliation", "verification_sources": CT_2025_Q3_SOURCES,
    },
    {
        "subject": "中国电信", "period": "Q3 2025", "metric_key": "free_cash_flow",
        "official_value": 29511, "unit": "millions CNY",
        "source_label": "中国电信2025年前三季度报告（港交所/IRAsia）", "source_url": CT_2025_Q3_HKEX_URL,
        "evidence": "Q3经营现金流按前三季度减上半年复算约40,121百万元，Q3资本开支约10,610百万元；自由现金流为29,511百万元。",
        "verification_method": "official_operating_cash_flow_minus_capex_reconciliation", "verification_sources": CT_2025_Q3_SOURCES,
    },
    {
        "subject": "中国电信", "period": "Q3 2025", "metric_key": "cash_and_equivalents",
        "official_value": 44594, "unit": "millions CNY",
        "source_label": "中国电信2025年前三季度报告（港交所/IRAsia）", "source_url": CT_2025_Q3_HKEX_URL,
        "evidence": "截至2025年9月30日Cash and cash equivalents 44,594百万元。",
        "verification_method": "official_balance_sheet_row_check", "verification_sources": CT_2025_Q3_DETAIL_SOURCES,
    },
    {
        "subject": "中国电信", "period": "Q3 2025", "metric_key": "total_assets",
        "official_value": 876049, "unit": "millions CNY",
        "source_label": "中国电信2025年前三季度报告（港交所/IRAsia）", "source_url": CT_2025_Q3_HKEX_URL,
        "evidence": "截至2025年9月30日Total assets 876,049百万元。",
        "verification_method": "official_balance_sheet_row_check", "verification_sources": CT_2025_Q3_DETAIL_SOURCES,
    },
    {
        "subject": "中国电信", "period": "Q4 2025", "metric_key": "revenue",
        "official_value": 132602, "unit": "millions CNY",
        "source_label": "中国电信2025年度业绩新闻稿", "source_url": CT_2025_ANNUAL_RESULTS_URL,
        "evidence": "全年经营收入529.6十亿元，减前三季度396,998百万元，复算Q4约132,602百万元。",
        "verification_method": "official_full_year_minus_9m_reconciliation", "verification_sources": CT_2025_Q4_SOURCES,
    },
    {
        "subject": "中国电信", "period": "Q4 2025", "metric_key": "service_revenue",
        "official_value": 119124, "unit": "millions CNY",
        "source_label": "中国电信2025年度业绩新闻稿", "source_url": CT_2025_ANNUAL_RESULTS_URL,
        "evidence": "全年Service Revenues 485,424减前三季度约366,300，复算Q4约119,124百万元。",
        "verification_method": "official_full_year_minus_9m_reconciliation", "verification_sources": CT_2025_Q4_SOURCES,
    },
    {
        "subject": "中国电信", "period": "Q4 2025", "metric_key": "ebitda",
        "official_value": 28272, "unit": "millions CNY",
        "source_label": "中国电信2025年度业绩新闻稿", "source_url": CT_2025_ANNUAL_RESULTS_URL,
        "evidence": "全年EBITDA 143,872减前三季度约115,600，复算Q4约28,272百万元。",
        "verification_method": "official_full_year_minus_9m_reconciliation", "verification_sources": CT_2025_Q4_SOURCES,
    },
    {
        "subject": "中国电信", "period": "Q4 2025", "metric_key": "net_income",
        "official_value": 2412, "unit": "millions CNY",
        "source_label": "中国电信2025年度业绩新闻稿", "source_url": CT_2025_ANNUAL_RESULTS_URL,
        "evidence": "全年Net Profit 33,185减前三季度股东应占利润30,773，复算Q4为2,412百万元。",
        "verification_method": "official_full_year_minus_9m_reconciliation", "verification_sources": CT_2025_Q4_SOURCES,
    },
    {
        "subject": "中国电信", "period": "Q4 2025", "metric_key": "operating_cash_flow",
        "official_value": 37679, "unit": "millions CNY",
        "source_label": "中国电信2025年度业绩新闻稿", "source_url": CT_2025_ANNUAL_RESULTS_URL,
        "evidence": "全年自由现金流44.7十亿元且资本开支80.4十亿元，复算全年经营现金流125.1十亿元；减前三季度87,421，Q4约37,679百万元。",
        "verification_method": "official_full_year_minus_9m_cash_flow_reconciliation", "verification_sources": CT_2025_Q4_SOURCES,
    },
    {
        "subject": "中国电信", "period": "Q4 2025", "metric_key": "capital_expenditures",
        "official_value": -35590, "unit": "millions CNY",
        "source_label": "中国电信2025年度业绩新闻稿", "source_url": CT_2025_ANNUAL_RESULTS_URL,
        "evidence": "全年Capital expenditure 80.4十亿元，减前三季度Capital expenditure 44,810百万元，Q4约35,590百万元，记为现金流出。",
        "verification_method": "official_full_year_minus_9m_capex_reconciliation", "verification_sources": CT_2025_Q4_SOURCES,
    },
    {
        "subject": "中国电信", "period": "Q4 2025", "metric_key": "free_cash_flow",
        "official_value": 2089, "unit": "millions CNY",
        "source_label": "中国电信2025年度业绩新闻稿", "source_url": CT_2025_ANNUAL_RESULTS_URL,
        "evidence": "全年自由现金流44.7十亿元且前三季度现金流表可复算Q4经营现金流约37,679百万元、Q4资本开支约35,590百万元；Q4自由现金流约2,089百万元。",
        "verification_method": "official_operating_cash_flow_minus_capex_reconciliation", "verification_sources": CT_2025_Q4_SOURCES,
    },
    {
        "subject": "中国联通",
        "period": "Q1 2025",
        "metric_key": "revenue",
        "official_value": 103353.772,
        "unit": "millions CNY",
        "source_label": "中国联通2025年第一季度报告（上交所，600050 A股口径）",
        "source_url": CU_2025_Q1_SSE_URL,
        "evidence": "主要会计数据/合并利润表：营业收入 103,353,771,882 元。",
        "verification_sources": CU_2025_Q1_SOURCES,
    },
    {
        "subject": "中国联通",
        "period": "Q1 2025",
        "metric_key": "revenue_growth_yoy",
        "official_value": 3.9,
        "unit": "percent",
        "source_label": "中国联通2025年第一季度报告（上交所，600050 A股口径）",
        "source_url": CU_2025_Q1_SSE_URL,
        "evidence": "主要会计数据：营业收入同比提升 3.9%。",
        "verification_sources": CU_2025_Q1_SOURCES,
    },
    {
        "subject": "中国联通",
        "period": "Q1 2025",
        "metric_key": "net_income",
        "official_value": 5896.768,
        "unit": "millions CNY",
        "source_label": "中国联通2025年第一季度报告（上交所，600050 A股口径）",
        "source_url": CU_2025_Q1_SSE_URL,
        "evidence": "合并利润表：合并净利润 5,896,768,021 元；其中归属于600050母公司股东净利润为2,605,653,080元，和0762.HK标准化口径并不完全相同。",
        "verification_sources": CU_2025_Q1_SOURCES,
    },
    {
        "subject": "中国联通",
        "period": "Q1 2025",
        "metric_key": "operating_cash_flow",
        "official_value": 7846.183,
        "unit": "millions CNY",
        "source_label": "中国联通2025年第一季度报告（上交所，600050 A股口径）",
        "source_url": CU_2025_Q1_SSE_URL,
        "evidence": "主要会计数据/合并现金流量表：经营活动产生的现金流量净额 7,846,183,063 元。",
        "verification_sources": CU_2025_Q1_SOURCES,
    },
    {
        "subject": "中国联通",
        "period": "Q1 2025",
        "metric_key": "capital_expenditures",
        "official_value": -14804.982,
        "unit": "millions CNY",
        "source_label": "中国联通2025年第一季度报告（上交所，600050 A股口径）",
        "source_url": CU_2025_Q1_SSE_URL,
        "evidence": "合并现金流量表：购建固定资产、无形资产和其他长期资产支付的现金 14,804,982,407 元；现金流出口径记为负数。",
        "verification_sources": CU_2025_Q1_SOURCES,
    },
    {
        "subject": "中国联通",
        "period": "Q1 2025",
        "metric_key": "free_cash_flow",
        "official_value": -6958.799,
        "unit": "millions CNY",
        "source_label": "中国联通2025年第一季度报告（上交所，600050 A股口径）",
        "source_url": CU_2025_Q1_SSE_URL,
        "evidence": "合并现金流量表披露经营现金流7,846.183百万元、购建长期资产现金支出14,804.982百万元；自由现金流按经营现金流减资本开支复算为-6,958.799百万元。",
        "verification_method": "official_operating_cash_flow_minus_capex_reconciliation",
        "verification_sources": CU_2025_Q1_SOURCES,
    },
    {
        "subject": "中国联通",
        "period": "Q1 2025",
        "metric_key": "operating_income",
        "official_value": 7243.432,
        "unit": "millions CNY",
        "source_label": "中国联通2025年第一季度报告（上交所，600050 A股口径）",
        "source_url": CU_2025_Q1_SSE_URL,
        "evidence": "合并利润表：营业利润 7,243,432,441 元；该A股中国会计准则口径可能与0762.HK标准化表的 operating income 定义不同。",
        "verification_sources": CU_2025_Q1_SOURCES,
    },
    {
        "subject": "中国联通",
        "period": "Q1 2025",
        "metric_key": "total_assets",
        "official_value": 667650.178,
        "unit": "millions CNY",
        "source_label": "中国联通2025年第一季度报告（上交所，600050 A股口径）",
        "source_url": CU_2025_Q1_SSE_URL,
        "evidence": "主要会计数据/合并资产负债表：总资产 667,650,178,431 元。",
        "verification_sources": CU_2025_Q1_SOURCES,
    },
    _official_record("中国联通", "Q1 2025", "cash_and_equivalents", 22377.978, "millions CNY", "中国联通2025年第一季度报告（上交所，600050 A股口径）", CU_2025_Q1_SSE_URL, "合并现金流量表披露期末现金及现金等价物余额22,377,977,852元；该口径不同于资产负债表货币资金48,102,687,571元。", "official_cash_flow_statement_cash_equivalents_check", CU_2025_Q1_SOURCES),
    _official_record("中国联通", "Q1 2025", "gross_profit", 25954.637, "millions CNY", "中国联通2025年第一季度报告（上交所，600050 A股口径）", CU_2025_Q1_SSE_URL, "合并利润表披露营业收入103,353.772百万元、营业成本77,399.135百万元；按收入减营业成本复算毛利为25,954.637百万元。", "official_revenue_minus_operating_cost_reconciliation", CU_2025_Q1_SOURCES),
    _official_record("中国联通", "Q1 2025", "gross_margin", 25.112, "percent", "中国联通2025年第一季度报告（上交所，600050 A股口径）", CU_2025_Q1_SSE_URL, "以官方复算毛利25,954.637百万元除以营业收入103,353.772百万元，毛利率为25.112%。", "official_gross_profit_divided_by_revenue_reconciliation", CU_2025_Q1_SOURCES),
    _official_record("中国联通", "Q1 2025", "total_debt", 38944.138, "millions CNY", "中国联通2025年第一季度报告（上交所，600050 A股口径）", CU_2025_Q1_SSE_URL, "合并资产负债表披露短期借款710.624百万元、一年内到期的非流动负债13,702.560百万元、长期借款2,259.451百万元、租赁负债22,271.502百万元，合计总债务38,944.138百万元。", "official_borrowings_plus_lease_liabilities_reconciliation", CU_2025_Q1_SOURCES),
    {
        "subject": "中国联通", "period": "H1 2025", "metric_key": "revenue",
        "official_value": 200200, "unit": "millions CNY",
        "source_label": "中国联通2025中期报告（0762.HK）", "source_url": CU_2025_H1_URL,
        "evidence": "中期报告Financial Overview：2025年上半年收入为人民币200.20十亿元，同比增长1.5%。",
        "verification_method": "official_interim_report_cumulative_check", "verification_sources": [CU_2025_Q2_SOURCES[1]],
    },
    {
        "subject": "中国联通", "period": "H1 2025", "metric_key": "service_revenue",
        "official_value": 178360, "unit": "millions CNY",
        "source_label": "中国联通2025中期报告（0762.HK）", "source_url": CU_2025_H1_URL,
        "evidence": "中期报告Financial Overview：2025年上半年服务收入为人民币178.36十亿元，同比增长1.5%。",
        "verification_method": "official_interim_report_cumulative_check", "verification_sources": [CU_2025_Q2_SOURCES[1]],
    },
    {
        "subject": "中国联通", "period": "H1 2025", "metric_key": "operating_income",
        "official_value": 13920, "unit": "millions CNY",
        "source_label": "中国联通2025中期报告（0762.HK）", "source_url": CU_2025_H1_URL,
        "evidence": "中期报告Earnings表：Operating profits 13.92十亿元。",
        "verification_method": "official_interim_report_cumulative_check", "verification_sources": [CU_2025_Q2_SOURCES[1]],
    },
    {
        "subject": "中国联通", "period": "H1 2025", "metric_key": "net_income",
        "official_value": 14480, "unit": "millions CNY",
        "source_label": "中国联通2025中期报告（0762.HK）", "source_url": CU_2025_H1_URL,
        "evidence": "中期报告Financial Overview：2025年上半年归属于公司权益持有人的利润为人民币14.48十亿元，同比增长5.0%。",
        "verification_method": "official_interim_report_cumulative_check", "verification_sources": [CU_2025_Q2_SOURCES[1]],
    },
    {
        "subject": "中国联通", "period": "H1 2025", "metric_key": "ebitda",
        "official_value": 54240, "unit": "millions CNY",
        "source_label": "中国联通2025中期报告（0762.HK）", "source_url": CU_2025_H1_URL,
        "evidence": "中期报告Financial Overview：2025年上半年EBITDA为人民币54.24十亿元，占服务收入30.4%。",
        "verification_method": "official_interim_report_cumulative_check", "verification_sources": [CU_2025_Q2_SOURCES[1]],
    },
    {
        "subject": "中国联通", "period": "H1 2025", "metric_key": "operating_cash_flow",
        "official_value": 29000, "unit": "millions CNY",
        "source_label": "中国联通2025中期报告（0762.HK）", "source_url": CU_2025_H1_URL,
        "evidence": "中期报告Capital Expenditure and Cash Flow：经营活动现金流净额为人民币29.00十亿元。",
        "verification_method": "official_interim_report_cumulative_check", "verification_sources": [CU_2025_Q2_SOURCES[1]],
    },
    {
        "subject": "中国联通", "period": "H1 2025", "metric_key": "capital_expenditures",
        "official_value": -20220, "unit": "millions CNY",
        "source_label": "中国联通2025中期报告（0762.HK）", "source_url": CU_2025_H1_URL,
        "evidence": "中期报告Capital Expenditure and Cash Flow：上半年资本开支为人民币20.22十亿元，现金流出口径记为负数。",
        "verification_method": "official_interim_report_cumulative_check", "verification_sources": [CU_2025_Q2_SOURCES[1]],
    },
    {
        "subject": "中国联通", "period": "H1 2025", "metric_key": "free_cash_flow",
        "official_value": 8780, "unit": "millions CNY",
        "source_label": "中国联通2025中期报告（0762.HK）", "source_url": CU_2025_H1_URL,
        "evidence": "中期报告Capital Expenditure and Cash Flow：扣除资本开支后自由现金流为人民币8.78十亿元。",
        "verification_method": "official_interim_report_cumulative_check", "verification_sources": [CU_2025_Q2_SOURCES[1]],
    },
    {
        "subject": "中国联通", "period": "H1 2025", "metric_key": "total_assets",
        "official_value": 663830, "unit": "millions CNY",
        "source_label": "中国联通2025中期报告（0762.HK）", "source_url": CU_2025_H1_URL,
        "evidence": "中期报告Balance Sheet：2025年6月30日总资产为人民币663.83十亿元。",
        "verification_method": "official_interim_report_cumulative_check", "verification_sources": [CU_2025_Q2_SOURCES[1]],
    },
    {
        "subject": "中国联通", "period": "Q2 2025", "metric_key": "revenue",
        "official_value": 96846.228, "unit": "millions CNY",
        "source_label": "中国联通2025中期报告（0762.HK）", "source_url": CU_2025_H1_URL,
        "evidence": "H1收入200,200减600050 Q1营业收入103,353.772，复算Q2为96,846.228百万元；需注意Q1为A股600050口径。",
        "verification_method": "official_h1_minus_q1_reconciliation_mixed_600050_0762", "verification_sources": CU_2025_Q2_SOURCES,
    },
    {
        "subject": "中国联通", "period": "Q2 2025", "metric_key": "operating_income",
        "official_value": 6676.568, "unit": "millions CNY",
        "source_label": "中国联通2025中期报告（0762.HK）", "source_url": CU_2025_H1_URL,
        "evidence": "H1 operating profits 13,920减600050 Q1营业利润7,243.432，复算Q2约6,676.568百万元；IFRS operating profits 与A股营业利润口径存在差异风险。",
        "verification_method": "official_h1_minus_q1_reconciliation_mixed_600050_0762", "verification_sources": CU_2025_Q2_SOURCES,
    },
    {
        "subject": "中国联通", "period": "Q2 2025", "metric_key": "operating_cash_flow",
        "official_value": 21153.817, "unit": "millions CNY",
        "source_label": "中国联通2025中期报告（0762.HK）", "source_url": CU_2025_H1_URL,
        "evidence": "H1经营现金流29,000减600050 Q1经营现金流7,846.183，复算Q2约21,153.817百万元。",
        "verification_method": "official_h1_minus_q1_cash_flow_reconciliation", "verification_sources": CU_2025_Q2_SOURCES,
    },
    {
        "subject": "中国联通", "period": "Q2 2025", "metric_key": "capital_expenditures",
        "official_value": -5415.018, "unit": "millions CNY",
        "source_label": "中国联通2025中期报告（0762.HK）", "source_url": CU_2025_H1_URL,
        "evidence": "H1资本开支20,220减600050 Q1购建长期资产现金支出14,804.982，复算Q2资本开支约5,415.018百万元，记为现金流出。",
        "verification_method": "official_h1_minus_q1_capex_reconciliation", "verification_sources": CU_2025_Q2_SOURCES,
    },
    {
        "subject": "中国联通", "period": "Q2 2025", "metric_key": "total_assets",
        "official_value": 663830, "unit": "millions CNY",
        "source_label": "中国联通2025中期报告（0762.HK）", "source_url": CU_2025_H1_URL,
        "evidence": "中期报告Balance Sheet：2025年6月30日总资产为人民币663.83十亿元，对应Q2期末时点。",
        "verification_method": "official_interim_balance_sheet_point_check", "verification_sources": [CU_2025_Q2_SOURCES[1]],
    },
    {
        "subject": "中国联通", "period": "H2 2025", "metric_key": "revenue",
        "official_value": 192023, "unit": "millions CNY",
        "source_label": "中国联通2025年度业绩公告", "source_url": CU_2025_ANNUAL_RESULTS_URL,
        "evidence": "全年经营收入392,223减H1收入200,200，复算H2经营收入192,023百万元。",
        "verification_method": "official_full_year_minus_h1_reconciliation", "verification_sources": CU_2025_H2_SOURCES,
    },
    {
        "subject": "中国联通", "period": "H2 2025", "metric_key": "service_revenue",
        "official_value": 169378, "unit": "millions CNY",
        "source_label": "中国联通2025年度业绩公告", "source_url": CU_2025_ANNUAL_RESULTS_URL,
        "evidence": "全年服务收入347,738减H1服务收入178,360，复算H2服务收入169,378百万元。",
        "verification_method": "official_full_year_minus_h1_reconciliation", "verification_sources": CU_2025_H2_SOURCES,
    },
    {
        "subject": "中国联通", "period": "H2 2025", "metric_key": "net_income",
        "official_value": 6336, "unit": "millions CNY",
        "source_label": "中国联通2025年度业绩公告", "source_url": CU_2025_ANNUAL_RESULTS_URL,
        "evidence": "全年Net Profit 20,816减H1归属于权益持有人利润14,480，复算H2为6,336百万元。",
        "verification_method": "official_full_year_minus_h1_reconciliation", "verification_sources": CU_2025_H2_SOURCES,
    },
    {
        "subject": "中国联通", "period": "H2 2025", "metric_key": "capital_expenditures",
        "official_value": -33980, "unit": "millions CNY",
        "source_label": "中国联通2025年度业绩公告", "source_url": CU_2025_ANNUAL_RESULTS_URL,
        "evidence": "全年CAPEX 54,200减H1资本开支20,220，复算H2资本开支33,980百万元，记为现金流出。",
        "verification_method": "official_full_year_minus_h1_capex_reconciliation", "verification_sources": CU_2025_H2_SOURCES,
    },
    {
        "subject": "中国联通", "period": "H2 2025", "metric_key": "free_cash_flow",
        "official_value": 27242, "unit": "millions CNY",
        "source_label": "中国联通2025年度业绩公告", "source_url": CU_2025_ANNUAL_RESULTS_URL,
        "evidence": "全年自由现金流36,022减H1自由现金流8,780，复算H2自由现金流27,242百万元。",
        "verification_method": "official_full_year_minus_h1_cash_flow_reconciliation", "verification_sources": CU_2025_H2_SOURCES,
    },
    _official_record("中国联通", "Q2 2025", "revenue", 96848.659, "millions CNY", "中国联通2025年半年度报告（600050 A股口径）", CU_2025_H1_SINA_URL, "A股半年度报告披露H1营业收入200,202.431百万元，减Q1营业收入103,353.772百万元，复算Q2营业收入96,848.659百万元。", "official_h1_minus_q1_revenue_reconciliation", CU_2025_Q2_DETAIL_SOURCES),
    _official_record("中国联通", "Q2 2025", "cash_and_equivalents", 20060.744, "millions CNY", "中国联通2025年半年度报告（600050 A股口径）", CU_2025_H1_SINA_URL, "A股半年度报告现金流量表披露2025年6月30日期末现金及现金等价物余额20,060.744百万元。", "official_cash_flow_statement_cash_equivalents_check", CU_2025_Q2_DETAIL_SOURCES),
    _official_record("中国联通", "Q2 2025", "gross_profit", 28214.261, "millions CNY", "中国联通2025年半年度报告（600050 A股口径）", CU_2025_H1_SINA_URL, "A股半年度报告披露H1营业收入200,202.431百万元、营业成本146,033.532百万元；减Q1营业收入103,353.772百万元和营业成本77,399.135百万元，复算Q2毛利为28,214.261百万元。", "official_h1_minus_q1_revenue_minus_cost_reconciliation", CU_2025_Q2_DETAIL_SOURCES),
    _official_record("中国联通", "Q2 2025", "gross_margin", 29.132, "percent", "中国联通2025年半年度报告（600050 A股口径）", CU_2025_H1_SINA_URL, "以A股口径Q2毛利28,214.261百万元除以Q2营业收入96,848.659百万元，毛利率为29.132%。", "official_gross_profit_divided_by_revenue_reconciliation", CU_2025_Q2_DETAIL_SOURCES),
    _official_record("中国联通", "Q2 2025", "net_income", 8536.480, "millions CNY", "中国联通2025年半年度报告（600050 A股口径）", CU_2025_H1_SINA_URL, "A股半年度报告披露H1合并净利润14,433.248百万元，减Q1合并净利润5,896.768百万元，复算Q2合并净利润8,536.480百万元。", "official_h1_minus_q1_net_profit_reconciliation", CU_2025_Q2_DETAIL_SOURCES),
    _official_record("中国联通", "Q2 2025", "operating_income", 9753.245, "millions CNY", "中国联通2025年半年度报告（600050 A股口径）", CU_2025_H1_SINA_URL, "A股半年度报告披露H1营业利润16,996.678百万元，减Q1营业利润7,243.432百万元，复算Q2营业利润9,753.245百万元。", "official_h1_minus_q1_operating_profit_reconciliation", CU_2025_Q2_DETAIL_SOURCES),
    _official_record("中国联通", "Q2 2025", "operating_margin", 10.071, "percent", "中国联通2025年半年度报告（600050 A股口径）", CU_2025_H1_SINA_URL, "以A股口径Q2营业利润9,753.245百万元除以Q2营业收入96,848.659百万元，经营利润率为10.071%。", "official_operating_income_divided_by_revenue_reconciliation", CU_2025_Q2_DETAIL_SOURCES),
    _official_record("中国联通", "Q2 2025", "revenue_growth_yoy", -1.017, "percent", "中国联通2025年半年度报告（600050 A股口径）", CU_2025_H1_SINA_URL, "A股口径2025Q2营业收入96,848.659百万元；对比已核验2024Q2营业收入97,844百万元，复算同比为-1.017%。", "official_h1_minus_q1_prior_quarter_reconciliation", CU_2025_Q2_DETAIL_SOURCES),
    _official_record("中国联通", "Q2 2025", "total_debt", 36843.016, "millions CNY", "中国联通2025年半年度报告（600050 A股口径）", CU_2025_H1_SINA_URL, "A股半年度报告资产负债表披露短期借款820.629百万元、一年内到期的长期借款704.813百万元、一年内到期的租赁负债12,604.519百万元、长期借款2,458.859百万元、租赁负债20,254.196百万元，合计总债务36,843.016百万元。", "official_borrowings_plus_lease_liabilities_reconciliation", CU_2025_Q2_DETAIL_SOURCES),
    _official_record("中国联通", "Q3 2025", "revenue", 92782.740, "millions CNY", "中国联通2025年第三季度报告（600050 A股口径）", CU_2025_Q3_SINA_URL, "A股三季报本报告期营业收入92,782.740百万元；也可由前三季度292,985.171百万元减H1 200,202.431百万元复算。", "official_quarter_report_row_and_9m_minus_h1_reconciliation", CU_2025_Q3_DETAIL_SOURCES),
    _official_record("中国联通", "Q3 2025", "cash_and_equivalents", 27752.605, "millions CNY", "中国联通2025年第三季度报告（600050 A股口径）", CU_2025_Q3_SINA_URL, "A股三季报现金流量表披露2025年9月30日期末现金及现金等价物余额27,752.605百万元。", "official_cash_flow_statement_cash_equivalents_check", CU_2025_Q3_DETAIL_SOURCES),
    _official_record("中国联通", "Q3 2025", "gross_profit", 24848.645, "millions CNY", "中国联通2025年第三季度报告（600050 A股口径）", CU_2025_Q3_SINA_URL, "A股三季报披露前三季度营业收入292,985.171百万元、营业成本213,967.627百万元；减H1营业收入200,202.431百万元和营业成本146,033.532百万元，复算Q3毛利为24,848.645百万元。", "official_9m_minus_h1_revenue_minus_cost_reconciliation", CU_2025_Q3_DETAIL_SOURCES),
    _official_record("中国联通", "Q3 2025", "gross_margin", 26.782, "percent", "中国联通2025年第三季度报告（600050 A股口径）", CU_2025_Q3_SINA_URL, "以A股口径Q3毛利24,848.645百万元除以Q3营业收入92,782.740百万元，毛利率为26.782%。", "official_gross_profit_divided_by_revenue_reconciliation", CU_2025_Q3_DETAIL_SOURCES),
    _official_record("中国联通", "Q3 2025", "net_income", 5503.741, "millions CNY", "中国联通2025年第三季度报告（600050 A股口径）", CU_2025_Q3_SINA_URL, "A股三季报披露前三季度合并净利润19,936.989百万元，减H1合并净利润14,433.248百万元，复算Q3合并净利润5,503.741百万元。", "official_9m_minus_h1_net_profit_reconciliation", CU_2025_Q3_DETAIL_SOURCES),
    _official_record("中国联通", "Q3 2025", "operating_income", 6680.302, "millions CNY", "中国联通2025年第三季度报告（600050 A股口径）", CU_2025_Q3_SINA_URL, "A股三季报披露前三季度营业利润23,676.980百万元，减H1营业利润16,996.678百万元，复算Q3营业利润6,680.302百万元。", "official_9m_minus_h1_operating_profit_reconciliation", CU_2025_Q3_DETAIL_SOURCES),
    _official_record("中国联通", "Q3 2025", "operating_margin", 7.200, "percent", "中国联通2025年第三季度报告（600050 A股口径）", CU_2025_Q3_SINA_URL, "以A股口径Q3营业利润6,680.302百万元除以Q3营业收入92,782.740百万元，经营利润率为7.200%。", "official_operating_income_divided_by_revenue_reconciliation", CU_2025_Q3_DETAIL_SOURCES),
    _official_record("中国联通", "Q3 2025", "revenue_growth_yoy", 0.001, "percent", "中国联通2025年第三季度报告（600050 A股口径）", CU_2025_Q3_SINA_URL, "三季报列示本报告期营业收入同比0.0%；按2025Q3营业收入92,782.740百万元对比2024Q3约92,781.992百万元复算为0.001%。", "official_quarter_report_yoy_and_prior_quarter_recalculation", CU_2025_Q3_DETAIL_SOURCES),
    _official_record("中国联通", "Q3 2025", "total_assets", 671346.506, "millions CNY", "中国联通2025年第三季度报告（600050 A股口径）", CU_2025_Q3_SINA_URL, "A股三季报资产负债表披露2025年9月30日资产总计671,346.506百万元。", "official_balance_sheet_row_check", CU_2025_Q3_DETAIL_SOURCES),
    _official_record("中国联通", "Q3 2025", "total_debt", 35427.734, "millions CNY", "中国联通2025年第三季度报告（600050 A股口径）", CU_2025_Q3_SINA_URL, "A股三季报资产负债表披露短期借款810.573百万元、一年内到期的非流动负债12,672.287百万元、长期借款2,760.569百万元、租赁负债19,184.306百万元，合计总债务35,427.734百万元。", "official_borrowings_plus_lease_liabilities_reconciliation", CU_2025_Q3_DETAIL_SOURCES),
    _official_record("中国联通", "Q4 2025", "revenue", 99237.710, "millions CNY", "中国联通2025年度报告（600050 A股口径）", CU_2025_ANNUAL_SINA_URL, "A股年报披露全年营业收入392,222.881百万元，减前三季度292,985.171百万元，复算Q4营业收入99,237.710百万元。", "official_full_year_minus_9m_revenue_reconciliation", CU_2025_Q4_DETAIL_SOURCES),
    _official_record("中国联通", "Q4 2025", "cash_and_equivalents", 25150.487, "millions CNY", "中国联通2025年度报告（600050 A股口径）", CU_2025_ANNUAL_SINA_URL, "A股年报现金流量表披露2025年末现金及现金等价物余额25,150.487百万元。", "official_cash_flow_statement_cash_equivalents_check", CU_2025_Q4_DETAIL_SOURCES),
    _official_record("中国联通", "Q4 2025", "gross_profit", 13299.469, "millions CNY", "中国联通2025年度报告（600050 A股口径）", CU_2025_ANNUAL_SINA_URL, "A股年报披露全年营业收入392,222.881百万元、营业成本299,905.868百万元；减前三季度营业收入292,985.171百万元和营业成本213,967.627百万元，复算Q4毛利为13,299.469百万元。", "official_full_year_minus_9m_revenue_minus_cost_reconciliation", CU_2025_Q4_DETAIL_SOURCES),
    _official_record("中国联通", "Q4 2025", "gross_margin", 13.402, "percent", "中国联通2025年度报告（600050 A股口径）", CU_2025_ANNUAL_SINA_URL, "以A股口径Q4毛利13,299.469百万元除以Q4营业收入99,237.710百万元，毛利率为13.402%。", "official_gross_profit_divided_by_revenue_reconciliation", CU_2025_Q4_DETAIL_SOURCES),
    _official_record("中国联通", "Q4 2025", "net_income", 850.800, "millions CNY", "中国联通2025年度报告（600050 A股口径）", CU_2025_ANNUAL_SINA_URL, "A股年报披露全年合并净利润20,787.789百万元，减前三季度合并净利润19,936.989百万元，复算Q4合并净利润850.800百万元。", "official_full_year_minus_9m_net_profit_reconciliation", CU_2025_Q4_DETAIL_SOURCES),
    _official_record("中国联通", "Q4 2025", "operating_income", 1358.747, "millions CNY", "中国联通2025年度报告（600050 A股口径）", CU_2025_ANNUAL_SINA_URL, "A股年报披露全年营业利润25,035.727百万元，减前三季度营业利润23,676.980百万元，复算Q4营业利润1,358.747百万元。", "official_full_year_minus_9m_operating_profit_reconciliation", CU_2025_Q4_DETAIL_SOURCES),
    _official_record("中国联通", "Q4 2025", "operating_margin", 1.369, "percent", "中国联通2025年度报告（600050 A股口径）", CU_2025_ANNUAL_SINA_URL, "以A股口径Q4营业利润1,358.747百万元除以Q4营业收入99,237.710百万元，经营利润率为1.369%。", "official_operating_income_divided_by_revenue_reconciliation", CU_2025_Q4_DETAIL_SOURCES),
    _official_record("中国联通", "Q4 2025", "revenue_growth_yoy", -0.230, "percent", "中国联通2025年度报告（600050 A股口径）", CU_2025_ANNUAL_SINA_URL, "A股口径2025Q4营业收入99,237.710百万元；对比2024Q4营业收入约99,466.273百万元，复算同比为-0.230%。", "official_full_year_minus_9m_prior_year_reconciliation", CU_2025_Q4_DETAIL_SOURCES),
    _official_record("中国联通", "Q4 2025", "total_assets", 671056.309, "millions CNY", "中国联通2025年度报告（600050 A股口径）", CU_2025_ANNUAL_SINA_URL, "A股年报资产负债表披露2025年12月31日资产总计671,056.309百万元。", "official_balance_sheet_row_check", CU_2025_Q4_DETAIL_SOURCES),
    _official_record("中国联通", "Q4 2025", "total_debt", 34086.496, "millions CNY", "中国联通2025年度报告（600050 A股口径）", CU_2025_ANNUAL_SINA_URL, "A股年报资产负债表披露短期借款965.579百万元、一年内到期的长期借款589.101百万元、一年内到期的租赁负债12,468.940百万元、长期借款3,928.359百万元、租赁负债16,134.517百万元，合计总债务34,086.496百万元。", "official_borrowings_plus_lease_liabilities_reconciliation", CU_2025_Q4_DETAIL_SOURCES),
    *HTHKH_2016_2020_OFFICIAL_VERIFICATIONS,
    *HTHKH_2021_2022_OFFICIAL_VERIFICATIONS,
    {
        "subject": "3HK / Hutchison", "period": "H1 2023", "metric_key": "revenue",
        "official_value": 2328, "unit": "millions HKD",
        "source_label": "HTHKH 2023 Interim Report", "source_url": HTHKH_2023_INTERIM_REPORT_URL,
        "evidence": "2023中报Financial Highlights、MD&A和损益表均披露1H 2023 Revenue/Total revenue为2,328百万港元。",
        "verification_method": "official_interim_report_multi_section_check", "verification_sources": HTHKH_2023_H1_SOURCES,
    },
    {
        "subject": "3HK / Hutchison", "period": "H1 2023", "metric_key": "revenue_growth_yoy",
        "official_value": 1.305, "unit": "percent",
        "source_label": "HTHKH 2023 Interim Report", "source_url": HTHKH_2023_H1_ANALYSIS_URL,
        "evidence": "2023中报披露1H 2023 Revenue 2,328、1H 2022 Revenue 2,298；复算同比为1.305%，MD&A披露约增长1%。",
        "verification_method": "official_interim_current_and_comparative_recalculation", "verification_sources": HTHKH_2023_H1_SOURCES[:2],
    },
    {
        "subject": "3HK / Hutchison", "period": "H1 2023", "metric_key": "gross_profit",
        "official_value": 1528, "unit": "millions HKD",
        "source_label": "HTHKH 2023 Interim Report - MD&A", "source_url": HTHKH_2023_H1_ANALYSIS_URL,
        "evidence": "2023中报MD&A披露1H 2023 Net customer service margin 1,516和Standalone hardware and other product sales margin 12，合计Total margin 1,528百万港元；CSV原值1,601与官方Total margin不一致。",
        "verification_method": "official_total_margin_reconciliation", "verification_sources": HTHKH_2023_H1_SOURCES[:2],
    },
    {
        "subject": "3HK / Hutchison", "period": "H1 2023", "metric_key": "ebitda",
        "official_value": 696, "unit": "millions HKD",
        "source_label": "HTHKH 2023 Interim Report - Supplementary Financial Information", "source_url": HTHKH_2023_INTERIM_REPORT_URL,
        "evidence": "2023中报调节表披露1H 2023公司及子公司EBITDA为696百万港元，另有合营公司份额31、Total EBITDA 727；CSV口径采用公司及子公司数。",
        "verification_method": "official_interim_reconciliation_table_check", "verification_sources": HTHKH_2023_H1_SOURCES,
    },
    {
        "subject": "3HK / Hutchison", "period": "H1 2023", "metric_key": "operating_income",
        "official_value": -43, "unit": "millions HKD",
        "source_label": "HTHKH 2023 Interim Report - Supplementary Financial Information", "source_url": HTHKH_2023_INTERIM_REPORT_URL,
        "evidence": "2023中报调节表披露1H 2023公司及子公司(LBIT)/EBIT为-43百万港元，另有合营公司份额8、Total LBIT -35；CSV口径采用公司及子公司数。",
        "verification_method": "official_interim_reconciliation_table_check", "verification_sources": HTHKH_2023_H1_SOURCES,
    },
    {
        "subject": "3HK / Hutchison", "period": "H1 2023", "metric_key": "operating_margin",
        "official_value": -1.847, "unit": "percent",
        "source_label": "HTHKH 2023 Interim Report", "source_url": HTHKH_2023_INTERIM_REPORT_URL,
        "evidence": "以1H 2023公司及子公司(LBIT)/EBIT -43除以Revenue 2,328，复算经营利润率为-1.847%。",
        "verification_method": "official_operating_income_divided_by_revenue_reconciliation", "verification_sources": HTHKH_2023_H1_SOURCES,
    },
    {
        "subject": "3HK / Hutchison", "period": "H1 2023", "metric_key": "net_income",
        "official_value": -19, "unit": "millions HKD",
        "source_label": "HTHKH 2023 Interim Report", "source_url": HTHKH_2023_INTERIM_REPORT_URL,
        "evidence": "2023中报Financial Highlights、MD&A和综合损益/调节表均披露1H 2023 Loss attributable to shareholders为19百万港元亏损。",
        "verification_method": "official_interim_report_multi_section_check", "verification_sources": HTHKH_2023_H1_SOURCES,
    },
    {
        "subject": "3HK / Hutchison", "period": "H1 2023", "metric_key": "operating_cash_flow",
        "official_value": 613, "unit": "millions HKD",
        "source_label": "HTHKH 2023 Interim Report - Cash Flows", "source_url": HTHKH_2023_INTERIM_REPORT_URL,
        "evidence": "2023中报现金流量表披露1H 2023 Net cash from operating activities为613百万港元。",
        "verification_method": "official_interim_cash_flow_check", "verification_sources": [HTHKH_2023_H1_SOURCES[2], HTHKH_2023_H1_SOURCES[1]],
    },
    {
        "subject": "3HK / Hutchison", "period": "H1 2023", "metric_key": "capital_expenditures",
        "official_value": -163, "unit": "millions HKD",
        "source_label": "HTHKH 2023 Interim Report", "source_url": HTHKH_2023_INTERIM_REPORT_URL,
        "evidence": "2023中报MD&A披露1H 2023 CAPEX excluding telecommunications licences为163百万港元；现金流量表列示Purchases of property, plant and equipment为163百万港元，现金流出口径记为负数。",
        "verification_method": "official_interim_capex_multi_section_check", "verification_sources": HTHKH_2023_H1_SOURCES,
    },
    {
        "subject": "3HK / Hutchison", "period": "H1 2023", "metric_key": "free_cash_flow",
        "official_value": 450, "unit": "millions HKD",
        "source_label": "HTHKH 2023 Interim Report - Cash Flows", "source_url": HTHKH_2023_INTERIM_REPORT_URL,
        "evidence": "1H 2023经营现金流613减购置固定资产163，复算自由现金流为450百万港元。",
        "verification_method": "official_operating_cash_flow_minus_capex", "verification_sources": HTHKH_2023_H1_SOURCES,
    },
    {
        "subject": "3HK / Hutchison", "period": "H1 2023", "metric_key": "cash_and_equivalents",
        "official_value": 814, "unit": "millions HKD",
        "source_label": "HTHKH 2023 Interim Report - Financial Statements", "source_url": HTHKH_2023_INTERIM_REPORT_URL,
        "evidence": "2023中报资产负债表和现金流量表均披露2023年6月30日Cash and cash equivalents为814百万港元。",
        "verification_method": "official_interim_balance_sheet_and_cash_flow_check", "verification_sources": HTHKH_2023_H1_SOURCES,
    },
    {
        "subject": "3HK / Hutchison", "period": "H1 2023", "metric_key": "total_assets",
        "official_value": 14750, "unit": "millions HKD",
        "source_label": "HTHKH 2023 Interim Report - Financial Statements", "source_url": HTHKH_2023_INTERIM_REPORT_URL,
        "evidence": "2023中报资产负债表披露非流动资产9,893、流动资产4,857，合计总资产14,750百万港元。",
        "verification_method": "official_interim_balance_sheet_reconciliation", "verification_sources": [HTHKH_2023_H1_SOURCES[2]],
    },
    {
        "subject": "3HK / Hutchison", "period": "H1 2023", "metric_key": "total_debt",
        "official_value": 526, "unit": "millions HKD",
        "source_label": "HTHKH 2023 Interim Report - Financial Statements", "source_url": HTHKH_2023_INTERIM_REPORT_URL,
        "evidence": "2023中报资产负债表披露流动租赁负债316、非流动租赁负债210，合计租赁债务526百万港元。",
        "verification_method": "official_interim_balance_sheet_reconciliation", "verification_sources": [HTHKH_2023_H1_SOURCES[2]],
    },
    {
        "subject": "3HK / Hutchison", "period": "H2 2023", "metric_key": "revenue",
        "official_value": 2568, "unit": "millions HKD",
        "source_label": "HTHKH 2023 Annual Report - MD&A", "source_url": HTHKH_2023_AR_ANALYSIS_URL,
        "evidence": "2023年报披露全年Revenue 4,896；减2023中报1H Revenue 2,328，复算H2为2,568百万港元。",
        "verification_method": "official_full_year_minus_h1_reconciliation", "verification_sources": HTHKH_2023_H2_SOURCES,
    },
    {
        "subject": "3HK / Hutchison", "period": "H2 2023", "metric_key": "revenue_growth_yoy",
        "official_value": -0.619, "unit": "percent",
        "source_label": "HTHKH 2023 Annual Report - MD&A", "source_url": HTHKH_2023_AR_ANALYSIS_URL,
        "evidence": "2023全年Revenue 4,896减1H 2,328得H2 2,568；2022全年Revenue 4,882减1H 2,298得H2 2,584；复算H2同比下降0.619%。",
        "verification_method": "official_full_year_minus_h1_prior_period_reconciliation", "verification_sources": HTHKH_2023_H2_SOURCES,
    },
    {
        "subject": "3HK / Hutchison", "period": "H2 2023", "metric_key": "gross_profit",
        "official_value": 1543, "unit": "millions HKD",
        "source_label": "HTHKH 2023 Annual Report - MD&A", "source_url": HTHKH_2023_AR_ANALYSIS_URL,
        "evidence": "2023年报披露全年Total margin 3,071；减2023中报1H Total margin 1,528，复算H2 Total margin为1,543百万港元；CSV原值1,529与官方Total margin不一致。",
        "verification_method": "official_full_year_minus_h1_total_margin_reconciliation", "verification_sources": HTHKH_2023_H2_SOURCES,
    },
    {
        "subject": "3HK / Hutchison", "period": "H2 2023", "metric_key": "ebitda",
        "official_value": 699, "unit": "millions HKD",
        "source_label": "HTHKH 2023 Annual Report - Supplementary Financial Information", "source_url": HTHKH_2023_AR_ANALYSIS_URL,
        "evidence": "2023年报调节表披露全年公司及子公司EBITDA 1,395；减1H公司及子公司EBITDA 696，复算H2为699百万港元。含合营公司份额的Total EBITDA为全年1,457、H1 727、H2 730。",
        "verification_method": "official_full_year_minus_h1_reconciliation_same_scope", "verification_sources": HTHKH_2023_H2_SOURCES,
    },
    {
        "subject": "3HK / Hutchison", "period": "H2 2023", "metric_key": "operating_income",
        "official_value": -43, "unit": "millions HKD",
        "source_label": "HTHKH 2023 Annual Report - Supplementary Financial Information", "source_url": HTHKH_2023_AR_ANALYSIS_URL,
        "evidence": "2023年报调节表披露全年公司及子公司(LBIT)/EBIT为-86；减1H公司及子公司(LBIT)/EBIT -43，复算H2经营亏损为43百万港元。",
        "verification_method": "official_full_year_minus_h1_reconciliation_same_scope", "verification_sources": HTHKH_2023_H2_SOURCES,
    },
    {
        "subject": "3HK / Hutchison", "period": "H2 2023", "metric_key": "operating_margin",
        "official_value": -1.674, "unit": "percent",
        "source_label": "HTHKH 2023 Annual Report - Supplementary Financial Information", "source_url": HTHKH_2023_AR_ANALYSIS_URL,
        "evidence": "以H2公司及子公司经营亏损-43除以H2 Revenue 2,568，复算经营利润率为-1.674%。",
        "verification_method": "official_operating_income_divided_by_revenue_reconciliation", "verification_sources": HTHKH_2023_H2_SOURCES,
    },
    {
        "subject": "3HK / Hutchison", "period": "H2 2023", "metric_key": "net_income",
        "official_value": -33, "unit": "millions HKD",
        "source_label": "HTHKH 2023 Annual Report", "source_url": HTHKH_2023_AR_HIGHLIGHTS_URL,
        "evidence": "2023年报披露全年Loss attributable to shareholders 52；减1H Loss attributable to shareholders 19，复算H2股东应占亏损33百万港元。",
        "verification_method": "official_full_year_minus_h1_reconciliation", "verification_sources": HTHKH_2023_H2_SOURCES,
    },
    {
        "subject": "3HK / Hutchison", "period": "H2 2023", "metric_key": "operating_cash_flow",
        "official_value": 514, "unit": "millions HKD",
        "source_label": "HTHKH 2023 Annual Report - Cash Flows", "source_url": HTHKH_2023_AR_CASHFLOW_URL,
        "evidence": "2023年报现金流量表披露全年Net cash from operating activities 1,127；减1H 613，复算H2为514百万港元。",
        "verification_method": "official_full_year_minus_h1_cash_flow_reconciliation", "verification_sources": HTHKH_2023_H2_SOURCES,
    },
    {
        "subject": "3HK / Hutchison", "period": "H2 2023", "metric_key": "capital_expenditures",
        "official_value": -318, "unit": "millions HKD",
        "source_label": "HTHKH 2023 Annual Report", "source_url": HTHKH_2023_AR_ANALYSIS_URL,
        "evidence": "2023年报披露全年CAPEX excluding telecommunications licences为481；减1H 163，复算H2资本开支318百万港元，现金流出口径记为负数；现金流量表全年购置固定资产同为481。",
        "verification_method": "official_full_year_minus_h1_capex_reconciliation", "verification_sources": HTHKH_2023_H2_SOURCES,
    },
    {
        "subject": "3HK / Hutchison", "period": "H2 2023", "metric_key": "free_cash_flow",
        "official_value": 196, "unit": "millions HKD",
        "source_label": "HTHKH 2023 Annual Report - Cash Flows", "source_url": HTHKH_2023_AR_CASHFLOW_URL,
        "evidence": "H2经营现金流514减H2购置固定资产318，复算自由现金流为196百万港元。",
        "verification_method": "official_operating_cash_flow_minus_capex", "verification_sources": HTHKH_2023_H2_SOURCES,
    },
    {
        "subject": "3HK / Hutchison", "period": "H2 2023", "metric_key": "cash_and_equivalents",
        "official_value": 1910, "unit": "millions HKD",
        "source_label": "HTHKH 2023 Annual Report - Financial Position", "source_url": HTHKH_2023_AR_POSITION_URL,
        "evidence": "2023年报资产负债表和现金流量表均披露2023年12月31日Cash and cash equivalents为1,910百万港元。",
        "verification_method": "official_annual_balance_sheet_and_cash_flow_check", "verification_sources": [HTHKH_2023_H2_SOURCES[4], HTHKH_2023_H2_SOURCES[3]],
    },
    {
        "subject": "3HK / Hutchison", "period": "H2 2023", "metric_key": "total_assets",
        "official_value": 14560, "unit": "millions HKD",
        "source_label": "HTHKH 2023 Annual Report - Financial Position", "source_url": HTHKH_2023_AR_POSITION_URL,
        "evidence": "2023年报资产负债表披露非流动资产9,715、流动资产4,845，合计总资产14,560百万港元。",
        "verification_method": "official_annual_balance_sheet_reconciliation", "verification_sources": [HTHKH_2023_H2_SOURCES[4]],
    },
    {
        "subject": "3HK / Hutchison", "period": "H2 2023", "metric_key": "total_debt",
        "official_value": 482, "unit": "millions HKD",
        "source_label": "HTHKH 2023 Annual Report - Financial Position", "source_url": HTHKH_2023_AR_POSITION_URL,
        "evidence": "2023年报资产负债表披露流动租赁负债312、非流动租赁负债170，合计租赁债务482百万港元。",
        "verification_method": "official_annual_balance_sheet_reconciliation", "verification_sources": [HTHKH_2023_H2_SOURCES[4]],
    },
    {
        "subject": "3HK / Hutchison", "period": "H1 2024", "metric_key": "revenue",
        "official_value": 2058, "unit": "millions HKD",
        "source_label": "HTHKH 2024 Interim Report", "source_url": HTHKH_2024_INTERIM_REPORT_URL,
        "evidence": "2024中报Financial Highlights、MD&A和损益表均披露1H 2024 Revenue/Total revenue为2,058百万港元。",
        "verification_method": "official_interim_report_multi_section_check", "verification_sources": HTHKH_2024_H1_SOURCES,
    },
    {
        "subject": "3HK / Hutchison", "period": "H1 2024", "metric_key": "revenue_growth_yoy",
        "official_value": -11.598, "unit": "percent",
        "source_label": "HTHKH 2024 Interim Report", "source_url": HTHKH_2024_H1_ANALYSIS_URL,
        "evidence": "2024中报披露1H 2024 Revenue 2,058、1H 2023 Revenue 2,328；复算同比为-11.598%，MD&A披露约下降12%。",
        "verification_method": "official_interim_current_and_comparative_recalculation", "verification_sources": HTHKH_2024_H1_SOURCES[:2],
    },
    {
        "subject": "3HK / Hutchison", "period": "H1 2024", "metric_key": "gross_profit",
        "official_value": 1523, "unit": "millions HKD",
        "source_label": "HTHKH 2024 Interim Report - MD&A", "source_url": HTHKH_2024_H1_ANALYSIS_URL,
        "evidence": "2024中报MD&A披露1H 2024 Net customer service margin 1,521和Standalone hardware and other product sales margin 2，合计Total margin 1,523百万港元；CSV原值1,530与官方Total margin不一致。",
        "verification_method": "official_total_margin_reconciliation", "verification_sources": HTHKH_2024_H1_SOURCES[:2],
    },
    {
        "subject": "3HK / Hutchison", "period": "H1 2024", "metric_key": "ebitda",
        "official_value": 700, "unit": "millions HKD",
        "source_label": "HTHKH 2024 Interim Report - Supplementary Financial Information", "source_url": HTHKH_2024_INTERIM_REPORT_URL,
        "evidence": "2024中报调节表披露1H 2024公司及子公司EBITDA为700百万港元，另有合营公司份额28、Total EBITDA 728；CSV口径采用公司及子公司数。",
        "verification_method": "official_interim_reconciliation_table_check", "verification_sources": HTHKH_2024_H1_SOURCES,
    },
    {
        "subject": "3HK / Hutchison", "period": "H1 2024", "metric_key": "operating_income",
        "official_value": -37, "unit": "millions HKD",
        "source_label": "HTHKH 2024 Interim Report - Supplementary Financial Information", "source_url": HTHKH_2024_INTERIM_REPORT_URL,
        "evidence": "2024中报调节表披露1H 2024公司及子公司(LBIT)/EBIT为-37百万港元，另有合营公司份额7、Total LBIT -30；CSV口径采用公司及子公司数。",
        "verification_method": "official_interim_reconciliation_table_check", "verification_sources": HTHKH_2024_H1_SOURCES,
    },
    {
        "subject": "3HK / Hutchison", "period": "H1 2024", "metric_key": "operating_margin",
        "official_value": -1.798, "unit": "percent",
        "source_label": "HTHKH 2024 Interim Report", "source_url": HTHKH_2024_INTERIM_REPORT_URL,
        "evidence": "以1H 2024公司及子公司(LBIT)/EBIT -37除以Revenue 2,058，复算经营利润率为-1.798%。",
        "verification_method": "official_operating_income_divided_by_revenue_reconciliation", "verification_sources": HTHKH_2024_H1_SOURCES,
    },
    {
        "subject": "3HK / Hutchison", "period": "H1 2024", "metric_key": "net_income",
        "official_value": -12, "unit": "millions HKD",
        "source_label": "HTHKH 2024 Interim Report", "source_url": HTHKH_2024_INTERIM_REPORT_URL,
        "evidence": "2024中报Financial Highlights、MD&A和综合损益/调节表均披露1H 2024 Loss attributable to shareholders为12百万港元亏损。",
        "verification_method": "official_interim_report_multi_section_check", "verification_sources": HTHKH_2024_H1_SOURCES,
    },
    {
        "subject": "3HK / Hutchison", "period": "H1 2024", "metric_key": "operating_cash_flow",
        "official_value": 529, "unit": "millions HKD",
        "source_label": "HTHKH 2024 Interim Report - Cash Flows", "source_url": HTHKH_2024_INTERIM_REPORT_URL,
        "evidence": "2024中报现金流量表披露1H 2024 Net cash from operating activities为529百万港元。",
        "verification_method": "official_interim_cash_flow_check", "verification_sources": [HTHKH_2024_H1_SOURCES[2], HTHKH_2024_H1_SOURCES[1]],
    },
    {
        "subject": "3HK / Hutchison", "period": "H1 2024", "metric_key": "capital_expenditures",
        "official_value": -166, "unit": "millions HKD",
        "source_label": "HTHKH 2024 Interim Report", "source_url": HTHKH_2024_INTERIM_REPORT_URL,
        "evidence": "2024中报MD&A披露1H 2024 CAPEX excluding telecommunications licences为166百万港元；现金流量表列示Purchases of property, plant and equipment为166百万港元，现金流出口径记为负数。",
        "verification_method": "official_interim_capex_multi_section_check", "verification_sources": HTHKH_2024_H1_SOURCES,
    },
    {
        "subject": "3HK / Hutchison", "period": "H1 2024", "metric_key": "free_cash_flow",
        "official_value": 363, "unit": "millions HKD",
        "source_label": "HTHKH 2024 Interim Report - Cash Flows", "source_url": HTHKH_2024_INTERIM_REPORT_URL,
        "evidence": "1H 2024经营现金流529减购置固定资产166，复算自由现金流为363百万港元。",
        "verification_method": "official_operating_cash_flow_minus_capex", "verification_sources": HTHKH_2024_H1_SOURCES,
    },
    {
        "subject": "3HK / Hutchison", "period": "H1 2024", "metric_key": "cash_and_equivalents",
        "official_value": 844, "unit": "millions HKD",
        "source_label": "HTHKH 2024 Interim Report - Financial Statements", "source_url": HTHKH_2024_INTERIM_REPORT_URL,
        "evidence": "2024中报资产负债表和现金流量表均披露2024年6月30日Cash and cash equivalents为844百万港元。",
        "verification_method": "official_interim_balance_sheet_and_cash_flow_check", "verification_sources": HTHKH_2024_H1_SOURCES,
    },
    {
        "subject": "3HK / Hutchison", "period": "H1 2024", "metric_key": "total_assets",
        "official_value": 14228, "unit": "millions HKD",
        "source_label": "HTHKH 2024 Interim Report - Financial Statements", "source_url": HTHKH_2024_INTERIM_REPORT_URL,
        "evidence": "2024中报资产负债表披露非流动资产9,389、流动资产4,839，合计总资产14,228百万港元。",
        "verification_method": "official_interim_balance_sheet_reconciliation", "verification_sources": [HTHKH_2024_H1_SOURCES[2]],
    },
    {
        "subject": "3HK / Hutchison", "period": "H1 2024", "metric_key": "total_debt",
        "official_value": 502, "unit": "millions HKD",
        "source_label": "HTHKH 2024 Interim Report - Financial Statements", "source_url": HTHKH_2024_INTERIM_REPORT_URL,
        "evidence": "2024中报资产负债表披露流动租赁负债334、非流动租赁负债168，合计租赁债务502百万港元。",
        "verification_method": "official_interim_balance_sheet_reconciliation", "verification_sources": [HTHKH_2024_H1_SOURCES[2]],
    },
    {
        "subject": "3HK / Hutchison", "period": "H2 2024", "metric_key": "revenue",
        "official_value": 2724, "unit": "millions HKD",
        "source_label": "HTHKH 2024 Annual Report - MD&A", "source_url": HTHKH_2024_AR_ANALYSIS_URL,
        "evidence": "2024年报披露全年Revenue 4,782；减2024中报1H Revenue 2,058，复算H2为2,724百万港元。",
        "verification_method": "official_full_year_minus_h1_reconciliation", "verification_sources": HTHKH_2024_H2_SOURCES,
    },
    {
        "subject": "3HK / Hutchison", "period": "H2 2024", "metric_key": "revenue_growth_yoy",
        "official_value": 6.075, "unit": "percent",
        "source_label": "HTHKH 2024 Annual Report - MD&A", "source_url": HTHKH_2024_AR_ANALYSIS_URL,
        "evidence": "2024全年Revenue 4,782减1H 2,058得H2 2,724；2023全年Revenue 4,896减1H 2,328得H2 2,568；复算H2同比增长6.075%。",
        "verification_method": "official_full_year_minus_h1_prior_period_reconciliation", "verification_sources": HTHKH_2024_H2_SOURCES,
    },
    {
        "subject": "3HK / Hutchison", "period": "H2 2024", "metric_key": "gross_profit",
        "official_value": 1548, "unit": "millions HKD",
        "source_label": "HTHKH 2024 Annual Report - MD&A", "source_url": HTHKH_2024_AR_ANALYSIS_URL,
        "evidence": "2024年报披露全年Total margin 3,071；减2024中报1H Total margin 1,523，复算H2 Total margin为1,548百万港元。",
        "verification_method": "official_full_year_minus_h1_total_margin_reconciliation", "verification_sources": HTHKH_2024_H2_SOURCES,
    },
    {
        "subject": "3HK / Hutchison", "period": "H2 2024", "metric_key": "ebitda",
        "official_value": 769, "unit": "millions HKD",
        "source_label": "HTHKH 2024 Annual Report - Supplementary Financial Information", "source_url": HTHKH_2024_AR_ANALYSIS_URL,
        "evidence": "2024年报调节表披露全年公司及子公司EBITDA 1,469；减1H公司及子公司EBITDA 700，复算H2为769百万港元。含合营公司份额的Total EBITDA为全年1,522、H1 728、H2 794。",
        "verification_method": "official_full_year_minus_h1_reconciliation_same_scope", "verification_sources": HTHKH_2024_H2_SOURCES,
    },
    {
        "subject": "3HK / Hutchison", "period": "H2 2024", "metric_key": "operating_income",
        "official_value": 15, "unit": "millions HKD",
        "source_label": "HTHKH 2024 Annual Report - Supplementary Financial Information", "source_url": HTHKH_2024_AR_ANALYSIS_URL,
        "evidence": "2024年报调节表披露全年公司及子公司(LBIT)/EBIT为-22；减1H公司及子公司(LBIT)/EBIT -37，复算H2经营利润为15百万港元。",
        "verification_method": "official_full_year_minus_h1_reconciliation_same_scope", "verification_sources": HTHKH_2024_H2_SOURCES,
    },
    {
        "subject": "3HK / Hutchison", "period": "H2 2024", "metric_key": "operating_margin",
        "official_value": 0.551, "unit": "percent",
        "source_label": "HTHKH 2024 Annual Report - Supplementary Financial Information", "source_url": HTHKH_2024_AR_ANALYSIS_URL,
        "evidence": "以H2公司及子公司经营利润15除以H2 Revenue 2,724，复算经营利润率为0.551%。",
        "verification_method": "official_operating_income_divided_by_revenue_reconciliation", "verification_sources": HTHKH_2024_H2_SOURCES,
    },
    {
        "subject": "3HK / Hutchison", "period": "H2 2024", "metric_key": "net_income",
        "official_value": 18, "unit": "millions HKD",
        "source_label": "HTHKH 2024 Annual Report", "source_url": HTHKH_2024_AR_HIGHLIGHTS_URL,
        "evidence": "2024年报披露全年Profit attributable to shareholders 6；减1H Loss attributable to shareholders -12，复算H2股东应占利润18百万港元。",
        "verification_method": "official_full_year_minus_h1_reconciliation", "verification_sources": HTHKH_2024_H2_SOURCES,
    },
    {
        "subject": "3HK / Hutchison", "period": "H2 2024", "metric_key": "operating_cash_flow",
        "official_value": 552, "unit": "millions HKD",
        "source_label": "HTHKH 2024 Annual Report - Cash Flows", "source_url": HTHKH_2024_AR_CASHFLOW_URL,
        "evidence": "2024年报现金流量表披露全年Net cash from operating activities 1,081；减1H 529，复算H2为552百万港元。",
        "verification_method": "official_full_year_minus_h1_cash_flow_reconciliation", "verification_sources": HTHKH_2024_H2_SOURCES,
    },
    {
        "subject": "3HK / Hutchison", "period": "H2 2024", "metric_key": "capital_expenditures",
        "official_value": -268, "unit": "millions HKD",
        "source_label": "HTHKH 2024 Annual Report", "source_url": HTHKH_2024_AR_ANALYSIS_URL,
        "evidence": "2024年报披露全年CAPEX excluding telecommunications licences为434；减1H 166，复算H2资本开支268百万港元，现金流出口径记为负数；现金流量表全年购置固定资产同为434。",
        "verification_method": "official_full_year_minus_h1_capex_reconciliation", "verification_sources": HTHKH_2024_H2_SOURCES,
    },
    {
        "subject": "3HK / Hutchison", "period": "H2 2024", "metric_key": "free_cash_flow",
        "official_value": 284, "unit": "millions HKD",
        "source_label": "HTHKH 2024 Annual Report - Cash Flows", "source_url": HTHKH_2024_AR_CASHFLOW_URL,
        "evidence": "H2经营现金流552减H2购置固定资产268，复算自由现金流为284百万港元。",
        "verification_method": "official_operating_cash_flow_minus_capex", "verification_sources": HTHKH_2024_H2_SOURCES,
    },
    {
        "subject": "3HK / Hutchison", "period": "H2 2024", "metric_key": "cash_and_equivalents",
        "official_value": 3168, "unit": "millions HKD",
        "source_label": "HTHKH 2024 Annual Report - Financial Position", "source_url": HTHKH_2024_AR_POSITION_URL,
        "evidence": "2024年报资产负债表和现金流量表均披露2024年12月31日Cash and cash equivalents为3,168百万港元。",
        "verification_method": "official_annual_balance_sheet_and_cash_flow_check", "verification_sources": [HTHKH_2024_H2_SOURCES[4], HTHKH_2024_H2_SOURCES[3]],
    },
    {
        "subject": "3HK / Hutchison", "period": "H2 2024", "metric_key": "total_assets",
        "official_value": 13970, "unit": "millions HKD",
        "source_label": "HTHKH 2024 Annual Report - Financial Position", "source_url": HTHKH_2024_AR_POSITION_URL,
        "evidence": "2024年报资产负债表披露非流动资产9,187、流动资产4,783，合计总资产13,970百万港元。",
        "verification_method": "official_annual_balance_sheet_reconciliation", "verification_sources": [HTHKH_2024_H2_SOURCES[4]],
    },
    {
        "subject": "3HK / Hutchison", "period": "H2 2024", "metric_key": "total_debt",
        "official_value": 463, "unit": "millions HKD",
        "source_label": "HTHKH 2024 Annual Report - Financial Position", "source_url": HTHKH_2024_AR_POSITION_URL,
        "evidence": "2024年报资产负债表披露流动租赁负债333、非流动租赁负债130，合计租赁债务463百万港元。",
        "verification_method": "official_annual_balance_sheet_reconciliation", "verification_sources": [HTHKH_2024_H2_SOURCES[4]],
    },
    {
        "subject": "3HK / Hutchison", "period": "H1 2025", "metric_key": "revenue",
        "official_value": 2216, "unit": "millions HKD",
        "source_label": "HTHKH 2025 Interim Report", "source_url": HTHKH_2025_H1_ANALYSIS_URL,
        "evidence": "2025中报Financial Performance Summary披露1H 2025 Revenue为2,216百万港元；Financial Highlights亦列示Total revenue 2,216百万港元。",
        "verification_method": "official_interim_report_multi_section_check", "verification_sources": HTHKH_2025_H1_SOURCES[:2],
    },
    {
        "subject": "3HK / Hutchison", "period": "H1 2025", "metric_key": "revenue_growth_yoy",
        "official_value": 7.677, "unit": "percent",
        "source_label": "HTHKH 2025 Interim Report", "source_url": HTHKH_2025_H1_ANALYSIS_URL,
        "evidence": "2025中报MD&A披露1H 2025 Revenue 2,216百万港元、1H 2024 Revenue 2,058百万港元；复算同比增长约7.677%，公告表格列示约+8%。",
        "verification_method": "official_interim_current_and_comparative_recalculation", "verification_sources": HTHKH_2025_H1_SOURCES[:2],
    },
    {
        "subject": "3HK / Hutchison", "period": "H1 2025", "metric_key": "service_revenue",
        "official_value": 1822, "unit": "millions HKD",
        "source_label": "HTHKH 2025 Interim Report", "source_url": HTHKH_2025_H1_ANALYSIS_URL,
        "evidence": "2025中报披露1H 2025 Net customer service revenue为1,822百万港元，同比增长4%。",
        "verification_method": "official_interim_report_multi_section_check", "verification_sources": HTHKH_2025_H1_SOURCES[:2],
    },
    {
        "subject": "3HK / Hutchison", "period": "H1 2025", "metric_key": "gross_profit",
        "official_value": 1525, "unit": "millions HKD",
        "source_label": "HTHKH 2025 Interim Report - MD&A", "source_url": HTHKH_2025_H1_ANALYSIS_URL,
        "evidence": "2025中报MD&A披露1H 2025 Net customer service margin 1,522和Standalone hardware and other product sales margin 3，合计Total margin 1,525百万港元；CSV gross_profit采用Total margin近似口径。",
        "verification_method": "official_total_margin_reconciliation", "verification_sources": HTHKH_2025_H1_SOURCES[:2],
    },
    {
        "subject": "3HK / Hutchison", "period": "H1 2025", "metric_key": "ebitda",
        "official_value": 771, "unit": "millions HKD",
        "source_label": "HTHKH 2025 Interim Report", "source_url": HTHKH_2025_H1_ANALYSIS_URL,
        "evidence": "2025中报Financial Highlights和MD&A均披露1H 2025 Total EBITDA为771百万港元。",
        "verification_method": "official_interim_report_multi_section_check", "verification_sources": HTHKH_2025_H1_SOURCES[:2],
    },
    {
        "subject": "3HK / Hutchison", "period": "H1 2025", "metric_key": "operating_income",
        "official_value": 6, "unit": "millions HKD",
        "source_label": "HTHKH 2025 Interim Report", "source_url": HTHKH_2025_H1_ANALYSIS_URL,
        "evidence": "2025中报Financial Highlights和MD&A披露1H 2025 EBIT为6百万港元；此处作为经营利润/EBIT口径核验。",
        "verification_method": "official_interim_report_multi_section_check", "verification_sources": HTHKH_2025_H1_SOURCES[:2],
    },
    {
        "subject": "3HK / Hutchison", "period": "H1 2025", "metric_key": "net_income",
        "official_value": 6, "unit": "millions HKD",
        "source_label": "HTHKH 2025 Interim Report", "source_url": HTHKH_2025_H1_ANALYSIS_URL,
        "evidence": "2025中报披露1H 2025 Profit attributable to shareholders为6百万港元。",
        "verification_method": "official_interim_report_multi_section_check", "verification_sources": HTHKH_2025_H1_SOURCES[:2],
    },
    {
        "subject": "3HK / Hutchison", "period": "H1 2025", "metric_key": "operating_cash_flow",
        "official_value": 668, "unit": "millions HKD",
        "source_label": "HTHKH 2025 Interim Report - Cash Flows", "source_url": HTHKH_2025_H1_CASHFLOW_URL,
        "evidence": "2025中报现金流量表披露1H 2025 Net cash from operating activities为668百万港元。",
        "verification_method": "official_interim_cash_flow_check", "verification_sources": [HTHKH_2025_H1_SOURCES[3], HTHKH_2025_H1_SOURCES[1]],
    },
    {
        "subject": "3HK / Hutchison", "period": "H1 2025", "metric_key": "capital_expenditures",
        "official_value": -174, "unit": "millions HKD",
        "source_label": "HTHKH 2025 Interim Report", "source_url": HTHKH_2025_H1_ANALYSIS_URL,
        "evidence": "2025中报MD&A披露1H 2025 CAPEX excluding telecommunications licences为174百万港元；现金流量表亦列示购买固定资产174百万港元，现金流出口径记为负数。",
        "verification_method": "official_interim_capex_multi_section_check", "verification_sources": [HTHKH_2025_H1_SOURCES[1], HTHKH_2025_H1_SOURCES[3]],
    },
    {
        "subject": "3HK / Hutchison", "period": "H1 2025", "metric_key": "free_cash_flow",
        "official_value": 494, "unit": "millions HKD",
        "source_label": "HTHKH 2025 Interim Report - Cash Flows", "source_url": HTHKH_2025_H1_CASHFLOW_URL,
        "evidence": "1H 2025经营现金流668减购置固定资产174，复算自由现金流为494百万港元。",
        "verification_method": "official_operating_cash_flow_minus_capex", "verification_sources": [HTHKH_2025_H1_SOURCES[3], HTHKH_2025_H1_SOURCES[1]],
    },
    {
        "subject": "3HK / Hutchison", "period": "H1 2025", "metric_key": "cash_and_equivalents",
        "official_value": 635, "unit": "millions HKD",
        "source_label": "HTHKH 2025 Interim Report - Financial Position", "source_url": HTHKH_2025_H1_POSITION_URL,
        "evidence": "2025中报资产负债表披露2025年6月30日Cash and cash equivalents为635百万港元；现金流量表期末现金亦为635百万港元。",
        "verification_method": "official_interim_balance_sheet_and_cash_flow_check", "verification_sources": [HTHKH_2025_H1_SOURCES[2], HTHKH_2025_H1_SOURCES[3]],
    },
    {
        "subject": "3HK / Hutchison", "period": "H1 2025", "metric_key": "total_assets",
        "official_value": 13634, "unit": "millions HKD",
        "source_label": "HTHKH 2025 Interim Report - Financial Position", "source_url": HTHKH_2025_H1_POSITION_URL,
        "evidence": "2025中报资产负债表披露非流动资产8,857、流动资产4,777，合计总资产13,634百万港元。",
        "verification_method": "official_interim_balance_sheet_reconciliation", "verification_sources": [HTHKH_2025_H1_SOURCES[2]],
    },
    {
        "subject": "3HK / Hutchison", "period": "H1 2025", "metric_key": "total_debt",
        "official_value": 454, "unit": "millions HKD",
        "source_label": "HTHKH 2025 Interim Report - Financial Position", "source_url": HTHKH_2025_H1_POSITION_URL,
        "evidence": "2025中报资产负债表披露流动租赁负债306、非流动租赁负债148，合计租赁债务454百万港元。",
        "verification_method": "official_interim_balance_sheet_reconciliation", "verification_sources": [HTHKH_2025_H1_SOURCES[2]],
    },
    {
        "subject": "3HK / Hutchison", "period": "H2 2025", "metric_key": "revenue",
        "official_value": 3232, "unit": "millions HKD",
        "source_label": "HTHKH 2025 Annual Report", "source_url": HTHKH_2025_AR_ANALYSIS_URL,
        "evidence": "2025年报披露全年香港业务Revenue 5,448；减1H Revenue 2,216，复算H2为3,232百万港元。",
        "verification_method": "official_full_year_minus_h1_reconciliation", "verification_sources": HTHKH_2025_H2_SOURCES,
    },
    {
        "subject": "3HK / Hutchison", "period": "H2 2025", "metric_key": "revenue_growth_yoy",
        "official_value": 25.029, "unit": "percent",
        "source_label": "HTHKH 2025 Annual Report", "source_url": HTHKH_2025_AR_ANALYSIS_URL,
        "evidence": "2025年报披露全年Revenue 5,448、2024重列全年Revenue 4,643；减1H 2025 Revenue 2,216和1H 2024 Revenue 2,058，复算H2 2025收入3,232、H2 2024收入2,585，同比增长约25.029%。",
        "verification_method": "official_full_year_minus_h1_prior_period_reconciliation", "verification_sources": HTHKH_2025_H2_SOURCES,
    },
    {
        "subject": "3HK / Hutchison", "period": "H2 2025", "metric_key": "service_revenue",
        "official_value": 1797, "unit": "millions HKD",
        "source_label": "HTHKH 2025 Annual Report", "source_url": HTHKH_2025_AR_ANALYSIS_URL,
        "evidence": "2025年报披露全年Net customer service revenue 3,619；减1H 1,822，复算H2为1,797百万港元。",
        "verification_method": "official_full_year_minus_h1_reconciliation", "verification_sources": HTHKH_2025_H2_SOURCES,
    },
    {
        "subject": "3HK / Hutchison", "period": "H2 2025", "metric_key": "gross_profit",
        "official_value": 1389, "unit": "millions HKD",
        "source_label": "HTHKH 2025 Annual Report - MD&A", "source_url": HTHKH_2025_AR_ANALYSIS_URL,
        "evidence": "2025年报披露全年Total margin 2,914；减2025中报1H Total margin 1,525，复算H2 Total margin为1,389百万港元；CSV gross_profit采用Total margin近似口径。",
        "verification_method": "official_full_year_minus_h1_total_margin_reconciliation", "verification_sources": HTHKH_2025_H2_SOURCES,
    },
    {
        "subject": "3HK / Hutchison", "period": "H2 2025", "metric_key": "ebitda",
        "official_value": 737, "unit": "millions HKD",
        "source_label": "HTHKH 2025 Annual Report", "source_url": HTHKH_2025_AR_ANALYSIS_URL,
        "evidence": "2025年报披露全年香港业务EBITDA 1,508；减1H EBITDA 771，复算H2为737百万港元。",
        "verification_method": "official_full_year_minus_h1_reconciliation", "verification_sources": HTHKH_2025_H2_SOURCES,
    },
    {
        "subject": "3HK / Hutchison", "period": "H2 2025", "metric_key": "operating_income",
        "official_value": 12, "unit": "millions HKD",
        "source_label": "HTHKH 2025 Annual Report", "source_url": HTHKH_2025_AR_ANALYSIS_URL,
        "evidence": "2025年报披露全年香港业务EBIT 18；减1H EBIT 6，复算H2 EBIT为12百万港元。",
        "verification_method": "official_full_year_minus_h1_reconciliation", "verification_sources": HTHKH_2025_H2_SOURCES,
    },
    {
        "subject": "3HK / Hutchison", "period": "H2 2025", "metric_key": "net_income",
        "official_value": -31, "unit": "millions HKD",
        "source_label": "HTHKH 2025 Annual Report", "source_url": HTHKH_2025_AR_HIGHLIGHTS_URL,
        "evidence": "2025年报披露全年集团股东应占亏损25；减1H股东应占利润6，复算H2集团股东应占亏损31百万港元。该口径包含已分类为终止经营的澳门业务影响。",
        "verification_method": "official_full_year_minus_h1_reconciliation_group_attributable", "verification_sources": HTHKH_2025_H2_SOURCES,
    },
    {
        "subject": "3HK / Hutchison", "period": "H2 2025", "metric_key": "operating_cash_flow",
        "official_value": 543, "unit": "millions HKD",
        "source_label": "HTHKH 2025 Annual Report - Cash Flows", "source_url": HTHKH_2025_AR_CASHFLOW_URL,
        "evidence": "2025年报现金流量表披露全年Net cash from operating activities 1,211；减1H 668，复算H2为543百万港元。",
        "verification_method": "official_full_year_minus_h1_cash_flow_reconciliation", "verification_sources": HTHKH_2025_H2_SOURCES,
    },
    {
        "subject": "3HK / Hutchison", "period": "H2 2025", "metric_key": "capital_expenditures",
        "official_value": -259, "unit": "millions HKD",
        "source_label": "HTHKH 2025 Annual Report", "source_url": HTHKH_2025_AR_ANALYSIS_URL,
        "evidence": "2025年报披露全年CAPEX excluding telecommunications licences为433；减1H 174，复算H2为259百万港元，现金流出口径记为负数。",
        "verification_method": "official_full_year_minus_h1_capex_reconciliation", "verification_sources": HTHKH_2025_H2_SOURCES,
    },
    {
        "subject": "3HK / Hutchison", "period": "H2 2025", "metric_key": "free_cash_flow",
        "official_value": 284, "unit": "millions HKD",
        "source_label": "HTHKH 2025 Annual Report - Cash Flows", "source_url": HTHKH_2025_AR_CASHFLOW_URL,
        "evidence": "H2经营现金流543减H2购置固定资产259，复算自由现金流为284百万港元。",
        "verification_method": "official_operating_cash_flow_minus_capex", "verification_sources": HTHKH_2025_H2_SOURCES,
    },
    {
        "subject": "3HK / Hutchison", "period": "H2 2025", "metric_key": "cash_and_equivalents",
        "official_value": 594, "unit": "millions HKD",
        "source_label": "HTHKH 2025 Annual Report - Financial Position", "source_url": HTHKH_2025_AR_POSITION_URL,
        "evidence": "2025年报资产负债表披露2025年12月31日Cash and cash equivalents为594百万港元；现金流量表因终止经营分类列示为605百万港元，采用资产负债表期末现金数。",
        "verification_method": "official_annual_balance_sheet_check", "verification_sources": [HTHKH_2025_H2_SOURCES[4], HTHKH_2025_H2_SOURCES[3]],
    },
    {
        "subject": "3HK / Hutchison", "period": "H2 2025", "metric_key": "total_assets",
        "official_value": 13412, "unit": "millions HKD",
        "source_label": "HTHKH 2025 Annual Report - Financial Position", "source_url": HTHKH_2025_AR_POSITION_URL,
        "evidence": "2025年报资产负债表披露非流动资产8,488、流动资产4,924，合计总资产13,412百万港元。",
        "verification_method": "official_annual_balance_sheet_reconciliation", "verification_sources": [HTHKH_2025_H2_SOURCES[4]],
    },
    {
        "subject": "3HK / Hutchison", "period": "H2 2025", "metric_key": "total_debt",
        "official_value": 401, "unit": "millions HKD",
        "source_label": "HTHKH 2025 Annual Report - Financial Position", "source_url": HTHKH_2025_AR_POSITION_URL,
        "evidence": "2025年报资产负债表披露流动租赁负债269、非流动租赁负债132，合计租赁债务401百万港元。",
        "verification_method": "official_annual_balance_sheet_reconciliation", "verification_sources": [HTHKH_2025_H2_SOURCES[4]],
    },
    *HKT_2016_2020_OFFICIAL_VERIFICATIONS,
    *HKT_2021_2022_OFFICIAL_VERIFICATIONS,
    *[
        {
            "subject": "HKT / csl / 1O1O",
            "period": period,
            "metric_key": metric_key,
            "official_value": official_value,
            "unit": "percent" if metric_key == "revenue_growth_yoy" else "millions HKD",
            "source_label": "HKT 2024 Annual Results Announcement",
            "source_url": HKT_2024_ANNUAL_RESULTS_URL,
            "evidence": evidence,
            "verification_method": verification_method,
            "verification_sources": sources,
        }
        for period, period_values in {
            "H1 2023": {
                "revenue": (16400, "Financial Review by Segment披露2023 H1 Total revenue为16,400百万港元。", "official_annual_segment_half_year_check", HKT_2024_SEGMENT_SOURCES),
                "gross_profit": (8121, "2023 H1 Total revenue 16,400减Cost of sales 8,279，复算毛利为8,121百万港元。", "official_revenue_minus_cost_of_sales", HKT_2024_SEGMENT_SOURCES),
                "ebitda": (6009, "Financial Review by Segment和Adjusted Funds Flow表均披露2023 H1 Total EBITDA为6,009百万港元。", "official_annual_segment_and_aff_check", HKT_2024_SEGMENT_SOURCES),
                "capital_expenditures": (-1078, "Adjusted Funds Flow表披露2023 H1 capital expenditures现金流出为1,078百万港元，记为负数。", "official_adjusted_funds_flow_capex_check", HKT_2024_SEGMENT_SOURCES),
                "adjusted_funds_flow": (2429, "Adjusted Funds Flow表披露2023 H1 adjusted funds flow为2,429百万港元。该口径不是HKFRS经营现金流，也不能等同普通自由现金流。", "official_adjusted_funds_flow_check", HKT_2024_SEGMENT_SOURCES),
                "profit_before_tax": (2333, "Financial Review by Segment披露2023 H1 Profit before income tax为2,333百万港元。", "official_annual_segment_half_year_check", HKT_2024_SEGMENT_SOURCES),
            },
            "H2 2023": {
                "revenue": (17930, "Financial Review by Segment披露2023 H2 Total revenue为17,930百万港元。", "official_annual_segment_half_year_check", HKT_2024_SEGMENT_SOURCES),
                "gross_profit": (8755, "2023 H2 Total revenue 17,930减Cost of sales 9,175，复算毛利为8,755百万港元。", "official_revenue_minus_cost_of_sales", HKT_2024_SEGMENT_SOURCES),
                "ebitda": (7391, "Financial Review by Segment和Adjusted Funds Flow表均披露2023 H2 Total EBITDA为7,391百万港元。", "official_annual_segment_and_aff_check", HKT_2024_SEGMENT_SOURCES),
                "capital_expenditures": (-1060, "Adjusted Funds Flow表披露2023 H2 capital expenditures现金流出为1,060百万港元，记为负数。", "official_adjusted_funds_flow_capex_check", HKT_2024_SEGMENT_SOURCES),
                "adjusted_funds_flow": (3369, "Adjusted Funds Flow表披露2023 H2 adjusted funds flow为3,369百万港元。该口径不是HKFRS经营现金流，也不能等同普通自由现金流。", "official_adjusted_funds_flow_check", HKT_2024_SEGMENT_SOURCES),
                "profit_before_tax": (3175, "Financial Review by Segment披露2023 H2 Profit before income tax为3,175百万港元。", "official_annual_segment_half_year_check", HKT_2024_SEGMENT_SOURCES),
                "cash_and_equivalents": (1630, "资产负债表披露2023年12月31日现金及现金等价物为1,630百万港元。", "official_annual_balance_sheet_check", HKT_2024_BALANCE_SOURCES),
                "total_assets": (112118, "资产负债表披露2023年12月31日非流动资产102,675、流动资产9,443，合计总资产112,118百万港元。", "official_annual_balance_sheet_reconciliation", HKT_2024_BALANCE_SOURCES),
                "total_debt": (44804, "管理层流动性披露2023年12月31日gross debt为44,804百万港元；gross debt定义为短期及长期借款本金，不含租赁负债。", "official_gross_debt_principal_check", HKT_2024_BALANCE_SOURCES),
            },
            "H1 2024": {
                "revenue": (16669, "Financial Review by Segment披露2024 H1 Total revenue为16,669百万港元。", "official_annual_segment_half_year_check", HKT_2024_SEGMENT_SOURCES),
                "revenue_growth_yoy": (1.640, "2024 H1 Total revenue 16,669对比2023 H1 16,400，复算同比增长约1.640%。", "official_current_prior_period_recalculation", HKT_2024_SEGMENT_SOURCES),
                "gross_profit": (8178, "2024 H1 Total revenue 16,669减Cost of sales 8,491，复算毛利为8,178百万港元。", "official_revenue_minus_cost_of_sales", HKT_2024_SEGMENT_SOURCES),
                "ebitda": (6168, "Financial Review by Segment和Adjusted Funds Flow表均披露2024 H1 Total EBITDA为6,168百万港元。", "official_annual_segment_and_aff_check", HKT_2024_SEGMENT_SOURCES),
                "capital_expenditures": (-1041, "Adjusted Funds Flow表披露2024 H1 capital expenditures现金流出为1,041百万港元，记为负数。", "official_adjusted_funds_flow_capex_check", HKT_2024_SEGMENT_SOURCES),
                "adjusted_funds_flow": (2495, "Adjusted Funds Flow表披露2024 H1 adjusted funds flow为2,495百万港元。该口径不是HKFRS经营现金流，也不能等同普通自由现金流。", "official_adjusted_funds_flow_check", HKT_2024_SEGMENT_SOURCES),
                "profit_before_tax": (2334, "Financial Review by Segment披露2024 H1 Profit before income tax为2,334百万港元。", "official_annual_segment_half_year_check", HKT_2024_SEGMENT_SOURCES),
            },
            "H2 2024": {
                "revenue": (18084, "Financial Review by Segment披露2024 H2 Total revenue为18,084百万港元。", "official_annual_segment_half_year_check", HKT_2024_SEGMENT_SOURCES),
                "revenue_growth_yoy": (0.859, "2024 H2 Total revenue 18,084对比2023 H2 17,930，复算同比增长约0.859%。", "official_current_prior_period_recalculation", HKT_2024_SEGMENT_SOURCES),
                "gross_profit": (8865, "2024 H2 Total revenue 18,084减Cost of sales 9,219，复算毛利为8,865百万港元。", "official_revenue_minus_cost_of_sales", HKT_2024_SEGMENT_SOURCES),
                "ebitda": (7575, "Financial Review by Segment和Adjusted Funds Flow表均披露2024 H2 Total EBITDA为7,575百万港元。", "official_annual_segment_and_aff_check", HKT_2024_SEGMENT_SOURCES),
                "capital_expenditures": (-996, "Adjusted Funds Flow表披露2024 H2 capital expenditures现金流出为996百万港元，记为负数。", "official_adjusted_funds_flow_capex_check", HKT_2024_SEGMENT_SOURCES),
                "adjusted_funds_flow": (3478, "Adjusted Funds Flow表披露2024 H2 adjusted funds flow为3,478百万港元。该口径不是HKFRS经营现金流，也不能等同普通自由现金流。", "official_adjusted_funds_flow_check", HKT_2024_SEGMENT_SOURCES),
                "profit_before_tax": (3681, "Financial Review by Segment披露2024 H2 Profit before income tax为3,681百万港元。", "official_annual_segment_half_year_check", HKT_2024_SEGMENT_SOURCES),
                "cash_and_equivalents": (1850, "资产负债表披露2024年12月31日现金及现金等价物为1,850百万港元。", "official_annual_balance_sheet_check", HKT_2024_BALANCE_SOURCES),
                "total_assets": (116813, "资产负债表披露2024年12月31日非流动资产105,928、流动资产10,885，合计总资产116,813百万港元。", "official_annual_balance_sheet_reconciliation", HKT_2024_BALANCE_SOURCES),
                "total_debt": (41723, "管理层流动性披露2024年12月31日gross debt为41,723百万港元；gross debt定义为短期及长期借款本金，不含租赁负债。", "official_gross_debt_principal_check", HKT_2024_BALANCE_SOURCES),
            },
        }.items()
        for metric_key, (official_value, evidence, verification_method, sources) in period_values.items()
    ],
    *[
        {
            "subject": "HKT / csl / 1O1O",
            "period": period,
            "metric_key": metric_key,
            "official_value": official_value,
            "unit": unit,
            "source_label": source_label,
            "source_url": source_url,
            "evidence": evidence,
            "verification_method": verification_method,
            "verification_sources": sources,
        }
        for period, period_values in {
            "H1 2023": {
                "net_income": (1952, "millions HKD", "HKT 2023 Interim Report", HKT_2023_INTERIM_REPORT_URL, "2023中报损益表披露2023 H1 holders of Share Stapled Units/shares of the Company应占利润为1,952百万港元；2024中报比较栏列示同值。", "official_interim_statement_and_comparative_check", HKT_2023_INTERIM_SOURCES),
                "operating_income": (3309, "millions HKD", "HKT 2024 Annual Results Announcement", HKT_2024_ANNUAL_RESULTS_URL, "2024年度业绩公告分部表披露2023 H1 EBITDA 6,009、折旧摊销2,700、处置损益0，复算经营利润为3,309百万港元。", "official_segment_ebitda_less_da_reconciliation", HKT_2024_SEGMENT_SOURCES),
                "operating_margin": (20.177, "percent", "HKT 2024 Annual Results Announcement", HKT_2024_ANNUAL_RESULTS_URL, "2023 H1经营利润3,309除以Total revenue 16,400，复算经营利润率约20.177%。", "official_operating_income_margin_recalculation", HKT_2024_SEGMENT_SOURCES),
                "operating_cash_flow": (4760, "millions HKD", "HKT 2023 Interim Report", HKT_2023_INTERIM_REPORT_URL, "2023中报现金流量表披露2023 H1 Net cash generated from operating activities为4,760百万港元；2024中报比较栏列示同值。", "official_interim_cashflow_and_comparative_check", HKT_2023_INTERIM_SOURCES),
                "free_cash_flow": (3682, "millions HKD", "HKT 2023 Interim Report and 2024 Annual Results Announcement", HKT_2023_INTERIM_REPORT_URL, "普通自由现金流按2023 H1经营现金流4,760减Adjusted Funds Flow表资本开支现金流出1,078复算为3,682百万港元；HKT官方AFF为独立口径，不等同普通FCF。", "official_operating_cash_flow_minus_capex_reconciliation", HKT_2023_INTERIM_SOURCES + HKT_2024_SEGMENT_SOURCES),
                "cash_and_equivalents": (1822, "millions HKD", "HKT 2023 Interim Report", HKT_2023_INTERIM_REPORT_URL, "2023中报资产负债表和现金流量表披露2023年6月30日现金及现金等价物为1,822百万港元。", "official_interim_balance_sheet_and_cashflow_check", HKT_2023_INTERIM_SOURCES),
                "total_assets": (109866, "millions HKD", "HKT 2023 Interim Report", HKT_2023_INTERIM_REPORT_URL, "2023中报资产负债表披露2023年6月30日非流动资产100,837、流动资产9,029，合计总资产109,866百万港元。", "official_interim_balance_sheet_reconciliation", HKT_2023_INTERIM_SOURCES),
                "total_debt": (45117, "millions HKD", "HKT 2023 Interim Report", HKT_2023_INTERIM_REPORT_URL, "2023中报管理层流动性披露2023年6月30日gross debt为45,117百万港元；gross debt定义为短期及长期借款本金，不含租赁负债。", "official_interim_gross_debt_principal_check", HKT_2023_INTERIM_SOURCES),
            },
            "H2 2023": {
                "net_income": (2997, "millions HKD", "HKT 2024 Annual Report", HKT_2024_ANNUAL_REPORT_URL, "2024年报损益表披露2023全年归母利润4,991百万港元，减2023 H1中报归母利润1,952，复算2023 H2为2,997百万港元。", "official_annual_minus_interim_statement_reconciliation", HKT_2024_ANNUAL_REPORT_SOURCES + HKT_2023_INTERIM_SOURCES),
                "operating_income": (4437, "millions HKD", "HKT 2024 Annual Results Announcement", HKT_2024_ANNUAL_RESULTS_URL, "2024年度业绩公告分部表披露2023 H2 EBITDA 7,391、折旧摊销2,952、处置损益为亏损2，复算经营利润为4,437百万港元。", "official_segment_ebitda_less_da_reconciliation", HKT_2024_SEGMENT_SOURCES),
                "operating_margin": (24.746, "percent", "HKT 2024 Annual Results Announcement", HKT_2024_ANNUAL_RESULTS_URL, "2023 H2经营利润4,437除以Total revenue 17,930，复算经营利润率约24.746%。", "official_operating_income_margin_recalculation", HKT_2024_SEGMENT_SOURCES),
                "operating_cash_flow": (6501, "millions HKD", "HKT 2024 Annual Report", HKT_2024_ANNUAL_REPORT_URL, "2024年报现金流量表披露2023全年经营现金流11,261百万港元，减2023 H1中报4,760，复算2023 H2为6,501百万港元。", "official_annual_minus_interim_cashflow_reconciliation", HKT_2024_ANNUAL_REPORT_SOURCES + HKT_2023_INTERIM_SOURCES),
                "free_cash_flow": (5441, "millions HKD", "HKT 2024 Annual Report and Annual Results Announcement", HKT_2024_ANNUAL_REPORT_URL, "普通自由现金流按2023 H2经营现金流6,501减Adjusted Funds Flow表资本开支现金流出1,060复算为5,441百万港元；HKT官方AFF为独立口径，不等同普通FCF。", "official_operating_cash_flow_minus_capex_reconciliation", HKT_2024_ANNUAL_REPORT_SOURCES + HKT_2024_SEGMENT_SOURCES),
            },
            "H1 2024": {
                "net_income": (1990, "millions HKD", "HKT 2024 Interim Report", HKT_2024_INTERIM_REPORT_URL, "2024中报损益表披露2024 H1 holders of Share Stapled Units/shares of the Company应占利润为1,990百万港元。", "official_interim_statement_check", HKT_2024_INTERIM_SOURCES),
                "operating_income": (3494, "millions HKD", "HKT 2024 Annual Results Announcement", HKT_2024_ANNUAL_RESULTS_URL, "2024年度业绩公告分部表披露2024 H1 EBITDA 6,168、折旧摊销2,683、处置收益9，复算经营利润为3,494百万港元。", "official_segment_ebitda_less_da_reconciliation", HKT_2024_SEGMENT_SOURCES),
                "operating_margin": (20.961, "percent", "HKT 2024 Annual Results Announcement", HKT_2024_ANNUAL_RESULTS_URL, "2024 H1经营利润3,494除以Total revenue 16,669，复算经营利润率约20.961%。", "official_operating_income_margin_recalculation", HKT_2024_SEGMENT_SOURCES),
                "operating_cash_flow": (5345, "millions HKD", "HKT 2024 Interim Report", HKT_2024_INTERIM_REPORT_URL, "2024中报现金流量表披露2024 H1 Net cash generated from operating activities为5,345百万港元。", "official_interim_cashflow_check", HKT_2024_INTERIM_SOURCES),
                "free_cash_flow": (4304, "millions HKD", "HKT 2024 Interim Report and Annual Results Announcement", HKT_2024_INTERIM_REPORT_URL, "普通自由现金流按2024 H1经营现金流5,345减Adjusted Funds Flow表资本开支现金流出1,041复算为4,304百万港元；HKT官方AFF为独立口径，不等同普通FCF。", "official_operating_cash_flow_minus_capex_reconciliation", HKT_2024_INTERIM_SOURCES + HKT_2024_SEGMENT_SOURCES),
                "cash_and_equivalents": (1480, "millions HKD", "HKT 2024 Interim Report", HKT_2024_INTERIM_REPORT_URL, "2024中报资产负债表和现金流量表披露2024年6月30日现金及现金等价物为1,480百万港元。", "official_interim_balance_sheet_and_cashflow_check", HKT_2024_INTERIM_SOURCES),
                "total_assets": (113722, "millions HKD", "HKT 2024 Interim Report", HKT_2024_INTERIM_REPORT_URL, "2024中报资产负债表披露2024年6月30日非流动资产103,927、流动资产9,795，合计总资产113,722百万港元。", "official_interim_balance_sheet_reconciliation", HKT_2024_INTERIM_SOURCES),
                "total_debt": (46344, "millions HKD", "HKT 2024 Interim Report", HKT_2024_INTERIM_REPORT_URL, "2024中报管理层流动性披露2024年6月30日gross debt为46,344百万港元；gross debt定义为短期及长期借款本金，不含租赁负债。", "official_interim_gross_debt_principal_check", HKT_2024_INTERIM_SOURCES),
            },
            "H2 2024": {
                "net_income": (3080, "millions HKD", "HKT 2024 Annual Report", HKT_2024_ANNUAL_REPORT_URL, "2024年报损益表披露2024全年归母利润5,070百万港元，减2024 H1中报归母利润1,990，复算2024 H2为3,080百万港元。", "official_annual_minus_interim_statement_reconciliation", HKT_2024_ANNUAL_REPORT_SOURCES + HKT_2024_INTERIM_SOURCES),
                "operating_income": (4754, "millions HKD", "HKT 2024 Annual Results Announcement", HKT_2024_ANNUAL_RESULTS_URL, "2024年度业绩公告分部表披露2024 H2 EBITDA 7,575、折旧摊销2,822、处置收益1，复算经营利润为4,754百万港元。", "official_segment_ebitda_less_da_reconciliation", HKT_2024_SEGMENT_SOURCES),
                "operating_margin": (26.288, "percent", "HKT 2024 Annual Results Announcement", HKT_2024_ANNUAL_RESULTS_URL, "2024 H2经营利润4,754除以Total revenue 18,084，复算经营利润率约26.288%。", "official_operating_income_margin_recalculation", HKT_2024_SEGMENT_SOURCES),
                "operating_cash_flow": (6566, "millions HKD", "HKT 2024 Annual Report", HKT_2024_ANNUAL_REPORT_URL, "2024年报现金流量表披露2024全年经营现金流11,911百万港元，减2024 H1中报5,345，复算2024 H2为6,566百万港元。", "official_annual_minus_interim_cashflow_reconciliation", HKT_2024_ANNUAL_REPORT_SOURCES + HKT_2024_INTERIM_SOURCES),
                "free_cash_flow": (5570, "millions HKD", "HKT 2024 Annual Report and Annual Results Announcement", HKT_2024_ANNUAL_REPORT_URL, "普通自由现金流按2024 H2经营现金流6,566减Adjusted Funds Flow表资本开支现金流出996复算为5,570百万港元；HKT官方AFF为独立口径，不等同普通FCF。", "official_operating_cash_flow_minus_capex_reconciliation", HKT_2024_ANNUAL_REPORT_SOURCES + HKT_2024_SEGMENT_SOURCES),
            },
        }.items()
        for metric_key, (official_value, unit, source_label, source_url, evidence, verification_method, sources) in period_values.items()
    ],
    {
        "subject": "HKT / csl / 1O1O", "period": "H1 2025", "metric_key": "revenue",
        "official_value": 17322, "unit": "millions HKD",
        "source_label": "HKT 2025 Annual Results Announcement", "source_url": HKT_2025_ANNUAL_RESULTS_URL,
        "evidence": "Financial Review by Segment披露2025 H1 Total revenue为17,322百万港元。",
        "verification_method": "official_annual_segment_half_year_check", "verification_sources": HKT_2025_SEGMENT_SOURCES,
    },
    {
        "subject": "HKT / csl / 1O1O", "period": "H2 2025", "metric_key": "revenue",
        "official_value": 19231, "unit": "millions HKD",
        "source_label": "HKT 2025 Annual Results Announcement", "source_url": HKT_2025_ANNUAL_RESULTS_URL,
        "evidence": "Financial Review by Segment披露2025 H2 Total revenue为19,231百万港元。",
        "verification_method": "official_annual_segment_half_year_check", "verification_sources": HKT_2025_SEGMENT_SOURCES,
    },
    {
        "subject": "HKT / csl / 1O1O", "period": "H1 2025", "metric_key": "gross_profit",
        "official_value": 8301, "unit": "millions HKD",
        "source_label": "HKT 2025 Annual Results Announcement", "source_url": HKT_2025_ANNUAL_RESULTS_URL,
        "evidence": "2025 H1 Total revenue 17,322减Cost of sales 9,021，复算毛利为8,301百万港元。",
        "verification_method": "official_revenue_minus_cost_of_sales", "verification_sources": HKT_2025_SEGMENT_SOURCES,
    },
    {
        "subject": "HKT / csl / 1O1O", "period": "H2 2025", "metric_key": "gross_profit",
        "official_value": 9112, "unit": "millions HKD",
        "source_label": "HKT 2025 Annual Results Announcement", "source_url": HKT_2025_ANNUAL_RESULTS_URL,
        "evidence": "2025 H2 Total revenue 19,231减Cost of sales 10,119，复算毛利为9,112百万港元。",
        "verification_method": "official_revenue_minus_cost_of_sales", "verification_sources": HKT_2025_SEGMENT_SOURCES,
    },
    {
        "subject": "HKT / csl / 1O1O", "period": "H1 2025", "metric_key": "ebitda",
        "official_value": 6380, "unit": "millions HKD",
        "source_label": "HKT 2025 Annual Results Announcement", "source_url": HKT_2025_ANNUAL_RESULTS_URL,
        "evidence": "Financial Review by Segment和Adjusted Funds Flow表均披露2025 H1 Total EBITDA为6,380百万港元。",
        "verification_method": "official_annual_segment_and_aff_check", "verification_sources": HKT_2025_SEGMENT_SOURCES,
    },
    {
        "subject": "HKT / csl / 1O1O", "period": "H2 2025", "metric_key": "ebitda",
        "official_value": 7854, "unit": "millions HKD",
        "source_label": "HKT 2025 Annual Results Announcement", "source_url": HKT_2025_ANNUAL_RESULTS_URL,
        "evidence": "Financial Review by Segment和Adjusted Funds Flow表均披露2025 H2 Total EBITDA为7,854百万港元。",
        "verification_method": "official_annual_segment_and_aff_check", "verification_sources": HKT_2025_SEGMENT_SOURCES,
    },
    {
        "subject": "HKT / csl / 1O1O", "period": "H1 2025", "metric_key": "capital_expenditures",
        "official_value": -1008, "unit": "millions HKD",
        "source_label": "HKT 2025 Annual Results Announcement", "source_url": HKT_2025_ANNUAL_RESULTS_URL,
        "evidence": "Adjusted Funds Flow表披露2025 H1 capital expenditures现金流出为1,008百万港元，记为负数。",
        "verification_method": "official_adjusted_funds_flow_capex_check", "verification_sources": HKT_2025_SEGMENT_SOURCES,
    },
    {
        "subject": "HKT / csl / 1O1O", "period": "H2 2025", "metric_key": "capital_expenditures",
        "official_value": -969, "unit": "millions HKD",
        "source_label": "HKT 2025 Annual Results Announcement", "source_url": HKT_2025_ANNUAL_RESULTS_URL,
        "evidence": "Adjusted Funds Flow表披露2025 H2 capital expenditures现金流出为969百万港元，记为负数。",
        "verification_method": "official_adjusted_funds_flow_capex_check", "verification_sources": HKT_2025_SEGMENT_SOURCES,
    },
    {
        "subject": "HKT / csl / 1O1O", "period": "H1 2025", "metric_key": "adjusted_funds_flow",
        "official_value": 2562, "unit": "millions HKD",
        "source_label": "HKT 2025 Annual Results Announcement", "source_url": HKT_2025_ANNUAL_RESULTS_URL,
        "evidence": "Adjusted Funds Flow表披露2025 H1 adjusted funds flow为2,562百万港元。该口径不是HKFRS经营现金流，也不能等同普通自由现金流。",
        "verification_method": "official_adjusted_funds_flow_check", "verification_sources": HKT_2025_SEGMENT_SOURCES,
    },
    {
        "subject": "HKT / csl / 1O1O", "period": "H2 2025", "metric_key": "adjusted_funds_flow",
        "official_value": 3637, "unit": "millions HKD",
        "source_label": "HKT 2025 Annual Results Announcement", "source_url": HKT_2025_ANNUAL_RESULTS_URL,
        "evidence": "Adjusted Funds Flow表披露2025 H2 adjusted funds flow为3,637百万港元。该口径不是HKFRS经营现金流，也不能等同普通自由现金流。",
        "verification_method": "official_adjusted_funds_flow_check", "verification_sources": HKT_2025_SEGMENT_SOURCES,
    },
    {
        "subject": "HKT / csl / 1O1O", "period": "H1 2025", "metric_key": "profit_before_tax",
        "official_value": 2712, "unit": "millions HKD",
        "source_label": "HKT 2025 Annual Results Announcement", "source_url": HKT_2025_ANNUAL_RESULTS_URL,
        "evidence": "Financial Review by Segment披露2025 H1 Profit before income tax为2,712百万港元。",
        "verification_method": "official_annual_segment_half_year_check", "verification_sources": HKT_2025_SEGMENT_SOURCES,
    },
    {
        "subject": "HKT / csl / 1O1O", "period": "H2 2025", "metric_key": "profit_before_tax",
        "official_value": 3942, "unit": "millions HKD",
        "source_label": "HKT 2025 Annual Results Announcement", "source_url": HKT_2025_ANNUAL_RESULTS_URL,
        "evidence": "Financial Review by Segment披露2025 H2 Profit before income tax为3,942百万港元。",
        "verification_method": "official_annual_segment_half_year_check", "verification_sources": HKT_2025_SEGMENT_SOURCES,
    },
    {
        "subject": "HKT / csl / 1O1O", "period": "H2 2025", "metric_key": "cash_and_equivalents",
        "official_value": 1957, "unit": "millions HKD",
        "source_label": "HKT 2025 Annual Results Announcement", "source_url": HKT_2025_ANNUAL_RESULTS_URL,
        "evidence": "资产负债表披露2025年12月31日现金及现金等价物为1,957百万港元。",
        "verification_method": "official_annual_balance_sheet_check", "verification_sources": HKT_2025_BALANCE_SOURCES,
    },
    {
        "subject": "HKT / csl / 1O1O", "period": "H2 2025", "metric_key": "total_assets",
        "official_value": 121152, "unit": "millions HKD",
        "source_label": "HKT 2025 Annual Results Announcement", "source_url": HKT_2025_ANNUAL_RESULTS_URL,
        "evidence": "资产负债表披露非流动资产109,033、流动资产12,119，合计总资产121,152百万港元。",
        "verification_method": "official_annual_balance_sheet_reconciliation", "verification_sources": HKT_2025_BALANCE_SOURCES,
    },
    {
        "subject": "HKT / csl / 1O1O", "period": "H2 2025", "metric_key": "total_debt",
        "official_value": 44750, "unit": "millions HKD",
        "source_label": "HKT 2025 Annual Results Announcement", "source_url": HKT_2025_ANNUAL_RESULTS_URL,
        "evidence": "管理层流动性披露2025年12月31日gross debt为44,750百万港元；gross debt定义为短期及长期借款本金，不含租赁负债。",
        "verification_method": "official_gross_debt_principal_check", "verification_sources": HKT_2025_BALANCE_SOURCES,
    },
    *[
        {
            "subject": "HKT / csl / 1O1O",
            "period": period,
            "metric_key": metric_key,
            "official_value": official_value,
            "unit": unit,
            "source_label": source_label,
            "source_url": source_url,
            "evidence": evidence,
            "verification_method": verification_method,
            "verification_sources": sources,
        }
        for period, period_values in {
            "H1 2023": {
                "revenue_growth_yoy": (1.504, "percent", "HKT 2023 Annual Report", HKT_2023_ANNUAL_REPORT_URL, "2023年报分部表披露2022 H1 Total revenue 16,157、2023 H1 16,400，复算同比增长约1.504%。", "official_prior_period_revenue_recalculation", HKT_2023_ANNUAL_REPORT_SOURCES),
            },
            "H2 2023": {
                "revenue_growth_yoy": (-0.211, "percent", "HKT 2023 Annual Report", HKT_2023_ANNUAL_REPORT_URL, "2023年报分部表披露2022 H2 Total revenue 17,968、2023 H2 17,930，复算同比下降约0.211%。", "official_prior_period_revenue_recalculation", HKT_2023_ANNUAL_REPORT_SOURCES),
            },
            "H1 2025": {
                "revenue_growth_yoy": (3.917, "percent", "HKT 2025 Annual Results Announcement", HKT_2025_ANNUAL_RESULTS_URL, "2025年度业绩公告分部表披露2024 H1 Total revenue 16,669、2025 H1 17,322，复算同比增长约3.917%。", "official_current_prior_period_recalculation", HKT_2025_SEGMENT_SOURCES),
                "net_income": (2070, "millions HKD", "HKT 2025 Interim Report", HKT_2025_INTERIM_REPORT_URL, "2025中报损益表披露2025 H1 holders of Share Stapled Units/shares of the Company应占利润为2,070百万港元。", "official_interim_statement_check", HKT_2025_INTERIM_SOURCES),
                "operating_income": (3624, "millions HKD", "HKT 2025 Annual Results Announcement", HKT_2025_ANNUAL_RESULTS_URL, "2025年度业绩公告分部表披露2025 H1 EBITDA 6,380、折旧摊销2,757、处置收益1，复算经营利润为3,624百万港元。", "official_segment_ebitda_less_da_reconciliation", HKT_2025_SEGMENT_SOURCES),
                "operating_margin": (20.921, "percent", "HKT 2025 Annual Results Announcement", HKT_2025_ANNUAL_RESULTS_URL, "2025 H1经营利润3,624除以Total revenue 17,322，复算经营利润率约20.921%。", "official_operating_income_margin_recalculation", HKT_2025_SEGMENT_SOURCES),
                "operating_cash_flow": (5313, "millions HKD", "HKT 2025 Interim Report", HKT_2025_INTERIM_REPORT_URL, "2025中报现金流量表披露2025 H1 Net cash generated from operating activities为5,313百万港元。", "official_interim_cashflow_check", HKT_2025_INTERIM_SOURCES),
                "free_cash_flow": (4305, "millions HKD", "HKT 2025 Interim Report and Annual Results Announcement", HKT_2025_INTERIM_REPORT_URL, "普通自由现金流按2025 H1经营现金流5,313减Adjusted Funds Flow表资本开支现金流出1,008复算为4,305百万港元；HKT官方AFF为独立口径，不等同普通FCF。", "official_operating_cash_flow_minus_capex_reconciliation", HKT_2025_INTERIM_SOURCES + HKT_2025_SEGMENT_SOURCES),
                "cash_and_equivalents": (1437, "millions HKD", "HKT 2025 Interim Report", HKT_2025_INTERIM_REPORT_URL, "2025中报资产负债表和现金流量表披露2025年6月30日现金及现金等价物为1,437百万港元。", "official_interim_balance_sheet_and_cashflow_check", HKT_2025_INTERIM_SOURCES),
                "total_assets": (118499, "millions HKD", "HKT 2025 Interim Report", HKT_2025_INTERIM_REPORT_URL, "2025中报资产负债表披露2025年6月30日非流动资产107,812、流动资产10,687，合计总资产118,499百万港元。", "official_interim_balance_sheet_reconciliation", HKT_2025_INTERIM_SOURCES),
                "total_debt": (43433, "millions HKD", "HKT 2025 Interim Report", HKT_2025_INTERIM_REPORT_URL, "2025中报管理层流动性披露2025年6月30日gross debt为43,433百万港元；gross debt定义为短期及长期借款本金，不含租赁负债。", "official_interim_gross_debt_principal_check", HKT_2025_INTERIM_SOURCES),
            },
            "H2 2025": {
                "revenue_growth_yoy": (6.343, "percent", "HKT 2025 Annual Results Announcement", HKT_2025_ANNUAL_RESULTS_URL, "2025年度业绩公告分部表披露2024 H2 Total revenue 18,084、2025 H2 19,231，复算同比增长约6.343%。", "official_current_prior_period_recalculation", HKT_2025_SEGMENT_SOURCES),
                "net_income": (3216, "millions HKD", "HKT 2025 Annual Report", HKT_2025_ANNUAL_REPORT_URL, "2025年报损益表披露2025全年归母利润5,286百万港元，减2025 H1中报归母利润2,070，复算2025 H2为3,216百万港元。", "official_annual_minus_interim_statement_reconciliation", HKT_2025_BALANCE_SOURCES + HKT_2025_INTERIM_SOURCES),
                "operating_income": (4778, "millions HKD", "HKT 2025 Annual Results Announcement", HKT_2025_ANNUAL_RESULTS_URL, "2025年度业绩公告分部表披露2025 H2 EBITDA 7,854、折旧摊销3,080、处置收益4，复算经营利润为4,778百万港元。", "official_segment_ebitda_less_da_reconciliation", HKT_2025_SEGMENT_SOURCES),
                "operating_margin": (24.845, "percent", "HKT 2025 Annual Results Announcement", HKT_2025_ANNUAL_RESULTS_URL, "2025 H2经营利润4,778除以Total revenue 19,231，复算经营利润率约24.845%。", "official_operating_income_margin_recalculation", HKT_2025_SEGMENT_SOURCES),
                "operating_cash_flow": (6315, "millions HKD", "HKT 2025 Annual Report", HKT_2025_ANNUAL_REPORT_URL, "2025年报现金流量表披露2025全年经营现金流11,628百万港元，减2025 H1中报5,313，复算2025 H2为6,315百万港元。", "official_annual_minus_interim_cashflow_reconciliation", HKT_2025_BALANCE_SOURCES + HKT_2025_INTERIM_SOURCES),
                "free_cash_flow": (5346, "millions HKD", "HKT 2025 Annual Report and Annual Results Announcement", HKT_2025_ANNUAL_REPORT_URL, "普通自由现金流按2025 H2经营现金流6,315减Adjusted Funds Flow表资本开支现金流出969复算为5,346百万港元；HKT官方AFF为独立口径，不等同普通FCF。", "official_operating_cash_flow_minus_capex_reconciliation", HKT_2025_BALANCE_SOURCES + HKT_2025_SEGMENT_SOURCES),
            },
        }.items()
        for metric_key, (official_value, unit, source_label, source_url, evidence, verification_method, sources) in period_values.items()
    ],
    *SMARTONE_2016_2021_OFFICIAL_VERIFICATIONS,
    *[
        {
            "subject": "SmarTone",
            "period": period,
            "metric_key": metric_key,
            "official_value": official_value,
            "unit": unit,
            "source_label": source_label,
            "source_url": source_url,
            "evidence": evidence,
            "verification_method": verification_method,
            "verification_sources": sources,
        }
        for period, period_values in {
            "H2 2021": {
                "revenue": (3475.995, "millions HKD", "SmarTone 2020/21 Annual Report", SMARTONE_2021_H2_REPORT_URL, "2020/21年报披露全年Revenues 6,720,308千港元；减2020/21中期Revenues 3,244,313千港元，复算H2 2021为3,475,995千港元。", "official_annual_minus_interim_reconciliation", SMARTONE_2021_H2_SOURCES),
                "gross_profit": (2026.988, "millions HKD", "SmarTone 2020/21 Annual Report", SMARTONE_2021_H2_REPORT_URL, "2020/21全年毛利按Revenues 6,720,308减Cost of inventories sold 2,315,791和Cost of services provided 372,041为4,032,476千港元；减H1毛利2,005,488后H2为2,026,988千港元。", "official_annual_minus_interim_gross_profit_reconciliation", SMARTONE_2021_H2_SOURCES),
                "ebitda": (1186.940, "millions HKD", "SmarTone 2020/21 Annual Report", SMARTONE_2021_H2_REPORT_URL, "2020/21年报分部附注披露全年EBITDA 2,459,591千港元；减2020/21中期EBITDA 1,272,651后H2为1,186,940千港元。", "official_annual_minus_interim_ebitda_reconciliation", SMARTONE_2021_H2_SOURCES),
                "operating_income": (294.200, "millions HKD", "SmarTone 2020/21 Annual Report", SMARTONE_2021_H2_REPORT_URL, "2020/21年报披露全年Operating profit 674,215千港元；减2020/21中期Operating profit 380,015后H2为294,200千港元。", "official_annual_minus_interim_reconciliation", SMARTONE_2021_H2_SOURCES),
                "operating_margin": (8.464, "percent", "SmarTone 2020/21 Annual Report", SMARTONE_2021_H2_REPORT_URL, "H2 2021 Operating profit 294,200千港元除以H2 Revenues 3,475,995千港元，复算经营利润率约8.464%。", "official_operating_income_margin_recalculation", SMARTONE_2021_H2_SOURCES),
                "net_income": (178.025, "millions HKD", "SmarTone 2020/21 Annual Report", SMARTONE_2021_H2_REPORT_URL, "2020/21年报披露全年Company's shareholders应占利润445,334千港元；减2020/21中期267,309千港元后H2为178,025千港元。", "official_annual_minus_interim_reconciliation", SMARTONE_2021_H2_SOURCES),
                "operating_cash_flow": (1229.037, "millions HKD", "SmarTone 2020/21 Annual Report", SMARTONE_2021_H2_REPORT_URL, "2020/21年报现金流量表披露全年经营现金流2,420,431千港元；减2020/21中期1,191,394后H2为1,229,037千港元。", "official_annual_minus_interim_cash_flow_reconciliation", SMARTONE_2021_H2_SOURCES),
                "capital_expenditures": (-315.872, "millions HKD", "SmarTone 2020/21 Annual Report", SMARTONE_2021_H2_REPORT_URL, "2020/21年报现金流量表披露全年购买固定资产付款850,507千港元；减2020/21中期534,635后H2为315,872千港元，现金流出口径记为负数。", "official_annual_minus_interim_cash_flow_reconciliation", SMARTONE_2021_H2_SOURCES),
                "free_cash_flow": (913.165, "millions HKD", "SmarTone 2020/21 Annual Report", SMARTONE_2021_H2_REPORT_URL, "H2经营现金流1,229,037千港元减购买固定资产付款315,872千港元，复算普通自由现金流为913,165千港元。", "official_operating_cash_flow_minus_capex_reconciliation", SMARTONE_2021_H2_SOURCES),
                "cash_and_equivalents": (2094.884, "millions HKD", "SmarTone 2020/21 Annual Report", SMARTONE_2021_H2_REPORT_URL, "2020/21年报资产负债表披露2021年6月30日Cash and cash equivalents为2,094,884千港元。", "official_annual_balance_sheet_check", SMARTONE_2021_H2_SOURCES),
                "total_assets": (10650.059, "millions HKD", "SmarTone 2020/21 Annual Report", SMARTONE_2021_H2_REPORT_URL, "2020/21年报资产负债表披露非流动资产7,465,501千港元、流动资产3,184,558千港元，合计总资产10,650,059千港元。", "official_annual_balance_sheet_reconciliation", SMARTONE_2021_H2_SOURCES),
                "total_debt": (2485.726, "millions HKD", "SmarTone 2020/21 Annual Report", SMARTONE_2021_H2_REPORT_URL, "2020/21年报资产负债表披露银行及其他借款77,189和1,510,771千港元、租赁负债546,301和351,465千港元，合计债务2,485,726千港元；不含spectrum utilization fee liabilities。", "official_bank_borrowings_plus_lease_liabilities_reconciliation", SMARTONE_2021_H2_SOURCES),
                "revenue_growth_yoy": (27.333, "percent", "SmarTone 2020/21 Annual Report", SMARTONE_2021_H2_REPORT_URL, "H2 2021 Revenues 3,475,995千港元，对比H2 2020由FY2020 6,986,451减H1 2020 4,256,606得2,729,845千港元，复算同比增长约27.333%。", "official_current_prior_period_recalculation", SMARTONE_2021_H2_SOURCES),
            },
            "H1 2022": {
                "revenue": (3791.522, "millions HKD", "SmarTone 2021/22 Interim Report", SMARTONE_2022_H1_REPORT_URL, "2021/22中期损益表披露截至2021年12月31日六个月Revenues为3,791,522千港元。", "official_interim_statement_check", SMARTONE_2022_H1_SOURCES),
                "gross_profit": (2105.234, "millions HKD", "SmarTone 2021/22 Interim Report", SMARTONE_2022_H1_REPORT_URL, "2021/22中期损益表披露Revenues 3,791,522、Cost of inventories sold 1,492,196、Cost of services provided 194,092，复算毛利为2,105,234千港元。", "official_revenue_minus_costs_reconciliation", SMARTONE_2022_H1_SOURCES),
                "ebitda": (1296.971, "millions HKD", "SmarTone 2021/22 Interim Report", SMARTONE_2022_H1_REPORT_URL, "2021/22中期分部附注披露集团EBITDA为1,296,971千港元。", "official_interim_segment_ebitda_check", SMARTONE_2022_H1_SOURCES),
                "operating_income": (390.905, "millions HKD", "SmarTone 2021/22 Interim Report", SMARTONE_2022_H1_REPORT_URL, "2021/22中期损益表披露Operating profit为390,905千港元。", "official_interim_statement_check", SMARTONE_2022_H1_SOURCES),
                "operating_margin": (10.310, "percent", "SmarTone 2021/22 Interim Report", SMARTONE_2022_H1_REPORT_URL, "H1 2022 Operating profit 390,905千港元除以Revenues 3,791,522千港元，复算经营利润率约10.310%。", "official_operating_income_margin_recalculation", SMARTONE_2022_H1_SOURCES),
                "net_income": (251.383, "millions HKD", "SmarTone 2021/22 Interim Report", SMARTONE_2022_H1_REPORT_URL, "2021/22中期损益表披露Company's shareholders应占利润为251,383千港元。", "official_interim_statement_check", SMARTONE_2022_H1_SOURCES),
                "operating_cash_flow": (1059.773, "millions HKD", "SmarTone 2021/22 Interim Report", SMARTONE_2022_H1_REPORT_URL, "2021/22中期现金流量表披露Net cash inflow from operating activities为1,059,773千港元。", "official_interim_cash_flow_check", SMARTONE_2022_H1_SOURCES),
                "capital_expenditures": (-375.924, "millions HKD", "SmarTone 2021/22 Interim Report", SMARTONE_2022_H1_REPORT_URL, "2021/22中期现金流量表披露Payment for purchase of fixed assets为375,924千港元，现金流出口径记为负数。", "official_interim_cash_flow_check", SMARTONE_2022_H1_SOURCES),
                "free_cash_flow": (683.849, "millions HKD", "SmarTone 2021/22 Interim Report", SMARTONE_2022_H1_REPORT_URL, "经营现金流1,059,773千港元减购买固定资产付款375,924千港元，复算普通自由现金流为683,849千港元。", "official_operating_cash_flow_minus_capex_reconciliation", SMARTONE_2022_H1_SOURCES),
                "cash_and_equivalents": (2100.936, "millions HKD", "SmarTone 2021/22 Interim Report", SMARTONE_2022_H1_REPORT_URL, "2021/22中期资产负债表披露2021年12月31日Cash and cash equivalents为2,100,936千港元。", "official_interim_balance_sheet_check", SMARTONE_2022_H1_SOURCES),
                "total_assets": (12756.354, "millions HKD", "SmarTone 2021/22 Interim Report", SMARTONE_2022_H1_REPORT_URL, "2021/22中期资产负债表披露非流动资产9,304,826千港元、流动资产3,451,528千港元，合计总资产12,756,354千港元。", "official_interim_balance_sheet_reconciliation", SMARTONE_2022_H1_SOURCES),
                "total_debt": (2390.502, "millions HKD", "SmarTone 2021/22 Interim Report", SMARTONE_2022_H1_REPORT_URL, "2021/22中期资产负债表披露银行及其他借款55,063和1,490,538千港元、租赁负债519,105和325,796千港元，合计债务2,390,502千港元；不含spectrum utilization fee liabilities。", "official_bank_borrowings_plus_lease_liabilities_reconciliation", SMARTONE_2022_H1_SOURCES),
                "revenue_growth_yoy": (16.867, "percent", "SmarTone 2021/22 Interim Report", SMARTONE_2022_H1_REPORT_URL, "2021/22中期损益表披露H1 2022 Revenues 3,791,522千港元、H1 2021比较数3,244,313千港元，复算同比增长约16.867%。", "official_current_prior_period_recalculation", SMARTONE_2022_H1_SOURCES),
            },
            "H2 2022": {
                "revenue": (3165.763, "millions HKD", "SmarTone 2021/22 Annual Report", SMARTONE_2022_H2_REPORT_URL, "2021/22年报披露全年Revenues 6,957,285千港元；减2021/22中期Revenues 3,791,522千港元，复算H2 2022为3,165,763千港元。", "official_annual_minus_interim_reconciliation", SMARTONE_2022_H2_SOURCES),
                "gross_profit": (2079.574, "millions HKD", "SmarTone 2021/22 Annual Report", SMARTONE_2022_H2_REPORT_URL, "2021/22全年毛利按Revenues 6,957,285减Cost of inventories sold 2,402,302和Cost of services provided 370,175为4,184,808千港元；减H1毛利2,105,234后H2为2,079,574千港元。", "official_annual_minus_interim_gross_profit_reconciliation", SMARTONE_2022_H2_SOURCES),
                "ebitda": (1278.358, "millions HKD", "SmarTone 2021/22 Annual Report", SMARTONE_2022_H2_REPORT_URL, "2021/22年报分部附注披露全年EBITDA 2,575,329千港元；减2021/22中期EBITDA 1,296,971后H2为1,278,358千港元。", "official_annual_minus_interim_ebitda_reconciliation", SMARTONE_2022_H2_SOURCES),
                "operating_income": (352.717, "millions HKD", "SmarTone 2021/22 Annual Report", SMARTONE_2022_H2_REPORT_URL, "2021/22年报披露全年Operating profit 743,622千港元；减2021/22中期Operating profit 390,905后H2为352,717千港元。", "official_annual_minus_interim_reconciliation", SMARTONE_2022_H2_SOURCES),
                "operating_margin": (11.142, "percent", "SmarTone 2021/22 Annual Report", SMARTONE_2022_H2_REPORT_URL, "H2 2022 Operating profit 352,717千港元除以H2 Revenues 3,165,763千港元，复算经营利润率约11.142%。", "official_operating_income_margin_recalculation", SMARTONE_2022_H2_SOURCES),
                "net_income": (171.787, "millions HKD", "SmarTone 2021/22 Annual Report", SMARTONE_2022_H2_REPORT_URL, "2021/22年报披露全年Company's shareholders应占利润423,170千港元；减2021/22中期251,383千港元后H2为171,787千港元。", "official_annual_minus_interim_reconciliation", SMARTONE_2022_H2_SOURCES),
                "operating_cash_flow": (976.383, "millions HKD", "SmarTone 2021/22 Annual Report", SMARTONE_2022_H2_REPORT_URL, "2021/22年报现金流量表披露全年经营现金流2,036,156千港元；减2021/22中期1,059,773后H2为976,383千港元。", "official_annual_minus_interim_cash_flow_reconciliation", SMARTONE_2022_H2_SOURCES),
                "capital_expenditures": (-335.752, "millions HKD", "SmarTone 2021/22 Annual Report", SMARTONE_2022_H2_REPORT_URL, "2021/22年报现金流量表披露全年购买固定资产付款711,676千港元；减2021/22中期375,924后H2为335,752千港元，现金流出口径记为负数。", "official_annual_minus_interim_cash_flow_reconciliation", SMARTONE_2022_H2_SOURCES),
                "free_cash_flow": (640.631, "millions HKD", "SmarTone 2021/22 Annual Report", SMARTONE_2022_H2_REPORT_URL, "H2经营现金流976,383千港元减购买固定资产付款335,752千港元，复算普通自由现金流为640,631千港元。", "official_operating_cash_flow_minus_capex_reconciliation", SMARTONE_2022_H2_SOURCES),
                "cash_and_equivalents": (385.467, "millions HKD", "SmarTone 2021/22 Annual Report", SMARTONE_2022_H2_REPORT_URL, "2021/22年报资产负债表披露2022年6月30日Cash and cash equivalents为385,467千港元。", "official_annual_balance_sheet_check", SMARTONE_2022_H2_SOURCES),
                "total_assets": (12581.132, "millions HKD", "SmarTone 2021/22 Annual Report", SMARTONE_2022_H2_REPORT_URL, "2021/22年报资产负债表披露非流动资产9,179,727千港元、流动资产3,401,405千港元，合计总资产12,581,132千港元。", "official_annual_balance_sheet_reconciliation", SMARTONE_2022_H2_SOURCES),
                "total_debt": (2415.633, "millions HKD", "SmarTone 2021/22 Annual Report", SMARTONE_2022_H2_REPORT_URL, "2021/22年报资产负债表披露银行及其他借款1,444,812和66,000千港元、租赁负债576,299和328,522千港元，合计债务2,415,633千港元；不含spectrum utilization fee liabilities。", "official_bank_borrowings_plus_lease_liabilities_reconciliation", SMARTONE_2022_H2_SOURCES),
                "revenue_growth_yoy": (-8.925, "percent", "SmarTone 2021/22 Annual Report", SMARTONE_2022_H2_REPORT_URL, "H2 2022 Revenues 3,165,763千港元，对比H2 2021 Revenues 3,475,995千港元，复算同比下降约8.925%。", "official_current_prior_period_recalculation", SMARTONE_2022_H2_SOURCES),
            },
            "H1 2023": {
                "revenue": (3809.011, "millions HKD", "SmarTone 2022/23 Interim Report", SMARTONE_2023_H1_REPORT_URL, "2022/23中期损益表披露截至2022年12月31日六个月Revenues为3,809,011千港元。", "official_interim_statement_check", SMARTONE_2023_H1_SOURCES),
                "gross_profit": (2143.298, "millions HKD", "SmarTone 2022/23 Interim Report", SMARTONE_2023_H1_REPORT_URL, "2022/23中期损益表披露Revenues 3,809,011、Cost of inventories sold 1,457,910、Cost of services provided 207,803，复算毛利为2,143,298千港元。", "official_revenue_minus_costs_reconciliation", SMARTONE_2023_H1_SOURCES),
                "ebitda": (1279.065, "millions HKD", "SmarTone 2022/23 Interim Report", SMARTONE_2023_H1_REPORT_URL, "2022/23中期分部附注披露集团EBITDA为1,279,065千港元。", "official_interim_segment_ebitda_check", SMARTONE_2023_H1_SOURCES),
                "operating_income": (391.373, "millions HKD", "SmarTone 2022/23 Interim Report", SMARTONE_2023_H1_REPORT_URL, "2022/23中期损益表披露Operating profit为391,373千港元。", "official_interim_statement_check", SMARTONE_2023_H1_SOURCES),
                "operating_margin": (10.275, "percent", "SmarTone 2022/23 Interim Report", SMARTONE_2023_H1_REPORT_URL, "2022/23 H1 Operating profit 391,373除以Revenues 3,809,011，复算经营利润率约10.275%。", "official_operating_income_margin_recalculation", SMARTONE_2023_H1_SOURCES),
                "net_income": (255.832, "millions HKD", "SmarTone 2022/23 Interim Report", SMARTONE_2023_H1_REPORT_URL, "2022/23中期损益表披露Company's shareholders应占利润为255,832千港元。", "official_interim_statement_check", SMARTONE_2023_H1_SOURCES),
                "operating_cash_flow": (1245.012, "millions HKD", "SmarTone 2022/23 Interim Report", SMARTONE_2023_H1_REPORT_URL, "2022/23中期现金流量表披露Net cash inflow from operating activities为1,245,012千港元。", "official_interim_cash_flow_check", SMARTONE_2023_H1_SOURCES),
                "capital_expenditures": (-344.459, "millions HKD", "SmarTone 2022/23 Interim Report", SMARTONE_2023_H1_REPORT_URL, "2022/23中期现金流量表披露Payment for purchase of fixed assets为344,459千港元，现金流出口径记为负数。", "official_interim_cash_flow_check", SMARTONE_2023_H1_SOURCES),
                "free_cash_flow": (900.553, "millions HKD", "SmarTone 2022/23 Interim Report", SMARTONE_2023_H1_REPORT_URL, "经营现金流1,245,012千港元减购买固定资产付款344,459千港元，复算普通自由现金流为900,553千港元。", "official_operating_cash_flow_minus_capex_reconciliation", SMARTONE_2023_H1_SOURCES),
                "cash_and_equivalents": (815.650, "millions HKD", "SmarTone 2022/23 Interim Report", SMARTONE_2023_H1_REPORT_URL, "2022/23中期资产负债表披露2022年12月31日Cash and cash equivalents为815,650千港元。", "official_interim_balance_sheet_check", SMARTONE_2023_H1_SOURCES),
                "total_assets": (12690.548, "millions HKD", "SmarTone 2022/23 Interim Report", SMARTONE_2023_H1_REPORT_URL, "2022/23中期资产负债表披露非流动资产8,834,998、流动资产3,855,550，合计总资产12,690,548千港元。", "official_interim_balance_sheet_reconciliation", SMARTONE_2023_H1_SOURCES),
                "total_debt": (2370.650, "millions HKD", "SmarTone 2022/23 Interim Report", SMARTONE_2023_H1_REPORT_URL, "2022/23中期资产负债表披露流动租赁负债603,916、非流动租赁负债271,576、流动银行及其他借款1,431,358、非流动银行借款63,800，合计债务2,370,650千港元；不含spectrum utilization fee liabilities。", "official_bank_borrowings_plus_lease_liabilities_reconciliation", SMARTONE_2023_H1_SOURCES),
                "revenue_growth_yoy": (0.461, "percent", "SmarTone 2022/23 Interim Report", SMARTONE_2023_H1_REPORT_URL, "2022/23中期损益表披露H1 2023 Revenues 3,809,011千港元、H1 2022比较数3,791,522千港元，复算同比增长约0.461%。", "official_current_prior_period_recalculation", SMARTONE_2023_H1_SOURCES),
            },
            "H2 2023": {
                "revenue": (2953.873, "millions HKD", "SmarTone 2022/23 Annual Report", SMARTONE_2023_H2_REPORT_URL, "2022/23年报披露全年Revenues 6,762,884千港元；减H1 3,809,011千港元，复算H2为2,953,873千港元。", "official_annual_minus_interim_reconciliation", SMARTONE_2023_H2_SOURCES),
                "gross_profit": (2027.932, "millions HKD", "SmarTone 2022/23 Annual Report", SMARTONE_2023_H2_REPORT_URL, "2022/23全年毛利按Revenues 6,762,884减Cost of inventories sold 2,199,365和Cost of services provided 392,289为4,171,230千港元；减H1 2,143,298后H2为2,027,932千港元。", "official_annual_minus_interim_gross_profit_reconciliation", SMARTONE_2023_H2_SOURCES),
                "ebitda": (1183.051, "millions HKD", "SmarTone 2022/23 Annual Report", SMARTONE_2023_H2_REPORT_URL, "2022/23年报分部附注披露全年EBITDA 2,462,116千港元；减H1 1,279,065后H2为1,183,051千港元。", "official_annual_minus_interim_ebitda_reconciliation", SMARTONE_2023_H2_SOURCES),
                "operating_income": (311.061, "millions HKD", "SmarTone 2022/23 Annual Report", SMARTONE_2023_H2_REPORT_URL, "2022/23年报披露全年Operating profit 702,434千港元；减H1 391,373后H2为311,061千港元。", "official_annual_minus_interim_reconciliation", SMARTONE_2023_H2_SOURCES),
                "operating_margin": (10.531, "percent", "SmarTone 2022/23 Annual Report", SMARTONE_2023_H2_REPORT_URL, "2023 H2 Operating profit 311,061除以H2 Revenues 2,953,873，复算经营利润率约10.531%。", "official_operating_income_margin_recalculation", SMARTONE_2023_H2_SOURCES),
                "net_income": (13.014, "millions HKD", "SmarTone 2022/23 Annual Report", SMARTONE_2023_H2_REPORT_URL, "2022/23年报披露全年Company's shareholders应占利润268,846千港元；减H1 255,832后H2为13,014千港元。", "official_annual_minus_interim_reconciliation", SMARTONE_2023_H2_SOURCES),
                "operating_cash_flow": (1009.350, "millions HKD", "SmarTone 2022/23 Annual Report", SMARTONE_2023_H2_REPORT_URL, "2022/23年报现金流量表披露全年经营现金流2,254,362千港元；减H1 1,245,012后H2为1,009,350千港元。", "official_annual_minus_interim_cash_flow_reconciliation", SMARTONE_2023_H2_SOURCES),
                "capital_expenditures": (-364.315, "millions HKD", "SmarTone 2022/23 Annual Report", SMARTONE_2023_H2_REPORT_URL, "2022/23年报现金流量表披露全年购买固定资产付款708,774千港元；减H1 344,459后H2为364,315千港元，现金流出口径记为负数。", "official_annual_minus_interim_cash_flow_reconciliation", SMARTONE_2023_H2_SOURCES),
                "free_cash_flow": (645.035, "millions HKD", "SmarTone 2022/23 Annual Report", SMARTONE_2023_H2_REPORT_URL, "H2经营现金流1,009,350千港元减购买固定资产付款364,315千港元，复算普通自由现金流为645,035千港元。", "official_operating_cash_flow_minus_capex_reconciliation", SMARTONE_2023_H2_SOURCES),
                "cash_and_equivalents": (1155.152, "millions HKD", "SmarTone 2022/23 Annual Report", SMARTONE_2023_H2_REPORT_URL, "2022/23年报资产负债表披露2023年6月30日Cash and cash equivalents为1,155,152千港元。", "official_annual_balance_sheet_check", SMARTONE_2023_H2_SOURCES),
                "total_assets": (10898.943, "millions HKD", "SmarTone 2022/23 Annual Report", SMARTONE_2023_H2_REPORT_URL, "2022/23年报资产负债表披露非流动资产8,496,421、流动资产2,402,522，合计总资产10,898,943千港元。", "official_annual_balance_sheet_reconciliation", SMARTONE_2023_H2_SOURCES),
                "total_debt": (852.994, "millions HKD", "SmarTone 2022/23 Annual Report", SMARTONE_2023_H2_REPORT_URL, "2022/23年报资产负债表披露流动租赁负债532,088、非流动租赁负债254,906、流动银行及其他借款2,200、非流动银行借款63,800，合计债务852,994千港元；不含spectrum utilization fee liabilities。", "official_bank_borrowings_plus_lease_liabilities_reconciliation", SMARTONE_2023_H2_SOURCES),
                "revenue_growth_yoy": (-6.693, "percent", "SmarTone 2022/23 Annual Report", SMARTONE_2023_H2_REPORT_URL, "H2 2023 Revenues 2,953,873千港元，对比H2 2022由FY2022 6,957,285减H1 2022 3,791,522得3,165,763千港元，复算同比下降约6.693%。", "official_current_prior_period_recalculation", SMARTONE_2023_H2_SOURCES),
            },
            "H1 2024": {
                "revenue": (3390.495, "millions HKD", "SmarTone 2023/24 Interim Report", SMARTONE_2024_H1_REPORT_URL, "2023/24中期损益表披露截至2023年12月31日六个月Revenues为3,390,495千港元。", "official_interim_statement_check", SMARTONE_2024_H1_SOURCES),
                "gross_profit": (2080.998, "millions HKD", "SmarTone 2023/24 Interim Report", SMARTONE_2024_H1_REPORT_URL, "2023/24中期损益表披露Revenues 3,390,495、Cost of inventories sold 1,069,686、Cost of services provided 239,811，复算毛利为2,080,998千港元。", "official_revenue_minus_costs_reconciliation", SMARTONE_2024_H1_SOURCES),
                "ebitda": (1241.179, "millions HKD", "SmarTone 2023/24 Interim Report", SMARTONE_2024_H1_REPORT_URL, "2023/24中期分部附注披露集团EBITDA为1,241,179千港元。", "official_interim_segment_ebitda_check", SMARTONE_2024_H1_SOURCES),
                "operating_income": (360.835, "millions HKD", "SmarTone 2023/24 Interim Report", SMARTONE_2024_H1_REPORT_URL, "2023/24中期损益表披露Operating profit为360,835千港元。", "official_interim_statement_check", SMARTONE_2024_H1_SOURCES),
                "operating_margin": (10.643, "percent", "SmarTone 2023/24 Interim Report", SMARTONE_2024_H1_REPORT_URL, "2024 H1 Operating profit 360,835除以Revenues 3,390,495，复算经营利润率约10.643%。", "official_operating_income_margin_recalculation", SMARTONE_2024_H1_SOURCES),
                "net_income": (245.792, "millions HKD", "SmarTone 2023/24 Interim Report", SMARTONE_2024_H1_REPORT_URL, "2023/24中期损益表披露Company's shareholders应占利润为245,792千港元。", "official_interim_statement_check", SMARTONE_2024_H1_SOURCES),
                "operating_cash_flow": (847.606, "millions HKD", "SmarTone 2023/24 Interim Report", SMARTONE_2024_H1_REPORT_URL, "2023/24中期现金流量表披露Net cash inflow from operating activities为847,606千港元。", "official_interim_cash_flow_check", SMARTONE_2024_H1_SOURCES),
                "capital_expenditures": (-315.988, "millions HKD", "SmarTone 2023/24 Interim Report", SMARTONE_2024_H1_REPORT_URL, "2023/24中期现金流量表披露Payment for purchase of fixed assets为315,988千港元，现金流出口径记为负数。", "official_interim_cash_flow_check", SMARTONE_2024_H1_SOURCES),
                "free_cash_flow": (531.618, "millions HKD", "SmarTone 2023/24 Interim Report", SMARTONE_2024_H1_REPORT_URL, "经营现金流847,606千港元减购买固定资产付款315,988千港元，复算普通自由现金流为531,618千港元。", "official_operating_cash_flow_minus_capex_reconciliation", SMARTONE_2024_H1_SOURCES),
                "cash_and_equivalents": (1047.761, "millions HKD", "SmarTone 2023/24 Interim Report", SMARTONE_2024_H1_REPORT_URL, "2023/24中期资产负债表披露2023年12月31日Cash and cash equivalents为1,047,761千港元。", "official_interim_balance_sheet_check", SMARTONE_2024_H1_SOURCES),
                "total_assets": (10721.690, "millions HKD", "SmarTone 2023/24 Interim Report", SMARTONE_2024_H1_REPORT_URL, "2023/24中期资产负债表披露非流动资产8,072,703、流动资产2,648,987，合计总资产10,721,690千港元。", "official_interim_balance_sheet_reconciliation", SMARTONE_2024_H1_SOURCES),
                "total_debt": (814.834, "millions HKD", "SmarTone 2023/24 Interim Report", SMARTONE_2024_H1_REPORT_URL, "2023/24中期资产负债表披露流动租赁负债487,882、非流动租赁负债263,152、流动银行借款2,200、非流动银行借款61,600，合计债务814,834千港元；不含spectrum utilization fee liabilities。", "official_bank_borrowings_plus_lease_liabilities_reconciliation", SMARTONE_2024_H1_SOURCES),
                "revenue_growth_yoy": (-10.988, "percent", "SmarTone 2023/24 Interim Report", SMARTONE_2024_H1_REPORT_URL, "2023/24中期损益表披露H1 2024 Revenues 3,390,495千港元、H1 2023比较数3,809,011千港元，复算同比下降约10.988%。", "official_current_prior_period_recalculation", SMARTONE_2024_H1_SOURCES),
            },
            "H2 2024": {
                "revenue": (2830.756, "millions HKD", "SmarTone 2023/24 Annual Report", SMARTONE_2024_H2_REPORT_URL, "2023/24年报披露全年Revenues 6,221,251千港元；减H1 3,390,495千港元，复算H2为2,830,756千港元。", "official_annual_minus_interim_reconciliation", SMARTONE_2024_H2_SOURCES),
                "gross_profit": (2037.990, "millions HKD", "SmarTone 2023/24 Annual Report", SMARTONE_2024_H2_REPORT_URL, "2023/24全年毛利按Revenues 6,221,251减Cost of inventories sold 1,691,876和Cost of services provided 410,387为4,118,988千港元；减H1 2,080,998后H2为2,037,990千港元。", "official_annual_minus_interim_gross_profit_reconciliation", SMARTONE_2024_H2_SOURCES),
                "ebitda": (1200.408, "millions HKD", "SmarTone 2023/24 Annual Report", SMARTONE_2024_H2_REPORT_URL, "2023/24全年EBITDA按Operating profit 700,602加Depreciation, amortization and loss on disposal 1,740,985复算为2,441,587千港元；减H1 EBITDA 1,241,179后H2为1,200,408千港元。", "official_annual_minus_interim_ebitda_reconciliation", SMARTONE_2024_H2_SOURCES),
                "operating_income": (339.767, "millions HKD", "SmarTone 2023/24 Annual Report", SMARTONE_2024_H2_REPORT_URL, "2023/24年报披露全年Operating profit 700,602千港元；减H1 360,835后H2为339,767千港元。", "official_annual_minus_interim_reconciliation", SMARTONE_2024_H2_SOURCES),
                "operating_margin": (12.003, "percent", "SmarTone 2023/24 Annual Report", SMARTONE_2024_H2_REPORT_URL, "2024 H2 Operating profit 339,767除以H2 Revenues 2,830,756，复算经营利润率约12.003%。", "official_operating_income_margin_recalculation", SMARTONE_2024_H2_SOURCES),
                "net_income": (224.334, "millions HKD", "SmarTone 2023/24 Annual Report", SMARTONE_2024_H2_REPORT_URL, "2023/24年报披露全年Company's shareholders应占利润470,126千港元；减H1 245,792后H2为224,334千港元。", "official_annual_minus_interim_reconciliation", SMARTONE_2024_H2_SOURCES),
                "operating_cash_flow": (1314.135, "millions HKD", "SmarTone 2023/24 Annual Report", SMARTONE_2024_H2_REPORT_URL, "2023/24年报现金流量表披露全年经营现金流2,161,741千港元；减H1 847,606后H2为1,314,135千港元。", "official_annual_minus_interim_cash_flow_reconciliation", SMARTONE_2024_H2_SOURCES),
                "capital_expenditures": (-285.557, "millions HKD", "SmarTone 2023/24 Annual Report", SMARTONE_2024_H2_REPORT_URL, "2023/24年报现金流量表披露全年购买固定资产付款601,545千港元；减H1 315,988后H2为285,557千港元，现金流出口径记为负数。", "official_annual_minus_interim_cash_flow_reconciliation", SMARTONE_2024_H2_SOURCES),
                "free_cash_flow": (1028.578, "millions HKD", "SmarTone 2023/24 Annual Report", SMARTONE_2024_H2_REPORT_URL, "H2经营现金流1,314,135千港元减购买固定资产付款285,557千港元，复算普通自由现金流为1,028,578千港元。", "official_operating_cash_flow_minus_capex_reconciliation", SMARTONE_2024_H2_SOURCES),
                "cash_and_equivalents": (1576.915, "millions HKD", "SmarTone 2023/24 Annual Report", SMARTONE_2024_H2_REPORT_URL, "2023/24年报资产负债表披露2024年6月30日Cash and cash equivalents为1,576,915千港元。", "official_annual_balance_sheet_check", SMARTONE_2024_H2_SOURCES),
                "total_assets": (11178.275, "millions HKD", "SmarTone 2023/24 Annual Report", SMARTONE_2024_H2_REPORT_URL, "2023/24年报资产负债表披露非流动资产8,152,969、流动资产3,025,306，合计总资产11,178,275千港元。", "official_annual_balance_sheet_reconciliation", SMARTONE_2024_H2_SOURCES),
                "total_debt": (963.176, "millions HKD", "SmarTone 2023/24 Annual Report", SMARTONE_2024_H2_REPORT_URL, "2023/24年报资产负债表披露流动租赁负债543,633、非流动租赁负债355,743、流动银行借款2,200、非流动银行借款61,600，合计债务963,176千港元；不含spectrum utilization fee liabilities。", "official_bank_borrowings_plus_lease_liabilities_reconciliation", SMARTONE_2024_H2_SOURCES),
                "revenue_growth_yoy": (-4.168, "percent", "SmarTone 2023/24 Annual Report", SMARTONE_2024_H2_REPORT_URL, "H2 2024 Revenues 2,830,756千港元，对比H2 2023 Revenues 2,953,873千港元，复算同比下降约4.168%。", "official_current_prior_period_recalculation", SMARTONE_2024_H2_SOURCES),
            },
        }.items()
        for metric_key, (official_value, unit, source_label, source_url, evidence, verification_method, sources) in period_values.items()
    ],
    {
        "subject": "SmarTone", "period": "H1 2025", "metric_key": "revenue",
        "official_value": 3491.538, "unit": "millions HKD",
        "source_label": "SmarTone 2024/25 Interim Results Announcement", "source_url": SMARTONE_2025_H1_RESULTS_URL,
        "evidence": "2024/25中期损益表披露Revenues为3,491,538千港元。",
        "verification_method": "official_interim_statement_check", "verification_sources": SMARTONE_2025_H1_SOURCES,
    },
    {
        "subject": "SmarTone", "period": "H1 2025", "metric_key": "operating_income",
        "official_value": 419.512, "unit": "millions HKD",
        "source_label": "SmarTone 2024/25 Interim Results Announcement", "source_url": SMARTONE_2025_H1_RESULTS_URL,
        "evidence": "2024/25中期损益表披露Operating profit为419,512千港元。",
        "verification_method": "official_interim_statement_check", "verification_sources": SMARTONE_2025_H1_SOURCES,
    },
    {
        "subject": "SmarTone", "period": "H1 2025", "metric_key": "net_income",
        "official_value": 256.658, "unit": "millions HKD",
        "source_label": "SmarTone 2024/25 Interim Results Announcement", "source_url": SMARTONE_2025_H1_RESULTS_URL,
        "evidence": "2024/25中期损益表披露Profit attributable to equity holders为256,658千港元。",
        "verification_method": "official_interim_statement_check", "verification_sources": SMARTONE_2025_H1_SOURCES,
    },
    {
        "subject": "SmarTone", "period": "H1 2025", "metric_key": "operating_cash_flow",
        "official_value": 967.961, "unit": "millions HKD",
        "source_label": "SmarTone 2025/26 Interim Results Announcement", "source_url": SMARTONE_2026_H1_RESULTS_URL,
        "evidence": "2025/26中期现金流量表比较数披露2024/25 H1 Net cash inflow from operating activities为967,961千港元。",
        "verification_method": "official_interim_cash_flow_comparative_check", "verification_sources": [SMARTONE_2025_H1_SOURCES[0], SMARTONE_2026_H1_SOURCES[0], SMARTONE_2026_H1_SOURCES[2]],
    },
    {
        "subject": "SmarTone", "period": "H1 2025", "metric_key": "capital_expenditures",
        "official_value": -333.014, "unit": "millions HKD",
        "source_label": "SmarTone 2025/26 Interim Results Announcement", "source_url": SMARTONE_2026_H1_RESULTS_URL,
        "evidence": "2025/26中期现金流量表比较数披露2024/25 H1 Payment for purchase of fixed assets为333,014千港元，现金流出口径记为负数。",
        "verification_method": "official_interim_cash_flow_comparative_check", "verification_sources": [SMARTONE_2025_H1_SOURCES[0], SMARTONE_2026_H1_SOURCES[0], SMARTONE_2026_H1_SOURCES[2]],
    },
    {
        "subject": "SmarTone", "period": "H1 2025", "metric_key": "free_cash_flow",
        "official_value": 634.947, "unit": "millions HKD",
        "source_label": "SmarTone 2025/26 Interim Results Announcement", "source_url": SMARTONE_2026_H1_RESULTS_URL,
        "evidence": "2025/26中期现金流量表比较数披露2024/25 H1经营现金流967,961千港元、购买固定资产付款333,014千港元；复算自由现金流为634,947千港元。",
        "verification_method": "official_operating_cash_flow_minus_capex_reconciliation", "verification_sources": [SMARTONE_2025_H1_SOURCES[0], SMARTONE_2026_H1_SOURCES[0], SMARTONE_2026_H1_SOURCES[2]],
    },
    {
        "subject": "SmarTone", "period": "H1 2025", "metric_key": "cash_and_equivalents",
        "official_value": 1649.667, "unit": "millions HKD",
        "source_label": "SmarTone 2024/25 Interim Results Announcement", "source_url": SMARTONE_2025_H1_RESULTS_URL,
        "evidence": "2024/25中期资产负债表披露2024年12月31日Cash and cash equivalents为1,649,667千港元。",
        "verification_method": "official_interim_balance_sheet_check", "verification_sources": SMARTONE_2025_H1_SOURCES,
    },
    {
        "subject": "SmarTone", "period": "H1 2025", "metric_key": "total_assets",
        "official_value": 10940.766, "unit": "millions HKD",
        "source_label": "SmarTone 2024/25 Interim Results Announcement", "source_url": SMARTONE_2025_H1_RESULTS_URL,
        "evidence": "2024/25中期资产负债表披露非流动资产7,767,682、流动资产3,173,084，合计总资产10,940,766千港元。",
        "verification_method": "official_interim_balance_sheet_reconciliation", "verification_sources": SMARTONE_2025_H1_SOURCES,
    },
    {
        "subject": "SmarTone", "period": "H2 2025", "metric_key": "revenue",
        "official_value": 2761.909, "unit": "millions HKD",
        "source_label": "SmarTone 2024/25 Annual Report", "source_url": SMARTONE_2025_H2_REPORT_URL,
        "evidence": "2024/25年报披露全年Revenues 6,253,447千港元；减H1 3,491,538千港元，复算H2为2,761,909千港元。",
        "verification_method": "official_annual_minus_interim_reconciliation", "verification_sources": SMARTONE_2025_H2_SOURCES,
    },
    {
        "subject": "SmarTone", "period": "H2 2025", "metric_key": "operating_income",
        "official_value": 332.697, "unit": "millions HKD",
        "source_label": "SmarTone 2024/25 Annual Report", "source_url": SMARTONE_2025_H2_REPORT_URL,
        "evidence": "2024/25年报披露全年Operating profit 752,209千港元；减H1 419,512千港元，复算H2为332,697千港元。",
        "verification_method": "official_annual_minus_interim_reconciliation", "verification_sources": SMARTONE_2025_H2_SOURCES,
    },
    {
        "subject": "SmarTone", "period": "H2 2025", "metric_key": "net_income",
        "official_value": 222.243, "unit": "millions HKD",
        "source_label": "SmarTone 2024/25 Annual Report", "source_url": SMARTONE_2025_H2_REPORT_URL,
        "evidence": "2024/25年报披露全年Profit attributable to equity holders 478,901千港元；减H1 256,658千港元，复算H2为222,243千港元。",
        "verification_method": "official_annual_minus_interim_reconciliation", "verification_sources": SMARTONE_2025_H2_SOURCES,
    },
    {
        "subject": "SmarTone", "period": "H2 2025", "metric_key": "operating_cash_flow",
        "official_value": 1165.031, "unit": "millions HKD",
        "source_label": "SmarTone 2024/25 Annual Report", "source_url": SMARTONE_2025_H2_REPORT_URL,
        "evidence": "2024/25年报现金流量表披露全年经营现金流2,132,992千港元；减H1 967,961千港元，复算H2为1,165,031千港元。",
        "verification_method": "official_annual_minus_interim_cash_flow_reconciliation", "verification_sources": SMARTONE_2025_H2_SOURCES,
    },
    {
        "subject": "SmarTone", "period": "H2 2025", "metric_key": "capital_expenditures",
        "official_value": -264.457, "unit": "millions HKD",
        "source_label": "SmarTone 2024/25 Annual Report", "source_url": SMARTONE_2025_H2_REPORT_URL,
        "evidence": "2024/25年报现金流量表披露全年Payment for purchase of fixed assets为597,471千港元；减H1 333,014千港元，复算H2为264,457千港元，现金流出口径记为负数。",
        "verification_method": "official_annual_minus_interim_cash_flow_reconciliation", "verification_sources": SMARTONE_2025_H2_SOURCES,
    },
    {
        "subject": "SmarTone", "period": "H2 2025", "metric_key": "free_cash_flow",
        "official_value": 900.574, "unit": "millions HKD",
        "source_label": "SmarTone 2024/25 Annual Report", "source_url": SMARTONE_2025_H2_REPORT_URL,
        "evidence": "2024/25年报现金流量表复算H2经营现金流1,165,031千港元、购买固定资产付款264,457千港元；H2自由现金流为900,574千港元。",
        "verification_method": "official_operating_cash_flow_minus_capex_reconciliation", "verification_sources": SMARTONE_2025_H2_SOURCES,
    },
    {
        "subject": "SmarTone", "period": "H2 2025", "metric_key": "cash_and_equivalents",
        "official_value": 2028.081, "unit": "millions HKD",
        "source_label": "SmarTone 2024/25 Annual Report", "source_url": SMARTONE_2025_H2_REPORT_URL,
        "evidence": "2024/25年报资产负债表披露2025年6月30日Cash and cash equivalents为2,028,081千港元。",
        "verification_method": "official_annual_balance_sheet_check", "verification_sources": SMARTONE_2025_H2_SOURCES,
    },
    {
        "subject": "SmarTone", "period": "H2 2025", "metric_key": "total_assets",
        "official_value": 11307.528, "unit": "millions HKD",
        "source_label": "SmarTone 2024/25 Annual Report", "source_url": SMARTONE_2025_H2_REPORT_URL,
        "evidence": "2024/25年报资产负债表披露非流动资产7,860,433、流动资产3,447,095，合计总资产11,307,528千港元。",
        "verification_method": "official_annual_balance_sheet_reconciliation", "verification_sources": SMARTONE_2025_H2_SOURCES,
    },
    {
        "subject": "SmarTone", "period": "H1 2026", "metric_key": "revenue",
        "official_value": 3561.288, "unit": "millions HKD",
        "source_label": "SmarTone 2025/26 Interim Results Announcement", "source_url": SMARTONE_2026_H1_RESULTS_URL,
        "evidence": "2025/26中期损益表披露Revenues为3,561,288千港元。",
        "verification_method": "official_interim_statement_check", "verification_sources": SMARTONE_2026_H1_SOURCES,
    },
    {
        "subject": "SmarTone", "period": "H1 2026", "metric_key": "operating_income",
        "official_value": 391.598, "unit": "millions HKD",
        "source_label": "SmarTone 2025/26 Interim Results Announcement", "source_url": SMARTONE_2026_H1_RESULTS_URL,
        "evidence": "2025/26中期损益表披露Operating profit为391,598千港元。",
        "verification_method": "official_interim_statement_check", "verification_sources": SMARTONE_2026_H1_SOURCES,
    },
    {
        "subject": "SmarTone", "period": "H1 2026", "metric_key": "net_income",
        "official_value": 278.325, "unit": "millions HKD",
        "source_label": "SmarTone 2025/26 Interim Results Announcement", "source_url": SMARTONE_2026_H1_RESULTS_URL,
        "evidence": "2025/26中期损益表披露Profit attributable to equity holders为278,325千港元。",
        "verification_method": "official_interim_statement_check", "verification_sources": SMARTONE_2026_H1_SOURCES,
    },
    {
        "subject": "SmarTone", "period": "H1 2026", "metric_key": "operating_cash_flow",
        "official_value": 1349.586, "unit": "millions HKD",
        "source_label": "SmarTone 2025/26 Interim Results Announcement", "source_url": SMARTONE_2026_H1_RESULTS_URL,
        "evidence": "2025/26中期现金流量表披露Net cash inflow from operating activities为1,349,586千港元。",
        "verification_method": "official_interim_cash_flow_check", "verification_sources": SMARTONE_2026_H1_SOURCES,
    },
    {
        "subject": "SmarTone", "period": "H1 2026", "metric_key": "capital_expenditures",
        "official_value": -330.559, "unit": "millions HKD",
        "source_label": "SmarTone 2025/26 Interim Results Announcement", "source_url": SMARTONE_2026_H1_RESULTS_URL,
        "evidence": "2025/26中期现金流量表披露Payment for purchase of fixed assets为330,559千港元，现金流出口径记为负数。",
        "verification_method": "official_interim_cash_flow_check", "verification_sources": SMARTONE_2026_H1_SOURCES,
    },
    {
        "subject": "SmarTone", "period": "H1 2026", "metric_key": "free_cash_flow",
        "official_value": 1019.027, "unit": "millions HKD",
        "source_label": "SmarTone 2025/26 Interim Results Announcement", "source_url": SMARTONE_2026_H1_RESULTS_URL,
        "evidence": "2025/26中期现金流量表披露经营现金流1,349,586千港元、购买固定资产付款330,559千港元；复算自由现金流为1,019,027千港元。",
        "verification_method": "official_operating_cash_flow_minus_capex_reconciliation", "verification_sources": SMARTONE_2026_H1_SOURCES,
    },
    {
        "subject": "SmarTone", "period": "H1 2026", "metric_key": "cash_and_equivalents",
        "official_value": 2435.049, "unit": "millions HKD",
        "source_label": "SmarTone 2025/26 Interim Results Announcement", "source_url": SMARTONE_2026_H1_RESULTS_URL,
        "evidence": "2025/26中期资产负债表披露2025年12月31日Cash and cash equivalents为2,435,049千港元。",
        "verification_method": "official_interim_balance_sheet_check", "verification_sources": SMARTONE_2026_H1_SOURCES,
    },
    {
        "subject": "SmarTone", "period": "H1 2026", "metric_key": "total_assets",
        "official_value": 11350.426, "unit": "millions HKD",
        "source_label": "SmarTone 2025/26 Interim Results Announcement", "source_url": SMARTONE_2026_H1_RESULTS_URL,
        "evidence": "2025/26中期资产负债表披露非流动资产7,477,581、流动资产3,872,845，合计总资产11,350,426千港元。",
        "verification_method": "official_interim_balance_sheet_reconciliation", "verification_sources": SMARTONE_2026_H1_SOURCES,
    },
    {
        "subject": "SmarTone", "period": "H1 2025", "metric_key": "gross_profit",
        "official_value": 2102.365, "unit": "millions HKD",
        "source_label": "SmarTone 2024/25 Interim Report", "source_url": SMARTONE_2025_H1_REPORT_URL,
        "evidence": "2024/25中期损益表披露Revenues 3,491,538、Cost of inventories sold 1,162,159、Cost of services provided 227,014，复算毛利为2,102,365千港元。",
        "verification_method": "official_revenue_minus_costs_reconciliation", "verification_sources": SMARTONE_2025_H1_SOURCES,
    },
    {
        "subject": "SmarTone", "period": "H1 2025", "metric_key": "ebitda",
        "official_value": 1278.786, "unit": "millions HKD",
        "source_label": "SmarTone 2024/25 Interim Report", "source_url": SMARTONE_2025_H1_REPORT_URL,
        "evidence": "2024/25 H1 EBITDA按Operating profit 419,512加Depreciation, amortization and loss on disposal 859,274复算为1,278,786千港元。",
        "verification_method": "official_operating_profit_plus_depreciation_reconciliation", "verification_sources": SMARTONE_2025_H1_SOURCES,
    },
    {
        "subject": "SmarTone", "period": "H1 2025", "metric_key": "total_debt",
        "official_value": 885.002, "unit": "millions HKD",
        "source_label": "SmarTone 2024/25 Interim Report", "source_url": SMARTONE_2025_H1_REPORT_URL,
        "evidence": "2024/25中期资产负债表披露流动租赁负债509,213、非流动租赁负债314,189、流动银行借款2,824、非流动银行借款58,776，合计债务885,002千港元；不含spectrum utilization fee liabilities。",
        "verification_method": "official_bank_borrowings_plus_lease_liabilities_reconciliation", "verification_sources": SMARTONE_2025_H1_SOURCES,
    },
    {
        "subject": "SmarTone", "period": "H1 2025", "metric_key": "revenue_growth_yoy",
        "official_value": 2.980, "unit": "percent",
        "source_label": "SmarTone 2024/25 Interim Report", "source_url": SMARTONE_2025_H1_REPORT_URL,
        "evidence": "2024/25中期损益表披露H1 2025 Revenues 3,491,538千港元、H1 2024比较数3,390,495千港元，复算同比增长约2.980%。",
        "verification_method": "official_current_prior_period_recalculation", "verification_sources": SMARTONE_2025_H1_SOURCES,
    },
    {
        "subject": "SmarTone", "period": "H2 2025", "metric_key": "gross_profit",
        "official_value": 1954.236, "unit": "millions HKD",
        "source_label": "SmarTone 2024/25 Annual Report", "source_url": SMARTONE_2025_H2_REPORT_URL,
        "evidence": "2024/25全年毛利按Revenues 6,253,447减Cost of inventories sold 1,801,501和Cost of services provided 395,345为4,056,601千港元；减H1 2,102,365后H2为1,954,236千港元。",
        "verification_method": "official_annual_minus_interim_gross_profit_reconciliation", "verification_sources": SMARTONE_2025_H2_SOURCES,
    },
    {
        "subject": "SmarTone", "period": "H2 2025", "metric_key": "ebitda",
        "official_value": 1166.274, "unit": "millions HKD",
        "source_label": "SmarTone 2024/25 Annual Report", "source_url": SMARTONE_2025_H2_REPORT_URL,
        "evidence": "2024/25全年EBITDA按Operating profit 752,209加Depreciation, amortization and loss on disposal 1,692,851复算为2,445,060千港元；减H1 1,278,786后H2为1,166,274千港元。",
        "verification_method": "official_annual_minus_interim_ebitda_reconciliation", "verification_sources": SMARTONE_2025_H2_SOURCES,
    },
    {
        "subject": "SmarTone", "period": "H2 2025", "metric_key": "total_debt",
        "official_value": 877.588, "unit": "millions HKD",
        "source_label": "SmarTone 2024/25 Annual Report", "source_url": SMARTONE_2025_H2_REPORT_URL,
        "evidence": "2024/25年报资产负债表披露流动租赁负债485,400、非流动租赁负债330,588、流动银行借款4,718、非流动银行借款56,882，合计债务877,588千港元；不含spectrum utilization fee liabilities。",
        "verification_method": "official_bank_borrowings_plus_lease_liabilities_reconciliation", "verification_sources": SMARTONE_2025_H2_SOURCES,
    },
    {
        "subject": "SmarTone", "period": "H2 2025", "metric_key": "revenue_growth_yoy",
        "official_value": -2.432, "unit": "percent",
        "source_label": "SmarTone 2024/25 Annual Report", "source_url": SMARTONE_2025_H2_REPORT_URL,
        "evidence": "H2 2025 Revenues按FY2025 6,253,447减H1 3,491,538得2,761,909千港元；H2 2024按FY2024 6,221,251减H1 3,390,495得2,830,756千港元，复算同比下降约2.432%。",
        "verification_method": "official_current_prior_period_recalculation", "verification_sources": SMARTONE_2025_H2_SOURCES,
    },
    {
        "subject": "SmarTone", "period": "H1 2026", "metric_key": "gross_profit",
        "official_value": 1991.269, "unit": "millions HKD",
        "source_label": "SmarTone 2025/26 Interim Report", "source_url": SMARTONE_2026_H1_REPORT_URL,
        "evidence": "2025/26中期损益表披露Revenues 3,561,288、Cost of inventories sold 1,331,371、Cost of services provided 238,648，复算毛利为1,991,269千港元。",
        "verification_method": "official_revenue_minus_costs_reconciliation", "verification_sources": SMARTONE_2026_H1_SOURCES,
    },
    {
        "subject": "SmarTone", "period": "H1 2026", "metric_key": "ebitda",
        "official_value": 1219.600, "unit": "millions HKD",
        "source_label": "SmarTone 2025/26 Interim Report", "source_url": SMARTONE_2026_H1_REPORT_URL,
        "evidence": "2025/26 H1 EBITDA按Operating profit 391,598加Depreciation, amortization and loss on disposal 828,002复算为1,219,600千港元。",
        "verification_method": "official_operating_profit_plus_depreciation_reconciliation", "verification_sources": SMARTONE_2026_H1_SOURCES,
    },
    {
        "subject": "SmarTone", "period": "H1 2026", "metric_key": "total_debt",
        "official_value": 797.351, "unit": "millions HKD",
        "source_label": "SmarTone 2025/26 Interim Report", "source_url": SMARTONE_2026_H1_REPORT_URL,
        "evidence": "2025/26中期资产负债表披露流动租赁负债466,750、非流动租赁负债271,834、流动银行借款3,957、非流动银行借款54,810，合计债务797,351千港元；不含spectrum utilization fee liabilities。",
        "verification_method": "official_bank_borrowings_plus_lease_liabilities_reconciliation", "verification_sources": SMARTONE_2026_H1_SOURCES,
    },
    {
        "subject": "SmarTone", "period": "H1 2026", "metric_key": "revenue_growth_yoy",
        "official_value": 1.998, "unit": "percent",
        "source_label": "SmarTone 2025/26 Interim Report", "source_url": SMARTONE_2026_H1_REPORT_URL,
        "evidence": "2025/26中期损益表披露H1 2026 Revenues 3,561,288千港元、H1 2025比较数3,491,538千港元，复算同比增长约1.998%。",
        "verification_method": "official_current_prior_period_recalculation", "verification_sources": SMARTONE_2026_H1_SOURCES,
    },
    *HKBN_OFFICIAL_VERIFICATIONS,
    *ICABLE_OFFICIAL_VERIFICATIONS,
    {
        "subject": "中国铁塔",
        "period": "Q1 2025",
        "metric_key": "revenue",
        "official_value": 24771,
        "unit": "millions CNY",
        "source_label": "中国铁塔2025年第一季度未经审核的主要运营数据",
        "source_url": "https://doc.irasia.com/listco/hk/chinatower/interim/2025/int1q.pdf",
        "evidence": "表格列示营业收入 24,771 百万元。",
    },
    {
        "subject": "中国铁塔",
        "period": "Q1 2025",
        "metric_key": "revenue_growth_yoy",
        "official_value": 3.3,
        "unit": "percent",
        "source_label": "中国铁塔2025年第一季度未经审核的主要运营数据",
        "source_url": "https://doc.irasia.com/listco/hk/chinatower/interim/2025/int1q.pdf",
        "evidence": "2025年第一季度营业收入为人民币247.71亿元，同比增长3.3%。",
    },
    {
        "subject": "中国铁塔",
        "period": "Q1 2025",
        "metric_key": "operator_business_revenue",
        "official_value": 21224,
        "unit": "millions CNY",
        "source_label": "中国铁塔2025年第一季度未经审核的主要运营数据",
        "source_url": "https://doc.irasia.com/listco/hk/chinatower/interim/2025/int1q.pdf",
        "evidence": "表格列示运营商业务收入 21,224 百万元。",
    },
    {
        "subject": "中国铁塔",
        "period": "Q1 2025",
        "metric_key": "tower_business_revenue",
        "official_value": 18877,
        "unit": "millions CNY",
        "source_label": "中国铁塔2025年第一季度未经审核的主要运营数据",
        "source_url": "https://doc.irasia.com/listco/hk/chinatower/interim/2025/int1q.pdf",
        "evidence": "表格列示塔类业务收入 18,877 百万元。",
    },
    {
        "subject": "中国铁塔",
        "period": "Q1 2025",
        "metric_key": "das_business_revenue",
        "official_value": 2347,
        "unit": "millions CNY",
        "source_label": "中国铁塔2025年第一季度未经审核的主要运营数据",
        "source_url": "https://doc.irasia.com/listco/hk/chinatower/interim/2025/int1q.pdf",
        "evidence": "表格列示室分业务收入 2,347 百万元。",
    },
    {
        "subject": "中国铁塔",
        "period": "Q1 2025",
        "metric_key": "smart_business_revenue",
        "official_value": 2312,
        "unit": "millions CNY",
        "source_label": "中国铁塔2025年第一季度未经审核的主要运营数据",
        "source_url": "https://doc.irasia.com/listco/hk/chinatower/interim/2025/int1q.pdf",
        "evidence": "表格列示智联业务收入 2,312 百万元。",
    },
    {
        "subject": "中国铁塔",
        "period": "Q1 2025",
        "metric_key": "energy_business_revenue",
        "official_value": 1145,
        "unit": "millions CNY",
        "source_label": "中国铁塔2025年第一季度未经审核的主要运营数据",
        "source_url": "https://doc.irasia.com/listco/hk/chinatower/interim/2025/int1q.pdf",
        "evidence": "表格列示能源业务收入 1,145 百万元。",
    },
    {
        "subject": "中国铁塔",
        "period": "Q1 2025",
        "metric_key": "ebitda",
        "official_value": 17295,
        "unit": "millions CNY",
        "source_label": "中国铁塔2025年第一季度未经审核的主要运营数据",
        "source_url": "https://doc.irasia.com/listco/hk/chinatower/interim/2025/int1q.pdf",
        "evidence": "表格列示 EBITDA 17,295 百万元。",
    },
    {
        "subject": "中国铁塔",
        "period": "Q1 2025",
        "metric_key": "ebitda_margin",
        "official_value": 69.8,
        "unit": "percent",
        "source_label": "中国铁塔2025年第一季度未经审核的主要运营数据",
        "source_url": "https://doc.irasia.com/listco/hk/chinatower/interim/2025/int1q.pdf",
        "evidence": "公告正文披露 EBITDA率为69.8%。",
    },
    {
        "subject": "中国铁塔",
        "period": "Q1 2025",
        "metric_key": "net_income",
        "official_value": 3024,
        "unit": "millions CNY",
        "source_label": "中国铁塔2025年第一季度未经审核的主要运营数据",
        "source_url": "https://doc.irasia.com/listco/hk/chinatower/interim/2025/int1q.pdf",
        "evidence": "表格列示归属于本公司股东的利润 3,024 百万元。",
    },
    {
        "subject": "中国铁塔",
        "period": "Q1 2025",
        "metric_key": "total_assets",
        "official_value": 329540,
        "unit": "millions CNY",
        "source_label": "中国铁塔2025年第一季度未经审核的主要运营数据",
        "source_url": "https://doc.irasia.com/listco/hk/chinatower/interim/2025/int1q.pdf",
        "evidence": "表格列示截至2025年3月31日总资产 329,540 百万元。",
    },
    {
        "subject": "中国铁塔", "period": "Q2 2025", "metric_key": "revenue",
        "official_value": 24830, "unit": "millions CNY",
        "source_label": "中国铁塔2025中期业绩公告", "source_url": TOWER_2025_H1_URL,
        "evidence": "上半年Operating revenue 49,601减Q1 24,771，复算Q2为24,830百万元。",
        "verification_method": "official_h1_minus_q1_reconciliation", "verification_sources": TOWER_2025_Q2_SOURCES,
    },
    {
        "subject": "中国铁塔", "period": "Q2 2025", "metric_key": "operator_business_revenue",
        "official_value": 21237, "unit": "millions CNY",
        "source_label": "中国铁塔2025中期业绩公告", "source_url": TOWER_2025_H1_URL,
        "evidence": "上半年TSP/运营商业务收入42,461减Q1 21,224，复算Q2为21,237百万元。",
        "verification_method": "official_h1_minus_q1_reconciliation", "verification_sources": TOWER_2025_Q2_SOURCES,
    },
    {
        "subject": "中国铁塔", "period": "Q2 2025", "metric_key": "tower_business_revenue",
        "official_value": 18920, "unit": "millions CNY",
        "source_label": "中国铁塔2025中期业绩公告", "source_url": TOWER_2025_H1_URL,
        "evidence": "上半年塔类业务收入37,797减Q1 18,877，复算Q2为18,920百万元。",
        "verification_method": "official_h1_minus_q1_reconciliation", "verification_sources": TOWER_2025_Q2_SOURCES,
    },
    {
        "subject": "中国铁塔", "period": "Q2 2025", "metric_key": "das_business_revenue",
        "official_value": 2317, "unit": "millions CNY",
        "source_label": "中国铁塔2025中期业绩公告", "source_url": TOWER_2025_H1_URL,
        "evidence": "上半年室分业务收入4,664减Q1 2,347，复算Q2为2,317百万元。",
        "verification_method": "official_h1_minus_q1_reconciliation", "verification_sources": TOWER_2025_Q2_SOURCES,
    },
    {
        "subject": "中国铁塔", "period": "Q2 2025", "metric_key": "smart_business_revenue",
        "official_value": 2414, "unit": "millions CNY",
        "source_label": "中国铁塔2025中期业绩公告", "source_url": TOWER_2025_H1_URL,
        "evidence": "上半年智联业务收入4,726减Q1 2,312，复算Q2为2,414百万元。",
        "verification_method": "official_h1_minus_q1_reconciliation", "verification_sources": TOWER_2025_Q2_SOURCES,
    },
    {
        "subject": "中国铁塔", "period": "Q2 2025", "metric_key": "energy_business_revenue",
        "official_value": 1064, "unit": "millions CNY",
        "source_label": "中国铁塔2025中期业绩公告", "source_url": TOWER_2025_H1_URL,
        "evidence": "上半年能源业务收入2,209减Q1 1,145，复算Q2为1,064百万元。",
        "verification_method": "official_h1_minus_q1_reconciliation", "verification_sources": TOWER_2025_Q2_SOURCES,
    },
    {
        "subject": "中国铁塔", "period": "Q2 2025", "metric_key": "ebitda",
        "official_value": 16932, "unit": "millions CNY",
        "source_label": "中国铁塔2025中期业绩公告", "source_url": TOWER_2025_H1_URL,
        "evidence": "上半年EBITDA 34,227减Q1 17,295，复算Q2为16,932百万元。",
        "verification_method": "official_h1_minus_q1_reconciliation", "verification_sources": TOWER_2025_Q2_SOURCES,
    },
    {
        "subject": "中国铁塔", "period": "Q2 2025", "metric_key": "net_income",
        "official_value": 2733, "unit": "millions CNY",
        "source_label": "中国铁塔2025中期业绩公告", "source_url": TOWER_2025_H1_URL,
        "evidence": "上半年归属于公司股东利润5,757减Q1 3,024，复算Q2为2,733百万元。",
        "verification_method": "official_h1_minus_q1_reconciliation", "verification_sources": TOWER_2025_Q2_SOURCES,
    },
    {
        "subject": "中国铁塔", "period": "Q2 2025", "metric_key": "total_assets",
        "official_value": 331127, "unit": "millions CNY",
        "source_label": "中国铁塔2025中期业绩公告", "source_url": TOWER_2025_H1_URL,
        "evidence": "截至2025年6月30日Total assets 331,127百万元。",
        "verification_method": "official_balance_sheet_row_check", "verification_sources": TOWER_2025_Q2_SOURCES[1:],
    },
    {
        "subject": "中国铁塔", "period": "Q3 2025", "metric_key": "revenue",
        "official_value": 24718, "unit": "millions CNY",
        "source_label": "中国铁塔2025年前三季度未经审核主要运营数据", "source_url": TOWER_2025_Q3_URL,
        "evidence": "前三季度营业收入74,319减上半年49,601，复算Q3为24,718百万元。",
        "verification_method": "official_9m_minus_h1_reconciliation", "verification_sources": TOWER_2025_Q3_SOURCES,
    },
    {
        "subject": "中国铁塔", "period": "Q3 2025", "metric_key": "operator_business_revenue",
        "official_value": 20971, "unit": "millions CNY",
        "source_label": "中国铁塔2025年前三季度未经审核主要运营数据", "source_url": TOWER_2025_Q3_URL,
        "evidence": "前三季度运营商业务收入63,432减上半年42,461，复算Q3为20,971百万元。",
        "verification_method": "official_9m_minus_h1_reconciliation", "verification_sources": TOWER_2025_Q3_SOURCES,
    },
    {
        "subject": "中国铁塔", "period": "Q3 2025", "metric_key": "tower_business_revenue",
        "official_value": 18712, "unit": "millions CNY",
        "source_label": "中国铁塔2025年前三季度未经审核主要运营数据", "source_url": TOWER_2025_Q3_URL,
        "evidence": "前三季度塔类业务收入56,509减上半年37,797，复算Q3为18,712百万元。",
        "verification_method": "official_9m_minus_h1_reconciliation", "verification_sources": TOWER_2025_Q3_SOURCES,
    },
    {
        "subject": "中国铁塔", "period": "Q3 2025", "metric_key": "das_business_revenue",
        "official_value": 2259, "unit": "millions CNY",
        "source_label": "中国铁塔2025年前三季度未经审核主要运营数据", "source_url": TOWER_2025_Q3_URL,
        "evidence": "前三季度室分业务收入6,923减上半年4,664，复算Q3为2,259百万元。",
        "verification_method": "official_9m_minus_h1_reconciliation", "verification_sources": TOWER_2025_Q3_SOURCES,
    },
    {
        "subject": "中国铁塔", "period": "Q3 2025", "metric_key": "smart_business_revenue",
        "official_value": 2367, "unit": "millions CNY",
        "source_label": "中国铁塔2025年前三季度未经审核主要运营数据", "source_url": TOWER_2025_Q3_URL,
        "evidence": "前三季度智联业务收入7,093减上半年4,726，复算Q3为2,367百万元。",
        "verification_method": "official_9m_minus_h1_reconciliation", "verification_sources": TOWER_2025_Q3_SOURCES,
    },
    {
        "subject": "中国铁塔", "period": "Q3 2025", "metric_key": "energy_business_revenue",
        "official_value": 1215, "unit": "millions CNY",
        "source_label": "中国铁塔2025年前三季度未经审核主要运营数据", "source_url": TOWER_2025_Q3_URL,
        "evidence": "前三季度能源业务收入3,424减上半年2,209，复算Q3为1,215百万元。",
        "verification_method": "official_9m_minus_h1_reconciliation", "verification_sources": TOWER_2025_Q3_SOURCES,
    },
    {
        "subject": "中国铁塔", "period": "Q3 2025", "metric_key": "ebitda",
        "official_value": 16732, "unit": "millions CNY",
        "source_label": "中国铁塔2025年前三季度未经审核主要运营数据", "source_url": TOWER_2025_Q3_URL,
        "evidence": "前三季度EBITDA 50,959减上半年34,227，复算Q3为16,732百万元。",
        "verification_method": "official_9m_minus_h1_reconciliation", "verification_sources": TOWER_2025_Q3_SOURCES,
    },
    {
        "subject": "中国铁塔", "period": "Q3 2025", "metric_key": "net_income",
        "official_value": 2951, "unit": "millions CNY",
        "source_label": "中国铁塔2025年前三季度未经审核主要运营数据", "source_url": TOWER_2025_Q3_URL,
        "evidence": "前三季度归属于公司股东利润8,708减上半年5,757，复算Q3为2,951百万元。",
        "verification_method": "official_9m_minus_h1_reconciliation", "verification_sources": TOWER_2025_Q3_SOURCES,
    },
    {
        "subject": "中国铁塔", "period": "Q3 2025", "metric_key": "total_assets",
        "official_value": 336340, "unit": "millions CNY",
        "source_label": "中国铁塔2025年前三季度未经审核主要运营数据", "source_url": TOWER_2025_Q3_URL,
        "evidence": "截至2025年9月30日总资产336,340百万元。",
        "verification_method": "official_balance_sheet_row_check", "verification_sources": TOWER_2025_Q3_SOURCES[1:],
    },
    {
        "subject": "中国铁塔", "period": "Q4 2025", "metric_key": "revenue",
        "official_value": 26092, "unit": "millions CNY",
        "source_label": "中国铁塔2025年度业绩演示", "source_url": TOWER_2025_ANNUAL_PRESENTATION_URL,
        "evidence": "全年Operating Revenue约100.4 billion/100,411百万元，减前三季度74,319百万元，复算Q4为26,092百万元。",
        "verification_method": "official_annual_minus_9m_reconciliation", "verification_sources": TOWER_2025_Q4_SOURCES,
    },
    {
        "subject": "中国铁塔", "period": "Q4 2025", "metric_key": "ebitda",
        "official_value": 14855, "unit": "millions CNY",
        "source_label": "中国铁塔2025年度业绩演示", "source_url": TOWER_2025_ANNUAL_PRESENTATION_URL,
        "evidence": "全年EBITDA 65,814百万元，减前三季度EBITDA 50,959百万元，复算Q4为14,855百万元。",
        "verification_method": "official_annual_minus_9m_reconciliation", "verification_sources": TOWER_2025_Q4_SOURCES,
    },
    {
        "subject": "中国铁塔", "period": "Q4 2025", "metric_key": "net_income",
        "official_value": 2922, "unit": "millions CNY",
        "source_label": "中国铁塔2025年度业绩演示", "source_url": TOWER_2025_ANNUAL_PRESENTATION_URL,
        "evidence": "全年Profit Attributable to Owners of the Company 11,630百万元，减前三季度归母利润8,708百万元，复算Q4为2,922百万元。",
        "verification_method": "official_annual_minus_9m_reconciliation", "verification_sources": TOWER_2025_Q4_SOURCES,
    },
    {
        "subject": "中国铁塔", "period": "Q4 2025", "metric_key": "operator_business_revenue",
        "official_value": 21293, "unit": "millions CNY",
        "source_label": "中国铁塔2025年度业绩演示", "source_url": TOWER_2025_ANNUAL_PRESENTATION_URL,
        "evidence": "全年TSP/运营商业务收入84,725百万元，减前三季度63,432百万元，复算Q4为21,293百万元。",
        "verification_method": "official_annual_minus_9m_reconciliation", "verification_sources": TOWER_2025_Q4_SOURCES,
    },
    {
        "subject": "中国铁塔", "period": "Q4 2025", "metric_key": "tower_business_revenue",
        "official_value": 18989, "unit": "millions CNY",
        "source_label": "中国铁塔2025年度业绩演示", "source_url": TOWER_2025_ANNUAL_PRESENTATION_URL,
        "evidence": "全年塔类业务收入75,498百万元，减前三季度56,509百万元，复算Q4为18,989百万元。",
        "verification_method": "official_annual_minus_9m_reconciliation", "verification_sources": TOWER_2025_Q4_SOURCES,
    },
    {
        "subject": "中国铁塔", "period": "Q4 2025", "metric_key": "das_business_revenue",
        "official_value": 2304, "unit": "millions CNY",
        "source_label": "中国铁塔2025年度业绩演示", "source_url": TOWER_2025_ANNUAL_PRESENTATION_URL,
        "evidence": "全年室分业务收入9,227百万元，减前三季度6,923百万元，复算Q4为2,304百万元。",
        "verification_method": "official_annual_minus_9m_reconciliation", "verification_sources": TOWER_2025_Q4_SOURCES,
    },
    {
        "subject": "中国铁塔", "period": "Q4 2025", "metric_key": "smart_business_revenue",
        "official_value": 3079, "unit": "millions CNY",
        "source_label": "中国铁塔2025年度业绩演示", "source_url": TOWER_2025_ANNUAL_PRESENTATION_URL,
        "evidence": "全年智联业务收入10,172百万元，减前三季度7,093百万元，复算Q4为3,079百万元。",
        "verification_method": "official_annual_minus_9m_reconciliation", "verification_sources": TOWER_2025_Q4_SOURCES,
    },
    {
        "subject": "中国铁塔", "period": "Q4 2025", "metric_key": "energy_business_revenue",
        "official_value": 1389, "unit": "millions CNY",
        "source_label": "中国铁塔2025年度业绩演示", "source_url": TOWER_2025_ANNUAL_PRESENTATION_URL,
        "evidence": "全年能源业务收入4,813百万元，减前三季度3,424百万元，复算Q4为1,389百万元。",
        "verification_method": "official_annual_minus_9m_reconciliation", "verification_sources": TOWER_2025_Q4_SOURCES,
    },
    {
        "subject": "中国铁塔", "period": "Q4 2025", "metric_key": "total_assets",
        "official_value": 336579, "unit": "millions CNY",
        "source_label": "中国铁塔2025业绩新闻稿", "source_url": TOWER_2025_ANNUAL_NEWS_URL,
        "evidence": "截至2025年12月31日，公司总资产达3365.79亿元，即336,579百万元。",
        "verification_method": "official_year_end_balance_sheet_point_check", "verification_sources": TOWER_2025_Q4_SOURCES[2:],
    },
    {
        "subject": "中国铁塔", "period": "Q4 2025", "metric_key": "total_debt",
        "official_value": 90460, "unit": "millions CNY",
        "source_label": "中国铁塔2025业绩新闻稿", "source_url": TOWER_2025_ANNUAL_NEWS_URL,
        "evidence": "截至2025年12月31日，带息负债为904.60亿元，即90,460百万元。",
        "verification_method": "official_year_end_debt_point_check", "verification_sources": TOWER_2025_Q4_SOURCES[2:],
    },
    {
        "subject": "中国移动",
        "period": "Q2 2025",
        "metric_key": "revenue",
        "official_value": 280009,
        "unit": "millions CNY",
        "source_label": "中国移动2025年官方单季度经营数据",
        "source_url": "https://www.chinamobileltd.com/en/ir/operation_q.php?year=2025",
        "evidence": "官网直接列示2025/2Q Operating Revenue 280.0亿元；港交所中报半年543,769百万元减Q1 263,760百万元，复算Q2为280,009百万元。",
        "verification_method": "official_direct_quarter_and_h1_minus_q1_reconciliation",
        "verification_sources": [
            {"label": "中国移动官网2025单季度经营数据", "url": "https://www.chinamobileltd.com/en/ir/operation_q.php?year=2025", "evidence": "2025/2Q Operating Revenue RMB280.0 billion."},
            {"label": "中国移动2025中期报告（港交所）", "url": "https://www1.hkexnews.hk/listedco/listconews/sehk/2025/0829/2025082901049.pdf", "evidence": "1H2025 operating revenue RMB543,769 million."},
            {"label": "中国移动2025年第一季度报告（上交所）", "url": "https://static.sse.com.cn/disclosure/listedinfo/announcement/c/new/2025-04-23/600941_20250423_97Z1.pdf", "evidence": "Q1 operating revenue RMB263,760 million."},
        ],
    },
    {
        "subject": "中国移动",
        "period": "Q2 2025",
        "metric_key": "operating_revenue",
        "official_value": 244589,
        "unit": "millions CNY",
        "source_label": "中国移动2025年官方单季度经营数据",
        "source_url": "https://www.chinamobileltd.com/en/ir/operation_q.php?year=2025",
        "evidence": "官网直接列示2025/2Q通信服务收入244.6亿元；港交所中护466,989减Q1 222,400，复算244,589百万元。",
        "verification_method": "official_direct_quarter_and_h1_minus_q1_reconciliation",
        "verification_sources": [
            {"label": "中国移动官网2025单季度经营数据", "url": "https://www.chinamobileltd.com/en/ir/operation_q.php?year=2025", "evidence": "2025/2Q telecommunications services revenue RMB244.6 billion."},
            {"label": "中国移动2025中期报告（港交所）", "url": "https://www1.hkexnews.hk/listedco/listconews/sehk/2025/0829/2025082901049.pdf", "evidence": "1H2025 telecommunications services revenue RMB466,989 million."},
            {"label": "中国移动2025年第一季度报告（上交所）", "url": "https://static.sse.com.cn/disclosure/listedinfo/announcement/c/new/2025-04-23/600941_20250423_97Z1.pdf", "evidence": "Q1 principal business revenue RMB222,400 million."},
        ],
    },
    {
        "subject": "中国移动",
        "period": "Q2 2025",
        "metric_key": "ebitda",
        "official_value": 105258,
        "unit": "millions CNY",
        "source_label": "中国移动2025年官方单季度经营数据",
        "source_url": "https://www.chinamobileltd.com/en/ir/operation_q.php?year=2025",
        "evidence": "官网直接列示2025/2Q EBITDA 105.3亿元；港交所中护185,958减Q1官方80,700，复算105,258百万元。",
        "verification_method": "official_direct_quarter_and_h1_minus_q1_reconciliation",
        "verification_sources": [
            {"label": "中国移动官网2025单季度经营数据", "url": "https://www.chinamobileltd.com/en/ir/operation_q.php?year=2025", "evidence": "2025/2Q EBITDA RMB105.3 billion."},
            {"label": "中国移动2025中期报告（港交所）", "url": "https://www1.hkexnews.hk/listedco/listconews/sehk/2025/0829/2025082901049.pdf", "evidence": "1H2025 EBITDA RMB185,958 million."},
            {"label": "中国移动2025年第一季度报告（上交所）", "url": "https://static.sse.com.cn/disclosure/listedinfo/announcement/c/new/2025-04-23/600941_20250423_97Z1.pdf", "evidence": "Q1 EBITDA RMB80,700 million."},
        ],
    },
    {
        "subject": "中国移动",
        "period": "Q2 2025",
        "metric_key": "net_income",
        "official_value": 53604,
        "unit": "millions CNY",
        "source_label": "中国移动2025年官方单季度经营数据",
        "source_url": "https://www.chinamobileltd.com/en/ir/operation_q.php?year=2025",
        "evidence": "官网直接列示2025/2Q归母利润53.6亿元；港交所中护84,235减Q1 30,631，复算53,604百万元。",
        "verification_method": "official_direct_quarter_and_h1_minus_q1_reconciliation",
        "verification_sources": [
            {"label": "中国移动官网2025单季度经营数据", "url": "https://www.chinamobileltd.com/en/ir/operation_q.php?year=2025", "evidence": "2025/2Q profit attributable to equity shareholders RMB53.6 billion."},
            {"label": "中国移动2025中期报告（港交所）", "url": "https://www1.hkexnews.hk/listedco/listconews/sehk/2025/0829/2025082901049.pdf", "evidence": "1H2025 attributable profit RMB84,235 million."},
            {"label": "中国移动2025年第一季度报告（上交所）", "url": "https://static.sse.com.cn/disclosure/listedinfo/announcement/c/new/2025-04-23/600941_20250423_97Z1.pdf", "evidence": "Q1 attributable profit RMB30,631 million."},
        ],
    },
    {
        "subject": "中国移动",
        "period": "Q2 2025",
        "metric_key": "operating_cash_flow",
        "official_value": 52515,
        "unit": "millions CNY",
        "source_label": "中国移动2025中期报告（港交所）",
        "source_url": "https://www1.hkexnews.hk/listedco/listconews/sehk/2025/0829/2025082901049.pdf",
        "evidence": "港交所中护经营现金流83,832减上交所Q1 31,317，复算Q2为52,515百万元；公司官网董事长报告同时披露半年经营现金流838亿元。",
        "verification_method": "official_h1_minus_q1_reconciliation",
        "verification_sources": [
            {"label": "中国移动2025中期报告（港交所）", "url": "https://www1.hkexnews.hk/listedco/listconews/sehk/2025/0829/2025082901049.pdf", "evidence": "1H2025 net operating cash flow RMB83,832 million."},
            {"label": "中国移动2025年第一季度报告（上交所）", "url": "https://static.sse.com.cn/disclosure/listedinfo/announcement/c/new/2025-04-23/600941_20250423_97Z1.pdf", "evidence": "Q1 net operating cash flow RMB31,317 million."},
            {"label": "中国移动官网2025中期业绩摘要", "url": "https://www.chinamobileltd.com/en/about/chairman.php", "evidence": "1H2025 net cash generated from operating activities RMB83.8 billion."},
        ],
    },
    {
        "subject": "中国移动",
        "period": "Q2 2025",
        "metric_key": "capital_expenditures",
        "official_value": -39158,
        "unit": "millions CNY",
        "source_label": "中国移动2025中期报告（港交所，现金流口径）",
        "source_url": "https://www1.hkexnews.hk/listedco/listconews/sehk/2025/0829/2025082901049.pdf",
        "evidence": "中报购建固定资产等现金支出-75,540减Q1现金支出-36,382，复算Q2为-39,158百万元。该现金流口径不等同于公司管理口径的半年资本开支584亿元。",
        "verification_method": "official_h1_minus_q1_cash_flow_reconciliation",
        "verification_sources": [
            {"label": "中国移动2025中期报告（港交所）", "url": "https://www1.hkexnews.hk/listedco/listconews/sehk/2025/0829/2025082901049.pdf", "evidence": "1H2025 cash payment for property, plant, intangibles and non-current assets RMB75,540 million."},
            {"label": "中国移动2025年第一季度报告（上交所）", "url": "https://static.sse.com.cn/disclosure/listedinfo/announcement/c/new/2025-04-23/600941_20250423_97Z1.pdf", "evidence": "Q1 cash payment for long-term assets RMB36,382 million."},
        ],
    },
    {
        "subject": "中国移动",
        "period": "Q2 2025",
        "metric_key": "free_cash_flow",
        "official_value": 13357,
        "unit": "millions CNY",
        "source_label": "中国移动2025中期报告（港交所，现金流口径）",
        "source_url": "https://www1.hkexnews.hk/listedco/listconews/sehk/2025/0829/2025082901049.pdf",
        "evidence": "Q2经营现金流按上半年83,832减Q1 31,317复算为52,515百万元；Q2购建长期资产现金支出为39,158百万元；自由现金流为13,357百万元。",
        "verification_method": "official_operating_cash_flow_minus_capex_reconciliation",
        "verification_sources": [
            {"label": "中国移动2025中期报告（港交所）", "url": "https://www1.hkexnews.hk/listedco/listconews/sehk/2025/0829/2025082901049.pdf", "evidence": "1H2025 cash flow statement for operating cash flow and long-term asset cash payment."},
            {"label": "中国移动2025年第一季度报告（上交所）", "url": "https://static.sse.com.cn/disclosure/listedinfo/announcement/c/new/2025-04-23/600941_20250423_97Z1.pdf", "evidence": "Q1 operating cash flow and cash payment for long-term assets."},
        ],
    },
    {
        "subject": "中国移动", "period": "Q3 2025", "metric_key": "revenue",
        "official_value": 250897, "unit": "millions CNY",
        "source_label": "中国移动2025年官方单季度经营数据", "source_url": CM_2025_OPERATION_URL,
        "evidence": "官网直接列示2025/3Q收入250.9亿元；前三季度794,666减上半年543,769，复算250,897百万元。",
        "verification_method": "official_direct_quarter_and_9m_minus_h1_reconciliation", "verification_sources": CM_2025_Q3_DIRECT_SOURCES,
    },
    {
        "subject": "中国移动", "period": "Q3 2025", "metric_key": "operating_revenue",
        "official_value": 216157, "unit": "millions CNY",
        "source_label": "中国移动2025年官方单季度经营数据", "source_url": CM_2025_OPERATION_URL,
        "evidence": "官网直接列示2025/3Q通信服务收入216.1亿元；前三季度683,146减上半年466,989，复算216,157百万元。",
        "verification_method": "official_direct_quarter_and_9m_minus_h1_reconciliation", "verification_sources": CM_2025_Q3_DIRECT_SOURCES,
    },
    {
        "subject": "中国移动", "period": "Q3 2025", "metric_key": "ebitda",
        "official_value": 79438, "unit": "millions CNY",
        "source_label": "中国移动2025年官方单季度经营数据", "source_url": CM_2025_OPERATION_URL,
        "evidence": "官网直接列示2025/3Q EBITDA 79.4亿元；前三季度EBITDA按营业利润123,372加折旧摊销142,024得到265,396，减上半年185,958，复算Q3为79,438百万元。",
        "verification_method": "official_direct_quarter_and_9m_minus_h1_reconciliation", "verification_sources": CM_2025_Q3_DIRECT_SOURCES,
    },
    {
        "subject": "中国移动", "period": "Q3 2025", "metric_key": "net_income",
        "official_value": 31118, "unit": "millions CNY",
        "source_label": "中国移动2025年官方单季度经营数据", "source_url": CM_2025_OPERATION_URL,
        "evidence": "官网直接列示2025/3Q归母利润31.2亿元；前三季度115,353减上半年84,235，复算31,118百万元。",
        "verification_method": "official_direct_quarter_and_9m_minus_h1_reconciliation", "verification_sources": CM_2025_Q3_DIRECT_SOURCES,
    },
    {
        "subject": "中国移动", "period": "Q3 2025", "metric_key": "operating_cash_flow",
        "official_value": 77215, "unit": "millions CNY",
        "source_label": "中国移动2025前三季度业绩（港交所）", "source_url": CM_2025_Q3_HKEX_URL,
        "evidence": "前三季度经营现金流161,047减上半年83,832，复算Q3为77,215百万元。",
        "verification_method": "official_9m_minus_h1_reconciliation", "verification_sources": CM_2025_Q3_STATEMENT_SOURCES,
    },
    {
        "subject": "中国移动", "period": "Q3 2025", "metric_key": "capital_expenditures",
        "official_value": -41575, "unit": "millions CNY",
        "source_label": "中国移动2025前三季度业绩（港交所，现金流口径）", "source_url": CM_2025_Q3_HKEX_URL,
        "evidence": "前三季度购建长期资产现金支出-117,115减上半年-75,540，复算Q3为-41,575百万元。",
        "verification_method": "official_9m_minus_h1_cash_flow_reconciliation", "verification_sources": CM_2025_Q3_STATEMENT_SOURCES,
    },
    {
        "subject": "中国移动", "period": "Q3 2025", "metric_key": "free_cash_flow",
        "official_value": 35640, "unit": "millions CNY",
        "source_label": "中国移动2025前三季度业绩（港交所，现金流口径）", "source_url": CM_2025_Q3_HKEX_URL,
        "evidence": "Q3经营现金流77,215百万元、购建长期资产现金支出41,575百万元；自由现金流为35,640百万元。",
        "verification_method": "official_operating_cash_flow_minus_capex_reconciliation", "verification_sources": CM_2025_Q3_STATEMENT_SOURCES,
    },
    {
        "subject": "中国移动", "period": "Q3 2025", "metric_key": "cash_and_equivalents",
        "official_value": 97619, "unit": "millions CNY",
        "source_label": "中国移动2025前三季度业绩（港交所）", "source_url": CM_2025_Q3_HKEX_URL,
        "evidence": "截至2025年9月30日现金及现金等价物97,619百万元。",
        "verification_method": "official_balance_sheet_multi_endpoint_check", "verification_sources": CM_2025_Q3_STATEMENT_SOURCES[:2],
    },
    {
        "subject": "中国移动", "period": "Q3 2025", "metric_key": "total_assets",
        "official_value": 2109124, "unit": "millions CNY",
        "source_label": "中国移动2025前三季度业绩（港交所）", "source_url": CM_2025_Q3_HKEX_URL,
        "evidence": "截至2025年9月30日总资产2,109,124百万元。",
        "verification_method": "official_balance_sheet_multi_endpoint_check", "verification_sources": CM_2025_Q3_STATEMENT_SOURCES[:2],
    },
    {
        "subject": "中国移动", "period": "Q3 2025", "metric_key": "total_debt",
        "official_value": 99111, "unit": "millions CNY",
        "source_label": "中国移动2025前三季度业绩（港交所）", "source_url": CM_2025_Q3_HKEX_URL,
        "evidence": "总债务按短期借款9,715+长期借款10+流动租赁负债35,464+非流动租赁负债53,922复算为99,111百万元。",
        "verification_method": "official_balance_sheet_component_reconciliation", "verification_sources": CM_2025_Q3_STATEMENT_SOURCES[:2],
    },
    {
        "subject": "中国移动", "period": "Q4 2025", "metric_key": "revenue",
        "official_value": 255521, "unit": "millions CNY",
        "source_label": "中国移动2025年报（港交所）", "source_url": CM_2025_ANNUAL_HKEX_URL,
        "evidence": "全年营运收入1,050,187减前三季度794,666，复算Q4为255,521百万元。",
        "verification_method": "official_full_year_minus_9m_reconciliation", "verification_sources": CM_2025_Q4_ANNUAL_SOURCES,
    },
    {
        "subject": "中国移动", "period": "Q4 2025", "metric_key": "operating_revenue",
        "official_value": 212384, "unit": "millions CNY",
        "source_label": "中国移动2025年报（港交所）", "source_url": CM_2025_ANNUAL_HKEX_URL,
        "evidence": "全年主营业务收入895,530减前三季度683,146，复算Q4为212,384百万元；标准化表把营运收入当成该口径时会高估。",
        "verification_method": "official_full_year_minus_9m_reconciliation", "verification_sources": CM_2025_Q4_ANNUAL_SOURCES,
    },
    {
        "subject": "中国移动", "period": "Q4 2025", "metric_key": "ebitda",
        "official_value": 73535, "unit": "millions CNY",
        "source_label": "中国移动2025年报（港交所）", "source_url": CM_2025_ANNUAL_HKEX_URL,
        "evidence": "全年EBITDA338,931减前三季度EBITDA265,396，复算Q4为73,535百万元。",
        "verification_method": "official_full_year_minus_9m_reconciliation", "verification_sources": CM_2025_Q4_ANNUAL_SOURCES,
    },
    {
        "subject": "中国移动", "period": "Q4 2025", "metric_key": "net_income",
        "official_value": 21742, "unit": "millions CNY",
        "source_label": "中国移动2025年报（港交所）", "source_url": CM_2025_ANNUAL_HKEX_URL,
        "evidence": "全年归母净利润137,095减前三季度115,353，复算Q4为21,742百万元。",
        "verification_method": "official_full_year_minus_9m_reconciliation", "verification_sources": CM_2025_Q4_ANNUAL_SOURCES,
    },
    {
        "subject": "中国移动", "period": "Q4 2025", "metric_key": "operating_cash_flow",
        "official_value": 71872, "unit": "millions CNY",
        "source_label": "中国移动2025年报（港交所，现金流口径）", "source_url": CM_2025_ANNUAL_HKEX_URL,
        "evidence": "全年经营现金流232,919减前三季度161,047，复算Q4为71,872百万元。",
        "verification_method": "official_full_year_minus_9m_cash_flow_reconciliation", "verification_sources": CM_2025_Q4_CASH_FLOW_SOURCES,
    },
    {
        "subject": "中国移动", "period": "Q4 2025", "metric_key": "capital_expenditures",
        "official_value": -39836, "unit": "millions CNY",
        "source_label": "中国移动2025年报（港交所，现金流口径）", "source_url": CM_2025_ANNUAL_HKEX_URL,
        "evidence": "全年购建固定资产、无形资产和其他长期资产现金支出-156,951减前三季度-117,115，复算Q4为-39,836百万元。",
        "verification_method": "official_full_year_minus_9m_cash_flow_reconciliation", "verification_sources": CM_2025_Q4_CASH_FLOW_SOURCES,
    },
    {
        "subject": "中国移动", "period": "Q4 2025", "metric_key": "free_cash_flow",
        "official_value": 32036, "unit": "millions CNY",
        "source_label": "中国移动2025年报（港交所，现金流口径）", "source_url": CM_2025_ANNUAL_HKEX_URL,
        "evidence": "Q4经营现金流71,872百万元、购建长期资产现金支出39,836百万元；自由现金流为32,036百万元。",
        "verification_method": "official_operating_cash_flow_minus_capex_reconciliation", "verification_sources": CM_2025_Q4_CASH_FLOW_SOURCES,
    },
    {
        "subject": "中国移动", "period": "Q4 2025", "metric_key": "cash_and_equivalents",
        "official_value": 97267, "unit": "millions CNY",
        "source_label": "中国移动2025年报（港交所）", "source_url": CM_2025_ANNUAL_HKEX_URL,
        "evidence": "2025年末现金及现金等价物余额97,267百万元；该时点余额与标准化表的现金及等价物口径不一致。",
        "verification_method": "official_balance_sheet_multi_endpoint_check", "verification_sources": CM_2025_Q4_BALANCE_SHEET_SOURCES,
    },
    {
        "subject": "中国移动", "period": "Q4 2025", "metric_key": "total_assets",
        "official_value": 2092882, "unit": "millions CNY",
        "source_label": "中国移动2025年报（港交所）", "source_url": CM_2025_ANNUAL_HKEX_URL,
        "evidence": "2025年末资产总额2,092,882百万元；中文摘要列示资产总额20,929亿元。",
        "verification_method": "official_balance_sheet_multi_endpoint_check", "verification_sources": CM_2025_Q4_BALANCE_SHEET_SOURCES[:2],
    },
    {
        "subject": "3HK / Hutchison", "period": "H1 2025", "metric_key": "operating_margin",
        "official_value": 0.271, "unit": "percent",
        "source_label": "HTHKH 2025 Interim Report - MD&A", "source_url": HTHKH_2025_H1_ANALYSIS_URL,
        "evidence": "2025中期业绩披露Revenue 2,216百万港元、Operating profit 6百万港元；经营利润率复算为0.271%。",
        "verification_method": "official_operating_income_divided_by_revenue_reconciliation", "verification_sources": HTHKH_2025_H1_SOURCES,
    },
    {
        "subject": "3HK / Hutchison", "period": "H2 2025", "metric_key": "operating_margin",
        "official_value": 0.371, "unit": "percent",
        "source_label": "HTHKH 2025 Annual Report - MD&A", "source_url": HTHKH_2025_AR_ANALYSIS_URL,
        "evidence": "2025全年数减H1复算H2 Revenue 3,232百万港元、Operating profit 12百万港元；经营利润率复算为0.371%。",
        "verification_method": "official_operating_income_divided_by_revenue_reconciliation", "verification_sources": HTHKH_2025_H2_SOURCES,
    },
    {
        "subject": "SmarTone", "period": "H1 2025", "metric_key": "operating_margin",
        "official_value": 12.015, "unit": "percent",
        "source_label": "SmarTone 2024/25 Interim Results Announcement", "source_url": SMARTONE_2025_H1_RESULTS_URL,
        "evidence": "2024/25中期业绩披露Revenues 3,491.538百万港元、Operating profit 419.512百万港元；经营利润率复算为12.015%。",
        "verification_method": "official_operating_income_divided_by_revenue_reconciliation", "verification_sources": SMARTONE_2025_H1_SOURCES,
    },
    {
        "subject": "SmarTone", "period": "H2 2025", "metric_key": "operating_margin",
        "official_value": 12.046, "unit": "percent",
        "source_label": "SmarTone 2024/25 Annual Report", "source_url": SMARTONE_2025_H2_REPORT_URL,
        "evidence": "2024/25全年数减H1复算H2 Revenues 2,761.909百万港元、Operating profit 332.697百万港元；经营利润率复算为12.046%。",
        "verification_method": "official_operating_income_divided_by_revenue_reconciliation", "verification_sources": SMARTONE_2025_H2_SOURCES,
    },
    {
        "subject": "SmarTone", "period": "H1 2026", "metric_key": "operating_margin",
        "official_value": 10.996, "unit": "percent",
        "source_label": "SmarTone 2025/26 Interim Results Announcement", "source_url": SMARTONE_2026_H1_RESULTS_URL,
        "evidence": "2025/26中期业绩披露Revenues 3,561.288百万港元、Operating profit 391.598百万港元；经营利润率复算为10.996%。",
        "verification_method": "official_operating_income_divided_by_revenue_reconciliation", "verification_sources": SMARTONE_2026_H1_SOURCES,
    },
    {
        "subject": "中国电信", "period": "Q1 2025", "metric_key": "operating_margin",
        "official_value": 7.932, "unit": "percent",
        "source_label": "中国电信2025年第一季度报告（港交所/IRAsia）", "source_url": CT_2025_Q1_HKEX_URL,
        "evidence": "2025Q1 Operating profit 10,748百万元，Operating revenues 135,498百万元；经营利润率复算为7.932%。",
        "verification_method": "official_operating_income_divided_by_revenue_reconciliation", "verification_sources": CT_2025_Q2_SOURCES[:1],
    },
    {
        "subject": "中国电信", "period": "Q2 2025", "metric_key": "operating_margin",
        "official_value": 13.092, "unit": "percent",
        "source_label": "中国电信2025中期业绩（港交所/IRAsia）", "source_url": CT_2025_H1_HKEX_URL,
        "evidence": "H1减Q1复算Q2 Operating profit 17,801百万元，Operating revenues 135,971百万元；经营利润率复算为13.092%。",
        "verification_method": "official_operating_income_divided_by_revenue_reconciliation", "verification_sources": CT_2025_Q2_SOURCES,
    },
    {
        "subject": "中国电信", "period": "Q3 2025", "metric_key": "operating_margin",
        "official_value": 7.321, "unit": "percent",
        "source_label": "中国电信2025年前三季度报告（港交所/IRAsia）", "source_url": CT_2025_Q3_HKEX_URL,
        "evidence": "前三季度减H1复算Q3 Operating profit 9,190百万元，Operating revenues 125,529百万元；经营利润率复算为7.321%。",
        "verification_method": "official_operating_income_divided_by_revenue_reconciliation", "verification_sources": CT_2025_Q3_SOURCES,
    },
    {
        "subject": "中国电信", "period": "Q1 2026", "metric_key": "operating_margin",
        "official_value": 7.213, "unit": "percent",
        "source_label": "中国电信2026年第一季度报告", "source_url": CT_2026_Q1_CNINFO_URL,
        "evidence": "2026Q1营业利润9,477.563百万元、营业收入131,393.926百万元；经营利润率复算为7.213%。",
        "verification_method": "official_operating_income_divided_by_revenue_reconciliation", "verification_sources": CT_2026_Q1_SOURCES,
    },
    {
        "subject": "中国移动", "period": "Q1 2025", "metric_key": "operating_margin",
        "official_value": 14.792, "unit": "percent",
        "source_label": "中国移动2025年第一季度报告（上交所）", "source_url": CM_2025_Q1_SSE_URL,
        "evidence": "2025Q1营业利润39,016百万元、营业收入263,760百万元；经营利润率复算为14.792%。该口径与标准化表的operating income定义不同。",
        "verification_method": "official_operating_income_divided_by_revenue_reconciliation", "verification_sources": CM_2025_Q1_DETAIL_SOURCES,
    },
    {
        "subject": "中国联通", "period": "Q1 2025", "metric_key": "operating_margin",
        "official_value": 7.008, "unit": "percent",
        "source_label": "中国联通2025年第一季度报告（上交所，600050 A股口径）", "source_url": CU_2025_Q1_SSE_URL,
        "evidence": "2025Q1营业利润7,243.432百万元、营业收入103,353.772百万元；经营利润率复算为7.008%。该口径与0762.HK标准化表不完全相同。",
        "verification_method": "official_operating_income_divided_by_revenue_reconciliation", "verification_sources": CU_2025_Q1_SOURCES,
    },
    {
        "subject": "中国联通", "period": "Q2 2025", "metric_key": "operating_margin",
        "official_value": 10.071, "unit": "percent",
        "source_label": "中国联通2025年半年度报告（600050 A股口径）", "source_url": CU_2025_H1_SINA_URL,
        "evidence": "A股半年度报告H1营业利润16,996.678百万元、营业收入200,202.431百万元，减Q1营业利润7,243.432百万元、营业收入103,353.772百万元，复算Q2营业利润9,753.245百万元、营业收入96,848.659百万元；经营利润率为10.071%。",
        "verification_method": "official_operating_income_divided_by_revenue_reconciliation",
        "verification_sources": CU_2025_Q2_DETAIL_SOURCES,
    },
    {
        "subject": "中国电信", "period": "Q1 2025", "metric_key": "ebitda_margin",
        "official_value": 27.085, "unit": "percent",
        "source_label": "中国电信2025年第一季度报告（港交所/IRAsia）", "source_url": CT_2025_Q1_HKEX_URL,
        "evidence": "2025Q1 EBITDA 36,700百万元、Operating revenues 135,498百万元；EBITDA率复算为27.085%。",
        "verification_method": "official_ebitda_divided_by_revenue_reconciliation", "verification_sources": CT_2025_Q2_SOURCES[:1],
    },
    {
        "subject": "中国电信", "period": "Q2 2025", "metric_key": "ebitda_margin",
        "official_value": 32.277, "unit": "percent",
        "source_label": "中国电信2025中期业绩（港交所/IRAsia）", "source_url": CT_2025_H1_HKEX_URL,
        "evidence": "H1减Q1复算Q2 EBITDA 43,888百万元、Operating revenues 135,971百万元；EBITDA率复算为32.277%。",
        "verification_method": "official_ebitda_divided_by_revenue_reconciliation", "verification_sources": CT_2025_Q2_SOURCES,
    },
    {
        "subject": "中国电信", "period": "Q3 2025", "metric_key": "ebitda_margin",
        "official_value": 27.892, "unit": "percent",
        "source_label": "中国电信2025年前三季度报告（港交所/IRAsia）", "source_url": CT_2025_Q3_HKEX_URL,
        "evidence": "前三季度减H1复算Q3 EBITDA 35,012百万元、Operating revenues 125,529百万元；EBITDA率复算为27.892%。",
        "verification_method": "official_ebitda_divided_by_revenue_reconciliation", "verification_sources": CT_2025_Q3_SOURCES,
    },
    {
        "subject": "中国电信", "period": "Q4 2025", "metric_key": "ebitda_margin",
        "official_value": 21.321, "unit": "percent",
        "source_label": "中国电信2025年度业绩新闻稿", "source_url": CT_2025_ANNUAL_RESULTS_URL,
        "evidence": "全年减前三季度复算Q4 EBITDA 28,272百万元、经营收入132,602百万元；EBITDA率复算为21.321%。",
        "verification_method": "official_ebitda_divided_by_revenue_reconciliation", "verification_sources": CT_2025_Q4_SOURCES,
    },
    {
        "subject": "中国移动", "period": "Q1 2025", "metric_key": "ebitda_margin",
        "official_value": 30.596, "unit": "percent",
        "source_label": "中国移动2025年第一季度报告（上交所）", "source_url": CM_2025_Q1_SSE_URL,
        "evidence": "2025Q1 EBITDA 80,700百万元、营业收入263,760百万元；EBITDA率复算为30.596%。",
        "verification_method": "official_ebitda_divided_by_revenue_reconciliation", "verification_sources": CM_2025_Q1_DETAIL_SOURCES,
    },
    {
        "subject": "中国移动", "period": "Q2 2025", "metric_key": "ebitda_margin",
        "official_value": 37.591, "unit": "percent",
        "source_label": "中国移动2025中期报告（港交所）", "source_url": "https://www1.hkexnews.hk/listedco/listconews/sehk/2025/0829/2025082901049.pdf",
        "evidence": "H1减Q1复算Q2 EBITDA 105,258百万元、营运收入280,009百万元；EBITDA率复算为37.591%。",
        "verification_method": "official_ebitda_divided_by_revenue_reconciliation",
    },
    {
        "subject": "中国移动", "period": "Q3 2025", "metric_key": "ebitda_margin",
        "official_value": 31.662, "unit": "percent",
        "source_label": "中国移动2025年官方单季度经营数据", "source_url": CM_2025_OPERATION_URL,
        "evidence": "官方单季度经营数据/前三季度复算Q3 EBITDA 79,438百万元、营运收入250,897百万元；EBITDA率复算为31.662%。",
        "verification_method": "official_ebitda_divided_by_revenue_reconciliation", "verification_sources": CM_2025_Q3_DIRECT_SOURCES,
    },
    {
        "subject": "中国移动", "period": "Q4 2025", "metric_key": "ebitda_margin",
        "official_value": 28.778, "unit": "percent",
        "source_label": "中国移动2025年报（港交所）", "source_url": CM_2025_ANNUAL_HKEX_URL,
        "evidence": "全年减前三季度复算Q4 EBITDA 73,535百万元、营运收入255,521百万元；EBITDA率复算为28.778%。",
        "verification_method": "official_ebitda_divided_by_revenue_reconciliation", "verification_sources": CM_2025_Q4_ANNUAL_SOURCES,
    },
    {
        "subject": "中国移动", "period": "Q1 2026", "metric_key": "ebitda_margin",
        "official_value": 28.783, "unit": "percent",
        "source_label": "中国移动2026年第一季度报告", "source_url": "https://dataclouds.cninfo.com.cn/shgonggao/hsomarket/2026/20260420/c34d1cf7b4794bebb3f39acf8b598c4b.PDF",
        "evidence": "2026Q1 EBITDA 76,700百万元、营业收入266,478百万元；EBITDA率复算为28.783%。",
        "verification_method": "official_ebitda_divided_by_revenue_reconciliation",
    },
    {
        "subject": "中国铁塔", "period": "Q2 2025", "metric_key": "ebitda_margin",
        "official_value": 68.192, "unit": "percent",
        "source_label": "中国铁塔2025中期业绩", "source_url": TOWER_2025_H1_URL,
        "evidence": "H1减Q1复算Q2 EBITDA 16,932百万元、营业收入24,830百万元；EBITDA率复算为68.192%。",
        "verification_method": "official_ebitda_divided_by_revenue_reconciliation", "verification_sources": TOWER_2025_Q2_SOURCES,
    },
    {
        "subject": "中国铁塔", "period": "Q3 2025", "metric_key": "ebitda_margin",
        "official_value": 67.692, "unit": "percent",
        "source_label": "中国铁塔2025年前三季度未经审核主要运营数据", "source_url": TOWER_2025_Q3_URL,
        "evidence": "前三季度减H1复算Q3 EBITDA 16,732百万元、营业收入24,718百万元；EBITDA率复算为67.692%。",
        "verification_method": "official_ebitda_divided_by_revenue_reconciliation", "verification_sources": TOWER_2025_Q3_SOURCES,
    },
    {
        "subject": "中国铁塔", "period": "Q4 2025", "metric_key": "ebitda_margin",
        "official_value": 56.933, "unit": "percent",
        "source_label": "中国铁塔2025年度业绩演示", "source_url": TOWER_2025_ANNUAL_PRESENTATION_URL,
        "evidence": "全年减前三季度复算Q4 EBITDA 14,855百万元、营业收入26,092百万元；EBITDA率复算为56.933%。",
        "verification_method": "official_ebitda_divided_by_revenue_reconciliation", "verification_sources": TOWER_2025_Q4_SOURCES,
    },
]


def stockanalysis_url(spec: SubjectSpec, statement: str) -> str:
    if not spec.stockanalysis_kind or not spec.stockanalysis_slug:
        raise ValueError(f"{spec.subject} has no stockanalysis source")
    base = (
        f"https://stockanalysis.com/quote/hkg/{spec.stockanalysis_slug}/financials"
        if spec.stockanalysis_kind == "hkg"
        else f"https://stockanalysis.com/stocks/{spec.stockanalysis_slug}/financials"
    )
    suffix = {
        "income_statement": "",
        "balance_sheet": "/balance-sheet",
        "cash_flow": "/cash-flow-statement",
    }[statement]
    return f"{base}{suffix}/?p=quarterly"


def fetch(url: str) -> str:
    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
        "Accept": "text/html,application/xhtml+xml",
    }
    cache_path = SOURCE_CACHE_ROOT / f"{hashlib.sha256(url.encode('utf-8')).hexdigest()}.html"
    try:
        with httpx.Client(headers=headers, follow_redirects=True, timeout=30) as client:
            response = client.get(url)
            response.raise_for_status()
            text = response.text
        SOURCE_CACHE_ROOT.mkdir(parents=True, exist_ok=True)
        cache_path.write_text(text, encoding="utf-8")
        return text
    except Exception:
        if cache_path.exists():
            return cache_path.read_text(encoding="utf-8")
        raise


def _period_grain(label: str) -> str:
    if re.match(r"Q[1-4]\s+\d{4}", label):
        return "quarter"
    if re.match(r"H[1-2]\s+\d{4}", label):
        return "half_year"
    return "period"


def _period_end_from_label(label: str) -> str:
    match = re.match(r"([QH])([1-4])\s+(\d{4})", label)
    if not match:
        return ""
    prefix, number, year = match.groups()
    month_day = {
        ("Q", "1"): "Mar 31",
        ("Q", "2"): "Jun 30",
        ("Q", "3"): "Sep 30",
        ("Q", "4"): "Dec 31",
        ("H", "1"): "Jun 30",
        ("H", "2"): "Dec 31",
    }.get((prefix, number))
    return f"{month_day}, {year}" if month_day else ""


def _period_sort_key(label: str) -> tuple[int, int]:
    match = re.match(r"([QH])([1-4])\s+(\d{4})", label)
    if not match:
        return (0, 0)
    prefix, number, year = match.groups()
    multiplier = 10 if prefix == "Q" else 20
    return (int(year), multiplier + int(number))


def parse_stockanalysis_rows(
    rows: list[list[str]],
    unit: str,
    source_label: str,
    earliest_year: int = 2021,
) -> tuple[dict[str, dict[str, str]], list[dict[str, str]], str]:
    if not rows:
        raise RuntimeError(f"季度财务表为空：{source_label}")
    headers = rows[0]
    periods: list[dict[str, str]] = []
    for idx, header in enumerate(headers):
        if idx == 0:
            continue
        match = re.match(r"([QH][1-4])\s+(\d{4})", header)
        if not match:
            continue
        year = int(match.group(2))
        if year < earliest_year:
            continue
        label = f"{match.group(1)} {year}"
        periods.append({"index": str(idx), "period": label, "year": str(year), "grain": _period_grain(label)})

    period_ending_by_idx: dict[int, str] = {}
    if len(rows) > 1:
        cells = rows[1]
        if cells and cells[0] == "Period Ending":
            for item in periods:
                idx = int(item["index"])
                period_ending_by_idx[idx] = cells[idx] if idx < len(cells) else ""

    parsed: dict[str, dict[str, str]] = {}
    for cells in rows[2:]:
        if not cells:
            continue
        mapped = METRIC_LABELS.get(cells[0])
        if not mapped:
            continue
        metric_key, _metric_zh = mapped
        parsed.setdefault(metric_key, {})
        for item in periods:
            idx = int(item["index"])
            value = cells[idx] if idx < len(cells) else ""
            parsed[metric_key][item["period"]] = value

    normalized_periods = [
        {
            "period": item["period"],
            "grain": item["grain"],
            "period_end": period_ending_by_idx.get(int(item["index"]), ""),
        }
        for item in periods
    ]
    normalized_periods.sort(key=lambda item: _period_sort_key(item["period"]))
    return parsed, normalized_periods, unit


def parse_stockanalysis_quarterly(url: str, earliest_year: int = 2021) -> tuple[dict[str, dict[str, str]], list[dict[str, str]], str]:
    html = fetch(url)
    soup = BeautifulSoup(html, "html.parser")
    text = soup.get_text("\n", strip=True)
    unit_match = re.search(r"Financials in millions ([A-Z]{3})", text)
    unit = f"millions {unit_match.group(1)}" if unit_match else "millions"
    table = soup.find("table")
    if not table:
        raise RuntimeError(f"未找到季度财务表：{url}")
    rows = [
        [cell.get_text(" ", strip=True) for cell in tr.find_all(["th", "td"])]
        for tr in table.find_all("tr")
    ]
    return parse_stockanalysis_rows(rows, unit, url, earliest_year)


def load_stockanalysis_snapshot(path: Path = STOCKANALYSIS_SNAPSHOT) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def merge_stockanalysis_quarterly(
    spec: SubjectSpec,
    snapshot: dict[str, Any] | None = None,
) -> tuple[dict[str, dict[str, str]], list[dict[str, str]], list[dict[str, str]], str]:
    merged: dict[str, dict[str, str]] = {}
    periods_by_name: dict[str, dict[str, str]] = {}
    sources: list[dict[str, str]] = []
    units: list[str] = []
    snapshot_subject = ((snapshot or {}).get("subjects") or {}).get(spec.subject) or {}
    for statement in ["income_statement", "balance_sheet", "cash_flow"]:
        url = stockanalysis_url(spec, statement)
        snapshot_statement = snapshot_subject.get(statement) or {}
        snapshot_rows = snapshot_statement.get("rows") or []
        if snapshot_rows:
            currency = str(snapshot_statement.get("unit") or "").strip()
            unit = f"millions {currency}" if currency else "millions"
            parsed, periods, unit = parse_stockanalysis_rows(
                snapshot_rows,
                unit,
                f"{spec.subject}/{statement} snapshot",
            )
            source_type = "standardized_quarterly_snapshot"
            url = str(snapshot_statement.get("url") or url)
        else:
            parsed, periods, unit = parse_stockanalysis_quarterly(url)
            source_type = "standardized_quarterly_financials"
        units.append(unit)
        sources.append(
            {
                "label": f"StockAnalysis quarterly {statement}",
                "url": url,
                "type": source_type,
            }
        )
        for metric, values in parsed.items():
            merged.setdefault(metric, {}).update(values)
        for period in periods:
            periods_by_name[period["period"]] = period
    unit = next((item for item in units if item and item != "millions"), units[0] if units else "millions")
    periods = sorted(periods_by_name.values(), key=lambda item: _period_sort_key(item["period"]))
    return merged, periods, sources, unit


def load_official_sources() -> dict[str, list[dict[str, str]]]:
    path = ROOT / "carrier_performance_sources.json"
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    out: dict[str, list[dict[str, str]]] = {}
    for subject, payload in (data.get("companies") or {}).items():
        items = []
        for item in payload.get("sources") or []:
            source_type = str(item.get("type") or "").strip()
            if source_type == "broker_view":
                continue
            label = str(item.get("label") or "").strip()
            url = str(item.get("url") or "").strip()
            if not label or not url:
                continue
            if source_type in {"quarterly_results", "interim_results", "annual_results"}:
                items.append({"label": label, "url": url, "type": source_type})
        out[subject] = items
    return out


def build_subject_record(
    spec: SubjectSpec,
    official_sources: dict[str, list[dict[str, str]]],
    snapshot: dict[str, Any] | None = None,
) -> dict[str, Any]:
    record: dict[str, Any] = {
        "subject": spec.subject,
        "legal_name": spec.legal_name,
        "category": spec.category,
        "ticker": spec.ticker,
        "unit": "",
        "periods": [],
        "metrics": {},
        "sources": official_sources.get(spec.subject, []),
        "quality_notes": [],
        "disclosure_frequency": "unknown",
    }
    if spec.disclosure_note:
        record["quality_notes"].append(spec.disclosure_note)
    if spec.category == "cloud":
        record["sources"].extend(CLOUD_QUARTERLY_SOURCE_HINTS.get(spec.subject, []))
        if spec.subject == "AWS":
            record["sources"].extend(AWS_2025_SOURCE_BY_PERIOD.values())
            record["unit"] = "millions USD"
            record["quality_status"] = "official_cloud_segment_quarterly"
            record["disclosure_frequency"] = "quarterly_official_segment_table"
            record["periods"] = AWS_2025_PERIODS
            record["metrics"] = AWS_2025_METRICS
            record["quality_notes"].append(
                "AWS 使用 Amazon 官方 earnings release、trailing AWS Segment 表、SEC 10-Q 和 Form 10-K 的 Segment Information 表；数值为 AWS segment net sales 和 operating income，不使用 Amazon 母公司总收入替代。当前已覆盖 2016Q1-2025Q4。"
            )
            record["quality_notes"].append(
                "2016 Q1-Q3、2017 Q1-Q3、2018 Q1-Q3、2019 Q1-Q3、2020 Q1-Q3、2021 Q1-Q3 来自官方 SEC 10-Q，2022 Q2-Q4、2023 Q1-Q4、2024 Q1-Q4 和 2025 Q1-Q3 来自官方季度 earnings release、10-Q 或 trailing AWS Segment 表；2016 Q4、2017 Q4、2018 Q4、2019 Q4、2020 Q4、2021 Q4、2022 Q1 和 2025 Q4 由对应 Form 10-K 全年分部数减已披露季度数复算，均在 verification_method 中标明。"
            )
            return record
        if spec.subject == "Microsoft Azure / Intelligent Cloud":
            record["sources"].extend(MICROSOFT_2025_SOURCE_BY_PERIOD.values())
            record["unit"] = "millions USD"
            record["quality_status"] = "official_cloud_proxy_segment_quarterly"
            record["disclosure_frequency"] = "quarterly_official_segment_table"
            record["periods"] = MICROSOFT_2025_PERIODS
            record["metrics"] = MICROSOFT_2025_METRICS
            record["quality_notes"].append(
                "Microsoft 不披露 Azure 绝对收入；本包写入官方 Intelligent Cloud 分部 revenue / operating income 作为代理口径，并单列 Azure and other cloud services 收入同比增速。"
            )
            record["quality_notes"].append(
                "期间按自然季度标注：Q1/Q2/Q3/Q4 2024 分别对应 Microsoft FY24 Q3、FY24 Q4、FY25 Q1、FY25 Q2；Q1/Q2/Q3/Q4 2025 分别对应 FY25 Q3、FY25 Q4、FY26 Q1、FY26 Q2。"
            )
            return record
        if spec.subject == "Google Cloud":
            record["sources"].extend(GOOGLE_CLOUD_2025_SOURCE_BY_PERIOD.values())
            record["sources"].append(
                {
                    "label": "Alphabet 2020-2025 Form 10-K - Google Cloud segment tables",
                    "url": ALPHABET_2025_10K_URL,
                    "type": "official_annual_report_segment_table",
                    "evidence": "Alphabet SEC annual segment tables for 2020-2025 are used to cross-check Google Cloud annual revenue and operating income totals and to reconcile Q4 as full year minus Q1-Q3 where needed.",
                }
            )
            record["sources"].append(
                {
                    "label": "Alphabet Q4 2019 earnings exhibit - expanded Google Cloud revenue disclosure",
                    "url": ALPHABET_Q4_2019_EARNINGS_EXHIBIT_URL,
                    "type": "official_sec_8k_earnings_exhibit",
                    "evidence": "Alphabet Q4 2019 earnings exhibit provides Q4 2018 and Q4 2019 Google Cloud revenue and FY2017-FY2019 annual Google Cloud revenue.",
                }
            )
            record["unit"] = "millions USD"
            record["quality_status"] = "official_cloud_segment_quarterly_revenue_with_annual_reconciliation"
            record["disclosure_frequency"] = "quarterly_public_disclosure_with_annual_segment_reconciliation"
            record["periods"] = GOOGLE_CLOUD_2025_PERIODS
            record["metrics"] = GOOGLE_CLOUD_2025_METRICS
            record["quality_notes"].append(
                "Google Cloud 收入和经营利润使用 Alphabet 官方 SEC 10-Q/8-K 季度分部表及 2020-2025 Form 10-K 年度分部表；Q4 2020-Q4 2024 按全年 Google Cloud 分部数减 Q1-Q3 官方季度值复算并在 evidence 中标明。另从 Alphabet Q4 2019 earnings exhibit 保留 Q4 2018 和 Q4 2019 Google Cloud revenue。当前 revenue 有值季度为 Q4 2018、Q4 2019、Q1 2020-Q4 2025；operating_income 仍从 Q1 2020 起。"
            )
            record["quality_notes"].append(
                "Google Cloud revenue_growth_yoy 来自官方季度 10-Q/8-K 管理层讨论或业绩公告；不使用媒体摘要作为逐行核验来源。2016-2019 未发现同等完整的官方季度 Google Cloud revenue 与 operating income 分部序列，除已披露 Q4 2018/Q4 2019 revenue 外不估算。"
            )
            return record
        if spec.subject == "Oracle Cloud":
            record["sources"].extend(ORACLE_CLOUD_SOURCE_BY_PERIOD.values())
            record["unit"] = "billions USD"
            record["quality_status"] = "official_cloud_product_revenue_quarterly"
            record["disclosure_frequency"] = "quarterly_official_cloud_revenue_disclosure"
            record["periods"] = ORACLE_CLOUD_PERIODS
            record["metrics"] = ORACLE_CLOUD_METRICS
            record["quality_notes"].append(
                "Oracle 披露 Cloud Revenue、Cloud Infrastructure (IaaS) Revenue 和 Cloud Application (SaaS) Revenue；本包不把 Oracle 总收入或 Software revenue 当作云收入。"
            )
            record["quality_notes"].append(
                "Oracle 未披露纯云业务利润；本次只写入官方季度云收入拆分和同比增速。"
            )
            return record
        if spec.subject == "Tencent Cloud / Tencent FBS proxy":
            record["sources"].extend(TENCENT_FBS_SOURCE_BY_PERIOD.values())
            record["unit"] = "millions CNY"
            record["quality_status"] = "official_cloud_proxy_segment_quarterly"
            record["disclosure_frequency"] = "quarterly_official_proxy_segment_table"
            record["periods"] = TENCENT_FBS_PERIODS
            record["metrics"] = TENCENT_FBS_METRICS
            record["quality_notes"].append(
                "Tencent 不披露纯 Tencent Cloud 收入；本包使用官方 FinTech and Business Services 分部作为代理口径，需明确包含金融科技、企业服务、云/AI相关服务和电商技术服务等。"
            )
            record["quality_notes"].append(
                "Tencent 自 2019Q1 起开始单独披露 FinTech and Business Services 分部；本包已写入 2019Q1-2026Q1 官方季度 FBS 收入和同比增速。"
            )
            record["quality_notes"].append(
                "2016-2018 未使用旧分部口径替代 FBS；如需 40 季度硬覆盖，应登记 2016Q2-2018Q4 的不可比/source-gap 边界，而不是估算。"
            )
            return record
        if spec.subject == "Alibaba Cloud":
            record["sources"].extend(ALIBABA_CLOUD_SOURCE_BY_PERIOD.values())
            record["unit"] = "millions CNY"
            record["quality_status"] = "official_cloud_segment_quarterly"
            record["disclosure_frequency"] = "quarterly_official_segment_table"
            record["periods"] = ALIBABA_CLOUD_PERIODS
            record["metrics"] = ALIBABA_CLOUD_METRICS
            record["quality_notes"].append(
                "Alibaba Cloud 使用 Alibaba 官方 Cloud Intelligence Group 分部口径；FY2026 Q4 对应截至 2026-03-31 的 March Quarter 2026。"
            )
            record["quality_notes"].append(
                "本轮先写入官方最新季度的 revenue、revenue_growth_yoy、adjusted_ebita 和 adjusted_ebita_growth_yoy；更早季度仍需继续从官方 PDF 或年报逐项抽取。"
            )
            return record
        if spec.subject == "Huawei Cloud / Cloud Computing":
            record["sources"].extend(HUAWEI_CLOUD_OFFICIAL_SOURCE_HINTS)
            record["unit"] = "status"
            record["quality_status"] = "source_gap"
            record["disclosure_frequency"] = "annual_official_cloud_segment_only"
            period = f"Quarterly source gap as of {BUILD_DATE}"
            record["periods"] = [
                {
                    "period": period,
                    "period_end": BUILD_DATE,
                    "grain": "source_gap",
                }
            ]
            record["metrics"] = {
                "cloud_quarterly_disclosure_status": {
                    period: (
                        "官方年报只披露年度 Cloud Computing 分部和含其他分部的云计算业务收入；"
                        "未发现可公开引用的季度/半年度 Huawei Cloud 收入或利润表，禁止估算季度云业务数据。"
                    )
                }
            }
            record["source_gap_source_label"] = "Huawei 2025 Annual Report quick view"
            record["source_gap_source_url"] = "https://www.huawei.com/en/annual-report/2025"
            record["source_gap_evidence"] = (
                "Huawei 2025 年报 By Business Segment 表列示 Cloud Computing 2025 年收入 32,161 百万元人民币、"
                "2024 年 33,325 百万元人民币、同比下降 3.5%；附注披露含其他分部的云计算业务收入为 72,075 百万元人民币。"
                "官方年报入口只列年度报告和历年年度报告，未提供季度/半年度云分部财务报表。"
            )
            record["source_gap_verification_note"] = (
                "官方 2025 年报确认 Huawei Cloud 只有年度 Cloud Computing 分部披露；"
                "本季度数据包不得将年度数拆分或估算为季度/半年度云收入。"
            )
            record["quality_notes"].append(
                "Huawei 为非上市公司，官方公开披露以年度报告为主；本包只记录季度披露缺口和年度云分部证据，不写入估算季度数据。"
            )
            return record
        record["quality_status"] = "cloud_segment_quarterly_extraction_pending"
        record["disclosure_frequency"] = "quarterly_or_periodic_official_segment_source_pending"
        record["periods"] = [
            {
                "period": f"Source entry as of {BUILD_DATE}",
                "period_end": BUILD_DATE,
                "grain": "source_entry",
            }
        ]
        record["metrics"] = {
            "cloud_segment_extraction_status": {
                f"Source entry as of {BUILD_DATE}": (
                    "官方披露入口已登记；云分部/代理口径季度表待逐项抽取，禁止用母公司总表替代。"
                )
            }
        }
        if record["sources"]:
            record["source_entry_source_label"] = record["sources"][0].get("label", "")
            record["source_entry_source_url"] = record["sources"][0].get("url", "")
            record["source_entry_evidence"] = (
                "已登记官方季度业绩、年报/中报或投资者关系入口；后续必须从 segment 或 product-line 表逐项抽取云业务口径。"
            )
        record["quality_notes"].append(
            "为避免误用母公司总收入，本包首版不写入云厂商母公司季度总表；后续只从官方 earnings release、10-Q、年报/中报的 segment 或 product-line 表抽取云分部/代理分部季度数据。"
        )
        return record
    if not spec.stockanalysis_slug:
        record["quality_notes"].append("无可自动抓取的公开标准化季度/半年度表；不得估算。")
        record["quality_status"] = "source_gap"
        if spec.subject == "HGC":
            record["sources"].extend(HGC_OFFICIAL_SOURCE_HINTS)
            record["disclosure_frequency"] = "not_publicly_disclosed"
            record["periods"] = [
                {
                    "period": f"Source gap as of {BUILD_DATE}",
                    "period_end": BUILD_DATE,
                    "grain": "source_gap",
                }
            ]
            record["metrics"] = {
                "financial_disclosure_status": {
                    f"Source gap as of {BUILD_DATE}": "未发现公开季度/半年度财务表；不得估算。"
                }
            }
            record["source_gap_source_label"] = "HGC company profile"
            record["source_gap_source_url"] = "https://www.hgc.com.hk/about-hgc/about-us/company-profile"
            record["source_gap_evidence"] = (
                "HGC官网确认其为 I Squared Capital 持有的非上市组合公司并披露业务范围；"
                "官网公开入口未提供季度/半年度财务报表。"
            )
            record["quality_notes"].append(
                "已核验 HGC 官网公司简介和主页；仅确认公司身份、业务范围和披露缺口，不写入任何估算财务数。"
            )
        return record
    try:
        metrics, periods, sources, unit = merge_stockanalysis_quarterly(spec, snapshot)
        record["metrics"] = {key: metrics.get(key, {}) for key in IMPORTANT_KEYS if metrics.get(key)}
        record["periods"] = periods
        record["unit"] = unit
        record["sources"].extend(sources)
        grains = {period.get("grain") for period in periods}
        if "quarter" in grains:
            record["disclosure_frequency"] = "quarterly_or_standardized_quarterly"
        elif "half_year" in grains:
            record["disclosure_frequency"] = "semiannual"
        else:
            record["disclosure_frequency"] = "periodic"
        record["quality_status"] = "standardized_online_source_with_official_crosscheck_required"
        record["quality_notes"].append(
            "结构化数值来自 StockAnalysis 在线季度/半年度标准化表；关键结论需用官方季报、业绩公告或年报逐项复核。"
        )
        if spec.category == "cloud":
            record["quality_notes"].append(
                "此记录仅用于发现可用季度披露入口；云厂商分部指标不得用母公司总表替代，必须在后续抽取官方 segment/product-line 表后才能作为云业务结论。"
            )
    except Exception as exc:
        record["quality_status"] = "fetch_failed"
        record["quality_notes"].append(f"在线季度表抓取失败：{exc}")
    return record


def flatten_rows(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for record in records:
        periods = {period["period"]: period for period in record.get("periods") or []}
        for metric_key, values in (record.get("metrics") or {}).items():
            for period, value in values.items():
                period_meta = periods.get(period, {})
                source_gap_sources = [
                    {
                        "label": item.get("label", ""),
                        "url": item.get("url", ""),
                        "type": item.get("type", ""),
                        "evidence": item.get("evidence", ""),
                    }
                    for item in (record.get("sources") or [])
                    if item.get("url")
                ]
                is_source_gap = record.get("quality_status") == "source_gap"
                is_cloud_pending = record.get("quality_status") == "cloud_segment_quarterly_extraction_pending"
                if is_source_gap:
                    verification_status = "source_gap_confirmed"
                    source_label = record.get("source_gap_source_label", "")
                    source_url = record.get("source_gap_source_url", "")
                    source_evidence = record.get("source_gap_evidence", "")
                    verification_count = len(source_gap_sources)
                    verification_method = "official_site_disclosure_gap_check"
                    verification_sources = json.dumps(source_gap_sources, ensure_ascii=False)
                    verification_note = record.get(
                        "source_gap_verification_note",
                        "官方站点确认公司身份、业务范围和非上市组合公司背景；未发现公开季度/半年度财务表入口，禁止估算。",
                    )
                elif is_cloud_pending:
                    verification_status = "official_source_registered"
                    source_label = record.get("source_entry_source_label", "")
                    source_url = record.get("source_entry_source_url", "")
                    source_evidence = record.get("source_entry_evidence", "")
                    verification_count = len(source_gap_sources)
                    verification_method = "official_source_entry_check"
                    verification_sources = json.dumps(source_gap_sources, ensure_ascii=False)
                    verification_note = "已登记官方披露入口；回答云收入、利润或季度趋势前，必须继续读取 segment/product-line 表逐项抽取，不得用母公司总表替代。"
                else:
                    verification_status = "needs_official_row_crosscheck"
                    source_label = ""
                    source_url = ""
                    source_evidence = ""
                    verification_count = 0
                    verification_method = ""
                    verification_sources = "[]"
                    verification_note = ""
                rows.append(
                    {
                        "subject": record["subject"],
                        "category": record["category"],
                        "legal_name": record["legal_name"],
                        "ticker": record.get("ticker") or "",
                        "period": period,
                        "period_end": period_meta.get("period_end", ""),
                        "grain": period_meta.get("grain", ""),
                        "metric_key": metric_key,
                        "metric_zh": METRIC_ZH_BY_KEY.get(metric_key, metric_key),
                        "value": value,
                        "unit": "percent" if metric_key in PERCENT_KEYS else record.get("unit", ""),
                        "disclosure_frequency": record.get("disclosure_frequency", ""),
                        "quality_status": record.get("quality_status", ""),
                        "verification_status": verification_status,
                        "official_value": "",
                        "official_unit": "",
                        "official_source_label": source_label,
                        "official_source_url": source_url,
                        "official_evidence": source_evidence,
                        "verification_count": verification_count,
                        "verification_method": verification_method,
                        "verification_sources": verification_sources,
                        "verification_note": verification_note,
                    }
                )
    rows.sort(key=lambda row: (row["category"], row["subject"], row["metric_key"], _period_sort_key(row["period"])))
    return rows


def _numeric_value(value: Any) -> float | None:
    text = str(value or "").strip()
    if not text or text in {"-", "—", "N/A", "n/a"}:
        return None
    negative = text.startswith("(") and text.endswith(")")
    text = text.strip("()").replace(",", "").replace("%", "")
    try:
        parsed = float(text)
    except ValueError:
        return None
    return -parsed if negative else parsed


def _official_match(row_value: Any, official_value: float) -> tuple[str, str]:
    parsed = _numeric_value(row_value)
    if parsed is None:
        return "official_conflict", "标准化表数值为空或无法解析，采用官方值。"
    diff = parsed - official_value
    tolerance = max(1.0, abs(official_value) * 0.002)
    if abs(diff) <= tolerance:
        return "official_match", f"标准化表与官方值一致，差异 {diff:.3f}。"
    return "official_conflict", f"标准化表 {parsed:g} 与官方值 {official_value:g} 不一致，差异 {diff:.3f}；正式回答应采用官方值并说明口径冲突。"


def apply_official_verifications(rows: list[dict[str, Any]], records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    index = {(row["subject"], row["period"], row["metric_key"]): row for row in rows}
    record_by_subject = {record["subject"]: record for record in records}
    official_rows: list[dict[str, Any]] = []
    for verification in OFFICIAL_VERIFICATIONS:
        verification_sources = _verification_sources_for_record(verification)
        verification_sources_json = json.dumps(verification_sources, ensure_ascii=False)
        key = (verification["subject"], verification["period"], verification["metric_key"])
        row = index.get(key)
        official_value = float(verification["official_value"])
        if row:
            status, note = _official_match(row.get("value"), official_value)
            row.update(
                {
                    "verification_status": status,
                    "official_value": verification["official_value"],
                    "official_unit": verification["unit"],
                    "official_source_label": verification["source_label"],
                    "official_source_url": verification["source_url"],
                    "official_evidence": verification["evidence"],
                    "verification_count": len(verification_sources),
                    "verification_method": verification.get("verification_method") or "official_source_row_check",
                    "verification_sources": verification_sources_json,
                    "verification_note": note,
                }
            )
            official_rows.append(row)
            continue

        record = record_by_subject.get(verification["subject"], {})
        periods = {period["period"]: period for period in record.get("periods") or []}
        period_meta = periods.get(verification["period"], {})
        official_only = {
            "subject": verification["subject"],
            "category": record.get("category", ""),
            "legal_name": record.get("legal_name", ""),
            "ticker": record.get("ticker") or "",
            "period": verification["period"],
            "period_end": period_meta.get("period_end") or _period_end_from_label(verification["period"]),
            "grain": period_meta.get("grain") or _period_grain(verification["period"]),
            "metric_key": verification["metric_key"],
            "metric_zh": METRIC_ZH_BY_KEY.get(verification["metric_key"], verification["metric_key"]),
            "value": verification["official_value"],
            "unit": verification["unit"],
            "disclosure_frequency": record.get("disclosure_frequency", ""),
            "quality_status": "official_only_metric",
            "verification_status": "official_only",
            "official_value": verification["official_value"],
            "official_unit": verification["unit"],
            "official_source_label": verification["source_label"],
            "official_source_url": verification["source_url"],
            "official_evidence": verification["evidence"],
            "verification_count": len(verification_sources),
            "verification_method": verification.get("verification_method") or "official_source_row_check",
            "verification_sources": verification_sources_json,
            "verification_note": "官方报告披露该口径，但标准化在线表未提供同名字段；作为官方独有口径补入。",
        }
        rows.append(official_only)
        official_rows.append(official_only)
    for confirmation in [
        *TOWER_SOURCE_GAP_CONFIRMATIONS,
        *TOWER_2016_DISCLOSURE_GAP_CONFIRMATIONS,
        *CU_SOURCE_GAP_CONFIRMATIONS,
        *CU_2016_2018_DISCLOSURE_GAP_CONFIRMATIONS,
        *CM_2021_SOURCE_GAP_CONFIRMATIONS,
        *CT_2021_SOURCE_GAP_CONFIRMATIONS,
        *CT_2022_SOURCE_GAP_CONFIRMATIONS,
        *CU_2021_2022_SOURCE_GAP_CONFIRMATIONS,
        *TOWER_2021_2022_SOURCE_GAP_CONFIRMATIONS,
        *ALIBABA_CLOUD_RESTATED_GROWTH_SOURCE_GAP_CONFIRMATIONS,
        *ALIBABA_CLOUD_PRE_RESTATED_CIG_SOURCE_GAP_CONFIRMATIONS,
        *TENCENT_FBS_PRE_DISCLOSURE_SOURCE_GAP_CONFIRMATIONS,
        *GOOGLE_CLOUD_PRE_QUARTERLY_SEGMENT_SOURCE_GAP_CONFIRMATIONS,
        *ORACLE_CLOUD_PRE_IASSAAS_SOURCE_GAP_CONFIRMATIONS,
    ]:
        key = (confirmation["subject"], confirmation["period"], confirmation["metric_key"])
        row = index.get(key)
        if not row:
            if not confirmation.get("append_if_missing"):
                continue
            record = record_by_subject.get(confirmation["subject"], {})
            periods = {period["period"]: period for period in record.get("periods") or []}
            period_meta = periods.get(confirmation["period"], {})
            row = {
                "subject": confirmation["subject"],
                "category": record.get("category", ""),
                "legal_name": record.get("legal_name", ""),
                "ticker": record.get("ticker") or "",
                "period": confirmation["period"],
                "period_end": period_meta.get("period_end") or _period_end_from_label(confirmation["period"]),
                "grain": period_meta.get("grain") or _period_grain(confirmation["period"]),
                "metric_key": confirmation["metric_key"],
                "metric_zh": METRIC_ZH_BY_KEY.get(confirmation["metric_key"], confirmation["metric_key"]),
                "value": "",
                "unit": "percent" if confirmation["metric_key"] in PERCENT_KEYS else record.get("unit", ""),
                "disclosure_frequency": record.get("disclosure_frequency", ""),
                "quality_status": "source_gap",
            }
            rows.append(row)
            index[key] = row
        verification_sources = _verification_sources_for_record(confirmation)
        row.update(
            {
                "verification_status": "source_gap_confirmed",
                "official_value": "",
                "official_unit": "",
                "official_source_label": confirmation["source_label"],
                "official_source_url": confirmation["source_url"],
                "official_evidence": confirmation["evidence"],
                "verification_count": len(verification_sources),
                "verification_method": confirmation["verification_method"],
                "verification_sources": json.dumps(verification_sources, ensure_ascii=False),
                "verification_note": confirmation["verification_note"],
            }
        )
        if row not in official_rows:
            official_rows.append(row)
    for row in rows:
        if row.get("verification_status") in {"source_gap_confirmed", "official_source_registered"} and row not in official_rows:
            official_rows.append(row)
    rows.sort(key=lambda row: (row["category"], row["subject"], row["metric_key"], _period_sort_key(row["period"])))
    return official_rows


def write_csv(rows: list[dict[str, Any]], path: Path) -> None:
    fields = [
        "subject",
        "category",
        "legal_name",
        "ticker",
        "period",
        "period_end",
        "grain",
        "metric_key",
        "metric_zh",
        "value",
        "unit",
        "disclosure_frequency",
        "quality_status",
        "verification_status",
        "official_value",
        "official_unit",
        "official_source_label",
        "official_source_url",
        "official_evidence",
        "verification_count",
        "verification_method",
        "verification_sources",
        "verification_note",
    ]
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def build_summary(records: list[dict[str, Any]], rows: list[dict[str, Any]]) -> str:
    lines = [
        f"# 季度/半年度竞对经营数据包（{BUILD_DATE}）",
        "",
        "本数据包把年度粒度拆到更小期间。可获得季度表的主体按季度列示；仅披露半年度的港股主体按 H1/H2 列示；没有公开季度/半年度完整表的主体只记录缺口，不估算。",
        "",
        "## 使用规则",
        "",
        "- `grain=quarter` 才能作为季度数据使用；`grain=half_year` 只能称为半年度数据。",
        "- `verification_status=needs_official_row_crosscheck` 的行只能作为标准化在线表线索，正式结论必须再读官方季报、业绩公告或年报。",
        "- 云厂商不得用母公司总收入替代云分部收入；本包先登记季度披露入口，云分部逐行数据需要从官方 segment/product-line 表继续抽取。",
        "",
        f"## 当前行数",
        "",
        f"- 结构化行：{len(rows)}",
        f"- 主体数：{len(records)}",
        "",
        "## 覆盖主体",
        "",
    ]
    for record in records:
        periods = record.get("periods") or []
        first_period = periods[0]["period"] if periods else "无"
        last_period = periods[-1]["period"] if periods else "无"
        lines.extend(
            [
                f"### {record['subject']}",
                "",
                f"- 类别：{record['category']}",
                f"- 主体：{record['legal_name']}",
                f"- 股票/状态：{record.get('ticker') or '未上市/未公开'}",
                f"- 披露粒度：{record.get('disclosure_frequency')}",
                f"- 覆盖期间：{first_period} 至 {last_period}",
                f"- 单位：{record.get('unit') or '未识别'}",
                f"- 质量状态：{record.get('quality_status')}",
            ]
        )
        if record.get("quality_notes"):
            lines.append("- 质量说明：" + "；".join(record["quality_notes"]))
        source_items = record.get("sources") or []
        if source_items:
            lines.append("- 主要来源：")
            for item in source_items[:6]:
                lines.append(f"  - {item.get('label')} ({item.get('type')}): {item.get('url')}")
        lines.append("")
    return "\n".join(lines).strip() + "\n"


def write_readme(path: Path) -> None:
    text = f"""# {DATASET_ID}

供小竞 AI 使用的季度/半年度竞对经营数据包。

## 文件

- `quarterly_metrics_summary.md`：数据包说明、覆盖主体、披露粒度和来源。
- `quarterly_metrics.json`：结构化数据，包含主体、期间、指标、来源和质量状态。
- `quarterly_metrics.csv`：长表，适合 Agent 做趋势、图表和筛选。
- `quarterly_metrics_human_readable.csv`：人工查看精简宽表。
- `sources.json`：来源清单。
- `official_verified_metrics_{BUILD_DATE}.csv`：已完成官方公告交叉核验的明细，包含官方值、来源链接、证据句和冲突说明。
- `online_verification_{BUILD_DATE}.md`：核验状态说明。
- `online_verification_{BUILD_DATE}.csv`：逐行核验状态。
- `prediction_history_coverage_{BUILD_DATE}.md` / `.csv`：7年/10年预测历史窗口覆盖缺口审计。
- `prediction_history_source_plan_{BUILD_DATE}.md`：下一轮补 2016-2024 历史数据的来源入口、优先级和验收门禁。

## Agent 使用要求

1. 用户问“季度”“Q1/Q2/Q3/Q4”“更小计量单位”“半年度”“最近几个季度”时，优先读取本目录。
2. 必须区分 `grain=quarter` 和 `grain=half_year`；不能把 H1/H2 说成季度。
3. `official_match` 可以作为已核验事实使用；`official_conflict` 必须采用 `official_value` 并说明标准化表与官方披露存在口径冲突；`official_only` 是官方报告独有口径。
4. `source_gap_confirmed` 表示已核验官方站点但未发现公开季度/半年度财务表，只能回答披露缺口，禁止估算财务数。
5. `official_source_registered` 表示已登记官方披露入口，但尚未从 segment/product-line 表逐项抽取数值，不能当作云业务数据结论。
6. `verification_count>=2` 才表示已用多个官方页面或披露文件复核；具体链接和证据保存在 `verification_sources`。
7. 对 `verification_status=needs_official_row_crosscheck` 的行，回答前必须再用联网搜索或本地官方来源核验关键数。
8. 云厂商分部数据不得使用母公司总表替代；如果本包只给出来源入口或母公司总表线索，必须说明不能直接作为云收入结论。
9. 回答 7年/10年覆盖、预测准备度或还缺哪些历史期间时，优先读取 `prediction_history_coverage_{BUILD_DATE}.*` 和 `prediction_history_source_plan_{BUILD_DATE}.md`。
"""
    path.write_text(text, encoding="utf-8")


def build_verification(records: list[dict[str, Any]], rows: list[dict[str, Any]], official_rows: list[dict[str, Any]]) -> str:
    status_counts: dict[str, int] = {}
    for row in rows:
        status_counts[row.get("verification_status") or "unknown"] = status_counts.get(row.get("verification_status") or "unknown", 0) + 1
    official_match = status_counts.get("official_match", 0)
    official_conflict = status_counts.get("official_conflict", 0)
    official_only = status_counts.get("official_only", 0)
    lines = [
        f"# 季度/半年度数据核验状态（{BUILD_DATE}）",
        "",
        "本文件记录当前季度包的核验边界。已完成在线标准化季度/半年度表抓取、官方来源入口登记，并开始把官方公告逐项交叉核验写回数据行。",
        "",
        "## 当前判断",
        "",
        "- 中国移动、中国电信、中国联通、中国铁塔：2026Q1 首批关键指标已用官方一季报、上交所公告或港交所/IRAsia 公告交叉核验。",
        "- 中国移动 2025Q2：收入、通信服务收入、EBITDA、归母净利润、经营现金流和现金流口径资本开支已用官网单季度数据、港交所中报和上交所Q1报告做多源复算；发现标准化表 EBITDA 和通信服务收入与官方值冲突。",
        "- 中国移动 2025Q3：9项关键指标已用官网单季度表、港交所前三季度公告、公司官网公告镜像和中报复核；标准化表的通信服务收入和 EBITDA 与官方复算值冲突。",
        "- 中国移动 2025Q4：8项关键指标已用年报/全年业绩材料、港交所前三季度公告和中文公告摘要复核；标准化表的主营业务收入、EBITDA、现金及现金等价物与官方复算/时点值冲突。",
        "- 中国联通：当前官方核验采用 600050 A 股一季报口径；如问题要求 0762.HK 红筹公司纯口径，仍需读取中国联通香港官网 FAQ 或公告交叉确认。",
        "- HKT、3HK、SmarTone、HKBN、i-CABLE：公开披露更接近半年度/年度，数据包按 H1/H2 标记，不称为季度。",
        "- HGC：非上市主体，未发现公开完整季度/半年度财务表。",
        "- 云厂商：需要从官方 earnings release、10-Q、半年报或年报 segment/product-line 表抽取云分部；不能用母公司季度总表替代。",
        "",
        "## 核验状态计数",
        "",
        f"- official_match: {official_match}",
        f"- official_conflict: {official_conflict}",
        f"- official_only: {official_only}",
        f"- source_gap_confirmed: {status_counts.get('source_gap_confirmed', 0)}",
        f"- official_source_registered: {status_counts.get('official_source_registered', 0)}",
        f"- needs_official_row_crosscheck: {status_counts.get('needs_official_row_crosscheck', 0)}",
        "",
        "## 已发现口径冲突",
        "",
    ]
    conflicts = [row for row in official_rows if row.get("verification_status") == "official_conflict"]
    if not conflicts:
        lines.append("- 暂无。")
    for row in conflicts:
        lines.append(
            f"- {row['subject']} {row['period']} {row['metric_zh']}：标准化表 `{row['value']}`，官方值 `{row['official_value']} {row['official_unit']}`。{row['verification_note']} 来源：{row['official_source_url']}"
        )
    source_registered_rows = [row for row in rows if row.get("verification_status") == "official_source_registered"]
    if source_registered_rows:
        lines.extend(
            [
                "",
                "## 云厂商官方入口登记",
                "",
                "以下记录只表示官方披露入口已登记，不能直接作为云业务收入、利润或季度趋势结论；回答前必须继续读取对应入口中的 segment/product-line 表。",
                "",
            ]
        )
        for row in source_registered_rows:
            lines.append(
                f"- {row['subject']}：{row['value']} 来源：{row.get('official_source_label')} {row.get('official_source_url')}"
            )
    lines.extend(
        [
            "",
            "## 已完成官方核验来源",
            "",
        ]
    )
    source_seen = set()
    for row in official_rows:
        key = (row.get("official_source_label"), row.get("official_source_url"))
        if key in source_seen:
            continue
        source_seen.add(key)
        lines.append(f"- {row.get('official_source_label')}: {row.get('official_source_url')}")
    return "\n".join(lines)


def write_verification_csv(rows: list[dict[str, Any]], path: Path) -> None:
    fields = ["row_no", *list(rows[0].keys())] if rows else ["row_no"]
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        for index, row in enumerate(rows, 1):
            writer.writerow({"row_no": index, **row})


def write_human_readable(rows: list[dict[str, Any]], path: Path) -> None:
    fields = [
        "subject",
        "period",
        "grain",
        "metric_zh",
        "value",
        "unit",
        "verification_status",
        "official_value",
        "official_unit",
        "verification_count",
        "verification_method",
        "official_source_url",
        "verification_note",
    ]
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in fields})


def write_manifest(path: Path, row_count: int) -> None:
    manifest = {
        "id": DATASET_ID,
        "title": f"竞对主体和重点云厂商季度/半年度经营数据包（{BUILD_DATE}）",
        "summary": "把原年度数据拆到 5 年季度或半年度粒度；覆盖主要运营商竞对和重点云厂商的可用期间数据、来源入口和核验状态。",
        "source_type": "external_standardized_and_official_public",
        "scope": "季度/半年度财务表、官方季报/中报/年报/业绩公告；云厂商分部数据需官方 segment/product-line 表核验。",
        "tags": ["quarterly", "half_year", "carrier", "cloud", "financial_metrics", "verification"],
        "keywords": [
            "季度",
            "半年度",
            "Q1",
            "Q2",
            "Q3",
            "Q4",
            "H1",
            "H2",
            "收入",
            "净利润",
            "毛利率",
            "EBITDA",
            "资本开支",
            "云收入",
            "AWS",
            "Azure",
            "Google Cloud",
            "Alibaba Cloud",
            "Tencent Cloud",
            "Tencent FBS",
            "Huawei Cloud",
            "Oracle Cloud",
            "中国移动",
            "中国电信",
            "中国联通",
            "中国铁塔",
            "HKT",
            "csl",
            "1O1O",
            "3HK",
            "Hutchison",
            "SmarTone",
            "HKBN",
            "HGC",
            "i-CABLE",
            "source_gap_confirmed",
            "official_source_registered",
            "cloud_segment_extraction_status",
        ],
        "entrypoints": [
            "README.md",
            "quarterly_metrics_summary.md",
            "quarterly_metrics.json",
            "quarterly_metrics.csv",
            "quarterly_metrics_human_readable.csv",
            "sources.json",
            f"official_verified_metrics_{BUILD_DATE}.csv",
            f"online_verification_{BUILD_DATE}.md",
            f"online_verification_{BUILD_DATE}.csv",
            f"prediction_history_coverage_{BUILD_DATE}.md",
            f"prediction_history_coverage_{BUILD_DATE}.csv",
            f"prediction_history_source_plan_{BUILD_DATE}.md",
            f"cloud_source_gap_integrity_{BUILD_DATE}.md",
            f"cloud_source_gap_integrity_{BUILD_DATE}.csv",
        ],
        "updated_at": datetime.now().isoformat(timespec="seconds"),
        "quality": {
            "status": "official_verified_with_documented_source_gaps",
            "row_count": row_count,
            "notes": [
                "全表保留 official_value、verification_status、verification_count 字段。",
                "当前严格审计显示 verification_count < 2 为 0。",
                "不估算缺失季度或半年度。",
                "半年度披露主体必须标记为 half_year。",
                "HGC 等非上市主体若未发现公开周期财务表，只登记 source_gap_confirmed，不估算。",
                "云厂商缺失季度以 documented source gap、annual-only 或 non-forecast legacy 口径登记，不计入预测值覆盖。",
            ],
        },
    }
    path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")


def existing_row_count(path: Path) -> int:
    if not path.exists():
        return 0
    with path.open(encoding="utf-8-sig", newline="") as f:
        return sum(1 for _ in csv.DictReader(f))


def enforce_non_degraded_publish(rows: list[dict[str, Any]], out_root: Path = OUT_ROOT) -> None:
    previous_count = existing_row_count(out_root / "quarterly_metrics.csv")
    if previous_count and len(rows) < previous_count and os.environ.get("CMHK_ALLOW_DEGRADED_QUARTERLY_BUILD") != "1":
        raise RuntimeError(
            f"拒绝发布降级季度数据包：新包 {len(rows)} 行，现有包 {previous_count} 行。"
            "如确认需要覆盖，请显式设置 CMHK_ALLOW_DEGRADED_QUARTERLY_BUILD=1。"
        )


def publish_staged_dataset(stage_root: Path, out_root: Path = OUT_ROOT) -> None:
    backup = out_root.with_name(f".{out_root.name}.backup")
    if backup.exists():
        shutil.rmtree(backup)
    moved_old = False
    try:
        if out_root.exists():
            os.replace(out_root, backup)
            moved_old = True
        os.replace(stage_root, out_root)
    except Exception:
        if moved_old and backup.exists() and not out_root.exists():
            os.replace(backup, out_root)
        raise
    if backup.exists():
        shutil.rmtree(backup)


def main() -> None:
    official_sources = load_official_sources()
    snapshot = load_stockanalysis_snapshot()
    records = [build_subject_record(spec, official_sources, snapshot) for spec in [*CORE_SUBJECTS, *CLOUD_SUBJECTS]]
    rows = flatten_rows(records)
    official_rows = apply_official_verifications(rows, records)
    enforce_non_degraded_publish(rows)
    sources = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "sources_by_subject": {record["subject"]: record.get("sources") or [] for record in records},
        "quality_notes_by_subject": {record["subject"]: record.get("quality_notes") or [] for record in records},
    }
    payload = {
        "dataset_id": DATASET_ID,
        "generated_at": sources["generated_at"],
        "period_scope": "2021 onward; quarter where disclosed, half-year where quarterly disclosure is unavailable",
        "subjects": records,
        "rows": rows,
    }
    OUT_ROOT.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=f".{DATASET_ID}.", dir=OUT_ROOT.parent) as temp_dir:
        stage_root = Path(temp_dir) / DATASET_ID
        stage_root.mkdir(parents=True)
        (stage_root / "quarterly_metrics.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        write_csv(rows, stage_root / "quarterly_metrics.csv")
        write_human_readable(rows, stage_root / "quarterly_metrics_human_readable.csv")
        (stage_root / "sources.json").write_text(json.dumps(sources, ensure_ascii=False, indent=2), encoding="utf-8")
        (stage_root / "quarterly_metrics_summary.md").write_text(build_summary(records, rows), encoding="utf-8")
        write_verification_csv(official_rows, stage_root / f"official_verified_metrics_{BUILD_DATE}.csv")
        (stage_root / f"online_verification_{BUILD_DATE}.md").write_text(build_verification(records, rows, official_rows), encoding="utf-8")
        write_verification_csv(rows, stage_root / f"online_verification_{BUILD_DATE}.csv")
        write_readme(stage_root / "README.md")
        write_manifest(stage_root / "manifest.json", len(rows))
        if OUT_ROOT.exists():
            for pattern in (f"prediction_history_*_{BUILD_DATE}.*", f"cloud_source_gap_integrity_{BUILD_DATE}.*"):
                for extra_path in OUT_ROOT.glob(pattern):
                    if extra_path.is_file():
                        shutil.copy2(extra_path, stage_root / extra_path.name)
        publish_staged_dataset(stage_root)
    print(f"Wrote {OUT_ROOT}")
    print(f"Rows: {len(rows)}")


if __name__ == "__main__":
    main()
