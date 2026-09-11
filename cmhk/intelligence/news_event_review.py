"""Expand a model's one representative per event/field into equivalent row states."""
from __future__ import annotations


def expand_event_review(payload, targets, provisional):
    if "decisions" in payload:
        raise ValueError("接受复核不能同时提供事件代表与逐条decisions，存在双重结论歧义")
    groups = payload.get("event_groups")
    if not isinstance(groups, list) or not groups:
        raise ValueError("接受复核缺少全批事件分组")
    by_id = {t["news_id"]: t for t in targets}
    initial = {p["news_id"]: p for p in provisional}
    rows, seen, expanded_groups = [], set(), []
    for group in groups:
        if not isinstance(group, dict) or not isinstance(group.get("event"), str) or not group["event"].strip():
            raise ValueError("接受复核事件分组缺少具体事件")
        members = group.get("news_ids")
        if not isinstance(members, list) or not members:
            raise ValueError("接受复核事件分组缺少候选")
        for news_id in members:
            if not isinstance(news_id, str) or news_id not in by_id or news_id in seen:
                raise ValueError(f"接受复核事件分组含未知或重复候选 {news_id}")
            seen.add(news_id)
        outcomes = {}
        for field in ("app", "weekly"):
            outcome = group.get(field)
            context = f"{'、'.join(members)}/{field}"
            if not isinstance(outcome, dict) or "accept_id" not in outcome:
                raise ValueError(f"接受复核缺少唯一代表accept_id或null {context}")
            if any(k in outcome for k in ("status", "app_status", "weekly_status", "duplicate_of")):
                raise ValueError(f"接受复核字段只能用accept_id表达结论，不能附加状态或重复指向 {context}")
            representative = outcome["accept_id"]
            if representative is not None:
                if not isinstance(representative, str) or not representative:
                    raise ValueError(f"接受复核代表必须是单个候选ID或null {context}")
                if representative not in by_id:
                    raise ValueError(f"接受复核代表是未知候选 {representative} {context}")
                if representative not in members:
                    raise ValueError(f"接受复核代表必须属于同一事件组 {representative} {context}")
                if (by_id[representative].get(f"{field}_before") != "待审核"
                        or initial.get(representative, {}).get(f"{field}_status") != "接受"):
                    raise ValueError(f"接受复核不得新增原不接受或人工字段的接受代表 {representative}/{field}")
            if not isinstance(outcome.get("reason"), str) or not outcome["reason"].strip():
                raise ValueError(f"接受复核缺少独立字段理由 {context}")
            outcomes[field] = outcome
        expanded_groups.append({"event": group["event"], "news_ids": list(members)})
        for news_id in members:
            row = {"news_id": news_id,
                   "reason": f"APP：{outcomes['app']['reason']}；周报：{outcomes['weekly']['reason']}"}
            for field, outcome in outcomes.items():
                representative = outcome["accept_id"]
                eligible = (by_id[news_id].get(f"{field}_before") == "待审核"
                            and initial.get(news_id, {}).get(f"{field}_status") == "接受")
                selected = eligible and representative == news_id
                duplicate = eligible and representative is not None and not selected
                row.update({
                    f"{field}_status": "接受" if selected else "不接受",
                    f"{field}_confidence": outcome.get("confidence", 0),
                    f"{field}_reason": ("同一事件重复，采用模型指定代表；" if duplicate else "") + outcome["reason"],
                    f"{field}_duplicate_of": representative if duplicate else "",
                    f"{field}_evidence": outcome.get("evidence", "") if selected else "",
                    f"{field}_impact": outcome.get("impact", "") if selected else "",
                    f"{field}_signal": outcome.get("signal", "") if selected else "",
                })
            rows.append(row)
    if seen != set(by_id):
        raise ValueError("接受复核事件分组遗漏候选")
    return {"event_groups": expanded_groups, "decisions": rows}
