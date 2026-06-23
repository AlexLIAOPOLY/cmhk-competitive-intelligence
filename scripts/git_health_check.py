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
)

RUNTIME_SUFFIXES = (
    ".log",
    ".pid",
    ".wav",
    ".aiff",
    ".mp3",
)

GENERATED_SUFFIXES = (
    ".docx",
    ".xlsx",
)

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
}


def git_lines(*args: str) -> list[str]:
    output = subprocess.check_output(["git", *args], text=True)
    return [line for line in output.splitlines() if line.strip()]


def is_runtime(path: str) -> bool:
    return path.startswith(RUNTIME_PREFIXES) or path.endswith(RUNTIME_SUFFIXES)


def is_generated(path: str) -> bool:
    name = Path(path).name
    if name in TEMPLATE_ALLOWLIST:
        return False
    return path.endswith(GENERATED_SUFFIXES)


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
    dirty = parse_status()
    dirty_runtime = [(status, path) for status, path in dirty if is_runtime(path)]
    dirty_generated = [(status, path) for status, path in dirty if is_generated(path)]

    print("Git hygiene report")
    print("==================")
    print(f"tracked_files: {len(tracked)}")
    for key in ("source", "tests", "knowledge", "generated", "runtime", "other"):
        print(f"{key}: {tracked_counter.get(key, 0)}")
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
        print("  git rm --cached -r tmp agent_runs agent_chat_threads agent_knowledge/generated_charts")
        print("  git rm --cached -- '*.log' '*.pid' '*.wav' '*.aiff' '*.mp3'")
        print("  git rm --cached -- '*.docx'")
        print("  git add weekly_report_template.docx carrier_performance_template.docx")
    else:
        print("warnings: none")

    return 1 if args.strict and warnings else 0


if __name__ == "__main__":
    raise SystemExit(main())
