from __future__ import annotations

import fcntl
import gzip
import os
import shutil
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any


DEFAULT_KEEP_THREADS = 8
DEFAULT_MAX_BYTES = 768 * 1024 * 1024
DEFAULT_KEEP_BACKUPS = 3


def _quick_check(path: Path) -> str:
    connection = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=60)
    try:
        row = connection.execute("PRAGMA quick_check(1)").fetchone()
        return str(row[0] if row else "missing quick_check result")
    finally:
        connection.close()


def maintain_checkpoint_database(
    path: Path,
    *,
    current_thread_id: str = "",
    keep_threads: int = DEFAULT_KEEP_THREADS,
    max_bytes: int = DEFAULT_MAX_BYTES,
    force: bool = False,
) -> dict[str, Any]:
    """Prune completed LangGraph threads and atomically compact SQLite.

    A verified gzip copy of the compact database is written before replacement.
    Per-run JSON/JSONL artifacts remain the long-term audit history; SQLite only
    retains enough recent threads for operational resume.
    """
    path = Path(path).resolve()
    if not path.exists():
        return {"ok": True, "maintained": False, "reason": "database_missing"}
    keep_threads = max(1, int(keep_threads))
    max_bytes = max(16 * 1024 * 1024, int(max_bytes))
    lock_path = path.with_suffix(path.suffix + ".maintenance.lock")
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open("a+", encoding="utf-8") as lock_handle:
        fcntl.flock(lock_handle.fileno(), fcntl.LOCK_EX)
        before_bytes = path.stat().st_size
        integrity_before = _quick_check(path)
        connection = sqlite3.connect(path, timeout=120)
        try:
            thread_rows = connection.execute(
                """
                SELECT thread_id, COUNT(*) AS checkpoint_count, MAX(checkpoint_id) AS latest
                FROM checkpoints
                GROUP BY thread_id
                ORDER BY latest DESC
                """
            ).fetchall()
            thread_ids = [str(row[0]) for row in thread_rows]
            needs_maintenance = (
                force
                or integrity_before != "ok"
                or before_bytes > max_bytes
                or len(thread_ids) > keep_threads
            )
            if not needs_maintenance:
                return {
                    "ok": True,
                    "maintained": False,
                    "reason": "healthy_within_retention",
                    "integrity": integrity_before,
                    "bytes": before_bytes,
                    "threads": len(thread_ids),
                }

            retained = list(thread_ids[:keep_threads])
            current_thread_id = str(current_thread_id or "").strip()
            if current_thread_id and current_thread_id in thread_ids and current_thread_id not in retained:
                retained.append(current_thread_id)
            removed = [thread_id for thread_id in thread_ids if thread_id not in retained]
            compact_path = path.with_name(f".{path.name}.compact-{os.getpid()}")
            if compact_path.exists():
                compact_path.unlink()
            # A damaged page map can make DELETE/VACUUM fail even while all
            # retained rows remain readable. Rebuild the two SqliteSaver tables
            # logically so unreachable/corrupt pages are never copied.
            compact = sqlite3.connect(compact_path, timeout=120)
            try:
                for table in ("checkpoints", "writes"):
                    schema_row = connection.execute(
                        "SELECT sql FROM sqlite_master WHERE type='table' AND name=?",
                        (table,),
                    ).fetchone()
                    if not schema_row or not schema_row[0]:
                        raise RuntimeError(f"检查点数据库缺少 {table} 表")
                    compact.execute(str(schema_row[0]))
                for thread_id in retained:
                    checkpoint_rows = connection.execute(
                        "SELECT * FROM checkpoints WHERE thread_id=?",
                        (thread_id,),
                    ).fetchall()
                    write_rows = connection.execute(
                        "SELECT * FROM writes WHERE thread_id=?",
                        (thread_id,),
                    ).fetchall()
                    compact.executemany(
                        "INSERT INTO checkpoints VALUES (?, ?, ?, ?, ?, ?, ?)",
                        checkpoint_rows,
                    )
                    compact.executemany(
                        "INSERT INTO writes VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                        write_rows,
                    )
                compact.commit()
                compact.execute("VACUUM")
            finally:
                compact.close()
        finally:
            connection.close()

        integrity_after = _quick_check(compact_path)
        if integrity_after != "ok":
            compact_path.unlink(missing_ok=True)
            raise RuntimeError(f"压缩后的检查点数据库完整性校验失败：{integrity_after}")

        backup_dir = path.parent / "checkpoint_backups"
        backup_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().astimezone().strftime("%Y%m%d_%H%M%S")
        backup_path = backup_dir / f"{path.stem}-{stamp}.sqlite.gz"
        with compact_path.open("rb") as source, gzip.open(backup_path, "wb", compresslevel=6) as target:
            shutil.copyfileobj(source, target, length=1024 * 1024)
        os.replace(compact_path, path)
        backups = sorted(
            backup_dir.glob(f"{path.stem}-*.sqlite.gz"),
            key=lambda candidate: candidate.stat().st_mtime,
            reverse=True,
        )
        for expired_backup in backups[DEFAULT_KEEP_BACKUPS:]:
            expired_backup.unlink()
        after_bytes = path.stat().st_size
        return {
            "ok": True,
            "maintained": True,
            "integrity_before": integrity_before,
            "integrity_after": integrity_after,
            "before_bytes": before_bytes,
            "after_bytes": after_bytes,
            "threads_before": len(thread_ids),
            "threads_after": len(retained),
            "removed_threads": len(removed),
            "backup_path": str(backup_path),
        }
