"""The six research assignments shared by execution, API and the process diagram.

Companies are work items, never child agents. Adding a company requires an
explicit assignment so the scheduler cannot silently create a seventh agent.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass


ARCHITECTURE_VERSION = "six_research_agents_v1"


@dataclass(frozen=True)
class ResearchAssignment:
    key: str
    title: str
    purpose: str
    companies: tuple[str, ...]


ASSIGNMENTS = (
    ResearchAssignment("hong-kong", "香港运营商研究 Agent", "研究香港运营商经营业绩、用户、网络及产品资费", (
        "CMHK", "HKT", "SmarTone", "3HK", "HKBN", "HGC", "i-CABLE")),
    ResearchAssignment("mainland", "内地运营商研究 Agent", "研究内地运营商及铁塔公司的经营指标和最新披露", (
        "中国移动", "中国电信", "中国联通", "中国铁塔", "中国广电")),
    ResearchAssignment("asia-pacific", "亚太运营商研究 Agent", "研究亚太运营商的业绩、用户规模和网络投入", (
        "Singtel", "Telstra", "SK Telecom", "KT", "NTT Docomo", "KDDI", "SoftBank", "Bharti Airtel", "Reliance Jio", "NTT")),
    ResearchAssignment("europe", "欧洲运营商研究 Agent", "研究欧洲运营商的收入、利润、用户和资本开支", (
        "Vodafone", "Deutsche Telekom", "Orange", "Telefonica", "BT", "TIM")),
    ResearchAssignment("americas-middle-east", "美洲与中东运营商研究 Agent", "研究美国与中东运营商的最新业绩及经营变化", (
        "Verizon", "AT&T", "T-Mobile US", "e&", "stc")),
    ResearchAssignment("cloud", "全球云厂商研究 Agent", "研究云收入、增长、利润、订单和资本开支，保留分部口径", (
        "AWS", "Microsoft Azure", "Google Cloud", "Alibaba Cloud", "Tencent Cloud", "Huawei Cloud", "Oracle Cloud", "China Mobile Cloud")),
)


def research_plan() -> list[dict]:
    from crawl import ALL_COMPANY_CURRENT_RESULT_TARGETS
    assigned = [company for task in ASSIGNMENTS for company in task.companies]
    if len(ASSIGNMENTS) > 6 or len(assigned) != len(set(assigned)):
        raise ValueError("研究任务必须由最多六个 Agent 承担，且公司不能重复派发")
    if set(assigned) != set(ALL_COMPANY_CURRENT_RESULT_TARGETS):
        raise ValueError("研究任务分工与当前公司目录不一致，请补齐明确的任务归属")
    return [asdict(task) for task in ASSIGNMENTS]
