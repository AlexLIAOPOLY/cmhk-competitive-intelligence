from __future__ import annotations

import argparse
import json

from data_curation.workflow import run_workflow


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="整理爬取证据、校验事实并规划缺口补爬。")
    parser.add_argument("legacy_limit", nargs="?", type=int)
    parser.add_argument("--limit", type=int)
    parser.add_argument("--batch-size", type=int, default=25)
    parser.add_argument("--ai-workers", type=int, default=3)
    parser.add_argument("--search-verify-workers", type=int, default=4)
    parser.add_argument("--search-verify-online", action="store_true")
    parser.add_argument(
        "--search-verify-online-limit",
        type=int,
        default=0,
        help="联网搜索验证条数上限；0 表示不限制，对所有待验证事实联网核验。",
    )
    parser.add_argument("--no-ai", action="store_true")
    parser.add_argument("--recrawl-gaps", action="store_true")
    parser.add_argument("--max-recrawl-rows", type=int, default=3)
    parser.add_argument("--max-recrawl-rounds", type=int, default=1)
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    summary = run_workflow(
        limit=args.limit if args.limit is not None else args.legacy_limit,
        batch_size=args.batch_size,
        ai_workers=max(1, args.ai_workers),
        search_verify_workers=max(1, args.search_verify_workers),
        search_verify_online=args.search_verify_online,
        search_verify_online_limit=max(0, args.search_verify_online_limit),
        online_ai=not args.no_ai,
        allow_recrawl=args.recrawl_gaps,
        max_recrawl_rows=args.max_recrawl_rows,
        max_recrawl_rounds=args.max_recrawl_rounds,
        dry_run=args.dry_run,
    )
    print("CURATION_SUMMARY=" + json.dumps(summary, ensure_ascii=False), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
