from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from urllib.request import urlretrieve
from pathlib import Path
from urllib.parse import quote

from docx import Document


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


def audio_info_for_report(report_path: Path) -> dict:
    audio_path = next((path for path in audio_paths_for_report(report_path) if path.exists()), None)
    if not audio_path:
        return {"exists": False}
    summary_text = ""
    txt_path = audio_path_for_report_ext(report_path, ".txt")
    if txt_path.exists():
        summary_text = txt_path.read_text(encoding="utf-8", errors="ignore")
    return {
        "exists": True,
        "name": audio_path.name,
        "url": f"/audio/{quote(audio_path.name)}",
        "size": audio_path.stat().st_size,
        "mtime": audio_path.stat().st_mtime,
        "mtimeText": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(audio_path.stat().st_mtime)),
        "summary": summary_text,
    }


def delete_audio_for_report(report_path: Path) -> None:
    for path in audio_paths_for_report(report_path) + [audio_path_for_report_ext(report_path, ".txt")]:
        if path.exists():
            path.unlink()


def rename_audio_for_report(old_report_path: Path, new_report_path: Path) -> None:
    AUDIO_DIR.mkdir(exist_ok=True)
    for old_audio in audio_paths_for_report(old_report_path) + [audio_path_for_report_ext(old_report_path, ".txt")]:
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
        "5G": "五 G",
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
    text = text.replace("/", "和")
    text = text.replace("&", "和")
    text = text.replace("欧盟 数据法案", "欧盟数据法案")
    text = re.sub(r"发布(.+?)相关政策信息", r"更新了\1信息", text)
    text = re.sub(r"发布(.+?)相关信息", r"更新了\1信息", text)
    text = re.sub(r"\([^)]*\)", "", text)
    text = re.sub(r"（[^）]*）", "", text)
    text = re.sub(r"\s+", " ", text)
    text = text.replace("；；", "；").replace("。。", "。")
    return text.strip(" ，。；")


def _generate_audio_summary_with_llm(text: str) -> str | None:
    from ai_config import load_ai_config
    import urllib.request
    import json
    import os

    config = load_ai_config(include_key=True)
    api_key = (os.environ.get("OPENAI_API_KEY") or str(config.get("api_key") or "")).strip()
    if not api_key:
        return None

    provider = str(config.get("provider") or "deepseek").lower()
    model = os.environ.get("OPENAI_MODEL") or str(config.get("model") or "deepseek-v4-flash")
    base_url = str(config.get("base_url") or "https://api.deepseek.com").rstrip("/")

    system_prompt = "你是一个专业的数据分析师和播音员。请根据以下的周报全文，撰写一段约60秒的精简汇报脱口秀脚本。字数控制在250-300字左右。要求：逻辑清晰，口语化，适合直接用于语音播报，直接输出播报文案，不要输出多余解释或开头语。"
    user_prompt = f"周报全文如下：\n{text[:12000]}"

    if provider == "openai":
        body = {"model": model, "instructions": system_prompt, "input": user_prompt}
        url = f"{base_url or 'https://api.openai.com/v1'}/responses"
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

    req = urllib.request.Request(
        url,
        data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=90) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
            if provider == "openai":
                return payload.get("output", {}).get("text", "")
            else:
                choices = payload.get("choices") or []
                if choices:
                    return ((choices[0].get("message") or {}).get("content") or "").strip()
    except Exception:
        pass
    return None


def build_audio_summary(report_path: Path, max_chars: int = 1500) -> str:
    text = _source_text(report_path)
    
    llm_summary = _generate_audio_summary_with_llm(text)
    if llm_summary:
        summary = normalize_for_speech(llm_summary)
        summary = re.sub(r"^(音频|语音)?摘要?已生成[，。,. ]*", "", summary)
        summary = re.sub(r"^本期战略竞对检测周报已生成[，。,. ]*", "", summary)
        if len(summary) > max_chars:
            summary = summary[: max_chars - 1].rstrip("，。；,. ") + "。"
        elif summary and not summary.endswith(("。", "！", "？")):
            summary += "。"
        return summary
    
    lines = [re.sub(r"\s+", " ", line).strip() for line in text.splitlines()]
    lines = [line for line in lines if line]
    if not lines:
        return "本期暂无可提取的重点内容，请打开 Word 文件查看详细内容。"

    skip_exact = {"目 录", "目录"}
    useful: list[str] = []
    for line in lines:
        if line in skip_exact:
            continue
        if line.startswith("中国移动香港公司"):
            continue
        if re.fullmatch(r"(政治|行业|社会|国际)资讯", line):
            continue
        if "（本期暂无更新）" in line:
            continue
        useful.append(line.strip(" #-\t"))

    title_items = [line for line in useful if re.match(r"^\d+\.【[^】]+】", line)]
    highlights = title_items[:4] or useful[:5]

    summary_parts: list[str] = []
    if highlights:
        cleaned = []
        for item in highlights:
            title = re.sub(r"^\d+\.【[^】]+】", "", item)
            title = normalize_for_speech(title)
            if title:
                cleaned.append(title)
        if cleaned:
            summary_parts.append("本期重点关注：" + "；".join(cleaned[:4]) + "。")
    summary_parts.append("建议先看政策监管变化，再看友商经营指标、产品资费调整和国际运营商动态。")

    summary = normalize_for_speech("".join(summary_parts))
    summary = re.sub(r"^(音频|语音)?摘要?已生成[，。,. ]*", "", summary)
    summary = re.sub(r"^本期战略竞对检测周报已生成[，。,. ]*", "", summary)
    fallback_max_chars = 360
    if len(summary) > fallback_max_chars:
        summary = summary[: fallback_max_chars - 1].rstrip("，。；,. ") + "。"
    elif summary and not summary.endswith(("。", "！", "？")):
        summary += "。"
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
        return None

    runtime = OnnxTtsRuntime(
        model_dir=str(base),
        thread_count=int(os.environ.get("MOSS_TTS_THREADS", "4")),
        max_new_frames=int(os.environ.get("MOSS_TTS_MAX_NEW_FRAMES", "260")),
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
    runtime.synthesize(
        text=text,
        voice=voice,
        prompt_audio_path=os.environ.get("MOSS_TTS_PROMPT_AUDIO_PATH") or None,
        output_audio_path=str(output_path),
        sample_mode=os.environ.get("MOSS_TTS_SAMPLE_MODE", "fixed"),
        do_sample=os.environ.get("MOSS_TTS_DO_SAMPLE", "1").strip().lower() not in {"0", "false", "no"},
        streaming=os.environ.get("MOSS_TTS_STREAMING", "1").strip().lower() not in {"0", "false", "no"},
        max_new_frames=int(os.environ.get("MOSS_TTS_MAX_NEW_FRAMES", "260")),
        voice_clone_max_text_tokens=int(os.environ.get("MOSS_TTS_MAX_TEXT_TOKENS", "75")),
        enable_wetext=False,
        enable_normalize_tts_text=True,
        seed=int(os.environ["MOSS_TTS_SEED"]) if os.environ.get("MOSS_TTS_SEED") else None,
    )
    return f"moss-tts-nano:{voice}"


def prepare_tts_text(value: str) -> str:
    text = value.replace("：", "，").replace("；", "。")
    text = text.replace("、", "，")
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


def synthesize_report_audio(report_path: Path, force: bool = False) -> dict:
    if not report_path.exists():
        raise FileNotFoundError(f"report not found: {report_path}")
    AUDIO_DIR.mkdir(exist_ok=True)
    if audio_info_for_report(report_path).get("exists") and not force:
        return {"ok": True, "created": False, "backend": "cached", "summary": "", "audio": audio_info_for_report(report_path)}

    summary = build_audio_summary(report_path)
    tts_text = prepare_tts_text(summary)
    backend = os.environ.get("TTS_BACKEND", "auto").strip().lower() or "auto"
    last_error = ""
    try:
        delete_audio_for_report(report_path)
        used = None
        output_path = audio_path_for_report_ext(report_path, ".wav")
        if backend in {"auto", "moss", "moss-tts", "moss-tts-nano"}:
            used = _synthesize_with_moss(tts_text, output_path)
        if not used and backend in {"auto", "sherpa", "sherpa-melo", "melotts", "melo"}:
            used = _synthesize_with_sherpa_melo(tts_text, output_path)
        if not used and backend in {"auto", "edge", "edge-tts"}:
            output_path = audio_path_for_report_ext(report_path, ".mp3")
            used = _synthesize_with_edge(tts_text, output_path)
        if not used and backend in {"auto", "kokoro", "kokoro-onnx"}:
            output_path = audio_path_for_report_ext(report_path, ".wav")
            used = _synthesize_with_kokoro(tts_text, output_path)
        if not used and backend in {"auto", "piper"}:
            output_path = audio_path_for_report_ext(report_path, ".wav")
            used = _synthesize_with_piper(tts_text, output_path)
        if not used and backend in {"auto", "say", "macos-say"}:
            output_path = audio_path_for_report_ext(report_path, ".wav")
            used = _synthesize_with_macos_say(tts_text, output_path)
        if not used:
            raise RuntimeError(
                "未找到可用 TTS 后端。生产环境建议配置 Piper/MeloTTS/Kokoro；本机兜底需要 macOS say。"
            )
    except Exception as exc:
        last_error = str(exc)
        if output_path.exists():
            output_path.unlink()
    if last_error:
        return {"ok": False, "error": last_error, "summary": summary, "audio": {"exists": False}}
        
    txt_path = audio_path_for_report_ext(report_path, ".txt")
    txt_path.write_text(summary, encoding="utf-8")
    
    return {"ok": True, "created": True, "backend": used, "summary": summary, "audio": audio_info_for_report(report_path)}
