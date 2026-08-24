from __future__ import annotations

import csv
import json
import os
import re
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit, urlunsplit

from ai_config import INTERNAL_AI_BASE_URL, load_ai_config
from ai_rate_limit import wait_for_internal_ai_slot
from cmhk.data.source_identity import canonical_source_document_identity, is_derived_value


ROOT = Path(__file__).resolve().parents[2]
AGENT_KNOWLEDGE_ROOT = ROOT / "agent_knowledge"
AGENT_KNOWLEDGE_ALLOWED_SUFFIXES = {".md", ".txt", ".json", ".csv", ".tsv"}
AGENT_KNOWLEDGE_SKIP_NAMES = {".DS_Store"}
DEFAULT_CONTEXT_TOKEN_BUDGET = int(os.environ.get("CMHK_RAG_CONTEXT_TOKEN_BUDGET", "9000"))
MAX_CHUNK_TOKENS = int(os.environ.get("CMHK_RAG_MAX_CHUNK_TOKENS", "1400"))
TOKEN_HEADROOM = int(os.environ.get("CMHK_RAG_TOKEN_HEADROOM", "1200"))


def _normalized_source_url(value: Any) -> str:
    raw = str(value or "").strip()
    if not re.match(r"^https?://", raw, re.IGNORECASE):
        return ""
    parts = urlsplit(raw)
    return urlunsplit((parts.scheme.lower(), parts.netloc.lower(), parts.path, parts.query, ""))


def _strict_source_document_count(
    row: dict[str, Any],
    *,
    source_registry_path: Path | None = None,
) -> int:
    """Count underlying documents, deduplicating mirrors when metadata permits."""
    primary_urls = {
        url
        for field in ["official_source_url", "primary_source_url", "来源URL"]
        if (url := _normalized_source_url(row.get(field)))
    }
    documents: set[str] = set()
    try:
        sources = json.loads(str(row.get("verification_sources") or "[]"))
    except Exception:
        sources = []
    if not isinstance(sources, list):
        sources = []
    registry: dict[str, dict[str, Any]] = {}
    if source_registry_path and source_registry_path.exists():
        try:
            payload = json.loads(source_registry_path.read_text(encoding="utf-8"))
            items = payload.get("sources", []) if isinstance(payload, dict) else payload
            registry = {
                str(item.get("source_id") or item.get("id")): item
                for item in items
                if isinstance(item, dict)
            }
        except Exception:
            registry = {}
    source_urls: set[str] = set()
    for source in sources:
        item = source if isinstance(source, dict) else registry.get(str(source), {})
        candidate = item.get("url") if isinstance(item, dict) else None
        if url := _normalized_source_url(candidate):
            source_urls.add(url)
        if isinstance(item, dict):
            if identity := canonical_source_document_identity(item, fallback_url=str(candidate or "")):
                documents.add(identity)
    for url in primary_urls - source_urls:
        documents.add(f"url:{url}")
    return len(documents)


def _strict_three_source_text(count: int) -> str:
    status = "three_distinct_sources_verified" if count >= 3 else "below_three_source_threshold"
    return f"distinct_source_document_count={count}; triple_source_status={status}"


def _strict_three_source_row_text(row: dict[str, Any], count: int) -> str:
    """Describe evidence without certifying missing or derived values."""
    value_fields = [field for field in ("official_value", "standardized_value", "value") if field in row]
    has_value = any(str(row.get(field) or "").strip() for field in value_fields) if value_fields else True
    if not has_value:
        return "distinct_source_document_count=0; triple_source_status=not_applicable_missing_value"
    if is_derived_value(row):
        return f"distinct_source_document_count={count}; triple_source_status=derived_not_directly_disclosed"
    return _strict_three_source_text(count)


def _token_encoder(model: str | None = None):
    try:
        import tiktoken  # type: ignore

        if model:
            try:
                return tiktoken.encoding_for_model(model)
            except Exception:
                pass
        return tiktoken.get_encoding("o200k_base")
    except Exception:
        return None


def estimate_tokens(text: str, model: str | None = None) -> int:
    text = text or ""
    encoder = _token_encoder(model)
    if encoder is not None:
        try:
            return len(encoder.encode(text))
        except Exception:
            pass
    ascii_chars = sum(1 for char in text if ord(char) < 128)
    non_ascii_chars = len(text) - ascii_chars
    return max(1, int(ascii_chars / 4) + int(non_ascii_chars * 0.9))


def _compress_chunk_text(text: str, max_tokens: int = MAX_CHUNK_TOKENS, model: str | None = None) -> tuple[str, bool]:
    if estimate_tokens(text, model=model) <= max_tokens:
        return text, False
    lines = [re.sub(r"\s+", " ", line).strip() for line in (text or "").splitlines()]
    priority_terms = [
        "subject=",
        "period=",
        "metric_key=",
        "official_value=",
        "official_unit=",
        "verification_status=",
        "verification_count=",
        "official_source",
        "source_gap",
        "official_conflict",
        "official_match",
        "forecast",
        "prediction",
        "coverage",
        "row_count",
        "数据集",
        "来源",
        "审计",
        "预测",
        "覆盖",
    ]
    selected: list[str] = []
    for line in lines:
        if any(term.lower() in line.lower() for term in priority_terms):
            selected.append(line)
        if estimate_tokens("\n".join(selected), model=model) >= max_tokens:
            break
    if not selected:
        selected = lines[:12]
    compressed = "\n".join(selected)
    while estimate_tokens(compressed, model=model) > max_tokens and len(compressed) > 200:
        compressed = compressed[: int(len(compressed) * 0.82)].rstrip()
    return compressed + "\n[上下文已按 token 预算压缩，保留主体、期间、数值、来源和审计状态优先字段。]", True


def build_context_package(
    chunks: list[dict[str, Any]],
    *,
    token_budget: int = DEFAULT_CONTEXT_TOKEN_BUDGET,
    model: str | None = None,
) -> dict[str, Any]:
    retained: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    total_tokens = 0
    for index, chunk in enumerate(chunks, 1):
        source = str(chunk.get("source") or "")
        raw_text = str(chunk.get("text") or "")
        text, compressed = _compress_chunk_text(raw_text, model=model)
        rendered = f"[来源 {len(retained) + 1}: {source}]\n{text}"
        tokens = estimate_tokens(rendered, model=model)
        if total_tokens + tokens > token_budget:
            skipped.append({"source": source, "reason": "context_token_budget_exceeded", "token_estimate": tokens})
            continue
        next_chunk = dict(chunk)
        next_chunk["text"] = text
        next_chunk["token_estimate"] = tokens
        next_chunk["compressed"] = compressed
        retained.append(next_chunk)
        total_tokens += tokens
    context = "\n\n".join(
        f"[来源 {i + 1}: {chunk['source']}]\n{chunk['text']}" for i, chunk in enumerate(retained)
    )
    return {
        "context": context,
        "chunks": retained,
        "audit": {
            "token_budget": token_budget,
            "token_estimate": total_tokens,
            "headroom": TOKEN_HEADROOM,
            "input_chunks": len(chunks),
            "retained_chunks": len(retained),
            "skipped_chunks": len(skipped),
            "compressed_chunks": sum(1 for chunk in retained if chunk.get("compressed")),
            "skipped": skipped[:10],
            "token_counter": "tiktoken" if _token_encoder(model) is not None else "heuristic",
        },
    }


def _read_text(path: Path, limit: int = 60000) -> str:
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8", errors="ignore")[:limit]


def _read_json(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def _tokens(text: str) -> set[str]:
    tokens = {
        item.lower()
        for item in re.findall(r"[A-Za-z0-9_-]{2,}", text or "")
    }
    for span in re.findall(r"[\u4e00-\u9fff]+", text or ""):
        if len(span) == 1:
            continue
        tokens.add(span)
        for width in range(2, min(4, len(span)) + 1):
            tokens.update(span[index : index + width] for index in range(len(span) - width + 1))
    return tokens


def _latest_period_score(text: str) -> int:
    scores: list[int] = []
    for quarter, year in re.findall(r"\bQ([1-4])\s+(20\d{2})\b", text or "", flags=re.IGNORECASE):
        scores.append(int(year) * 4 + int(quarter))
    for year, quarter in re.findall(r"\b(20\d{2})\s*Q([1-4])\b", text or "", flags=re.IGNORECASE):
        scores.append(int(year) * 4 + int(quarter))
    for year, quarter in re.findall(r"\bFY\s*(20\d{2})\s+Q([1-4])\b", text or "", flags=re.IGNORECASE):
        scores.append(int(year) * 4 + int(quarter))
    for half, year in re.findall(r"\bH([12])\s+(20\d{2})\b", text or "", flags=re.IGNORECASE):
        scores.append(int(year) * 2 + int(half))
    for year, half in re.findall(r"\b(20\d{2})\s*H([12])\b", text or "", flags=re.IGNORECASE):
        scores.append(int(year) * 2 + int(half))
    return max(scores) if scores else 0


def _local_ref(source: str) -> str:
    if source in {"weekly_report.docx", "weekly_report_from_word_template.docx"}:
        return f"/outputs/{source}"
    return f"/references/{source}"


def _is_allowed_knowledge_file(path: Path) -> bool:
    if path.name in AGENT_KNOWLEDGE_SKIP_NAMES:
        return False
    if path.name.startswith("."):
        return False
    if path.suffix.lower() not in AGENT_KNOWLEDGE_ALLOWED_SUFFIXES:
        return False
    return path.is_file()


def _knowledge_dataset_id(folder: Path) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "-", folder.name).strip("-") or folder.name


def _knowledge_manifest(folder: Path) -> dict[str, Any]:
    manifest = _read_json(folder / "manifest.json")
    dataset_id = str(manifest.get("id") or _knowledge_dataset_id(folder)).strip()
    title = str(manifest.get("title") or folder.name).strip()
    summary = str(manifest.get("summary") or manifest.get("description") or "").strip()
    tags = manifest.get("tags") if isinstance(manifest.get("tags"), list) else []
    keywords = manifest.get("keywords") if isinstance(manifest.get("keywords"), list) else []
    entrypoints = manifest.get("entrypoints") if isinstance(manifest.get("entrypoints"), list) else []
    include_datasets = manifest.get("include_datasets") if isinstance(manifest.get("include_datasets"), list) else []
    source_type = str(manifest.get("source_type") or manifest.get("sourceType") or "local").strip()
    scope = str(manifest.get("scope") or "").strip()
    updated_at = str(manifest.get("updated_at") or manifest.get("updatedAt") or "").strip()
    raw_quality = manifest.get("quality") or manifest.get("quality_note") or ""
    if isinstance(raw_quality, dict):
        quality = json.dumps(
            {
                key: raw_quality.get(key)
                for key in (
                    "status", "row_count", "parsed_count", "current_count", "historical_count",
                    "source_gap_count", "unresolved_source_gap_count", "verification_backlog_count",
                    "multi_verified_count", "verification_followup",
                )
                if raw_quality.get(key) not in (None, "", [], {})
            },
            ensure_ascii=False,
        )
    else:
        quality = str(raw_quality).strip()
    visibility = str(manifest.get("visibility") or "").strip().lower()
    superseded_by = str(manifest.get("superseded_by") or manifest.get("supersededBy") or "").strip()
    default_load = bool(manifest.get("default_load") or manifest.get("defaultLoad"))
    rag_prefer_parent_entrypoints = bool(manifest.get("rag_prefer_parent_entrypoints"))
    return {
        "id": dataset_id,
        "title": title,
        "summary": summary,
        "tags": [str(item).strip() for item in tags if str(item).strip()],
        "keywords": [str(item).strip() for item in keywords if str(item).strip()],
        "entrypoints": [str(item).strip() for item in entrypoints if str(item).strip()],
        "include_datasets": [str(item).strip() for item in include_datasets if str(item).strip()],
        "source_type": source_type,
        "scope": scope,
        "updated_at": updated_at,
        "quality": quality,
        "visibility": visibility,
        "superseded_by": superseded_by,
        "default_load": default_load,
        "rag_prefer_parent_entrypoints": rag_prefer_parent_entrypoints,
        "folder": folder.relative_to(ROOT).as_posix(),
        "manifest_path": (folder / "manifest.json").relative_to(ROOT).as_posix() if (folder / "manifest.json").exists() else "",
    }


def list_knowledge_datasets(dataset_ids: set[str] | None = None) -> list[dict[str, Any]]:
    datasets: list[dict[str, Any]] = []
    if not AGENT_KNOWLEDGE_ROOT.exists():
        return datasets
    for folder in sorted(AGENT_KNOWLEDGE_ROOT.iterdir()):
        if not folder.is_dir() or folder.name.startswith("."):
            continue
        manifest = _knowledge_manifest(folder)
        visibility = manifest.get("visibility")
        # Superseded and archived packages are audit history, never selectable
        # retrieval sources. Hidden packages may still be loaded explicitly by
        # a visible parent dataset or as a backend support dataset.
        if visibility in {"superseded", "archived"}:
            continue
        if dataset_ids is None and visibility == "hidden":
            continue
        if dataset_ids is not None and manifest["id"] not in dataset_ids and folder.name not in dataset_ids:
            continue
        files = []
        for path in sorted(folder.rglob("*")):
            if not _is_allowed_knowledge_file(path):
                continue
            rel = path.relative_to(ROOT).as_posix()
            files.append(
                {
                    "path": rel,
                    "name": path.name,
                    "url": _local_ref(rel),
                    "size": path.stat().st_size,
                    "entrypoint": path.name in set(manifest.get("entrypoints") or []) or rel in set(manifest.get("entrypoints") or []),
                }
            )
        include_ids = {str(item).strip() for item in manifest.get("include_datasets") or [] if str(item).strip()}
        if include_ids:
            child_paths = {item["path"] for item in files}
            for child_dataset in list_knowledge_datasets(dataset_ids=include_ids):
                for item in child_dataset.get("files", []):
                    if item.get("path") in child_paths:
                        continue
                    child_paths.add(item.get("path"))
                    files.append(dict(item))
        if not files and not manifest.get("manifest_path"):
            continue
        manifest["files"] = files
        datasets.append(manifest)
    return datasets


def default_background_dataset_ids() -> set[str]:
    """Hidden operational datasets that should be available without UI exposure."""
    ids: set[str] = set()
    if not AGENT_KNOWLEDGE_ROOT.exists():
        return ids
    for folder in sorted(AGENT_KNOWLEDGE_ROOT.iterdir()):
        if not folder.is_dir() or folder.name.startswith("."):
            continue
        manifest = _knowledge_manifest(folder)
        if manifest.get("default_load"):
            ids.add(str(manifest.get("id") or folder.name))
    return ids


def resolve_dataset_ids(dataset_ids: set[str] | None) -> set[str] | None:
    """Resolve stale selectable IDs to active packages without loading history."""
    if dataset_ids is None:
        return None
    manifests: dict[str, dict[str, Any]] = {}
    if AGENT_KNOWLEDGE_ROOT.exists():
        for folder in sorted(AGENT_KNOWLEDGE_ROOT.iterdir()):
            if not folder.is_dir() or folder.name.startswith("."):
                continue
            manifest = _knowledge_manifest(folder)
            manifests[str(manifest.get("id") or folder.name)] = manifest
            manifests.setdefault(folder.name, manifest)

    resolved: set[str] = set()
    for requested_id in dataset_ids:
        current = manifests.get(str(requested_id))
        visited: set[str] = set()
        while current and current.get("visibility") == "superseded":
            current_id = str(current.get("id") or "")
            if current_id in visited:
                current = None
                break
            visited.add(current_id)
            successor_id = str(current.get("superseded_by") or "").strip()
            current = manifests.get(successor_id) if successor_id else None
        if not current or current.get("visibility") == "archived":
            continue
        resolved.add(str(current.get("id") or requested_id))
    return resolved


def effective_dataset_ids(dataset_ids: set[str] | None = None) -> set[str] | None:
    background_ids = default_background_dataset_ids()
    if dataset_ids is None:
        return None
    return set(resolve_dataset_ids(dataset_ids) or set()) | background_ids


def _chunk_text(source: str, text: str, max_chars: int = 1200) -> list[dict[str, Any]]:
    chunks: list[dict[str, Any]] = []
    buffer: list[str] = []
    size = 0
    for line in text.splitlines():
        line = re.sub(r"\s+", " ", line).strip()
        if not line:
            continue
        if size + len(line) > max_chars and buffer:
            chunks.append({"source": source, "text": "\n".join(buffer), "links": [{"label": source, "url": _local_ref(source)}]})
            buffer = []
            size = 0
        buffer.append(line)
        size += len(line)
    if buffer:
        chunks.append({"source": source, "text": "\n".join(buffer), "links": [{"label": source, "url": _local_ref(source)}]})
    return chunks


def _table_file_chunks(path: Path, source: str, *, max_rows_per_chunk: int = 8) -> list[dict[str, Any]]:
    delimiter = "\t" if path.suffix.lower() == ".tsv" else ","
    try:
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            rows = list(csv.DictReader(handle, delimiter=delimiter))
    except Exception:
        return _chunk_text(source, _read_text(path, limit=240000), max_chars=1600)
    chunks: list[dict[str, Any]] = []
    for start in range(0, len(rows), max_rows_per_chunk):
        part = rows[start : start + max_rows_per_chunk]
        lines = []
        for row in part:
            useful = {key: value for key, value in row.items() if str(value or "").strip()}
            lines.append(json.dumps(useful, ensure_ascii=False, sort_keys=True))
        if lines:
            chunks.append(
                {
                    "source": source,
                    "text": "\n".join(lines),
                    "links": [{"label": source, "url": _local_ref(source)}],
                }
            )
    return chunks


def _result_chunks() -> list[dict[str, Any]]:
    chunks: list[dict[str, Any]] = []
    for path in sorted((ROOT / "results").glob("row_*.json"), key=lambda p: int(p.stem.split("_")[1])):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        extracted = data.get("extracted") or {}
        summary = {
            "row": data.get("row"),
            "status": data.get("status"),
            "object": data.get("object"),
            "entities": data.get("entities"),
            "selected_fields": data.get("selected_fields"),
            "extracted": extracted,
            "missing_fields": data.get("missing_fields"),
            "source_urls": data.get("source_urls"),
        }
        links = [{"label": path.name, "url": _local_ref(path.name)}]
        for index, url in enumerate(data.get("source_urls") or [], 1):
            if isinstance(url, str) and url.startswith(("http://", "https://")):
                links.append({"label": f"原始来源 {index}", "url": url})
        chunks.append({"source": path.name, "text": json.dumps(summary, ensure_ascii=False)[:1600], "links": links})
    return chunks


def _agent_knowledge_chunks(dataset_ids: set[str] | None = None) -> list[dict[str, Any]]:
    chunks: list[dict[str, Any]] = []
    if not AGENT_KNOWLEDGE_ROOT.exists():
        return chunks

    seen_dataset_ids: set[str] = set()

    def add_dataset_chunks(dataset: dict[str, Any]) -> None:
        dataset_key = str(dataset.get("id") or dataset.get("folder") or "")
        if dataset_key in seen_dataset_ids:
            return
        seen_dataset_ids.add(dataset_key)
        folder = ROOT / dataset["folder"]
        manifest_text = json.dumps(
            {
                "dataset": dataset["title"],
                "id": dataset["id"],
                "summary": dataset.get("summary"),
                "scope": dataset.get("scope"),
                "source_type": dataset.get("source_type"),
                "tags": dataset.get("tags"),
                "keywords": dataset.get("keywords"),
                "entrypoints": dataset.get("entrypoints"),
                "include_datasets": dataset.get("include_datasets"),
                "quality": dataset.get("quality"),
                "files": [item["path"] for item in dataset.get("files", [])],
            },
            ensure_ascii=False,
            indent=2,
        )
        manifest_source = dataset.get("manifest_path") or f"{dataset['folder']}/manifest.json"
        chunks.extend(_chunk_text(manifest_source, manifest_text, max_chars=1600))
        entrypoints = set(dataset.get("entrypoints") or [])
        ordered_files = sorted(
            [ROOT / item["path"] for item in dataset.get("files", [])],
            key=lambda p: (0 if p.name in entrypoints or p.relative_to(ROOT).as_posix() in entrypoints else 1, p.name),
        )
        include_ids = {str(item).strip() for item in dataset.get("include_datasets") or [] if str(item).strip()}
        parent_only = bool(include_ids and dataset.get("rag_prefer_parent_entrypoints"))
        files_to_index = [
            path for path in ordered_files
            if not parent_only or (
                path.parent == folder
                and (path.name in entrypoints or path.relative_to(ROOT).as_posix() in entrypoints)
            )
        ]
        for path in files_to_index:
            if not _is_allowed_knowledge_file(path):
                continue
            source = path.relative_to(ROOT).as_posix()
            if path.suffix.lower() in {".csv", ".tsv"}:
                rows_per_chunk = 1 if dataset.get("id") in {"competitor_product_tariffs", "hk_competitor_product_tariffs", "hkt_product_tariffs"} else 8
                chunks.extend(_table_file_chunks(path, source, max_rows_per_chunk=rows_per_chunk))
                continue
            text = _read_text(path, limit=120000)
            if path.suffix.lower() == ".json":
                try:
                    text = json.dumps(json.loads(text), ensure_ascii=False, indent=2)
                except Exception:
                    pass
            chunks.extend(_chunk_text(source, text, max_chars=1600))
        if include_ids and not parent_only:
            for child_dataset in list_knowledge_datasets(dataset_ids=include_ids):
                add_dataset_chunks(child_dataset)

    datasets = list_knowledge_datasets(dataset_ids=dataset_ids)
    if dataset_ids is None:
        background_ids = default_background_dataset_ids()
        if background_ids:
            known_ids = {str(item.get("id") or "") for item in datasets}
            for dataset in list_knowledge_datasets(dataset_ids=background_ids):
                if str(dataset.get("id") or "") not in known_ids:
                    datasets.append(dataset)
    for dataset in datasets:
        add_dataset_chunks(dataset)
    return chunks


def build_rag_index(dataset_ids: set[str] | None = None) -> list[dict[str, Any]]:
    chunks: list[dict[str, Any]] = []
    for name in ["weekly_report.md", "final_audit.md", "coverage_report.tsv", "run_log.tsv"]:
        chunks.extend(_chunk_text(name, _read_text(ROOT / name)))
    chunks.extend(_agent_knowledge_chunks(dataset_ids=effective_dataset_ids(dataset_ids)))
    chunks.extend(_result_chunks())
    return chunks


def _selected_quarterly_metrics_csv(dataset_ids: set[str] | None = None) -> Path | None:
    candidates: list[tuple[str, float, Path]] = []
    if not AGENT_KNOWLEDGE_ROOT.exists():
        return None
    for folder in AGENT_KNOWLEDGE_ROOT.glob("quarterly_competitor_metrics_*"):
        if not folder.is_dir():
            continue
        manifest = _knowledge_manifest(folder)
        if manifest.get("visibility") in {"hidden", "superseded", "archived"}:
            continue
        if dataset_ids is not None and manifest["id"] not in dataset_ids and folder.name not in dataset_ids:
            continue
        csv_path = folder / "quarterly_metrics.csv"
        if csv_path.exists():
            candidates.append(
                (str(manifest.get("updated_at") or ""), csv_path.stat().st_mtime, csv_path)
            )
    if not candidates:
        return None
    return max(candidates, key=lambda item: (item[0], item[1]))[2]


def _global_operator_exact_metric_chunks(
    question: str,
    dataset_ids: set[str] | None = None,
) -> list[dict[str, Any]]:
    dataset_id = "global_top5_operators_2016_2025"
    if dataset_ids is not None and dataset_id not in dataset_ids:
        return []

    csv_path = AGENT_KNOWLEDGE_ROOT / dataset_id / "annual_metrics.csv"
    if not csv_path.exists():
        return []

    normalized = re.sub(r"\s+", " ", question or "").strip()
    lowered = normalized.lower()
    if any(token in lowered for token in ["q1", "q2", "q3", "q4", "h1", "h2", "季度", "半年度"]):
        return []

    subject_aliases = {
        "china_mobile": ["中国移动", "中移动", "china mobile"],
        "china_telecom": ["中国电信", "china telecom"],
        "china_unicom": ["中国联通", "china unicom"],
        "china_broadnet": ["中国广电", "中广电", "china broadnet", "china broadcasting network", "cbn"],
        "bharti_airtel": ["bharti airtel", "airtel"],
        "reliance_jio": ["reliance jio", "jio"],
    }
    matched_subjects = {
        operator_id
        for operator_id, aliases in subject_aliases.items()
        if any(alias in lowered for alias in aliases)
    }

    metric_aliases = {
        "total_customers": ["集团总客户", "总客户数", "总客户", "客户数", "total customers", "total customer base"],
        "mobile_subscribers": ["移动用户数", "移动用户", "移动客户数", "移动客户", "mobile subscribers", "mobile customers"],
        "4g_subscribers": ["4g用户", "4g subscribers"],
        "5g_package_subscribers": ["5g套餐用户", "5g package subscribers"],
        "5g_network_subscribers": ["5g网络用户", "5g用户", "5g users", "5g network subscribers"],
        "fixed_broadband_subscribers": ["固定宽带用户", "固网宽带用户", "宽带用户", "fixed broadband"],
        "fixed_broadband_access_ports": ["固网宽带接入端口", "固定网络宽带接入端口", "宽带接入端口", "broadband access ports"],
        "integrated_broadband_network_customers": ["融合宽带网络客户", "融合宽带客户", "integrated broadband network customers"],
        "gigabit_broadband_customers": ["千兆宽带客户", "千兆宽带用户", "gigabit broadband customers"],
        "connected_homes": ["连接家庭", "已连接家庭", "connected homes", "connected premises"],
        "churn": ["用户流失率", "月度流失率", "流失率", "monthly churn", "churn"],
        "mobile_arpu": ["移动arpu", "mobile arpu", "arpu"],
        "broadband_arpu": ["宽带arpu", "broadband arpu"],
        "household_customer_blended_arpu": ["家庭客户综合arpu", "家庭综合arpu", "household customer blended arpu"],
        "integrated_package_arpu": ["融合套餐arpu", "融合arpu", "integrated package arpu"],
        "mobile_dou": ["移动dou", "户均流量", "月户均流量", "data consumption per user", "dou"],
        "total_data_traffic": ["总数据流量", "年度数据流量", "数据流量", "total data traffic"],
        "handset_data_traffic": ["手机上网流量", "手机数据流量", "手机流量", "handset data traffic"],
        "iot_connections": ["物联网连接", "物联网终端连接", "物联网卡连接", "物联网卡客户", "iot connections", "iot connection"],
        "mobile_broadband_integration_rate": ["移动宽带融合率", "移宽融合率", "mobile broadband integration rate"],
        "government_enterprise_customers": ["政企客户", "government enterprise customers"],
        "households_gigabit_coverage": ["千兆覆盖家庭", "千兆家庭覆盖", "households gigabit coverage"],
        "5g_network_penetration": ["5g网络用户渗透率", "5g网络渗透率", "5g渗透率", "5g network subscriber penetration", "5g network penetration"],
        "gigabit_broadband_penetration": ["千兆宽带渗透率", "gigabit broadband penetration"],
        "total_connectivity_subscribers": ["连接用户总规模", "总连接用户", "total connectivity subscribers"],
        "integrated_subscriber_penetration": ["融合用户渗透率", "integrated subscriber penetration"],
        "mobile_population_coverage": ["移动人口覆盖率", "mobile population coverage"],
        "4g_population_coverage": ["4g人口覆盖率", "4g网络人口覆盖率", "4g population coverage"],
        "5g_a_deployment_cities": ["5g-a城市", "5g-a部署城市", "5g a cities"],
        "cloud_ai_product_users": ["云ai产品用户", "cloud-ai users", "cloud ai product users"],
        "intelligent_compute_capacity": ["智算规模", "智算能力", "intelligent compute capacity"],
        "ten_g_pon_ports": ["10g pon端口", "10g pon ports"],
        "urban_gigabit_coverage": ["城市千兆覆盖率", "城市千兆宽带覆盖率", "urban gigabit coverage"],
        "network_towers": ["网络铁塔", "铁塔数", "network towers"],
        "mobile_broadband_base_stations": ["移动宽带基站", "mobile broadband base stations"],
        "total_base_stations": ["基站总数", "全部基站", "total base stations"],
        "4g_base_stations": ["4g基站", "4g base stations"],
        "5g_base_stations": ["5g基站", "5g base stations", "5g sites", "5g cells"],
        "shared_4g_5g_base_stations": ["共享4g/5g基站", "共享基站", "可共享基站", "shared 4g/5g base stations"],
        "spectrum_holdings": ["频谱持有量", "频谱资源", "频谱规模", "spectrum holdings", "spectrum footprint"],
        "cable_tv_actual_users": ["有线电视实际用户", "有线电视用户", "cable tv users", "cable television users"],
        "two_way_digital_cable_tv_users": ["双向数字电视用户", "双向数字有线用户", "two-way digital cable"],
        "hd_uhd_cable_tv_users": ["高清超高清有线用户", "高清和超高清用户", "hd uhd cable users"],
        "uhd_cable_tv_users": ["超高清有线用户", "uhd cable users"],
        "cable_network_industry_revenue": ["有线电视网络收入", "有线网络行业收入", "cable network industry revenue"],
        "revenue": ["营业收入", "总收入", "revenue"],
        "value_of_sales_and_services": ["销售及服务价值", "value of sales and services"],
        "revenue_from_operations": ["经营收入", "revenue from operations"],
        "ebitda": ["ebitda"],
        "ebit": ["ebit"],
        "earnings_before_tax": ["税前利润", "profit before tax", "earnings before tax"],
        "net_profit": ["净利润", "net profit", "net income"],
        "capex": ["资本开支", "capex"],
        "net_debt": ["净债务", "net debt"],
        "shareholders_equity": ["股东权益", "shareholders equity", "shareholder's equity"],
    }
    matched_metrics = {
        metric_key
        for metric_key, aliases in metric_aliases.items()
        if any(alias in lowered for alias in aliases)
    }
    if "broadband_arpu" in matched_metrics or "household_customer_blended_arpu" in matched_metrics:
        matched_metrics.discard("mobile_arpu")
    if "integrated_package_arpu" in matched_metrics:
        matched_metrics.discard("mobile_arpu")
        matched_metrics.discard("broadband_arpu")
    if "5g_network_penetration" in matched_metrics:
        matched_metrics.discard("5g_network_subscribers")
    if "revenue_from_operations" in matched_metrics or "value_of_sales_and_services" in matched_metrics:
        matched_metrics.discard("revenue")
    if "ebitda" in matched_metrics:
        matched_metrics.discard("ebit")

    # Keep subject-to-metric associations in compound questions instead of
    # returning every metric for every named operator.
    requested_pairs: set[tuple[str, str]] = set()
    requested_years_by_pair: dict[tuple[str, str], set[int]] = {}
    for sentence in re.split(r"[。！？\n]", lowered):
        carried_subjects: set[str] = set()
        carried_years: set[int] = set()
        for clause in re.split(r"[,，、;；]", sentence):
            clause_subjects = {
                operator_id
                for operator_id, aliases in subject_aliases.items()
                if any(alias in clause for alias in aliases)
            }
            if clause_subjects:
                carried_subjects = set(clause_subjects)
            elif carried_subjects:
                clause_subjects = set(carried_subjects)
            elif len(matched_subjects) == 1:
                clause_subjects = set(matched_subjects)
            clause_metrics = {
                metric_key
                for metric_key, aliases in metric_aliases.items()
                if any(alias in clause for alias in aliases)
            }
            if "broadband_arpu" in clause_metrics or "household_customer_blended_arpu" in clause_metrics or "integrated_package_arpu" in clause_metrics:
                clause_metrics.discard("mobile_arpu")
            if "integrated_package_arpu" in clause_metrics:
                clause_metrics.discard("broadband_arpu")
            if "5g_network_penetration" in clause_metrics:
                clause_metrics.discard("5g_network_subscribers")
            clause_years = {
                int(value)
                for value in re.findall(r"(?<!\d)(20(?:1[6-9]|2[0-5]))(?!\d)", clause)
            }
            for start_text, end_text in re.findall(
                r"(?<!\d)(20(?:1[6-9]|2[0-5]))\s*(?:至|到|[-–—])\s*(20(?:1[6-9]|2[0-5]))(?!\d)",
                clause,
            ):
                start_year, end_year = int(start_text), int(end_text)
                if start_year <= end_year:
                    clause_years.update(range(start_year, end_year + 1))
            if clause_years:
                carried_years = set(clause_years)
            elif carried_years:
                clause_years = set(carried_years)
            for subject in clause_subjects:
                for metric in clause_metrics:
                    pair = (subject, metric)
                    requested_pairs.add(pair)
                    if clause_years:
                        requested_years_by_pair.setdefault(pair, set()).update(clause_years)

    years = {
        int(value)
        for value in re.findall(r"(?<!\d)(20(?:1[6-9]|2[0-5]))(?!\d)", normalized)
    }
    for start_text, end_text in re.findall(
        r"(?<!\d)(20(?:1[6-9]|2[0-5]))\s*(?:至|到|[-–—])\s*(20(?:1[6-9]|2[0-5]))(?!\d)",
        normalized,
    ):
        start_year, end_year = int(start_text), int(end_text)
        if start_year <= end_year:
            years.update(range(start_year, end_year + 1))
    if not matched_subjects or not matched_metrics:
        return []

    try:
        with csv_path.open("r", encoding="utf-8-sig", newline="") as handle:
            rows = list(csv.DictReader(handle))
    except Exception:
        return []

    filtered = []
    for row in rows:
        if (row.get("operator_id") or "").strip() not in matched_subjects:
            continue
        if (row.get("metric_key") or "").strip() not in matched_metrics:
            continue
        if requested_pairs and (
            (row.get("operator_id") or "").strip(),
            (row.get("metric_key") or "").strip(),
        ) not in requested_pairs:
            continue
        if not str(row.get("official_value") or "").strip() and (row.get("operator_id") or "").strip() != "china_broadnet":
            continue
        try:
            row_year = int((row.get("year") or "0").strip())
        except ValueError:
            continue
        pair = (
            (row.get("operator_id") or "").strip(),
            (row.get("metric_key") or "").strip(),
        )
        pair_years = requested_years_by_pair.get(pair)
        if pair_years and row_year not in pair_years:
            continue
        if years and row_year not in years:
            continue
        filtered.append(row)

    source = csv_path.relative_to(ROOT).as_posix()
    registry_path = AGENT_KNOWLEDGE_ROOT / dataset_id / "sources.json"
    chunks: list[dict[str, Any]] = []
    for row in filtered[:24]:
        strict_sources = _strict_source_document_count(row, source_registry_path=registry_path)
        value_text = (
            f"{row.get('official_value')} {row.get('unit')}"
            if str(row.get("official_value") or "").strip()
            else "未披露（source_gap_confirmed / not_applicable_precommercial）"
        )
        text = (
            f"精确年度运营商指标行：operator={row.get('operator')}; operator_id={row.get('operator_id')}; "
            f"period={row.get('period')}; period_end={row.get('period_end')}; metric_key={row.get('metric_key')}; "
            f"metric_zh={row.get('metric_zh')}; official_value={value_text}; "
            f"comparator={row.get('comparator')}; scope={row.get('scope')}; basis={row.get('basis')}; "
            f"verification_status={row.get('verification_status')}; verification_count={row.get('verification_count')}; "
            f"{_strict_three_source_row_text(row, strict_sources)}; "
            f"primary_source_url={row.get('primary_source_url')}; quality_note={row.get('quality_note')}."
            "如果值为未披露，只能回答未披露或商用前不适用，不能当作0、行业汇总或估算值。"
        )
        chunks.append({"source": source, "text": text, "links": [{"label": source, "url": _local_ref(source)}]})
    return chunks


def _local_hk_operator_exact_metric_chunks(
    question: str,
    dataset_ids: set[str] | None = None,
) -> list[dict[str, Any]]:
    dataset_id = "local_hk_operator_operating_metrics_2016_2025"
    if dataset_ids is not None and dataset_id not in dataset_ids:
        return []
    csv_path = AGENT_KNOWLEDGE_ROOT / dataset_id / "annual_metrics.csv"
    if not csv_path.exists():
        return []

    normalized = re.sub(r"\s+", " ", question or "").strip()
    lowered = normalized.lower()
    if any(token in lowered for token in ["q1", "q2", "q3", "q4", "h1", "h2", "季度", "半年度"]):
        return []
    subject_aliases = {
        "hkt": ["hkt", "香港電訊", "csl", "1o1o"],
        "three_hk": ["3hk", "3 hong kong", "和記電訊香港", "和記電訊", "香港三"],
        "smartone": ["smartone", "數碼通", "数码通"],
        "hkbn": ["hkbn", "香港寬頻", "香港宽频"],
        "hgc": ["hgc", "環球全域電訊", "环球全域电讯"],
        "icable": ["i-cable", "icable", "i cable", "有線寬頻", "有线宽频"],
    }
    matched_subjects = {key for key, aliases in subject_aliases.items() if any(alias in lowered for alias in aliases)}
    metric_aliases = {
        "total_customers": ["總客戶", "总客户", "total customers", "customer base"],
        "mobile_postpaid_customers": ["後付客戶", "后付客户", "postpaid customers", "post-paid customers"],
        "mobile_prepaid_customers": ["預付客戶", "预付客户", "prepaid customers", "pre-paid customers"],
        "5g_customers": ["5g客戶", "5g客户", "5g用戶", "5g用户", "5g customers"],
        "5g_penetration": ["5g滲透率", "5g渗透率", "5g penetration"],
        "consumer_broadband_customers": ["住宅寬頻", "住宅宽频", "寬頻客戶", "宽频客户", "broadband customers", "broadband subscriptions"],
        "ftth_connections": ["ftth", "光纖入戶", "光纤入户"],
        "homes_passed_or_connected": ["homes passed", "homes connected", "家庭覆蓋", "家庭接入", "網絡覆蓋", "网络覆盖"],
        "commercial_buildings_covered": ["商業樓宇", "商业楼宇", "commercial buildings"],
        "residential_arpu": ["住宅arpu", "residential arpu"],
        "residential_arph": ["arph", "residential arph"],
        "mobile_postpaid_arpu": ["後付arpu", "后付arpu", "postpaid arpu", "post-paid arpu", "arpu"],
        "mobile_postpaid_exit_arpu": ["期末arpu", "exit arpu"],
        "mobile_postpaid_net_arpu": ["淨arpu", "净arpu", "net arpu"],
        "mobile_postpaid_net_ampu": ["淨ampu", "净ampu", "net ampu", "ampu"],
        "mobile_postpaid_churn": ["後付流失率", "后付流失率", "churn"],
        "pay_tv_customers": ["收費電視客戶", "收费电视客户", "pay tv customers", "pay-tv customers"],
        "telephony_customers": ["固網電話客戶", "固网电话客户", "telephony customers"],
        "5g_population_coverage": ["5g人口覆蓋", "5g population coverage"],
        "mobile_data_dou": ["移動dou", "移动dou", "戶均流量", "户均流量", "data usage per user"],
        "annual_mobile_data_traffic": ["年度移動數據流量", "年度移动数据流量", "總流量", "总流量", "annual mobile data traffic"],
        "total_base_stations": ["基站總數", "基站总数", "total base stations"],
        "5g_base_stations": ["5g基站數", "5g基站数", "5g base stations", "5g sites"],
        "5g_base_station_expansion": ["5g基站擴展", "5g基站扩展", "5g base station expansion"],
        "free_tv_population_coverage": ["免費電視覆蓋", "免费电视覆盖", "free tv coverage", "free-to-air coverage"],
        "mtr_stations_5g_enhanced": ["地鐵站", "地铁站", "mtr stations"],
        "residential_2gbps_plus_customers": ["住宅2gbps", "residential 2gbps"],
        "enterprise_2gbps_plus_customers": ["企業2gbps", "企业2gbps", "enterprise 2gbps", "gigafast"],
        "enterprise_core_churn": ["企業流失率", "企业流失率", "enterprise churn"],
        "5g_home_broadband_revenue_growth": ["5g家庭寬頻收入", "5g家庭宽频收入", "5g home broadband revenue"],
        "5g_home_broadband_ebitda_growth": ["5g家庭寬頻ebitda", "5g家庭宽频ebitda", "5g home broadband ebitda"],
    }
    matched_metrics = {key for key, aliases in metric_aliases.items() if any(alias in lowered for alias in aliases)}
    if "5g_penetration" in matched_metrics:
        matched_metrics.discard("5g_customers")
    if "mobile_postpaid_exit_arpu" in matched_metrics or "mobile_postpaid_net_arpu" in matched_metrics:
        matched_metrics.discard("mobile_postpaid_arpu")
    if "residential_arpu" in matched_metrics:
        matched_metrics.discard("mobile_postpaid_arpu")
    if "5g_home_broadband_ebitda_growth" in matched_metrics:
        matched_metrics.discard("5g_home_broadband_revenue_growth")
    years = {int(value) for value in re.findall(r"(?<!\d)(20(?:1[6-9]|2[0-5]))(?!\d)", normalized)}
    if not matched_subjects or not matched_metrics:
        return []

    try:
        with csv_path.open("r", encoding="utf-8-sig", newline="") as handle:
            rows = list(csv.DictReader(handle))
    except Exception:
        return []
    filtered = []
    for row in rows:
        if (row.get("operator_id") or "").strip() not in matched_subjects:
            continue
        if (row.get("metric_key") or "").strip() not in matched_metrics:
            continue
        try:
            row_year = int((row.get("year") or "0").strip())
        except ValueError:
            continue
        if years and row_year not in years:
            continue
        filtered.append(row)

    source = csv_path.relative_to(ROOT).as_posix()
    registry_path = AGENT_KNOWLEDGE_ROOT / dataset_id / "sources.json"
    chunks: list[dict[str, Any]] = []
    for row in filtered[:30]:
        strict_sources = _strict_source_document_count(row, source_registry_path=registry_path)
        value_text = f"{row.get('official_value')} {row.get('unit')}" if row.get("official_value") else "未披露（source_gap_confirmed）"
        text = (
            f"香港本地運營商精確年度指標行：operator={row.get('operator')}; operator_id={row.get('operator_id')}; "
            f"period={row.get('period')}; period_end={row.get('period_end')}; metric_key={row.get('metric_key')}; "
            f"metric_zh={row.get('metric_zh')}; official_value={value_text}; comparator={row.get('comparator')}; "
            f"scope={row.get('scope')}; basis={row.get('basis')}; verification_status={row.get('verification_status')}; "
            f"verification_count={row.get('verification_count')}; {_strict_three_source_row_text(row, strict_sources)}; "
            f"primary_source_url={row.get('primary_source_url')}; "
            f"quality_note={row.get('quality_note')}.如果狀態為source_gap_confirmed，只能回答未披露，不能當作0或推測。"
        )
        chunks.append({"source": source, "text": text, "links": [{"label": source, "url": _local_ref(source)}]})
    return chunks


def _product_tariff_exact_chunks(
    question: str,
    dataset_ids: set[str] | None = None,
) -> list[dict[str, Any]]:
    relevant_dataset_ids = {
        "competitor_product_tariffs",
        "hkt_product_tariffs",
        "hk_competitor_product_tariffs",
    }
    if dataset_ids is not None and not (set(dataset_ids) & relevant_dataset_ids):
        return []

    normalized = re.sub(r"\s+", " ", question or "").strip()
    lowered = normalized.lower()
    tariff_intent = any(
        term in lowered
        for term in [
            "套餐",
            "資費",
            "资费",
            "月费",
            "月費",
            "合约",
            "合約",
            "数据量",
            "數據量",
            "宽频",
            "寬頻",
            "broadband",
            "tariff",
            "service plan",
            "monthly fee",
        ]
    )
    gap_intent = any(
        term in lowered
        for term in [
            "source gap",
            "source-gap",
            "来源缺口",
            "來源缺口",
            "数据缺口",
            "資料缺口",
            "单源",
            "單源",
            "待复核",
            "待覆核",
            "为什么没有",
            "為什麼沒有",
        ]
    )
    if not tariff_intent or gap_intent:
        return []

    csv_path = (
        AGENT_KNOWLEDGE_ROOT
        / "competitor_product_tariffs"
        / "product_tariffs_formal_agent_records.csv"
    )
    if not csv_path.exists():
        return []
    try:
        with csv_path.open("r", encoding="utf-8-sig", newline="") as handle:
            rows = [
                row
                for row in csv.DictReader(handle)
                if (row.get("record_class") or "").strip() == "formal_product_tariff"
            ]
    except Exception:
        return []

    brand_aliases = {
        "HKT Enterprise": ["hkt enterprise", "hkt 企业", "hkt企業"],
        "HKT SME": ["hkt sme"],
        "3HK / Hutchison": ["3hk", "hutchison", "和记", "和記"],
        "SmarTone": ["smartone", "数码通", "數碼通"],
        "NETVIGATOR": ["netvigator", "网上行", "網上行"],
        "i-CABLE": ["i-cable", "icable", "有线宽频", "有線寬頻"],
        "HKBN": ["hkbn", "香港宽频", "香港寬頻"],
        "HGC": ["hgc", "环球全域", "環球全域"],
        "1O1O": ["1o1o", "1010"],
        "csl": ["csl"],
        "HKT": ["hkt"],
    }
    dataset_rows = list(rows)
    dataset_brand_names = [
        brand
        for brand in brand_aliases
        if any((row.get("品牌") or "").strip() == brand for row in dataset_rows)
    ]
    dataset_current_records = sum(
        1
        for row in dataset_rows
        if (row.get("时间类型") or "").strip() == "当前"
    )
    matched_brands: list[str] = []
    remaining_for_hkt = lowered
    for brand, aliases in brand_aliases.items():
        if any(alias in lowered for alias in aliases):
            matched_brands.append(brand)
            if brand != "HKT":
                for alias in aliases:
                    remaining_for_hkt = remaining_for_hkt.replace(alias, "")
    if "HKT" in matched_brands and "hkt" not in remaining_for_hkt:
        matched_brands.remove("HKT")
    if re.search(
        r"全库|全資料庫|全数据库|所有品牌|全部品牌|所有竞对|全部竞对|"
        r"所有競對|全部競對|主要竞对|主要競對|cross[- ]brand|all brands",
        lowered,
        re.IGNORECASE,
    ):
        matched_brands = []
    if matched_brands:
        rows = [row for row in rows if (row.get("品牌") or "").strip() in matched_brands]

    years = set(re.findall(r"\b(?:19|20)\d{2}\b", normalized))
    history_intent = bool(
        years
        or any(
            term in lowered
            for term in ["历史", "歷史", "历年", "歷年", "过去", "過去", "往年", "趋势", "趨勢", "变化", "變化", "historical", "history", "trend"]
        )
    )
    if years:
        rows = [
            row
            for row in rows
            if any(
                year in " ".join(
                    [
                        row.get("期间") or "",
                        row.get("抓取/生效时间") or "",
                        row.get("快照ID") or "",
                    ]
                )
                for year in years
            )
        ]
    elif not history_intent:
        rows = [row for row in rows if (row.get("时间类型") or "").strip() == "当前"]

    wants_broadband = any(
        term in lowered
        for term in ["宽频", "寬頻", "宽带", "寬帶", "broadband", "光纤", "光纖", "家居网络", "家居網絡"]
    )
    wants_mobile = any(
        term in lowered
        for term in ["移动", "移動", "流动", "流動", "手机", "手機", "mobile", "5g", "4g", "sim"]
    )

    def product_kind(row: dict[str, str]) -> str:
        category = (row.get("产品类别") or "").lower()
        if (row.get("宽频速度_Mbps") or "").strip():
            return "宽频"
        if any(term in category for term in ["home_5g_broadband", "5g home broadband", "家居5g", "5g家居"]):
            return "宽频"
        if any(term in category for term in ["mobile", "5g", "4g", "3g", "sim", "roaming", "流动", "流動"]):
            return "移动"
        if any(term in category for term in ["broadband", "宽频", "寬頻", "宽带", "寬帶", "fibre", "fiber"]):
            return "宽频"
        if any(term in (row.get("网络代际") or "").lower() for term in ["5g", "4g", "3g", "mobile"]):
            return "移动"
        text = " ".join(
            [
                row.get("产品系列") or "",
                row.get("套餐名称") or "",
            ]
        ).lower()
        if any(term in text for term in ["mobile", "5g", "4g", "3g", "sim", "roaming", "流动", "流動"]):
            return "移动"
        if any(term in text for term in ["broadband", "宽频", "寬頻", "宽带", "寬帶", "fibre", "fiber"]):
            return "宽频"
        return "其他"

    wanted_kinds = {
        kind
        for kind, wanted in [("宽频", wants_broadband), ("移动", wants_mobile)]
        if wanted
    }
    if wanted_kinds:
        rows = [row for row in rows if product_kind(row) in wanted_kinds]
    if not rows:
        return []

    def row_recency(row: dict[str, str]) -> tuple[str, str, str]:
        return (
            row.get("抓取/生效时间") or "",
            row.get("期间") or "",
            row.get("记录键") or "",
        )

    rows.sort(key=row_recency, reverse=True)
    by_brand: dict[str, list[dict[str, str]]] = {}
    for row in rows:
        brand = (row.get("品牌") or "未标注品牌").strip()
        by_brand.setdefault(brand, []).append(row)

    source = csv_path.relative_to(ROOT).as_posix()
    local_link = [{"label": source, "url": _local_ref(source)}]
    brand_order = {brand: index for index, brand in enumerate(brand_aliases)}
    brand_names = sorted(by_brand, key=lambda brand: (brand_order.get(brand, 999), brand.lower()))

    def compact_value(row: dict[str, str], *fields: str) -> str:
        for field in fields:
            value = re.sub(r"\s+", " ", (row.get(field) or "").strip())
            if value:
                return value
        return "-"

    def numeric_values(brand_rows: list[dict[str, str]], *fields: str) -> list[float]:
        values: list[float] = []
        for row in brand_rows:
            raw = compact_value(row, *fields)
            try:
                values.append(float(raw.replace(",", "")))
            except (TypeError, ValueError):
                continue
        return values

    def summary_line(brand: str, brand_rows: list[dict[str, str]]) -> str:
        periods = sorted({compact_value(row, "期间") for row in brand_rows if compact_value(row, "期间") != "-"})
        monthly_values = numeric_values(brand_rows, "月费_HKD", "平均月费_HKD")
        categories = sorted({product_kind(row) for row in brand_rows})
        coverage = f"{periods[0]}至{periods[-1]}" if len(periods) > 1 else (periods[0] if periods else "未标注")
        price_range = (
            f"HK${min(monthly_values):g}-HK${max(monthly_values):g}"
            if monthly_values
            else "无统一月费"
        )
        summary = (
            f"品牌汇总：brand={brand}; matched_records={len(brand_rows)}; "
            f"kinds={','.join(categories)}; period_coverage={coverage}; monthly_fee_range={price_range}."
        )
        if history_intent and matched_brands:
            annual_values: dict[str, list[float]] = {}
            for row in brand_rows:
                period_text = " ".join(
                    [
                        row.get("期间") or "",
                        row.get("抓取/生效时间") or "",
                        row.get("快照ID") or "",
                    ]
                )
                year_match = re.search(r"\b(?:19|20)\d{2}\b", period_text)
                if not year_match:
                    continue
                values = numeric_values([row], "月费_HKD", "平均月费_HKD")
                if values:
                    annual_values.setdefault(year_match.group(0), []).extend(values)
            if annual_values:
                ranges = [
                    f"{year}:HK${min(values):g}-HK${max(values):g}"
                    for year, values in sorted(annual_values.items())
                ]
                summary += f" annual_monthly_ranges={'; '.join(ranges)}."
        return summary

    def row_line(row: dict[str, str]) -> str:
        price = compact_value(row, "月费_HKD", "平均月费_HKD", "公开价格_HKD")
        strict_sources = _strict_source_document_count(row)
        return (
            f"正式套餐：brand={compact_value(row, '品牌')}; time={compact_value(row, '时间类型')}; "
            f"period={compact_value(row, '期间')}; kind={product_kind(row)}; "
            f"category={compact_value(row, '产品类别')}; plan={compact_value(row, '套餐名称')}; "
            f"monthly_fee_HKD={price}; local_data_GB={compact_value(row, '本地数据_GB')}; "
            f"broadband_speed_Mbps={compact_value(row, '宽频速度_Mbps')}; "
            f"contract_months={compact_value(row, '合约月数')}; "
            f"verification={compact_value(row, '核验状态')}; {_strict_three_source_row_text(row, strict_sources)}; "
            f"source_id={compact_value(row, '来源ID')}."
        )

    chunks: list[dict[str, Any]] = []
    if len(matched_brands) != 1:
        def representative_row(brand_rows: list[dict[str, str]], kind: str) -> dict[str, str] | None:
            candidates = [row for row in brand_rows if product_kind(row) == kind]
            if not candidates:
                return None

            def score(row: dict[str, str]) -> tuple[int, tuple[str, str, str]]:
                name = f"{row.get('产品类别') or ''} {row.get('套餐名称') or ''}".lower()
                value = 0
                if compact_value(row, "月费_HKD", "平均月费_HKD") != "-":
                    value += 4
                if compact_value(row, "合约月数") != "-":
                    value += 3
                if kind == "移动" and compact_value(row, "本地数据_GB") != "-":
                    value += 4
                if kind == "宽频" and compact_value(row, "宽频速度_Mbps") != "-":
                    value += 4
                if any(term in name for term in ["consumer", "home_", "service plan", "monthly plan"]):
                    value += 2
                if any(term in name for term in ["add-on", "addon", "附加", "行政费", "roaming", "漫游"]):
                    value -= 3
                return value, row_recency(row)

            return max(candidates, key=score)

        overview_lines = [
            (
                "跨品牌当前正式套餐总览：本块用于回答多品牌比较；"
                f"query_matched_records={len(rows)}; query_matched_brands={len(by_brand)}。"
                "每个 mobile/broadband 值均为该品牌当前正式记录中的代表行；"
                "missing 表示本次正式当前子集中没有该产品类型，不代表其他历史期间也没有。"
            )
        ]
        for brand in brand_names:
            brand_rows = by_brand[brand]
            values: list[str] = []
            for kind, label in [("移动", "mobile"), ("宽频", "broadband")]:
                row = representative_row(brand_rows, kind)
                if row is None:
                    values.append(f"{label}=missing")
                    continue
                plan = compact_value(row, "套餐名称")
                if len(plan) > 86:
                    plan = f"{plan[:83]}..."
                values.append(
                    f"{label}=[plan={plan}; fee_HKD={compact_value(row, '月费_HKD', '平均月费_HKD')}; "
                    f"data_GB={compact_value(row, '本地数据_GB')}; "
                    f"speed_Mbps={compact_value(row, '宽频速度_Mbps')}; "
                    f"contract_months={compact_value(row, '合约月数')}; "
                    f"source_id={compact_value(row, '来源ID')}]"
                )
            overview_lines.append(
                f"brand={brand}; matched_records={len(brand_rows)}; {'; '.join(values)}."
            )
        chunks.append(
            {
                "source": source,
                "text": (
                    "产品资费结构化检索结果（跨品牌总览）。"
                    f"查询结果块：chunk_brands={','.join(brand_names)}。"
                    "数据集全局覆盖锚点："
                    f"dataset_total_formal_records={len(dataset_rows)}; "
                    f"dataset_current_formal_records={dataset_current_records}; "
                    f"dataset_total_brands={len(dataset_brand_names)}; "
                    f"dataset_brands={','.join(dataset_brand_names)}。"
                    f"本次查询范围：query_scope={'named_brand_comparison' if matched_brands else 'cross_brand'}。"
                    "不得把任一单品牌或单产品类型子查询概括成整个数据库覆盖。\n"
                    + "\n".join(overview_lines)
                ),
                "links": local_link,
            }
        )
    brands_per_chunk = 1 if matched_brands else 3
    sample_per_brand = 10 if matched_brands else 2
    for start in range(0, len(brand_names), brands_per_chunk):
        group = brand_names[start : start + brands_per_chunk]
        lines = [
            (
                f"查询结果块：chunk_brands={','.join(group)}。"
                "数据集全局覆盖锚点："
                f"dataset_total_formal_records={len(dataset_rows)}; "
                f"dataset_current_formal_records={dataset_current_records}; "
                f"dataset_total_brands={len(dataset_brand_names)}; "
                f"dataset_brands={','.join(dataset_brand_names)}。"
                f"本次查询范围：query_scope={'brand_subset' if matched_brands else 'cross_brand'}; "
                f"query_matched_records={len(rows)}; query_matched_brands={len(by_brand)}。"
                "查询结果是全库在当前关键词、品牌、产品类型和期间条件下的命中子集；"
                "不得因本次子集未出现某品牌，就推断整个数据库没有该品牌。"
                "判断数据库整体覆盖只能使用本行的全局覆盖锚点。"
            ),
            (
                "产品资费结构化检索结果：仅使用 record_class=formal_product_tariff；"
                f"matched_records={len(rows)}; matched_brands={len(by_brand)}; "
                f"scope={'历史/指定年份' if history_intent else '当前'}。"
                "以下汇总由全部命中记录计算，明细为跨品牌紧凑代表行，不含 source_gap 或待复核候选。"
            )
        ]
        for brand in group:
            brand_rows = by_brand[brand]
            lines.append(summary_line(brand, brand_rows))
            seen_signatures: set[tuple[str, ...]] = set()
            seen_years: set[str] = set()
            emitted = 0
            for row in brand_rows:
                if history_intent:
                    period_text = " ".join(
                        [
                            row.get("期间") or "",
                            row.get("抓取/生效时间") or "",
                            row.get("快照ID") or "",
                        ]
                    )
                    year_match = re.search(r"\b(?:19|20)\d{2}\b", period_text)
                    year = year_match.group(0) if year_match else compact_value(row, "期间")
                    if year in seen_years:
                        continue
                    seen_years.add(year)
                signature = (
                    product_kind(row),
                    compact_value(row, "产品类别"),
                    compact_value(row, "月费_HKD", "平均月费_HKD", "公开价格_HKD"),
                    compact_value(row, "本地数据_GB"),
                    compact_value(row, "宽频速度_Mbps"),
                )
                if signature in seen_signatures:
                    continue
                seen_signatures.add(signature)
                lines.append(row_line(row))
                emitted += 1
                if emitted >= sample_per_brand:
                    break
        chunks.append({"source": source, "text": "\n".join(lines), "links": local_link})
    return chunks


def _quarterly_exact_metric_chunks(question: str, dataset_ids: set[str] | None = None) -> list[dict[str, Any]]:
    csv_path = _selected_quarterly_metrics_csv(dataset_ids=dataset_ids)
    if csv_path is None:
        return []

    normalized_question = re.sub(r"\s+", " ", question or "")
    periods = {
        match.group(1).upper().replace(" ", " ")
        for match in re.finditer(r"\b((?:Q[1-4]|H[12])\s*20\d{2})\b", normalized_question, re.IGNORECASE)
    }
    periods.update(
        {
            f"Q{match.group(2)} {match.group(1)}"
            for match in re.finditer(r"\b(20\d{2})\s*Q([1-4])\b", normalized_question, re.IGNORECASE)
        }
    )
    periods.update(
        {
            f"H{match.group(2)} {match.group(1)}"
            for match in re.finditer(r"\b(20\d{2})\s*H([12])\b", normalized_question, re.IGNORECASE)
        }
    )
    periods.update(
        {
            re.sub(r"\s+", " ", match.group(1).upper())
            for match in re.finditer(r"\b(FY\s*20\d{2}\s*Q[1-4])\b", normalized_question, re.IGNORECASE)
        }
    )
    periods.update(
        {
            re.sub(r"\s+", " ", match.group(1).upper().replace("FY", "FY "))
            for match in re.finditer(r"\b(FY\s*20\d{2})\b", normalized_question, re.IGNORECASE)
        }
    )
    periods.update(
        {
            f"H1 {match.group(1)}"
            for match in re.finditer(r"(20\d{2})\s*年?\s*(?:上半年|中期|半年报)", normalized_question)
        }
    )
    periods.update(
        {
            f"H2 {match.group(1)}"
            for match in re.finditer(r"(20\d{2})\s*年?\s*下半年", normalized_question)
        }
    )
    chinese_quarters = {"一": "1", "二": "2", "三": "3", "四": "4", "1": "1", "2": "2", "3": "3", "4": "4"}
    periods.update(
        {
            f"Q{chinese_quarters[match.group(2)]} {match.group(1)}"
            for match in re.finditer(r"(20\d{2})\s*年?\s*第?([一二三四1234])季度", normalized_question)
        }
    )
    periods = {re.sub(r"\s+", " ", item) for item in periods}
    lowered_question = normalized_question.lower()
    annual_revenue_intent = bool(
        re.search(r"\bannual(?:-only| only)?\b[^.;,]{0,80}\brevenue\b", lowered_question)
        or re.search(r"\brevenue\b[^.;,]{0,80}\bannual(?:-only| only)?\b", lowered_question)
        or re.search(r"\bfy\s*20\d{2}\b[^.;,]{0,80}\brevenue\b", lowered_question)
        or re.search(r"\brevenue\b[^.;,]{0,80}\bfy\s*20\d{2}\b", lowered_question)
        or "年度收入" in normalized_question
    )
    disclosure_gap_intent = any(
        token in lowered_question
        for token in [
            "source gap",
            "source-gap",
            "no quarterly",
            "not disclosed quarterly",
            "quarterly disclosure status",
            "cloud_quarterly_disclosure_status",
            "quarterly_financial_disclosure_status",
            "披露缺口",
            "披露边界",
            "未披露季度",
            "无季度披露",
        ]
    )

    metric_aliases = {
        "ebitda_margin": ["EBITDA率", "EBITDA 率", "ebitda margin", "ebitda率"],
        "ebitda": ["EBITDA", "ebitda"],
        "revenue_growth_yoy": ["收入同比", "营收同比", "营业收入同比", "收入增长", "营收增长", "revenue growth", "revenue_growth_yoy", "yoy revenue", "YoY"],
        "service_revenue": ["服务收入", "主营业务收入", "通信服务收入", "service revenue", "service_revenue"],
        "revenue": ["营收", "收入", "营业收入", "operating revenue", "revenue"],
        "net_income": ["净利润", "归母利润", "股东应占", "profit attributable", "net profit", "net_income"],
        "capital_expenditures": ["资本开支", "capex", "CAPEX"],
        "free_cash_flow": ["自由现金流", "free cash flow", "FCF"],
        "operating_cash_flow": ["经营现金流", "operating cash flow"],
        "operating_income": ["营业利润", "经营利润", "经营亏损", "operating income", "loss from operations"],
        "adjusted_ebita": ["adjusted ebita", "adjusted_ebita", "经调整 ebita", "调整后 ebita"],
        "adjusted_ebita_growth_yoy": ["adjusted ebita growth", "adjusted_ebita_growth_yoy", "adjusted ebita yoy"],
        "operating_margin": ["经营利润率", "经营亏损率", "operating margin"],
        "gross_profit": ["毛利", "gross profit"],
        "cash_and_equivalents": ["现金及现金等价物", "期末现金", "现金及等价物", "现金和等价物", "cash and equivalents", "cash equivalents"],
        "total_assets": ["总资产", "total assets"],
        "total_debt": ["总债务", "债务", "total debt", "debt"],
        "cloud_revenue": ["云收入", "cloud revenue"],
        "cloud_revenue_growth_yoy": ["云收入同比", "cloud revenue growth", "cloud revenue yoy", "cloud_revenue_growth_yoy"],
        "cloud_quarterly_disclosure_status": [
            "cloud quarterly disclosure status",
            "cloud_quarterly_disclosure_status",
            "季度披露状态",
            "披露边界",
            "披露缺口",
            "source gap",
            "source-gap",
            "no quarterly",
            "not disclosed quarterly",
            "未披露季度",
            "无季度披露",
        ],
        "quarterly_financial_disclosure_status": [
            "quarterly financial disclosure status",
            "quarterly_financial_disclosure_status",
            "季度财务披露状态",
            "财务披露状态",
            "披露缺口",
            "披露边界",
            "未披露季度",
            "无季度披露",
            "source gap",
            "source-gap",
            "not estimate",
            "不得估算",
            "不要估算",
        ],
        "cloud_infrastructure_revenue": [
            "云基础设施收入",
            "cloud infrastructure revenue",
            "cloud infra revenue",
            "infrastructure cloud revenue",
            "oci revenue",
            "iaas revenue",
            "cloud_infrastructure_revenue",
        ],
        "cloud_infrastructure_revenue_growth_yoy": [
            "云基础设施收入同比",
            "cloud infrastructure revenue growth",
            "cloud infrastructure growth",
            "oci growth",
            "iaas growth",
            "cloud_infrastructure_revenue_growth_yoy",
        ],
        "cloud_application_revenue": [
            "云应用收入",
            "cloud application revenue",
            "cloud applications revenue",
            "saas revenue",
            "cloud_application_revenue",
        ],
        "cloud_application_revenue_growth_yoy": [
            "云应用收入同比",
            "cloud application revenue growth",
            "cloud applications growth",
            "saas growth",
            "cloud_application_revenue_growth_yoy",
        ],
        "azure_and_other_cloud_services_growth_yoy": [
            "Azure同比",
            "Azure 增长",
            "Azure growth",
            "Azure and other cloud services growth",
            "azure_and_other_cloud_services_growth_yoy",
            "cloud services growth",
        ],
        "fintech_business_services_revenue": [
            "fintech and business services revenue",
            "fintech business services revenue",
            "fbs revenue",
            "tencent fbs revenue",
            "金融科技及企业服务收入",
            "金融科技和企业服务收入",
            "fintech_business_services_revenue",
        ],
        "fintech_business_services_revenue_growth_yoy": [
            "fintech and business services revenue growth",
            "fintech business services growth",
            "fbs revenue growth",
            "tencent fbs growth",
            "金融科技及企业服务收入同比",
            "金融科技和企业服务收入同比",
            "fintech_business_services_revenue_growth_yoy",
        ],
    }
    metric_keys: set[str] = set()
    for key, aliases in metric_aliases.items():
        if any(alias.lower() in lowered_question for alias in aliases):
            metric_keys.add(key)
    if not disclosure_gap_intent and any(token in lowered_question for token in ["annual-only", "annual only"]):
        metric_keys.discard("cloud_quarterly_disclosure_status")
    if annual_revenue_intent:
        metric_keys.discard("cloud_quarterly_disclosure_status")
        metric_keys.add("revenue")
    if "revenue_growth_yoy" in metric_keys and any(token in lowered_question for token in ["同比", "增长", "growth", "yoy"]):
        metric_keys.discard("revenue")
    if "service_revenue" in metric_keys:
        metric_keys.discard("revenue")
    if "cloud_revenue_growth_yoy" in metric_keys:
        metric_keys.discard("cloud_revenue")
        metric_keys.discard("revenue")
    if "cloud_quarterly_disclosure_status" in metric_keys:
        metric_keys.discard("cloud_revenue")
        metric_keys.discard("revenue")
        metric_keys.discard("operating_income")
        metric_keys.discard("revenue_growth_yoy")
    if "quarterly_financial_disclosure_status" in metric_keys:
        metric_keys.discard("revenue")
        metric_keys.discard("service_revenue")
        metric_keys.discard("operating_income")
        metric_keys.discard("net_income")
        metric_keys.discard("ebitda")
        metric_keys.discard("ebitda_margin")
    if "cloud_infrastructure_revenue" in metric_keys or "cloud_infrastructure_revenue_growth_yoy" in metric_keys:
        metric_keys.discard("cloud_revenue")
        metric_keys.discard("revenue")
    if "cloud_application_revenue" in metric_keys or "cloud_application_revenue_growth_yoy" in metric_keys:
        metric_keys.discard("cloud_revenue")
        metric_keys.discard("revenue")
    if "azure_and_other_cloud_services_growth_yoy" in metric_keys and any(token in lowered_question for token in ["同比", "增长", "growth", "yoy"]):
        metric_keys.discard("revenue")
    if "fintech_business_services_revenue" in metric_keys or "fintech_business_services_revenue_growth_yoy" in metric_keys:
        metric_keys.discard("revenue")
    if "fintech_business_services_revenue_growth_yoy" in metric_keys and any(token in lowered_question for token in ["同比", "增长", "growth", "yoy"]):
        metric_keys.discard("fintech_business_services_revenue")
    if "ebitda_margin" in metric_keys and "ebitda" in metric_keys and "EBITDA率" in normalized_question:
        metric_keys.discard("ebitda")
    if "net_income" in metric_keys:
        metric_keys.discard("ebitda")
        metric_keys.discard("ebitda_margin")

    try:
        with csv_path.open("r", encoding="utf-8-sig", newline="") as handle:
            rows = list(csv.DictReader(handle))
    except Exception:
        return []

    subjects = {row.get("subject", "").strip() for row in rows if row.get("subject")}
    matched_subjects = {
        subject
        for subject in subjects
        if subject and (subject.lower() in lowered_question or subject.split(" / ")[0].lower() in lowered_question)
    }
    subject_aliases = {
        "中国移动": ["中移动", "China Mobile"],
        "中国电信": ["China Telecom"],
        "中国联通": ["China Unicom"],
        "中国广电": ["China Broadnet", "China Broadcasting Network", "CBN"],
        "中国铁塔": ["China Tower"],
        "Microsoft Azure / Intelligent Cloud": ["Azure", "Microsoft Intelligent Cloud", "微软云"],
        "Google Cloud": ["谷歌云"],
        "Alibaba Cloud": ["阿里云", "阿里 Cloud"],
        "Tencent Cloud / Tencent FBS proxy": ["腾讯云", "Tencent Cloud", "Tencent FBS", "FBS proxy", "FinTech and Business Services"],
        "Huawei Cloud / Cloud Computing": ["华为云", "Huawei Cloud"],
        "Oracle Cloud": ["甲骨文云"],
    }
    for subject, aliases in subject_aliases.items():
        if any(alias.lower() in lowered_question for alias in aliases):
            matched_subjects.add(subject)

    if not matched_subjects and not periods and not metric_keys:
        return []
    if metric_keys and not matched_subjects and not periods and not disclosure_gap_intent:
        return []

    latest_intent = any(
        key in lowered_question
        for key in ["最新", "最近", "latest", "recent", "current", "last quarter", "latest quarter"]
    )
    explicit_series_intent = any(
        key in lowered_question
        for key in [
            "趋势",
            "走势",
            "时间序列",
            "历年",
            "历史",
            "长期",
            "近年",
            "多年",
            "过去",
            "变化",
            "trend",
            "time series",
            "historical",
        ]
    ) or len(set(re.findall(r"\b20\d{2}\b", lowered_question))) >= 2
    series_intent = explicit_series_intent or (
        not periods and any(key in lowered_question for key in ["季度", "quarterly"])
    )

    filtered: list[dict[str, str]] = []
    for row in rows:
        subject = (row.get("subject") or "").strip()
        period = re.sub(r"\s+", " ", (row.get("period") or "").strip().upper())
        metric_key = (row.get("metric_key") or "").strip()
        if matched_subjects and subject not in matched_subjects:
            continue
        # A trend/range question needs the complete available series. Periods
        # named in the query are anchors or boundaries, not permission to hide
        # every other observation.
        if periods and not series_intent and period not in periods:
            continue
        if metric_keys and metric_key not in metric_keys:
            continue
        filtered.append(row)

    if latest_intent:
        filtered.sort(
            key=lambda row: _latest_period_score(f"{row.get('period', '')} {row.get('period_end', '')}"),
            reverse=True,
        )

    source = csv_path.relative_to(ROOT).as_posix()
    if series_intent:
        grouped: dict[tuple[str, str, str], list[dict[str, str]]] = {}
        for row in filtered:
            unit = (row.get("official_unit") or row.get("unit") or "").strip()
            key = (
                (row.get("subject") or "").strip(),
                (row.get("metric_key") or "").strip(),
                unit,
            )
            grouped.setdefault(key, []).append(row)

        series_chunks: list[dict[str, Any]] = []
        for (subject, metric_key, unit), group_rows in grouped.items():
            ordered = sorted(
                group_rows,
                key=lambda row: _latest_period_score(
                    f"{row.get('period', '')} {row.get('period_end', '')}"
                ),
            )
            points = []
            conflicts = []
            for row in ordered:
                period = (row.get("period") or "").strip()
                value = (row.get("official_value") or row.get("value") or "").strip()
                if period and value:
                    points.append(f"{period}={value}")
                if (row.get("verification_status") or "").strip() == "official_conflict":
                    conflicts.append(period)
            if not points:
                continue
            metric_zh = (ordered[0].get("metric_zh") or metric_key).strip()
            text = (
                f"完整季度时间序列：subject={subject}; metric_key={metric_key}; metric_zh={metric_zh}; "
                f"coverage={ordered[0].get('period')} 至 {ordered[-1].get('period')}; "
                f"points={len(points)}; unit={unit}; period_values={'; '.join(points)}. "
                "各期优先使用 official_value，缺失时使用 standardized_value。"
                f"如需画图，直接调用 render_quarterly_metric_chart(subject={subject!r}, "
                f"metric_key={metric_key!r})，无需手工重组数据。"
            )
            if conflicts:
                text += f" official_conflict_periods={', '.join(conflicts)}，这些期间应说明口径冲突。"
            series_chunks.append(
                {
                    "source": source,
                    "text": text,
                    "links": [{"label": source, "url": _local_ref(source)}],
                }
            )
        if series_chunks:
            return series_chunks

    chunks: list[dict[str, Any]] = []
    for row in filtered[:12]:
        official_value = (row.get("official_value") or "").strip()
        official_unit = (row.get("official_unit") or row.get("unit") or "").strip()
        standard_value = (row.get("value") or "").strip()
        verification_count = (row.get("verification_count") or "").strip()
        status = (row.get("verification_status") or "").strip()
        evidence = re.sub(r"\s+", " ", (row.get("official_evidence") or "").strip())
        note = re.sub(r"\s+", " ", (row.get("verification_note") or "").strip())
        strict_sources = _strict_source_document_count(row)
        text = (
            f"精确季度指标行：subject={row.get('subject')}; period={row.get('period')}; "
            f"metric_key={row.get('metric_key')}; metric_zh={row.get('metric_zh')}; grain={row.get('grain')}; "
            f"standardized_value={standard_value} {row.get('unit')}; official_value={official_value} {official_unit}; "
            f"verification_status={status}; verification_count={verification_count}; "
            f"{_strict_three_source_row_text(row, strict_sources)}; "
            f"official_source_label={row.get('official_source_label')}; official_source_url={row.get('official_source_url')}; "
            f"official_evidence={evidence}; verification_note={note}. "
            "回答时：只有 distinct_source_document_count>=3 才能称为已通过三来源核验；"
            "verification_count 只是旧证据条数，同一文档多个章节不能重复计源；"
            "若 verification_status=official_conflict，正式数值采用 official_value，并说明标准化表与官方披露冲突。"
        )
        chunks.append({"source": source, "text": text, "links": [{"label": source, "url": _local_ref(source)}]})
    return chunks


def retrieve_context(question: str, limit: int = 8, dataset_ids: set[str] | None = None) -> list[dict[str, Any]]:
    query_tokens = _tokens(question)
    core_metric_question = any(
        key in question
        for key in [
            "近三年",
            "过去三年",
            "三年",
            "趋势",
            "核心数据",
            "主要数据",
            "财务数据",
            "经营数据",
            "收入",
            "收益",
            "净利润",
            "毛利率",
            "EBITDA",
            "资本开支",
            "现金流",
            "同业",
            "对比",
        ]
    )
    quarterly_metric_question = any(
        key in question
        for key in [
            "季度",
            "季报",
            "一季报",
            "二季报",
            "三季报",
            "四季报",
            "Q1",
            "Q2",
            "Q3",
            "Q4",
            "q1",
            "q2",
            "q3",
            "q4",
            "H1",
            "H2",
            "h1",
            "h2",
            "半年度",
            "半年",
            "更小计量单位",
            "最近几个季度",
            "最新",
            "最近",
            "latest",
            "recent",
            "current",
        ]
    )
    latest_period_intent = any(
        key in question.lower()
        for key in ["最新", "最近", "latest", "recent", "current", "last quarter", "latest quarter"]
    )
    macro_intent = any(
        key.lower() in question.lower()
        for key in ["OFCA", "宏观", "政策", "渗透率", "频谱", "移动用户", "宽带", "Key Communications Statistics"]
    )
    exact_chunks = _product_tariff_exact_chunks(question, dataset_ids=dataset_ids)
    exact_chunks.extend(_global_operator_exact_metric_chunks(question, dataset_ids=dataset_ids))
    exact_chunks.extend(_local_hk_operator_exact_metric_chunks(question, dataset_ids=dataset_ids))
    exact_chunks.extend(_quarterly_exact_metric_chunks(question, dataset_ids=dataset_ids))
    if latest_period_intent:
        exact_chunks.sort(
            key=lambda chunk: _latest_period_score(chunk.get("text", "") + " " + chunk.get("source", "")),
            reverse=True,
        )
    scored: list[tuple[int, int, dict[str, Any]]] = []
    index_chunks = build_rag_index(dataset_ids=dataset_ids)
    for index, chunk in enumerate(index_chunks):
        searchable_text = chunk["text"] + " " + chunk["source"]
        chunk_tokens = _tokens(searchable_text)
        overlap = len(query_tokens & chunk_tokens)
        source_boost = 3 if chunk["source"] == "weekly_report.md" else 0
        if chunk["source"].startswith("agent_knowledge/"):
            source_boost += 4
            if macro_intent and "cmhk_macro_policy" in chunk["source"]:
                source_boost += 35
            if core_metric_question:
                source_boost += 10
            if quarterly_metric_question and "quarterly_competitor_metrics" in chunk["source"]:
                source_boost += 14
                if latest_period_intent:
                    source_boost += min(80, max(0, _latest_period_score(searchable_text) - 2016 * 4))
            elif quarterly_metric_question and any(name in chunk["source"] for name in ["core_company_metrics", "cloud_vendor_metrics"]):
                source_boost += 4
        if any(key in question for key in ["建议", "风险", "重点", "总结", "摘要", "周报"]):
            source_boost += 2 if chunk["source"] in {"weekly_report.md", "final_audit.md"} else 0
        score = overlap + source_boost
        if score > 0:
            scored.append((score, -index, chunk))
    scored.sort(reverse=True)
    if not scored:
        results = exact_chunks + index_chunks
    else:
        results = exact_chunks + [item[2] for item in scored]
    deduped: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for chunk in results:
        key = (chunk.get("source", ""), chunk.get("text", "")[:240])
        if key in seen:
            continue
        seen.add(key)
        deduped.append(chunk)
        if len(deduped) >= limit:
            break
    return deduped


def citation_markdown(chunks: list[dict[str, Any]], max_items: int = 20) -> str:
    lines: list[str] = []
    for i, chunk in enumerate(chunks):
        links = []
        for link in chunk.get("links", []):
            label = str(link.get("label") or "").strip()
            url = str(link.get("url") or "").strip()
            if label and url:
                links.append(f"[{label}]({url})")
        if links:
            lines.append(f"- [{i+1}] {'，'.join(links)}")
    return "\n".join(lines[:max_items])


def _extract_output_text(payload: dict[str, Any]) -> str:
    if isinstance(payload.get("output_text"), str):
        return payload["output_text"].strip()
    parts: list[str] = []
    for item in payload.get("output", []) or []:
        for content in item.get("content", []) or []:
            text = content.get("text")
            if isinstance(text, str):
                parts.append(text)
    return "\n".join(parts).strip()


def ask_llm_with_rag(question: str) -> dict[str, Any]:
    config = load_ai_config(include_key=True)
    api_key = str(config.get("api_key") or "").strip()
    if not api_key:
        return {
            "ok": False,
            "configured": False,
            "error": "未配置 API Key，无法调用真正的 LLM。请在页面右上角“AI 设置”里填写并保存。",
            "sources": [],
        }

    provider = str(config.get("provider") or "deepseek").lower()
    model = str(config.get("model") or "deepseek-v4")
    base_url = str(config.get("base_url") or INTERNAL_AI_BASE_URL).rstrip("/")
    chunks = retrieve_context(question, limit=14)
    context_package = build_context_package(chunks, model=model)
    chunks = context_package["chunks"]
    context = context_package["context"]
    system_prompt = (
        "你是中国移动战略部公开信息监测系统中的 RAG 助手。"
        "只能基于提供的本地周报、爬取结果和审计上下文回答；如果上下文不足，要明确说明。"
        "上下文已按 token 预算筛选和必要压缩；回答必须优先使用 official_value、distinct_source_document_count、source_gap 和审计状态。"
        "只有 distinct_source_document_count>=3 才能称为通过三来源核验；verification_count 可能只是同一文档内的多条证据。"
        "回答要正式、具体、可执行。涉及建议时，分为重点判断、风险、下一步建议。"
    )
    user_prompt = (
        f"用户问题：{question}\n\n"
        f"本地检索上下文：\n{context}\n\n"
        "请用中文回答。不要编造链接；引用链接由系统在回答末尾追加。"
    )

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
    if provider != "openai":
        from ai_response_compat import deepseek_nonthinking_parameters
        body = deepseek_nonthinking_parameters(body)

    req = urllib.request.Request(
        url,
        data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        method="POST",
    )
    try:
        wait_for_internal_ai_slot("rag-answer")
        with urllib.request.urlopen(req, timeout=90) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="ignore")[:800]
        return {"ok": False, "configured": True, "error": f"OpenAI API 调用失败：HTTP {exc.code} {detail}", "sources": []}
    except Exception as exc:
        return {"ok": False, "configured": True, "error": f"OpenAI API 调用失败：{exc}", "sources": []}

    if provider == "openai":
        answer = _extract_output_text(payload)
    else:
        choices = payload.get("choices") or []
        answer = ""
        if choices:
            answer = ((choices[0].get("message") or {}).get("content") or "").strip()
    citations = citation_markdown(chunks)
    if citations:
        answer = f"{answer}\n\n---\n\n**引用来源：**\n{citations}"
    return {
        "ok": bool(answer),
        "configured": True,
        "model": model,
        "provider": provider,
        "content": answer or "模型没有返回可用文本。",
        "sources": [chunk["source"] for chunk in chunks],
        "context_audit": context_package["audit"],
    }


def stream_llm_with_rag(question: str):
    config = load_ai_config(include_key=True)
    api_key = str(config.get("api_key") or "").strip()
    if not api_key:
        yield {"type": "error", "text": "未配置 API Key，请在 AI 助手弹窗里的“设置”中填写并保存。"}
        return

    provider = str(config.get("provider") or "deepseek").lower()
    model = str(config.get("model") or "deepseek-v4")
    base_url = str(config.get("base_url") or INTERNAL_AI_BASE_URL).rstrip("/")
    
    yield {"type": "process", "step": "检索", "text": "开始从本地文档和爬取结果中进行 RAG 检索..."}
    chunks = retrieve_context(question, limit=14)
    context_package = build_context_package(chunks, model=model)
    chunks = context_package["chunks"]
    audit = context_package["audit"]
    yield {
        "type": "process",
        "step": "完成",
        "text": (
            f"检索完成：保留 {audit['retained_chunks']} / {audit['input_chunks']} 个片段，"
            f"估算 {audit['token_estimate']} / {audit['token_budget']} tokens，"
            f"压缩 {audit['compressed_chunks']} 个片段。"
        ),
    }
    
    meta_links = []
    seen_urls = set()
    references = []
    for i, chunk in enumerate(chunks):
        chunk_links = chunk.get("links", [])
        references.append({"index": i + 1, "source": chunk["source"], "links": chunk_links})
        for link in chunk_links:
            url = link.get("url")
            if url and url not in seen_urls:
                seen_urls.add(url)
                meta_links.append(link)
                
    yield {
        "type": "meta",
        "model": model,
        "provider": provider,
        "sources": [chunk["source"] for chunk in chunks],
        "links": meta_links,
        "references": references,
        "contextAudit": audit,
    }
    
    context = context_package["context"]
    
    system_prompt = (
        "你是中国移动战略部公开信息监测系统中的 RAG 助手。"
        "只能基于提供的本地周报、爬取结果和审计上下文回答；如果上下文不足，要明确说明。"
        "上下文已按 token 预算筛选和必要压缩；回答必须优先使用 official_value、distinct_source_document_count、source_gap 和审计状态。"
        "只有 distinct_source_document_count>=3 才能称为通过三来源核验；verification_count 可能只是同一文档内的多条证据。"
        "回答要正式、具体、可执行。涉及建议时，分为：重点判断、风险、下一步建议。"
        "请使用清晰 Markdown：二级标题、编号列表、加粗关键词，避免大段文字堆在一起。"
        "非常重要：请在回答中通过标注如 [1], [2] 来内联引用相应片段的来源（数字对应上下文中的来源编号）。"
    )
    user_prompt = (
        f"用户问题：{question}\n\n"
        f"本地检索上下文：\n{context}\n\n"
        "请用中文回答。务必在段落中使用 [1], [2] 等格式进行来源引用。"
    )

    if provider == "openai":
        body = {"model": model, "instructions": system_prompt, "input": user_prompt, "stream": True}
        url = f"{base_url}/responses"
    else:
        body = {
            "model": model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": 0.2,
            "stream": True,
        }
        url = f"{base_url}/chat/completions"
    body.update(config.get("extra_parameters") or {})
    if provider != "openai":
        from ai_response_compat import deepseek_nonthinking_parameters
        body = deepseek_nonthinking_parameters(body)

    req = urllib.request.Request(
        url,
        data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        method="POST",
    )
    try:
        wait_for_internal_ai_slot("rag-stream")
        with urllib.request.urlopen(req, timeout=120) as resp:
            for raw in resp:
                line = raw.decode("utf-8", errors="ignore").strip()
                if not line or not line.startswith("data:"):
                    continue
                data = line.removeprefix("data:").strip()
                if data == "[DONE]":
                    break
                try:
                    payload = json.loads(data)
                except json.JSONDecodeError:
                    continue
                if provider == "openai":
                    if payload.get("type") == "response.output_text.delta":
                        delta = payload.get("delta", "")
                    else:
                        delta = ""
                else:
                    choices = payload.get("choices") or []
                    delta = ""
                    if choices:
                        delta = ((choices[0].get("delta") or {}).get("content") or "")
                if delta:
                    yield {"type": "delta", "text": delta}
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="ignore")[:800]
        yield {"type": "error", "text": f"LLM 调用失败：HTTP {exc.code} {detail}"}
    except Exception as exc:
        yield {"type": "error", "text": f"LLM 调用失败：{exc}"}
    citations = citation_markdown(chunks)
    if citations:
        yield {"type": "delta", "text": f"\n\n---\n\n**引用来源：**\n{citations}"}
    yield {"type": "done"}
