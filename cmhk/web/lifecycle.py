from __future__ import annotations

# Annotation imports do not create application services or mutable state.
from http.server import BaseHTTPRequestHandler

from ._binding import publish


def bind(app) -> None:
    """Bind this domain to the existing application and its shared state."""
    def write_sse(handler: BaseHTTPRequestHandler, payload: dict) -> bool:
        app.observe_task_progress(handler, payload)
        task_id = str(getattr(handler, "_general_task_run_id", "") or "")
        if task_id and isinstance(payload, dict):
            event_type = str(payload.get("type") or "")
            if event_type == "log" and payload.get("text"):
                app.append_general_task_log(task_id, payload.get("text"))
            elif event_type == "done":
                ok = bool(payload.get("ok", True))
                detail = str(payload.get("error") or payload.get("message") or "")
                app.append_general_task_log(task_id, "任务完成。" if ok else "任务失败：" + (detail or "未提供原因"))
                app.finish_general_task_run(task_id, ok, detail)
                handler._general_task_finished = True
        return app._ORIGINAL_WRITE_SSE(handler, payload)

    publish(app, write_sse)

    def stream_report_generation(handler: BaseHTTPRequestHandler, script_name: str, report_kind: str) -> None:
        if report_kind == "weekly":
            kind = "weekly-report"
            title = "生成周报"
            scope = "战略部每周周报"
        else:
            kind = "carrier-performance"
            title = "生成业绩摘要"
            scope = "运营商业绩摘要"
        task = app.start_general_task_run(kind, title, scope, script_name)
        task_id = str(task["task_id"])
        handler._general_task_run_id = task_id
        handler._general_task_finished = False
        app.start_task_lifecycle_monitor(handler, "general", task_id, "报告生成")
        try:
            result = app._ORIGINAL_STREAM_REPORT_GENERATION(handler, script_name, report_kind)
            if not handler._general_task_finished:
                app.append_general_task_log(task_id, "任务执行结束。")
                app.finish_general_task_run(task_id, True, "")
                handler._general_task_finished = True
            return result
        except Exception as exc:
            app.append_general_task_log(task_id, "任务异常：" + str(exc))
            app.finish_general_task_run(task_id, False, str(exc))
            handler._general_task_finished = True
            raise
        finally:
            app.stop_task_lifecycle_monitor(handler)
            handler._general_task_run_id = ""

    publish(app, stream_report_generation)

