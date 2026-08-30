#!/usr/bin/env python3
"""Report Git hygiene issues without changing project files."""

from __future__ import annotations

import argparse
import subprocess
from collections import Counter
from pathlib import Path


RUNTIME_PREFIXES = (
    "tmp/",
    "agent_runs/",
    "agent_chat_threads/",
    "agent_knowledge/generated_charts/",
    "weekly_report_render/",
    "audio/",
    "evidence_cache/",
    "artifacts/ui-qa/",
    "curation_data/backups/",
    "curation_data/cache_backups/",
    "curation_data/runs/",
    "data/quarterly_sources/http_cache/",
    "web/static/report-previews/",
)

RUNTIME_SUFFIXES = (
    ".log",
    ".pid",
    ".wav",
    ".aiff",
    ".mp3",
    ".sqlite",
    ".sqlite-shm",
    ".sqlite-wal",
)

GENERATED_SUFFIXES = (
    ".docx",
    ".xlsx",
    ".pdf",
)

MAX_TRACKED_FILE_BYTES = 25 * 1024 * 1024

SOURCE_SUFFIXES = (
    ".py",
    ".js",
    ".css",
    ".html",
    ".md",
    ".json",
    ".tsv",
    ".csv",
    ".yaml",
    ".yml",
    ".txt",
)

TEMPLATE_ALLOWLIST = {
    "weekly_report_template.docx",
    "carrier_performance_template.docx",
    "weekly_report_from_word_template.docx",
}


def git_lines(*args: str) -> list[str]:
    output = subprocess.check_output(["git", *args], text=True)
    return [line for line in output.splitlines() if line.strip()]


def git_config_values(key: str) -> list[str]:
    completed = subprocess.run(
        ["git", "config", "--get-all", key],
        capture_output=True,
        text=True,
        check=False,
    )
    return [line for line in completed.stdout.splitlines() if line.strip()]


def is_runtime(path: str) -> bool:
    return path.startswith(RUNTIME_PREFIXES) or path.endswith(RUNTIME_SUFFIXES)


def is_generated(path: str) -> bool:
    name = Path(path).name
    if name in TEMPLATE_ALLOWLIST:
        return False
    return path.endswith(GENERATED_SUFFIXES)


def is_duplicate_release(path: str) -> bool:
    return path.startswith("agent_knowledge/") and " 2." in Path(path).name


def classify(path: str) -> str:
    if is_runtime(path):
        return "runtime"
    if is_generated(path):
        return "generated"
    if path.startswith("agent_knowledge/"):
        return "knowledge"
    if path.startswith("tests/") or Path(path).name.startswith("test_"):
        return "tests"
    if path.endswith(SOURCE_SUFFIXES):
        return "source"
    return "other"


def parse_status() -> list[tuple[str, str]]:
    rows: list[tuple[str, str]] = []
    for line in git_lines("status", "--porcelain"):
        if len(line) < 4:
            continue
        status = line[:2]
        path = line[3:]
        if " -> " in path:
            path = path.split(" -> ", 1)[1]
        rows.append((status, path))
    return rows


def main() -> int:
    parser = argparse.ArgumentParser(description="Check tracked runtime/generated file hygiene.")
    parser.add_argument("--strict", action="store_true", help="Exit non-zero when hygiene warnings exist.")
    args = parser.parse_args()

    tracked = git_lines("ls-files")
    tracked_counter = Counter(classify(path) for path in tracked)
    tracked_runtime = [path for path in tracked if is_runtime(path)]
    tracked_generated = [path for path in tracked if is_generated(path)]
    tracked_ignored = git_lines("ls-files", "-ci", "--exclude-standard")
    tracked_duplicates = [path for path in tracked if is_duplicate_release(path)]
    private_tracking_refs = git_lines(
        "for-each-ref", "--format=%(refname)", "refs/remotes/private"
    )
    private_backup_tracking_refs = [
        ref for ref in private_tracking_refs
        if ref.startswith("refs/remotes/private/backup/")
    ]
    private_snapshot_tracking_refs = [
        ref for ref in private_tracking_refs
        if ref == "refs/remotes/private/main"
    ]
    private_fetch_specs = git_config_values("remote.private.fetch")
    broad_private_fetch = any("refs/heads/*" in spec for spec in private_fetch_specs)
    oversized_tracked = [
        path
        for path in tracked
        if Path(path).is_file() and Path(path).stat().st_size > MAX_TRACKED_FILE_BYTES
    ]
    dirty = parse_status()
    # An index deletion is the intended cleanup operation: the local ignored
    # file remains in place and must not make the cleanup commit fail strict mode.
    dirty_runtime = [
        (status, path) for status, path in dirty
        if status[0] != "D" and is_runtime(path)
    ]
    dirty_generated = [
        (status, path) for status, path in dirty
        if status[0] != "D" and is_generated(path)
    ]

    print("Git hygiene report")
    print("==================")
    print(f"tracked_files: {len(tracked)}")
    for key in ("source", "tests", "knowledge", "generated", "runtime", "other"):
        print(f"{key}: {tracked_counter.get(key, 0)}")
    print(f"private_remote_tracking_refs: {len(private_tracking_refs)}")
    print(f"private_backup_tracking_refs: {len(private_backup_tracking_refs)}")
    print()

    if dirty:
        print("working_tree_changes:")
        for status, path in dirty[:30]:
            print(f"  {status} {path}")
        if len(dirty) > 30:
            print(f"  ... {len(dirty) - 30} more")
    else:
        print("working_tree_changes: none")
    print()

    warnings: list[str] = []
    if tracked_runtime:
        warnings.append(f"tracked runtime files: {len(tracked_runtime)}")
    if tracked_generated:
        warnings.append(f"tracked generated/binary artifacts: {len(tracked_generated)}")
    if tracked_ignored:
        warnings.append(f"tracked files already covered by .gitignore: {len(tracked_ignored)}")
    if tracked_duplicates:
        warnings.append(f"tracked duplicate knowledge releases: {len(tracked_duplicates)}")
    if oversized_tracked:
        warnings.append(f"tracked files larger than 25 MiB: {len(oversized_tracked)}")
    if broad_private_fetch:
        warnings.append("private remote fetches every branch instead of only active refs")
    if private_backup_tracking_refs:
        warnings.append(
            f"local private backup tracking refs: {len(private_backup_tracking_refs)}"
        )
    if private_snapshot_tracking_refs:
        warnings.append("private snapshot main is retained in the development object database")
    if dirty_runtime:
        warnings.append(f"dirty runtime files: {len(dirty_runtime)}")
    if dirty_generated:
        warnings.append(f"dirty generated/binary artifacts: {len(dirty_generated)}")

    if warnings:
        print("warnings:")
        for warning in warnings:
            print(f"  - {warning}")
        print()
        print("recommended cleanup, after review:")
        print("  git ls-files -ci --exclude-standard -z | git update-index --force-remove -z --stdin")
        print("  Keep local runtime/evidence files in place; remove them from the index only.")
        if broad_private_fetch or private_backup_tracking_refs or private_snapshot_tracking_refs:
            print("  Limit private.fetch to the active development branch, then remove private/main")
            print("  and refs/remotes/private/backup/* locally; all remote branches remain untouched.")
    else:
        print("warnings: none")

    return 1 if args.strict and warnings else 0


if __name__ == "__main__":
    raise SystemExit(main())
