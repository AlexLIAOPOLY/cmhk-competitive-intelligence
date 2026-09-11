"""Repair only conflicting event groups; unvalidated drafts can never be written."""
from __future__ import annotations

import hashlib
import json


MAX_REQUESTS = 12
MAX_SCOPE_REQUESTS = 3


def _partition(payload, ids):
    groups = payload.get("event_groups", []) if isinstance(payload, dict) else []
    if not isinstance(groups, list) or not groups or any(
        not isinstance(g, dict) or not isinstance(g.get("news_ids"), list)
        or any(not isinstance(n, str) for n in g["news_ids"]) for g in groups
    ):
        return False
    members = [n for g in groups for n in g["news_ids"]]
    return bool(groups) and len(members) == len(ids) and set(members) == ids


def _invalid_groups(draft, targets, provisional, validate):
    """Collect every invalid group without altering any model decision."""
    rows = draft.get("decisions")
    ids = {t["news_id"] for t in targets}
    if (not _partition(draft, ids) or not isinstance(rows, list)
            or any(not isinstance(r, dict) for r in rows)):
        return []
    row_ids = [r.get("news_id") for r in rows]
    if len(row_ids) != len(ids) or any(not isinstance(n, str) for n in row_ids) or set(row_ids) != ids:
        return []
    issues = []
    for group in draft["event_groups"]:
        members = set(group["news_ids"])
        try:
            validate({"event_groups": [group],
                      "decisions": [r for r in rows if r["news_id"] in members]},
                     [t for t in targets if t["news_id"] in members],
                     [p for p in provisional if p["news_id"] in members])
        except ValueError as exc:
            issues.append({"news_ids": list(group["news_ids"]),
                           "error": str(exc.__cause__ or exc)})
    return issues


def repair_review(examples, targets, provisional, *, cached, checkpoint,
                  checkpoint_key, checkpoint_callback, session, invoke, validate,
                  blocked_error):
    """Persist budgets before inference, retain valid groups across process restarts."""
    if cached.get("payload"):
        validate(cached["payload"], targets, provisional)
        return cached["payload"], cached["model"]
    key = checkpoint_key + ":repair"
    state = dict((checkpoint or {}).get(key, {}))
    ids = {t["news_id"] for t in targets}
    draft, model = state.get("draft"), state.get("model", "")
    prior_feedback = session.get("quality_feedback")
    original_review = session.get("acceptance_review")
    original_repair = session.get("acceptance_review_repair")

    def save():
        if checkpoint is not None:
            checkpoint[key] = state
            if checkpoint_callback:
                checkpoint_callback(0, 0, 0)

    def block(reason):
        state.update(status="needs_review", blocked=True, last_error=reason)
        save()
        raise blocked_error("接受复核已停止自动重试：" + reason)

    if state.get("blocked"):
        block(state.get("last_error") or "同一输入的修复次数已用尽")
    try:
        while True:
            error = state.get("last_error", "")
            if draft is not None:
                try:
                    validate(draft, targets, provisional)
                    state.update(status="validated", draft=draft, model=model, last_error="")
                    save()
                    return draft, model
                except ValueError as exc:
                    error = str(exc.__cause__ or exc)
            issues = _invalid_groups(draft, targets, provisional, validate) if isinstance(draft, dict) else []
            # Repair all bad groups together; the first validation error must not
            # force a separate request for every duplicate pair in a large batch.
            scope = {n for issue in issues for n in issue["news_ids"]} if issues else ids
            scope_key = hashlib.sha256(json.dumps(sorted(scope)).encode()).hexdigest()
            scope_attempts = state.setdefault("scope_attempts", {})
            news_attempts = state.setdefault("news_attempts", {})
            if (int(state.get("requests", 0)) >= MAX_REQUESTS
                    or int(scope_attempts.get(scope_key, 0)) >= MAX_SCOPE_REQUESTS
                    or any(int(news_attempts.get(n, 0)) >= MAX_SCOPE_REQUESTS for n in scope)):
                block(error or "接受复核未返回完整结果")
            scope_attempts[scope_key] = int(scope_attempts.get(scope_key, 0)) + 1
            for news_id in scope:
                news_attempts[news_id] = int(news_attempts.get(news_id, 0)) + 1
            state.update(requests=int(state.get("requests", 0)) + 1,
                         status="repairing" if draft else "reviewing", last_error=error,
                         validation_issues=issues)
            save()  # Crashes and network failures cannot reset the call budget.
            subset = [t for t in targets if t["news_id"] in scope]
            session["acceptance_review"] = [t for t in provisional if t["news_id"] in scope]
            session["acceptance_review_repair"] = {
                "validation_issues": issues or [{"news_ids": sorted(scope), "error": error}],
                "unvalidated_draft": {
                    "event_groups": [g for g in draft["event_groups"] if scope.intersection(g["news_ids"])],
                    "decisions": [r for r in draft["decisions"] if r["news_id"] in scope],
                } if issues else draft,
            } if draft is not None else None
            session["quality_feedback"] = (
                f"{prior_feedback or ''} 具体校验问题：{error}。本次只复核所给候选。"
                "同场大会的不同产品、投资计划和独立项目必须分别分组。"
                "同一具体事件每个字段只能接受一个代表，其他重复项不接受并指向代表；"
                "acceptance_review_repair包含未通过校验的草稿和逐组错误，不是已确认结论。"
                "逐条修正后重新输出完整的本范围结果，不能照抄原拟接受状态。"
                "每个问题组同时检查APP和周报两字段，不能只修正首个报错字段。"
                "字段不接受且同组没有该字段的接受代表时，duplicate_of必须为空。"
                "若app_duplicate_of非空，app_status必须是不接受；weekly同理。"
                "先选代表再填写逐条状态，检查两者完全一致。不能确认重复则分开；不得凑数量。"
            ) if draft is not None else prior_feedback
            if session.get("request_callback") and draft is not None:
                session["request_callback"](
                    f"接受复核局部修复：{error}；仅复核 {len(subset)} 条，"
                    f"合并处理 {len(issues)} 个问题组，保留其他组；"
                    f"本范围第 {scope_attempts[scope_key]}/{MAX_SCOPE_REQUESTS} 次。")
            replacement, replacement_model = invoke(examples, subset)
            if scope == ids:
                draft, model = replacement, replacement_model
            elif _partition(replacement, scope):
                rows = replacement.get("decisions", [])
                replacement_ids = [r.get("news_id") for r in rows if isinstance(r, dict)] if isinstance(rows, list) else []
                if (len(replacement_ids) != len(scope)
                        or any(not isinstance(n, str) for n in replacement_ids)
                        or set(replacement_ids) != scope):
                    state["last_error"] = error
                    save()
                    continue
                draft = {**draft,
                         "event_groups": [g for g in draft["event_groups"]
                                          if not scope.intersection(g["news_ids"])] + replacement["event_groups"],
                         "decisions": [r for r in draft["decisions"] if r["news_id"] not in scope]
                                      + replacement["decisions"]}
                model = replacement_model
            else:
                # An invalid replacement is never allowed to erase unrelated progress.
                save()
                continue
            state.update(draft=draft, model=model)
            save()
    finally:
        session["acceptance_review"] = original_review
        session["quality_feedback"] = prior_feedback
        if original_repair is None:
            session.pop("acceptance_review_repair", None)
        else:
            session["acceptance_review_repair"] = original_repair
