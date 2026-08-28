"""Content-addressed data releases for downstream CMHK applications.

The crawler remains the only writer of competitor facts.  Consumers receive an
immutable package and an atomically replaced ``current.json`` pointer, so they
never need to read this repository while a refresh is being assembled.
"""

from __future__ import annotations

import csv
import hashlib
import json
import os
import re
import shutil
import subprocess
import tempfile
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any


DATASET_KEY = "quarterly_competitor_metrics"
POINTER_SCHEMA_VERSION = "1.0"
RELEASE_SCHEMA_VERSION = "1.0"
NATURAL_KEY_FIELDS = ("subject", "period", "grain", "metric_key")
REQUIRED_COLUMNS = frozenset(
    {
        *NATURAL_KEY_FIELDS,
        "period_end",
        "value",
        "unit",
        "verification_status",
        "verification_count",
        "official_source_url",
    }
)
HEX_SHA256 = re.compile(r"^[0-9a-f]{64}$")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _stable_json(value: Any) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")


def _write_json(path: Path, payload: Any) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _atomic_write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, raw_path = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary = Path(raw_path)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _safe_entrypoint(dataset_dir: Path, raw_path: str) -> tuple[str, Path]:
    relative = Path(str(raw_path).replace("\\", "/"))
    if relative.is_absolute() or not relative.parts or ".." in relative.parts:
        raise RuntimeError(f"unsafe release entrypoint: {raw_path}")
    unresolved = dataset_dir / relative
    cursor = unresolved
    while cursor != dataset_dir:
        if cursor.is_symlink():
            raise RuntimeError(f"release entrypoint cannot be a symlink: {raw_path}")
        cursor = cursor.parent
    target = unresolved.resolve()
    if dataset_dir.resolve() not in target.parents or not target.is_file():
        raise RuntimeError(f"release entrypoint is missing: {raw_path}")
    return relative.as_posix(), target


def _period_end(period: str, raw_period_end: str) -> str | None:
    raw = raw_period_end.strip()
    try:
        return date.fromisoformat(raw).isoformat()
    except ValueError:
        pass
    label = period.strip()
    match = re.search(r"(?:Q([1-4])\s*(\d{4})|(\d{4})\s*Q([1-4]))", label, re.I)
    if match:
        quarter = int(match.group(1) or match.group(4))
        year = int(match.group(2) or match.group(3))
        month = quarter * 3
        day = 31 if month in {3, 12} else 30
        return date(year, month, day).isoformat()
    match = re.search(r"(?:H([12])\s*(\d{4})|(\d{4})\s*H([12]))", label, re.I)
    if match:
        half = int(match.group(1) or match.group(4))
        year = int(match.group(2) or match.group(3))
        return date(year, 6 if half == 1 else 12, 30 if half == 1 else 31).isoformat()
    match = re.fullmatch(r"(?:FY\s*)?(\d{4})", label, re.I)
    return date(int(match.group(1)), 12, 31).isoformat() if match else None


def validate_quarterly_dataset(dataset_dir: Path) -> dict[str, Any]:
    """Validate the publishable package without accepting degraded metadata."""

    dataset_dir = dataset_dir.expanduser().resolve()
    manifest_path = dataset_dir / "manifest.json"
    csv_path = dataset_dir / "quarterly_metrics.csv"
    if not manifest_path.is_file() or not csv_path.is_file():
        raise RuntimeError("quarterly dataset requires manifest.json and quarterly_metrics.csv")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if not isinstance(manifest, dict):
        raise RuntimeError("quarterly manifest must be a JSON object")
    if str(manifest.get("id") or "") != "quarterly_competitor_metrics_2026-06-18":
        raise RuntimeError("quarterly manifest does not use the canonical stable dataset id")

    with csv_path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        fields = tuple(reader.fieldnames or ())
        missing = REQUIRED_COLUMNS - set(fields)
        if missing:
            raise RuntimeError("quarterly CSV missing columns: " + ", ".join(sorted(missing)))
        rows = list(reader)
    if not rows:
        raise RuntimeError("quarterly CSV has no rows")

    declared_rows = manifest.get("row_count")
    if declared_rows is None:
        declared_rows = (manifest.get("quality") or {}).get("row_count")
    if int(declared_rows or -1) != len(rows):
        raise RuntimeError(
            f"quarterly manifest row count mismatch: declared={declared_rows}, actual={len(rows)}"
        )

    seen: set[tuple[str, ...]] = set()
    periods: list[str] = []
    below_two = 0
    blocked = 0
    blocked_statuses = {
        "official_conflict",
        "source_gap_confirmed",
        "needs_official_row_crosscheck",
    }
    for index, row in enumerate(rows, start=2):
        natural_key = tuple((row.get(field) or "").strip() for field in NATURAL_KEY_FIELDS)
        if not all(natural_key):
            raise RuntimeError(f"quarterly CSV has an incomplete natural key at row {index}")
        if natural_key in seen:
            raise RuntimeError(f"quarterly CSV has a duplicate natural key at row {index}")
        seen.add(natural_key)
        try:
            below_two += int(float((row.get("verification_count") or "0").replace(",", "")) < 2)
        except ValueError as exc:
            raise RuntimeError(f"invalid verification_count at row {index}") from exc
        blocked += int((row.get("verification_status") or "").strip() in blocked_statuses)
        normalized_period = _period_end(
            row.get("period") or "", row.get("period_end") or ""
        )
        if normalized_period:
            periods.append(normalized_period)

    raw_entrypoints = manifest.get("entrypoints")
    if not isinstance(raw_entrypoints, list) or not raw_entrypoints:
        raise RuntimeError("quarterly manifest must declare non-empty entrypoints")
    entrypoints = ["manifest.json", *[str(item) for item in raw_entrypoints]]
    unique_entrypoints = list(dict.fromkeys(entrypoints))
    resolved = [_safe_entrypoint(dataset_dir, item) for item in unique_entrypoints]
    return {
        "dataset_dir": dataset_dir,
        "manifest": manifest,
        "fields": fields,
        "rows": len(rows),
        "data_as_of": max(periods) if periods else None,
        "verification_count_below_2": below_two,
        "blocked_status_rows": blocked,
        "entrypoints": resolved,
    }


def _git_sha(project_root: Path) -> str | None:
    try:
        completed = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=project_root,
            check=True,
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    value = completed.stdout.strip().lower()
    return value if re.fullmatch(r"[0-9a-f]{40}", value) else None


def publish_quarterly_release(
    dataset_dir: str | Path,
    release_root: str | Path,
    *,
    project_root: str | Path | None = None,
) -> dict[str, Any]:
    """Publish one immutable release and atomically advance ``current.json``."""

    validated = validate_quarterly_dataset(Path(dataset_dir))
    root = Path(release_root).expanduser().resolve()
    root.mkdir(parents=True, exist_ok=True)
    source_artifacts = [
        {
            "path": relative,
            "size": source.stat().st_size,
            "sha256": sha256_file(source),
            "source": source,
        }
        for relative, source in validated["entrypoints"]
    ]
    fingerprint_input = [
        {key: artifact[key] for key in ("path", "size", "sha256")}
        for artifact in source_artifacts
    ]
    content_sha256 = hashlib.sha256(_stable_json(fingerprint_input)).hexdigest()
    release_id = f"qcm_{content_sha256[:24]}"
    release_relative = Path("releases") / release_id
    release_dir = root / release_relative
    release_manifest_path = release_dir / "release.json"
    created = False

    if not release_dir.exists():
        staging = Path(tempfile.mkdtemp(prefix=f".{release_id}.", dir=root))
        try:
            staged_release = staging / release_id
            staged_release.mkdir()
            copied: list[dict[str, Any]] = []
            for artifact in source_artifacts:
                destination = staged_release / artifact["path"]
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(artifact["source"], destination)
                actual_sha = sha256_file(destination)
                if actual_sha != artifact["sha256"]:
                    raise RuntimeError(f"release copy hash mismatch: {artifact['path']}")
                copied.append({key: artifact[key] for key in ("path", "size", "sha256")})
            source_manifest = validated["manifest"]
            release_manifest = {
                "schema_version": RELEASE_SCHEMA_VERSION,
                "dataset_key": DATASET_KEY,
                "source_dataset_id": source_manifest["id"],
                "release_id": release_id,
                "content_sha256": content_sha256,
                "published_at": datetime.now(UTC).isoformat(timespec="seconds"),
                "data_as_of": validated["data_as_of"],
                "row_count": validated["rows"],
                "natural_key_fields": list(NATURAL_KEY_FIELDS),
                "columns": list(validated["fields"]),
                "quality": {
                    "verification_count_below_2": validated[
                        "verification_count_below_2"
                    ],
                    "blocked_status_rows": validated["blocked_status_rows"],
                },
                "publisher_git_sha": _git_sha(
                    Path(project_root).resolve()
                    if project_root is not None
                    else validated["dataset_dir"].parents[1]
                ),
                "artifacts": copied,
            }
            _write_json(staged_release / "release.json", release_manifest)
            (root / "releases").mkdir(exist_ok=True)
            os.replace(staged_release, release_dir)
            created = True
        finally:
            shutil.rmtree(staging, ignore_errors=True)

    release_manifest_sha256 = sha256_file(release_manifest_path)
    release_manifest = json.loads(release_manifest_path.read_text(encoding="utf-8"))
    if release_manifest.get("release_id") != release_id:
        raise RuntimeError("existing release manifest does not match its directory")
    if release_manifest.get("content_sha256") != content_sha256:
        raise RuntimeError("existing release content fingerprint is inconsistent")
    pointer = {
        "schema_version": POINTER_SCHEMA_VERSION,
        "dataset_key": DATASET_KEY,
        "release_id": release_id,
        "release_manifest": (release_relative / "release.json").as_posix(),
        "release_manifest_sha256": release_manifest_sha256,
        "published_at": release_manifest["published_at"],
        "data_as_of": release_manifest.get("data_as_of"),
        "row_count": release_manifest["row_count"],
        "content_sha256": content_sha256,
    }
    _atomic_write_json(root / "current.json", pointer)
    return {
        "ok": True,
        "created": created,
        "release_root": str(root),
        "release_dir": str(release_dir),
        "current_pointer": str(root / "current.json"),
        **pointer,
    }


def default_release_root(project_root: str | Path) -> Path:
    configured = os.environ.get("CMHK_QUARTERLY_RELEASE_ROOT")
    return (
        Path(configured).expanduser().resolve()
        if configured
        else Path(project_root).resolve() / "runtime" / "local" / "data_releases" / DATASET_KEY
    )


def resolve_release_request(release_root: Path, request_path: str) -> Path | None:
    """Resolve the small read-only HTTP surface without directory traversal."""

    prefix = "/data-releases/quarterly/"
    if not request_path.startswith(prefix):
        return None
    relative = Path(request_path.removeprefix(prefix))
    if relative.is_absolute() or not relative.parts or ".." in relative.parts:
        return None
    target = (release_root / relative).resolve()
    root = release_root.resolve()
    if root not in target.parents or not target.is_file() or target.is_symlink():
        return None
    return target


__all__ = [
    "DATASET_KEY",
    "default_release_root",
    "publish_quarterly_release",
    "resolve_release_request",
    "sha256_file",
    "validate_quarterly_dataset",
]
