from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from data_curation.checkpoint_store import maintain_checkpoint_database


def main() -> int:
    parser = argparse.ArgumentParser(description="校验、保留并压缩 LangGraph SQLite 检查点。")
    parser.add_argument("--database", type=Path, default=ROOT / "curation_data" / "checkpoints.sqlite")
    parser.add_argument("--current-thread-id", default="")
    parser.add_argument("--keep-threads", type=int, default=8)
    parser.add_argument("--max-mb", type=int, default=768)
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()
    result = maintain_checkpoint_database(
        args.database,
        current_thread_id=args.current_thread_id,
        keep_threads=args.keep_threads,
        max_bytes=args.max_mb * 1024 * 1024,
        force=args.force,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
