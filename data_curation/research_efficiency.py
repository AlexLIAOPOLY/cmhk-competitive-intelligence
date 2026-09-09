"""Lossless request packing and bounded I/O; no research or acceptance policy."""
from __future__ import annotations

import json
import threading
from concurrent.futures import ThreadPoolExecutor


# Six research agents share this budget; the final reviewer uses the same code.
# These workers perform only I/O, never model calls or checkpoint writes.
_NETWORK_SLOTS = threading.BoundedSemaphore(6)


def index_passages(body):
    """Match .{1,1100}(?:\\s|$) on whitespace-normalized text without backtracking.

    Long unbroken tokens made regex search retry a 1100-character match at
    every character. Preserve its exact text, offsets and numbering, including
    the skipped prefix of such tokens; the full page remains in the archive.
    """
    passages = {}
    cursor, size = 0, len(body)
    while cursor < size:
        start = cursor
        if size - cursor <= 1100:
            end = size
        else:
            space = body.rfind(" ", cursor + 1, cursor + 1101)
            if space < 0:
                space = body.find(" ", cursor + 1101)
                if space < 0:
                    start, end = size - 1100, size
                else:
                    start, end = space - 1100, space + 1
            else:
                end = space + 1
        passages[f"p{len(passages)}"] = {"text": body[start:end], "offset": start}
        cursor = end
    return passages


def ordered_network_map(function, values):
    """Preserve input order and keep all state mutation in the calling agent."""
    def call(value):
        with _NETWORK_SLOTS:
            return function(value)

    with ThreadPoolExecutor(max_workers=3, thread_name_prefix="research-io") as pool:
        yield from pool.map(call, values)


def compact_json(value):
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def pack_baseline(rows):
    """All periods, values and provenance remain present, including unknowns.

    A table removes repeated field names and common unit/scope strings. Mixed
    schemas stay untouched so absent fields cannot silently become null values.
    """
    if not isinstance(rows, list) or len(rows) < 2 or not all(isinstance(r, dict) for r in rows):
        return rows
    columns = list(rows[0])
    if any(set(row) != set(columns) for row in rows):
        return rows
    common = {key: rows[0][key] for key in columns
              if all(compact_json(row[key]) == compact_json(rows[0][key]) for row in rows)}
    columns = [key for key in columns if key not in common]
    packed = {"format": "table: each row uses columns plus common fields",
              "common": common, "columns": columns,
              "rows": [[row[key] for key in columns] for row in rows]}
    return packed if len(compact_json(packed)) < len(compact_json(rows)) else rows


def pack_context(payload):
    """Remove exact duplicate previews only; never truncate or summarize evidence."""
    packed = dict(payload)
    packed["trusted_database_baseline"] = pack_baseline(payload.get("trusted_database_baseline", []))
    previews = {}
    catalog = []
    for source in payload.get("official_sources", []):
        row = dict(source)
        preview = row.get("preview")
        if isinstance(preview, str) and len(preview) > 100:
            if preview in previews:
                row.pop("preview")
                row["preview_same_as_source_url"] = previews[preview]
            else:
                previews[preview] = row["source_url"]
        catalog.append(row)
    packed["official_sources"] = catalog
    original = compact_json(payload)
    result = compact_json(packed)
    return result if len(result) < len(original) else original
