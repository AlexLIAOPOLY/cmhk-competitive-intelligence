from __future__ import annotations

import csv
import hashlib
import json
import re
import time
from pathlib import Path
from typing import Any

from rag_llm import estimate_tokens, list_knowledge_datasets


ROOT = Path(__file__).resolve().parent
TRACE_DIR = ROOT / "agent_runs"
TRACE_INDEX = TRACE_DIR / "runs.jsonl"


DANGEROUS_ACTIONS = {
    "trigger_crawl": "定向爬虫",
    "trigger_full_crawl": "全量爬虫",
    "trigger_report_generation": "生成周报",
    "trigger_carrier_performance_report_generation": "生成业绩摘要",
    "feishu_cli": "飞书命令",
}


def _now() -> float:
    return time.time()


def _date(ts: float | None = None) -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(ts or _now()))


def short_hash(value: Any) -> str:
    text = json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:12]


def action_id(name: str, payload: Any = None) -> str:
    return f"{name}:{short_hash(payload or {})}"


def confirmation_event(name: str, payload: Any = None, description: str = "") -> dict[str, Any]:
    label = DANGEROUS_ACTIONS.get(name, name)
    return {
        "type": "action_confirmation",
        "action": name,
        "actionId": action_id(name, payload),
        "label": label,
        "description": description or f"即将执行：{label}",
        "risk": "该操作会改变本地文件、触发外部同步或启动耗时任务。",
    }


def confirmation_metadata(event: dict[str, Any]) -> str:
    return f"<metadata>{json.dumps(event, ensure_ascii=False)}</metadata>"


def dataset_lineage(dataset_ids: set[str] | None = None) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for dataset in list_knowledge_datasets(dataset_ids=dataset_ids):
        files = dataset.get("files") or []
        total_size = sum(int(item.get("size") or 0) for item in files)
        file_fingerprint = short_hash(
            [
                {"path": item.get("path"), "size": item.get("size")}
                for item in files
            ]
        )
        manifest_path = dataset.get("manifest_path") or ""
        row = {
            "id": dataset.get("id"),
            "title": dataset.get("title"),
            "source_type": dataset.get("source_type"),
            "scope": dataset.get("scope"),
            "updated_at": dataset.get("updated_at"),
            "quality": dataset.get("quality"),
            "folder": dataset.get("folder"),
            "manifest_path": manifest_path,
            "file_count": len(files),
            "total_size": total_size,
            "fingerprint": file_fingerprint,
            "entrypoints": dataset.get("entrypoints") or [],
            "tags": dataset.get("tags") or [],
        }
        manifest_file = ROOT / manifest_path if manifest_path else None
        if manifest_file and manifest_file.exists():
            try:
                manifest = json.loads(manifest_file.read_text(encoding="utf-8"))
            except Exception:
                manifest = {}
            for key in ("version", "built_at", "row_count", "verified_count", "gap_count", "last_audit_path"):
                if key in manifest:
                    row[key] = manifest[key]
        rows.append(row)
    return rows


def retrieval_quality(query: str, chunks: list[dict[str, Any]], audit: dict[str, Any] | None = None) -> dict[str, Any]:
    query_terms = {
        item.lower()
        for item in re.findall(r"[A-Za-z0-9_\-]{2,}|[\u4e00-\u9fff]{2,}", query or "")
    }
    official_hits = 0
    conflict_hits = 0
    source_gap_hits = 0
    exact_metric_hits = 0
    source_counts: dict[str, int] = {}
    for chunk in chunks:
        source = str(chunk.get("source") or "")
        text = str(chunk.get("text") or "")
        lower = text.lower()
        source_counts[source] = source_counts.get(source, 0) + 1
        if "official_value" in lower or "official_source" in lower:
            official_hits += 1
        if "official_conflict" in lower:
            conflict_hits += 1
        if "source_gap" in lower:
            source_gap_hits += 1
        if query_terms and any(term in lower for term in query_terms):
            exact_metric_hits += 1
    retained = len(chunks)
    score = 0
    if retained:
        score += 35
    if official_hits:
        score += 25
    if exact_metric_hits:
        score += 20
    if audit and int(audit.get("skipped_chunks") or 0) == 0:
        score += 10
    if conflict_hits or source_gap_hits:
        score += 5
    if len(source_counts) >= 2:
        score += 5
    return {
        "score": min(100, score),
        "retained_chunks": retained,
        "official_hits": official_hits,
        "conflict_hits": conflict_hits,
        "source_gap_hits": source_gap_hits,
        "query_term_hits": exact_metric_hits,
        "unique_sources": len(source_counts),
        "status": "strong" if score >= 75 else "usable" if score >= 50 else "weak",
    }


class AgentRunRecorder:
    def __init__(
        self,
        *,
        message: str,
        selected_dataset_ids: list[str],
        selected_skill_ids: list[str],
        web_search_enabled: bool,
        thinking_enabled: bool,
        approved_action_ids: list[str] | None = None,
    ) -> None:
        ts = _now()
        self.run_id = f"run_{time.strftime('%Y%m%d_%H%M%S', time.localtime(ts))}_{short_hash([message, ts])}"
        self.started_at = ts
        self.events: list[dict[str, Any]] = []
        self.tool_calls: list[dict[str, Any]] = []
        self.meta_events: list[dict[str, Any]] = []
        self.errors: list[str] = []
        self.answer_parts: list[str] = []
        self.record: dict[str, Any] = {
            "run_id": self.run_id,
            "started_at": _date(ts),
            "message": str(message or "")[:4000],
            "selected_dataset_ids": selected_dataset_ids,
            "selected_skill_ids": selected_skill_ids,
            "web_search_enabled": web_search_enabled,
            "thinking_enabled": thinking_enabled,
            "approved_action_ids": approved_action_ids or [],
            "input_tokens_estimate": estimate_tokens(message or ""),
        }

    def observe(self, event: dict[str, Any]) -> None:
        clean = {k: v for k, v in event.items() if k != "content"}
        clean["ts"] = _date()
        self.events.append(clean)
        event_type = event.get("type")
        if event_type == "delta":
            self.answer_parts.append(str(event.get("text") or ""))
        elif event_type in {"tool_call_start", "tool_call_result"}:
            self.tool_calls.append(
                {
                    "type": event_type,
                    "id": event.get("id"),
                    "name": event.get("name"),
                    "args": str(event.get("args") or "")[:2000],
                    "content_preview": str(event.get("content") or "")[:2000],
                    "ts": clean["ts"],
                }
            )
        elif event_type == "meta":
            self.meta_events.append(event)
        elif event_type == "error":
            self.errors.append(str(event.get("text") or ""))

    def finish(self) -> dict[str, Any]:
        ended = _now()
        answer = "".join(self.answer_parts)
        context_audits = [item.get("contextAudit") for item in self.meta_events if item.get("contextAudit")]
        retrieval_scores = [item.get("retrievalQuality") for item in self.meta_events if item.get("retrievalQuality")]
        self.record.update(
            {
                "ended_at": _date(ended),
                "duration_ms": int((ended - self.started_at) * 1000),
                "answer_preview": answer[:4000],
                "answer_tokens_estimate": estimate_tokens(answer),
                "tool_calls": self.tool_calls,
                "context_audits": context_audits,
                "retrieval_quality": retrieval_scores,
                "errors": self.errors,
                "status": "error" if self.errors else "ok",
            }
        )
        TRACE_DIR.mkdir(parents=True, exist_ok=True)
        detail_path = TRACE_DIR / f"{self.run_id}.json"
        detail_path.write_text(json.dumps(self.record, ensure_ascii=False, indent=2), encoding="utf-8")
        with TRACE_INDEX.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps({k: v for k, v in self.record.items() if k not in {"answer_preview"}}, ensure_ascii=False) + "\n")
        return self.record


def list_agent_runs(limit: int = 20) -> list[dict[str, Any]]:
    if not TRACE_INDEX.exists():
        return []
    rows: list[dict[str, Any]] = []
    for line in TRACE_INDEX.read_text(encoding="utf-8", errors="ignore").splitlines():
        try:
            item = json.loads(line)
        except Exception:
            continue
        if isinstance(item, dict):
            rows.append(item)
    rows.sort(key=lambda item: str(item.get("started_at") or ""), reverse=True)
    return rows[: max(1, min(limit, 100))]


def rolling_backtest(values: list[float], season_length: int, forecast_fn: Any) -> dict[str, Any]:
    if len(values) < max(10, season_length * 3):
        return {"ok": False, "reason": "样本不足，无法做稳定滚动回测。"}
    start = max(season_length * 2, len(values) - min(12, max(4, len(values) // 3)))
    actuals: list[float] = []
    hw_preds: list[float] = []
    naive_preds: list[float] = []
    seasonal_preds: list[float] = []
    for idx in range(start, len(values)):
        history = values[:idx]
        actual = values[idx]
        hw_forecast, _method, _rmse = forecast_fn(history, 1, season_length)
        actuals.append(actual)
        hw_preds.append(float(hw_forecast[0]))
        naive_preds.append(float(history[-1]))
        seasonal_preds.append(float(history[-season_length] if len(history) >= season_length else history[-1]))

    def rmse(preds: list[float]) -> float:
        return (sum((pred - actual) ** 2 for pred, actual in zip(preds, actuals)) / len(actuals)) ** 0.5

    def mape(preds: list[float]) -> float:
        parts = [
            abs((pred - actual) / actual)
            for pred, actual in zip(preds, actuals)
            if actual
        ]
        return sum(parts) / len(parts) * 100 if parts else 0.0

    scores = {
        "holt_winters": {"rmse": rmse(hw_preds), "mape": mape(hw_preds)},
        "naive": {"rmse": rmse(naive_preds), "mape": mape(naive_preds)},
        "seasonal_naive": {"rmse": rmse(seasonal_preds), "mape": mape(seasonal_preds)},
    }
    best = min(scores, key=lambda key: scores[key]["rmse"])
    return {"ok": True, "windows": len(actuals), "scores": scores, "best_baseline": best}


def eval_summary_line(rows: list[dict[str, Any]]) -> str:
    passed = sum(1 for row in rows if row.get("passed"))
    total = len(rows)
    return f"Agent Evals：{passed}/{total} 通过" if total else "Agent Evals：无用例"
