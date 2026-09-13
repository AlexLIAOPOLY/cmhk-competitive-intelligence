"""Automatic report-to-audio handoff shared by CLI and Web generation."""
from pathlib import Path
import json

RESULT_PREFIX = "REPORT_AUDIO_RESULT="


def generate_report_audio(report_path: Path, *, synthesize=None, progress=print) -> dict:
    if synthesize is None:
        from tts_service import synthesize_report_audio
        synthesize = synthesize_report_audio
    progress("[生成语音摘要] 报告文件已生成，开始生成对应语音。", flush=True)
    result = {}
    for attempt in range(2):
        try:
            result = synthesize(report_path, force=False)
            if result.get("ok") and result.get("audio", {}).get("exists"):
                break
            result = {**result, "ok": False, "error": result.get("error") or "未取得可用语音文件"}
        except Exception as exc:
            result = {"ok": False, "error": str(exc)}
        if attempt == 0:
            progress("[语音重试] 音频已保存，继续重试字幕对齐。" if result.get('resumeStage') == 'subtitle_alignment'
                     else "[语音重试] 首次生成未完成，自动重试一次。", flush=True)
    # Keep the machine handoff small: no full transcript in the process stream.
    result = {key: result[key] for key in ("ok", "error", "audio", "backend", "created", "resumeStage") if key in result}
    if isinstance(result.get("audio"), dict):
        result["audio"] = {k: v for k, v in result["audio"].items() if k not in {"summary", "subtitleCues", "spokenText"}}
    result["report_path"] = str(report_path.resolve())
    progress(RESULT_PREFIX + json.dumps(result, ensure_ascii=False), flush=True)
    progress("[语音完成] 对应语音已生成。" if result.get("ok") else "[语音未完成] 报告已保留；" + str(result.get("error")), flush=True)
    return result


def audio_result_from_output(output: str) -> dict | None:
    for line in reversed(output.splitlines()):
        if line.startswith(RESULT_PREFIX):
            result = json.loads(line[len(RESULT_PREFIX):])
            if not isinstance(result, dict):
                raise ValueError("报告语音结果格式不正确")
            return result
    return None
