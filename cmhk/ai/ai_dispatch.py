"""Bounded, fair AI admission shared by processes on ONE host.

The file lock protects short accounting transactions, never inference or sleep.
All workers must share the PID namespace and local state path. Multiple containers
or hosts need a distributed
backend before scaling out; copying this file between hosts is not coordination.
"""
from __future__ import annotations

import asyncio
import fcntl
import hashlib
import json
import os
import tempfile
import time
import uuid
from contextlib import asynccontextmanager, contextmanager
from contextvars import ContextVar
from pathlib import Path


PRIORITY = ContextVar("cmhk_ai_priority", default="background")
SUBJECT = ContextVar("cmhk_ai_subject", default="")
WAIT_CALLBACK = ContextVar("cmhk_ai_wait_callback", default=None)


class AIRequestCancelled(RuntimeError):
    """The caller disconnected; never retry or charge an unused queue entry."""


class AIQueueBusy(TimeoutError):
    status_code = 429
    retryable = True
    retry_after = 5


def _number(name, default, minimum=1):
    try:
        return max(minimum, int(os.environ.get("CMHK_INTERNAL_AI_" + name, default)))
    except (TypeError, ValueError):
        return default


def _configured_key_count():
    """Count the global pool without ever exposing a credential."""
    try:
        from cmhk.ai.ai_config import api_key_candidates, load_ai_config
        return max(1, len(api_key_candidates(load_ai_config(include_key=True))))
    except Exception:
        return 1


def limits():
    key_count = _configured_key_count()
    per_key_rpm = _number("KEY_REQUESTS_PER_MINUTE", 14)
    # An explicit legacy aggregate override remains authoritative. Otherwise the
    # safe single-key allowance scales with the configured global key pool.
    aggregate_default = per_key_rpm * key_count
    rpm = _number("REQUESTS_PER_MINUTE", aggregate_default)
    concurrent = _number("MAX_CONCURRENT", 8)
    return {
        "requestsPerMinute": rpm,
        "configuredKeyCount": key_count,
        "keyRequestsPerMinute": per_key_rpm,
        "keyMaxConcurrent": _number("KEY_MAX_CONCURRENT", 3),
        "maxConcurrent": concurrent,
        "backgroundConcurrent": max(1, concurrent - min(concurrent - 1, _number("INTERACTIVE_CONCURRENT_RESERVE", 2))),
        "interactiveConcurrent": max(1, concurrent - min(concurrent - 1, _number("BACKGROUND_CONCURRENT_RESERVE", 1))),
        "perUserConcurrent": _number("PER_USER_CONCURRENT", 2),
        "perWorkflowConcurrent": _number("PER_WORKFLOW_CONCURRENT", 3),
        "interactiveReserve": min(rpm - 1, _number("INTERACTIVE_RESERVE", 4, 0)),
        "backgroundReserve": min(rpm - 1, _number("BACKGROUND_RESERVE", 2, 0)),
        "maxQueued": _number("MAX_QUEUED", 200),
        "perUserQueued": _number("PER_USER_QUEUED", 4),
        "perWorkflowQueued": _number("PER_WORKFLOW_QUEUED", 24),
    }


def state_path():
    configured = os.environ.get("CMHK_INTERNAL_AI_RATE_STATE_PATH", "").strip()
    return Path(configured).expanduser() if configured else Path(tempfile.gettempdir()) / "cmhk_internal_ai_rate_limit.json"


@contextmanager
def request_context(subject="", priority="interactive", wait_callback=None):
    # Store opaque hashes only, never names, session cookies, prompts or keys.
    identity = hashlib.sha256(str(subject).encode()).hexdigest()[:24] if subject else ""
    user_token = SUBJECT.set(identity)
    priority_token = PRIORITY.set(priority)
    callback_token = WAIT_CALLBACK.set(wait_callback)
    try:
        yield
    finally:
        SUBJECT.reset(user_token)
        PRIORITY.reset(priority_token)
        WAIT_CALLBACK.reset(callback_token)


def _alive(pid):
    try:
        os.kill(int(pid), 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True


@contextmanager
def _state(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+", encoding="utf-8") as handle:
        fcntl.flock(handle, fcntl.LOCK_EX)
        try:
            handle.seek(0)
            raw = handle.read()
            try:
                value = json.loads(raw) if raw else {}
                if not isinstance(value, dict):
                    raise ValueError("invalid state")
            except ValueError as exc:
                raise AIQueueBusy("AI 调度状态暂不可读，请稍后重试") from exc
            yield value
            handle.seek(0)
            handle.truncate()
            json.dump(value, handle, ensure_ascii=False, separators=(",", ":"))
            handle.flush()
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)


def _prune(state, now):
    alive = {}
    def live(entry):
        pid = entry.get("pid", -1)
        if pid not in alive:
            alive[pid] = pid > 0 and _alive(pid)
        return alive[pid]
    state["active"] = [e for e in state.get("active", []) if live(e)]
    state["queue"] = [e for e in state.get("queue", []) if live(e) and e["expires"] > now]
    if int(state.get("window", -1)) != int(now // 60):
        state.update(window=int(now // 60), count=0, background_count=0,
                     interactive_count=0, served={}, resource_counts={},
                     resource_served={})
    # Migrate the former counter conservatively; never grant extra capacity.
    state.setdefault("background_count", state.get("count", 0))
    state.setdefault("interactive_count", 0)
    # Keep the round-robin charge for the whole rate window. Dropping it as
    # soon as a fast request closes lets one polling workflow repeatedly jump
    # ahead of an older waiter and consume the entire minute allowance.
    state.setdefault("served", {})
    state.setdefault("resource_counts", {})
    state.setdefault("resource_served", {})


class _Ticket:
    def __init__(self, operation, *, hold, deadline_monotonic=None,
                 wait_callback=None, resources=None):
        self.path = state_path()
        self.started = time.monotonic()
        lane = "interactive" if PRIORITY.get() == "interactive" else "background"
        timeout = _number("INTERACTIVE_QUEUE_TIMEOUT" if lane == "interactive" else "BACKGROUND_QUEUE_TIMEOUT", 180 if lane == "interactive" else 900)
        self.deadline = min(deadline_monotonic or float("inf"), self.started + timeout)
        self.callback = wait_callback or WAIT_CALLBACK.get()
        self.last_callback = 0.0
        self.hold = hold
        self.registered = False
        self.admitted = False
        self.resource = ""
        resources = list(dict.fromkeys(str(value) for value in (resources or []) if value))
        # Group batch fan-out under one workflow; UI requests use verified actor.
        family = operation.split("-")[0]
        self.entry = {"id": uuid.uuid4().hex, "pid": os.getpid(), "lane": lane,
                      "subject": SUBJECT.get() or "workflow:" + family,
                      "operation": operation[:120], "created": time.time(),
                      "expires": time.time() + max(0, self.deadline - self.started),
                      "hold": hold, "resources": resources}

    def try_acquire(self):
        if time.monotonic() >= self.deadline:
            raise AIQueueBusy("AI 请求排队超时，本次未发起新的模型调用，请稍后重试")
        now = time.time()
        cfg = limits()
        with _state(self.path) as state:
            _prune(state, now)
            queue, active = state["queue"], state["active"]
            if not self.registered:
                if len(queue) >= cfg["maxQueued"]:
                    raise AIQueueBusy("AI 请求较多，队列已满，请稍后重试")
                per_subject = cfg["perUserQueued"] if self.entry["lane"] == "interactive" else cfg["perWorkflowQueued"]
                if sum(e["subject"] == self.entry["subject"] for e in queue) >= per_subject:
                    raise AIQueueBusy("您的 AI 待处理请求较多，请等待已有请求完成后重试")
                queue.append(self.entry)
                self.registered = True
            def available_resource(entry):
                resources = entry.get("resources") or []
                if not resources:
                    return ""
                counts = state["resource_counts"]
                active_counts = {
                    resource: sum(e.get("resource") == resource for e in active)
                    for resource in resources
                }
                available = [
                    resource for resource in resources
                    if counts.get(resource, 0) < cfg["keyRequestsPerMinute"]
                    and (not entry["hold"] or active_counts[resource] < cfg["keyMaxConcurrent"])
                ]
                return min(
                    available,
                    key=lambda resource: (
                        active_counts[resource], counts.get(resource, 0),
                        state["resource_served"].get(resource, 0), resources.index(resource),
                    ),
                    default=None,
                )

            def eligible(entry):
                lane = entry["lane"]
                reserve = cfg["interactiveReserve"] if lane == "background" else cfg["backgroundReserve"]
                if state.get("count", 0) >= cfg["requestsPerMinute"] or state[lane + "_count"] >= cfg["requestsPerMinute"] - reserve:
                    return None
                if not entry["hold"]:
                    return available_resource(entry)
                if len(active) >= cfg["maxConcurrent"]:
                    return None
                if sum(e["lane"] == lane for e in active) >= cfg[lane + "Concurrent"]:
                    return None
                cap = cfg["perUserConcurrent"] if lane == "interactive" else cfg["perWorkflowConcurrent"]
                if sum(e["subject"] == entry["subject"] for e in active) >= cap:
                    return None
                return available_resource(entry)
            candidates = [(e, eligible(e)) for e in queue]
            candidates = [(e, resource) for e, resource in candidates if resource is not None]
            # Round robin between subjects, FIFO within a subject. A batch cannot
            # jump ahead just because it has more waiting threads.
            selected = min(candidates, key=lambda item: (state["served"].get(item[0]["subject"], 0), item[0]["created"]), default=None)
            if selected and selected[0]["id"] == self.entry["id"]:
                selected, resource = selected
                queue.remove(selected)
                selected["resource"] = resource
                if self.hold:
                    active.append(selected)
                state["count"] = state.get("count", 0) + 1
                state[self.entry["lane"] + "_count"] += 1
                state["served"][self.entry["subject"]] = now
                if resource:
                    state["resource_counts"][resource] = state["resource_counts"].get(resource, 0) + 1
                    state["resource_served"][resource] = now
                self.resource = resource
                state.update(updated_at=now, last_operation=self.entry["operation"])
                self.admitted = True
                return True
        if self.callback and time.monotonic() - self.last_callback >= 5:
            self.last_callback = time.monotonic()
            self.callback(max(1, min(60 - now % 60, self.deadline - time.monotonic())))
        return False

    def close(self):
        if not self.registered:
            return
        with _state(self.path) as state:
            for name in ("queue", "active"):
                state[name] = [e for e in state.get(name, []) if e["id"] != self.entry["id"]]
        self.registered = False


@contextmanager
def model_call(operation="internal-model", *, deadline_monotonic=None,
               wait_callback=None, resources=None):
    ticket = _Ticket(operation, hold=True, deadline_monotonic=deadline_monotonic,
                     wait_callback=wait_callback, resources=resources)
    try:
        while not ticket.try_acquire():
            time.sleep(0.2)
        yield ticket
    finally:
        ticket.close()


@asynccontextmanager
async def async_model_call(operation="internal-model", *, resources=None):
    ticket = _Ticket(operation, hold=True, resources=resources)
    try:
        # Only short local accounting is synchronous. Waiting is cancellable and
        # does not leave an asyncio.to_thread sleeper to consume a ghost slot.
        while not ticket.try_acquire():
            await asyncio.sleep(0.2)
        yield ticket
    finally:
        ticket.close()


def wait_for_slot(operation="internal-model", *, deadline_monotonic=None, wait_callback=None):
    """Compatibility for callers that only need a rate reservation."""
    ticket = _Ticket(operation, hold=False, deadline_monotonic=deadline_monotonic, wait_callback=wait_callback)
    try:
        while not ticket.try_acquire():
            time.sleep(0.2)
        return time.monotonic() - ticket.started
    finally:
        ticket.close()


def order_resources(resources):
    """Least-loaded ordering for callers that must build a route-specific body."""
    resources = list(dict.fromkeys(str(value) for value in resources if value))
    with _state(state_path()) as state:
        _prune(state, time.time())
        active = state["active"]
        return sorted(
            resources,
            key=lambda resource: (
                sum(entry.get("resource") == resource for entry in active),
                state["resource_counts"].get(resource, 0),
                state["resource_served"].get(resource, 0),
                resources.index(resource),
            ),
        )


def capacity_status():
    with _state(state_path()) as state:
        _prune(state, time.time())
        resource_ids = sorted(set(state["resource_counts"]) | {
            entry.get("resource") for entry in state["active"] if entry.get("resource")
        })
        key_usage = [
            {"route": resource, "usedThisMinute": state["resource_counts"].get(resource, 0),
             "active": sum(entry.get("resource") == resource for entry in state["active"])}
            for resource in resource_ids
        ]
        return {"backend": "single-host-file", **limits(), "active": len(state["active"]),
                "queued": len(state["queue"]), "usedThisMinute": state.get("count", 0),
                "backgroundActive": sum(e["lane"] == "background" for e in state["active"]),
                "keyUsage": key_usage}
