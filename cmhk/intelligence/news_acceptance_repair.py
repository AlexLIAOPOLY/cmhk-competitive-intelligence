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
            scope = ids
            if draft is not None and _partition(draft, ids):
                implicated = {n for n in ids if n in error}
                if implicated:
                    # Include entire intersecting groups so a split cannot orphan members.
                    scope = {n for g in draft["event_groups"]
                             if implicated.intersection(g["news_ids"]) for n in g["news_ids"]}
            scope_key = hashlib.sha256(json.dumps(sorted(scope)).encode()).hexdigest()
            scope_attempts = state.setdefault("scope_attempts", {})
            if (int(state.get("requests", 0)) >= MAX_REQUESTS
                    or int(scope_attempts.get(scope_key, 0)) >= MAX_SCOPE_REQUESTS):
                block(error or "接受复核未返回完整结果")
            scope_attempts[scope_key] = int(scope_attempts.get(scope_key, 0)) + 1
            state.update(requests=int(state.get("requests", 0)) + 1,
                         status="repairing" if draft else "reviewing", last_error=error)
            save()  # Crashes and network failures cannot reset the call budget.
            subset = [t for t in targets if t["news_id"] in scope]
            session["acceptance_review"] = [t for t in provisional if t["news_id"] in scope]
            session["quality_feedback"] = (
                f"{prior_feedback or ''} 具体校验问题：{error}。本次只复核所给候选。"
                "同场大会的不同产品、投资计划和独立项目必须分别分组。"
                "同一具体事件每个字段只能接受一个代表，其他重复项不接受并指向代表；"
                "先选代表再填写逐条状态，检查两者完全一致。不能确认重复则分开；不得凑数量。"
            ) if draft is not None else prior_feedback
            if session.get("request_callback") and draft is not None:
                session["request_callback"](
                    f"接受复核局部修复：{error}；仅复核 {len(subset)} 条，"
                    f"保留其他组；本范围第 {scope_attempts[scope_key]}/{MAX_SCOPE_REQUESTS} 次。")
            replacement, replacement_model = invoke(examples, subset)
            if scope == ids:
                draft, model = replacement, replacement_model
            elif _partition(replacement, scope):
                rows = replacement.get("decisions", [])
                replacement_ids = [r.get("news_id") for r in rows if isinstance(r, dict)] if isinstance(rows, list) else []
                if len(replacement_ids) != len(scope) or set(replacement_ids) != scope:
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
