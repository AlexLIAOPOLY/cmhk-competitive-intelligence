from __future__ import annotations

import hashlib
import json
import os
import re
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from langchain_core.messages import HumanMessage, SystemMessage

from ai_config import load_ai_config
from ai_rate_limit import RateLimitedChatDeepSeek as ChatDeepSeek
from cmhk.crawl.run_registry import (
    append_crawl_run_event,
    finalize_operational_crawl_run,
    heartbeat_crawl_run,
    start_crawl_run,
)


ROOT = Path(__file__).resolve().parents[2]
HKT = ZoneInfo("Asia/Hong_Kong")
AGENT_DIR = ROOT / "agent_knowledge" / "news_selection_agent"
AUDIT_PATH = AGENT_DIR / "decisions.jsonl"
STATE_PATH = AGENT_DIR / "state.json"
SKILL_PATH = AGENT_DIR / "SKILL.md"
MAX_HISTORY_EXAMPLES = max(
    40, min(300, int(os.environ.get("CMHK_NEWS_SELECTION_HISTORY_LIMIT", "160")))
)
MODEL_BATCH_SIZE = max(
    5, min(30, int(os.environ.get("CMHK_NEWS_SELECTION_MODEL_BATCH_SIZE", "20")))
)
WRITE_BATCH_ROWS = max(
    10, min(90, int(os.environ.get("CMHK_NEWS_SELECTION_WRITE_BATCH_ROWS", "80")))
)
LOW_CONFIDENCE_THRESHOLD = max(
    0.5,
    min(0.95, float(os.environ.get("CMHK_NEWS_SELECTION_CONFIDENCE", "0.68"))),
)
VALID_STATUSES = {"接受", "不接受", "暂缓"}


def _text(value: Any, limit: int = 1000) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()[:limit]


def _now_iso() -> str:
    return datetime.now(HKT).isoformat(timespec="seconds")


def _display_path(path: Path) -> str:
    try:
        return str(path.relative_to(ROOT))
    except ValueError:
        return str(path)


def _atomic_write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.{uuid.uuid4().hex}.tmp")
    try:
        temporary.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        os.replace(temporary, path)
    finally:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass


def _append_audit(payload: dict[str, Any]) -> None:
    AUDIT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with AUDIT_PATH.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, ensure_ascii=False) + "\n")


def _load_audit() -> list[dict[str, Any]]:
    if not AUDIT_PATH.exists():
        return []
    records: list[dict[str, Any]] = []
    for line in AUDIT_PATH.read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            payload = json.loads(line)
        except (TypeError, ValueError):
            continue
        if isinstance(payload, dict):
            records.append(payload)
    return records


def _load_state() -> dict[str, Any]:
    try:
        payload = json.loads(STATE_PATH.read_text(encoding="utf-8"))
    except (OSError, TypeError, ValueError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _json_object(value: Any) -> dict[str, Any]:
    content = value if isinstance(value, str) else str(value or "")
    content = re.sub(r"^```(?:json)?\s*|\s*```$", "", content.strip(), flags=re.I)
    try:
        parsed = json.loads(content)
    except json.JSONDecodeError:
        match = re.search(r"\{[\s\S]*\}", content)
        if not match:
            raise ValueError("模型未返回可解析的 JSON 对象")
        parsed = json.loads(match.group(0))
    if not isinstance(parsed, dict):
        raise ValueError("模型结果必须是 JSON 对象")
    return parsed


def _latest_agent_decisions(records: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    latest: dict[str, dict[str, Any]] = {}
    for record in records:
        if record.get("event") != "decision" or record.get("write_verified") is not True:
            continue
        news_id = _text(record.get("news_id"), 80)
        if news_id:
            latest[news_id] = record
    return latest


def _snapshot_rows(snapshot: dict[str, Any]) -> list[dict[str, Any]]:
    from cmhk.intelligence import news_review_sheet

    rows: list[dict[str, Any]] = []
    for raw in snapshot.get("rows") or []:
        if not isinstance(raw, dict):
            continue
        values = raw.get("values") if isinstance(raw.get("values"), list) else []
        parsed = news_review_sheet._row_dict(values, int(raw.get("rowNumber") or 0))
        parsed["values"] = list(values)
        rows.append(parsed)
    return rows


def _human_examples(
    rows: list[dict[str, Any]],
    latest_agent_decisions: dict[str, dict[str, Any]],
) -> tuple[list[dict[str, Any]], int]:
    examples: list[dict[str, Any]] = []
    corrected_count = 0
    for row in rows:
        app_status = _text(row.get("status"), 20)
        weekly_status = _text(row.get("weekly_status"), 20)
        previous = latest_agent_decisions.get(_text(row.get("news_id"), 80))
        app_is_agent_owned = False
        weekly_is_agent_owned = False
        if previous:
            automated_fields = set(previous.get("automated_fields") or ("app", "weekly"))
            app_is_agent_owned = (
                "app" in automated_fields
                and app_status == _text(previous.get("app_status"), 20)
            )
            weekly_is_agent_owned = (
                "weekly" in automated_fields
                and weekly_status == _text(previous.get("weekly_status"), 20)
            )
            if app_is_agent_owned and weekly_is_agent_owned:
                continue
            if (
                ("app" in automated_fields and not app_is_agent_owned)
                or ("weekly" in automated_fields and not weekly_is_agent_owned)
            ):
                corrected_count += 1
        if app_status == "待审核" and weekly_status == "待审核":
            continue
        examples.append(
            {
                "news_id": _text(row.get("news_id"), 80),
                "title": _text(row.get("title"), 260),
                "summary": _text(row.get("summary"), 420),
                "region": _text(row.get("region"), 60),
                "category": _text(row.get("category"), 80),
                "source": _text(row.get("source"), 100),
                "source_date": _text(row.get("source_date"), 40),
                "keywords": _text(row.get("keywords"), 180),
                "app_status": "待审核" if app_is_agent_owned else app_status,
                "weekly_status": "待审核" if weekly_is_agent_owned else weekly_status,
                "human_correction_of_agent": bool(previous)
                and (not app_is_agent_owned or not weekly_is_agent_owned),
            }
        )
    return examples[:MAX_HISTORY_EXAMPLES], corrected_count


def _target_rows(
    rows: list[dict[str, Any]],
    new_items: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    target_ids = {
        _text(item.get("news_id"), 80)
        for item in new_items
        if isinstance(item, dict) and _text(item.get("news_id"), 80)
    }
    targets: list[dict[str, Any]] = []
    for row in rows:
        if _text(row.get("news_id"), 80) not in target_ids:
            continue
        if row.get("status") != "待审核" and row.get("weekly_status") != "待审核":
            continue
        targets.append(
            {
                "news_id": _text(row.get("news_id"), 80),
                "row_number": int(row.get("row_number") or 0),
                "title": _text(row.get("title"), 300),
                "summary": _text(row.get("summary"), 500),
                "region": _text(row.get("region"), 60),
                "category": _text(row.get("category"), 100),
                "source": _text(row.get("source"), 100),
                "source_date": _text(row.get("source_date"), 40),
                "keywords": _text(row.get("keywords"), 220),
                "note": _text(row.get("note"), 220),
                "app_before": _text(row.get("status"), 20),
                "weekly_before": _text(row.get("weekly_status"), 20),
            }
        )
    return targets


def _model_routes() -> list[tuple[str, str]]:
    config = load_ai_config(include_key=True)
    primary_model = (
        os.environ.get("CMHK_NEWS_SELECTION_MODEL", "").strip()
        or _text(config.get("model"), 120)
    )
    primary_keys = [
        _text(value, 500)
        for value in (config.get("strategy_api_keys") or [])
        if _text(value, 500)
    ]
    if _text(config.get("api_key"), 500):
        primary_keys.append(_text(config.get("api_key"), 500))
    routes = [(primary_model, key) for key in dict.fromkeys(primary_keys) if primary_model]
    for model, values in (config.get("model_api_keys") or {}).items():
        keys = [values] if isinstance(values, str) else values
        if not isinstance(keys, list):
            continue
        routes.extend(
            (_text(model, 120), _text(key, 500))
            for key in keys
            if _text(model, 120) and _text(key, 500)
        )
    return list(dict.fromkeys(routes))


def _invoke_langchain(
    examples: list[dict[str, Any]],
    targets: list[dict[str, Any]],
) -> tuple[dict[str, Any], str]:
    config = load_ai_config(include_key=True)
    system_prompt = (
        "你是 CMHK 每日新聞選材偏好學習 Agent。你只從已提供的歷史人工決策中歸納習慣，"
        "並對本輪候選分別判斷 APP 滾動新聞與雙周報。兩個欄位互相獨立。"
        "接受表示符合歷史取捨，不接受表示明顯不符合；資訊或證據不足時使用暂缓。"
        "不得把既有自動決策當成人工樣本，不得補造新聞事實。"
        "只輸出 JSON：learned_rules、avoid_patterns、app_preference_summary、"
        "weekly_preference_summary、decisions。decisions 每項必須有 news_id、"
        "app_status、weekly_status、app_confidence、weekly_confidence、reason。"
        "狀態只能是接受、不接受、暂缓，confidence 為 0 至 1。"
    )
    user_prompt = json.dumps(
        {
            "human_examples": examples,
            "current_candidates": targets,
            "instruction": "歸納可復用偏好並逐條判斷；不可遺漏任何 current_candidates。",
        },
        ensure_ascii=False,
    )
    errors: list[str] = []
    for model_name, api_key in _model_routes():
        model = ChatDeepSeek(
            model=model_name,
            api_key=api_key,
            api_base=_text(config.get("base_url"), 500),
            extra_body={"response_format": {"type": "json_object"}},
            temperature=0.1,
            disable_streaming=True,
            max_retries=1,
            max_tokens=7000,
        )
        try:
            response = model.invoke(
                [SystemMessage(content=system_prompt), HumanMessage(content=user_prompt)]
            )
            return _json_object(getattr(response, "content", "")), model_name
        except Exception as exc:
            errors.append(f"{model_name}: {_text(exc, 180)}")
    raise RuntimeError("LangChain 模型路由全部失敗；" + "；".join(errors[:4]))


def _normalized_decisions(
    payload: dict[str, Any], targets: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    raw_by_id = {
        _text(item.get("news_id"), 80): item
        for item in (payload.get("decisions") or [])
        if isinstance(item, dict) and _text(item.get("news_id"), 80)
    }
    decisions: list[dict[str, Any]] = []
    for target in targets:
        raw = raw_by_id.get(target["news_id"])
        if not raw:
            raise ValueError(f"模型遺漏候選 {target['news_id']}")
        item = {**target}
        for field in ("app", "weekly"):
            before = _text(target.get(f"{field}_before"), 20)
            if before != "待审核":
                item[f"{field}_status"] = before
                item[f"{field}_confidence"] = 1.0
                continue
            status = _text(raw.get(f"{field}_status"), 20)
            try:
                confidence = max(0.0, min(1.0, float(raw.get(f"{field}_confidence"))))
            except (TypeError, ValueError):
                confidence = 0.0
            if status not in VALID_STATUSES or confidence < LOW_CONFIDENCE_THRESHOLD:
                status = "暂缓"
            item[f"{field}_status"] = status
            item[f"{field}_confidence"] = round(confidence, 4)
        item["reason"] = _text(raw.get("reason"), 500) or "按歷史人工取捨習慣判斷"
        decisions.append(item)
    return decisions


def _invoke_langchain_batches(
    examples: list[dict[str, Any]],
    targets: list[dict[str, Any]],
    *,
    progress_callback: Any = None,
) -> tuple[dict[str, Any], str]:
    payloads: list[dict[str, Any]] = []
    model_names: list[str] = []
    total = (len(targets) + MODEL_BATCH_SIZE - 1) // MODEL_BATCH_SIZE
    for batch_index, start in enumerate(range(0, len(targets), MODEL_BATCH_SIZE), start=1):
        batch = targets[start : start + MODEL_BATCH_SIZE]
        if progress_callback:
            progress_callback(batch_index, total, len(batch))
        payload, model_name = _invoke_langchain(examples, batch)
        payloads.append(payload)
        model_names.append(model_name)
    first = payloads[0] if payloads else {}
    return {
        "learned_rules": list(
            dict.fromkeys(
                _text(value, 300)
                for payload in payloads
                for value in (payload.get("learned_rules") or [])
                if _text(value, 300)
            )
        )[:12],
        "avoid_patterns": list(
            dict.fromkeys(
                _text(value, 300)
                for payload in payloads
                for value in (payload.get("avoid_patterns") or [])
                if _text(value, 300)
            )
        )[:12],
        "app_preference_summary": _text(first.get("app_preference_summary"), 1000),
        "weekly_preference_summary": _text(first.get("weekly_preference_summary"), 1000),
        "decisions": [
            item
            for payload in payloads
            for item in (payload.get("decisions") or [])
            if isinstance(item, dict)
        ],
    }, ", ".join(dict.fromkeys(model_names))


def _skill_text(
    payload: dict[str, Any],
    *,
    model_name: str,
    human_example_count: int,
    corrected_count: int,
) -> str:
    rules = [
        _text(value, 300)
        for value in (payload.get("learned_rules") or [])
        if _text(value, 300)
    ][:12]
    avoid = [
        _text(value, 300)
        for value in (payload.get("avoid_patterns") or [])
        if _text(value, 300)
    ][:12]
    bullet_rules = "\n".join(f"- {value}" for value in rules) or "- 暫無足夠人工樣本可歸納。"
    bullet_avoid = "\n".join(f"- {value}" for value in avoid) or "- 暫無穩定排除模式。"
    return f'''---
name: cmhk-news-selection-preference
description: 學習 CMHK 每日新聞歷史人工選材習慣，分別判斷 APP 滾動新聞與雙周報候選；僅用於本輪新增且仍待審核的新聞。
---

# CMHK 新聞選材偏好

## 不可變邊界

- APP 與雙周報為兩個獨立決策，不得互相複製。
- 不覆蓋任何既有人工決策；只處理本輪新增且仍為「待審核」的欄位。
- 歷史自動決策不作訓練樣本；人工改正自動結果後，改正值可作新樣本。
- 低於 {LOW_CONFIDENCE_THRESHOLD:.2f} 的判斷一律標為「暂缓」。
- 不補造新聞事實；原文、日期或證據不足時保守暂缓。

## 最新學習摘要

- 更新時間：{_now_iso()}
- LangChain 模型：{_text(model_name, 120)}
- 有效人工樣本：{human_example_count}
- 已識別人工糾正：{corrected_count}
- APP 偏好：{_text(payload.get('app_preference_summary'), 1000) or '尚未形成穩定摘要'}
- 雙周報偏好：{_text(payload.get('weekly_preference_summary'), 1000) or '尚未形成穩定摘要'}

## 已學習規則

{bullet_rules}

## 已學習排除模式

{bullet_avoid}
'''


def _progress(
    crawl_run_id: str,
    stream_log_path: str,
    phase: str,
    detail: str,
) -> None:
    heartbeat_crawl_run(crawl_run_id, phase, detail, append_log=False)
    append_crawl_run_event(
        stream_log_path,
        {"type": "log", "text": f"[{datetime.now(HKT):%Y-%m-%d %H:%M:%S}] {phase}：{detail}"},
    )


def run_news_selection_agent(
    *,
    new_items: list[dict[str, Any]],
    sheet_id: str,
    parent_crawl_run_id: str,
    idempotency_key: str,
) -> dict[str, Any]:
    """Learn human choices and auto-review only this crawl's pending rows."""
    started = time.monotonic()
    run = start_crawl_run(
        trigger="新聞偏好學習與自動勾選 Agent",
        scope=f"爬蟲後選材（{_text(idempotency_key, 120) or '未命名輪次'}）",
        task_kind="news-selection-agent",
        parent_crawl_run_id=parent_crawl_run_id,
        phase="讀取人工樣本",
        progress_detail="正在讀取歷史人工 APP 與雙周報勾選習慣。",
    )
    crawl_run_id = _text(run.get("crawl_run_id"), 120)
    stream_log_path = _text(run.get("stream_log_path"), 1600)
    try:
        state = _load_state()
        completed_keys = state.get("completed_keys") if isinstance(state.get("completed_keys"), dict) else {}
        if idempotency_key and idempotency_key in completed_keys:
            detail = "同一爬蟲輪次已完成自動勾選，直接復用已驗證結果。"
            _progress(crawl_run_id, stream_log_path, "幂等結果復用", detail)
            result = {**completed_keys[idempotency_key], "reused": True, "task_run_id": crawl_run_id}
            finalize_operational_crawl_run(
                crawl_run_id,
                ok=True,
                duration_ms=round((time.monotonic() - started) * 1000),
                progress_detail=detail,
                summary=result,
            )
            return result

        from cmhk.intelligence import news_review_sheet

        snapshot = news_review_sheet.review_sheet_snapshot(sheet_id=sheet_id)
        rows = _snapshot_rows(snapshot)
        audits = _load_audit()
        examples, corrected_count = _human_examples(rows, _latest_agent_decisions(audits))
        targets = _target_rows(rows, new_items)
        _progress(
            crawl_run_id,
            stream_log_path,
            "人工樣本隔離",
            f"讀取 {len(rows)} 條候選；有效人工樣本 {len(examples)} 條，排除既有自動決策，識別人工糾正 {corrected_count} 條。",
        )
        if not targets:
            result = {
                "status": "completed",
                "candidate_count": 0,
                "changed_count": 0,
                "readback_verified": True,
                "reason": "本輪沒有仍待審核的新候選",
                "task_run_id": crawl_run_id,
            }
            _progress(crawl_run_id, stream_log_path, "無待審候選", result["reason"])
        else:
            _progress(
                crawl_run_id,
                stream_log_path,
                "LangChain 偏好學習",
                f"使用 {len(examples)} 條人工樣本分析 {len(targets)} 條本輪候選；APP 與雙周報分開判斷。",
            )
            model_payload, model_name = _invoke_langchain_batches(
                examples,
                targets,
                progress_callback=lambda batch, total, count: _progress(
                    crawl_run_id,
                    stream_log_path,
                    "LangChain 分批判斷",
                    f"正在處理第 {batch}/{total} 組，本組 {count} 條候選。",
                ),
            )
            decisions = _normalized_decisions(model_payload, targets)
            SKILL_PATH.parent.mkdir(parents=True, exist_ok=True)
            SKILL_PATH.write_text(
                _skill_text(
                    model_payload,
                    model_name=model_name,
                    human_example_count=len(examples),
                    corrected_count=corrected_count,
                ),
                encoding="utf-8",
            )
            _progress(
                crawl_run_id,
                stream_log_path,
                "Skill 更新",
                f"已把最新人工偏好摘要寫入 {_display_path(SKILL_PATH)}。",
            )
            changed_count = 0
            write_batch_total = (
                len(decisions) + WRITE_BATCH_ROWS - 1
            ) // WRITE_BATCH_ROWS
            for write_batch_index, start in enumerate(
                range(0, len(decisions), WRITE_BATCH_ROWS), start=1
            ):
                decision_batch = decisions[start : start + WRITE_BATCH_ROWS]
                changes: list[dict[str, Any]] = []
                for decision in decision_batch:
                    if decision["app_before"] == "待审核":
                        changes.append(
                            {
                                "rowNumber": decision["row_number"],
                                "columnIndex": 0,
                                "before": "待审核",
                                "value": decision["app_status"],
                            }
                        )
                    if decision["weekly_before"] == "待审核":
                        changes.append(
                            {
                                "rowNumber": decision["row_number"],
                                "columnIndex": 1,
                                "before": "待审核",
                                "value": decision["weekly_status"],
                            }
                        )
                write_result = news_review_sheet.update_review_sheet_cells(
                    changes,
                    sheet_id=sheet_id,
                )
                if write_result.get("readbackVerified") is not True:
                    raise RuntimeError("自動勾選後未取得逐格回讀證據")
                changed_count += int(write_result.get("changedCount") or 0)
                recorded_at = _now_iso()
                for decision in decision_batch:
                    automated_fields = [
                        field
                        for field in ("app", "weekly")
                        if decision[f"{field}_before"] == "待审核"
                    ]
                    _append_audit(
                        {
                            "event": "decision",
                            "recorded_at": recorded_at,
                            "agent_run_id": crawl_run_id,
                            "parent_crawl_run_id": parent_crawl_run_id,
                            "idempotency_key": idempotency_key,
                            "model": model_name,
                            "news_id": decision["news_id"],
                            "row_number": decision["row_number"],
                            "title": decision["title"],
                            "app_before": decision["app_before"],
                            "weekly_before": decision["weekly_before"],
                            "app_status": decision["app_status"],
                            "weekly_status": decision["weekly_status"],
                            "automated_fields": automated_fields,
                            "app_confidence": decision["app_confidence"],
                            "weekly_confidence": decision["weekly_confidence"],
                            "reason": decision["reason"],
                            "write_verified": True,
                        }
                    )
                _progress(
                    crawl_run_id,
                    stream_log_path,
                    "分批寫入與回讀",
                    f"第 {write_batch_index}/{write_batch_total} 批已寫入 {len(changes)} 格並逐格回讀通過。",
                )
            result = {
                "status": "completed",
                "candidate_count": len(decisions),
                "changed_count": changed_count,
                "app_accepted_count": sum(item["app_status"] == "接受" for item in decisions),
                "weekly_accepted_count": sum(item["weekly_status"] == "接受" for item in decisions),
                "deferred_field_count": sum(
                    item[field] == "暂缓"
                    for item in decisions
                    for field in ("app_status", "weekly_status")
                ),
                "human_example_count": len(examples),
                "human_correction_count": corrected_count,
                "model": model_name,
                "skill_path": _display_path(SKILL_PATH),
                "audit_path": _display_path(AUDIT_PATH),
                "readback_verified": True,
                "task_run_id": crawl_run_id,
            }
            _progress(
                crawl_run_id,
                stream_log_path,
                "自動勾選與回讀",
                f"處理 {len(decisions)} 條、寫入 {result['changed_count']} 格；APP 接受 {result['app_accepted_count']} 條，雙周報接受 {result['weekly_accepted_count']} 條，逐格回讀通過。",
            )

        if idempotency_key:
            state = _load_state()
            completed_keys = state.get("completed_keys") if isinstance(state.get("completed_keys"), dict) else {}
            completed_keys[idempotency_key] = {
                key: value for key, value in result.items() if key != "task_run_id"
            }
            state["completed_keys"] = dict(list(completed_keys.items())[-64:])
            state["last_run"] = result
            state["updated_at"] = _now_iso()
            _atomic_write_json(STATE_PATH, state)
        append_crawl_run_event(
            stream_log_path,
            {"type": "done", "ok": True, "summary": result},
        )
        finalize_operational_crawl_run(
            crawl_run_id,
            ok=True,
            duration_ms=round((time.monotonic() - started) * 1000),
            progress_detail=(
                f"新聞偏好學習與自動勾選完成；處理 {result['candidate_count']} 條，"
                f"寫入 {result['changed_count']} 格，逐格回讀通過。"
            ),
            summary=result,
        )
        return result
    except Exception as exc:
        detail = "新聞偏好學習 Agent 失敗：" + _text(exc, 700)
        try:
            append_crawl_run_event(
                stream_log_path,
                {"type": "done", "ok": False, "error": detail},
            )
            finalize_operational_crawl_run(
                crawl_run_id,
                ok=False,
                duration_ms=round((time.monotonic() - started) * 1000),
                progress_detail=detail,
                failure_stage="news_selection_agent",
            )
        finally:
            raise


def selection_provenance(news_id: str) -> dict[str, Any]:
    """Return the latest verified automatic decision for one news item."""
    return _latest_agent_decisions(_load_audit()).get(_text(news_id, 80), {})


def selection_provenance_map() -> dict[str, dict[str, Any]]:
    """Return the latest verified automatic decisions without repeated file reads."""
    return _latest_agent_decisions(_load_audit())
