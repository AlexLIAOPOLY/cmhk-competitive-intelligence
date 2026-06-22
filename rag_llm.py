from __future__ import annotations

import csv
import json
import os
import re
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from ai_config import load_ai_config


ROOT = Path(__file__).resolve().parent
AGENT_KNOWLEDGE_ROOT = ROOT / "agent_knowledge"
AGENT_KNOWLEDGE_ALLOWED_SUFFIXES = {".md", ".txt", ".json", ".csv", ".tsv"}
AGENT_KNOWLEDGE_SKIP_NAMES = {".DS_Store"}
DEFAULT_CONTEXT_TOKEN_BUDGET = int(os.environ.get("CMHK_RAG_CONTEXT_TOKEN_BUDGET", "9000"))
MAX_CHUNK_TOKENS = int(os.environ.get("CMHK_RAG_MAX_CHUNK_TOKENS", "1400"))
TOKEN_HEADROOM = int(os.environ.get("CMHK_RAG_TOKEN_HEADROOM", "1200"))


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
    return {item.lower() for item in re.findall(r"[A-Za-z0-9_\-\u4e00-\u9fff]{2,}", text or "")}


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
    source_type = str(manifest.get("source_type") or manifest.get("sourceType") or "local").strip()
    scope = str(manifest.get("scope") or "").strip()
    updated_at = str(manifest.get("updated_at") or manifest.get("updatedAt") or "").strip()
    quality = str(manifest.get("quality") or manifest.get("quality_note") or "").strip()
    visibility = str(manifest.get("visibility") or "").strip().lower()
    superseded_by = str(manifest.get("superseded_by") or manifest.get("supersededBy") or "").strip()
    return {
        "id": dataset_id,
        "title": title,
        "summary": summary,
        "tags": [str(item).strip() for item in tags if str(item).strip()],
        "keywords": [str(item).strip() for item in keywords if str(item).strip()],
        "entrypoints": [str(item).strip() for item in entrypoints if str(item).strip()],
        "source_type": source_type,
        "scope": scope,
        "updated_at": updated_at,
        "quality": quality,
        "visibility": visibility,
        "superseded_by": superseded_by,
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
        if dataset_ids is None and manifest.get("visibility") in {"hidden", "superseded", "archived"}:
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
                    "entrypoint": path.name in set(manifest.get("entrypoints") or []),
                }
            )
        if not files and not manifest.get("manifest_path"):
            continue
        manifest["files"] = files
        datasets.append(manifest)
    return datasets


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
    for dataset in list_knowledge_datasets(dataset_ids=dataset_ids):
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
            key=lambda p: (0 if p.name in entrypoints else 1, p.name),
        )
        for path in ordered_files:
            if not _is_allowed_knowledge_file(path):
                continue
            source = path.relative_to(ROOT).as_posix()
            text = _read_text(path, limit=120000)
            if path.suffix.lower() == ".json":
                try:
                    text = json.dumps(json.loads(text), ensure_ascii=False, indent=2)
                except Exception:
                    pass
            chunks.extend(_chunk_text(source, text, max_chars=1600))
    return chunks


def build_rag_index(dataset_ids: set[str] | None = None) -> list[dict[str, Any]]:
    chunks: list[dict[str, Any]] = []
    for name in ["weekly_report.md", "final_audit.md", "coverage_report.tsv", "run_log.tsv"]:
        chunks.extend(_chunk_text(name, _read_text(ROOT / name)))
    chunks.extend(_agent_knowledge_chunks(dataset_ids=dataset_ids))
    chunks.extend(_result_chunks())
    return chunks


def _selected_quarterly_metrics_csv(dataset_ids: set[str] | None = None) -> Path | None:
    candidates: list[Path] = []
    if not AGENT_KNOWLEDGE_ROOT.exists():
        return None
    for folder in AGENT_KNOWLEDGE_ROOT.glob("quarterly_competitor_metrics_*"):
        if not folder.is_dir():
            continue
        manifest = _knowledge_manifest(folder)
        if dataset_ids is not None and manifest["id"] not in dataset_ids and folder.name not in dataset_ids:
            continue
        csv_path = folder / "quarterly_metrics.csv"
        if csv_path.exists():
            candidates.append(csv_path)
    if not candidates:
        return None
    return sorted(candidates, key=lambda path: (path.parent.name, path.stat().st_mtime), reverse=True)[0]


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

    filtered: list[dict[str, str]] = []
    for row in rows:
        subject = (row.get("subject") or "").strip()
        period = re.sub(r"\s+", " ", (row.get("period") or "").strip().upper())
        metric_key = (row.get("metric_key") or "").strip()
        if matched_subjects and subject not in matched_subjects:
            continue
        if periods and period not in periods:
            continue
        if metric_keys and metric_key not in metric_keys:
            continue
        filtered.append(row)

    latest_intent = any(
        key in lowered_question
        for key in ["最新", "最近", "latest", "recent", "current", "last quarter", "latest quarter"]
    )
    if latest_intent:
        filtered.sort(
            key=lambda row: _latest_period_score(f"{row.get('period', '')} {row.get('period_end', '')}"),
            reverse=True,
        )

    chunks: list[dict[str, Any]] = []
    for row in filtered[:12]:
        official_value = (row.get("official_value") or "").strip()
        official_unit = (row.get("official_unit") or row.get("unit") or "").strip()
        standard_value = (row.get("value") or "").strip()
        verification_count = (row.get("verification_count") or "").strip()
        status = (row.get("verification_status") or "").strip()
        evidence = re.sub(r"\s+", " ", (row.get("official_evidence") or "").strip())
        note = re.sub(r"\s+", " ", (row.get("verification_note") or "").strip())
        text = (
            f"精确季度指标行：subject={row.get('subject')}; period={row.get('period')}; "
            f"metric_key={row.get('metric_key')}; metric_zh={row.get('metric_zh')}; grain={row.get('grain')}; "
            f"standardized_value={standard_value} {row.get('unit')}; official_value={official_value} {official_unit}; "
            f"verification_status={status}; verification_count={verification_count}; "
            f"official_source_label={row.get('official_source_label')}; official_source_url={row.get('official_source_url')}; "
            f"official_evidence={evidence}; verification_note={note}. "
            "回答时：只要 verification_count>=2 即代表该行已有多来源核验；"
            "若 verification_status=official_conflict，正式数值采用 official_value，并说明标准化表与官方披露冲突。"
        )
        source = csv_path.relative_to(ROOT).as_posix()
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
    exact_chunks = _quarterly_exact_metric_chunks(question, dataset_ids=dataset_ids)
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
    api_key = (os.environ.get("OPENAI_API_KEY") or str(config.get("api_key") or "")).strip()
    if not api_key:
        return {
            "ok": False,
            "configured": False,
            "error": "未配置 API Key，无法调用真正的 LLM。请在页面右上角“AI 设置”里填写并保存。",
            "sources": [],
        }

    provider = str(config.get("provider") or "deepseek").lower()
    model = os.environ.get("OPENAI_MODEL") or str(config.get("model") or "deepseek-v4-flash")
    base_url = str(config.get("base_url") or "https://api.deepseek.com").rstrip("/")
    chunks = retrieve_context(question, limit=14)
    context_package = build_context_package(chunks, model=model)
    chunks = context_package["chunks"]
    context = context_package["context"]
    system_prompt = (
        "你是中国移动战略部公开信息监测系统中的 RAG 助手。"
        "只能基于提供的本地周报、爬取结果和审计上下文回答；如果上下文不足，要明确说明。"
        "上下文已按 token 预算筛选和必要压缩；回答必须优先使用 official_value、verification_count、source_gap 和审计状态。"
        "回答要正式、具体、可执行。涉及建议时，分为重点判断、风险、下一步建议。"
    )
    user_prompt = (
        f"用户问题：{question}\n\n"
        f"本地检索上下文：\n{context}\n\n"
        "请用中文回答。不要编造链接；引用链接由系统在回答末尾追加。"
    )

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
    api_key = (os.environ.get("OPENAI_API_KEY") or str(config.get("api_key") or "")).strip()
    if not api_key:
        yield {"type": "error", "text": "未配置 API Key，请在 AI 助手弹窗里的“设置”中填写并保存。"}
        return

    provider = str(config.get("provider") or "deepseek").lower()
    model = os.environ.get("OPENAI_MODEL") or str(config.get("model") or "deepseek-v4-flash")
    base_url = str(config.get("base_url") or "https://api.deepseek.com").rstrip("/")
    
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
        "上下文已按 token 预算筛选和必要压缩；回答必须优先使用 official_value、verification_count、source_gap 和审计状态。"
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
        url = f"{base_url or 'https://api.openai.com/v1'}/responses"
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

    req = urllib.request.Request(
        url,
        data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        method="POST",
    )
    try:
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
