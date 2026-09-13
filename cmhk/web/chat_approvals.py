from __future__ import annotations

from ._binding import publish


def bind(app) -> None:
    """Bind this domain to the existing application and its shared state."""
    def _chat_approval_key(request_id: str, action_id: str) -> tuple[str, str]:
        return (str(request_id or "")[:160], str(action_id or "")[:240])

    publish(app, _chat_approval_key)

    def register_chat_approval(request_id: str, action_id: str) -> None:
        key = app._chat_approval_key(request_id, action_id)
        with app.CHAT_APPROVAL_LOCK:
            app.CHAT_APPROVAL_WAITERS[key] = {"event": app.threading.Event(), "decision": ""}

    publish(app, register_chat_approval)

    def resolve_chat_approval(request_id: str, action_id: str, decision: str) -> bool:
        key = app._chat_approval_key(request_id, action_id)
        normalized = "allow" if decision == "allow" else "deny"
        with app.CHAT_APPROVAL_LOCK:
            waiter = app.CHAT_APPROVAL_WAITERS.get(key)
            if not waiter:
                return False
            waiter["decision"] = normalized
            signal = waiter.get("event")
        if isinstance(signal, app.threading.Event):
            signal.set()
        return True

    publish(app, resolve_chat_approval)

    def wait_for_chat_approval(request_id: str, action_id: str) -> str:
        key = app._chat_approval_key(request_id, action_id)
        with app.CHAT_APPROVAL_LOCK:
            waiter = app.CHAT_APPROVAL_WAITERS.get(key)
        if not waiter:
            return "deny"
        signal = waiter.get("event")
        if isinstance(signal, app.threading.Event):
            signal.wait()
        with app.CHAT_APPROVAL_LOCK:
            resolved = app.CHAT_APPROVAL_WAITERS.pop(key, waiter)
        return "allow" if resolved.get("decision") == "allow" else "deny"

    publish(app, wait_for_chat_approval)

    def stream_agent_with_approvals(
        message: str,
        *,
        request_id: str,
        approved_action_ids: list[str] | None = None,
        decision_waiter=app.wait_for_chat_approval,
        agent_factory=app.stream_agent,
        **agent_kwargs,
    ):
        """Pause one SSE turn for approval, then resume it with the user's decision."""
        approved = {str(item) for item in (approved_action_ids or []) if str(item).strip()}
        while True:
            events = agent_factory(message, approved_action_ids=sorted(approved), **agent_kwargs)
            restart = False
            try:
                for raw_event in events:
                    event = dict(raw_event or {})
                    if event.get("type") != "action_confirmation":
                        yield event
                        continue
                    action_id = str(event.get("actionId") or "")
                    if not action_id:
                        yield event
                        continue
                    app.register_chat_approval(request_id, action_id)
                    event["requestId"] = request_id
                    yield event
                    decision = decision_waiter(request_id, action_id)
                    with app.CHAT_APPROVAL_LOCK:
                        app.CHAT_APPROVAL_WAITERS.pop(app._chat_approval_key(request_id, action_id), None)
                    yield {
                        "type": "approval_result",
                        "requestId": request_id,
                        "actionId": action_id,
                        "decision": decision,
                        "label": str(event.get("label") or "执行操作"),
                    }
                    if decision == "allow":
                        approved.add(action_id)
                        restart = True
                    else:
                        yield {"type": "delta", "text": f"已取消执行：{event.get('label') or '该操作'}。"}
                        yield {"type": "done"}
                    break
            finally:
                close = getattr(events, "close", None)
                if callable(close):
                    close()
            if restart:
                continue
            return

    publish(app, stream_agent_with_approvals)

