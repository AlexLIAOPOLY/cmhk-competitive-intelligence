"""Fail-closed real-time monitoring for the CMHK competitive-intelligence app.

The monitor is deliberately independent from the crawler and web processes so
it can observe failures in either one.  Group delivery is disabled by default.
An incident may be delivered only when all of these gates pass:

1. ``CMHK_ALERT_NOTIFICATIONS=1`` is explicitly present in the monitor process.
2. The incident was first detected while that gate was enabled.
3. One internal-AI diagnosis has completed and passed the output contract.
4. The configured lark-cli profile resolves to the expected bot app id.
5. Both live chat names/modes/statuses match the checked-in allowlist.

Healthy and heartbeat messages are never sent to a chat.  When a delivered
incident later clears, the original shared card may be edited in place to show
the recovery; no additional recovery message is sent.
"""
from __future__ import annotations

import argparse
import faulthandler
import fcntl
import hashlib
import json
import os
import re
import signal
import subprocess
import sys
import time
import urllib.error
import urllib.request
from datetime import date, datetime, time as clock_time, timedelta
from pathlib import Path
from typing import Any, Callable, Iterable
from zoneinfo import ZoneInfo

from ai_response_compat import final_chat_message_text, load_json_response, prepare_structured_chat_body
from ai_key_rotation import open_llm_request
from cmhk.integrations.feishu_sheet_rollover import (
    active_part,
    capacity_decision,
    record_active_part,
    sheet_url,
    timestamped_part_title,
)
from cmhk.integrations.feishu_runtime import lark_cli_env, portable_lark_argv

try:
    from opencc import OpenCC
except ImportError:  # local monitor prompts already require simplified Chinese
    OpenCC = None  # type: ignore[assignment]


ROOT = Path(__file__).resolve().parent
HKT = ZoneInfo("Asia/Hong_Kong")

STABLE_LOG_CONDITION_KEYS = {
    "scheduler-log-error",
    "feishu-media-metrics-error",
    "project-monitor-log-error",
    "project-monitor-card-actions-log-error",
    "web-log-fatal",
    "ai-http-400-burst",
    "ai-timeout-burst",
    "web-background-error",
}
AUTO_RECOVERING_LOG_CONDITION_KEYS = {
    "scheduler-log-error",
    "project-monitor-card-actions-log-error",
    "ai-http-400-burst",
    "ai-timeout-burst",
    "web-background-error",
}
LOG_CONDITION_SERVICE_IDS = {
    "scheduler-log-error": "frequency-scheduler",
    "feishu-media-metrics-error": "feishu-media-metrics",
    "project-monitor-log-error": "project-monitor",
    "project-monitor-card-actions-log-error": "project-monitor-card-actions",
    "web-log-fatal": "web-app",
    "ai-http-400-burst": "web-app",
    "ai-timeout-burst": "web-app",
    "web-background-error": "web-app",
}
STATEFUL_CONDITION_PREFIXES = (
    "data-quality:",
    "crawl-task-failed:",
    "general-task-failed:",
    "strategic-slot-",
    "strategic-monitor-heartbeat-stale",
    "strategic-deferred-backlog:",
    "launchd:",
    "ui-runtime:",
)
DEFAULT_CONFIG_PATH = ROOT / "config" / "project_monitor.json"
SEVERITY_ORDER = {"P1": 0, "P2": 1, "P3": 2}
SEVERITY_LABELS = {
    "P1": "紧急",
    "P2": "高",
    "P3": "中",
}
ERROR_LEDGER_COLUMNS = (
    "告警ID",
    "故障时间",
    "首次发现时间",
    "重要等级",
    "重要等级理由",
    "任务",
    "组件",
    "故障原因",
    "故障影响",
    "错误证据",
    "建议解决方案",
    "是否需人工介入",
    "处理人员",
    "处理状态",
    "最近同步时间",
    "AI模型",
    "群通知状态",
)
# M/N are deliberately absent: 处理人员 and 处理状态 belong to operators.
# O is a write timestamp and therefore is also excluded from content hashing.
ERROR_LEDGER_HASH_INDEXES = tuple(range(12)) + (15, 16)
ERROR_LEDGER_TARGET_KEY = "error_ledger"
ERROR_LEDGER_OPERATIONAL_MAX_ROWS = max(
    1000,
    int(os.environ.get("CMHK_ERROR_LEDGER_MAX_ROWS", "200000")),
)
ERROR_LEDGER_READ_CHUNK_ROWS = max(
    10,
    int(os.environ.get("CMHK_ERROR_LEDGER_READ_CHUNK_ROWS", "50")),
)
ERROR_LEDGER_SYNC_BUDGET_SECONDS = max(
    30,
    int(os.environ.get("CMHK_ERROR_LEDGER_SYNC_BUDGET_SECONDS", "90")),
)
TERMINAL_STATUSES = {"completed", "failed"}
SENSITIVE_RE = re.compile(
    r"(?i)(authorization\s*[:=]\s*bearer\s+|api[_-]?key\s*[:=]\s*|app[_-]?secret\s*[:=]\s*)[^\s,;\"']+"
)
BEARER_RE = re.compile(r"(?i)bearer\s+[A-Za-z0-9._~+\-/=]+")
SECRET_TOKEN_RE = re.compile(r"\b(?:sk|ak|sess|token)[-_][A-Za-z0-9._-]{12,}\b", re.I)
_T2S_CONVERTER = OpenCC("t2s") if OpenCC is not None else None


def _env_true(value: object) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


def _iso(now: datetime | None = None) -> str:
    return (now or datetime.now(HKT)).astimezone(HKT).isoformat(timespec="seconds")


def _parse_datetime(value: object) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=HKT)
    return parsed.astimezone(HKT)


def _parse_process_start(value: object) -> datetime | None:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    if not text:
        return None
    try:
        return datetime.strptime(text, "%a %b %d %H:%M:%S %Y").replace(tzinfo=HKT)
    except ValueError:
        return None


def _read_json(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, TypeError, ValueError, json.JSONDecodeError):
        return default


def _atomic_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    os.replace(temporary, path)


def _append_jsonl(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, ensure_ascii=False) + "\n")


def _redact(value: object, limit: int = 1800) -> str:
    text = str(value or "").replace("\x00", " ").strip()
    text = SENSITIVE_RE.sub(lambda match: match.group(1) + "[REDACTED]", text)
    text = BEARER_RE.sub("Bearer [REDACTED]", text)
    text = SECRET_TOKEN_RE.sub("[REDACTED]", text)
    text = re.sub(r"([?&](?:token|key|secret|signature)=)[^&\s]+", r"\1[REDACTED]", text, flags=re.I)
    return text[:limit]


def _to_simplified(value: object) -> str:
    text = str(value or "")
    converted = _T2S_CONVERTER.convert(text) if _T2S_CONVERTER is not None else text
    # OpenCC performs script conversion, but this Hong Kong variant remains a
    # valid simplified glyph rather than the standard Mainland wording.
    return converted.replace("甚么", "什么")


def _solution_text(value: object, limit: int = 450) -> str:
    text = _to_simplified(_redact(value, limit))
    return re.sub(r"^\s*(?:\d{1,2}\s*[.\u3001)]|[-•])\s*", "", text).strip()


def _alert_plain(value: object, limit: int = 1800) -> str:
    """Keep alert text readable while preventing Feishu mention-tag injection."""
    return _redact(value, limit).replace("<", "＜").replace(">", "＞").replace("\r", "")


def _fingerprint(*parts: object) -> str:
    raw = "\x1f".join(str(part or "") for part in parts)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]


def _command_env(base: dict[str, str] | None = None) -> dict[str, str]:
    return lark_cli_env(base)


def _default_command_runner(
    argv: list[str],
    *,
    cwd: Path,
    env: dict[str, str],
    timeout: float,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        argv,
        cwd=cwd,
        env=env,
        text=True,
        capture_output=True,
        timeout=timeout,
        check=False,
    )


def _default_http_getter(url: str, timeout: float) -> dict[str, Any]:
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    request = urllib.request.Request(
        url,
        headers={"User-Agent": "CMHK-Project-Monitor/1.0", "Cache-Control": "no-cache"},
    )
    with opener.open(request, timeout=timeout) as response:
        payload = json.loads(response.read().decode("utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("health endpoint did not return a JSON object")
    return payload


def load_public_status(
    runtime_root: Path | str | None = None,
    *,
    state_dir: Path | str | None = None,
) -> dict[str, Any]:
    """Read the redacted monitor status without importing or starting the daemon."""
    root = Path(runtime_root or ROOT)
    directory = Path(state_dir or (root / "var" / "project_monitor"))
    payload = _read_json(directory / "status.json", {})
    if isinstance(payload, dict) and payload:
        return payload
    return {
        "ok": False,
        "mode": "not_started",
        "notifications_enabled": False,
        "message_policy": "errors_only_after_ai",
        "active_incidents": [],
    }


class ProjectMonitor:
    def __init__(
        self,
        *,
        runtime_root: Path | str | None = None,
        config_path: Path | str | None = None,
        state_dir: Path | str | None = None,
        environ: dict[str, str] | None = None,
        now_fn: Callable[[], datetime] | None = None,
        command_runner: Callable[..., subprocess.CompletedProcess[str]] | None = None,
        http_getter: Callable[[str, float], dict[str, Any]] | None = None,
        ai_diagnoser: Callable[[dict[str, Any]], dict[str, Any]] | None = None,
    ) -> None:
        self.runtime_root = Path(runtime_root or os.environ.get("CMHK_MONITOR_RUNTIME_ROOT") or ROOT)
        self.config_path = Path(config_path or DEFAULT_CONFIG_PATH)
        self.config = _read_json(self.config_path, {})
        if not isinstance(self.config, dict) or int(self.config.get("version") or 0) != 1:
            raise RuntimeError(f"invalid monitor config: {self.config_path}")
        self.state_dir = Path(
            state_dir
            or os.environ.get("CMHK_MONITOR_STATE_DIR")
            or (self.runtime_root / "var" / "project_monitor")
        )
        self.state_path = self.state_dir / "state.json"
        self.status_path = self.state_dir / "status.json"
        self.events_path = self.state_dir / "events.jsonl"
        self.preview_path = self.state_dir / "latest_preview.md"
        self.lock_path = self.state_dir / "monitor.lock"
        self.environ = dict(environ or os.environ)
        self.now_fn = now_fn or (lambda: datetime.now(HKT))
        self.command_runner = command_runner or _default_command_runner
        self._uses_default_command_runner = command_runner is None
        self.http_getter = http_getter or _default_http_getter
        self.ai_diagnoser = ai_diagnoser
        self.state = _read_json(self.state_path, {})
        if not isinstance(self.state, dict):
            self.state = {}
        self.state.setdefault("version", 1)
        self.state.setdefault("initialized_at_hkt", _iso(self.now()))
        self.state.setdefault("incidents", {})
        self.state.setdefault("conditions", {})
        self.state.setdefault("counters", {})
        self.state.setdefault("log_offsets", {})
        self.state.setdefault("service_instances", {})
        self.state.setdefault("cycles", 0)
        ledger_state = self.state.get("error_ledger")
        if not isinstance(ledger_state, dict):
            ledger_state = {}
            self.state["error_ledger"] = ledger_state
        if not isinstance(ledger_state.get("rows"), dict):
            ledger_state["rows"] = {}
        self._ledger_verified_this_process = False

    def now(self) -> datetime:
        value = self.now_fn()
        if value.tzinfo is None:
            value = value.replace(tzinfo=HKT)
        return value.astimezone(HKT)

    @property
    def notifications_enabled(self) -> bool:
        return _env_true(self.environ.get("CMHK_ALERT_NOTIFICATIONS"))

    @property
    def configured_targets(self) -> list[dict[str, Any]]:
        return [item for item in (self.config.get("targets") or []) if isinstance(item, dict)]

    @property
    def alert_targets(self) -> list[dict[str, Any]]:
        """Groups that still receive incident cards.

        Previous groups stay in ``targets`` for historical card-callback trust
        checks, but only entries with ``alert_notify`` receive new cards.
        """
        override = str(self.environ.get("CMHK_ALERT_TARGET_ROLES") or "").strip()
        if override:
            wanted = {part.strip() for part in override.split(",") if part.strip()}
            return [item for item in self.configured_targets if str(item.get("role") or "") in wanted]
        return [item for item in self.configured_targets if item.get("alert_notify", True)]

    def _target_accepts_incident(
        self, incident: dict[str, Any], target: dict[str, Any]
    ) -> bool:
        """Keep a route cutover from replaying already-open incidents."""
        notify_from = _parse_datetime(target.get("notify_from_hkt"))
        if not notify_from:
            return True
        first_seen = _parse_datetime(incident.get("first_seen_at_hkt"))
        return bool(first_seen and first_seen >= notify_from)

    @property
    def ai_enabled(self) -> bool:
        return _env_true(self.environ.get("CMHK_ALERT_AI_DIAGNOSIS", "1"))

    @property
    def error_ledger_enabled(self) -> bool:
        config = self.config.get("error_ledger")
        configured = isinstance(config, dict) and bool(config.get("enabled"))
        value = self.environ.get("CMHK_ERROR_LEDGER_ENABLED")
        return configured and (True if value is None else _env_true(value))

    @property
    def resolution_message_updates_enabled(self) -> bool:
        config = self.config.get("resolution_message_updates")
        return isinstance(config, dict) and bool(config.get("enabled"))

    def _run(self, argv: list[str], timeout: float = 20) -> subprocess.CompletedProcess[str]:
        return self.command_runner(
            portable_lark_argv(argv, self.environ) if self._uses_default_command_runner else argv,
            cwd=self.runtime_root,
            env=_command_env(self.environ),
            timeout=timeout,
        )

    def _issue(
        self,
        *,
        condition_key: str,
        component: str,
        task_name: str,
        severity: str,
        summary: str,
        error: str,
        impact: str,
        suggestions: Iterable[str],
        occurred_at_hkt: str = "",
        evidence: Iterable[str] = (),
        terminal: bool = False,
    ) -> dict[str, Any]:
        if severity not in SEVERITY_ORDER:
            severity = "P2"
        return {
            "condition_key": str(condition_key),
            "component": str(component),
            "task_name": str(task_name),
            "severity": severity,
            "summary": _redact(summary, 500),
            "error": _redact(error),
            "impact": _redact(impact, 700),
            "suggestions": [_redact(item, 500) for item in suggestions if str(item).strip()][:4],
            "occurred_at_hkt": str(occurred_at_hkt or _iso(self.now())),
            "evidence": [_redact(item, 500) for item in evidence if str(item).strip()][:6],
            "terminal": bool(terminal),
        }

    def _detector_failure(self, detector: str, exc: Exception) -> dict[str, Any]:
        return self._issue(
            condition_key=f"monitor-detector:{detector}",
            component="project-monitor",
            task_name=f"监控探针 {detector}",
            severity="P2",
            summary="监控探针执行失败",
            error=f"{type(exc).__name__}: {exc}",
            impact="该探针对应的主项目故障可能暂时无法被发现；其他探针仍继续运行。",
            suggestions=[
                "检查监控进程本地日志与探针输入文件权限。",
                "修复后执行一次只读 --once 验证，不要触发生产爬虫或群消息。",
            ],
        )

    def collect_issues(self) -> list[dict[str, Any]]:
        issues: list[dict[str, Any]] = []
        detectors = (
            ("launch-services", self._detect_launch_services),
            ("web-health", self._detect_web_health),
            ("ui-runtime-incidents", self._detect_ui_runtime_incidents),
            ("crawl-runs", self._detect_crawl_runs),
            ("general-tasks", self._detect_general_tasks),
            ("scheduler-pending", self._detect_scheduler_pending),
            ("strategic-monitor-heartbeat", self._detect_strategic_monitor_heartbeat),
            ("strategic-slots", self._detect_strategic_slots),
            ("strategic-content-quality", self._detect_strategic_content_quality),
            ("feishu-media-metrics", self._detect_feishu_media_metrics),
            ("runtime-logs", self._detect_runtime_logs),
        )
        for name, detector in detectors:
            self.state["current_detector"] = name
            _atomic_json(self.state_path, self.state)
            try:
                issues.extend(detector())
            except Exception as exc:  # each probe is an independent fault domain
                issues.append(self._detector_failure(name, exc))
        self.state.pop("current_detector", None)
        excluded = {str(item) for item in self.config.get("excluded_components") or []}
        return [
            issue
            for issue in issues
            if issue.get("component") not in excluded
            and not any(value in str(issue.get("condition_key") or "") for value in excluded)
        ]

    def _detect_ui_runtime_incidents(self) -> list[dict[str, Any]]:
        """Surface failures which reached a user-visible fallback but used to be swallowed."""
        path = self.runtime_root / "var" / "ui_runtime_incidents.json"
        payload = _read_json(path, {})
        records = payload.get("incidents") if isinstance(payload, dict) else {}
        if not isinstance(records, dict):
            return []
        issues: list[dict[str, Any]] = []
        for incident_type, record in records.items():
            if not isinstance(record, dict) or record.get("status") != "open":
                continue
            issues.append(
                self._issue(
                    condition_key=f"ui-runtime:{incident_type}",
                    component=str(record.get("component") or "web-app"),
                    task_name=str(record.get("task_name") or "用户界面实时功能"),
                    severity=str(record.get("severity") or "P2"),
                    summary=str(record.get("summary") or "用户界面功能降级"),
                    error=str(record.get("error") or "界面已进入失败状态，未记录具体错误"),
                    impact=str(record.get("impact") or "至少一项用户可见功能未完成。"),
                    suggestions=record.get("suggestions") or ["核对服务日志并只恢复失败步骤。"],
                    occurred_at_hkt=str(record.get("first_seen_at_hkt") or record.get("last_seen_at_hkt") or ""),
                    evidence=[str(path), json.dumps(record.get("context") or {}, ensure_ascii=False)],
                )
            )
        return issues

    def _detect_launch_services(self) -> list[dict[str, Any]]:
        issues: list[dict[str, Any]] = []
        domain = f"gui/{os.getuid()}"
        for service in self.config.get("services") or []:
            label = str(service.get("launchd_label") or "")
            if not label:
                continue
            proc = self._run(["launchctl", "print", f"{domain}/{label}"], timeout=10)
            output = (proc.stdout or "") + "\n" + (proc.stderr or "")
            state_match = re.search(r"(?m)^\s*state\s*=\s*([^\s]+)", output)
            state = state_match.group(1).strip() if state_match else "unknown"
            if proc.returncode == 0 and state == "running":
                pid_match = re.search(r"(?m)^\s*pid\s*=\s*(\d+)", output)
                pid = int(pid_match.group(1)) if pid_match else 0
                if pid:
                    instances = self.state.setdefault("service_instances", {})
                    previous = instances.get(label) if isinstance(instances, dict) else None
                    if not isinstance(previous, dict) or int(previous.get("pid") or 0) != pid:
                        started_proc = self._run(["ps", "-p", str(pid), "-o", "lstart="], timeout=5)
                        started = (
                            _parse_process_start(started_proc.stdout)
                            if started_proc.returncode == 0
                            else None
                        )
                        instances[label] = {
                            "service_id": str(service.get("id") or label),
                            "pid": pid,
                            "started_at_hkt": _iso(started or self.now()),
                            "observed_at_hkt": _iso(self.now()),
                        }
                    else:
                        previous["observed_at_hkt"] = _iso(self.now())
                continue
            exit_match = re.search(r"(?m)^\s*last exit code\s*=\s*([^\n]+)", output)
            last_exit = exit_match.group(1).strip() if exit_match else "未读取"
            issues.append(
                self._issue(
                    condition_key=f"launchd:{label}",
                    component=str(service.get("id") or label),
                    task_name=str(service.get("name") or label),
                    severity=str(service.get("severity") or "P1"),
                    summary="主项目常驻服务未运行",
                    error=f"launchd state={state}; last_exit={last_exit}; return_code={proc.returncode}",
                    impact="对应的爬虫、定时任务或Web能力可能停止，后续计划任务可能漏跑。",
                    suggestions=[
                        f"先读取 launchctl print {domain}/{label} 与对应 stderr 日志。",
                        "确认没有同类任务正在执行后，再按既有 LaunchAgent 流程恢复服务。",
                        "恢复后交叉检查任务归档、/api/status 与 /api/task-runs，禁止盲目补跑。",
                    ],
                    evidence=[f"launchd:{label}", _redact(output[-800:], 800)],
                )
            )
        return issues

    def _detect_web_health(self) -> list[dict[str, Any]]:
        issues: list[dict[str, Any]] = []
        key = "web-health"
        counters = self.state.setdefault("counters", {})
        try:
            payload = self.http_getter(str(self.config.get("web_health_url")), 6)
            if not payload.get("ok"):
                raise RuntimeError(str(payload.get("error") or "health endpoint returned ok=false"))
            counters[key] = 0
        except Exception as exc:
            counters[key] = int(counters.get(key) or 0) + 1
            if counters[key] >= 2:
                issues.append(
                    self._issue(
                        condition_key=key,
                        component="web-app",
                        task_name="主项目Web健康检查",
                        severity="P1",
                        summary="主项目Web接口连续不可用",
                        error=f"连续 {counters[key]} 次健康检查失败：{type(exc).__name__}: {exc}",
                        impact="管理页面、任务状态读取和内嵌战略监视器可能不可用。",
                        suggestions=[
                            "检查 com.liaowang.cmhk-web-app 的 launchd 状态和 stderr 日志。",
                            "确认 8765 端口监听与 /api/status 响应，再决定是否重启。",
                            "重启前确认没有报告、TTS或战略新闻任务在执行，避免中断任务。",
                        ],
                        evidence=[str(self.config.get("web_health_url"))],
                    )
                )
            return issues

        status = payload.get("status") if isinstance(payload.get("status"), dict) else {}
        visuals = status.get("visuals") if isinstance(status.get("visuals"), dict) else {}
        quality = visuals.get("quality") if isinstance(visuals.get("quality"), dict) else {}
        crawl = visuals.get("crawl") if isinstance(visuals.get("crawl"), dict) else {}
        failed = int(quality.get("failed") or 0)
        success_rate = int(crawl.get("successRate") or 0)
        completed_at = str(crawl.get("completedAt") or "unknown")
        if failed > 0 or (success_rate and success_rate < 95):
            issues.append(
                self._issue(
                    condition_key=f"data-quality:{completed_at}:{failed}:{success_rate}",
                    component="crawl",
                    task_name="主爬虫数据质量门禁",
                    severity="P3",
                    summary="主爬虫存在失败或未通过质量门禁的数据",
                    error=f"failed_rows={failed}; crawl_success_rate={success_rate}%",
                    impact="系统仍可保留旧数据或部分结果，但相关指标可能不是本轮完整更新。",
                    suggestions=[
                        "查看失败行及来源级错误，区分网站变更、网络失败和字段抽取失败。",
                        "只重试受影响来源；保留旧数据和证据边界，不要把部分成功标成全量成功。",
                    ],
                    occurred_at_hkt=completed_at,
                    evidence=["/api/status", f"quality.failed={failed}", f"crawl.successRate={success_rate}"],
                )
            )
        return issues

    def _lookback_cutoff(self) -> datetime:
        hours = max(1, min(720, int(self.config.get("lookback_hours") or 48)))
        return self.now() - timedelta(hours=hours)

    def _task_stale_seconds(self, kind: str, default: int) -> int:
        for item in self.config.get("task_kinds") or []:
            if str(item.get("id") or "") == kind:
                return max(60, int(item.get("stale_after_seconds") or default))
        return default

    def _task_name(self, kind: str, fallback: str = "") -> str:
        for item in self.config.get("task_kinds") or []:
            if str(item.get("id") or "") == kind:
                return str(item.get("name") or fallback or kind)
        return fallback or kind or "后台任务"

    def _failure_severity(self, kind: str, stage: str) -> str:
        if stage in {"crawl", "feishu_sync", "strategic_news"}:
            return "P1"
        if kind in {"crawl", "strategic-news", "executive-intelligence-refresh"}:
            return "P2"
        if kind in {"weekly-report", "carrier-performance"}:
            return "P2"
        return "P3"

    def _failure_suggestions(self, kind: str, stage: str) -> list[str]:
        mapping = {
            "crawl": [
                "查看本轮完整流日志，定位失败行和来源，不要先重跑全部来源。",
                "检查网络、DNS、目标站结构与历史结果回退状态。",
            ],
            "feishu_sync": [
                "使用无代理环境检查飞书认证、DNS、表格权限和目标字段。",
                "先读回任务归档确认是否已写入，避免重复写入或重复通知。",
            ],
            "four_database_feishu_log": [
                "检查飞书“四库爬虫明细日志”的认证、权限、DNS、真实数据末行和写后回读范围。",
                "先用事件ID回读确认是否已经写入；只补写缺失日志，禁止重跑已完成的官方来源抓取、AI洞察或页面发布。",
            ],
            "agent_review": [
                "检查 Agent run_id、节点完整性、超时和待恢复状态。",
                "保留抓取结果，只恢复审核阶段，不重新触发已完成抓取。",
            ],
            "strategic_news": [
                "检查对应 07:30/14:00 归档、进程锁、候选队列与飞书回读。",
                "先确认是否已经完成或发送，禁止直接补跑造成重复消息。",
            ],
            "executive_intelligence_refresh": [
                "检查失败域、模型回退原因、证据哈希和公开页面验证状态。",
                "保留上一版可用数据，修复失败阶段后再执行有界恢复。",
            ],
            "financial_frontend_publish": [
                "检查 GitHub Pages 发布结果、site_version、HTTPS和关键资源状态。",
                "不要把数据库成功误报为完整前端发布成功。",
            ],
            "news_bridge": [
                "检查已完成爬虫线索是否进入战略新闻桥接队列。",
                "只恢复桥接阶段，避免重跑主爬虫。",
            ],
            "audio-generation": [
                "检查 TTS 模型、ffmpeg、真实字幕时间戳和临时文件日志。",
                "Word报告若已成功应继续保留，并单独恢复音频阶段。",
            ],
        }
        return mapping.get(stage) or mapping.get(kind) or [
            "读取该任务完整日志和最后心跳，确认实际失败阶段。",
            "修复后只恢复未完成阶段，避免重复执行已经成功的外部写入。",
        ]

    @staticmethod
    def _is_verified_intelligence_fallback(run: dict[str, Any]) -> bool:
        """Recognize archives whose deterministic fallback passed every gate."""
        if str(run.get("task_kind") or "") != "executive-intelligence-refresh":
            return False
        summary = run.get("operational_summary")
        summary = summary if isinstance(summary, dict) else {}
        analysis = summary.get("model_analysis")
        analysis = analysis if isinstance(analysis, dict) else {}
        pages = summary.get("pages_publish")
        pages = pages if isinstance(pages, dict) else {}
        expected = int(analysis.get("focuses_expected") or 0)
        passed = int(analysis.get("focuses_passed") or 0)
        return bool(
            summary.get("status") == "completed_with_fallback"
            and analysis.get("fallback_used")
            and expected > 0
            and passed == expected
            and pages.get("ok")
        )

    def _detect_crawl_runs(self) -> list[dict[str, Any]]:
        path = self.runtime_root / "agent_knowledge" / "crawl_run_logs" / "index.json"
        payload = _read_json(path, [])
        runs = payload if isinstance(payload, list) else []
        cutoff = self._lookback_cutoff()
        latest_success_by_kind: dict[str, datetime] = {}
        for run in runs:
            if not isinstance(run, dict) or (
                str(run.get("run_status") or "") != "completed"
                and not self._is_verified_intelligence_fallback(run)
            ):
                continue
            kind = str(run.get("task_kind") or "crawl")
            completed = _parse_datetime(run.get("completed_at_hkt")) or _parse_datetime(
                run.get("heartbeat_at_hkt")
            )
            if completed and completed > latest_success_by_kind.get(kind, datetime.min.replace(tzinfo=HKT)):
                latest_success_by_kind[kind] = completed
        issues: list[dict[str, Any]] = []
        for run in runs:
            if not isinstance(run, dict):
                continue
            run_id = str(run.get("crawl_run_id") or "")
            kind = str(run.get("task_kind") or "crawl")
            status = str(run.get("run_status") or "")
            started = _parse_datetime(run.get("started_at_hkt"))
            completed = _parse_datetime(run.get("completed_at_hkt"))
            timestamp = completed or started
            if timestamp and timestamp < cutoff:
                continue
            stage = str(run.get("failure_stage") or "")
            detail = str(run.get("progress_detail") or run.get("status_detail") or "")
            if status == "failed":
                if self._is_verified_intelligence_fallback(run):
                    continue
                if timestamp and latest_success_by_kind.get(kind) and timestamp < latest_success_by_kind[kind]:
                    continue
                operational_summary = run.get("operational_summary") if isinstance(run.get("operational_summary"), dict) else {}
                feishu_detail_log = operational_summary.get("feishu_detail_log") if isinstance(operational_summary.get("feishu_detail_log"), dict) else {}
                issues.append(
                    self._issue(
                        condition_key=f"crawl-task-failed:{run_id}",
                        component=kind,
                        task_name=self._task_name(kind, str(run.get("trigger") or "爬虫任务")),
                        severity=self._failure_severity(kind, stage),
                        summary=f"任务失败：{str(run.get('trigger') or self._task_name(kind))}",
                        error=detail or f"failure_stage={stage or 'unknown'}",
                        impact=(
                            "本轮任务未达到完整成功条件；已有成功阶段和旧数据应继续保留，"
                            "受影响阶段等待有界恢复。"
                        ),
                        suggestions=self._failure_suggestions(kind, stage),
                        occurred_at_hkt=_iso(timestamp) if timestamp else "",
                        evidence=[
                            f"crawl_run_id={run_id}",
                            f"failure_stage={stage or '-'}",
                            f"feishu_log_error={feishu_detail_log.get('error') or '-'}",
                            f"feishu_log_written={feishu_detail_log.get('written', '-')}; readback_verified={feishu_detail_log.get('readback_verified', False)}",
                            f"local_source_audit={(operational_summary.get('overview_source_recrawl') or {}).get('path') if isinstance(operational_summary.get('overview_source_recrawl'), dict) else '-'}",
                            str((run.get("local_files") or {}).get("stream_log") or ""),
                        ],
                    )
                )
            elif status == "running":
                heartbeat = _parse_datetime(run.get("heartbeat_at_hkt")) or started
                stale_after = self._task_stale_seconds(kind, 4200)
                if heartbeat and (self.now() - heartbeat).total_seconds() > stale_after:
                    issues.append(
                        self._issue(
                            condition_key=f"crawl-task-stuck:{run_id}",
                            component=kind,
                            task_name=self._task_name(kind),
                            severity="P1" if kind in {"crawl", "strategic-news"} else "P2",
                            summary="任务心跳超时，可能卡死或进程已中断",
                            error=f"最后心跳 {heartbeat.isoformat(timespec='seconds')}；阶段 {run.get('phase') or '-'}；{detail}",
                            impact="任务可能长期占用锁或错过后续定时窗口，且不能直接判断是否可以安全重跑。",
                            suggestions=[
                                "先检查 worker_pid、进程锁和完整流日志，确认进程是否仍存活。",
                                "若已中断，按任务归档从最后未完成阶段恢复，不要重放已完成外部写入。",
                            ],
                            occurred_at_hkt=heartbeat.isoformat(timespec="seconds"),
                            evidence=[f"crawl_run_id={run_id}", f"heartbeat={heartbeat.isoformat()}"],
                        )
                    )
        return issues

    def _detect_general_tasks(self) -> list[dict[str, Any]]:
        path = self.runtime_root / "task_runs" / "index.json"
        payload = _read_json(path, {})
        tasks = payload.get("tasks") if isinstance(payload, dict) else payload
        tasks = tasks if isinstance(tasks, list) else []
        cutoff = self._lookback_cutoff()
        latest_success_by_kind: dict[str, datetime] = {}
        for task in tasks:
            if not isinstance(task, dict) or str(task.get("run_status") or "") != "completed":
                continue
            kind = str(task.get("kind") or "background")
            completed = _parse_datetime(task.get("completed_at_hkt")) or _parse_datetime(
                task.get("heartbeat_at_hkt")
            )
            if completed and completed > latest_success_by_kind.get(kind, datetime.min.replace(tzinfo=HKT)):
                latest_success_by_kind[kind] = completed
        issues: list[dict[str, Any]] = []
        for task in tasks:
            if not isinstance(task, dict):
                continue
            task_id = str(task.get("task_id") or task.get("task_run_id") or "")
            kind = str(task.get("kind") or "background")
            status = str(task.get("run_status") or "")
            started = _parse_datetime(task.get("started_at_hkt"))
            completed = _parse_datetime(task.get("completed_at_hkt"))
            timestamp = completed or started
            if timestamp and timestamp < cutoff:
                continue
            detail = str(task.get("status_detail") or task.get("progress_detail") or "")
            if status == "failed":
                if timestamp and latest_success_by_kind.get(kind) and timestamp < latest_success_by_kind[kind]:
                    continue
                stage = "audio-generation" if "audio" in detail.lower() or kind == "audio-generation" else kind
                issues.append(
                    self._issue(
                        condition_key=f"general-task-failed:{task_id}",
                        component=kind,
                        task_name=self._task_name(kind, str(task.get("title") or "后台任务")),
                        severity=self._failure_severity(kind, stage),
                        summary=f"任务失败：{str(task.get('title') or self._task_name(kind))}",
                        error=detail or "任务归档为 failed，未记录详细错误。",
                        impact=(
                            "本轮报告或音频产物未达到完整交付条件；已经生成的有效文件不应被覆盖。"
                            if kind in {"weekly-report", "carrier-performance", "audio-generation"}
                            else "本轮后台任务未完成。"
                        ),
                        suggestions=self._failure_suggestions(kind, stage),
                        occurred_at_hkt=_iso(timestamp) if timestamp else "",
                        evidence=[f"task_id={task_id}", str(task.get("log_path") or "")],
                    )
                )
            elif status == "running":
                heartbeat = _parse_datetime(task.get("heartbeat_at_hkt")) or started
                stale_after = self._task_stale_seconds(kind, 7200)
                if heartbeat and (self.now() - heartbeat).total_seconds() > stale_after:
                    issues.append(
                        self._issue(
                            condition_key=f"general-task-stuck:{task_id}",
                            component=kind,
                            task_name=self._task_name(kind),
                            severity="P2",
                            summary="报告或音频任务心跳超时",
                            error=f"最后心跳 {heartbeat.isoformat(timespec='seconds')}；{detail}",
                            impact="任务可能已经中断但仍显示运行中，后续自动恢复可能被阻塞。",
                            suggestions=[
                                "检查任务 worker_pid、日志和目标文件是否仍在更新。",
                                "确认进程不存在后再按现有自动恢复机制收尾，避免同时启动两个生成任务。",
                            ],
                            occurred_at_hkt=heartbeat.isoformat(timespec="seconds"),
                            evidence=[f"task_id={task_id}", str(task.get("log_path") or "")],
                        )
                    )
        return issues

    def _detect_scheduler_pending(self) -> list[dict[str, Any]]:
        path = self.runtime_root / "scheduler_pending_run.json"
        pending = _read_json(path, {})
        if not isinstance(pending, dict) or not pending:
            return []
        stage = str(pending.get("stage") or "unknown")
        last = _parse_datetime(pending.get("last_attempt_at_hkt") or pending.get("started_at_hkt"))
        thresholds = {
            "crawl_running": 2400,
            "crawl_completed": 4800,
            "sync_completed": 4800,
            "audit_completed": 2400,
        }
        threshold = thresholds.get(stage, 5400)
        if not last or (self.now() - last).total_seconds() <= threshold:
            return []
        run_id = str(pending.get("crawl_run_id") or "unknown")
        return [
            self._issue(
                condition_key=f"scheduler-pending-stale:{run_id}:{stage}",
                component="frequency-scheduler",
                task_name="定时爬虫续跑状态",
                severity="P1",
                summary="定时爬虫待恢复状态长时间未推进",
                error=f"stage={stage}; last_attempt={last.isoformat(timespec='seconds')}",
                impact="本轮任务可能卡在抓取、同步或Agent审核阶段，后续到期任务可能被阻塞。",
                suggestions=[
                    "交叉检查 pending 状态、crawl_run_id 完整日志和实际进程。",
                    "确认最后成功阶段后，只恢复后续阶段；不要删除状态后直接全量重跑。",
                ],
                occurred_at_hkt=last.isoformat(timespec="seconds"),
                evidence=[str(path), f"crawl_run_id={run_id}", f"stage={stage}"],
            )
        ]

    def _strategic_task_started(self, slot: datetime) -> bool:
        path = self.runtime_root / "agent_knowledge" / "crawl_run_logs" / "index.json"
        runs = _read_json(path, [])
        if not isinstance(runs, list):
            return False
        prefix = slot.strftime("%Y-%m-%d@%H:%M")
        for run in runs:
            if not isinstance(run, dict) or str(run.get("task_kind") or "") != "strategic-news":
                continue
            scope = str(run.get("scope") or "")
            started = _parse_datetime(run.get("started_at_hkt"))
            if prefix in scope or (started and abs((started - slot).total_seconds()) < 30 * 60):
                return True
        return False

    def _detect_strategic_monitor_heartbeat(self) -> list[dict[str, Any]]:
        path = self.runtime_root / "strategy_briefing" / "state.json"
        state = _read_json(path, {})
        if not isinstance(state, dict) or not state:
            return [
                self._issue(
                    condition_key="strategic-monitor-state-missing",
                    component="strategic-news",
                    task_name="战略新闻常驻监视器",
                    severity="P1",
                    summary="战略新闻监视器状态文件不存在或不可读",
                    error=f"无法读取 {path}",
                    impact="07:30/14:00 扫描及群消息回读监视可能已经停止。",
                    suggestions=[
                        "检查主Web服务和 strategic-briefing-monitor 后台线程日志。",
                        "确认没有战略新闻任务在执行后，再恢复主Web服务。",
                    ],
                    evidence=[str(path)],
                )
            ]
        heartbeat = _parse_datetime(state.get("last_cycle_at"))
        if heartbeat and (self.now() - heartbeat).total_seconds() <= 300:
            return []
        # The strategic monitor executes each scheduled scan synchronously. Its
        # loop heartbeat pauses during that work, while the run archive keeps a
        # separate progress heartbeat that is already monitored for staleness.
        active_run = _read_json(
            self.runtime_root / "agent_knowledge" / "crawl_run_logs" / "latest.json",
            {},
        )
        if (
            isinstance(active_run, dict)
            and str(active_run.get("task_kind") or "") == "strategic-news"
            and str(active_run.get("run_status") or "") == "running"
        ):
            run_heartbeat = _parse_datetime(active_run.get("heartbeat_at_hkt"))
            stale_after = self._task_stale_seconds("strategic-news", 4200)
            if run_heartbeat and (self.now() - run_heartbeat).total_seconds() <= stale_after:
                return []
        error = str(state.get("last_scan_error") or state.get("last_group_error") or "")
        return [
            self._issue(
                condition_key="strategic-monitor-heartbeat-stale",
                component="strategic-news",
                task_name="战略新闻常驻监视器",
                severity="P1",
                summary="战略新闻监视器超过5分钟没有心跳",
                error=(
                    f"last_cycle_at={heartbeat.isoformat(timespec='seconds') if heartbeat else 'missing'}"
                    + (f"; last_error={error}" if error else "")
                ),
                impact="下一次战略新闻扫描、群回读或待发状态恢复可能不会执行。",
                suggestions=[
                    "检查 com.liaowang.cmhk-web-app 运行状态和 web_app stderr。",
                    "确认战略任务进程锁与当前任务状态后，再按 LaunchAgent 流程恢复。",
                ],
                occurred_at_hkt=(
                    (heartbeat + timedelta(minutes=5)).isoformat(timespec="seconds")
                    if heartbeat
                    else _iso(self.now())
                ),
                evidence=[str(path)],
            )
        ]

    def _detect_strategic_slots(self) -> list[dict[str, Any]]:
        issues: list[dict[str, Any]] = []
        now = self.now()
        start_grace = max(5, int(self.config.get("strategic_start_grace_minutes") or 15))
        finish_grace = max(start_grace + 10, int(self.config.get("strategic_finish_grace_minutes") or 70))
        try:
            cutoff_hour, cutoff_minute = [
                int(value)
                for value in str(self.config.get("strategic_daily_cutoff") or "00:00").split(":", 1)
            ]
            daily_cutoff = datetime.combine(
                now.date() + timedelta(days=1), clock_time(cutoff_hour, cutoff_minute), HKT
            )
        except (TypeError, ValueError):
            daily_cutoff = datetime.combine(
                now.date() + timedelta(days=1), clock_time(0, 0), HKT
            )
        for slot_index, raw in enumerate(self.config.get("strategic_scan_times") or []):
            try:
                hour, minute = [int(value) for value in str(raw).split(":", 1)]
                slot = datetime.combine(now.date(), clock_time(hour, minute), HKT)
            except (TypeError, ValueError):
                continue
            if now < slot + timedelta(minutes=start_grace):
                continue
            slot_key = slot.strftime("%Y-%m-%d@%H-%M")
            path, archive = self._strategic_archive_for_slot(slot, slot_index)
            if not isinstance(archive, dict) or not archive:
                task_started = self._strategic_task_started(slot)
                if not task_started:
                    issues.append(
                        self._issue(
                            condition_key=f"strategic-slot-not-started:{slot_key}",
                            component="strategic-news",
                            task_name=f"战略新闻定时扫描 {raw}",
                            severity="P1",
                            summary="战略新闻定时扫描超过宽限期仍未启动",
                            error=f"计划时间 {slot.isoformat(timespec='minutes')}；未发现任务归档或启动记录。",
                            impact="该时段竞对与战略新闻可能漏采，且不能在未核实历史状态前直接补跑。",
                            suggestions=self._failure_suggestions("strategic-news", "strategic_news"),
                            occurred_at_hkt=(slot + timedelta(minutes=start_grace)).isoformat(timespec="seconds"),
                            evidence=[str(path)],
                        )
                    )
                elif now < daily_cutoff:
                    # Both runs may continue until the next 00:00 cutoff;
                    # task-heartbeat monitoring detects a real stall meanwhile.
                    continue
                elif now >= slot + timedelta(minutes=finish_grace):
                    issues.append(
                        self._issue(
                            condition_key=f"strategic-slot-incomplete:{slot_key}",
                            component="strategic-news",
                            task_name=f"战略新闻定时扫描 {raw}",
                            severity="P1",
                            summary="战略新闻任务已启动但长时间没有完成归档",
                            error=f"计划时间 {slot.isoformat(timespec='minutes')}；{finish_grace} 分钟后仍无完成归档。",
                            impact="任务可能卡在搜索、AI审核、去重、飞书写入或群通知阶段。",
                            suggestions=self._failure_suggestions("strategic-news", "strategic_news"),
                            occurred_at_hkt=(slot + timedelta(minutes=finish_grace)).isoformat(timespec="seconds"),
                            evidence=[str(path)],
                        )
                    )
                continue
            status = str(archive.get("status") or "")
            notification = str(archive.get("notification_status") or "")
            if status == "cutoff" and notification == "not_sent_cutoff":
                continue
            explicit_failure = status in {"failed", "error"} or notification == "failed"
            if not explicit_failure and now < slot + timedelta(minutes=finish_grace):
                # The archive is updated in several atomic stages.  In
                # particular, pipeline_completed/pending is a normal transient
                # state while the Feishu notification and final completion
                # fields are being written.  Do not turn that intermediate
                # snapshot into a sticky P1 incident.
                continue
            if status not in {"completed"} or notification == "failed":
                issues.append(
                    self._issue(
                        condition_key=f"strategic-slot-failed:{slot_key}",
                        component="strategic-news",
                        task_name=f"战略新闻定时扫描 {raw}",
                        severity="P1",
                        summary="战略新闻定时扫描未完整成功",
                        error=str(
                            archive.get("notification_error")
                            or archive.get("error")
                            or f"status={status}; notification_status={notification}"
                        ),
                        impact="扫描、飞书写入、回读或原有战略通知链路至少有一个阶段未完成。",
                        suggestions=self._failure_suggestions("strategic-news", "strategic_news"),
                        occurred_at_hkt=str(archive.get("completed_at") or archive.get("scanned_at") or ""),
                        evidence=[str(path), f"status={status}", f"notification_status={notification}"],
                        terminal=True,
                    )
                )
        return issues

    def _strategic_archive_for_slot(
        self, slot: datetime, slot_index: int
    ) -> tuple[Path, dict[str, Any]]:
        runs_dir = self.runtime_root / "strategy_briefing" / "runs"
        slot_key = slot.strftime("%Y-%m-%d@%H-%M")
        exact_path = runs_dir / f"{slot_key}.json"
        exact = _read_json(exact_path, {})
        if isinstance(exact, dict) and exact:
            return exact_path, exact

        expected_label = "晨间扫描" if slot_index == 0 else "午后扫描"
        for candidate in sorted(runs_dir.glob(f"{slot.date().isoformat()}@*.json")):
            archive = _read_json(candidate, {})
            if not isinstance(archive, dict) or not archive:
                continue
            if str(archive.get("slot_label") or "") != expected_label:
                continue
            match = re.search(r"@(\d{2})-(\d{2})$", candidate.stem)
            candidate_time = (
                datetime.combine(
                    slot.date(),
                    clock_time(int(match.group(1)), int(match.group(2))),
                    HKT,
                )
                if match
                else _parse_datetime(archive.get("scanned_at") or archive.get("completed_at"))
            )
            if candidate_time and abs((candidate_time - slot).total_seconds()) <= 2 * 3600:
                return candidate, archive
        return exact_path, {}

    def _latest_strategic_archive(self) -> tuple[str, dict[str, Any]]:
        """Return the most recent completed scan archive for the current day."""
        now = self.now()
        newest_key = ""
        newest: dict[str, Any] = {}
        for slot_index, raw in enumerate(self.config.get("strategic_scan_times") or []):
            try:
                hour, minute = [int(value) for value in str(raw).split(":", 1)]
                slot = datetime.combine(now.date(), clock_time(hour, minute), HKT)
            except (TypeError, ValueError):
                continue
            if now < slot:
                continue
            path, archive = self._strategic_archive_for_slot(slot, slot_index)
            if isinstance(archive, dict) and archive:
                newest_key, newest = path.stem, archive
        return newest_key, newest

    def _detect_strategic_content_quality(self) -> list[dict[str, Any]]:
        """Catch scans that finish successfully while producing unusable output.

        A run can archive as completed with an empty Agentic gap search, blocked
        prompt-leak copy or a stuck AI review backlog. Those degrade coverage
        silently, so they need their own signal rather than the pass/fail one.
        """
        issues: list[dict[str, Any]] = []
        slot_key, archive = self._latest_strategic_archive()
        if not archive:
            return issues
        archive_path = (
            self.runtime_root / "strategy_briefing" / "runs" / f"{slot_key}.json"
        )
        occurred_at = str(archive.get("completed_at") or archive.get("scanned_at") or "")
        agentic = (archive.get("news_discovery") or {}).get("agentic_search") or {}
        query_count = int(agentic.get("agentic_query_count") or 0)
        result_count = int(agentic.get("agentic_result_count") or 0)
        if query_count > 0 and result_count == 0:
            issues.append(
                self._issue(
                    condition_key=f"strategic-agentic-empty:{slot_key}",
                    component="strategic-news",
                    task_name=f"战略新闻Agentic补搜 {slot_key}",
                    severity="P2",
                    summary="Agentic 补搜执行了查询但一条结果都没有返回",
                    error=(
                        f"本轮补搜查询 {query_count} 条，返回 0 条结果；"
                        "扫描本身仍标记为完成。"
                    ),
                    impact="覆盖缺口没有被补上，竞对与政策盲区会连续多轮无人发现。",
                    suggestions=[
                        "检查补搜查询是否被写成整串 AND 词，导致搜索引擎零命中。",
                        "确认查询已改写为“(别名 OR 别名) (意图 OR 意图)”形式。",
                        "核对当日该竞对是否确实没有新闻，避免误判为故障。",
                    ],
                    occurred_at_hkt=occurred_at,
                    evidence=[
                        str(archive_path),
                        f"agentic_query_count={query_count}",
                        f"agentic_result_count={result_count}",
                    ],
                )
            )
        review = archive.get("review_sheet") or {}
        dirty_count = int(review.get("dirty_copy_blocked_count") or 0)
        if dirty_count > 0:
            samples = "；".join(
                f"{str(entry.get('reason') or '')}（{str(entry.get('title') or '')[:40]}）"
                for entry in (review.get("dirty_copy_blocked") or [])[:3]
                if isinstance(entry, dict)
            )
            issues.append(
                self._issue(
                    condition_key=f"strategic-dirty-copy:{slot_key}:{dirty_count}",
                    component="strategic-news",
                    task_name=f"战略新闻AI文案质量 {slot_key}",
                    severity="P1",
                    summary="AI 生成文案含提示词或节目单，已在写表前拦截",
                    error=f"本轮拦截 {dirty_count} 条不可发布文案。{samples}",
                    impact="模型输出出现新的污染形态，上游守卫没有覆盖，可能漏进人工审核表。",
                    suggestions=[
                        "查看被拦截标题，确认是哪一类提示词泄漏或栏目导视。",
                        "在 strategic_briefing 的提示词与 artifact 标记中补上新形态。",
                        "确认被拦截的条目是真实新闻时，人工补回审核表。",
                    ],
                    occurred_at_hkt=occurred_at,
                    evidence=[str(archive_path), f"dirty_copy_blocked_count={dirty_count}"],
                )
            )
        audit = _read_json(
            self.runtime_root / "strategy_briefing" / "candidate_ai_editor_audit.json",
            {},
        )
        queue = _read_json(
            self.runtime_root / "strategy_briefing" / "candidate_ai_editor_deferred.json",
            {},
        )
        queued = queue.get("items") if isinstance(queue, dict) else []
        queued_count = len(queued) if isinstance(queued, list) else 0
        threshold = max(1, int(self.config.get("strategic_deferred_queue_limit") or 40))
        if queued_count >= threshold:
            issues.append(
                self._issue(
                    condition_key=f"strategic-deferred-backlog:{queued_count // threshold}",
                    component="strategic-news",
                    task_name="战略新闻AI补审队列",
                    severity="P2",
                    summary="AI 补审队列持续积压，条目迟迟没有进入审核表",
                    error=(
                        f"待补审 {queued_count} 条，阈值 {threshold} 条；"
                        f"最近一轮延期 {int((audit or {}).get('deferred_count') or 0)} 条。"
                    ),
                    impact="这些新闻不会出现在群通报里，只能靠后续轮次补进表，时效性下降。",
                    suggestions=[
                        "检查内部模型额度与限流，确认审核请求不是被持续拒绝。",
                        "查看 candidate_ai_editor_audit.json 的 deferred 原因分布。",
                    ],
                    occurred_at_hkt=occurred_at,
                    evidence=[f"deferred_queue_count={queued_count}"],
                )
            )
        return issues

    def _source_root(self) -> Path:
        """Return the source checkout used by auxiliary main-project daemons."""
        return Path(self.environ.get("CMHK_MONITOR_SOURCE_ROOT") or self.runtime_root)

    def _media_metrics_state_path(self) -> Path:
        runtime_path = self.runtime_root / "var" / "feishu_media_metrics" / "state.json"
        if runtime_path.is_file():
            return runtime_path
        return self._source_root() / "var" / "feishu_media_metrics" / "state.json"

    def _detect_feishu_media_metrics(self) -> list[dict[str, Any]]:
        """Detect missed 10:00/17:00 media-metrics reports."""
        now = self.now()
        grace = max(5, int(self.config.get("media_metrics_grace_minutes") or 20))
        state_path = self._media_metrics_state_path()
        state = _read_json(state_path, {})
        sent_slots = state.get("sent_slots") if isinstance(state, dict) else {}
        sent_slots = sent_slots if isinstance(sent_slots, dict) else {}
        issues: list[dict[str, Any]] = []
        for raw in self.config.get("media_metrics_scan_times") or []:
            try:
                hour, minute = [int(value) for value in str(raw).split(":", 1)]
                slot = datetime.combine(now.date(), clock_time(hour, minute), HKT)
            except (TypeError, ValueError):
                continue
            due = slot + timedelta(minutes=grace)
            if now < due:
                continue
            slot_key = slot.strftime("%Y%m%d-%H%M")
            if str(sent_slots.get(slot_key) or "").strip():
                continue
            issues.append(
                self._issue(
                    condition_key=f"feishu-media-metrics-slot-missed:{slot_key}",
                    component="feishu-media-metrics",
                    task_name=f"Feishu媒体指标定时汇总 {raw}",
                    severity="P2",
                    summary="Feishu媒体指标定时汇总超过宽限期仍未完成",
                    error=f"计划时段 {slot.isoformat(timespec='minutes')}；sent_slots 未找到 {slot_key}",
                    impact="该时段媒体发布阅读与互动指标没有按计划汇总，项目数据本身和主爬虫仍可继续运行。",
                    suggestions=[
                        "检查媒体指标 daemon 的 launchd 状态、stderr、飞书读取和消息回读错误。",
                        "先核对目标群是否已经收到该时段报告；确认未发送后再做有界恢复，避免重复消息。",
                    ],
                    occurred_at_hkt=due.isoformat(timespec="seconds"),
                    evidence=[str(state_path), f"missing_sent_slot={slot_key}"],
                )
            )
        return issues

    def _feishu_media_metrics_recovery_evidence(self, record: dict[str, Any]) -> list[str]:
        occurred = _parse_datetime(record.get("occurred_at_hkt")) or _parse_datetime(
            record.get("first_seen_at_hkt")
        )
        if occurred is None:
            return []
        scheduled_slots: list[datetime] = []
        for raw in self.config.get("media_metrics_scan_times") or []:
            try:
                hour, minute = [int(value) for value in str(raw).split(":", 1)]
                scheduled = datetime.combine(occurred.date(), clock_time(hour, minute), HKT)
            except (TypeError, ValueError):
                continue
            if scheduled <= occurred and occurred - scheduled <= timedelta(hours=12):
                scheduled_slots.append(scheduled)
        if not scheduled_slots:
            return []
        slot = max(scheduled_slots)
        slot_key = slot.strftime("%Y%m%d-%H%M")
        state_path = self._media_metrics_state_path()
        state = _read_json(state_path, {})
        if not isinstance(state, dict):
            return []
        sent_slots = state.get("sent_slots") if isinstance(state.get("sent_slots"), dict) else {}
        message_id = str(sent_slots.get(slot_key) or "").strip()
        if not message_id:
            return []
        deliveries = state.get("slot_deliveries") if isinstance(state.get("slot_deliveries"), dict) else {}
        delivery = deliveries.get(slot_key) if isinstance(deliveries.get(slot_key), dict) else {}
        evidence = [
            str(state_path),
            f"时段 {slot_key} 已在发送后回读账本登记消息 {message_id}。",
        ]
        if delivery.get("readback_verified") is True:
            evidence.append(
                f"发送后回读 verified_at={delivery.get('verified_at_hkt') or '-'}，chat_id={delivery.get('chat_id') or '-'}。"
            )
        else:
            evidence.append("该账本仅在群消息发送并通过目标、正文和图片回读后写入。")
        return evidence

    def _read_new_log_text(self, path: Path, *, initial_tail_bytes: int = 131072) -> str:
        offsets = self.state.setdefault("log_offsets", {})
        key = str(path)
        try:
            size = path.stat().st_size
        except OSError:
            return ""
        previous = offsets.get(key)
        if previous is None:
            if bool(self.config.get("ignore_existing_logs_on_first_observation", True)) and not _env_true(
                self.environ.get("CMHK_MONITOR_REPLAY_EXISTING_LOGS")
            ):
                offsets[key] = size
                return ""
            start = max(0, size - initial_tail_bytes)
        else:
            start = max(0, min(int(previous or 0), size))
        try:
            with path.open("rb") as handle:
                handle.seek(start)
                data = handle.read(262144)
                offsets[key] = handle.tell()
        except OSError:
            return ""
        return data.decode("utf-8", errors="replace")

    def _detect_runtime_logs(self) -> list[dict[str, Any]]:
        log_root = Path(self.environ.get("CMHK_MONITOR_LOG_ROOT") or (Path.home() / "Library" / "Logs" / "cmhk_public_crawl"))
        scheduler_path = log_root / "frequency_scheduler.stderr.log"
        scheduler_text = self._read_new_log_text(scheduler_path)
        web_text = self._read_new_log_text(log_root / "web_app.stderr.log")
        monitor_path = log_root / "project_monitor.stderr.log"
        monitor_text = self._read_new_log_text(monitor_path)
        card_actions_path = log_root / "project_monitor_card_actions.stderr.log"
        card_actions_text = self._read_new_log_text(card_actions_path)
        media_metrics_path = self.runtime_root / "var" / "feishu_media_metrics" / "daemon.stderr.log"
        media_metrics_text = self._read_new_log_text(media_metrics_path)
        issues: list[dict[str, Any]] = []
        heartbeat_path = self.runtime_root / "var" / "frequency_scheduler" / "heartbeat.json"
        heartbeat = _read_json(heartbeat_path, {})
        heartbeat_at = _parse_datetime(heartbeat.get("updated_at_hkt")) if isinstance(heartbeat, dict) else None
        heartbeat_fresh = bool(
            isinstance(heartbeat, dict)
            and heartbeat.get("service") == "frequency-scheduler"
            and heartbeat_at
            and (self.now() - heartbeat_at).total_seconds() <= 120
        )
        try:
            scheduler_mtime = datetime.fromtimestamp(scheduler_path.stat().st_mtime, HKT)
        except OSError:
            scheduler_mtime = None
        if not heartbeat_fresh and (not scheduler_mtime or (self.now() - scheduler_mtime).total_seconds() > 300):
            issues.append(
                self._issue(
                    condition_key="frequency-scheduler-heartbeat-stale",
                    component="frequency-scheduler",
                    task_name="飞书频率调度器",
                    severity="P1",
                    summary="频率调度器独立心跳中断",
                    error=(
                        f"heartbeat updated_at={heartbeat_at.isoformat(timespec='seconds') if heartbeat_at else 'missing'}; "
                        f"scheduler log mtime={scheduler_mtime.isoformat(timespec='seconds') if scheduler_mtime else 'missing'}"
                    ),
                    impact="到期行可能没有被检查，03:00或其他频率任务可能漏跑。",
                    suggestions=[
                        "检查 launchd 状态、进程PID和 frequency_scheduler stderr。",
                        "先核对任务归档与到期状态，再决定是否恢复服务，禁止盲目补跑。",
                    ],
                    occurred_at_hkt=(
                        (scheduler_mtime + timedelta(minutes=5)).isoformat(timespec="seconds")
                        if scheduler_mtime
                        else _iso(self.now())
                    ),
                    evidence=[str(heartbeat_path), str(scheduler_path)],
                )
            )
        scheduler_markers = [
            line.strip()
            for line in scheduler_text.splitlines()
            if re.search(r"调度周期失败|Traceback \(most recent call last\)|CRITICAL|Unhandled", line, re.I)
        ]
        if scheduler_markers:
            issues.append(
                self._issue(
                    condition_key="scheduler-log-error",
                    component="frequency-scheduler",
                    task_name="飞书频率调度周期",
                    severity="P1",
                    summary="调度器日志出现未处理异常",
                    error="\n".join(scheduler_markers[-8:]),
                    impact="本轮或后续到期任务可能没有被正常检查或启动。",
                    suggestions=[
                        "读取异常前后的完整 scheduler stderr 与任务状态。",
                        "先确认本轮是否已经启动/完成，再修复异常，避免重复触发。",
                    ],
                    evidence=[str(log_root / "frequency_scheduler.stderr.log")],
                    terminal=True,
                )
            )
        media_metrics_errors = [
            line.strip()
            for line in media_metrics_text.splitlines()
            if line.strip()
            and (
                re.search(r"Traceback \(most recent call last\)|CRITICAL|Unhandled", line, re.I)
                or '"ok": false' in line.lower()
            )
        ]
        if media_metrics_errors:
            issues.append(
                self._issue(
                    condition_key="feishu-media-metrics-error",
                    component="feishu-media-metrics",
                    task_name="Feishu媒体指标定时汇总",
                    severity="P2",
                    summary="Feishu媒体指标任务日志出现执行错误",
                    error="\n".join(media_metrics_errors[-8:]),
                    impact="当期媒体指标收集、AI校验、群发送或发送后回读至少一个阶段未完成。",
                    suggestions=[
                        "按日志时间核对 state.json 的 sent_slots 与目标群实际消息，先判断是否已发送。",
                        "修复来源校验、飞书权限或AI校验问题后，只恢复未完成时段并验证回读。",
                    ],
                    evidence=[str(media_metrics_path)],
                    terminal=True,
                )
            )
        infrastructure_logs = (
            (
                monitor_path,
                monitor_text,
                "project-monitor",
                "主项目错误监控器",
                "project monitor cycle failed",
                "监控周期执行失败",
                "至少一个主项目故障探针、错误台账同步或告警发送周期可能未完成。",
                "P1",
            ),
            (
                card_actions_path,
                card_actions_text,
                "project-monitor-card-actions",
                "错误告警处理按钮监听器",
                "card action failed locally|consumer exited before a healthy ready state",
                "告警处理按钮回调执行失败",
                "用户点击“已处理”后，处理人员或处理状态可能暂时无法写回错误台账。",
                "P2",
            ),
        )
        for (
            path,
            text,
            component,
            task_name,
            marker_pattern,
            summary,
            impact,
            severity,
        ) in infrastructure_logs:
            markers = [
                line.strip()
                for line in text.splitlines()
                if line.strip()
                and re.search(
                    rf"{marker_pattern}|Traceback \(most recent call last\)|CRITICAL|Unhandled",
                    line,
                    re.I,
                )
            ]
            if not markers:
                continue
            issues.append(
                self._issue(
                    condition_key=f"{component}-log-error",
                    component=component,
                    task_name=task_name,
                    severity=severity,
                    summary=summary,
                    error="\n".join(markers[-8:]),
                    impact=impact,
                    suggestions=[
                        f"读取 {path.name} 的完整错误上下文并核对 LaunchAgent 状态。",
                        "修复后执行隔离测试并确认本地状态或错误台账写回正常，不发送测试群消息。",
                    ],
                    evidence=[str(path)],
                    terminal=True,
                )
            )
        web_lines = [line.strip() for line in web_text.splitlines() if line.strip()]
        ai_400 = [line for line in web_lines if "HTTP Error 400" in line or "HTTP 400" in line]
        ai_timeouts = [line for line in web_lines if "AI" in line and ("超时" in line or "timed out" in line.lower())]
        fatal = [
            line
            for line in web_lines
            if re.search(r"Traceback \(most recent call last\)|CRITICAL|Unhandled", line, re.I)
            and "BrokenPipeError" not in line
        ]
        if fatal:
            issues.append(
                self._issue(
                    condition_key="web-log-fatal",
                    component="web-app",
                    task_name="主项目Web后台",
                    severity="P1",
                    summary="Web后台日志出现未处理异常",
                    error="\n".join(fatal[-8:]),
                    impact="至少一个请求、后台线程或战略监视周期可能中断。",
                    suggestions=[
                        "按时间戳关联 /api/task-runs 与完整 web_app stderr。",
                        "确认受影响任务状态后再恢复；不要仅凭单行堆栈重启服务。",
                    ],
                    evidence=[str(log_root / "web_app.stderr.log")],
                    terminal=True,
                )
            )
        if len(ai_400) >= 3:
            issues.append(
                self._issue(
                    condition_key="ai-http-400-burst",
                    component="strategic-news",
                    task_name="公司内部AI审核",
                    severity="P2",
                    summary="内部AI请求持续返回 HTTP 400",
                    error=f"本次日志增量发现 {len(ai_400)} 条 HTTP 400；样本：{ai_400[-1]}",
                    impact="候选审核、去重或观察结论可能进入延期/回退，完整任务可能最终失败。",
                    suggestions=[
                        "检查当前模型路由、请求协议、模型名称与网关返回体。",
                        "确认主模型和救援模型是否同时失败，并保留未审核候选等待后续恢复。",
                    ],
                    evidence=[str(log_root / "web_app.stderr.log")],
                    terminal=True,
                )
            )
        if len(ai_timeouts) >= 3:
            issues.append(
                self._issue(
                    condition_key="ai-timeout-burst",
                    component="strategic-news",
                    task_name="公司内部AI审核",
                    severity="P2",
                    summary="内部AI请求连续超时",
                    error=f"本次日志增量发现 {len(ai_timeouts)} 条AI超时；样本：{ai_timeouts[-1]}",
                    impact="审核吞吐下降，定时任务可能超过窗口或将候选延期。",
                    suggestions=[
                        "检查内部网关健康、并发限流和任务队列长度。",
                        "不要丢弃候选；让失败条目保留到待恢复队列。",
                    ],
                    evidence=[str(log_root / "web_app.stderr.log")],
                    terminal=True,
                )
            )
        generic_web_errors = [
            line
            for line in web_lines
            if re.search(r"\b(?:ERROR|CRITICAL|FATAL)\b", line, re.I)
            and line not in ai_400
            and line not in ai_timeouts
            and line not in fatal
            and "BrokenPipeError" not in line
        ]
        if generic_web_errors:
            samples = generic_web_errors[-12:]
            issues.append(
                self._issue(
                    condition_key="web-background-error",
                    component="web-app",
                    task_name="主项目后台任务",
                    severity="P3",
                    summary="主项目后台日志出现业务处理错误",
                    error=f"本次日志增量发现 {len(generic_web_errors)} 条错误；样本：\n" + "\n".join(samples[-6:]),
                    impact="至少一个候选、去重、AI审核或后台处理步骤进入回退、延期或失败；整体任务是否完成需结合任务归档判断。",
                    suggestions=[
                        "按日志时间关联对应任务归档、候选ID和最终完成状态，区分已回退成功与最终失败。",
                        "若条目进入待恢复队列，保留已有结果并只恢复失败步骤；完成后验证任务归档。",
                    ],
                    evidence=[str(log_root / "web_app.stderr.log")],
                    terminal=True,
                )
            )
        return issues

    def _mark_resolved(
        self,
        record: dict[str, Any],
        *,
        resolution_type: str,
        reason: str,
        evidence: list[str],
        action_type: str = "none",
    ) -> None:
        resolved_at = _iso(self.now())
        record["status"] = "resolved"
        record["resolved_at_hkt"] = resolved_at
        record["resolution_reason"] = reason
        record["resolution"] = {
            "status": "evidence_verified",
            "type": resolution_type,
            "resolved_at_hkt": resolved_at,
            "evidence": [_redact(item, 800) for item in evidence if str(item).strip()],
            "action": {"type": action_type, "performed": action_type != "none"},
            "ai_status": "pending",
        }

    def _four_database_log_recovery_evidence(self, record: dict[str, Any]) -> list[str]:
        occurred = _parse_datetime(record.get("occurred_at_hkt")) or _parse_datetime(record.get("first_seen_at_hkt"))
        component = str(record.get("component") or "")
        path = self.runtime_root / "agent_knowledge" / "crawl_run_logs" / "index.json"
        payload = _read_json(path, [])
        runs = payload if isinstance(payload, list) else []
        for run in sorted(runs, key=lambda item: str(item.get("completed_at_hkt") or ""), reverse=True):
            if not isinstance(run, dict) or str(run.get("task_kind") or "") != component:
                continue
            completed = _parse_datetime(run.get("completed_at_hkt"))
            if str(run.get("run_status") or "") != "completed" or not completed or (occurred and completed <= occurred):
                continue
            summary = run.get("operational_summary") if isinstance(run.get("operational_summary"), dict) else {}
            log = summary.get("feishu_detail_log") if isinstance(summary.get("feishu_detail_log"), dict) else {}
            if not (log.get("ok") and log.get("readback_verified")):
                continue
            return [
                f"后续运行 crawl_run_id={run.get('crawl_run_id')} 于 {_iso(completed)} 完成。",
                f"飞书子表={log.get('sheet_title') or '四库爬虫明细日志'}；写入{log.get('written', 0)}条；"
                f"回读行={log.get('row_start', '-')}-{log.get('row_end', '-')}。",
                "readback_verified=true；以首尾事件ID正向回读为恢复证据。",
            ]
        return []

    def _recover_historical_pending_incidents(self, active_keys: set[str]) -> None:
        """Close legacy pending records only when a current positive signal proves recovery.

        Older monitor versions removed a cleared condition from ``conditions`` but left the
        incident in ``recovery_pending``.  If the same condition returned, every polling
        cycle could therefore create another incident.  Restrict this migration to sources
        whose current files provide explicit recovery evidence; unrelated pending records
        remain untouched.
        """
        strategic_state_path = self.runtime_root / "strategy_briefing" / "state.json"
        strategic_state = _read_json(strategic_state_path, {})
        strategic_heartbeat = _parse_datetime(
            strategic_state.get("last_cycle_at") if isinstance(strategic_state, dict) else None
        )
        strategic_fresh = bool(
            strategic_heartbeat
            and (self.now() - strategic_heartbeat).total_seconds() <= 300
        )

        deferred_path = (
            self.runtime_root
            / "strategy_briefing"
            / "candidate_ai_editor_deferred.json"
        )
        deferred = _read_json(deferred_path, {})
        deferred_items = deferred.get("items") if isinstance(deferred, dict) else []
        deferred_count = len(deferred_items) if isinstance(deferred_items, list) else 0
        deferred_threshold = max(
            1, int(self.config.get("strategic_deferred_queue_limit") or 40)
        )
        deferred_healthy = deferred_path.is_file() and deferred_count < deferred_threshold

        scheduler_path = (
            self.runtime_root / "var" / "frequency_scheduler" / "heartbeat.json"
        )
        scheduler = _read_json(scheduler_path, {})
        scheduler_heartbeat = _parse_datetime(
            scheduler.get("updated_at_hkt") if isinstance(scheduler, dict) else None
        )
        scheduler_fresh = bool(
            scheduler_heartbeat
            and (self.now() - scheduler_heartbeat).total_seconds() <= 120
        )
        service_instances = self.state.get("service_instances") or {}
        service_instances = service_instances if isinstance(service_instances, dict) else {}

        now_text = _iso(self.now())
        incidents = self.state.get("incidents") or {}
        if not isinstance(incidents, dict):
            return
        for record in incidents.values():
            if not isinstance(record, dict) or record.get("status") != "recovery_pending":
                continue
            key = str(record.get("condition_key") or "")
            if not key or key in active_keys:
                continue
            reason = ""
            evidence: list[str] = []
            if key == "strategic-monitor-heartbeat-stale" and strategic_fresh:
                reason = "strategic_monitor_heartbeat_verified"
                evidence = [
                    f"战略新闻监视器心跳于 {_iso(strategic_heartbeat)} 更新。",
                    f"回读状态文件：{strategic_state_path}。",
                ]
            elif key.startswith("strategic-deferred-backlog:") and deferred_healthy:
                reason = "strategic_deferred_queue_below_threshold"
                evidence = [
                    f"AI 补审队列当前 {deferred_count} 条，低于告警阈值 {deferred_threshold} 条。",
                    f"回读队列文件：{deferred_path}。",
                ]
            elif key == "frequency-scheduler-heartbeat-stale" and scheduler_fresh:
                reason = "scheduler_heartbeat_verified"
                evidence = [
                    f"独立调度器心跳于 {_iso(scheduler_heartbeat)} 更新。",
                    f"回读状态文件：{scheduler_path}。",
                ]
            elif key.startswith("launchd:"):
                label = key.removeprefix("launchd:")
                instance = service_instances.get(label)
                observed_at = _parse_datetime(
                    instance.get("observed_at_hkt") if isinstance(instance, dict) else None
                )
                if (
                    isinstance(instance, dict)
                    and int(instance.get("pid") or 0) > 0
                    and observed_at
                    and (self.now() - observed_at).total_seconds() <= 120
                ):
                    reason = "launchd_running_verified"
                    evidence = [
                        f"launchd 服务 {label} 于 {_iso(observed_at)} 回读为 running。",
                        f"PID={int(instance.get('pid') or 0)}。",
                    ]
            if not reason:
                continue
            self._mark_resolved(
                record,
                resolution_type="normal_task_progress",
                reason=reason,
                evidence=evidence,
            )
            _append_jsonl(
                self.events_path,
                {
                    "type": "incident_resolved_local_only",
                    "at_hkt": now_text,
                    "incident_id": record.get("incident_id"),
                    "condition_key": key,
                    "reason": reason,
                    "historical_pending_reconciliation": True,
                },
            )

    def _upsert_incidents(self, issues: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        now_text = _iso(self.now())
        incidents = self.state.setdefault("incidents", {})
        conditions = self.state.setdefault("conditions", {})
        active_keys = {str(issue.get("condition_key") or "") for issue in issues}
        new_records: list[dict[str, Any]] = []
        active_records: list[dict[str, Any]] = []
        active_ids: set[str] = set()
        for issue in issues:
            key = str(issue.get("condition_key") or "")
            incident_id = str(conditions.get(key) or "")
            record = incidents.get(incident_id)
            if not isinstance(record, dict) or record.get("status") != "open":
                sequence = int(self.state.get("incident_sequence") or 0) + 1
                self.state["incident_sequence"] = sequence
                incident_id = _fingerprint(key, now_text, sequence)
                record = {
                    "incident_id": incident_id,
                    "first_seen_at_hkt": now_text,
                    "detected_with_notifications_enabled": self.notifications_enabled,
                    "delivery": {},
                    "diagnosis": {},
                    "diagnosis_attempts": 0,
                    "status": "open",
                }
                new_records.append(record)
                _append_jsonl(
                    self.events_path,
                    {"type": "incident_opened", "at_hkt": now_text, **issue, "incident_id": incident_id},
                )
            record.update(issue)
            record["last_seen_at_hkt"] = now_text
            record["status"] = "open"
            incidents[incident_id] = record
            conditions[key] = incident_id
            if incident_id not in active_ids:
                active_records.append(record)
                active_ids.add(incident_id)

        for key, incident_id in list(conditions.items()):
            if key in active_keys:
                continue
            record = incidents.get(str(incident_id))
            if not isinstance(record, dict) or record.get("status") != "open":
                conditions.pop(key, None)
                continue
            # Older versions fingerprinted every log cursor. A noisy fallback
            # therefore opened a new terminal incident every polling cycle and
            # kept hundreds of already-consumed log fragments active. Stable
            # category keys above now coalesce recurrences; retire the legacy
            # fingerprinted records once they are no longer in this cycle.
            legacy_log_key = any(
                key.startswith(f"{stable_key}:")
                for stable_key in STABLE_LOG_CONDITION_KEYS
            )
            if legacy_log_key:
                self._mark_resolved(
                    record,
                    resolution_type="superseded",
                    reason="superseded_by_stable_log_condition",
                    evidence=["旧版游标型日志告警已由同类稳定条件键接管。"],
                )
                conditions.pop(key, None)
                _append_jsonl(
                    self.events_path,
                    {
                        "type": "incident_resolved_local_only",
                        "at_hkt": now_text,
                        "incident_id": record.get("incident_id"),
                        "condition_key": key,
                        "reason": "superseded_by_stable_log_condition",
                    },
                )
                continue
            stable_log_key = next(
                (
                    stable_key
                    for stable_key in STABLE_LOG_CONDITION_KEYS
                    if key == stable_key or key.startswith(f"{stable_key}:")
                ),
                "",
            )
            if stable_log_key:
                if stable_log_key == "feishu-media-metrics-error":
                    recovery_evidence = self._feishu_media_metrics_recovery_evidence(record)
                    if recovery_evidence:
                        self._mark_resolved(
                            record,
                            resolution_type="normal_task_progress",
                            reason="media_metrics_delivery_verified",
                            evidence=recovery_evidence,
                        )
                        conditions.pop(key, None)
                        _append_jsonl(
                            self.events_path,
                            {
                                "type": "incident_resolved_local_only",
                                "at_hkt": now_text,
                                "incident_id": record.get("incident_id"),
                                "condition_key": key,
                                "reason": "media_metrics_delivery_verified",
                            },
                        )
                        continue
                service_id = LOG_CONDITION_SERVICE_IDS.get(stable_log_key, "")
                instances = self.state.get("service_instances") or {}
                starts = [
                    _parse_datetime(instance.get("started_at_hkt"))
                    for instance in instances.values()
                    if isinstance(instance, dict) and str(instance.get("service_id") or "") == service_id
                ]
                service_started = max((item for item in starts if item is not None), default=None)
                occurred = _parse_datetime(record.get("occurred_at_hkt")) or _parse_datetime(
                    record.get("first_seen_at_hkt")
                )
                if service_started and occurred and occurred < service_started:
                    self._mark_resolved(
                        record,
                        resolution_type="service_restarted",
                        reason="service_restarted_after_error",
                        evidence=[f"服务 {service_id} 于 {_iso(service_started)} 重新启动，晚于故障证据时间。"],
                        action_type="service_restart",
                    )
                    record["resolved_by_service_start_hkt"] = _iso(service_started)
                    conditions.pop(key, None)
                    _append_jsonl(
                        self.events_path,
                        {
                            "type": "incident_resolved_local_only",
                            "at_hkt": now_text,
                            "incident_id": record.get("incident_id"),
                            "condition_key": key,
                            "reason": "service_restarted_after_error",
                            "service_started_at_hkt": _iso(service_started),
                        },
                    )
                    continue
                if stable_log_key in AUTO_RECOVERING_LOG_CONDITION_KEYS:
                    self._mark_resolved(
                        record,
                        resolution_type="condition_cleared",
                        reason="log_condition_cleared",
                        evidence=["本轮增量日志未再出现同一稳定错误条件；未记录自动修复动作。"],
                    )
                    conditions.pop(key, None)
                    _append_jsonl(
                        self.events_path,
                        {
                            "type": "incident_resolved_local_only",
                            "at_hkt": now_text,
                            "incident_id": record.get("incident_id"),
                            "condition_key": key,
                            "reason": "log_condition_cleared",
                        },
                    )
                    continue
            if key.startswith("crawl-task-failed:") and any(
                "failure_stage=four_database_feishu_log" in str(item)
                for item in record.get("evidence") or []
            ):
                recovery_evidence = self._four_database_log_recovery_evidence(record)
                if recovery_evidence:
                    self._mark_resolved(
                        record,
                        resolution_type="normal_task_progress",
                        reason="four_database_feishu_log_readback_verified",
                        evidence=recovery_evidence,
                    )
                    conditions.pop(key, None)
                    _append_jsonl(
                        self.events_path,
                        {
                            "type": "incident_resolved_local_only",
                            "at_hkt": now_text,
                            "incident_id": record.get("incident_id"),
                            "condition_key": key,
                            "reason": "four_database_feishu_log_readback_verified",
                        },
                    )
                else:
                    record["status"] = "recovery_pending"
                    record["resolution"] = {
                        "status": "awaiting_evidence",
                        "type": "unverified",
                        "evidence": ["告警条件本轮未出现，但尚无后续飞书首尾事件ID写后回读证据。"],
                        "action": {"type": "none", "performed": False},
                    }
                    conditions.pop(key, None)
                continue
            if key.startswith(STATEFUL_CONDITION_PREFIXES):
                self._mark_resolved(
                    record,
                    resolution_type="condition_cleared",
                    reason="condition_no_longer_current",
                    evidence=["最新任务归档或状态源不再返回该条件；未记录自动修复动作。"],
                )
                conditions.pop(key, None)
                _append_jsonl(
                    self.events_path,
                    {
                        "type": "incident_resolved_local_only",
                        "at_hkt": now_text,
                        "incident_id": record.get("incident_id"),
                        "condition_key": key,
                        "reason": "condition_no_longer_current",
                    },
                )
                continue
            if record.get("terminal"):
                occurred = _parse_datetime(record.get("occurred_at_hkt")) or _parse_datetime(
                    record.get("first_seen_at_hkt")
                )
                if occurred is None or occurred >= self._lookback_cutoff():
                    if str(incident_id) not in active_ids:
                        active_records.append(record)
                        active_ids.add(str(incident_id))
                    continue
            if key == "frequency-scheduler-heartbeat-stale":
                heartbeat_path = self.runtime_root / "var" / "frequency_scheduler" / "heartbeat.json"
                heartbeat = _read_json(heartbeat_path, {})
                heartbeat_at = _parse_datetime(heartbeat.get("updated_at_hkt")) if isinstance(heartbeat, dict) else None
                if heartbeat_at and (self.now() - heartbeat_at).total_seconds() <= 120:
                    self._mark_resolved(
                        record,
                        resolution_type="normal_task_progress",
                        reason="scheduler_heartbeat_verified",
                        evidence=[
                            f"独立心跳于 {_iso(heartbeat_at)} 更新。",
                            f"调度器 PID={heartbeat.get('pid')}，状态={heartbeat.get('status')}，阶段={heartbeat.get('stage') or '-'}，run_id={heartbeat.get('crawl_run_id') or '-'}。",
                            "没有记录重启、补跑或其他自动修复动作。",
                        ],
                    )
                else:
                    record["status"] = "recovery_pending"
                    record["resolution"] = {
                        "status": "awaiting_evidence",
                        "type": "unverified",
                        "evidence": ["告警条件本轮未出现，但尚无新鲜独立心跳作为恢复证据。"],
                        "action": {"type": "none", "performed": False},
                    }
            else:
                record["status"] = "recovery_pending"
                record["resolution"] = {
                    "status": "awaiting_evidence",
                    "type": "unverified",
                    "evidence": ["告警条件本轮未出现，但没有足够正向证据确认恢复。"],
                    "action": {"type": "none", "performed": False},
                }
            conditions.pop(key, None)
            _append_jsonl(
                self.events_path,
                {
                    "type": "incident_resolved_local_only",
                    "at_hkt": now_text,
                    "incident_id": record.get("incident_id"),
                    "condition_key": key,
                },
            )
        self._recover_historical_pending_incidents(active_keys)
        return new_records, active_records

    def _extract_json_object(self, text: str) -> dict[str, Any]:
        cleaned = re.sub(r"<think>[\s\S]*?</think>", "", str(text or ""), flags=re.I).strip()
        if cleaned.startswith("```"):
            cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", cleaned, flags=re.I)
        try:
            payload = json.loads(cleaned)
            return payload if isinstance(payload, dict) else {}
        except (TypeError, ValueError, json.JSONDecodeError):
            pass
        start = cleaned.find("{")
        decoder = json.JSONDecoder()
        while start >= 0:
            try:
                payload, _ = decoder.raw_decode(cleaned[start:])
                return payload if isinstance(payload, dict) else {}
            except (TypeError, ValueError, json.JSONDecodeError):
                start = cleaned.find("{", start + 1)
        return {}

    def _ai_message_text(self, value: object) -> str:
        """Normalize OpenAI-compatible string and content-block responses."""
        if isinstance(value, str):
            return value
        if isinstance(value, list):
            parts: list[str] = []
            for block in value:
                if isinstance(block, str):
                    parts.append(block)
                elif isinstance(block, dict):
                    for key in ("text", "content", "output_text"):
                        text = block.get(key)
                        if isinstance(text, str) and text:
                            parts.append(text)
                            break
            return "\n".join(parts)
        if isinstance(value, dict):
            for key in ("text", "content", "output_text"):
                text = value.get(key)
                if isinstance(text, str):
                    return text
        return ""

    def _diagnose_with_internal_ai(self, incident: dict[str, Any]) -> dict[str, Any]:
        if self.ai_diagnoser is not None:
            payload = self.ai_diagnoser(dict(incident))
            return self._validate_diagnosis(payload, model="test-injected", incident=incident)
        from ai_config import INTERNAL_AI_BASE_URL, load_ai_config
        from ai_rate_limit import wait_for_internal_ai_slot
        from network_utils import urlopen_with_local_proxy_fallback

        config = load_ai_config(include_key=True)
        api_key = str(config.get("api_key") or "").strip()
        base_url = str(config.get("base_url") or INTERNAL_AI_BASE_URL).rstrip("/")
        model = str(
            self.environ.get("CMHK_ALERT_AI_MODEL")
            or self.environ.get("CMHK_STRATEGY_AI_RESCUE_MODEL")
            or config.get("model")
            or "deepseek-v4"
        ).strip()
        if not api_key or not base_url or not model:
            raise RuntimeError("内部AI配置不完整")
        prompt_payload = {
            "task": incident.get("task_name"),
            "component": incident.get("component"),
            "severity": incident.get("severity"),
            "summary": incident.get("summary"),
            "error": incident.get("error"),
            "impact": incident.get("impact"),
            "deterministic_suggestions": incident.get("suggestions"),
            "occurred_at_hkt": incident.get("occurred_at_hkt"),
        }
        body = prepare_structured_chat_body({
            **dict(config.get("extra_parameters") or {}),
            "model": model,
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "你是中国移动香港公司科创及数智化部的生产运维分析员。"
                        "只根据输入错误做一轮分析，不得臆测未提供的内部事实。"
                        "输出单一JSON对象，字段必须是severity、severity_reason、diagnosis_summary、"
                        "confirmed_facts、inferences、fault_cause、fault_impact、recommended_solutions、needs_human。"
                        "severity只能是P1、P2或P3，可以提高输入的严重程度，但不得降低；"
                        "confirmed_facts只能写输入中可直接验证的事实；inferences必须明确为推断，可为空数组；"
                        "severity_reason、fault_cause和fault_impact使用简体中文，并区分已确认事实与推断；"
                        "recommended_solutions是1至4条可执行步骤，包含检查、修复及修复后验证；"
                        "needs_human必须是JSON布尔值；"
                        "不得建议直接重跑已完成的外部写入，不得输出密钥、令牌或内部地址。"
                    ),
                },
                {
                    "role": "user",
                    "content": json.dumps(prompt_payload, ensure_ascii=False),
                },
            ],
            "temperature": 0.1,
            "max_tokens": 720,
        })
        # Some internal gateways cache by request_id even when the HTTP request
        # carries no-cache headers.  Give each contract-validation retry its own
        # deterministic ID so an empty/malformed first response cannot be
        # replayed forever, while a completed diagnosis is still persisted once.
        diagnosis_attempt = max(1, int(incident.get("diagnosis_attempts") or 1))
        request_id = (
            "cmhk-alert-"
            + str(incident.get("incident_id") or _fingerprint(prompt_payload))
            + f"-a{diagnosis_attempt}"
        )
        request = urllib.request.Request(
            f"{base_url}/chat/completions?request_id={request_id}",
            data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
                "Cache-Control": "no-cache, no-store",
                "X-Request-ID": request_id,
            },
            method="POST",
        )
        wait_for_internal_ai_slot("project-monitor-diagnosis", deadline_monotonic=time.monotonic() + 45)
        try:
            with open_llm_request(
                request,
                timeout=35,
                config=config,
                requested_key=api_key,
                model=model,
                open_func=urlopen_with_local_proxy_fallback,
            ) as response:
                response_payload = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")[:500]
            raise RuntimeError(f"内部AI HTTP {exc.code}: {_redact(detail, 500)}") from exc
        content = final_chat_message_text(response_payload, operation="运维告警诊断")
        parsed = load_json_response(content, operation="运维告警诊断")
        if not parsed:
            raise ValueError(
                "AI诊断未返回可解析JSON对象"
                f"（content_chars={len(content)}）"
            )
        diagnosis = self._validate_diagnosis(parsed, model=model, incident=incident)
        diagnosis.update({
            "source": "llm",
            "request_id": request_id,
            "response_sha256": hashlib.sha256(content.encode("utf-8")).hexdigest(),
        })
        return diagnosis

    def _validate_diagnosis(
        self,
        payload: object,
        *,
        model: str,
        incident: dict[str, Any],
    ) -> dict[str, Any]:
        if not isinstance(payload, dict):
            raise ValueError("AI诊断未返回JSON对象")
        required = {
            "severity",
            "severity_reason",
            "fault_cause",
            "fault_impact",
            "recommended_solutions",
            "needs_human",
        }
        missing = sorted(required.difference(payload))
        if missing:
            raise ValueError(f"AI诊断缺少必填字段：{', '.join(missing)}")

        llm_severity = str(payload.get("severity") or "").strip().upper()
        rule_severity = str(incident.get("severity") or "P2").strip().upper()
        if llm_severity not in SEVERITY_ORDER:
            raise ValueError("AI诊断 severity 必须是 P1、P2 或 P3")
        if rule_severity not in SEVERITY_ORDER:
            rule_severity = "P2"
        # The deterministic detector is the severity floor.  LLM output may
        # elevate an incident but can never make a known production fault less
        # urgent.  Preserve both values for auditability.
        severity = (
            llm_severity
            if SEVERITY_ORDER[llm_severity] <= SEVERITY_ORDER[rule_severity]
            else rule_severity
        )
        severity_reason = _to_simplified(_redact(payload.get("severity_reason"), 600))
        fault_cause = _to_simplified(_redact(payload.get("fault_cause"), 900))
        fault_impact = _to_simplified(_redact(payload.get("fault_impact"), 900))
        source_fault_time = str(
            incident.get("occurred_at_hkt") or incident.get("first_seen_at_hkt") or ""
        ).strip()
        if _parse_datetime(source_fault_time) is None:
            raise ValueError("故障证据时间无效，禁止由 AI 补写")

        diagnosis_summary = _to_simplified(_redact(payload.get("diagnosis_summary") or fault_cause, 900))
        confirmed_facts = [
            _to_simplified(_redact(item, 500))
            for item in (payload.get("confirmed_facts") if isinstance(payload.get("confirmed_facts"), list) else [])
            if str(item).strip()
        ][:8]
        inferences = [
            _to_simplified(_redact(item, 500))
            for item in (payload.get("inferences") if isinstance(payload.get("inferences"), list) else [])
            if str(item).strip()
        ][:8]

        solutions_raw = payload.get("recommended_solutions")
        solutions = [
            _solution_text(item, 450)
            for item in (solutions_raw if isinstance(solutions_raw, list) else [])
            if str(item).strip()
        ][:4]
        if not severity_reason or not fault_cause or not fault_impact or not solutions:
            raise ValueError("AI诊断的重要程度、故障原因、故障影响或建议解决方案为空")
        if type(payload.get("needs_human")) is not bool:
            raise ValueError("AI诊断 needs_human 必须是布林值")
        return {
            "ok": True,
            "model": str(model),
            "source": "llm",
            "severity": severity,
            "severity_label": SEVERITY_LABELS[severity],
            "llm_severity": llm_severity,
            "rule_severity_floor": rule_severity,
            "severity_floor_applied": severity != llm_severity,
            "severity_reason": severity_reason,
            "fault_cause": fault_cause,
            "fault_impact": fault_impact,
            "fault_time_hkt": source_fault_time,
            "diagnosis_summary": diagnosis_summary,
            "confirmed_facts": confirmed_facts,
            "inferences": inferences,
            "recommended_solutions": solutions,
            "needs_human": bool(payload.get("needs_human")),
            "completed_at_hkt": _iso(self.now()),
            "rounds": 1,
        }

    def _ensure_ai_diagnosis(self, incident: dict[str, Any]) -> bool:
        diagnosis = incident.get("diagnosis")
        if (
            isinstance(diagnosis, dict)
            and diagnosis.get("ok")
            and diagnosis.get("source") == "llm"
            and not str(diagnosis.get("model") or "").startswith("deterministic-")
        ):
            return True
        if not self.ai_enabled:
            incident["diagnosis_status"] = "disabled"
            return False
        retry_after = _parse_datetime(incident.get("diagnosis_retry_after_hkt"))
        if retry_after and self.now() < retry_after:
            return False
        incident["diagnosis_attempts"] = int(incident.get("diagnosis_attempts") or 0) + 1
        try:
            incident["diagnosis"] = self._diagnose_with_internal_ai(incident)
            incident["diagnosis_status"] = "completed"
            incident.pop("diagnosis_error", None)
            incident.pop("diagnosis_retry_after_hkt", None)
            _append_jsonl(self.events_path, {
                "type": "ai_diagnosis_completed",
                "at_hkt": _iso(self.now()),
                "incident_id": incident.get("incident_id"),
                "model": incident["diagnosis"].get("model"),
                "rounds": 1,
            })
            return True
        except Exception as exc:
            incident["diagnosis_status"] = "failed_waiting_retry"
            incident["diagnosis_error"] = _redact(f"{type(exc).__name__}: {exc}", 700)
            incident["diagnosis_retry_after_hkt"] = _iso(self.now() + timedelta(minutes=5))
            _append_jsonl(self.events_path, {
                "type": "ai_diagnosis_failed_local_only",
                "at_hkt": _iso(self.now()),
                "incident_id": incident.get("incident_id"),
                "error": incident["diagnosis_error"],
            })
            return False

    def _summarize_resolution_with_internal_ai(self, incident: dict[str, Any]) -> dict[str, Any]:
        resolution = incident.get("resolution") if isinstance(incident.get("resolution"), dict) else {}
        prompt_payload = {
            "analysis_kind": "resolution",
            "task": incident.get("task_name"),
            "original_diagnosis": incident.get("diagnosis"),
            "locked_resolution_type": resolution.get("type"),
            "locked_evidence": resolution.get("evidence"),
            "locked_action": resolution.get("action"),
            "resolved_at_hkt": resolution.get("resolved_at_hkt"),
        }
        if self.ai_diagnoser is not None:
            payload = self.ai_diagnoser({**dict(incident), "_analysis_kind": "resolution", "resolution_prompt": prompt_payload})
            model = "test-injected"
            request_id = f"cmhk-resolution-{incident.get('incident_id')}-test"
            raw = json.dumps(payload, ensure_ascii=False)
        else:
            from ai_config import INTERNAL_AI_BASE_URL, load_ai_config
            from ai_rate_limit import wait_for_internal_ai_slot
            from network_utils import urlopen_with_local_proxy_fallback

            config = load_ai_config(include_key=True)
            api_key = str(config.get("api_key") or "").strip()
            base_url = str(config.get("base_url") or INTERNAL_AI_BASE_URL).rstrip("/")
            model = str(self.environ.get("CMHK_ALERT_AI_MODEL") or config.get("model") or "deepseek-v4").strip()
            if not api_key or not base_url or not model:
                raise RuntimeError("内部AI配置不完整")
            request_id = f"cmhk-resolution-{incident.get('incident_id')}-a{int(resolution.get('ai_attempts') or 1)}"
            body = prepare_structured_chat_body({
                **dict(config.get("extra_parameters") or {}),
                "model": model,
                "messages": [
                    {"role": "system", "content": (
                        "你是生产运维结案分析员。只根据已锁定的恢复类型、证据和动作写结论，不得把条件消失写成自动修复。"
                        "输出单一JSON对象，字段为resolution_summary、recovery_cause、verification_summary、remaining_risk、needs_followup。"
                        "不得改写恢复类型、时间、证据或动作；没有修复动作时必须明确说明。"
                    )},
                    {"role": "user", "content": json.dumps(prompt_payload, ensure_ascii=False)},
                ],
                "temperature": 0.1,
                "max_tokens": 650,
            })
            request = urllib.request.Request(
                f"{base_url}/chat/completions?request_id={request_id}",
                data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
                headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json", "Cache-Control": "no-cache, no-store", "X-Request-ID": request_id},
                method="POST",
            )
            wait_for_internal_ai_slot("project-monitor-resolution", deadline_monotonic=time.monotonic() + 45)
            with open_llm_request(
                request,
                timeout=35,
                config=config,
                requested_key=api_key,
                model=model,
                open_func=urlopen_with_local_proxy_fallback,
            ) as response:
                response_payload = json.loads(response.read().decode("utf-8"))
            raw = final_chat_message_text(response_payload, operation="运维告警结案")
            payload = load_json_response(raw, operation="运维告警结案")
        if not isinstance(payload, dict):
            raise ValueError("AI结案未返回JSON对象")
        required = ("resolution_summary", "recovery_cause", "verification_summary", "remaining_risk", "needs_followup")
        if any(key not in payload for key in required) or type(payload.get("needs_followup")) is not bool:
            raise ValueError("AI结案缺少必填字段或 needs_followup 不是布林值")
        result = {key: _to_simplified(_redact(payload.get(key), 900)) for key in required[:-1]}
        if any(not result[key] for key in required[:-1]):
            raise ValueError("AI结案关键字段为空")
        result.update({
            "ok": True,
            "source": "llm",
            "model": model,
            "request_id": request_id,
            "response_sha256": hashlib.sha256(raw.encode("utf-8")).hexdigest(),
            "needs_followup": bool(payload.get("needs_followup")),
            "completed_at_hkt": _iso(self.now()),
        })
        return result

    def _ensure_resolution_ai_summary(self, incident: dict[str, Any]) -> bool:
        resolution = incident.get("resolution") if isinstance(incident.get("resolution"), dict) else {}
        if resolution.get("status") != "evidence_verified":
            return False
        ai_summary = resolution.get("ai_summary") if isinstance(resolution.get("ai_summary"), dict) else {}
        if ai_summary.get("ok") and ai_summary.get("source") == "llm":
            return True
        retry_after = _parse_datetime(resolution.get("ai_retry_after_hkt"))
        if retry_after and self.now() < retry_after:
            return False
        resolution["ai_attempts"] = int(resolution.get("ai_attempts") or 0) + 1
        try:
            resolution["ai_summary"] = self._summarize_resolution_with_internal_ai(incident)
            resolution["ai_status"] = "completed"
            resolution.pop("ai_error", None)
            resolution.pop("ai_retry_after_hkt", None)
            return True
        except Exception as exc:
            resolution["ai_status"] = "failed_waiting_retry"
            resolution["ai_error"] = _redact(f"{type(exc).__name__}: {exc}", 700)
            resolution["ai_retry_after_hkt"] = _iso(self.now() + timedelta(minutes=5))
            return False
    def _card_markdown_text(self, value: object, limit: int = 1800) -> str:
        text = _to_simplified(_redact(value, limit)).replace("&", "&amp;").replace("<", "&#60;").replace(">", "&#62;")
        for character in ("\\", "`", "*", "_", "~", "[", "]", "(", ")", "#"):
            text = text.replace(character, "\\" + character)
        return text.replace("\r", "")

    def render_alert_card(self, incident: dict[str, Any]) -> dict[str, Any]:
        diagnosis = incident.get("diagnosis") if isinstance(incident.get("diagnosis"), dict) else {}
        if not (
            diagnosis.get("ok")
            and diagnosis.get("source") == "llm"
            and not str(diagnosis.get("model") or "").startswith("deterministic-")
        ):
            raise ValueError("alert rendering requires a completed AI diagnosis")
        card_actions = (
            self.config.get("card_actions")
            if isinstance(self.config.get("card_actions"), dict)
            else {}
        )
        handler_open_id = str(card_actions.get("primary_handler_open_id") or "")
        action_name = str(card_actions.get("action") or "")
        if not handler_open_id.startswith("ou_") or not action_name:
            raise ValueError("interactive card handler configuration is incomplete")
        solutions = (
            diagnosis.get("recommended_solutions")
            if isinstance(diagnosis.get("recommended_solutions"), list)
            else []
        )
        solution_lines = "\n".join(
            f"{index}. {self._card_markdown_text(_solution_text(item, 450), 450)}"
            for index, item in enumerate(solutions, start=1)
        )
        severity = str(diagnosis.get("severity") or incident.get("severity") or "P2")
        palette = {
            "P1": {"template": "red", "background": "red-50", "tag": "red"},
            "P2": {"template": "orange", "background": "orange-50", "tag": "orange"},
            "P3": {"template": "blue", "background": "blue-50", "tag": "blue"},
        }.get(severity, {"template": "orange", "background": "orange-50", "tag": "orange"})
        needs_human = "是" if diagnosis.get("needs_human") else "否"
        task_name_plain = _to_simplified(
            _alert_plain(incident.get("task_name") or "-", 100)
        ).replace("\n", " ")
        task_name = self._card_markdown_text(task_name_plain, 100)
        fault_time_plain = _alert_plain(diagnosis.get("fault_time_hkt") or "-", 100)
        fault_time = self._card_markdown_text(fault_time_plain, 100)
        fault_cause = self._card_markdown_text(diagnosis.get("fault_cause") or "-", 900)
        fault_impact = self._card_markdown_text(diagnosis.get("fault_impact") or "-", 900)
        severity_reason = self._card_markdown_text(diagnosis.get("severity_reason") or "-", 600)
        error_evidence = self._card_markdown_text(
            incident.get("error") or incident.get("summary") or "-",
            1800,
        )
        floor_note = ""
        if diagnosis.get("severity_floor_applied"):
            floor_note = (
                f"\n系统规则最低为 `{self._card_markdown_text(diagnosis.get('rule_severity_floor'), 10)}`；"
                f"LLM 原始输出 `{self._card_markdown_text(diagnosis.get('llm_severity'), 10)}`，"
                "已按安全规则采用较高等级。"
            )
        incident_id = _alert_plain(incident.get("incident_id"), 80)
        model = self._card_markdown_text(diagnosis.get("model") or "-", 100)
        severity_label = SEVERITY_LABELS.get(severity, "高")
        callback_value = {
            "action": action_name,
            "incident_id": incident_id,
            "project": "cmhk-main",
            "version": 1,
        }
        return {
            "schema": "2.0",
            "config": {
                "update_multi": True,
                "width_mode": "default",
                "enable_forward": True,
                "summary": {"content": f"{severity} {severity_label}故障 · {task_name_plain}"},
                "style": {
                    "text_size": {
                        "body": {"default": "normal", "pc": "normal", "mobile": "normal"},
                        "caption": {
                            "default": "notation",
                            "pc": "notation",
                            "mobile": "notation",
                        },
                    }
                },
            },
            "header": {
                "title": {
                    "tag": "plain_text",
                    "content": f"{severity}｜{severity_label}故障 · {task_name_plain}",
                },
                "subtitle": {
                    "tag": "plain_text",
                    "content": f"{fault_time_plain} · 告警 ID {incident_id}",
                },
                "template": palette["template"],
                "icon": {"tag": "standard_icon", "token": "warning_outlined"},
                "text_tag_list": [
                    {
                        "tag": "text_tag",
                        "text": {"tag": "plain_text", "content": f"{severity} {severity_label}"},
                        "color": palette["tag"],
                    },
                    {
                        "tag": "text_tag",
                        "text": {"tag": "plain_text", "content": "待处理"},
                        "color": "yellow",
                    },
                ],
            },
            "body": {
                "direction": "vertical",
                "padding": "12px 12px 20px 12px",
                "vertical_spacing": "12px",
                "elements": [
                    {
                        "tag": "div",
                        "element_id": "alertMeta",
                        "fields": [
                            {
                                "is_short": True,
                                "text": {
                                    "tag": "lark_md",
                                    "content": f"**重要等级（LLM 复核）**\n{severity} {severity_label}",
                                },
                            },
                            {
                                "is_short": True,
                                "text": {"tag": "lark_md", "content": f"**故障时间**\n{fault_time}"},
                            },
                            {
                                "is_short": True,
                                "text": {
                                    "tag": "lark_md",
                                    "content": f"**需要人工介入**\n{needs_human}",
                                },
                            },
                            {
                                "is_short": True,
                                "text": {"tag": "lark_md", "content": f"**AI 模型**\n{model}"},
                            },
                        ],
                    },
                    {
                        "tag": "column_set",
                        "element_id": "diagnosisBlock",
                        "flex_mode": "none",
                        "columns": [
                            {
                                "tag": "column",
                                "width": "weighted",
                                "weight": 1,
                                "background_style": palette["background"],
                                "padding": "12px",
                                "vertical_spacing": "8px",
                                "elements": [
                                    {
                                        "tag": "markdown",
                                        "content": f"**故障影响**\n{fault_impact}",
                                    },
                                    {
                                        "tag": "markdown",
                                        "content": f"**故障原因**\n{fault_cause}",
                                    },
                                    {
                                        "tag": "markdown",
                                        "content": (
                                            f"**重要程度判断**\n{severity_reason}{floor_note}"
                                        ),
                                    },
                                ],
                            }
                        ],
                    },
                    {
                        "tag": "collapsible_panel",
                        "element_id": "evidencePanel",
                        "expanded": False,
                        "background_color": "grey-50",
                        "padding": "8px",
                        "header": {
                            "title": {"tag": "plain_text", "content": "查看原始错误证据"},
                            "width": "fill",
                        },
                        "elements": [
                            {
                                "tag": "markdown",
                                "content": f"```text\n{error_evidence}\n```",
                                "text_size": "caption",
                            }
                        ],
                    },
                    {
                        "tag": "markdown",
                        "element_id": "solutionBlock",
                        "content": f"**建议解决方案**\n{solution_lines}",
                    },
                    {
                        "tag": "column_set",
                        "element_id": "actionBlock",
                        "flex_mode": "none",
                        "columns": [
                            {
                                "tag": "column",
                                "width": "weighted",
                                "weight": 1,
                                "background_style": "grey-50",
                                "padding": "12px",
                                "vertical_spacing": "8px",
                                "elements": [
                                    {
                                        "tag": "markdown",
                                        "element_id": "handlerPrompt",
                                        "content": (
                                            f"**处理人**　请 <at id={handler_open_id}></at> 处理此故障。"
                                        ),
                                    },
                                    {
                                        "tag": "button",
                                        "element_id": "resolveButton",
                                        "text": {"tag": "plain_text", "content": "已处理"},
                                        "type": "primary_filled",
                                        "size": "medium",
                                        "width": "fill",
                                        "behaviors": [
                                            {"type": "callback", "value": callback_value}
                                        ],
                                        "confirm": {
                                            "title": {
                                                "tag": "plain_text",
                                                "content": "确认已处理？",
                                            },
                                            "text": {
                                                "tag": "plain_text",
                                                "content": "确认后会把你的飞书姓名写入错误台账。",
                                            },
                                        },
                                    },
                                ],
                            }
                        ],
                    },
                ],
            },
        }

    def render_alert(self, incident: dict[str, Any]) -> str:
        return json.dumps(self.render_alert_card(incident), ensure_ascii=False, separators=(",", ":"))

    def _resolution_reason_text(self, incident: dict[str, Any]) -> str:
        reason = str(incident.get("resolution_reason") or "")
        messages = {
            "log_condition_cleared": "后续巡检未再发现同一类新增错误。",
            "media_metrics_delivery_verified": "对应时段汇总已发送并完成消息回读。",
            "condition_no_longer_current": "后续任务归档或状态记录已不再显示该故障。",
            "service_restarted_after_error": "相关服务在故障后已重新启动，后续巡检未再命中该错误。",
            "superseded_by_stable_log_condition": "旧版重复日志告警已由稳定的同类故障状态取代。",
        }
        return messages.get(reason, "后续巡检确认该故障条件已不再成立。")

    def render_resolved_card(self, incident: dict[str, Any]) -> dict[str, Any]:
        card = self.render_alert_card(incident)
        resolution = incident.get("resolution") if isinstance(incident.get("resolution"), dict) else {}
        ai_summary = resolution.get("ai_summary") if isinstance(resolution.get("ai_summary"), dict) else {}
        if not (resolution.get("status") == "evidence_verified" and ai_summary.get("ok") and ai_summary.get("source") == "llm"):
            raise ValueError("resolved card requires verified evidence and a completed LLM resolution summary")
        task_name_plain = _to_simplified(
            _alert_plain(incident.get("task_name") or "-", 100)
        ).replace("\n", " ")
        incident_id = _alert_plain(incident.get("incident_id"), 80)
        severity = str((incident.get("diagnosis") or {}).get("severity") or incident.get("severity") or "P2")
        severity_label = SEVERITY_LABELS.get(severity, "高")
        resolved_at_plain = _alert_plain(incident.get("resolved_at_hkt") or _iso(self.now()), 100)
        resolved_at = self._card_markdown_text(resolved_at_plain, 100)
        reason = self._card_markdown_text(ai_summary.get("verification_summary") or self._resolution_reason_text(incident), 900)
        recovery_cause = self._card_markdown_text(ai_summary.get("recovery_cause") or "-", 900)
        remaining_risk = self._card_markdown_text(ai_summary.get("remaining_risk") or "-", 900)
        resolution_type = str(resolution.get("type") or "condition_cleared")
        labels = {
            "automatic_recovery": "已自动恢复",
            "normal_task_progress": "已确认任务正常",
            "service_restarted": "服务已恢复",
            "condition_cleared": "故障已恢复（已验证）",
            "false_positive": "已确认为误报",
            "superseded": "已由新口径接管",
        }
        resolution_label = labels.get(resolution_type, "恢复证据已确认")

        card["config"]["summary"] = {"content": f"{resolution_label} · {task_name_plain}"}
        card["header"] = {
            "title": {"tag": "plain_text", "content": f"{resolution_label}｜{task_name_plain}"},
            "subtitle": {
                "tag": "plain_text",
                "content": f"{resolved_at_plain} · 告警 ID {incident_id}",
            },
            "template": "green",
            "icon": {"tag": "standard_icon", "token": "done_outlined"},
            "text_tag_list": [
                {
                    "tag": "text_tag",
                    "text": {"tag": "plain_text", "content": resolution_label},
                    "color": "green",
                },
                {
                    "tag": "text_tag",
                    "text": {"tag": "plain_text", "content": f"原 {severity} {severity_label}"},
                    "color": "grey",
                },
            ],
        }
        body = card.get("body") if isinstance(card.get("body"), dict) else {}
        elements = body.get("elements") if isinstance(body.get("elements"), list) else []
        elements = [
            {
                "tag": "column_set",
                "element_id": "resolutionBlock",
                "flex_mode": "none",
                "columns": [
                    {
                        "tag": "column",
                        "width": "weighted",
                        "weight": 1,
                        "background_style": "green-50",
                        "padding": "12px",
                        "vertical_spacing": "8px",
                        "elements": [
                            {
                                "tag": "markdown",
                                "content": (
                                    f"**结案时间**\n{resolved_at}\n\n"
                                    f"**恢复原因（LLM）**\n{recovery_cause}\n\n"
                                    f"**验证依据**\n{reason}\n\n"
                                    f"**剩余风险**\n{remaining_risk}\n\n"
                                    f"模型：`{self._card_markdown_text(ai_summary.get('model') or '-', 100)}`；"
                                    "恢复类型、时间、证据和动作由程序锁定，LLM 只负责据实归纳。"
                                ),
                            }
                        ],
                    }
                ],
            },
            *[
                element
                for element in elements
                if not (isinstance(element, dict) and element.get("element_id") == "actionBlock")
            ],
        ]
        body["elements"] = elements
        card["body"] = body
        return card

    def render_manually_repaired_card(
        self,
        incident: dict[str, Any],
        *,
        handler_name: str,
        handled_at_hkt: str,
        handler_open_id: str = "",
    ) -> dict[str, Any]:
        card = self.render_alert_card(incident)
        task_name_plain = _to_simplified(
            _alert_plain(incident.get("task_name") or "-", 100)
        ).replace("\n", " ")
        incident_id = _alert_plain(incident.get("incident_id"), 80)
        handled_at_plain = _alert_plain(handled_at_hkt, 100)
        handled_at = self._card_markdown_text(handled_at_plain, 100)
        safe_name = self._card_markdown_text(handler_name, 120)
        handler = (
            f"<at id={handler_open_id}></at>"
            if str(handler_open_id).startswith("ou_")
            else safe_name
        )
        body = card.get("body") if isinstance(card.get("body"), dict) else {}
        elements = body.get("elements") if isinstance(body.get("elements"), list) else []
        elements = [
            element
            for element in elements
            if not (
                isinstance(element, dict)
                and element.get("element_id") in {"actionBlock", "manualRepairBlock"}
            )
        ]
        elements.insert(
            0,
            {
                "tag": "column_set",
                "element_id": "manualRepairBlock",
                "flex_mode": "none",
                "columns": [
                    {
                        "tag": "column",
                        "width": "weighted",
                        "weight": 1,
                        "background_style": "green-50",
                        "padding": "12px",
                        "vertical_spacing": "8px",
                        "elements": [
                            {
                                "tag": "markdown",
                                "content": (
                                    f"**人工修复时间**\n{handled_at}\n\n"
                                    f"**修复人员**\n{handler}"
                                ),
                            }
                        ],
                    }
                ],
            },
        )
        body["elements"] = elements
        card["body"] = body
        header = card.get("header") if isinstance(card.get("header"), dict) else {}
        header["title"] = {
            "tag": "plain_text",
            "content": f"已人工修复｜{task_name_plain}",
        }
        header["subtitle"] = {
            "tag": "plain_text",
            "content": f"{handled_at_plain} · 告警 ID {incident_id}",
        }
        header["template"] = "green"
        header["icon"] = {"tag": "standard_icon", "token": "done_outlined"}
        tags = [
            {
                "tag": "text_tag",
                "text": {"tag": "plain_text", "content": "人工修复"},
                "color": "green",
            }
        ]
        if incident.get("status") == "resolved":
            tags.append(
                {
                    "tag": "text_tag",
                    "text": {"tag": "plain_text", "content": "自动恢复已确认"},
                    "color": "turquoise",
                }
            )
        header["text_tag_list"] = tags
        card["header"] = header
        config = card.get("config") if isinstance(card.get("config"), dict) else {}
        config["summary"] = {"content": f"已人工修复 · {handler_name} · {task_name_plain}"}
        card["config"] = config
        return card

    def _readback_resolution_update(
        self,
        incident: dict[str, Any],
        delivery: dict[str, Any],
        target: dict[str, Any],
        *,
        expected_marker: str = "已恢复",
    ) -> None:
        bot = self.config.get("bot") if isinstance(self.config.get("bot"), dict) else {}
        profile = str(bot.get("profile") or "")
        message_id = str(delivery.get("message_id") or "")
        proc = self._run(
            [
                "lark-cli", "im", "+messages-mget", "--as", "bot", "--profile", profile,
                "--message-ids", message_id, "--no-reactions", "--format", "json",
            ],
            timeout=20,
        )
        payload = self._json_from_process(proc)
        data = payload.get("data") if isinstance(payload.get("data"), dict) else payload
        messages = data.get("messages") if isinstance(data, dict) else []
        messages = messages if isinstance(messages, list) else []
        message = next(
            (item for item in messages if str(item.get("message_id") or "") == message_id),
            None,
        )
        if not isinstance(message, dict):
            raise RuntimeError("恢复卡片更新后未能回读")
        sender = message.get("sender") if isinstance(message.get("sender"), dict) else {}
        content = str(message.get("content") or "")
        if (
            str(message.get("chat_id") or "") != str(target.get("chat_id") or "")
            or str(sender.get("id") or sender.get("sender_id") or "") != str(bot.get("app_id") or "")
            or str(message.get("msg_type") or "") != "interactive"
            or expected_marker not in content
            or str(incident.get("incident_id") or "") not in content
        ):
            raise RuntimeError("恢复卡片更新后的群、发送者或内容回读不一致")

    def _manual_repair_record(self, incident_id: str) -> dict[str, Any]:
        candidates: list[dict[str, Any]] = []
        action_state = _read_json(self.state_dir / "card_actions.json", {})
        handled_messages = (
            action_state.get("handled_messages") if isinstance(action_state, dict) else {}
        )
        if isinstance(handled_messages, dict):
            candidates.extend(
                item for item in handled_messages.values() if isinstance(item, dict)
            )
        try:
            lines = (self.state_dir / "web_actions.jsonl").read_text(encoding="utf-8").splitlines()
        except OSError:
            lines = []
        for line in lines:
            try:
                item = json.loads(line)
            except (TypeError, ValueError, json.JSONDecodeError):
                continue
            if isinstance(item, dict):
                candidates.append(item)
        matching = [
            item for item in candidates if str(item.get("incident_id") or "") == incident_id
        ]
        return max(
            matching,
            key=lambda item: str(item.get("handled_at_hkt") or item.get("completed_at_hkt") or ""),
            default={},
        )

    def _update_resolved_deliveries(self) -> int:
        if not self.resolution_message_updates_enabled:
            return 0
        config = self.config.get("resolution_message_updates") or {}
        backfill_from = _parse_datetime(config.get("backfill_from_hkt"))
        updated_count = 0
        targets = {
            str(item.get("chat_id") or ""): item
            for item in self.alert_targets
            if str(item.get("chat_id") or "")
        }
        records = [
            item
            for item in (self.state.get("incidents") or {}).values()
            if isinstance(item, dict) and item.get("status") == "resolved"
        ]
        records.sort(key=lambda item: str(item.get("resolved_at_hkt") or ""))
        for incident in records:
            manual = self._manual_repair_record(str(incident.get("incident_id") or ""))
            if not manual and not self._ensure_resolution_ai_summary(incident):
                continue
            resolved_at = _parse_datetime(incident.get("resolved_at_hkt"))
            if backfill_from and (not resolved_at or resolved_at < backfill_from):
                continue
            deliveries = incident.get("delivery") if isinstance(incident.get("delivery"), dict) else {}
            for chat_id, delivery in deliveries.items():
                if not isinstance(delivery, dict) or delivery.get("state") != "verified":
                    continue
                target = targets.get(str(chat_id))
                message_id = str(delivery.get("message_id") or "")
                if not target or not message_id.startswith("om_"):
                    continue
                resolution_update = delivery.get("resolution_update")
                resolution_update = resolution_update if isinstance(resolution_update, dict) else {}
                if resolution_update.get("state") == "verified":
                    continue
                retry_after = _parse_datetime(resolution_update.get("retry_after_hkt"))
                if retry_after and self.now() < retry_after:
                    continue
                try:
                    self._verify_bot_identity()
                    self._verify_target(target)
                    card = (
                        self.render_manually_repaired_card(
                            incident,
                            handler_name=str(manual.get("operator_name") or "已记录人员"),
                            handled_at_hkt=str(
                                manual.get("handled_at_hkt")
                                or manual.get("completed_at_hkt")
                                or ""
                            ),
                            handler_open_id=str(manual.get("operator_id") or ""),
                        )
                        if manual
                        else self.render_resolved_card(incident)
                    )
                    content = json.dumps(
                        card,
                        ensure_ascii=False,
                        separators=(",", ":"),
                    )
                    proc = self._run(
                        [
                            "lark-cli", "api", "PATCH",
                            f"/open-apis/im/v1/messages/{message_id}",
                            "--as", "bot", "--profile",
                            str((self.config.get("bot") or {}).get("profile") or ""),
                            "--data", json.dumps({"content": content}, ensure_ascii=False),
                            "--format", "json",
                        ],
                        timeout=30,
                    )
                    self._json_from_process(proc)
                    self._readback_resolution_update(
                        incident,
                        delivery,
                        target,
                        expected_marker="已人工修复" if manual else str(card.get("header", {}).get("title", {}).get("content", "")).split("｜", 1)[0],
                    )
                    delivery["resolution_update"] = {
                        "state": "verified",
                        "updated_at_hkt": _iso(self.now()),
                        "message_id": message_id,
                    }
                    updated_count += 1
                    _append_jsonl(
                        self.events_path,
                        {
                            "type": "alert_resolution_update_verified",
                            "at_hkt": _iso(self.now()),
                            "incident_id": incident.get("incident_id"),
                            "chat_id": chat_id,
                            "message_id": message_id,
                        },
                    )
                except Exception as exc:
                    delivery["resolution_update"] = {
                        "state": "failed_waiting_retry",
                        "attempted_at_hkt": _iso(self.now()),
                        "retry_after_hkt": _iso(self.now() + timedelta(minutes=5)),
                        "error": _redact(f"{type(exc).__name__}: {exc}", 700),
                    }
                    _append_jsonl(
                        self.events_path,
                        {
                            "type": "alert_resolution_update_failed_local_only",
                            "at_hkt": _iso(self.now()),
                            "incident_id": incident.get("incident_id"),
                            "chat_id": chat_id,
                            "message_id": message_id,
                            "error": delivery["resolution_update"]["error"],
                        },
                    )
        return updated_count

    def _json_from_process(self, proc: subprocess.CompletedProcess[str]) -> dict[str, Any]:
        raw = proc.stdout if proc.returncode == 0 else (proc.stderr or proc.stdout)
        try:
            payload = json.loads(raw or "{}")
        except (TypeError, ValueError, json.JSONDecodeError) as exc:
            raise RuntimeError(f"lark-cli returned non-JSON output: {_redact(raw, 500)}") from exc
        if proc.returncode != 0 or payload.get("ok") is False:
            error = payload.get("error") if isinstance(payload, dict) else {}
            raise RuntimeError(_redact((error or {}).get("message") or raw, 600))
        return payload

    def _verify_bot_identity(self) -> dict[str, Any]:
        bot = self.config.get("bot") if isinstance(self.config.get("bot"), dict) else {}
        profile = str(bot.get("profile") or "")
        proc = self._run(["lark-cli", "whoami", "--as", "bot", "--profile", profile], timeout=15)
        payload = self._json_from_process(proc)
        if (
            str(payload.get("identity") or "") != "bot"
            or not payload.get("available")
            or str(payload.get("appId") or "") != str(bot.get("app_id") or "")
            or str(payload.get("profile") or "") != profile
        ):
            raise RuntimeError("机器人身份校验失败，发送已关闭")
        return payload

    def _verify_target(self, target: dict[str, Any]) -> dict[str, Any]:
        bot = self.config.get("bot") if isinstance(self.config.get("bot"), dict) else {}
        profile = str(bot.get("profile") or "")
        chat_id = str(target.get("chat_id") or "")
        proc = self._run(
            [
                "lark-cli",
                "im",
                "chats",
                "get",
                "--as",
                "bot",
                "--profile",
                profile,
                "--params",
                json.dumps({"chat_id": chat_id}, ensure_ascii=False),
                "--format",
                "json",
            ],
            timeout=20,
        )
        payload = self._json_from_process(proc)
        data = payload.get("data") if isinstance(payload.get("data"), dict) else {}
        if (
            str(data.get("name") or "") != str(target.get("expected_name") or "")
            or str(data.get("chat_mode") or "") != "group"
            or str(data.get("chat_status") or "") != "normal"
            or bool(data.get("external"))
        ):
            raise RuntimeError(
                "目标群实时元数据与白名单不一致，发送已关闭："
                f"expected={target.get('expected_name')}; actual={data.get('name')}"
            )
        return data

    def _verify_primary_handler(self) -> dict[str, Any]:
        bot = self.config.get("bot") if isinstance(self.config.get("bot"), dict) else {}
        profile = str(bot.get("profile") or "")
        actions = self.config.get("card_actions") if isinstance(self.config.get("card_actions"), dict) else {}
        open_id = str(actions.get("primary_handler_open_id") or "")
        proc = self._run(
            [
                "lark-cli",
                "contact",
                "+get-user",
                "--user-id",
                open_id,
                "--user-id-type",
                "open_id",
                "--as",
                "bot",
                "--profile",
                profile,
                "--format",
                "json",
            ],
            timeout=20,
        )
        payload = self._json_from_process(proc)
        data = payload.get("data") if isinstance(payload.get("data"), dict) else {}
        user = data.get("user") if isinstance(data.get("user"), dict) else {}
        if (
            str(user.get("open_id") or "") != open_id
            or str(user.get("name") or "") != str(actions.get("primary_handler_expected_name") or "")
        ):
            raise RuntimeError("卡片@处理人身份校验失败，发送已关闭")
        return user

    def _send_to_target(self, incident: dict[str, Any], target: dict[str, Any]) -> dict[str, Any]:
        if not self.notifications_enabled:
            raise RuntimeError("notification gate is disabled")
        if not (incident.get("diagnosis") or {}).get("ok"):
            raise RuntimeError("AI diagnosis gate is incomplete")
        chat_id = str(target.get("chat_id") or "")
        if chat_id not in {str(item.get("chat_id") or "") for item in self.alert_targets}:
            raise RuntimeError("目标群未在报障推送路由内，发送已关闭")
        if not self._target_accepts_incident(incident, target):
            raise RuntimeError("故障早于目标群路由生效时间，禁止历史补发")
        bot = self.config.get("bot") if isinstance(self.config.get("bot"), dict) else {}
        profile = str(bot.get("profile") or "")
        self._verify_bot_identity()
        self._verify_target(target)
        self._verify_primary_handler()
        content = self.render_alert(incident)
        idempotency = "cmhk-alert-" + _fingerprint(incident.get("incident_id"), chat_id)[:32]
        proc = self._run(
            [
                "lark-cli",
                "im",
                "+messages-send",
                "--as",
                "bot",
                "--profile",
                profile,
                "--chat-id",
                chat_id,
                "--msg-type",
                "interactive",
                "--content",
                content,
                "--idempotency-key",
                idempotency,
                "--format",
                "json",
            ],
            timeout=30,
        )
        payload = self._json_from_process(proc)
        data = payload.get("data") if isinstance(payload.get("data"), dict) else payload
        message_id = str(data.get("message_id") or data.get("messageId") or "")
        if not message_id.startswith("om_"):
            raise RuntimeError("发送返回缺少有效 message_id，状态不确定")
        result = {
            "state": "sent_pending_readback",
            "message_id": message_id,
            "chat_id": chat_id,
            "idempotency_key": idempotency,
            "sent_at_hkt": _iso(self.now()),
        }
        # A successful send followed by a transient readback failure is not a
        # safe reason to resend.  Preserve the message id and retry readback on
        # the next cycle with the same local delivery record.
        try:
            self._readback_delivery(result, target)
        except Exception as exc:
            result["readback_error"] = _redact(f"{type(exc).__name__}: {exc}", 700)
        return result

    def _readback_delivery(self, delivery: dict[str, Any], target: dict[str, Any]) -> None:
        bot = self.config.get("bot") if isinstance(self.config.get("bot"), dict) else {}
        profile = str(bot.get("profile") or "")
        message_id = str(delivery.get("message_id") or "")
        proc = self._run(
            [
                "lark-cli",
                "im",
                "+messages-mget",
                "--as",
                "bot",
                "--profile",
                profile,
                "--message-ids",
                message_id,
                "--no-reactions",
                "--format",
                "json",
            ],
            timeout=20,
        )
        payload = self._json_from_process(proc)
        data = payload.get("data") if isinstance(payload.get("data"), dict) else payload
        messages = data.get("messages") if isinstance(data, dict) else []
        messages = messages if isinstance(messages, list) else []
        message = next((item for item in messages if str(item.get("message_id") or "") == message_id), None)
        if not isinstance(message, dict):
            raise RuntimeError("告警消息发送后未能回读")
        sender = message.get("sender") if isinstance(message.get("sender"), dict) else {}
        sender_id = str(sender.get("id") or sender.get("sender_id") or "")
        sender_type = str(sender.get("sender_type") or sender.get("type") or "")
        chat_id = str(message.get("chat_id") or delivery.get("chat_id") or "")
        if sender_type not in {"app", "bot"} or sender_id != str(bot.get("app_id") or ""):
            raise RuntimeError("告警消息实际发送者不是白名单机器人")
        if chat_id != str(target.get("chat_id") or ""):
            raise RuntimeError("告警消息回读群与目标群不一致")
        delivery.update(
            {
                "state": "verified",
                "verified_at_hkt": _iso(self.now()),
                "sender_id": sender_id,
                "sender_name": str(sender.get("name") or bot.get("expected_name") or ""),
            }
        )

    def _deliver_incident(self, incident: dict[str, Any]) -> None:
        if not self.notifications_enabled:
            return
        if not incident.get("detected_with_notifications_enabled"):
            incident["delivery_suppressed"] = "detected_while_notifications_disabled"
            return
        deliveries = incident.setdefault("delivery", {})
        eligible_targets: list[dict[str, Any]] = []
        for target in self.alert_targets:
            chat_id = str(target.get("chat_id") or "")
            if self._target_accepts_incident(incident, target):
                eligible_targets.append(target)
                continue
            if not isinstance(deliveries.get(chat_id), dict):
                deliveries[chat_id] = {
                    "state": "suppressed_route_cutover",
                    "reason": "incident_first_seen_before_target_notify_from",
                    "suppressed_at_hkt": _iso(self.now()),
                }
        if not eligible_targets:
            incident["delivery_suppressed"] = "detected_before_active_route_cutover"
            return
        if not self._ensure_ai_diagnosis(incident):
            incident["delivery_suppressed"] = "awaiting_successful_ai_diagnosis"
            return
        incident.pop("delivery_suppressed", None)
        for target in eligible_targets:
            chat_id = str(target.get("chat_id") or "")
            current = deliveries.get(chat_id)
            if isinstance(current, dict) and current.get("state") == "verified":
                continue
            if isinstance(current, dict) and current.get("state") == "sent_pending_readback":
                try:
                    self._readback_delivery(current, target)
                except Exception as exc:
                    current["readback_error"] = _redact(f"{type(exc).__name__}: {exc}", 700)
                continue
            retry_after = _parse_datetime((current or {}).get("retry_after_hkt") if isinstance(current, dict) else "")
            if retry_after and self.now() < retry_after:
                continue
            try:
                delivery = self._send_to_target(incident, target)
                deliveries[chat_id] = delivery
                _append_jsonl(
                    self.events_path,
                    {
                        "type": (
                            "alert_delivery_verified"
                            if delivery.get("state") == "verified"
                            else "alert_delivery_sent_pending_readback"
                        ),
                        "at_hkt": _iso(self.now()),
                        "incident_id": incident.get("incident_id"),
                        "chat_id": chat_id,
                        "message_id": delivery.get("message_id"),
                        "sender_id": delivery.get("sender_id"),
                    },
                )
            except Exception as exc:
                deliveries[chat_id] = {
                    "state": "failed_before_verification",
                    "error": _redact(f"{type(exc).__name__}: {exc}", 700),
                    "attempted_at_hkt": _iso(self.now()),
                    "retry_after_hkt": _iso(self.now() + timedelta(minutes=5)),
                }
                _append_jsonl(
                    self.events_path,
                    {
                        "type": "alert_delivery_failed_local_only",
                        "at_hkt": _iso(self.now()),
                        "incident_id": incident.get("incident_id"),
                        "chat_id": chat_id,
                        "error": deliveries[chat_id]["error"],
                    },
                )

    def _error_ledger_config(self) -> dict[str, Any]:
        config = self.config.get("error_ledger")
        if not isinstance(config, dict):
            raise RuntimeError("错误台账配置缺失")
        config = dict(config)
        runtime_part = active_part(ROOT, ERROR_LEDGER_TARGET_KEY)
        if runtime_part.get("sheet_id") and runtime_part.get("spreadsheet_token"):
            config.update(
                {
                    "spreadsheet_token": runtime_part["spreadsheet_token"],
                    "sheet_id": runtime_part["sheet_id"],
                    "sheet_name": runtime_part.get("sheet_title") or config.get("sheet_name"),
                    "sheet_url": runtime_part.get("sheet_url"),
                }
            )
        columns = tuple(str(item) for item in config.get("columns") or [])
        if columns != ERROR_LEDGER_COLUMNS:
            raise RuntimeError("错误台账列定义与监控程序不一致")
        for field in ("spreadsheet_token", "expected_main_sheet_id", "sheet_id", "sheet_name"):
            if not str(config.get(field) or "").strip():
                raise RuntimeError(f"错误台账配置缺少 {field}")
        return config

    def _maybe_rollover_error_ledger(self, *, used_rows: int, incoming_rows: int) -> bool:
        config = self._error_ledger_config()
        bot = self.config.get("bot") if isinstance(self.config.get("bot"), dict) else {}
        profile = str(bot.get("profile") or "")
        token = str(config.get("spreadsheet_token") or "")
        workbook = self._json_from_process(
            self._run(
                [
                    "lark-cli",
                    "sheets",
                    "+workbook-info",
                    "--spreadsheet-token",
                    token,
                    "--as",
                    "bot",
                    "--profile",
                    profile,
                    "--format",
                    "json",
                ],
                timeout=25,
            )
        )
        workbook_data = workbook.get("data") if isinstance(workbook.get("data"), dict) else {}
        sheets = workbook_data.get("sheets") if isinstance(workbook_data.get("sheets"), list) else []
        decision = capacity_decision(
            used_rows=used_rows,
            incoming_rows=incoming_rows,
            column_count=len(ERROR_LEDGER_COLUMNS),
            sheet_count=len(sheets),
            operational_max_rows=ERROR_LEDGER_OPERATIONAL_MAX_ROWS,
        )
        if not decision.should_rollover:
            return False
        if decision.reason == "workbook_sheet_limit_near":
            raise RuntimeError("错误台账所在工作簿已接近 300 张子表上限，已阻止继续建表")
        titles = {str(item.get("sheet_name") or item.get("title") or "") for item in sheets}
        title = timestamped_part_title("项目错误告警", existing_titles=titles)
        created = self._json_from_process(
            self._run(
                [
                    "lark-cli",
                    "sheets",
                    "+sheet-create",
                    "--spreadsheet-token",
                    token,
                    "--title",
                    title,
                    "--row-count",
                    "1000",
                    "--col-count",
                    str(len(ERROR_LEDGER_COLUMNS)),
                    "--as",
                    "bot",
                    "--profile",
                    profile,
                    "--format",
                    "json",
                ],
                timeout=45,
            )
        )
        data = created.get("data") if isinstance(created.get("data"), dict) else {}
        new_sheet_id = str(data.get("sheet_id") or data.get("sheetId") or "")
        if not new_sheet_id:
            refreshed = self._json_from_process(
                self._run(
                    [
                        "lark-cli", "sheets", "+workbook-info",
                        "--spreadsheet-token", token,
                        "--as", "bot", "--profile", profile, "--format", "json",
                    ],
                    timeout=25,
                )
            )
            refreshed_data = refreshed.get("data") if isinstance(refreshed.get("data"), dict) else {}
            new_sheet_id = next(
                (
                    str(item.get("sheet_id") or "")
                    for item in (refreshed_data.get("sheets") or [])
                    if str(item.get("sheet_name") or item.get("title") or "") == title
                ),
                "",
            )
        if not new_sheet_id:
            raise RuntimeError("错误台账新分卷创建后未能回读 sheet_id")
        writes = [{"sheet_id": new_sheet_id, "range": "A1:Q1", "cells": [[{"value": value} for value in ERROR_LEDGER_COLUMNS]]}]
        self._json_from_process(
            self._run(
                [
                    "lark-cli", "sheets", "+cells-set",
                    "--spreadsheet-token", token,
                    "--writes", json.dumps(writes, ensure_ascii=False),
                    "--as", "bot", "--profile", profile, "--format", "json",
                ],
                timeout=45,
            )
        )
        previous = {
            "spreadsheet_token": token,
            "sheet_id": str(config.get("sheet_id") or ""),
            "sheet_title": str(config.get("sheet_name") or ""),
            "sheet_url": str(config.get("sheet_url") or sheet_url(token, str(config.get("sheet_id") or ""))),
        }
        record_active_part(
            ROOT,
            ERROR_LEDGER_TARGET_KEY,
            spreadsheet_token=token,
            sheet_id=new_sheet_id,
            sheet_title=title,
            decision=decision,
            previous=previous,
        )
        self._ledger_verified_this_process = False
        return True

    def _ledger_command_timeout(
        self, deadline_monotonic: float | None, maximum: float
    ) -> float:
        if deadline_monotonic is None:
            return maximum
        remaining = deadline_monotonic - time.monotonic()
        if remaining <= 1:
            raise TimeoutError("error ledger sync exceeded its per-cycle time budget")
        return max(1.0, min(maximum, remaining))

    def _read_error_ledger(
        self, *, deadline_monotonic: float | None = None
    ) -> tuple[list[list[str]], dict[str, int]]:
        config = self._error_ledger_config()
        bot = self.config.get("bot") if isinstance(self.config.get("bot"), dict) else {}
        profile = str(bot.get("profile") or "")
        token = str(config.get("spreadsheet_token") or "")
        sheet_id = str(config.get("sheet_id") or "")
        sheet_name = str(config.get("sheet_name") or "")
        self._verify_bot_identity()
        workbook = self._json_from_process(
            self._run(
                [
                    "lark-cli",
                    "sheets",
                    "+workbook-info",
                    "--spreadsheet-token",
                    token,
                    "--as",
                    "bot",
                    "--profile",
                    profile,
                    "--format",
                    "json",
                ],
                timeout=self._ledger_command_timeout(deadline_monotonic, 25),
            )
        )
        workbook_data = workbook.get("data") if isinstance(workbook.get("data"), dict) else {}
        sheets = workbook_data.get("sheets") if isinstance(workbook_data.get("sheets"), list) else []
        ledger_sheet = next(
            (item for item in sheets if str(item.get("sheet_id") or "") == sheet_id),
            None,
        )
        if not isinstance(ledger_sheet, dict) or str(ledger_sheet.get("sheet_name") or "") != sheet_name:
            raise RuntimeError("错误台账子表 ID 或名称与白名单不一致")
        main_sheet = next(
            (
                item
                for item in sheets
                if str(item.get("sheet_id") or "") == str(config.get("expected_main_sheet_id") or "")
            ),
            None,
        )
        if not isinstance(main_sheet, dict) or str(main_sheet.get("sheet_name") or "") != "主表":
            raise RuntimeError("目标工作簿的主表身份校验失败")
        row_count = max(2, int(ledger_sheet.get("row_count") or 0))
        rows_by_number: dict[int, list[str]] = {}
        expected_columns = [chr(ord("A") + index) for index in range(17)]
        for chunk_start in range(1, row_count + 1, ERROR_LEDGER_READ_CHUNK_ROWS):
            chunk_timeout = self._ledger_command_timeout(deadline_monotonic, 30)
            chunk_end = min(row_count, chunk_start + ERROR_LEDGER_READ_CHUNK_ROWS - 1)
            cells_payload = self._json_from_process(
                self._run(
                    [
                        "lark-cli",
                        "sheets",
                        "+cells-get",
                        "--spreadsheet-token",
                        token,
                        "--sheet-id",
                        sheet_id,
                        "--range",
                        f"A{chunk_start}:Q{chunk_end}",
                        "--include",
                        "value",
                        "--max-chars",
                        "1000000",
                        "--as",
                        "bot",
                        "--profile",
                        profile,
                        "--format",
                        "json",
                    ],
                    timeout=chunk_timeout,
                )
            )
            cells_data = (
                cells_payload.get("data")
                if isinstance(cells_payload.get("data"), dict)
                else {}
            )
            if cells_data.get("has_more"):
                raise RuntimeError(
                    f"错误台账单元格回读被截断：{chunk_start}:{chunk_end}"
                )
            ranges = (
                cells_data.get("ranges")
                if isinstance(cells_data.get("ranges"), list)
                else []
            )
            if len(ranges) != 1 or not isinstance(ranges[0], dict):
                raise RuntimeError(
                    f"错误台账单元格回读未返回唯一范围：{chunk_start}:{chunk_end}"
                )
            result = ranges[0]
            if result.get("truncated"):
                raise RuntimeError(
                    f"错误台账单元格回读范围被截断：{chunk_start}:{chunk_end}"
                )
            row_indices = (
                result.get("row_indices")
                if isinstance(result.get("row_indices"), list)
                else []
            )
            col_indices = (
                result.get("col_indices")
                if isinstance(result.get("col_indices"), list)
                else []
            )
            raw_cells = (
                result.get("cells") if isinstance(result.get("cells"), list) else []
            )
            if col_indices != expected_columns:
                raise RuntimeError(
                    f"错误台账单元格回读列范围不一致：{chunk_start}:{chunk_end}"
                )
            for index, raw_row in enumerate(raw_cells):
                if index >= len(row_indices):
                    break
                row_number = int(row_indices[index])
                if row_number < chunk_start or row_number > chunk_end:
                    raise RuntimeError("错误台账单元格回读行号超出请求范围")
                cells = raw_row if isinstance(raw_row, list) else []
                values: list[str] = []
                for column in range(17):
                    cell = (
                        cells[column]
                        if column < len(cells) and isinstance(cells[column], dict)
                        else {}
                    )
                    values.append(str(cell.get("value") or ""))
                rows_by_number[row_number] = values
        header = rows_by_number.get(1, [])
        if tuple(header) != ERROR_LEDGER_COLUMNS:
            raise RuntimeError("错误台账表头被修改，自动写入已停止")
        last_nonempty_row = max(
            (row_number for row_number, values in rows_by_number.items() if any(values)),
            default=1,
        )
        rows: list[list[str]] = []
        row_by_incident: dict[str, int] = {}
        for offset in range(2, last_nonempty_row + 1):
            normalized = rows_by_number.get(offset, [""] * 17)
            rows.append(normalized)
            incident_id = normalized[0].strip()
            if not incident_id:
                continue
            if incident_id in row_by_incident:
                existing_row_number = row_by_incident[incident_id]
                existing_values = rows[existing_row_number - 2]
                existing_handled = bool(existing_values[12].strip()) or existing_values[13] == "已处理"
                current_handled = bool(normalized[12].strip()) or normalized[13] == "已处理"
                # A previous failed append may have left a duplicate row. Keep
                # the human-owned handled row if one exists; otherwise retain
                # the earliest row. Never let a duplicate make all callbacks
                # for that incident unusable.
                if current_handled and not existing_handled:
                    row_by_incident[incident_id] = offset
                continue
            row_by_incident[incident_id] = offset
        return rows, row_by_incident

    def _ledger_notification_status(self, incident: dict[str, Any]) -> str:
        deliveries = incident.get("delivery") if isinstance(incident.get("delivery"), dict) else {}
        routed = [str(item.get("chat_id") or "") for item in self.alert_targets]
        states = [
            str(deliveries[chat_id].get("state") or "")
            for chat_id in routed
            if isinstance(deliveries.get(chat_id), dict)
        ]
        target_count = len(routed)
        verified = sum(1 for state in states if state == "verified")
        if target_count and verified == target_count:
            resolution_states = [
                str((deliveries[chat_id].get("resolution_update") or {}).get("state") or "")
                for chat_id in routed
                if isinstance(deliveries.get(chat_id), dict)
            ]
            if incident.get("status") == "resolved" and resolution_states and all(
                state == "verified" for state in resolution_states
            ):
                return f"原消息已更新为恢复（{verified}/{target_count}）"
            return f"已发送并回读（{verified}/{target_count}）"
        if any(state == "sent_pending_readback" for state in states):
            return "已发送，等待回读"
        if any(state == "failed_before_verification" for state in states):
            return "发送失败，等待本地重试"
        if states and all(state == "suppressed_route_cutover" for state in states):
            return "未发送（路由切换前故障）"
        if not self.notifications_enabled or not incident.get("detected_with_notifications_enabled"):
            return "未发送（影子期）"
        diagnosis = incident.get("diagnosis") if isinstance(incident.get("diagnosis"), dict) else {}
        return "待发送" if diagnosis.get("ok") else "待LLM分析，未发送"

    def _ledger_row_values(self, incident: dict[str, Any], synced_at_hkt: str) -> list[str]:
        diagnosis = incident.get("diagnosis") if isinstance(incident.get("diagnosis"), dict) else {}
        has_diagnosis = bool(diagnosis.get("ok"))
        severity = str(diagnosis.get("severity") or incident.get("severity") or "P2")
        severity_label = SEVERITY_LABELS.get(severity, "高")
        if has_diagnosis:
            severity_reason = str(diagnosis.get("severity_reason") or "")
            fault_cause = str(diagnosis.get("fault_cause") or "")
            fault_impact = str(diagnosis.get("fault_impact") or "")
            fault_time = str(diagnosis.get("fault_time_hkt") or incident.get("occurred_at_hkt") or "")
            solutions = diagnosis.get("recommended_solutions")
            solutions = solutions if isinstance(solutions, list) else []
            needs_human = "是" if diagnosis.get("needs_human") else "否"
            model = str(diagnosis.get("model") or "")
        else:
            shadow = not self.notifications_enabled or not incident.get("detected_with_notifications_enabled")
            suffix = "影子模式不调用 LLM。" if shadow else "等待 LLM 分析。"
            severity_reason = f"规则最低等级：{severity}（{severity_label}）；{suffix}"
            fault_cause = str(incident.get("summary") or incident.get("error") or "待核查")
            fault_impact = str(incident.get("impact") or "待核查")
            fault_time = str(incident.get("occurred_at_hkt") or incident.get("first_seen_at_hkt") or "")
            solutions = incident.get("suggestions")
            solutions = solutions if isinstance(solutions, list) else []
            needs_human = "待LLM判断"
            model = "未调用（影子模式）" if shadow else "等待LLM分析"
        evidence_items: list[str] = []
        for item in [incident.get("error"), *(incident.get("evidence") or [])]:
            text = str(item or "").strip()
            if text and text not in evidence_items:
                evidence_items.append(text)
        solution_text = "\n".join(
            f"{index}. {_solution_text(item, 450)}"
            for index, item in enumerate(solutions[:4], start=1)
            if str(item).strip()
        )
        values = [
            str(incident.get("incident_id") or ""),
            fault_time,
            str(incident.get("first_seen_at_hkt") or ""),
            f"{severity} {severity_label}",
            severity_reason,
            str(incident.get("task_name") or ""),
            str(incident.get("component") or ""),
            fault_cause,
            fault_impact,
            "\n".join(evidence_items),
            solution_text,
            needs_human,
            "",
            "待处理",
            synced_at_hkt,
            model,
            self._ledger_notification_status(incident),
        ]
        return [_to_simplified(_redact(value, 3000)) for value in values]

    def _ledger_content_hash(self, values: list[str]) -> str:
        stable_values = [str(values[index] or "") for index in ERROR_LEDGER_HASH_INDEXES]
        return _fingerprint(json.dumps(stable_values, ensure_ascii=False, separators=(",", ":")))

    def _ledger_severity_style(self, value: str) -> dict[str, str]:
        severity = str(value or "").split(" ", 1)[0]
        palette = {
            "P1": ("#FDECEC", "#B42318"),
            "P2": ("#FFF4E5", "#8A4B08"),
            "P3": ("#EEF4FF", "#2F5AA8"),
        }
        background, foreground = palette.get(severity, ("#F2F4F7", "#344054"))
        return {
            "background_color": background,
            "font_color": foreground,
            "font_weight": "bold",
            "horizontal_alignment": "center",
            "vertical_alignment": "middle",
        }

    def _append_error_ledger_rows(self, rows: list[list[str]]) -> tuple[int, int]:
        config = self._error_ledger_config()
        bot = self.config.get("bot") if isinstance(self.config.get("bot"), dict) else {}
        profile = str(bot.get("profile") or "")
        sheet_name = str(config.get("sheet_name") or "")
        table_payload = {
            "sheets": [
                {
                    "name": sheet_name,
                    "start_cell": "A1",
                    "mode": "append",
                    "header": False,
                    "allow_overwrite": False,
                    "columns": list(ERROR_LEDGER_COLUMNS),
                    "data": rows,
                }
            ]
        }
        payload = self._json_from_process(
            self._run(
                [
                    "lark-cli",
                    "sheets",
                    "+table-put",
                    "--spreadsheet-token",
                    str(config.get("spreadsheet_token") or ""),
                    "--sheets",
                    json.dumps(table_payload, ensure_ascii=False),
                    "--as",
                    "bot",
                    "--profile",
                    profile,
                    "--format",
                    "json",
                ],
                timeout=45,
            )
        )
        data = payload.get("data") if isinstance(payload.get("data"), dict) else {}
        results = data.get("sheets") if isinstance(data.get("sheets"), list) else []
        result = next((item for item in results if str(item.get("name") or "") == sheet_name), None)
        match = re.fullmatch(r"[A-Z]+(\d+):[A-Z]+(\d+)", str((result or {}).get("range") or ""))
        if not match:
            raise RuntimeError("错误台账追加后未返回有效范围")
        start_row, end_row = int(match.group(1)), int(match.group(2))
        if start_row < 2 or end_row - start_row + 1 != len(rows):
            raise RuntimeError(
                f"错误台账追加范围不符合写入行数：expected_rows={len(rows)}; "
                f"actual={start_row}:{end_row}"
            )

        # Append positioning is decided by Feishu at execution time. Another
        # writer (or a trailing formatted row) can move the actual start after
        # our read, so styles must be applied only after the returned range is
        # known. Supplying a precomputed style range to +table-put makes the
        # whole append fail when that range shifts by even one row.
        cell_styles: list[dict[str, Any]] = [
            {
                "range": f"A{start_row}:Q{end_row}",
                "font_size": 12,
                "vertical_alignment": "top",
                "word_wrap": "auto-wrap",
                "border": {"style": "solid", "weight": "thin", "color": "#E4E7EC"},
            }
        ]
        for offset, values in enumerate(rows):
            cell_styles.append(
                {
                    "range": f"D{start_row + offset}",
                    **self._ledger_severity_style(values[3]),
                }
            )
        style_payload = {
            "styles": [
                {
                    "name": sheet_name,
                    "cell_styles": cell_styles,
                    "row_sizes": [
                        {"range": f"{start_row}:{end_row}", "type": "auto"}
                    ],
                }
            ]
        }
        try:
            self._json_from_process(
                self._run(
                    [
                        "lark-cli",
                        "sheets",
                        "+styles-put",
                        "--spreadsheet-token",
                        str(config.get("spreadsheet_token") or ""),
                        "--styles",
                        json.dumps(style_payload, ensure_ascii=False),
                        "--as",
                        "bot",
                        "--profile",
                        profile,
                        "--format",
                        "json",
                    ],
                    timeout=45,
                )
            )
        except Exception as exc:
            # The data append has already committed. Styling is secondary and
            # must never make the incident row unavailable to card callbacks.
            _append_jsonl(
                self.events_path,
                {
                    "type": "error_ledger_style_failed_local_only",
                    "at_hkt": _iso(self.now()),
                    "range": f"A{start_row}:Q{end_row}",
                    "error": _redact(f"{type(exc).__name__}: {exc}", 700),
                },
            )
        return start_row, end_row

    def _update_error_ledger_rows(self, updates: list[tuple[int, list[str]]]) -> None:
        config = self._error_ledger_config()
        bot = self.config.get("bot") if isinstance(self.config.get("bot"), dict) else {}
        profile = str(bot.get("profile") or "")
        sheet_id = str(config.get("sheet_id") or "")
        for start in range(0, len(updates), 50):
            writes: list[dict[str, Any]] = []
            for row_number, values in updates[start : start + 50]:
                left_cells = [{"value": value} for value in values[:12]]
                left_cells[3]["cell_styles"] = self._ledger_severity_style(values[3])
                writes.extend(
                    [
                        {
                            "sheet_id": sheet_id,
                            "range": f"A{row_number}:L{row_number}",
                            "cells": [left_cells],
                        },
                        {
                            "sheet_id": sheet_id,
                            "range": f"O{row_number}:Q{row_number}",
                            "cells": [[{"value": value} for value in values[14:17]]],
                        },
                    ]
                )
            self._json_from_process(
                self._run(
                    [
                        "lark-cli",
                        "sheets",
                        "+cells-set",
                        "--spreadsheet-token",
                        str(config.get("spreadsheet_token") or ""),
                        "--writes",
                        json.dumps(writes, ensure_ascii=False),
                        "--as",
                        "bot",
                        "--profile",
                        profile,
                        "--format",
                        "json",
                    ],
                    timeout=45,
                )
            )

    def _sync_error_ledger(self, *, deadline_monotonic: float | None = None) -> None:
        ledger_state = self.state.setdefault("error_ledger", {})
        if not isinstance(ledger_state.get("rows"), dict):
            ledger_state["rows"] = {}
        ledger_state["enabled"] = self.error_ledger_enabled
        if not self.error_ledger_enabled:
            return
        retry_after = _parse_datetime(ledger_state.get("retry_after_hkt"))
        if retry_after and self.now() < retry_after:
            return
        try:
            if deadline_monotonic is None:
                deadline_monotonic = (
                    time.monotonic() + ERROR_LEDGER_SYNC_BUDGET_SECONDS
                )
            config = self._error_ledger_config()
            ledger_state.update(
                {
                    "sheet_id": config.get("sheet_id"),
                    "sheet_name": config.get("sheet_name"),
                }
            )
            records = [
                item
                for item in (self.state.get("incidents") or {}).values()
                if isinstance(item, dict) and str(item.get("incident_id") or "")
            ]
            records.sort(
                key=lambda item: (
                    SEVERITY_ORDER.get(str(item.get("severity") or "P3"), 9),
                    str(item.get("occurred_at_hkt") or item.get("first_seen_at_hkt") or ""),
                    str(item.get("incident_id") or ""),
                )
            )
            if not records:
                return
            synced_at = _iso(self.now())
            desired = {
                str(record.get("incident_id")): self._ledger_row_values(record, synced_at)
                for record in records
            }
            local_rows = ledger_state.get("rows") if isinstance(ledger_state.get("rows"), dict) else {}
            local_changed = any(
                not isinstance(local_rows.get(incident_id), dict)
                or str(local_rows[incident_id].get("content_hash") or "")
                != self._ledger_content_hash(values)
                for incident_id, values in desired.items()
            )
            if self._ledger_verified_this_process and not local_changed:
                return

            remote_rows, row_by_incident = self._read_error_ledger(
                deadline_monotonic=deadline_monotonic
            )
            missing_ids = [incident_id for incident_id in desired if incident_id not in row_by_incident]
            if self._maybe_rollover_error_ledger(
                used_rows=len(remote_rows) + 1,
                incoming_rows=len(missing_ids),
            ):
                config = self._error_ledger_config()
                ledger_state.update(
                    {
                        "sheet_id": config.get("sheet_id"),
                        "sheet_name": config.get("sheet_name"),
                        "sheet_url": config.get("sheet_url"),
                        "last_rollover_at_hkt": synced_at,
                    }
                )
                remote_rows, row_by_incident = self._read_error_ledger(
                    deadline_monotonic=deadline_monotonic
                )
                missing_ids = [incident_id for incident_id in desired if incident_id not in row_by_incident]
            if missing_ids:
                append_values = [desired[incident_id] for incident_id in missing_ids]
                start_row, end_row = self._append_error_ledger_rows(append_values)
                _append_jsonl(
                    self.events_path,
                    {
                        "type": "error_ledger_rows_appended",
                        "at_hkt": synced_at,
                        "count": len(missing_ids),
                        "range": f"A{start_row}:Q{end_row}",
                    },
                )
                # Re-read instead of assuming contiguous row positions from a
                # stale pre-append snapshot. This also covers another writer
                # appending between our read and write.
                remote_rows, row_by_incident = self._read_error_ledger(
                    deadline_monotonic=deadline_monotonic
                )
                for incident_id in missing_ids:
                    if incident_id not in row_by_incident:
                        raise RuntimeError(f"错误台账追加后未回读到告警ID：{incident_id}")

            updates: list[tuple[int, list[str]]] = []
            for incident_id, values in desired.items():
                row_number = row_by_incident.get(incident_id)
                if not row_number:
                    raise RuntimeError(f"错误台账缺少告警ID回读行：{incident_id}")
                remote_index = row_number - 2
                remote_values = remote_rows[remote_index] if 0 <= remote_index < len(remote_rows) else []
                if self._ledger_content_hash(remote_values) != self._ledger_content_hash(values):
                    updates.append((row_number, values))
            if updates:
                self._update_error_ledger_rows(updates)
                _append_jsonl(
                    self.events_path,
                    {
                        "type": "error_ledger_rows_updated",
                        "at_hkt": synced_at,
                        "count": len(updates),
                    },
                )

            if missing_ids or updates or not self._ledger_verified_this_process:
                verified_rows, verified_mapping = self._read_error_ledger(
                    deadline_monotonic=deadline_monotonic
                )
                for incident_id, values in desired.items():
                    row_number = verified_mapping.get(incident_id)
                    if not row_number:
                        raise RuntimeError(f"错误台账写入后未回读到告警ID：{incident_id}")
                    remote_values = verified_rows[row_number - 2]
                    if self._ledger_content_hash(remote_values) != self._ledger_content_hash(values):
                        raise RuntimeError(f"错误台账写入后内容校验失败：{incident_id}")
                    local_rows[incident_id] = {
                        "row": row_number,
                        "content_hash": self._ledger_content_hash(values),
                        "last_synced_at_hkt": synced_at,
                    }
                ledger_state["rows"] = local_rows
            ledger_state["last_synced_at_hkt"] = synced_at
            ledger_state["synced_incidents"] = len(local_rows)
            ledger_state.pop("last_error", None)
            ledger_state.pop("retry_after_hkt", None)
            self._ledger_verified_this_process = True
        except Exception as exc:
            ledger_state["last_error"] = _redact(f"{type(exc).__name__}: {exc}", 900)
            ledger_state["last_failed_at_hkt"] = _iso(self.now())
            ledger_state["retry_after_hkt"] = _iso(self.now() + timedelta(minutes=5))
            _append_jsonl(
                self.events_path,
                {
                    "type": "error_ledger_sync_failed_local_only",
                    "at_hkt": _iso(self.now()),
                    "error": ledger_state["last_error"],
                },
            )

    def _public_incident(self, record: dict[str, Any]) -> dict[str, Any]:
        diagnosis = record.get("diagnosis") if isinstance(record.get("diagnosis"), dict) else {}
        deliveries = record.get("delivery") if isinstance(record.get("delivery"), dict) else {}
        return {
            "incident_id": record.get("incident_id"),
            "status": record.get("status"),
            "severity": record.get("severity"),
            "severity_label": SEVERITY_LABELS.get(str(record.get("severity") or ""), ""),
            "task_name": record.get("task_name"),
            "component": record.get("component"),
            "summary": record.get("summary"),
            "error": record.get("error"),
            "impact": record.get("impact"),
            "occurred_at_hkt": record.get("occurred_at_hkt"),
            "first_seen_at_hkt": record.get("first_seen_at_hkt"),
            "last_seen_at_hkt": record.get("last_seen_at_hkt"),
            "diagnosis_status": record.get("diagnosis_status") or ("completed" if diagnosis.get("ok") else "pending"),
            "ai_severity": diagnosis.get("severity") if diagnosis.get("ok") else "",
            "ai_fault_cause": diagnosis.get("fault_cause") if diagnosis.get("ok") else "",
            "ai_fault_impact": diagnosis.get("fault_impact") if diagnosis.get("ok") else "",
            "ai_recommended_solutions": (
                diagnosis.get("recommended_solutions") if diagnosis.get("ok") else []
            ),
            "delivery_states": {
                chat_id: str(value.get("state") or "")
                for chat_id, value in deliveries.items()
                if isinstance(value, dict)
            },
        }

    def _write_outputs(self, active_records: list[dict[str, Any]]) -> dict[str, Any]:
        ordered = sorted(
            active_records,
            key=lambda item: (
                SEVERITY_ORDER.get(str(item.get("severity") or "P3"), 9),
                str(item.get("occurred_at_hkt") or ""),
            ),
        )
        status = {
            "ok": not any(item.get("severity") == "P1" for item in ordered),
            "mode": "enabled" if self.notifications_enabled else "shadow_no_send",
            "notifications_enabled": self.notifications_enabled,
            "message_policy": "errors_only_after_ai_update_original_on_resolution",
            "normal_messages_sent": 0,
            "recovery_messages_sent": 0,
            "recovery_messages_updated": int(self.state.get("recovery_messages_updated") or 0),
            "checked_at_hkt": _iso(self.now()),
            "poll_seconds": int(self.config.get("poll_seconds") or 30),
            "bot": {
                "identity": "bot",
                "app_id": (self.config.get("bot") or {}).get("app_id"),
                "expected_name": (self.config.get("bot") or {}).get("expected_name"),
            },
            "targets": [
                {
                    "role": item.get("role"),
                    "chat_id": item.get("chat_id"),
                    "expected_name": item.get("expected_name"),
                    "alert_notify": bool(item.get("alert_notify", True)),
                    "notify_from_hkt": item.get("notify_from_hkt"),
                }
                for item in self.configured_targets
            ],
            "alert_targets": [
                {
                    "role": item.get("role"),
                    "chat_id": item.get("chat_id"),
                    "expected_name": item.get("expected_name"),
                }
                for item in self.alert_targets
            ],
            "alert_routing_policy": str(
                (self.config.get("alert_routing") or {}).get("policy") or "all_targets"
            ),
            "excluded_components": list(self.config.get("excluded_components") or []),
            "error_ledger": {
                "enabled": self.error_ledger_enabled,
                "sheet_id": self._error_ledger_config().get("sheet_id"),
                "sheet_name": self._error_ledger_config().get("sheet_name"),
                "sheet_url": self._error_ledger_config().get("sheet_url")
                or sheet_url(
                    str(self._error_ledger_config().get("spreadsheet_token") or ""),
                    str(self._error_ledger_config().get("sheet_id") or ""),
                ),
                "synced_incidents": int(
                    ((self.state.get("error_ledger") or {}).get("synced_incidents") or 0)
                ),
                "last_synced_at_hkt": (
                    (self.state.get("error_ledger") or {}).get("last_synced_at_hkt")
                ),
                "last_error": (self.state.get("error_ledger") or {}).get("last_error"),
            },
            "active_counts": {
                severity: sum(1 for item in ordered if item.get("severity") == severity)
                for severity in SEVERITY_ORDER
            },
            "active_incidents": [self._public_incident(item) for item in ordered],
        }
        _atomic_json(self.status_path, status)
        lines = [
            "# CMHK主项目监控本地预览",
            "",
            f"- 模式：{'告警已启用' if self.notifications_enabled else '影子监控，不发送'}",
            "- 群消息政策：仅错误；必须先完成一轮AI分析；恢复时原地更新原告警，不另发消息",
            "- 报障目标群："
            + (
                "、".join(
                    str(item.get("expected_name") or item.get("chat_id") or "")
                    for item in status["alert_targets"]
                )
                or "无（当前路由为空，不会发送任何报障）"
            ),
            f"- 检查时间：{status['checked_at_hkt']}",
            f"- 当前错误：P1 {status['active_counts']['P1']} / P2 {status['active_counts']['P2']} / P3 {status['active_counts']['P3']}",
            "- 明确排除：Token Hub",
            "",
        ]
        if not ordered:
            lines.extend(["当前没有检测到主项目错误。此状态不会发送到任何群。", ""])
        for item in ordered:
            lines.extend(
                [
                    f"## {item.get('severity')} {SEVERITY_LABELS.get(str(item.get('severity')), '')} · {item.get('task_name')}",
                    "",
                    f"- 错误：{item.get('error') or item.get('summary')}",
                    f"- 影响：{item.get('impact')}",
                    f"- AI状态：{item.get('diagnosis_status') or '等待发送门闸启用后分析'}",
                    f"- 告警ID：{item.get('incident_id')}",
                    "",
                ]
            )
        self.preview_path.write_text("\n".join(lines), encoding="utf-8")
        return status

    def run_cycle(self) -> dict[str, Any]:
        self.state["cycle_started_at_hkt"] = _iso(self.now())
        self.state["cycle_phase"] = "collecting"
        _atomic_json(self.state_path, self.state)
        enabled = self.notifications_enabled
        last_enabled = bool(self.state.get("notifications_enabled_last"))
        if enabled and not last_enabled:
            self.state["notifications_enabled_since_hkt"] = _iso(self.now())
        self.state["notifications_enabled_last"] = enabled
        issues = self.collect_issues()
        _, active = self._upsert_incidents(issues)
        # Persist local truth before any Feishu/LLM call. A slow external
        # readback must not hide a completed probe pass or leave positively
        # verified historical recoveries looking unresolved until the whole
        # external synchronization phase finishes.
        self.state["last_local_check_at_hkt"] = _iso(self.now())
        self.state["cycle_phase"] = "external_sync"
        self.state["last_issue_count"] = len(active)
        _atomic_json(self.state_path, self.state)
        ledger_deadline_monotonic = (
            time.monotonic() + ERROR_LEDGER_SYNC_BUDGET_SECONDS
        )
        # A card must never be delivered before its incident row exists. The
        # callback can be clicked immediately, so syncing after delivery leaves
        # a race where the click cannot resolve the incident ID.
        self._sync_error_ledger(deadline_monotonic=ledger_deadline_monotonic)
        # The user explicitly requires errors only and AI-before-send. Healthy
        # cycles never send messages; resolved incidents only edit a previously
        # verified shared card in place.
        for incident in active:
            ledger_rows = (self.state.get("error_ledger") or {}).get("rows") or {}
            ledger_row = ledger_rows.get(str(incident.get("incident_id") or ""))
            if self.error_ledger_enabled and not (
                isinstance(ledger_row, dict) and int(ledger_row.get("row") or 0) >= 2
            ):
                incident["delivery_suppressed"] = "awaiting_error_ledger_sync"
                continue
            self._deliver_incident(incident)
        updated = self._update_resolved_deliveries()
        self.state["recovery_messages_updated"] = int(
            self.state.get("recovery_messages_updated") or 0
        ) + updated
        # Sync again so notification status is reflected after successful sends.
        # M/N (处理人员/处理状态) are never touched by this path after append.
        self._sync_error_ledger(deadline_monotonic=ledger_deadline_monotonic)
        self.state["last_cycle_at_hkt"] = _iso(self.now())
        self.state["cycle_phase"] = "idle"
        self.state["cycles"] = int(self.state.get("cycles") or 0) + 1
        self.state["last_issue_count"] = len(active)
        _atomic_json(self.state_path, self.state)
        return self._write_outputs(active)

    def run_daemon(self) -> None:
        interval = max(10, int(self.config.get("poll_seconds") or 30))
        while True:
            started = time.monotonic()
            try:
                status = self.run_cycle()
                print(
                    json.dumps(
                        {
                            "checked_at_hkt": status.get("checked_at_hkt"),
                            "mode": status.get("mode"),
                            "active_counts": status.get("active_counts"),
                        },
                        ensure_ascii=False,
                    ),
                    flush=True,
                )
            except Exception as exc:
                print(f"project monitor cycle failed: {_redact(exc)}", file=sys.stderr, flush=True)
            remaining = interval - (time.monotonic() - started)
            if remaining > 0:
                time.sleep(remaining)

    def acquire_lock(self):
        self.state_dir.mkdir(parents=True, exist_ok=True)
        handle = self.lock_path.open("a+", encoding="utf-8")
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            handle.close()
            raise RuntimeError("another project monitor process is already running")
        handle.seek(0)
        handle.truncate()
        handle.write(str(os.getpid()))
        handle.flush()
        return handle


def main() -> None:
    if hasattr(signal, "SIGUSR1"):
        faulthandler.register(signal.SIGUSR1, all_threads=True)
    parser = argparse.ArgumentParser(description="CMHK主项目错误实时监控（默认禁止群发送）")
    parser.add_argument("--once", action="store_true", help="只执行一次只读检测")
    parser.add_argument("--daemon", action="store_true", help="持续轮询")
    parser.add_argument("--status", action="store_true", help="输出最近一次脱敏状态")
    parser.add_argument("--runtime-root", default="")
    parser.add_argument("--config", default="")
    parser.add_argument("--state-dir", default="")
    args = parser.parse_args()
    monitor = ProjectMonitor(
        runtime_root=args.runtime_root or None,
        config_path=args.config or None,
        state_dir=args.state_dir or None,
    )
    if args.status:
        print(json.dumps(load_public_status(monitor.runtime_root, state_dir=monitor.state_dir), ensure_ascii=False, indent=2))
        return
    lock = monitor.acquire_lock()
    try:
        if args.daemon and not args.once:
            monitor.run_daemon()
        else:
            print(json.dumps(monitor.run_cycle(), ensure_ascii=False, indent=2))
    finally:
        fcntl.flock(lock.fileno(), fcntl.LOCK_UN)
        lock.close()


if __name__ == "__main__":
    main()
