#!/usr/bin/env python3
"""Populate the application-identity Feishu directory cache before traffic cutover."""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from cmhk.auth.service import AuthService  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--runtime-root", default=os.environ.get("CMHK_RUNTIME_ROOT", str(ROOT)))
    parser.add_argument("--env-file", default=os.environ.get("CMHK_AUTH_ENV_FILE", ""))
    args = parser.parse_args()
    if args.env_file:
        os.environ["CMHK_AUTH_ENV_FILE"] = args.env_file
    service = AuthService(Path(args.runtime_root).resolve())
    people = service._directory_users_from_openapi()
    print(json.dumps({
        "ok": bool(people),
        "people_count": len(people),
        "cache_path": str(service.directory_cache_path),
    }, ensure_ascii=False))
    return 0 if people else 1


if __name__ == "__main__":
    raise SystemExit(main())
