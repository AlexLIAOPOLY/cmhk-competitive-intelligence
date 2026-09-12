"""Back up and remove daily admissions that violate established database series."""
from __future__ import annotations

import argparse
from contextlib import ExitStack
from datetime import datetime
import fcntl
import hashlib
import json
from pathlib import Path
import shutil

from .research_contracts import (VERSION, formal_record_fact, formal_row_error, is_daily_row, source_fact_error)
from .research_freshness import load_baseline, period_key
from .research_kpi import CARRIER_PATH, CLOUD_PATH
from .research_storage import DOMAIN_PATHS, read_object
from .storage import atomic_write_json


def cleanup(root: Path, *, apply=False, stamp=None):
    root = root.resolve()
    backup = root / "curation_data/series_cleanup" / (stamp or datetime.now().strftime("%Y%m%d_%H%M%S"))
    table_paths = [root / CARRIER_PATH, root / CLOUD_PATH]
    sidecars = [root / p for p in DOMAIN_PATHS.values()]
    lock_paths = [root / "agent_knowledge/executive_intelligence_refresh/.refresh.lock"]
    lock_paths += [p.with_suffix(".promotion.lock") for p in table_paths]
    lock_paths += [p.with_suffix(".lock") for p in sidecars]
    lock_paths += sorted((root / "curation_data/research_runs").glob("*/execution.lock"))
    with ExitStack() as stack:
        # Fail before any mutation if research or a publication owns a table.
        for path in lock_paths:
            if not path.parent.exists():
                continue
            handle = stack.enter_context(path.open("a"))
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        baseline = load_baseline(root).get("companies", {})
        changes, removed = {}, []
        for path in table_paths + sidecars:
            if not path.exists():
                continue
            payload = read_object(path)
            key = "rows" if path in table_paths else "facts"
            kept = []
            for row in payload.get(key, []):
                reason = ""
                if key == "facts":
                    reason = source_fact_error(row, baseline)
                elif is_daily_row(row):
                    fact = formal_record_fact(row)
                    reason = formal_row_error(fact, row, baseline.get(fact["company"], {}))
                    if not reason and period_key(fact["period"]) is None:
                        reason = "日更记录缺少可匹配正式序列的报告期"
                if reason:
                    removed.append({"path": str(path.relative_to(root)), "reason": reason, "record": row})
                else:
                    kept.append(row)
            if len(kept) != len(payload.get(key, [])):
                payload[key] = kept
                if key == "rows":
                    # Remove stale subject indexes; rebuild them from remaining rows.
                    for subject in payload.get("subjects", []):
                        rows = [r for r in kept if r.get("subject") == subject.get("subject")]
                        metrics, periods = {}, {}
                        for row in rows:
                            metrics.setdefault(row["metric_key"], {})[row["period"]] = row.get("value")
                            periods[row["period"]] = {k: row[k] for k in ("period", "period_end", "grain") if k in row}
                        subject.update(metrics=metrics, periods=list(periods.values()))
                changes[path] = payload
        audit = {"policy": VERSION, "applied": apply, "root": str(root), "backup": str(backup),
                 "removed_count": len(removed), "formal_rows_removed": sum(r["path"] in {CARRIER_PATH, CLOUD_PATH} for r in removed),
                 "sidecar_facts_removed": sum(r["path"] in DOMAIN_PATHS.values() for r in removed),
                 "removed": removed, "files": {}}
        if not apply or not changes:
            return audit
        backup.mkdir(parents=True, exist_ok=False)
        for path in changes:
            related = [path]
            if path in table_paths:
                related += [path.with_suffix(".csv"), path.with_name("quarterly_metrics_human_readable.csv"), path.with_name("manifest.json")]
            for original in related:
                if not original.exists():
                    continue
                relative = original.relative_to(root)
                destination = backup / relative
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(original, destination)
                digest = hashlib.sha256(original.read_bytes()).hexdigest()
                if hashlib.sha256(destination.read_bytes()).hexdigest() != digest:
                    raise ValueError("清理备份回读失败")
                audit["files"][str(relative)] = {"before_sha256": digest}
        atomic_write_json(backup / "audit.json", {**audit, "applied": False, "status": "backup_verified"})
        from cmhk.data.daily_financial_promotion import _write_csv
        for path, payload in changes.items():
            atomic_write_json(path, payload)
            if path in table_paths:
                _write_csv(path.with_suffix(".csv"), payload["rows"])
                if path == root / CARRIER_PATH:
                    _write_csv(path.with_name("quarterly_metrics_human_readable.csv"), payload["rows"])
                manifest_path = path.with_name("manifest.json")
                if manifest_path.exists():
                    manifest = read_object(manifest_path)
                    manifest["row_count"] = len(payload["rows"])
                    if isinstance(manifest.get("quality"), dict):
                        manifest["quality"]["row_count"] = len(payload["rows"])
                    atomic_write_json(manifest_path, manifest)
            if read_object(path) != payload:
                raise ValueError("清理写后回读不一致")
        for relative, item in audit["files"].items():
            item["after_sha256"] = hashlib.sha256((root / relative).read_bytes()).hexdigest()
        audit["status"] = "completed"
        atomic_write_json(backup / "audit.json", audit)
        return audit


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    result = cleanup(args.root, apply=args.apply)
    print(json.dumps({k: v for k, v in result.items() if k != "removed"}, ensure_ascii=False, indent=2))
