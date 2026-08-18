"""Canonical identities for disclosure documents used as evidence.

Different URLs are not necessarily different sources: an issuer may split one
annual report into section PDFs, and an exchange may host a mirror of the same
announcement.  This module supplies one conservative identity rule shared by
the offline audit and Xiaojing's live RAG layer.
"""

from __future__ import annotations

import re
from typing import Any
from urllib.parse import urlsplit, urlunsplit


DOCUMENT_TITLE_PATTERN = re.compile(
    r"^(.*?\b(?:"
    r"annual results announcement|interim results announcement|quarterly results announcement|"
    r"annual results presentation|interim results presentation|quarterly results presentation|"
    r"annual report|interim report|quarterly report|sustainability report|esg report|investor factsheet"
    r"))\b",
    re.IGNORECASE,
)


def normalized_source_url(value: Any) -> str:
    raw = str(value or "").strip()
    if not re.match(r"^https?://", raw, re.IGNORECASE):
        return ""
    parts = urlsplit(raw)
    return urlunsplit((parts.scheme.lower(), parts.netloc.lower(), parts.path, parts.query, ""))


def _normalized_label(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip()).lower()


def canonical_source_document_identity(source: dict[str, Any], *, fallback_url: str = "") -> str:
    """Return an underlying-document identity for one evidence entry.

    Explicit IDs always win.  Otherwise a recognizable disclosure title is
    used so section PDFs and exchange mirrors collapse.  Legal variants such
    as A-share, H-share, Form 20-F and annual-report summaries remain distinct.
    Unknown labels conservatively fall back to URL.
    """
    explicit = str(source.get("source_document_id") or "").strip()
    if explicit:
        return f"document:{explicit.lower()}"

    label = _normalized_label(source.get("label") or source.get("title"))
    match = DOCUMENT_TITLE_PATTERN.match(label)
    if match:
        title = match.group(1).strip(" -–—:;,.")
        qualifiers: list[str] = []
        for token, canonical in (
            ("a-share", "a-share"),
            ("a share", "a-share"),
            ("h-share", "h-share"),
            ("h share", "h-share"),
            ("form 20-f", "form-20-f"),
            ("20-f", "form-20-f"),
            ("annual report summary", "summary"),
            ("annual-report summary", "summary"),
        ):
            if token in label and canonical not in qualifiers:
                qualifiers.append(canonical)
        suffix = ":" + ":".join(qualifiers) if qualifiers else ""
        return f"title:{title}{suffix}"

    url = normalized_source_url(source.get("url") or fallback_url)
    return f"url:{url}" if url else ""


def is_derived_value(row: dict[str, Any]) -> bool:
    """Return True only when the stored value itself was calculated.

    A generic cross-check or reconciliation note is not enough.  We require a
    direct derived status, a calculation-shaped method/basis, or explicit
    arithmetic wording in the supporting evidence.
    """
    status = " ".join(
        str(row.get(field) or "").lower()
        for field in ("verification_status", "核验状态")
    )
    if "derived" in status or "推导" in status:
        return True

    method = " ".join(
        str(row.get(field) or "").lower()
        for field in ("verification_method", "basis", "口径")
    )
    if re.search(r"(?:^|_)(?:minus|less|divided_by|calculated|derived|sum|recalculation)(?:_|$)", method):
        return True
    if any(token in method for token in ("差额", "相减", "除以", "复算值", "推导值")):
        return True

    evidence = " ".join(
        str(row.get(field) or "").lower()
        for field in ("official_evidence", "verification_note", "quality_note", "核验说明")
    )
    arithmetic_evidence = (
        re.search(r"\b(?:minus|divided by|calculated as|derived from)\b", evidence)
        or any(token in evidence for token in ("减", "相减", "相加", "除以", "合计", "复算", "推导"))
    )
    return bool("reconciliation" in method and arithmetic_evidence)
