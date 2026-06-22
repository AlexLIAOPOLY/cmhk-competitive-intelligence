#!/usr/bin/env python3
from __future__ import annotations

import csv
import json
import time
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
KNOWLEDGE_ROOT = ROOT / "agent_knowledge"


def _read_json(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def _count_csv_rows(path: Path) -> int | None:
    if not path.exists():
        return None
    try:
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            return sum(1 for _ in csv.DictReader(handle))
    except Exception:
        return None


def _count_verified(path: Path) -> tuple[int | None, int | None]:
    if not path.exists():
        return None, None
    verified = 0
    gaps = 0
    try:
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            for row in csv.DictReader(handle):
                status = str(row.get("verification_status") or "")
                count = str(row.get("verification_count") or "")
                if status and status != "source_gap_confirmed":
                    verified += 1
                elif count.isdigit() and int(count) > 0:
                    verified += 1
                if "gap" in status:
                    gaps += 1
    except Exception:
        return None, None
    return verified, gaps


def enrich_manifest(folder: Path) -> bool:
    manifest_path = folder / "manifest.json"
    if not manifest_path.exists():
        return False
    manifest = _read_json(manifest_path)
    if not manifest:
        return False
    changed = False
    now = time.strftime("%Y-%m-%d")
    if "version" not in manifest:
        manifest["version"] = str(manifest.get("updated_at") or now)
        changed = True
    if "built_at" not in manifest:
        manifest["built_at"] = str(manifest.get("updated_at") or now)
        changed = True
    csv_candidates = [
        folder / "quarterly_metrics.csv",
        folder / "macro_policy_metrics.csv",
        folder / "cloud_vendor_metrics_2023_2025.csv",
        folder / "core_metrics_2023_2025.csv",
    ]
    primary_csv = next((path for path in csv_candidates if path.exists()), None)
    if primary_csv:
        row_count = _count_csv_rows(primary_csv)
        if row_count is not None and manifest.get("row_count") != row_count:
            manifest["row_count"] = row_count
            changed = True
        verified, gaps = _count_verified(primary_csv)
        if verified is not None and manifest.get("verified_count") != verified:
            manifest["verified_count"] = verified
            changed = True
        if gaps is not None and manifest.get("gap_count") != gaps:
            manifest["gap_count"] = gaps
            changed = True
    audit_candidates = sorted(folder.glob("*audit*.md")) + sorted(folder.glob("*verification*.md"))
    if audit_candidates and "last_audit_path" not in manifest:
        manifest["last_audit_path"] = audit_candidates[-1].relative_to(ROOT).as_posix()
        changed = True
    if changed:
        manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return changed


def main() -> int:
    changed = []
    if KNOWLEDGE_ROOT.exists():
        for folder in sorted(KNOWLEDGE_ROOT.iterdir()):
            if folder.is_dir() and enrich_manifest(folder):
                changed.append(folder.name)
    print(json.dumps({"ok": True, "changed": changed, "changed_count": len(changed)}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
