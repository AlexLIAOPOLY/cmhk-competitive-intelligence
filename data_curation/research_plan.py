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
    ResearchAssignment("hong-kong", "香港运营商研究 Agent", "仅研究主页香港运营商指标", (
        "CMHK", "HKT", "SmarTone", "3HK", "HKBN", "HGC", "i-CABLE")),
    ResearchAssignment("mainland", "内地运营商研究 Agent", "研究内地运营商及铁塔公司的经营指标和最新披露", (
        "中国移动", "中国电信", "中国联通", "中国铁塔", "中国广电")),
    ResearchAssignment("asia-pacific", "亚太运营商研究 Agent", "研究亚太运营商的业绩、用户规模和网络投入", (
        "Singtel", "Telstra", "SK Telecom", "KT", "NTT Docomo", "KDDI", "SoftBank", "Bharti Airtel", "Reliance Jio", "NTT")),
    ResearchAssignment("europe", "欧洲运营商研究 Agent", "研究欧洲运营商的收入、利润、用户和资本开支", (
        "Vodafone", "Deutsche Telekom", "Orange", "Telefonica", "BT", "TIM")),
    ResearchAssignment("americas-middle-east", "美洲与中东运营商研究 Agent", "研究美国与中东运营商的最新业绩及经营变化", (
        "Verizon", "AT&T", "T-Mobile US", "e&", "stc")),
    ResearchAssignment("cloud", "全球云厂商研究 Agent", "仅研究主页云收入、经营利润和资本开支，保留分部口径", (
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


def frontend_metric_plan() -> dict[str, list[str]]:
    """Use the current dashboard focus definitions, including their subject scope."""
    from cmhk.intelligence.executive import build_executive_intelligence_snapshot
    labels = {"营收": "收入", "移动ARPU": "ARPU", "云利润": "经营利润"}
    return {
        domain["id"]: list(dict.fromkeys(labels.get(focus["label"], focus["label"])
                                        for focus in domain.get("focuses", [])))
        for domain in build_executive_intelligence_snapshot()["domains"]
        if domain["id"] in {"local", "international", "mainland", "cloud"}
    }


def company_metric_plan(company: str, plan: dict | None = None) -> list[str]:
    """Homepage focuses are the exclusive research allowlist; fail closed."""
    task = next((task for task in ASSIGNMENTS if company in task.companies), None)
    if task is None:
        return []
    domain = {"hong-kong": "local", "mainland": "mainland", "cloud": "cloud"}.get(task.key, "international")
    return list((frontend_metric_plan() if plan is None else plan).get(domain, []))


def restrict_report_metrics(report: dict, allowed: list[str], *, reopen_missing: bool = True) -> None:
    """Old checkpoints cannot reintroduce removed topics into active work."""
    report["metrics"] = allowed
    report["items"] = [item for item in report.get("items", []) if item.get("metric") in allowed]
    if "reviewed_metrics" in report:
        report["reviewed_metrics"] = [m for m in report["reviewed_metrics"] if m in allowed]
    if reopen_missing and set(allowed) - {item.get("metric") for item in report["items"]}:
        report["status"] = "running"
