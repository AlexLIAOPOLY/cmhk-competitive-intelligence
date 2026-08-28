#!/usr/bin/env python3
"""Publish the current quarterly competitor package as an immutable release."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from cmhk.data_releases import default_release_root, publish_quarterly_release_task


DEFAULT_DATASET = ROOT / "agent_knowledge" / "quarterly_competitor_metrics_2026-06-18"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset-dir", type=Path, default=DEFAULT_DATASET)
    parser.add_argument("--release-root", type=Path, default=default_release_root(ROOT))
    args = parser.parse_args()
    result = publish_quarterly_release_task(
        args.dataset_dir,
        args.release_root,
        project_root=ROOT,
        trigger_kind="手动",
    )
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
