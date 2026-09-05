"""Durable, bounded execution for the existing news decision agents.

LangGraph owns retries and SQLite checkpoints. Business callers still own their
schemas, human-review rules and external write/readback receipts. Only completed
JSON results enter the checkpoint; credentials and reasoning never enter state.
"""
from __future__ import annotations

import fcntl
import hashlib
import json
import logging
import time
from pathlib import Path
from typing import Any, Callable, TypedDict

from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import RetryPolicy


class TruncatedModelOutput(RuntimeError):
    """Incomplete model output must never be treated as a business decision."""


def assert_complete(message: Any) -> None:
    metadata = getattr(message, "response_metadata", {}) or {}
    assert_finish_reason(metadata.get("finish_reason", ""))
    if getattr(message, "invalid_tool_calls", None):
        raise TruncatedModelOutput("模型工具参数不完整；本次未提交任何记录")


def assert_finish_reason(reason: str) -> None:
    reason = str(reason or "").strip().lower()
    if reason in {"length", "max_tokens", "max_output_tokens"}:
        raise TruncatedModelOutput("模型输出被截断；本次未提交任何记录")
    if reason in {"content_filter", "error", "cancelled"}:
        raise TruncatedModelOutput("模型响应未正常完成；本次未提交任何记录")


class _State(TypedDict, total=False):
    result: Any


def run_durable_agent(*, namespace: str, identity: Any, directory: Path,
                      execute: Callable[[int], Any], max_attempts: int = 3,
                      retry_on: tuple[type[Exception], ...] = (TruncatedModelOutput,),
                      deadline: float | None = None) -> Any:
    """Resume one content-addressed decision, without replaying external effects.

    ``execute`` must be inference plus validation only, never send/write operations.
    An interrupted in-flight inference may run again; completed decisions do not.
    External exactly-once behavior requires the callers' existing durable receipts.
    """
    fingerprint = hashlib.sha256(json.dumps(
        {"version": 1, "namespace": namespace, "identity": identity},
        sort_keys=True, ensure_ascii=False, separators=(",", ":"),
    ).encode()).hexdigest()
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    attempts = 0

    def decide(state: _State) -> dict:
        nonlocal attempts
        if deadline is not None and time.monotonic() >= deadline:
            raise TimeoutError("Agent 执行已达到本轮时间上限")
        attempt = attempts
        attempts += 1
        result = execute(attempt)
        # Normalize to plain JSON rather than serializing model/client objects.
        return {"result": json.loads(json.dumps(result, ensure_ascii=False))}

    graph = StateGraph(_State)
    graph.add_node("validated_decision", decide, retry_policy=RetryPolicy(
        max_attempts=max(1, max_attempts), initial_interval=1, max_interval=4,
        jitter=False, retry_on=retry_on,
    ))
    graph.add_edge(START, "validated_decision")
    graph.add_edge("validated_decision", END)
    config = {"configurable": {"thread_id": fingerprint}}
    # A per-decision OS lock is released even by SIGKILL. Different jobs stay
    # concurrent; identical jobs cannot both consume a model and publish state.
    with (directory / f"{fingerprint}.lock").open("a") as lock:
        lock_deadline = min(deadline or float("inf"), time.monotonic() + 30)
        while True:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                if time.monotonic() >= lock_deadline:
                    raise TimeoutError("相同 Agent 决策正在执行；保持待处理，不重复提交")
                time.sleep(0.1)
        with SqliteSaver.from_conn_string(str(directory / f"{fingerprint}.sqlite")) as saver:
            app = graph.compile(checkpointer=saver)
            saved = app.get_state(config)
            if saved.values and "result" in saved.values and not saved.next:
                logging.info("%s harness 复用已完成决策检查点", namespace)
                return saved.values["result"]
            result = app.invoke(None if saved.created_at else {}, config, durability="sync")
            return result["result"]
