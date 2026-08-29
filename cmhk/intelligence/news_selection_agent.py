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

try:
    from opencc import OpenCC
except ImportError:  # pragma: no cover - deployment fallback
    OpenCC = None

from ai_config import api_key_candidates, load_ai_config
from ai_rate_limit import RateLimitedChatDeepSeek as ChatDeepSeek
from ai_response_compat import deepseek_nonthinking_parameters
from cmhk.crawl.run_registry import (
    append_crawl_run_event,
    finalize_operational_crawl_run,
    heartbeat_crawl_run,
    start_crawl_run,
)


ROOT = Path(__file__).resolve().parents[2]
OPERATION_AUDIT_ROOT = ROOT
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
SUPPLEMENT_BATCH_SIZE = max(
    1, min(8, int(os.environ.get("CMHK_NEWS_SELECTION_SUPPLEMENT_BATCH_SIZE", "5")))
)
WRITE_BATCH_ROWS = max(
    10, min(90, int(os.environ.get("CMHK_NEWS_SELECTION_WRITE_BATCH_ROWS", "80")))
)
REVIEW_SNAPSHOT_LOCK_TIMEOUT_SECONDS = max(
    5.0,
    min(
        120.0,
        float(os.environ.get("CMHK_NEWS_SELECTION_SNAPSHOT_LOCK_TIMEOUT_SECONDS", "60")),
    ),
)
VALID_STATUSES = {"接受", "不接受"}
FEISHU_BOT_PROFILE = (
    os.environ.get("CMHK_NEWS_SELECTION_FEISHU_PROFILE")
    or os.environ.get("CMHK_FEISHU_SHEET_EDIT_PROFILE")
    or "cli_a9575e70ae799cb2"
).strip()
SIMPLIFIED_CONVERTER = OpenCC("t2s") if OpenCC is not None else None


def _text(value: Any, limit: int = 1000) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()[:limit]


def _simplified(value: Any, limit: int = 1000) -> str:
    text = _text(value, limit)
    if SIMPLIFIED_CONVERTER is not None and text:
        text = SIMPLIFIED_CONVERTER.convert(text)
    return text[:limit]


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


def _record_verified_operation_footprints(
    decisions: list[dict[str, Any]],
    *,
    sheet_id: str,
    agent_run_id: str,
    model_name: str,
    recorded_at: str,
) -> int:
    """Write verified robot cell changes directly to the unified audit log."""
    from cmhk.auth.service import AuthService

    service = AuthService(OPERATION_AUDIT_ROOT)
    existing_keys = {
        str(details.get("automation_event_key") or "")
        for event in service.operation_audit(limit=1000)
        if isinstance(event, dict)
        and event.get("action") == "news_review.update"
        and isinstance((details := event.get("details")), dict)
        and details.get("automation_event_key")
    }
    actor = {
        "id": "news-auto-screening-bot",
        "name": "新闻自动初筛机器人",
        "role": "SYSTEM",
    }
    written = 0
    for decision in decisions:
        for field_key, field_label in (
            ("app", "纳入滚动栏"),
            ("weekly", "纳入周报"),
        ):
            if decision.get(f"{field_key}_before") != "待审核":
                continue
            after = str(decision.get(f"{field_key}_status") or "")
            event_key = "|".join((agent_run_id, str(decision["row_number"]), field_label, after))
            if event_key in existing_keys:
                continue
            service.record_operation(
                actor=actor,
                action="news_review.update",
                target=sheet_id,
                source="feishu_sheet",
                details={
                    "source_label": "新闻自动初筛",
                    "target_label": str(decision.get("title") or "")[:500],
                    "sheet_row": int(decision["row_number"]),
                    "decision_rows": [int(decision["row_number"])],
                    "field": field_label,
                    "before": "待审核",
                    "after": after,
                    "identity_note": "机器人写入后已逐格回读，并直接写入统一操作审计",
                    "agent_run_id": agent_run_id,
                    "agent_recorded_at": recorded_at,
                    "model": model_name,
                    "writer_profile": FEISHU_BOT_PROFILE,
                    "automation_event_key": event_key,
                },
            )
            existing_keys.add(event_key)
            written += 1
    return written


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


def _repair_missing_json_commas(value: Any, *, max_repairs: int = 8) -> dict[str, Any]:
    """Repair only parser-proven missing delimiters in an otherwise JSON object."""
    content = value if isinstance(value, str) else str(value or "")
    content = re.sub(r"^```(?:json)?\s*|\s*```$", "", content.strip(), flags=re.I)
    match = re.search(r"\{[\s\S]*\}", content)
    candidate = match.group(0) if match else content
    for _ in range(max(0, max_repairs)):
        try:
            parsed = json.loads(candidate)
        except json.JSONDecodeError as exc:
            if exc.msg != "Expecting ',' delimiter" or exc.pos >= len(candidate):
                raise
            next_char = candidate[exc.pos]
            if next_char not in {'"', "{", "["}:
                raise
            previous_index = exc.pos - 1
            while previous_index >= 0 and candidate[previous_index].isspace():
                previous_index -= 1
            if previous_index < 0 or candidate[previous_index] not in '"}]0123456789':
                raise
            candidate = candidate[: exc.pos] + "," + candidate[exc.pos :]
            continue
        if not isinstance(parsed, dict):
            raise ValueError("模型结果必须是 JSON 对象")
        return parsed
    raise ValueError("JSON 缺失分隔符超出有界修复范围")


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
    *,
    selection_date: str,
) -> list[dict[str, Any]]:
    target_ids = {
        _text(item.get("news_id"), 80)
        for item in new_items
        if isinstance(item, dict) and _text(item.get("news_id"), 80)
    }
    targets: list[dict[str, Any]] = []
    for row in rows:
        if _text(row.get("search_date"), 20) != selection_date:
            continue
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
                "search_date": _text(row.get("search_date"), 20),
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
    if config.get("api_keys"):
        primary_keys = api_key_candidates(config, model=primary_model)
    else:
        legacy_keys = config.get("strategy_api_keys") or []
        if isinstance(legacy_keys, str):
            legacy_keys = [legacy_keys]
        primary_keys = [
            _text(value, 500) for value in legacy_keys if _text(value, 500)
        ]
        if primary_key := _text(config.get("api_key"), 500):
            primary_keys.append(primary_key)
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
        "你是 CMHK 每日新闻选材偏好学习 Agent。你只从已提供的历史人工决策中归纳习惯，"
        "并对本轮候选分别判断 APP 滚动新闻与双周报。两个字段互相独立。"
        "接受表示符合历史取舍，不接受表示不符合或信息不足。"
        "不得把既有自动决策当成人工样本，不得补造新闻事实。"
        "请使用简体中文，只输出 JSON：learned_rules、avoid_patterns、app_preference_summary、"
        "weekly_preference_summary、decisions。decisions 每项必须有 news_id、"
        "app_status、weekly_status、app_confidence、weekly_confidence、reason。"
        "状态只能是接受或不接受，confidence 为 0 至 1。"
    )
    user_prompt = json.dumps(
        {
            "human_examples": examples,
            "current_candidates": targets,
            "instruction": "归纳可复用偏好并逐条判断；不可遗漏任何 current_candidates。",
        },
        ensure_ascii=False,
    )
    errors: list[str] = []
    for model_name, api_key in _model_routes():
        model = ChatDeepSeek(
            model=model_name,
            api_key=api_key,
            api_base=_text(config.get("base_url"), 500),
            extra_body=deepseek_nonthinking_parameters(
                {"response_format": {"type": "json_object"}}
            ),
            temperature=0.1,
            disable_streaming=True,
            max_retries=1,
            max_tokens=7000,
        )
        try:
            response = model.invoke(
                [SystemMessage(content=system_prompt), HumanMessage(content=user_prompt)]
            )
            response_content = getattr(response, "content", "")
            try:
                return _json_object(response_content), model_name
            except Exception as parse_exc:
                try:
                    repaired = _repair_missing_json_commas(response_content)
                    repaired["_format_repaired"] = True
                    return repaired, model_name
                except Exception:
                    pass
                repair_response = model.invoke(
                    [
                        SystemMessage(
                            content=(
                                "你是 JSON 格式修复器。只修复语法，不改变、增删或重新判断"
                                "任何字段和业务结论。只输出修复后的 JSON 对象。"
                            )
                        ),
                        HumanMessage(
                            content=json.dumps(
                                {
                                    "parser_error": _text(parse_exc, 300),
                                    "invalid_json": str(response_content or ""),
                                },
                                ensure_ascii=False,
                            )
                        ),
                    ]
                )
                repair_content = getattr(repair_response, "content", "")
                try:
                    repaired = _json_object(repair_content)
                except Exception:
                    repaired = _repair_missing_json_commas(repair_content)
                repaired["_format_repaired"] = True
                return repaired, model_name
        except Exception as exc:
            errors.append(f"{model_name}: {_text(exc, 180)}")
    raise RuntimeError("LangChain 模型路由全部失败；" + "；".join(errors[:4]))


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
            raise ValueError(f"模型遗漏候选 {target['news_id']}")
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
            if status not in VALID_STATUSES:
                status = "不接受"
            item[f"{field}_status"] = status
            item[f"{field}_confidence"] = round(confidence, 4)
        item["reason"] = _simplified(raw.get("reason"), 500) or "按历史人工取舍习惯判断"
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
        original_ids = {
            _text(item.get("news_id"), 80)
            for item in (payload.get("decisions") or [])
            if isinstance(item, dict)
        }
        supplemented_count = 0
        # Retry valid-but-incomplete JSON in small groups, then one candidate at
        # a time. Persistent omissions must fail the run, not be rewritten into
        # negative editorial decisions.
        for attempt in range(2):
            decided_ids = {
                _text(item.get("news_id"), 80)
                for item in (payload.get("decisions") or [])
                if isinstance(item, dict)
            }
            missing_targets = [
                item for item in batch if item["news_id"] not in decided_ids
            ]
            if not missing_targets:
                break
            supplement_size = SUPPLEMENT_BATCH_SIZE if attempt == 0 else 1
            for supplement_start in range(0, len(missing_targets), supplement_size):
                supplement_targets = missing_targets[
                    supplement_start : supplement_start + supplement_size
                ]
                supplement, supplement_model = _invoke_langchain(examples, supplement_targets)
                payload.setdefault("decisions", []).extend(supplement.get("decisions") or [])
                payload["_format_repaired"] = bool(
                    payload.get("_format_repaired") or supplement.get("_format_repaired")
                )
                model_name = ", ".join(dict.fromkeys([model_name, supplement_model]))
        decided_ids = {
            _text(item.get("news_id"), 80)
            for item in (payload.get("decisions") or [])
            if isinstance(item, dict)
        }
        supplemented_count = len(decided_ids - original_ids)
        missing_targets = [item for item in batch if item["news_id"] not in decided_ids]
        if missing_targets:
            missing_ids = ", ".join(item["news_id"] for item in missing_targets[:8])
            raise RuntimeError(
                f"LangChain 多轮补判后仍遗漏 {len(missing_targets)} 条候选：{missing_ids}"
            )
        payload["_supplemented_count"] = supplemented_count
        payload["_fallback_count"] = 0
        payloads.append(payload)
        model_names.append(model_name)
    first = payloads[0] if payloads else {}
    return {
        "_format_repaired": any(
            payload.get("_format_repaired") is True for payload in payloads
        ),
        "_supplemented_count": sum(
            int(payload.get("_supplemented_count") or 0) for payload in payloads
        ),
        "_fallback_count": sum(
            int(payload.get("_fallback_count") or 0) for payload in payloads
        ),
        "learned_rules": list(
            dict.fromkeys(
                _simplified(value, 300)
                for payload in payloads
                for value in (payload.get("learned_rules") or [])
                if _text(value, 300)
            )
        )[:12],
        "avoid_patterns": list(
            dict.fromkeys(
                _simplified(value, 300)
                for payload in payloads
                for value in (payload.get("avoid_patterns") or [])
                if _text(value, 300)
            )
        )[:12],
        "app_preference_summary": _simplified(first.get("app_preference_summary"), 1000),
        "weekly_preference_summary": _simplified(first.get("weekly_preference_summary"), 1000),
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
        _simplified(value, 300)
        for value in (payload.get("learned_rules") or [])
        if _text(value, 300)
    ][:12]
    avoid = [
        _simplified(value, 300)
        for value in (payload.get("avoid_patterns") or [])
        if _text(value, 300)
    ][:12]
    bullet_rules = "\n".join(f"- {value}" for value in rules) or "- 暂无足够人工样本可归纳。"
    bullet_avoid = "\n".join(f"- {value}" for value in avoid) or "- 暂无稳定排除模式。"
    return f'''---
name: cmhk-news-selection-preference
description: 学习 CMHK 每日新闻历史人工选材习惯，分别判断 APP 滚动新闻与双周报候选；仅用于本轮新增、检索日期为当天且仍待审核的新闻。
---

# CMHK 新闻选材偏好

## 不可变边界

- APP 与双周报为两个独立决策，不得互相复制。
- 不覆盖任何既有人工决策；只处理本轮新增且仍为「待审核」的字段。
- 历史自动决策不作训练样本；人工改正自动结果后，改正值可作新样本。
- 自动结果只使用「接受」或「不接受」，不写「暂缓」。
- 不补造新闻事实；原文、日期或证据不足时保守标为「不接受」。
- 只修改本轮新增且检索日期等于当天的新闻；过往日期只可作学习样本。

## 最新学习摘要

- 更新时间：{_now_iso()}
- LangChain 模型：{_text(model_name, 120)}
- 有效人工样本：{human_example_count}
- 已识别人工纠正：{corrected_count}
- APP 偏好：{_simplified(payload.get('app_preference_summary'), 1000) or '尚未形成稳定摘要'}
- 双周报偏好：{_simplified(payload.get('weekly_preference_summary'), 1000) or '尚未形成稳定摘要'}

## 已学习规则

{bullet_rules}

## 已学习排除模式

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
        trigger="新闻自动初筛",
        scope=f"爬虫后选材（{_text(idempotency_key, 120) or '未命名轮次'}）",
        task_kind="news-selection-agent",
        parent_crawl_run_id=parent_crawl_run_id,
        phase="读取人工样本",
        progress_detail="正在读取历史人工 APP 与双周报勾选习惯。",
    )
    crawl_run_id = _text(run.get("crawl_run_id"), 120)
    stream_log_path = _text(run.get("stream_log_path"), 1600)
    try:
        state = _load_state()
        completed_keys = state.get("completed_keys") if isinstance(state.get("completed_keys"), dict) else {}
        if idempotency_key and idempotency_key in completed_keys:
            detail = "同一爬虫轮次已完成自动勾选，直接复用已验证结果。"
            _progress(crawl_run_id, stream_log_path, "幂等结果复用", detail)
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

        snapshot = news_review_sheet.review_sheet_snapshot(
            sheet_id=sheet_id,
            lock_timeout_seconds=REVIEW_SNAPSHOT_LOCK_TIMEOUT_SECONDS,
        )
        rows = _snapshot_rows(snapshot)
        audits = _load_audit()
        examples, corrected_count = _human_examples(rows, _latest_agent_decisions(audits))
        selection_date_match = re.match(r"(\d{4}-\d{2}-\d{2})", idempotency_key or "")
        selection_date = (
            selection_date_match.group(1) if selection_date_match else _now_iso()[:10]
        )
        targets = _target_rows(
            rows,
            new_items,
            selection_date=selection_date,
        )
        _progress(
            crawl_run_id,
            stream_log_path,
            "人工样本隔离",
            f"读取审核表 {len(rows)} 条；学习历史人工样本 {len(examples)} 条，排除既有自动结果，识别人工纠正 {corrected_count} 条；当天且属于本轮的新候选 {len(targets)} 条。",
        )
        if not targets:
            result = {
                "status": "completed",
                "candidate_count": 0,
                "changed_count": 0,
                "readback_verified": True,
                "operation_audit_count": 0,
                "reason": "本轮没有检索日期为当天且仍待审核的新候选",
                "task_run_id": crawl_run_id,
            }
            _progress(crawl_run_id, stream_log_path, "无待审候选", result["reason"])
        else:
            _progress(
                crawl_run_id,
                stream_log_path,
                "LangChain 偏好学习",
                f"使用 {len(examples)} 条人工样本分析 {len(targets)} 条当天新候选；APP 与双周报分开判断，只输出接受或不接受。",
            )
            model_payload, model_name = _invoke_langchain_batches(
                examples,
                targets,
                progress_callback=lambda batch, total, count: _progress(
                    crawl_run_id,
                    stream_log_path,
                    "LangChain 分批判断",
                    f"正在处理第 {batch}/{total} 批，本批 {count} 条当天候选。",
                ),
            )
            if model_payload.get("_format_repaired") is True:
                _progress(
                    crawl_run_id,
                    stream_log_path,
                    "模型格式自动修复",
                    "模型首次返回的 JSON 格式不完整；已通过 LangChain 仅修复语法并重新校验，业务判断未重写。",
                )
            if int(model_payload.get("_supplemented_count") or 0):
                _progress(
                    crawl_run_id,
                    stream_log_path,
                    "遗漏候选补判",
                    f"首轮模型结果遗漏候选；已单独补判 {int(model_payload['_supplemented_count'])} 条并通过完整性校验。",
                )
            if int(model_payload.get("_fallback_count") or 0):
                _progress(
                    crawl_run_id,
                    stream_log_path,
                    "保守兜底判断",
                    f"模型多轮仍遗漏 {int(model_payload['_fallback_count'])} 条；已按信息不足标记为不接受，未放大进入 APP 或双周报的范围。",
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
                f"已把最新人工偏好摘要写入 {_display_path(SKILL_PATH)}，供下次爬虫继续学习。",
            )
            changed_count = 0
            operation_audit_count = 0
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
                    writer_identity="bot",
                    writer_profile=FEISHU_BOT_PROFILE,
                )
                if write_result.get("readbackVerified") is not True:
                    raise RuntimeError("自动勾选后未取得逐格回读证据")
                changed_count += int(write_result.get("changedCount") or 0)
                app_batch_accept = sum(
                    item["app_before"] == "待审核" and item["app_status"] == "接受"
                    for item in decision_batch
                )
                weekly_batch_accept = sum(
                    item["weekly_before"] == "待审核" and item["weekly_status"] == "接受"
                    for item in decision_batch
                )
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
                            "writer_identity": "bot",
                            "writer_profile": FEISHU_BOT_PROFILE,
                        }
                    )
                operation_audit_count += _record_verified_operation_footprints(
                    decision_batch,
                    sheet_id=sheet_id,
                    agent_run_id=crawl_run_id,
                    model_name=model_name,
                    recorded_at=recorded_at,
                )
                _progress(
                    crawl_run_id,
                    stream_log_path,
                    "机器人分批写入与回读",
                    f"第 {write_batch_index}/{write_batch_total} 批由飞书机器人 {FEISHU_BOT_PROFILE} 写入 {len(changes)} 格；滚动栏接受 {app_batch_accept} 条、滚动栏不接受 {sum(item['app_before'] == '待审核' for item in decision_batch) - app_batch_accept} 条，周报接受 {weekly_batch_accept} 条、周报不接受 {sum(item['weekly_before'] == '待审核' for item in decision_batch) - weekly_batch_accept} 条；逐格回读通过。",
                )
            result = {
                "status": "completed",
                "candidate_count": len(decisions),
                "changed_count": changed_count,
                "app_accepted_count": sum(
                    item["app_before"] == "待审核"
                    and item["app_status"] == "接受"
                    for item in decisions
                ),
                "weekly_accepted_count": sum(
                    item["weekly_before"] == "待审核"
                    and item["weekly_status"] == "接受"
                    for item in decisions
                ),
                "deferred_field_count": 0,
                "human_example_count": len(examples),
                "human_correction_count": corrected_count,
                "model": model_name,
                "skill_path": _display_path(SKILL_PATH),
                "audit_path": _display_path(AUDIT_PATH),
                "readback_verified": True,
                "operation_audit_count": operation_audit_count,
                "writer_identity": "bot",
                "writer_profile": FEISHU_BOT_PROFILE,
                "task_run_id": crawl_run_id,
            }
            _progress(
                crawl_run_id,
                stream_log_path,
                "自动勾选与回读完成",
                f"仅处理检索日期为 {selection_date} 的本轮新增新闻 {len(decisions)} 条，由飞书机器人写入 {result['changed_count']} 格；滚动栏接受 {result['app_accepted_count']} 条、不接受 {sum(item['app_before'] == '待审核' for item in decisions) - result['app_accepted_count']} 条，周报接受 {result['weekly_accepted_count']} 条、不接受 {sum(item['weekly_before'] == '待审核' for item in decisions) - result['weekly_accepted_count']} 条；逐格回读全部通过。",
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
                f"新闻自动初筛完成；处理 {result['candidate_count']} 条，"
                f"由机器人写入 {result['changed_count']} 格，逐格回读通过。"
            ),
            summary=result,
        )
        return result
    except Exception as exc:
        detail = "新闻自动初筛失败：" + _text(exc, 700)
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
