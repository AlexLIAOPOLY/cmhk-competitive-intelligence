#!/usr/bin/env python3
"""Reject undeclared root entries without reading private file contents."""
from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path


def violations(root: Path, entries: list[str]) -> list[str]:
    allowed = set(json.loads((root / 'config/workspace_layout.json').read_text())['root_entries'])
    return sorted({entry.split('/', 1)[0] for entry in entries} - allowed)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--staged', action='store_true', help='Validate the staged tree, for commit hooks.')
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    if args.staged:
        raw = subprocess.check_output(['git', '-C', str(root), 'ls-files', '-z'])
        entries = [p.decode() for p in raw.split(b'\0') if p]
        # An unstaged allowlist edit must not bypass the pre-commit gate.
        policy = subprocess.check_output(['git', '-C', str(root), 'show', ':config/workspace_layout.json'])
        allowed = set(json.loads(policy)['root_entries'])
        unexpected = sorted({p.split('/', 1)[0] for p in entries} - allowed)
    else:
        unexpected = violations(root, [p.name for p in root.iterdir()])
    if unexpected:
        print('未登记的根目录项：' + ', '.join(unexpected))
        print('请按 docs/PROJECT_STRUCTURE.md 归位；仅技术必需的入口可登记根目录例外。')
        return 1
    print('Workspace layout: root entries match the explicit directory policy.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
