from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import json
import uuid
from urllib.request import urlretrieve
from pathlib import Path
from urllib.parse import quote

from docx import Document
from network_utils import urlopen_with_local_proxy_fallback
from ai_rate_limit import wait_for_internal_ai_slot


ROOT = Path(__file__).resolve().parent
AUDIO_DIR = ROOT / "audio"
TTS_MODEL_DIR = ROOT / "models" / "tts"
WEEKLY_MD = ROOT / "weekly_report.md"
KOKORO_MODEL_URL = "https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/kokoro-v1.0.int8.onnx"
KOKORO_VOICES_URL = "https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/voices-v1.0.bin"
SHERPA_MELO_URL = "https://github.com/k2-fsa/sherpa-onnx/releases/download/tts-models/vits-melo-tts-zh_en.tar.bz2"
SHERPA_MELO_INT8_URL = "https://huggingface.co/csukuangfj/vits-melo-tts-zh_en/resolve/main/model.int8.onnx"
MOSS_TTS_REPO_ID = "OpenMOSS-Team/MOSS-TTS-Nano-100M-ONNX"
MOSS_CODEC_REPO_ID = "OpenMOSS-Team/MOSS-Audio-Tokenizer-Nano-ONNX"
MOSS_VENDOR_DIR = ROOT / "vendor" / "moss_tts_nano"
TTS_VENV_PYTHON = ROOT / ".venv_tts" / "bin" / "python"
MIN_FULL_REPORT_AUDIO_SUMMARY_CHARS = 220
FULL_REPORT_SOURCE_CHARS = 800
REPORT_SECTION_NAMES = (
    "政治资讯",
    "经济资讯",
    "行业资讯",
    "本地运营商资讯",
    "社会资讯",
    "国际资讯",
)


def safe_audio_stem(report_path: Path) -> str:
    stem = re.sub(r"[^0-9A-Za-z\u4e00-\u9fff._ -]+", "", report_path.stem).strip()
    return stem or "weekly_report"


def audio_path_for_report(report_path: Path) -> Path:
    return AUDIO_DIR / f"{safe_audio_stem(report_path)}.wav"


def audio_path_for_report_ext(report_path: Path, suffix: str) -> Path:
    suffix = suffix if suffix.startswith(".") else f".{suffix}"
    return AUDIO_DIR / f"{safe_audio_stem(report_path)}{suffix}"


def audio_paths_for_report(report_path: Path) -> list[Path]:
    return [audio_path_for_report_ext(report_path, ".mp3"), audio_path_for_report_ext(report_path, ".wav")]


def subtitle_timing_path_for_report(report_path: Path) -> Path:
    return audio_path_for_report_ext(report_path, ".timings.json")


def _subtitle_sentences(text: str) -> list[str]:
    sentences = [
        item.strip()
        for item in re.findall(r"[^。！？；\n]+[。！？；\n]*", text or "")
        if item.strip()
    ]
    return sentences or ([text.strip()] if text.strip() else [])


def _subtitle_sentence_weight(text: str) -> float:
    cjk_count = len(re.findall(r"[\u3400-\u9fff]", text))
    latin_words = len(re.findall(r"[A-Za-z]+(?:[-'][A-Za-z]+)*", text))
    digit_count = len(re.findall(r"\d", text))
    comma_pauses = len(re.findall(r"[，,:：、]", text))
    sentence_pauses = len(re.findall(r"[。！？；;]", text))
    return max(1.0, cjk_count + latin_words * 1.8 + digit_count * 1.25 + comma_pauses * 1.2 + sentence_pauses * 2.2)


def _write_moss_subtitle_timings(output_path: Path, result: dict, runtime) -> None:
    text_chunks = [str(item or "").strip() for item in result.get("text_chunks") or []]
    chunk_results = result.get("chunk_results") or []
    sample_rate = int(result.get("sample_rate") or 0)
    if not text_chunks or sample_rate <= 0 or len(text_chunks) != len(chunk_results):
        return

    cues: list[dict] = []
    cursor = 0.0
    for index, (chunk_text, chunk_result) in enumerate(zip(text_chunks, chunk_results, strict=True)):
        waveform = chunk_result.get("waveform")
        sample_count = len(waveform) if waveform is not None else 0
        chunk_duration = sample_count / sample_rate if sample_count > 0 else 0.0
        sentences = _subtitle_sentences(chunk_text)
        weights = [_subtitle_sentence_weight(sentence) for sentence in sentences]
        total_weight = sum(weights) or 1.0
        used_weight = 0.0
        for sentence, weight in zip(sentences, weights, strict=True):
            start = cursor + chunk_duration * used_weight / total_weight
            used_weight += weight
            end = cursor + chunk_duration * used_weight / total_weight
            cues.append(
                {
                    "text": sentence,
                    "start": round(start, 3),
                    "end": round(max(end, start + 0.05), 3),
                }
            )
        cursor += chunk_duration
        if index < len(text_chunks) - 1:
            cursor += float(runtime.estimate_voice_clone_inter_chunk_pause_seconds(chunk_text))

    if not cues:
        return
    final_waveform = result.get("waveform")
    final_duration = len(final_waveform) / sample_rate if final_waveform is not None else cursor
    if cursor > 0 and final_duration > 0:
        scale = final_duration / cursor
        for cue in cues:
            cue["start"] = round(float(cue["start"]) * scale, 3)
            cue["end"] = round(float(cue["end"]) * scale, 3)
        cursor = final_duration
    timing_path = output_path.with_suffix(".timings.json")
    timing_path.write_text(
        json.dumps(
            {
                "version": 1,
                "backend": "moss-tts-nano",
                "duration": round(cursor, 3),
                "spokenText": "".join(text_chunks),
                "cues": cues,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )


def _alignment_char_positions(text: str) -> tuple[str, list[int]]:
    normalized: list[str] = []
    positions: list[int] = []
    for index, character in enumerate(str(text or "")):
        if character.isalnum() or "\u3400" <= character <= "\u9fff":
            normalized.append(character.casefold())
            positions.append(index)
    return "".join(normalized), positions


def _build_asr_subtitle_cues(transcript: str, segments: list[dict]) -> list[dict]:
    transcript = str(transcript or "").strip()
    normalized_transcript, transcript_positions = _alignment_char_positions(transcript)
    if not transcript or not normalized_transcript:
        return []

    aligned_tokens: list[dict] = []
    normalized_cursor = 0
    matched_characters = 0
    for raw_segment in segments or []:
        if not isinstance(raw_segment, dict):
            continue
        token_text = str(raw_segment.get("text") or "")
        normalized_token, _ = _alignment_char_positions(token_text)
        if not normalized_token:
            continue
        try:
            start_time = float(raw_segment.get("start"))
            end_time = float(raw_segment.get("end"))
        except (TypeError, ValueError):
            continue
        if end_time <= start_time:
            continue

        match_start = normalized_transcript.find(normalized_token, normalized_cursor)
        if match_start < 0:
            continue
        match_end = match_start + len(normalized_token)
        if match_end > len(transcript_positions):
            continue
        char_start = transcript_positions[match_start]
        char_end = transcript_positions[match_end - 1] + 1
        aligned_tokens.append(
            {
                "text": transcript[char_start:char_end],
                "start": round(start_time, 3),
                "end": round(end_time, 3),
                "charStart": char_start,
                "charEnd": char_end,
            }
        )
        normalized_cursor = max(normalized_cursor, match_end)
        matched_characters += len(normalized_token)

    coverage = matched_characters / max(1, len(normalized_transcript))
    if not aligned_tokens or coverage < 0.85:
        return []

    sentence_matches = list(re.finditer(r"[^。！？；\n]+[。！？；\n]*", transcript))
    if not sentence_matches:
        sentence_matches = [re.match(r".+", transcript)]

    cues: list[dict] = []
    for sentence_match in sentence_matches:
        if sentence_match is None:
            continue
        sentence_text = sentence_match.group(0).strip()
        if not sentence_text:
            continue
        leading_trim = len(sentence_match.group(0)) - len(sentence_match.group(0).lstrip())
        sentence_start = sentence_match.start() + leading_trim
        sentence_end = sentence_start + len(sentence_text)
        sentence_tokens = [
            token for token in aligned_tokens
            if sentence_start <= int(token["charStart"]) < sentence_end
        ]
        if not sentence_tokens:
            continue
        local_tokens = []
        for token in sentence_tokens:
            local_tokens.append(
                {
                    "text": token["text"],
                    "start": token["start"],
                    "end": token["end"],
                    "charStart": max(0, int(token["charStart"]) - sentence_start),
                    "charEnd": min(len(sentence_text), int(token["charEnd"]) - sentence_start),
                }
            )
        cues.append(
            {
                "text": sentence_text,
                "start": local_tokens[0]["start"],
                "end": local_tokens[-1]["end"],
                "tokens": local_tokens,
            }
        )
    return cues


def _internal_asr_timing_payload(audio_path: Path) -> dict:
    import urllib.error
    import urllib.request

    from ai_config import is_internal_ai_base_url, load_ai_config

    config = load_ai_config(include_key=True)
    base_url = str(config.get("base_url") or "").strip().rstrip("/")
    api_key = str(config.get("api_key") or "").strip()
    if not is_internal_ai_base_url(base_url) or not api_key:
        raise RuntimeError("公司内网语音模型配置不完整")

    boundary = f"----CMHKAudioTiming{uuid.uuid4().hex}"
    line_break = b"\r\n"
    body = bytearray()
    fields = (
        ("model", os.environ.get("INTERNAL_ASR_MODEL", "Qwen3ASR").strip() or "Qwen3ASR"),
        ("language", "zh"),
        ("response_format", "verbose_json"),
        ("timestamp_granularities[]", "word"),
    )
    for name, value in fields:
        body.extend(f"--{boundary}".encode("ascii") + line_break)
        body.extend(f'Content-Disposition: form-data; name="{name}"'.encode("ascii") + line_break + line_break)
        body.extend(str(value).encode("utf-8") + line_break)
    mime_type = "audio/mpeg" if audio_path.suffix.lower() == ".mp3" else "audio/wav"
    body.extend(f"--{boundary}".encode("ascii") + line_break)
    body.extend(
        f'Content-Disposition: form-data; name="file"; filename="{audio_path.name}"'.encode("utf-8")
        + line_break
    )
    body.extend(f"Content-Type: {mime_type}".encode("ascii") + line_break + line_break)
    body.extend(audio_path.read_bytes() + line_break)
    body.extend(f"--{boundary}--".encode("ascii") + line_break)

    request = urllib.request.Request(
        f"{base_url}/audio/transcriptions",
        data=bytes(body),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": f"multipart/form-data; boundary={boundary}",
            "Accept": "application/json",
        },
        method="POST",
    )
    try:
        wait_for_internal_ai_slot("tts-subtitle-alignment")
        with urllib.request.urlopen(request, timeout=180) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="ignore")[:600]
        raise RuntimeError(f"公司内网语音对齐返回 HTTP {exc.code}: {detail}") from exc


def _write_internal_asr_subtitle_timings(output_path: Path) -> dict:
    result = _internal_asr_timing_payload(output_path)
    transcript = str(result.get("text") or result.get("transcript") or "").strip()
    segments = result.get("segments")
    cues = _build_asr_subtitle_cues(transcript, segments if isinstance(segments, list) else [])
    if not transcript or not cues:
        raise RuntimeError("公司内网语音模型未返回可用的逐字时间戳")
    duration = float(result.get("duration") or cues[-1]["end"])
    payload = {
        "version": 2,
        "backend": "internal-qwen3-asr",
        "duration": round(duration, 3),
        "spokenText": transcript,
        "cues": cues,
    }
    output_path.with_suffix(".timings.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return payload


def audio_info_for_report(report_path: Path) -> dict:
    audio_path = next((path for path in audio_paths_for_report(report_path) if path.exists()), None)
    if not audio_path:
        return {"exists": False}
    summary_text = ""
    txt_path = audio_path_for_report_ext(report_path, ".txt")
    if txt_path.exists():
        summary_text = txt_path.read_text(encoding="utf-8", errors="ignore")
    timing_payload = {}
    timing_path = subtitle_timing_path_for_report(report_path)
    if timing_path.exists():
        try:
            timing_payload = json.loads(timing_path.read_text(encoding="utf-8"))
        except Exception:
            timing_payload = {}
    result = {
        "exists": True,
        "name": audio_path.name,
        "url": f"/audio/{quote(audio_path.name)}",
        "size": audio_path.stat().st_size,
        "mtime": audio_path.stat().st_mtime,
        "mtimeText": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(audio_path.stat().st_mtime)),
        "summary": summary_text,
    }
    cues = timing_payload.get("cues")
    if isinstance(cues, list) and cues:
        result["subtitleCues"] = cues
        result["spokenText"] = str(timing_payload.get("spokenText") or summary_text)
    return result


def delete_audio_for_report(report_path: Path) -> None:
    for path in audio_paths_for_report(report_path) + [
        audio_path_for_report_ext(report_path, ".txt"),
        subtitle_timing_path_for_report(report_path),
    ]:
        if path.exists():
            path.unlink()


def rename_audio_for_report(old_report_path: Path, new_report_path: Path) -> None:
    AUDIO_DIR.mkdir(exist_ok=True)
    for old_audio in audio_paths_for_report(old_report_path) + [
        audio_path_for_report_ext(old_report_path, ".txt"),
        subtitle_timing_path_for_report(old_report_path),
    ]:
        if not old_audio.exists():
            continue
        new_audio = audio_path_for_report_ext(new_report_path, old_audio.suffix)
        if new_audio.exists() and new_audio != old_audio:
            new_audio.unlink()
        old_audio.rename(new_audio)


def _read_docx_text(path: Path) -> str:
    try:
        doc = Document(str(path))
    except Exception:
        return ""
    return "\n".join(p.text.strip() for p in doc.paragraphs if p.text.strip())


def _source_text(report_path: Path) -> str:
    docx_text = _read_docx_text(report_path)
    if docx_text.strip():
        return docx_text
    if WEEKLY_MD.exists():
        text = WEEKLY_MD.read_text(encoding="utf-8", errors="ignore")
        if text.strip():
            return text
    return ""


def normalize_for_speech(value: str) -> str:
    text = re.sub(r"\s+", " ", value).strip()
    replacements = {
        "PCPD/AI": "私隐专员公署人工智能",
        "GDPR/DSA": "欧盟通用数据保护条例和数字服务法",
        "OFCA": "通讯事务管理局办公室",
        "ARPU": "每用户平均收入",
        "EBITDA": "息税折旧及摊销前利润",
        "AI": "人工智能",
        "HKT": "香港电讯",
        "csl": "C S L",
        "1O1O": "一 O 一 O",
        "EU": "欧盟",
        "Data Act": "数据法案",
        "Airtel": "艾尔特尔",
        "Vodafone": "沃达丰",
        "AT&T": "A T and T",
    }
    for source, target in replacements.items():
        text = text.replace(source, target)
    for source, target in {
        "SmarTone": "数码通",
        "3HK": "Three香港",
        "HKBN": "香港宽频",
        "MoU": "合作备忘录",
    }.items():
        text = text.replace(source, target)
    text = re.sub(r"(?<!\d)5G-Advanced(?![A-Za-z])", "五G增强版", text, flags=re.IGNORECASE)
    text = re.sub(r"(?<!\d)5G-A(?![A-Za-z])", "五G增强版", text, flags=re.IGNORECASE)
    text = re.sub(r"(?<!\d)5G(?![A-Za-z])", "五 G", text, flags=re.IGNORECASE)
    text = text.replace("/", "和")
    text = text.replace("&", "和")
    text = text.replace("欧盟 数据法案", "欧盟数据法案")
    text = re.sub(r"发布(.+?)相关政策信息", r"更新了\1信息", text)
    text = re.sub(r"发布(.+?)相关信息", r"更新了\1信息", text)
    text = re.sub(r"\([^)]*\)", "", text)
    text = re.sub(r"（[^）]*）", "", text)
    text = re.sub(r"\s+", " ", text)
    text = re.sub(r"五\s*G(?:-Advanced|-A)", "五G增强版", text, flags=re.IGNORECASE)
    text = re.sub(r"五\s*G", "五G", text, flags=re.IGNORECASE)
    text = text.replace("；；", "；").replace("。。", "。")
    return text.strip(" ，。；")


def _generate_audio_summary_with_llm(text: str, report_kind: str = "weekly") -> str | None:
    from ai_config import INTERNAL_AI_BASE_URL, load_ai_config
    import urllib.request
    import json
    import os

    config = load_ai_config(include_key=True)
    api_key = str(config.get("api_key") or "").strip()
    if not api_key:
        return None

    provider = str(config.get("provider") or "deepseek").lower()
    model = str(config.get("model") or "deepseek-v4")
    base_url = str(config.get("base_url") or INTERNAL_AI_BASE_URL).rstrip("/")

    if report_kind == "carrier-performance":
        report_instruction = (
            "根据运营商业绩摘要全文撰写管理层语音摘要，控制在320至450个汉字。"
            "依次概括香港主要竞对、内地运营商、资本开支与股东回报、关键风险和观察重点。"
        )
        report_label = "运营商业绩摘要"
    else:
        report_instruction = (
            "根据战略双周报全文撰写管理层语音摘要，控制在300至420个汉字。"
            "按报告实际存在的栏目概括政策、经济、行业、本地运营商、社会或国际重点，不能遗漏全部正文栏目。"
        )
        report_label = "战略双周报"
    system_prompt = (
        "你是中国移动战略部门的资深分析师和正式播音员。"
        + report_instruction
        + "要求结论先行、事实准确、语气正式克制，保留重要公司、数字和业务变化，不得编造；"
        "不得使用脱口秀、夸张、网络流行语、闲聊、寒暄或主观揣测。"
        "直接输出可播报正文，不要标题、项目符号或解释。"
    )
    user_prompt = f"{report_label}全文如下：\n{text[:12000]}"

    if provider == "openai":
        body = {"model": model, "instructions": system_prompt, "input": user_prompt}
        url = f"{base_url}/responses"
    else:
        body = {
            "model": model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": 0.2,
        }
        url = f"{base_url}/chat/completions"
    body.update(config.get("extra_parameters") or {})

    req = urllib.request.Request(
        url,
        data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        method="POST",
    )
    try:
        wait_for_internal_ai_slot("tts-summary")
        with urlopen_with_local_proxy_fallback(req, timeout=25) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
            if provider == "openai":
                output_parts = []
                if isinstance(payload.get("output_text"), str):
                    output_parts.append(payload["output_text"])
                for output in payload.get("output") or []:
                    for content in output.get("content") or []:
                        if isinstance(content.get("text"), str):
                            output_parts.append(content["text"])
                return "\n".join(output_parts).strip()
            else:
                choices = payload.get("choices") or []
                if choices:
                    return ((choices[0].get("message") or {}).get("content") or "").strip()
    except Exception:
        pass
    return None


def _truncate_audio_summary(text: str, max_chars: int) -> str:
    value = normalize_for_speech(text)
    if len(value) <= max_chars:
        return value if value.endswith(("。", "！", "？")) else value + "。"
    complete = ""
    for sentence in re.findall(r"[^。！？]+[。！？]", value):
        if len(complete) + len(sentence) > max_chars:
            break
        complete += sentence
    if complete:
        return complete
    return value[: max_chars - 1].rstrip("，。；,. ") + "。"


def _condense_report_detail(text: str, max_chars: int = 90) -> str:
    value = normalize_for_speech(text)
    first_sentence = re.split(r"(?<=[。！？])", value, maxsplit=1)[0].strip()
    candidate = first_sentence or value
    if len(candidate) <= max_chars:
        return candidate.rstrip("。")
    clauses = re.split(r"(?<=[，；])", candidate)
    complete = ""
    for clause in clauses:
        if len(complete) + len(clause) > max_chars:
            break
        complete += clause
    return (complete or candidate[:max_chars]).rstrip("，。；,. ")


def _weekly_fallback_summary(lines: list[str], max_chars: int) -> str:
    body_items: dict[str, list[tuple[str, str]]] = {name: [] for name in REPORT_SECTION_NAMES}
    current_section = ""
    candidate_title = ""
    numbered_title_pending = False
    for line in lines:
        if line in REPORT_SECTION_NAMES:
            current_section = line
            candidate_title = ""
            numbered_title_pending = False
            continue
        if not current_section or line.startswith("发布时间：") or line.startswith("来源："):
            continue
        if line.startswith("【") and line.endswith("】"):
            continue
        numbered_match = re.match(r"^[一二三四五六七八九十百]+、(.+)$", line)
        if numbered_match:
            candidate_title = numbered_match.group(1).strip()
            numbered_title_pending = True
            continue
        if numbered_title_pending and candidate_title:
            body_items[current_section].append((candidate_title, line))
            candidate_title = ""
            numbered_title_pending = False
            continue
        if len(line) >= 80 and candidate_title:
            body_items[current_section].append((candidate_title, line))
            candidate_title = ""
            continue
        if len(line) <= 100 and "（本期暂无更新）" not in line:
            candidate_title = re.sub(r"^[一二三四五六七八九十百]+、", "", line).strip()

    limits = {
        "政治资讯": 2,
        "经济资讯": 2,
        "行业资讯": 3,
        "本地运营商资讯": 3,
        "社会资讯": 2,
        "国际资讯": 2,
    }
    summary_parts = ["本期双周报重点如下。"]
    for section_name in REPORT_SECTION_NAMES:
        items = body_items[section_name][: limits[section_name]]
        if not items:
            continue
        cleaned_items = []
        for title, detail in items:
            spoken_title = normalize_for_speech(title).rstrip("。")
            detail_excerpt = _condense_report_detail(detail, 82)
            cleaned_items.append(f"{spoken_title}，{detail_excerpt}".rstrip("，。"))
        summary_parts.append(f"{section_name}方面，" + "；".join(cleaned_items) + "。")
    if len(summary_parts) == 1:
        return ""
    summary_parts.append("综合来看，应持续跟进上述政策与行业变化、相关主体后续披露及其对市场竞争和业务部署的影响。")
    return _truncate_audio_summary("".join(summary_parts), min(max_chars, 760))


def _carrier_performance_fallback_summary(lines: list[str], max_chars: int) -> str:
    companies: list[tuple[str, dict[str, str]]] = []
    current_company = ""
    current_fields: dict[str, str] = {}
    for line in lines:
        if line.endswith("关键摘要") and "运营商及香港主要竞对" not in line:
            if current_company and current_fields:
                companies.append((current_company, current_fields))
            current_company = re.split(r"[（(]", line, maxsplit=1)[0].strip()
            current_fields = {}
            continue
        match = re.match(r"^\d+[.、]\s*(派息|资本开支|战略升级|券商观点|市场反应)：(.+)$", line)
        if current_company and match:
            current_fields[match.group(1)] = match.group(2).strip()
    if current_company and current_fields:
        companies.append((current_company, current_fields))
    if not companies:
        return ""

    summary_parts = ["本期运营商业绩摘要重点如下。"]
    for company, fields in companies:
        preferred = fields.get("战略升级") or fields.get("市场反应") or fields.get("资本开支")
        secondary = fields.get("派息") or fields.get("资本开支")
        clauses = [_condense_report_detail(preferred, 48)] if preferred else []
        if len(companies) <= 6 and secondary and secondary != preferred:
            clauses.append(_condense_report_detail(secondary, 36))
        if clauses:
            summary_parts.append(f"{company}方面，" + "；".join(clauses) + "。")
    summary_parts.append("综合来看，应继续关注各运营商资本开支效率、股东回报、传统业务压力及人工智能和算力转型的兑现进度。")
    return _truncate_audio_summary("".join(summary_parts), min(max_chars, 680))


def _generic_fallback_summary(lines: list[str], max_chars: int) -> str:
    useful = []
    for line in lines:
        if line.startswith(("发布时间：", "来源：", "中国移动香港公司")):
            continue
        if line in {"目 录", "目录"} or (line.startswith("【") and line.endswith("】")):
            continue
        if len(line) >= 35:
            useful.append(_condense_report_detail(line, 110))
        if len("".join(useful)) >= 360:
            break
    if not useful:
        return ""
    return _truncate_audio_summary("本期报告重点如下。" + "。".join(useful) + "。", min(max_chars, 620))


def build_audio_summary(report_path: Path, max_chars: int = 1100) -> str:
    text = _source_text(report_path)
    report_kind = (
        "carrier-performance"
        if "业绩摘要" in report_path.name or "运营商及香港主要竞对关键业绩摘要" in text
        else "weekly"
    )

    llm_summary = _generate_audio_summary_with_llm(text, report_kind=report_kind)
    if llm_summary:
        summary = normalize_for_speech(llm_summary)
        summary = re.sub(r"^(音频|语音)?摘要?已生成[，。,. ]*", "", summary)
        summary = re.sub(r"^本期战略竞对检测周报已生成[，。,. ]*", "", summary)
        if len(summary) < MIN_FULL_REPORT_AUDIO_SUMMARY_CHARS or "相关动态更新" in summary:
            summary = ""
        elif len(summary) > max_chars:
            summary = _truncate_audio_summary(summary, max_chars)
        elif summary and not summary.endswith(("。", "！", "？")):
            summary += "。"
        if summary:
            return summary

    lines = [re.sub(r"\s+", " ", line).strip() for line in text.splitlines()]
    lines = [line for line in lines if line]
    if not lines:
        return "本期暂无可提取的重点内容，请打开 Word 文件查看详细内容。"

    if report_kind == "carrier-performance":
        summary = _carrier_performance_fallback_summary(lines, max_chars)
    else:
        summary = _weekly_fallback_summary(lines, max_chars)
    if len(summary) < MIN_FULL_REPORT_AUDIO_SUMMARY_CHARS and len(text) >= FULL_REPORT_SOURCE_CHARS:
        summary = _generic_fallback_summary(lines, max_chars)
    if len(summary) < MIN_FULL_REPORT_AUDIO_SUMMARY_CHARS and len(text) >= FULL_REPORT_SOURCE_CHARS:
        raise RuntimeError(
            f"报告正文有{len(text)}字，但语音摘要仅{len(summary)}字，已阻止生成过短音频。"
        )
    return summary


def _ensure_moss_files() -> Path | None:
    base = Path(os.environ.get("MOSS_TTS_MODEL_DIR") or TTS_MODEL_DIR / "moss")
    tts_dir = base / "MOSS-TTS-Nano-100M-ONNX"
    codec_dir = base / "MOSS-Audio-Tokenizer-Nano-ONNX"
    if (tts_dir / "browser_poc_manifest.json").exists() and (codec_dir / "codec_browser_onnx_meta.json").exists():
        return base

    if os.environ.get("TTS_AUTO_DOWNLOAD", "1").strip().lower() not in {"1", "true", "yes"}:
        return None

    try:
        from huggingface_hub import snapshot_download
    except Exception:
        return None

    base.mkdir(parents=True, exist_ok=True)
    snapshot_download(
        repo_id=os.environ.get("MOSS_TTS_REPO_ID", MOSS_TTS_REPO_ID),
        local_dir=tts_dir,
    )
    snapshot_download(
        repo_id=os.environ.get("MOSS_CODEC_REPO_ID", MOSS_CODEC_REPO_ID),
        local_dir=codec_dir,
    )
    return base if (tts_dir / "browser_poc_manifest.json").exists() and (codec_dir / "codec_browser_onnx_meta.json").exists() else None


def _synthesize_with_moss(text: str, output_path: Path) -> str | None:
    base = _ensure_moss_files()
    if not base:
        return None

    if str(MOSS_VENDOR_DIR) not in sys.path:
        sys.path.insert(0, str(MOSS_VENDOR_DIR))

    try:
        from onnx_tts_runtime import OnnxTtsRuntime
    except Exception:
        current_python = Path(sys.executable).absolute()
        venv_python = TTS_VENV_PYTHON.absolute() if TTS_VENV_PYTHON.exists() else None
        if (
            os.environ.get("MOSS_TTS_DELEGATED") != "1"
            and venv_python
            and current_python != venv_python
        ):
            env = os.environ.copy()
            env["MOSS_TTS_DELEGATED"] = "1"
            code = (
                "import json,sys;"
                "from pathlib import Path;"
                "from tts_service import _synthesize_with_moss;"
                "used=_synthesize_with_moss(sys.argv[1],Path(sys.argv[2]));"
                "print(json.dumps({'backend':used},ensure_ascii=False))"
            )
            proc = subprocess.run(
                [str(venv_python), "-c", code, text, str(output_path)],
                cwd=str(ROOT),
                env=env,
                text=True,
                capture_output=True,
                timeout=600,
            )
            if proc.returncode == 0 and output_path.exists():
                try:
                    payload = json.loads(proc.stdout.strip().splitlines()[-1])
                    return str(payload.get("backend") or "moss-tts-nano")
                except Exception:
                    return "moss-tts-nano"
        return None

    max_new_frames = int(os.environ.get("MOSS_TTS_MAX_NEW_FRAMES", "640"))
    max_text_tokens = int(os.environ.get("MOSS_TTS_MAX_TEXT_TOKENS", "90"))
    seed = int(os.environ.get("MOSS_TTS_SEED", "20260529"))
    runtime = OnnxTtsRuntime(
        model_dir=str(base),
        thread_count=int(os.environ.get("MOSS_TTS_THREADS", "4")),
        max_new_frames=max_new_frames,
        do_sample=os.environ.get("MOSS_TTS_DO_SAMPLE", "1").strip().lower() not in {"0", "false", "no"},
        sample_mode=os.environ.get("MOSS_TTS_SAMPLE_MODE", "fixed"),
        execution_provider=os.environ.get("MOSS_TTS_EXECUTION_PROVIDER", "cpu"),
    )
    generation_defaults = runtime.manifest["generation_defaults"]
    generation_defaults["text_temperature"] = float(os.environ.get("MOSS_TTS_TEXT_TEMPERATURE", "1.0"))
    generation_defaults["text_top_p"] = float(os.environ.get("MOSS_TTS_TEXT_TOP_P", "1.0"))
    generation_defaults["text_top_k"] = int(os.environ.get("MOSS_TTS_TEXT_TOP_K", "50"))
    generation_defaults["audio_temperature"] = float(os.environ.get("MOSS_TTS_AUDIO_TEMPERATURE", "0.8"))
    generation_defaults["audio_top_p"] = float(os.environ.get("MOSS_TTS_AUDIO_TOP_P", "0.95"))
    generation_defaults["audio_top_k"] = int(os.environ.get("MOSS_TTS_AUDIO_TOP_K", "25"))
    generation_defaults["audio_repetition_penalty"] = float(os.environ.get("MOSS_TTS_AUDIO_REPETITION_PENALTY", "1.2"))

    voice = os.environ.get("MOSS_TTS_VOICE", "Junhao")
    result = runtime.synthesize(
        text=text,
        voice=voice,
        prompt_audio_path=os.environ.get("MOSS_TTS_PROMPT_AUDIO_PATH") or None,
        output_audio_path=str(output_path),
        sample_mode=os.environ.get("MOSS_TTS_SAMPLE_MODE", "fixed"),
        do_sample=os.environ.get("MOSS_TTS_DO_SAMPLE", "1").strip().lower() not in {"0", "false", "no"},
        streaming=os.environ.get("MOSS_TTS_STREAMING", "0").strip().lower() not in {"0", "false", "no"},
        max_new_frames=max_new_frames,
        voice_clone_max_text_tokens=max_text_tokens,
        enable_wetext=False,
        enable_normalize_tts_text=True,
        seed=seed,
    )
    chunk_results = result.get("chunk_results") or []
    frame_counts = [len(chunk.get("generated_frames") or []) for chunk in chunk_results]
    if not frame_counts:
        raise RuntimeError("MOSS-TTS 未生成任何有效音频分段")
    truncated = [
        index + 1
        for index, frame_count in enumerate(frame_counts)
        if frame_count >= max_new_frames - 1
    ]
    if truncated:
        output_path.unlink(missing_ok=True)
        raise RuntimeError(f"MOSS-TTS 分段疑似被截断：{truncated}")
    _write_moss_subtitle_timings(output_path, result, runtime)
    return f"moss-tts-nano:{voice}:seed-{seed}:chunks-{len(frame_counts)}"


def _percentage_number_to_chinese(value: str) -> str:
    sign = ""
    number = value.replace(",", "")
    if number.startswith(("+", "-")):
        sign = "正" if number[0] == "+" else "负"
        number = number[1:]
    integer_text, dot, decimal_text = number.partition(".")
    integer = int(integer_text or "0")
    integer_spoken = _integer_to_chinese(integer)
    digits = "零一二三四五六七八九"
    if dot:
        return f"{sign}{integer_spoken}点{''.join(digits[int(char)] for char in decimal_text)}"
    return f"{sign}{integer_spoken}"


def _integer_to_chinese(n: int) -> str:
    """Convert an integer to its spoken Chinese form."""
    if n == 0:
        return "零"
    digits = "零一二三四五六七八九"
    
    def _section(num: int) -> str:
        if num == 0:
            return ""
        units = ["", "十", "百", "千"]
        parts: list[str] = []
        zero_pending = False
        for pos in range(len(str(num)) - 1, -1, -1):
            divisor = 10 ** pos
            digit = num // divisor % 10
            if digit == 0:
                if parts and num % divisor:
                    zero_pending = True
                continue
            if zero_pending:
                parts.append("零")
                zero_pending = False
            if digit == 2 and pos == 3 and not parts:
                parts.append("两")
            elif digit == 1 and pos == 1 and not parts:
                pass
            else:
                parts.append(digits[digit])
            parts.append(units[pos])
        return "".join(parts)

    if n < 10_000:
        return _section(n)
    if n < 100_000_000:
        wan = n // 10_000
        rest = n % 10_000
        wan_str = "两" if wan == 2 else _section(wan)
        result = wan_str + "万"
        if rest == 0:
            return result
        if rest < 1000:
            result += "零"
        result += _section(rest)
        return result
    yi = n // 100_000_000
    rest = n % 100_000_000
    yi_str = "两" if yi == 2 else _section(yi)
    result = yi_str + "亿"
    if rest == 0:
        return result
    wan = rest // 10_000
    remainder = rest % 10_000
    if wan:
        if rest < 10_000_000:
            result += "零"
        wan_str = "两" if wan == 2 else _section(wan)
        result += wan_str + "万"
    if remainder:
        if rest % 10_000 < 1000:
            result += "零"
        result += _section(remainder)
    return result


def prepare_tts_text(value: str) -> str:
    # Remove markdown bold/heading/code symbols
    text = re.sub(r"[*#`]+", "", value)
    spoken_terms = [
        (r"五\s*G-Advanced", "五G增强版"),
        (r"五\s*G-A", "五G增强版"),
        (r"五\s*G", "五G"),
        (r"(?<!\d)5G-Advanced(?![A-Za-z])", "五G增强版"),
        (r"(?<!\d)5G-A(?![A-Za-z])", "五G增强版"),
        (r"(?<!\d)5G(?![A-Za-z])", "五G"),
        (r"3HK", "Three香港"),
        (r"SmarTone", "数码通"),
        (r"HKBN", "香港宽频"),
        (r"HKT", "香港电讯"),
        (r"Hutchison", "和记电讯"),
        (r"i-CABLE", "有线宽频"),
        (r"MoU", "合作备忘录"),
        (r"EBITDA", "息税折旧及摊销前利润"),
        (r"ARPU", "每用户平均收入"),
    ]
    for pattern, replacement in spoken_terms:
        text = re.sub(pattern, replacement, text, flags=re.IGNORECASE)
    text = text.replace("：", "，").replace("；", "。").replace("、", "，")
    
    # 1. Convert time format (e.g. 17:30 -> 十七时三十分)
    text = re.sub(
        r"(\d{1,2}):(\d{2})", 
        lambda m: f"{_integer_to_chinese(int(m.group(1)))}时{_integer_to_chinese(int(m.group(2)))}分", 
        text
    )
    
    # 2. Keep the percentage operator in front of the complete number. 
    # Leaving "%" after a decimal such as "8点3%" can be spoken as "八点百分之三".
    text = re.sub(
        r"(?<![\d.])([+-]?\d[\d,]*(?:\.\d+)?)\s*[%％]",
        lambda match: "百分之" + _percentage_number_to_chinese(match.group(1)),
        text,
    )
    
    # 3. Convert years (e.g. 2024年 -> 二零二四年)
    def _year_replacer(match: re.Match) -> str:
        digits_map = "零一二三四五六七八九"
        return "".join(digits_map[int(d)] for d in match.group(1)) + "年"
    text = re.sub(r"(\d{4})年", _year_replacer, text)
    
    # 4. Convert general standalone numbers (e.g. "166" -> "一百六十六", "3.5" -> "三点五")
    # Only convert pure integer/float tokens not already part of an English word/ID.
    def _num_replacer(match: re.Match) -> str:
        num_str = match.group(1).replace(",", "")
        sign = ""
        if num_str.startswith(("+", "-")):
            sign = "正" if num_str[0] == "+" else "负"
            num_str = num_str[1:]
        
        if "." in num_str:
            integer_part, _, decimal_part = num_str.partition(".")
            int_spoken = _integer_to_chinese(int(integer_part)) if integer_part else "零"
            digits_map = "零一二三四五六七八九"
            dec_spoken = "".join(digits_map[int(d)] for d in decimal_part)
            return f"{sign}{int_spoken}点{dec_spoken}"
        else:
            return f"{sign}{_integer_to_chinese(int(num_str))}"

    text = re.sub(r"(?<![a-zA-Z0-9.\-_])([+-]?\d[\d,]*(?:\.\d+)?)(?![a-zA-Z0-9.\-_])", _num_replacer, text)
    
    # 5. Fallback for any missed decimals or commas
    text = re.sub(r"(?<=\d)\.(?=\d)", "点", text)
    text = re.sub(r"(?<=\d),(?=\d{3}(?:\D|$))", "", text)
    
    text = re.sub(r"\s+", " ", text)
    return text.strip()



def _ensure_kokoro_files() -> tuple[Path, Path] | None:
    model = Path(os.environ.get("KOKORO_MODEL_PATH") or TTS_MODEL_DIR / "kokoro-v1.0.int8.onnx")
    voices = Path(os.environ.get("KOKORO_VOICES_PATH") or TTS_MODEL_DIR / "voices-v1.0.bin")
    if model.exists() and voices.exists():
        return model, voices

    if os.environ.get("TTS_AUTO_DOWNLOAD", "1").strip().lower() not in {"1", "true", "yes"}:
        return None

    TTS_MODEL_DIR.mkdir(parents=True, exist_ok=True)
    if not model.exists():
        urlretrieve(os.environ.get("KOKORO_MODEL_URL", KOKORO_MODEL_URL), model)
    if not voices.exists():
        urlretrieve(os.environ.get("KOKORO_VOICES_URL", KOKORO_VOICES_URL), voices)
    return model, voices


def _synthesize_with_kokoro(text: str, output_path: Path) -> str | None:
    try:
        from kokoro_onnx import Kokoro
        import soundfile as sf
    except Exception:
        return None

    paths = _ensure_kokoro_files()
    if not paths:
        return None
    model_path, voices_path = paths
    kokoro = Kokoro(str(model_path), str(voices_path))
    voice = os.environ.get("KOKORO_VOICE", "zf_xiaoxiao")
    if voice not in kokoro.get_voices():
        voice = "zf_xiaobei" if "zf_xiaobei" in kokoro.get_voices() else kokoro.get_voices()[0]
    speed = float(os.environ.get("KOKORO_SPEED", "0.92"))
    lang = os.environ.get("KOKORO_LANG", "cmn")
    audio, sample_rate = kokoro.create(text, voice=voice, speed=speed, lang=lang)
    sf.write(str(output_path), audio, sample_rate)
    return f"kokoro-onnx:{voice}"


def _internal_tts_acoustic_profile(audio_path: Path, ffmpeg: str) -> tuple[float, float | None]:
    """Return decoded duration and a robust median pitch estimate."""
    decoded = subprocess.run(
        [ffmpeg, "-v", "error", "-i", str(audio_path), "-ac", "1", "-ar", "16000", "-f", "f32le", "-"],
        check=True,
        capture_output=True,
        timeout=240,
    ).stdout
    duration = len(decoded) / 4 / 16000
    try:
        import numpy as np
    except Exception:
        return duration, None

    samples = np.frombuffer(decoded, dtype="<f4").astype(np.float64)
    frame_size = 400
    if samples.size < frame_size:
        return duration, None
    window = np.hanning(frame_size)
    pitches: list[float] = []
    min_lag = int(16000 / 350)
    max_lag = int(16000 / 70)
    for start in range(0, samples.size - frame_size, 1600):
        frame = samples[start : start + frame_size]
        if float(np.sqrt(np.mean(frame * frame) + 1e-12)) <= 0.01:
            continue
        frame = frame * window
        correlation = np.correlate(frame, frame, mode="full")[frame_size - 1 :]
        lag = min_lag + int(np.argmax(correlation[min_lag : max_lag + 1]))
        if correlation[lag] > 0.25 * correlation[0]:
            pitches.append(16000 / lag)
    return duration, float(np.median(pitches)) if pitches else None


def _internal_tts_consistency_filter(text: str, audio_path: Path, ffmpeg: str) -> str:
    duration, median_pitch = _internal_tts_acoustic_profile(audio_path, ffmpeg)
    target_rate = max(1.0, float(os.environ.get("INTERNAL_TTS_TARGET_UNITS_PER_SECOND", "4.15")))
    target_duration = _subtitle_sentence_weight(text) / target_rate
    tempo = duration / max(target_duration, 1.0)
    tempo = max(0.75, min(1.40, tempo))

    target_pitch = max(100.0, float(os.environ.get("INTERNAL_TTS_TARGET_PITCH_HZ", "225")))
    pitch = target_pitch / median_pitch if median_pitch else 1.0
    pitch = max(0.80, min(1.20, pitch))

    filters = subprocess.run(
        [ffmpeg, "-hide_banner", "-filters"],
        check=False,
        capture_output=True,
        timeout=20,
    ).stdout.decode("utf-8", errors="ignore")
    if "rubberband" in filters:
        return f"rubberband=tempo={tempo:.5f}:pitch={pitch:.5f},loudnorm=I=-16:LRA=5:TP=-1.5"
    return f"atempo={tempo:.5f},loudnorm=I=-16:LRA=5:TP=-1.5"


def _synthesize_with_internal_tts(text: str, output_path: Path) -> str | None:
    import urllib.error
    import urllib.request

    from ai_config import is_internal_ai_base_url, load_ai_config

    config = load_ai_config(include_key=True)
    base_url = str(config.get("base_url") or "").rstrip("/")
    api_key = str(config.get("api_key") or "").strip()
    if not is_internal_ai_base_url(base_url):
        raise RuntimeError("TTS 只允许使用公司内网模型服务")
    if not api_key:
        raise RuntimeError("公司内网 TTS 未配置 API Key")

    model = os.environ.get("INTERNAL_TTS_MODEL", "Qwen3TTS").strip() or "Qwen3TTS"
    voice = os.environ.get("INTERNAL_TTS_VOICE", "vivian").strip() or "vivian"
    language = os.environ.get("INTERNAL_TTS_LANGUAGE", "Chinese").strip() or "Chinese"
    instruct = os.environ.get(
        "INTERNAL_TTS_INSTRUCT",
        "使用稳定一致、正式克制的企业新闻播报风格；语速自然适中、清晰利落且恒定，句间停顿简短均匀，音调平稳，不随内容改变情绪或声线。",
    ).strip()
    # Generated summaries are capped below this value, so normal reports stay
    # in one request and retain one continuous voice/prosody conditioning pass.
    max_chars = max(120, int(os.environ.get("INTERNAL_TTS_CHUNK_CHARS", "1200")))
    sentences = [part.strip() for part in re.split(r"(?<=[。！？；!?;])", text) if part.strip()]
    chunks: list[str] = []
    current = ""
    for sentence in sentences or [text]:
        if current and len(current) + len(sentence) > max_chars:
            chunks.append(current)
            current = sentence
        else:
            current += sentence
    if current:
        chunks.append(current)

    with tempfile.TemporaryDirectory(prefix="cmhk_internal_tts_") as tmp_dir:
        tmp = Path(tmp_dir)
        parts: list[Path] = []
        for index, chunk in enumerate(chunks, 1):
            body = {
                "model": model,
                "input": chunk,
                "voice": voice,
                "response_format": "mp3",
                "speed": float(os.environ.get("INTERNAL_TTS_SPEED", "1.0")),
                "language": language,
                "instruct": instruct,
            }
            request = urllib.request.Request(
                f"{base_url}/audio/speech",
                data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
                headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                method="POST",
            )
            try:
                wait_for_internal_ai_slot("tts-audio-chunk")
                with urllib.request.urlopen(request, timeout=180) as response:
                    audio_bytes = response.read()
            except urllib.error.HTTPError as exc:
                detail = exc.read().decode("utf-8", errors="ignore")[:600]
                raise RuntimeError(f"公司内网 TTS 返回 HTTP {exc.code}: {detail}") from exc
            if audio_bytes[:1] in {b"{", b"["}:
                raise RuntimeError(f"公司内网 TTS 未返回音频: {audio_bytes.decode('utf-8', errors='ignore')[:600]}")
            if len(audio_bytes) < 1024:
                raise RuntimeError(f"公司内网 TTS 音频异常短: {len(audio_bytes)} bytes")
            part_path = tmp / f"part_{index:03d}.mp3"
            part_path.write_bytes(audio_bytes)
            parts.append(part_path)

        concat_file = tmp / "concat.txt"
        concat_file.write_text("".join(f"file '{path.as_posix()}'\n" for path in parts), encoding="utf-8")
        merged = tmp / "merged.mp3"
        ffmpeg = shutil.which("ffmpeg")
        if ffmpeg:
            subprocess.run(
                [ffmpeg, "-y", "-f", "concat", "-safe", "0", "-i", str(concat_file), "-c", "copy", str(merged)],
                check=True,
                capture_output=True,
                timeout=240,
            )
            subprocess.run(
                [
                    ffmpeg,
                    "-y",
                    "-i",
                    str(merged),
                    "-af",
                    _internal_tts_consistency_filter(text, merged, ffmpeg),
                    "-ar",
                    "24000",
                    "-ac",
                    "1",
                    "-b:a",
                    "96k",
                    str(output_path),
                ],
                check=True,
                capture_output=True,
                timeout=240,
            )
        elif len(parts) == 1:
            shutil.copy2(parts[0], output_path)
        else:
            raise RuntimeError("合并多段公司内网 TTS 音频需要 ffmpeg")
    return f"internal-tts:{model}:{voice}"


def _synthesize_with_edge(text: str, output_path: Path) -> str | None:
    try:
        import asyncio
        import edge_tts
    except Exception:
        return None

    voice = os.environ.get("EDGE_TTS_VOICE", "zh-CN-XiaoxiaoNeural")
    rate = os.environ.get("EDGE_TTS_RATE", "-8%")
    pitch = os.environ.get("EDGE_TTS_PITCH", "+0Hz")

    async def run() -> None:
        communicate = edge_tts.Communicate(text=text, voice=voice, rate=rate, pitch=pitch)
        await communicate.save(str(output_path))

    asyncio.run(run())
    return f"edge-tts:{voice}"


def _ensure_sherpa_melo_files() -> Path | None:
    base = Path(os.environ.get("SHERPA_MELO_DIR") or TTS_MODEL_DIR / "sherpa" / "vits-melo-tts-zh_en")
    required = [base / "lexicon.txt", base / "tokens.txt", base / "dict", base / "phone.fst", base / "date.fst", base / "number.fst"]
    model = base / "model.int8.onnx"
    if all(path.exists() for path in required) and model.exists() and model.stat().st_size > 1024 * 1024:
        return base

    if os.environ.get("TTS_AUTO_DOWNLOAD", "1").strip().lower() not in {"1", "true", "yes"}:
        return None

    import tarfile

    tmp_archive = TTS_MODEL_DIR / "vits-melo-tts-zh_en.tar.bz2"
    TTS_MODEL_DIR.mkdir(parents=True, exist_ok=True)
    if not tmp_archive.exists():
        urlretrieve(os.environ.get("SHERPA_MELO_URL", SHERPA_MELO_URL), tmp_archive)
    with tarfile.open(tmp_archive, "r:bz2") as tar:
        tar.extractall(TTS_MODEL_DIR / "sherpa")
    tmp_archive.unlink(missing_ok=True)
    urlretrieve(os.environ.get("SHERPA_MELO_INT8_URL", SHERPA_MELO_INT8_URL), model)
    full_model = base / "model.onnx"
    if full_model.exists() and os.environ.get("KEEP_FULL_TTS_MODEL", "0").strip() not in {"1", "true", "yes"}:
        full_model.unlink()
    return base if all(path.exists() for path in required) and model.exists() else None


def _synthesize_with_sherpa_melo(text: str, output_path: Path) -> str | None:
    try:
        import sherpa_onnx
        import soundfile as sf
    except Exception:
        return None

    base = _ensure_sherpa_melo_files()
    if not base:
        return None

    config = sherpa_onnx.OfflineTtsConfig()
    config.model.vits.model = str(base / "model.int8.onnx")
    config.model.vits.lexicon = str(base / "lexicon.txt")
    config.model.vits.tokens = str(base / "tokens.txt")
    config.model.vits.data_dir = str(base / "dict")
    config.model.vits.length_scale = float(os.environ.get("SHERPA_MELO_LENGTH_SCALE", "0.9"))
    config.model.num_threads = int(os.environ.get("TTS_NUM_THREADS", "2"))
    config.rule_fsts = ",".join(str(base / name) for name in ["phone.fst", "date.fst", "number.fst"])
    config.max_num_sentences = 1

    tts = sherpa_onnx.OfflineTts(config)
    sid = int(os.environ.get("SHERPA_MELO_SID", "0"))
    speed = float(os.environ.get("SHERPA_MELO_SPEED", "1.0"))
    audio = tts.generate(text, sid=sid, speed=speed)
    sf.write(str(output_path), audio.samples, audio.sample_rate)
    return f"sherpa-melo:sid-{sid}"


def _synthesize_with_piper(text: str, output_path: Path) -> str | None:
    piper_bin = os.environ.get("PIPER_BIN") or shutil.which("piper")
    model = os.environ.get("PIPER_MODEL")
    if not piper_bin or not model or not Path(model).exists():
        return None
    cmd = [piper_bin, "--model", model, "--output_file", str(output_path)]
    config = os.environ.get("PIPER_CONFIG")
    if config and Path(config).exists():
        cmd.extend(["--config", config])
    subprocess.run(cmd, input=text, text=True, check=True, timeout=180)
    return "piper"


def _synthesize_with_macos_say(text: str, output_path: Path) -> str | None:
    if sys.platform != "darwin" or not shutil.which("say") or not shutil.which("afconvert"):
        return None
    voice = os.environ.get("MACOS_TTS_VOICE", "Tingting")
    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp = Path(tmp_dir)
        text_path = tmp / "summary.txt"
        aiff_path = tmp / "summary.aiff"
        text_path.write_text(text, encoding="utf-8")
        subprocess.run(["say", "-v", voice, "-f", str(text_path), "-o", str(aiff_path)], check=True, timeout=180)
        subprocess.run(["afconvert", "-f", "WAVE", "-d", "LEI16", str(aiff_path), str(output_path)], check=True, timeout=180)
    return "macos-say"


def _audio_duration_seconds(path: Path) -> float | None:
    ffprobe = shutil.which("ffprobe")
    if ffprobe:
        try:
            result = subprocess.run(
                [
                    ffprobe,
                    "-v",
                    "error",
                    "-show_entries",
                    "format=duration",
                    "-of",
                    "default=noprint_wrappers=1:nokey=1",
                    str(path),
                ],
                check=True,
                capture_output=True,
                text=True,
                timeout=20,
            )
            return float(result.stdout.strip())
        except Exception:
            pass
    return None


def _minimum_audio_duration_seconds(summary: str) -> float:
    return max(35.0, min(90.0, len(summary) / 7.0))


def synthesize_report_audio(report_path: Path, force: bool = False) -> dict:
    if not report_path.exists():
        raise FileNotFoundError(f"report not found: {report_path}")
    AUDIO_DIR.mkdir(exist_ok=True)
    if audio_info_for_report(report_path).get("exists") and not force:
        return {"ok": True, "created": False, "backend": "cached", "summary": "", "audio": audio_info_for_report(report_path)}

    summary = build_audio_summary(report_path)
    tts_text = prepare_tts_text(summary)
    backend = "internal"
    last_error = ""
    try:
        delete_audio_for_report(report_path)
        used = None
        output_path = audio_path_for_report_ext(report_path, ".wav")
        output_path = audio_path_for_report_ext(report_path, ".mp3")
        used = _synthesize_with_internal_tts(tts_text, output_path)
        if not used:
            raise RuntimeError(
                "公司内网 TTS 不可用，请检查内部模型网关、API Key、Qwen3TTS 和音色配置。"
            )
    except Exception as exc:
        last_error = str(exc)
        if output_path.exists():
            output_path.unlink()
    if last_error:
        return {"ok": False, "error": last_error, "summary": summary, "audio": {"exists": False}}

    duration = _audio_duration_seconds(output_path)
    minimum_duration = _minimum_audio_duration_seconds(summary)
    if duration is not None and duration < minimum_duration:
        if output_path.exists():
            output_path.unlink()
        return {
            "ok": False,
            "error": (
                f"生成音频仅{duration:.1f}秒，低于当前{len(summary)}字摘要要求的"
                f"{minimum_duration:.1f}秒，已阻止发布过短音频。"
            ),
            "summary": summary,
            "audio": {"exists": False},
        }

    try:
        timing_payload = _write_internal_asr_subtitle_timings(output_path)
    except Exception as exc:
        if output_path.exists():
            output_path.unlink()
        subtitle_timing_path_for_report(report_path).unlink(missing_ok=True)
        return {
            "ok": False,
            "error": f"音频已生成，但真实字幕时间轴生成失败：{exc}",
            "summary": summary,
            "audio": {"exists": False},
        }

    txt_path = audio_path_for_report_ext(report_path, ".txt")
    txt_path.write_text(str(timing_payload.get("spokenText") or tts_text), encoding="utf-8")

    return {
        "ok": True,
        "created": True,
        "backend": used,
        "summary": summary,
        "duration": duration,
        "audio": audio_info_for_report(report_path),
    }
