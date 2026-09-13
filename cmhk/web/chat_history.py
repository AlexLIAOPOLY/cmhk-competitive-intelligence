from __future__ import annotations

# Annotation imports do not create application services or mutable state.
from http.server import BaseHTTPRequestHandler

from ._binding import publish


def bind(app) -> None:
    """Bind this domain to the existing application and its shared state."""
    def is_loopback_client(address: str) -> bool:
        try:
            parsed = app.ipaddress.ip_address(address)
        except ValueError:
            return False
        if isinstance(parsed, app.ipaddress.IPv6Address) and parsed.ipv4_mapped:
            parsed = parsed.ipv4_mapped
        return parsed.is_loopback

    publish(app, is_loopback_client)

    def sample_chat_starters(limit: int = 4) -> list[dict]:
        count = max(1, min(int(limit), len(app.CHAT_STARTER_POOL)))
        return [dict(item) for item in app.CHAT_STARTER_POOL[:count]]

    publish(app, sample_chat_starters)

    def request_runtime_context(handler: BaseHTTPRequestHandler) -> dict:
        now = app.datetime.now().astimezone()
        client_ip = ""
        try:
            client_ip = str(handler.client_address[0] or "")
        except Exception:
            client_ip = ""
        forwarded_for = str(handler.headers.get("X-Forwarded-For") or "").split(",")[0].strip()
        real_ip = str(handler.headers.get("X-Real-IP") or "").strip()
        visible_ip = forwarded_for or real_ip or client_ip or "unknown"
        if visible_ip in {"127.0.0.1", "::1", "localhost"} or visible_ip.startswith(("10.", "192.168.", "172.16.", "172.17.", "172.18.", "172.19.", "172.20.", "172.21.", "172.22.", "172.23.", "172.24.", "172.25.", "172.26.", "172.27.", "172.28.", "172.29.", "172.30.", "172.31.")):
            location_hint = "本机或内网访问；按服务端时区和用户工作环境推断为 Hong Kong / Asia_Hong_Kong"
        else:
            location_hint = "公网 IP；未接入第三方 GeoIP，不能精确到城市"
        return {
            "current_time": now.isoformat(timespec="seconds"),
            "timezone": now.tzname() or "local",
            "utc_offset": now.strftime("%z"),
            "client_ip": client_ip,
            "forwarded_for": forwarded_for,
            "real_ip": real_ip,
            "visible_ip": visible_ip,
            "location_hint": location_hint,
        }

    publish(app, request_runtime_context)

    def _now_iso() -> str:
        return app.datetime.now().isoformat(timespec="seconds")

    publish(app, _now_iso)

    def _clean_chat_message(item: dict) -> dict | None:
        if not isinstance(item, dict):
            return None
        role = "assistant" if item.get("role") == "assistant" else "user"
        content = str(item.get("content") or "").strip()
        if not content:
            return None
        clean = {"role": role, "content": content[:20000]}
        for timestamp_key in ("createdAt", "completedAt"):
            timestamp = str(item.get(timestamp_key) or "").strip()
            if timestamp:
                try:
                    normalized = timestamp[:-1] + "+00:00" if timestamp.endswith(("Z", "z")) else timestamp
                    app.datetime.fromisoformat(normalized)
                except ValueError:
                    continue
                clean[timestamp_key] = timestamp[:40]
        if role == "user":
            display_content = str(item.get("displayContent") or "").strip()
            if display_content:
                clean["displayContent"] = display_content[:4000]
            image_preview = item.get("imagePreview")
            if isinstance(image_preview, dict):
                data_url = str(image_preview.get("dataUrl") or "")
                if len(data_url) <= 1_500_000 and app.re.match(r"^data:image/(?:png|jpeg|webp|gif);base64,", data_url, flags=app.re.I):
                    clean["imagePreview"] = {
                        "name": str(image_preview.get("name") or "已发送图片")[:200],
                        "dataUrl": data_url,
                    }
        else:
            references = item.get("references")
            links = item.get("links")
            suggestions = item.get("suggestions")
            timeline = item.get("timeline")
            metrics = item.get("metrics")
            if isinstance(references, list):
                clean["references"] = references[:30]
            if isinstance(links, list):
                clean["links"] = links[:30]
            if isinstance(suggestions, list):
                clean["suggestions"] = [str(s).strip()[:160] for s in suggestions if str(s).strip()][:3]
            if isinstance(timeline, list):
                clean_timeline = []
                timeline_size = 0
                for raw_event in timeline[:240]:
                    if not isinstance(raw_event, dict):
                        continue
                    event_type = str(raw_event.get("type") or "")
                    if event_type == "text":
                        event = {"type": "text", "text": str(raw_event.get("text") or "")[:20000]}
                        if not event["text"]:
                            continue
                    elif event_type in {"tool_call_start", "tool_call_result"}:
                        event = {
                            "type": event_type,
                            "id": str(raw_event.get("id") or "")[:160],
                            "name": str(raw_event.get("name") or "")[:120],
                            "processText": str(raw_event.get("processText") or "")[:500],
                            "args": str(raw_event.get("args") or "")[:6000],
                            "content": str(raw_event.get("content") or "")[:16000],
                        }
                    else:
                        continue
                    event_size = len(app.json.dumps(event, ensure_ascii=False))
                    if timeline_size + event_size > 120000:
                        break
                    timeline_size += event_size
                    clean_timeline.append(event)
                if clean_timeline:
                    clean["timeline"] = clean_timeline
            if isinstance(metrics, dict):
                clean["metrics"] = {
                    "inputTokens": max(0, int(metrics.get("inputTokens") or 0)),
                    "outputTokens": max(0, int(metrics.get("outputTokens") or 0)),
                    "totalTokens": max(0, int(metrics.get("totalTokens") or 0)),
                    "durationMs": max(0, int(metrics.get("durationMs") or 0)),
                    "estimated": bool(metrics.get("estimated")),
                }
        return clean

    publish(app, _clean_chat_message)

    def load_chat_threads() -> list[dict]:
        if not app.CHAT_THREADS_PATH.exists():
            return []
        try:
            data = app.json.loads(app.CHAT_THREADS_PATH.read_text(encoding="utf-8"))
        except Exception:
            return []
        threads = data.get("threads") if isinstance(data, dict) else data
        if not isinstance(threads, list):
            return []
        return [item for item in threads if isinstance(item, dict) and item.get("id")]

    publish(app, load_chat_threads)

    def save_chat_threads(threads: list[dict]) -> None:
        app.CHAT_THREADS_DIR.mkdir(parents=True, exist_ok=True)
        app.CHAT_THREADS_PATH.write_text(
            app.json.dumps({"threads": threads[:200]}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    publish(app, save_chat_threads)

    def chat_thread_summaries() -> list[dict]:
        threads = sorted(app.load_chat_threads(), key=lambda item: str(item.get("updatedAt") or ""), reverse=True)
        threads = sorted(threads, key=lambda item: 0 if item.get("pinned") else 1)
        summaries = []
        for thread in threads:
            messages = thread.get("messages") if isinstance(thread.get("messages"), list) else []
            last = next((m for m in reversed(messages) if isinstance(m, dict) and m.get("content")), {})
            preview = str(last.get("content") or "")
            preview = app.re.sub(r"[*_`#]+", "", preview)
            preview = app.re.sub(r"!?\[([^\]]*)\]\([^)]*\)", r"\1", preview)
            preview = app.re.sub(r"\s+", " ", preview).strip()[:120]
            summaries.append(
                {
                    "id": thread.get("id"),
                    "title": thread.get("title") or "未命名对话",
                    "createdAt": thread.get("createdAt"),
                    "updatedAt": thread.get("updatedAt"),
                    "messageCount": len(messages),
                    "preview": preview,
                    "pinned": bool(thread.get("pinned")),
                }
            )
        return summaries

    publish(app, chat_thread_summaries)

    def _sanitize_thread_title(raw: str) -> str:
        title = app.re.sub(r"^[\"'“”‘’\s]+|[\"'“”‘’\s]+$", "", str(raw or ""))
        title = app.re.sub(r"^(标题|对话标题|主题)[:：]\s*", "", title)
        title = app.re.sub(r"[\r\n\t]+", " ", title)
        title = app.re.sub(r"\s+", " ", title).strip(" -_，。,.")
        return title[:24] or "新对话"

    publish(app, _sanitize_thread_title)

    def _fallback_thread_title(first_user: str) -> str:
        text = app.re.sub(r"\s+", " ", str(first_user or "")).strip()
        if text in {"你好", "您好", "hi", "hello", "看看", "测试"}:
            return "初次咨询"
        text = app.re.sub(r"^(请|帮我|麻烦|能不能|可以|给我)", "", text).strip()
        return app._sanitize_thread_title(text[:18] or "新对话")

    publish(app, _fallback_thread_title)

    def _thread_title_source(messages: list[dict]) -> str:
        generic = {"你好", "您好", "hi", "hello", "看看", "测试"}
        users = [str(item.get("content") or "").strip() for item in messages if item.get("role") == "user"]
        for text in users:
            normalized = app.re.sub(r"\s+", " ", text).strip()
            if len(normalized) >= 6 and normalized.lower() not in generic:
                return normalized
        return users[0] if users else ""

    publish(app, _thread_title_source)

    def generate_chat_thread_title(first_user: str) -> str:
        first_user = str(first_user or "").strip()
        if not first_user:
            return "新对话"
        config = app.load_ai_config(include_key=True)
        api_key = str(config.get("api_key") or "").strip()
        if not api_key:
            return app._fallback_thread_title(first_user)
        provider = str(config.get("provider") or "deepseek").lower()
        model = (
            app.os.environ.get("CMHK_CHAT_TITLE_MODEL", "").strip()
            or "Qwen3-30B-A3B-Instruct-2507"
        )
        base_url = str(config.get("base_url") or app.INTERNAL_AI_BASE_URL).rstrip("/")
        prompt = (
            "请根据用户第一条问题生成一个中文对话标题。"
            "要求：6到12个汉字或短词；不要照抄原句；不要加引号、标点、解释或前缀。\n\n"
            f"用户第一问：{first_user[:500]}"
        )
        body = {
            "model": model,
            "messages": [
                {"role": "system", "content": "你只输出简洁中文标题。"},
                {"role": "user", "content": prompt},
            ],
            "temperature": 0.1,
            "max_tokens": 48,
        }
        from cmhk.ai.ai_response_compat import deepseek_nonthinking_parameters
        body.update(config.get("extra_parameters") or {})
        body = deepseek_nonthinking_parameters(body)
        req = app.urllib.request.Request(
            f"{base_url}/chat/completions",
            data=app.json.dumps(body, ensure_ascii=False).encode("utf-8"),
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            method="POST",
        )
        try:
            with app.open_llm_request(
                req,
                timeout=12,
                config=config,
                requested_key=api_key,
                model=model,
                operation="chat-thread-title",
            ) as resp:
                payload = app.json.loads(resp.read().decode("utf-8"))
            content = str(payload.get("choices", [{}])[0].get("message", {}).get("content") or "").strip()
            if not content:
                return app._fallback_thread_title(first_user)
            title = app._sanitize_thread_title(content)
            if title in {"新对话", "未命名对话"}:
                return app._fallback_thread_title(first_user)
            return title
        except Exception as exc:
            print(f"chat thread title generation failed: {exc}", flush=True)
            return app._fallback_thread_title(first_user)

    publish(app, generate_chat_thread_title)

    def _schedule_chat_thread_title(thread_id: str, title_source: str) -> None:
        """Refresh an AI chat title in the background without blocking message saves."""
        source = str(title_source or "").strip()
        if not thread_id or not source:
            return
        with app.CHAT_TITLE_TASK_LOCK:
            app.CHAT_TITLE_PENDING[thread_id] = source
            if thread_id in app.CHAT_TITLE_ACTIVE:
                return
            app.CHAT_TITLE_ACTIVE.add(thread_id)

        def worker() -> None:
            try:
                while True:
                    with app.CHAT_TITLE_TASK_LOCK:
                        current_source = app.CHAT_TITLE_PENDING.pop(thread_id, "")
                    if not current_source:
                        return
                    generated_title = app.generate_chat_thread_title(current_source)
                    with app.CHAT_TITLE_TASK_LOCK:
                        has_newer_source = bool(app.CHAT_TITLE_PENDING.get(thread_id))
                    with app.CHAT_THREADS_LOCK:
                        threads = app.load_chat_threads()
                        target = next((item for item in threads if str(item.get("id")) == thread_id), None)
                        if target and target.get("titlePending"):
                            target["title"] = generated_title
                            target["titlePending"] = has_newer_source
                            app.save_chat_threads(threads)
                    if not has_newer_source:
                        return
            finally:
                with app.CHAT_TITLE_TASK_LOCK:
                    app.CHAT_TITLE_ACTIVE.discard(thread_id)
                    should_restart = bool(app.CHAT_TITLE_PENDING.get(thread_id))
                if should_restart:
                    app._schedule_chat_thread_title(thread_id, app.CHAT_TITLE_PENDING.get(thread_id, ""))

        app.threading.Thread(target=worker, name=f"chat-title-{thread_id[:8]}", daemon=True).start()

    publish(app, _schedule_chat_thread_title)

    def get_chat_thread(thread_id: str) -> dict | None:
        for thread in app.load_chat_threads():
            if str(thread.get("id")) == thread_id:
                return thread
        return None

    publish(app, get_chat_thread)

    def upsert_chat_thread(payload: dict) -> dict:
        messages = [app._clean_chat_message(item) for item in payload.get("messages", []) if isinstance(item, dict)]
        messages = [item for item in messages if item]
        title = str(payload.get("title") or "").strip()
        thread_id = str(payload.get("id") or "").strip() or app.uuid.uuid4().hex[:12]
        now = app._now_iso()
        existing_title = ""
        existing_title_pending = False
        for thread in app.load_chat_threads():
            if str(thread.get("id")) == thread_id and thread.get("title"):
                existing_title = str(thread.get("title"))
                existing_title_pending = bool(thread.get("titlePending"))
                break
        if title:
            title = app._sanitize_thread_title(title)
        title_source = app._thread_title_source(messages)
        first_user = next((item["content"] for item in messages if item["role"] == "user"), "")
        placeholder_titles = {
            "新对话",
            "未命名对话",
            "你好",
            "看看",
            first_user[:24],
            app._fallback_thread_title(first_user),
        }
        title_pending = False
        if title:
            title_pending = False
        elif existing_title and not existing_title_pending and existing_title not in placeholder_titles:
            title = existing_title
        else:
            title = app._fallback_thread_title(title_source or first_user)
            title_pending = True
        with app.CHAT_THREADS_LOCK:
            threads = app.load_chat_threads()
            existing = next((item for item in threads if str(item.get("id")) == thread_id), None)
            record = {
                "id": thread_id,
                "title": title[:80],
                "titlePending": title_pending,
                "createdAt": (existing or {}).get("createdAt") or now,
                "updatedAt": now,
                "messages": messages[-80:],
                "agentContextKey": str(payload.get("agentContextKey") or ""),
                "loadedSkillIds": [str(item) for item in payload.get("loadedSkillIds", []) if str(item)],
                "pinned": bool((existing or {}).get("pinned")),
            }
            threads = [item for item in threads if str(item.get("id")) != thread_id]
            threads.insert(0, record)
            app.save_chat_threads(threads)
        if title_pending:
            app._schedule_chat_thread_title(thread_id, title_source or first_user)
        return record

    publish(app, upsert_chat_thread)

    def delete_chat_thread(thread_id: str) -> bool:
        with app.CHAT_THREADS_LOCK:
            threads = app.load_chat_threads()
            next_threads = [item for item in threads if str(item.get("id")) != thread_id]
            app.save_chat_threads(next_threads)
        return len(next_threads) != len(threads)

    publish(app, delete_chat_thread)

    def set_chat_thread_pinned(thread_id: str, pinned: bool) -> dict | None:
        with app.CHAT_THREADS_LOCK:
            threads = app.load_chat_threads()
            updated = None
            for thread in threads:
                if str(thread.get("id")) == thread_id:
                    thread["pinned"] = bool(pinned)
                    thread["updatedAt"] = app._now_iso()
                    updated = thread
                    break
            app.save_chat_threads(threads)
        return updated

    publish(app, set_chat_thread_pinned)

