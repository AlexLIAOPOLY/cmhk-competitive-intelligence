from __future__ import annotations

from ._binding import publish


def bind(app) -> None:
    """Bind this domain to the existing application and its shared state."""
    def analyze_chat_image(payload: dict) -> dict:
        config = app.load_ai_config(include_key=True)
        requested_model = str(payload.get("model") or config.get("model") or "").strip()
        vision_pattern = r"(?:vision|multimodal|omni|(?:^|[-_.])vl(?:[-_.]|$)|qwen[^/]*vl|internvl|llava|gpt-4o|gpt-4\.1|gemini|claude-3|kimi[-_.]?k2\.5)"
        model = requested_model
        if not app.re.search(vision_pattern, model, flags=app.re.I):
            model = str(app.os.environ.get("CMHK_CHAT_IMAGE_MODEL") or "Kimi-K2.5").strip()
        if not app.re.search(vision_pattern, model, flags=app.re.I):
            raise ValueError("未配置可用的图片识别模型")
        data_url = str(payload.get("image") or "").strip()
        match = app.re.fullmatch(r"data:(image/(?:png|jpeg|webp|gif));base64,([A-Za-z0-9+/=\s]+)", data_url, flags=app.re.I)
        if not match:
            raise ValueError("只支持 PNG、JPG、WebP 或 GIF 图片")
        raw = app.base64.b64decode(app.re.sub(r"\s+", "", match.group(2)), validate=True)
        if not raw or len(raw) > app.CHAT_IMAGE_MAX_BYTES:
            raise ValueError("图片不能为空且不能超过 8 MB")
        base_url = str(config.get("base_url") or "").strip().rstrip("/")
        api_key = str(config.get("api_key") or "").strip()
        if not app.is_internal_ai_base_url(base_url) or not api_key:
            raise ValueError("AI 模型配置不完整")
        question = str(payload.get("question") or "请分析这张图片").strip()[:1200]
        body = {
            "model": model,
            "messages": [{
                "role": "user",
                "content": [
                    {"type": "text", "text": f"请准确识别图片中与下列问题相关的内容，输出可供后续分析的中文事实描述，不要猜测。问题：{question}"},
                    {"type": "image_url", "image_url": {"url": data_url}},
                ],
            }],
            "max_tokens": 900,
            "stream": False,
        }
        from cmhk.ai.ai_response_compat import deepseek_nonthinking_parameters
        body.update(config.get("extra_parameters") or {})
        body = deepseek_nonthinking_parameters(body)
        request = app.urllib.request.Request(
            f"{base_url}/chat/completions",
            data=app.json.dumps(body, ensure_ascii=False).encode("utf-8"),
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            method="POST",
        )
        with app.open_llm_request(
            request,
            timeout=90,
            config=config,
            requested_key=api_key,
            model=model,
            operation="chat-image-analyze",
        ) as response:
            result = app.json.loads(response.read().decode("utf-8"))
        from cmhk.ai.ai_response_compat import final_chat_message_text
        content = final_chat_message_text(result, operation="图片识别")
        if isinstance(content, list):
            content = "\n".join(str(item.get("text") or "") for item in content if isinstance(item, dict))
        elif isinstance(content, dict):
            content = content.get("text") or content.get("content") or ""
        description = str(content).strip()
        if not description:
            raise ValueError("视觉模型没有返回可用的图片描述")
        return {"description": description, "model": model}

    publish(app, analyze_chat_image)

    def _competitor_insight_content(content: object) -> str:
        """Normalize the model response container without applying semantic gates."""
        if isinstance(content, list):
            text = "".join(str(item.get("text") or "") for item in content if isinstance(item, dict))
        elif isinstance(content, dict):
            text = str(content.get("text") or content.get("content") or "")
        else:
            text = str(content or "")
        if not text.strip():
            raise RuntimeError("AI 未返回可用洞察")
        return text

    publish(app, _competitor_insight_content)

    def _parse_competitor_insight_items(content: object) -> list[str]:
        """Best-effort three-row display parsing; format drift must not reject a usable answer."""
        text = app._competitor_insight_content(content).strip()
        text = app.re.sub(r"^```(?:json|text|markdown)?\s*|\s*```$", "", text, flags=app.re.I)
        labels = ("竞争格局", "公司定位", "业务含义")
        aliases = {"竞争格局": 0, "公司分化": 1, "公司定位": 1, "业务含义": 2}
        labelled: dict[int, str] = {}
        candidates: list[str] = []
        active_label_index: int | None = None
        for raw_line in text.splitlines():
            line = app.re.sub(r"^\s*(?:#{1,6}\s*|[-*•]\s+|\d+[.)、]\s*)", "", raw_line).strip()
            line = app.re.sub(r"^\*\*(.*?)\**$", r"\1", line).strip()
            if not line or app.re.fullmatch(r"\|?\s*:?-{2,}[-| :]*", line):
                continue
            if app.re.match(r"^(?:战略指标|核心结论)[：|｜]", line):
                active_label_index = None
                continue
            match = app.re.match(r"^(?:一|二|三)?[、.\s]*(竞争格局|公司分化|公司定位|业务含义)[：|｜]\s*(.+)$", line)
            if match:
                label_index = aliases[match.group(1)]
                value = match.group(2).strip()
                labelled.setdefault(label_index, value)
                active_label_index = None if app.re.search(r"[。！？!?；;]$", value) else label_index
                continue
            if active_label_index is not None:
                labelled[active_label_index] = f"{labelled.get(active_label_index, '')}{line}".strip()
            elif len(line) < 12 and not app.re.search(r"[\d。！？!?；;，,]", line):
                continue
            elif not (line.startswith("|") and line.endswith("|")):
                candidates.append(line)
        if len(candidates) < 3 and not labelled:
            sentences = [part.strip() for part in app.re.split(r"(?<=[。！？!?])\s*", " ".join(candidates) or text) if part.strip()]
            if len(sentences) > len(candidates):
                candidates = sentences
        result: list[str] = []
        candidate_index = 0
        for index, label in enumerate(labels):
            value = labelled.get(index, "")
            while not value and candidate_index < len(candidates):
                candidate = candidates[candidate_index]
                candidate_index += 1
                value = candidate
            if not value:
                continue
            value = app.re.sub(r"^(?:竞争格局|公司分化|公司定位|业务含义)[：|｜]\s*", "", value).strip()
            if len(value) > 180:
                value = value[:179].rstrip("，,；; ") + "…"
            result.append(f"{label}｜{value}")
        return result

    publish(app, _parse_competitor_insight_items)

    def _parse_competitor_strategic_signal(content: object) -> tuple[str, list[str]]:
        """Extract the strategic sentence and the short phrases selected by the model."""
        text = app._competitor_insight_content(content).strip()
        text = app.re.sub(r"^```(?:json|text|markdown)?\s*|\s*```$", "", text, flags=app.re.I)
        for raw_line in text.splitlines():
            line = app.re.sub(r"^\s*(?:#{1,6}\s*|[-*•]\s+|\d+[.)、]\s*)", "", raw_line).strip()
            match = app.re.match(r"^(?:战略指标|核心结论)[：|｜]\s*(.+)$", line)
            if not match:
                continue
            marked_value = match.group(1).strip()
            highlights: list[str] = []
            for highlighted in app.re.findall(r"【([^【】]{2,12})】", marked_value):
                value = highlighted.strip()
                if value and value not in highlights:
                    highlights.append(value)
                if len(highlights) == 3:
                    break
            value = app.re.sub(r"[【】]", "", marked_value).strip().rstrip("。．.")
            if len(value) > 100:
                value = value[:99].rstrip("，,；; ") + "…"
            return value, [item for item in highlights if item in value]
        return "", []

    publish(app, _parse_competitor_strategic_signal)

    def _parse_competitor_strategic_indicator(content: object) -> str:
        """Compatibility wrapper returning only the clean strategic sentence."""
        return app._parse_competitor_strategic_signal(content)[0]

    publish(app, _parse_competitor_strategic_indicator)

    def _competitor_currency_from_unit(unit: str) -> str:
        match = app.re.search(r"(?:^|_)(HKD|USD|EUR|CNY|RMB|JPY|KRW|SGD|INR|GBP)(?:_|$)", unit or "", app.re.I)
        return (match.group(1).upper().replace("RMB", "CNY") if match else "")

    publish(app, _competitor_currency_from_unit)

    def _competitor_value_in_usd(value: float, unit: str, local_per_usd: float) -> tuple[float, str]:
        if local_per_usd <= 0:
            raise ValueError("年度平均汇率必须大于零")
        scale = 1000.0 if app.re.search(r"(?:^|_)billion(?:_|$)", unit, app.re.I) else 10.0 if app.re.search(r"(?:^|_)crore(?:_|$)", unit, app.re.I) else 1.0
        translated_unit = "USD/户/月" if app.re.search(r"per_user|per_month|arpu|arpa", unit, app.re.I) else "USD million"
        return value * scale / local_per_usd, translated_unit

    publish(app, _competitor_value_in_usd)

    def generate_competitor_insight(payload: dict, stream_callback=None) -> dict:
        request_id = str(payload.get("requestId") or "")[:80]
        companies = [str(value)[:80] for value in (payload.get("companies") or []) if str(value).strip()]
        metric = payload.get("metric") if isinstance(payload.get("metric"), dict) else {}
        years = [int(value) for value in (payload.get("years") or [])]
        if len(set(companies)) != len(companies) or len(set(years)) != len(years):
            raise ValueError("竞对或年份包含重复选择")
        if not (2 <= len(companies) <= 6) or not (2 <= len(years) <= 10):
            raise ValueError("竞对、年份或表格数据不完整")
        metric_key = str(metric.get("key") or "")[:120]
        if not metric_key or not app.COMPETITOR_WORKBENCH_DATA_PATH.exists():
            raise ValueError("竞对指标或权威数据集不可用")
        canonical = app.json.loads(app.COMPETITOR_WORKBENCH_DATA_PATH.read_text(encoding="utf-8"))
        evidence_version = str(payload.get("evidenceVersion") or "")
        if evidence_version and evidence_version != str(canonical.get("evidenceVersion") or ""):
            raise ValueError("竞对数据版本已更新，请刷新后重试")
        allowed = set(companies)
        normalized = [
            {
                "company": str(row.get("company") or "")[:80],
                "year": int(row.get("year") or 0),
                "value": float(row.get("value")),
                "unit": str(row.get("unit") or "")[:80],
                "comparator": str(row.get("comparator") or "=")[:8],
                "period": str(row.get("period") or "")[:40],
                "period_end": str(row.get("periodEnd") or "")[:20],
                "scope": str(row.get("scope") or "")[:300],
                "basis": str(row.get("basis") or "")[:120],
                "status": str(row.get("status") or "")[:80],
                "source": str(row.get("source") or "")[:500],
                "note": str(row.get("note") or "")[:500],
            }
            for row in (canonical.get("cells") or [])
            if isinstance(row, dict)
            and str(row.get("company") or "") in allowed
            and str(row.get("metric") or "") == metric_key
            and int(row.get("year") or 0) in years
        ]
        normalized.sort(key=lambda row: (row["year"], row["company"]))
        if not normalized or len(normalized) > 80:
            raise ValueError("当前比较范围没有可用的权威数据")
        company_groups = {
            str(item.get("id") or ""): str(item.get("group") or "")
            for item in (canonical.get("companies") or [])
            if isinstance(item, dict)
        }
        all_international = all(company_groups.get(company) == "国际运营商" for company in companies)
        fx_payload = canonical.get("fxRates") if isinstance(canonical.get("fxRates"), dict) else {}
        fx_rates = {
            (str(item.get("currency") or ""), int(item.get("year") or 0)): float(item.get("local_per_usd"))
            for item in (fx_payload.get("rates") or [])
            if isinstance(item, dict) and item.get("local_per_usd") is not None
        }
        units = {row["unit"] for row in normalized}
        currencies = {app._competitor_currency_from_unit(unit) for unit in units}
        convert_to_usd = all_international and bool(currencies) and "" not in currencies
        if len(units) != 1 and not convert_to_usd:
            raise ValueError("所选数据单位不一致，不能直接比较")
        if convert_to_usd:
            for row in normalized:
                currency = app._competitor_currency_from_unit(row["unit"])
                rate = fx_rates.get((currency, row["year"]))
                if rate is None:
                    raise ValueError(f"缺少 {currency} {row['year']} 年官方平均汇率")
                reported_value, reported_unit = row["value"], row["unit"]
                row["value"], row["unit"] = app._competitor_value_in_usd(reported_value, reported_unit, rate)
                row["reported_value"] = reported_value
                row["reported_unit"] = reported_unit
                row["fx_local_per_usd"] = rate
        per_company_years = {company: {row["year"] for row in normalized if row["company"] == company} for company in companies}
        if any(len(company_years) < 2 for company_years in per_company_years.values()):
            raise ValueError("每家竞对至少需要两个有效年度")
        common_years = sorted(set.intersection(*(set(value) for value in per_company_years.values())))
        if len(common_years) < 2:
            raise ValueError("共同可比年度不足两个，暂不生成 AI 解析")
        comparison_rows = [row for row in normalized if row["year"] in common_years]
        # URLs and repeated per-year disclosure metadata made this prompt large
        # enough for the gateway's hidden reasoning to consume the whole completion
        # budget.  The model needs values plus native scope/basis/notes; official
        # source URLs remain available in the rendered evidence table and are not
        # useful input to this no-external-knowledge analysis.
        table = "\n".join(
            "\t".join(str(row.get(key, "")) for key in ("company", "year", "comparator", "value", "unit", "reported_value", "reported_unit", "fx_local_per_usd"))
            for row in comparison_rows
        )
        definition_lines: list[str] = []
        for company in companies:
            company_rows = [row for row in comparison_rows if row["company"] == company]
            scopes = sorted({row["scope"] for row in company_rows if row["scope"]})
            definition_lines.append(f"{company}={' / '.join(scopes) or '未标注'}")
        definitions = "\n".join(definition_lines)
        fx_context = (
            f"\n汇率来源\n{fx_payload.get('publisher', '')} · {fx_payload.get('indicator', '')} · 指标年份对应自然年平均（非财年逐月加权） · {fx_payload.get('source_url', '')}"
            if convert_to_usd else ""
        )
        config = app.load_ai_config(include_key=True)
        base_url = str(config.get("base_url") or app.INTERNAL_AI_BASE_URL).strip().rstrip("/")
        api_key = str(config.get("api_key") or "").strip()
        model = str(config.get("model") or "").strip()
        if not base_url or not api_key or not model or not app.is_internal_ai_base_url(base_url):
            raise RuntimeError("AI 配置不完整")
        metric_label = str(metric.get("label") or metric_key)[:120]
        body = {
            "model": model,
            "messages": [
                {"role": "system", "content": "只输出四行简体中文。第一行以战略指标｜开头，用一句不超过45字的话给出面向决策的竞争判断，不复述单个数据值，句末不要句号或英文句点；并由你从公司、竞争动作、趋势拐点或胜负判断中选出1—3个最值得决策者关注的短语，每个2—10字，仅在该短语两侧加【】用于视觉强调，不包裹标点或整句。其后三行每行35—70字，依次以竞争格局｜、公司定位｜、业务含义｜开头。四行必须基于同一组输入证据判断趋势、位置和业务意义；保留必要比较符；不得补数、使用Markdown或引用外部知识。若输入包含reported_value、reported_unit和fx_local_per_usd，比较值已按同期年度平均汇率统一为美元；必须说明换算口径，不得把换算值称为公司原始披露。若多家公司的原生口径标明共建共享且数值相同，必须说明这是同一共享网络口径，不得表述为各自拥有或将数值相加。"},
                {"role": "user", "content": f"{metric_label}\n公司\t年\t比较符\t值\t单位\t原始值\t原币单位\t本币/美元年均汇率\n{table}{fx_context}\n原生口径\n{definitions}"},
            ],
            "temperature": 0.1,
            # The current internal V4 gateway may still emit hidden reasoning even
            # when both supported non-thinking switches are present.  Production
            # readback showed that 1,800 tokens could still end after reasoning
            # only, so reserve enough headroom for the required final four lines;
            # the final-output gate below remains strict.
            "max_tokens": 4096,
            "chat_template_kwargs": {"enable_thinking": False},
            "stream": stream_callback is not None,
        }
        from cmhk.ai.ai_response_compat import deepseek_nonthinking_parameters
        body.update(config.get("extra_parameters") or {})
        body = deepseek_nonthinking_parameters(body)
        # Per-feature completion headroom is a correctness gate.  A smaller global
        # extra_parameters.max_tokens previously overrode this value and let hidden
        # reasoning consume the whole budget, leaving no user-visible final answer.
        body["max_tokens"] = 4096
        request = app.urllib.request.Request(
            f"{base_url}/chat/completions",
            data=app.json.dumps(body, ensure_ascii=False).encode("utf-8"),
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            method="POST",
        )
        priority_token = app.set_internal_ai_priority("interactive")

        def emit_visible_delta(text: object) -> None:
            """Keep the browser visibly streaming even when the gateway batches text."""
            value = str(text or "")
            if not value or not stream_callback:
                return
            chunk_size = 14
            for offset in range(0, len(value), chunk_size):
                stream_callback({"type": "delta", "text": value[offset:offset + chunk_size]})
                # A small pacing interval prevents localhost/proxy coalescing from
                # turning several flushed SSE events into one browser paint.
                app.time.sleep(0.018)

        try:
            if stream_callback:
                stream_callback({"type": "status", "stage": "queue", "message": "请求已进入 AI 前台队列"})
            for attempt in range(2 if stream_callback else 1):
                content_parts: list[str] = []
                try:
                    with app.open_llm_request(
                        request,
                        timeout=90 if stream_callback else 60,
                        config=config,
                        requested_key=api_key,
                        model=model,
                        operation="competitor-insight",
                        wait_callback=(lambda remaining: stream_callback({
                            "type": "status", "stage": "queue",
                            "message": "AI 请求较多，本次洞察仍在排队，请稍候",
                        })) if stream_callback else None,
                    ) as response:
                        if stream_callback:
                            stream_callback({"type": "status", "stage": "generating", "message": "AI 已连接，正在生成结果"})
                            reasoning_started = False
                            non_sse_parts: list[bytes] = []
                            for raw_line in response:
                                line = raw_line.decode("utf-8", errors="replace").strip()
                                if not line.startswith("data:"):
                                    if line:
                                        non_sse_parts.append(raw_line)
                                    continue
                                payload_text = line.removeprefix("data:").strip()
                                if not payload_text or payload_text == "[DONE]":
                                    continue
                                try:
                                    event = app.json.loads(payload_text)
                                except app.json.JSONDecodeError:
                                    continue
                                delta = ((event.get("choices") or [{}])[0].get("delta") or {})
                                reasoning_delta = delta.get("reasoning_content")
                                if reasoning_delta and not reasoning_started:
                                    reasoning_started = True
                                    stream_callback({"type": "status", "stage": "reasoning", "message": "AI 正在分析所选数据"})
                                content_delta = delta.get("content")
                                if isinstance(content_delta, str) and content_delta:
                                    content_parts.append(content_delta)
                                    emit_visible_delta(content_delta)
                            if not content_parts and non_sse_parts:
                                # Some OpenAI-compatible gateways occasionally
                                # ignore stream=true and return one JSON response.
                                # Preserve the real response text, but never expose
                                # a non-streaming browser path.
                                result = app.json.loads(b"".join(non_sse_parts).decode("utf-8"))
                                from cmhk.ai.ai_response_compat import final_chat_message_text
                                complete_text = final_chat_message_text(result, operation="竞争指标AI洞察")
                                complete_text = app._competitor_insight_content(complete_text)
                                content_parts.append(complete_text)
                                emit_visible_delta(complete_text)
                            if not content_parts:
                                # The gateway can finish a nominal SSE response with
                                # reasoning-only deltas and no final content. Keep the
                                # browser on this SSE connection, fetch the final answer
                                # once without upstream streaming, then replay it as
                                # paced visible deltas. This replaces the removed browser
                                # fallback without bringing back one-shot rendering.
                                stream_callback(
                                    {
                                        "type": "status",
                                        "stage": "generating",
                                        "message": "AI 正在整理最终结果",
                                    }
                                )
                                fallback_body = dict(body)
                                fallback_body["stream"] = False
                                fallback_request = app.urllib.request.Request(
                                    f"{base_url}/chat/completions",
                                    data=app.json.dumps(fallback_body, ensure_ascii=False).encode("utf-8"),
                                    headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                                    method="POST",
                                )
                                with app.open_llm_request(
                                    fallback_request,
                                    timeout=60,
                                    config=config,
                                    requested_key=api_key,
                                    model=model,
                                    operation="competitor-insight",
                                ) as fallback_response:
                                    fallback_result = app.json.loads(fallback_response.read().decode("utf-8"))
                                from cmhk.ai.ai_response_compat import final_chat_message_text
                                complete_text = final_chat_message_text(
                                    fallback_result,
                                    operation="竞争指标AI洞察",
                                )
                                complete_text = app._competitor_insight_content(complete_text)
                                content_parts.append(complete_text)
                                emit_visible_delta(complete_text)
                            raw_content = "".join(content_parts)
                        else:
                            result = app.json.loads(response.read().decode("utf-8"))
                            from cmhk.ai.ai_response_compat import final_chat_message_text
                            raw_content = final_chat_message_text(result, operation="竞争指标AI洞察")
                    break
                except (app.urllib.error.HTTPError, app.urllib.error.URLError, TimeoutError) as exc:
                    if isinstance(exc, app.AIQueueBusy):
                        raise
                    retryable_http = not isinstance(exc, app.urllib.error.HTTPError) or exc.code in {429, 500, 502, 503, 504}
                    if attempt == 0 and stream_callback and not content_parts and retryable_http:
                        app.logging.warning("competitor insight upstream interrupted before content; retrying once: %s", exc)
                        stream_callback({"type": "status", "stage": "queue", "message": "AI 连接波动，正在自动续接"})
                        continue
                    raise
        finally:
            app.reset_internal_ai_priority(priority_token)
        insight = app._competitor_insight_content(raw_content)
        strategic_indicator, strategic_highlights = app._parse_competitor_strategic_signal(insight)
        if not strategic_indicator:
            raise RuntimeError("AI 未返回战略指标")
        insights = app._parse_competitor_insight_items(insight)
        return {
            "requestId": request_id,
            "strategicIndicator": strategic_indicator,
            "strategicHighlights": strategic_highlights,
            "insight": insight,
            "insights": insights,
            "model": model,
        }

    publish(app, generate_competitor_insight)

    def transcribe_chat_audio(payload: dict) -> dict:
        data_url = str(payload.get("audio") or "").strip()
        match = app.re.fullmatch(
            r"data:(audio/(?:webm|mp4|mpeg|mpga|m4a|x-m4a|wav|x-wav))(?:;codecs=[^;,]+)?;base64,([A-Za-z0-9+/=\s]+)",
            data_url,
            flags=app.re.I,
        )
        if not match:
            raise ValueError("只支持 WebM、M4A、MP3 或 WAV 语音")
        try:
            raw = app.base64.b64decode(app.re.sub(r"\s+", "", match.group(2)), validate=True)
        except Exception as exc:
            raise ValueError("语音数据格式无效") from exc
        if not raw:
            raise ValueError("没有录到可识别的语音")
        if len(raw) > app.CHAT_AUDIO_MAX_BYTES:
            raise ValueError("单次语音不能超过 20 MB")

        mime_type = match.group(1).lower()
        extension = app.CHAT_AUDIO_MIME_EXTENSIONS.get(mime_type)
        if not extension:
            raise ValueError("不支持当前录音格式")
        try:
            converted = app.subprocess.run(
                [
                    app.os.environ.get("CMHK_FFMPEG_BIN") or "ffmpeg",
                    "-hide_banner",
                    "-loglevel",
                    "error",
                    "-i",
                    "pipe:0",
                    "-vn",
                    "-ac",
                    "1",
                    "-ar",
                    "16000",
                    "-c:a",
                    "pcm_s16le",
                    "-f",
                    "wav",
                    "pipe:1",
                ],
                input=raw,
                stdout=app.subprocess.PIPE,
                stderr=app.subprocess.PIPE,
                timeout=20,
                check=False,
            )
        except FileNotFoundError as exc:
            raise ValueError("服务器音频解码组件未就绪，请联系管理员安装 FFmpeg") from exc
        except app.subprocess.TimeoutExpired as exc:
            raise ValueError("录音解码超时，请缩短录音后重试") from exc
        if converted.returncode != 0 or len(converted.stdout) <= 44:
            raise ValueError("录音格式无法解码，请重新录音")
        raw = converted.stdout
        mime_type = "audio/wav"
        extension = "wav"

        config = app.load_ai_config(include_key=True)
        base_url = str(config.get("base_url") or "").strip().rstrip("/")
        api_key = str(config.get("api_key") or "").strip()
        if not app.is_internal_ai_base_url(base_url) or not api_key:
            raise ValueError("AI 模型配置不完整")

        boundary = f"----CMHKVoice{app.uuid.uuid4().hex}"
        line_break = b"\r\n"
        body = bytearray()
        for name, value in (("model", app.CHAT_STT_MODEL), ("language", "zh")):
            body.extend(f"--{boundary}".encode("ascii") + line_break)
            body.extend(f'Content-Disposition: form-data; name="{name}"'.encode("ascii") + line_break + line_break)
            body.extend(str(value).encode("utf-8") + line_break)
        body.extend(f"--{boundary}".encode("ascii") + line_break)
        body.extend(
            f'Content-Disposition: form-data; name="file"; filename="voice.{extension}"'.encode("ascii")
            + line_break
        )
        body.extend(f"Content-Type: {mime_type}".encode("ascii") + line_break + line_break)
        body.extend(raw + line_break)
        body.extend(f"--{boundary}--".encode("ascii") + line_break)

        request = app.urllib.request.Request(
            f"{base_url}/audio/transcriptions",
            data=bytes(body),
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": f"multipart/form-data; boundary={boundary}",
                "Accept": "application/json",
            },
            method="POST",
        )
        with app.open_llm_request(
            request,
            timeout=90,
            config=config,
            requested_key=api_key,
            model=app.CHAT_STT_MODEL,
            operation="chat-audio-transcription",
        ) as response:
            result = app.json.loads(response.read().decode("utf-8"))
        transcript = str(result.get("text") or result.get("transcript") or "").strip()
        if not transcript:
            raise ValueError("语音模型没有识别出文字，请靠近麦克风后重试")
        if transcript.rstrip("。！？!?，, ").strip() in {"嗯", "呃", "啊", "唔"}:
            raise ValueError("只识别到很短的语气词，请确认麦克风输入后靠近说话并重试")
        return {"text": transcript, "model": app.CHAT_STT_MODEL}

    publish(app, transcribe_chat_audio)
