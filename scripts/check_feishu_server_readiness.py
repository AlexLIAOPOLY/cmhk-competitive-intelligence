#!/usr/bin/env python3
"""Read-only deployment check for CMHK Feishu integrations."""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from cmhk.integrations.feishu_runtime import lark_cli_env, resolve_lark_cli  # noqa: E402


def _run_json(argv: list[str]) -> dict:
    process = subprocess.run(
        argv,
        cwd=ROOT,
        env=lark_cli_env(),
        capture_output=True,
        text=True,
        timeout=45,
    )
    if process.returncode:
        detail = (process.stderr or process.stdout).strip()
        raise RuntimeError(detail[:800] or f"exit {process.returncode}")
    payload = json.loads(process.stdout)
    if not isinstance(payload, dict):
        raise RuntimeError("lark-cli did not return a JSON object")
    return payload


def _load_env_file(path: str) -> None:
    target = Path(path).expanduser() if path else None
    if not target or not target.is_file():
        return
    for raw_line in target.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


def _is_loopback_url(value: str) -> bool:
    host = (urlparse(value).hostname or "").lower()
    return host in {"127.0.0.1", "localhost", "::1"}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--live", action="store_true", help="verify bot profiles with read-only API calls")
    parser.add_argument(
        "--require-drive",
        action="store_true",
        help="require and execute a read-only Drive statistics probe (implies --live)",
    )
    parser.add_argument("--server-url", default="", help="expected external service URL")
    parser.add_argument("--env-file", default=os.environ.get("CMHK_AUTH_ENV_FILE", ""))
    args = parser.parse_args()
    if args.require_drive:
        args.live = True
    _load_env_file(args.env_file)

    config = json.loads((ROOT / "config" / "project_monitor.json").read_text(encoding="utf-8"))
    bot = config.get("bot") if isinstance(config.get("bot"), dict) else {}
    subscriptions = config.get("subscriptions") if isinstance(config.get("subscriptions"), dict) else {}
    profiles = list(dict.fromkeys(filter(None, [
        os.environ.get("CMHK_FEISHU_PROFILE"),
        str(bot.get("profile") or ""),
        os.environ.get("CMHK_FEISHU_DIRECTORY_PROFILE"),
        str(subscriptions.get("directory_profile") or ""),
        os.environ.get("CMHK_FEISHU_DELIVERY_PROFILE"),
        str(subscriptions.get("delivery_profile") or ""),
    ])))
    app_id = (os.environ.get("CMHK_FEISHU_APP_ID") or os.environ.get("FEISHU_APP_ID") or "").strip()
    app_secret = (os.environ.get("CMHK_FEISHU_APP_SECRET") or os.environ.get("FEISHU_APP_SECRET") or "").strip()
    redirect_uri = (
        os.environ.get("CMHK_FEISHU_REDIRECT_URI")
        or os.environ.get("FEISHU_REDIRECT_URI")
        or ""
    ).strip()
    checks: list[dict[str, object]] = []
    drive_probe_token = os.environ.get("CMHK_FEISHU_DRIVE_PROBE_TOKEN", "").strip()
    if args.require_drive:
        checks.append({
            "name": "drive_probe_configured",
            "ok": bool(drive_probe_token),
            "error": "set CMHK_FEISHU_DRIVE_PROBE_TOKEN" if not drive_probe_token else "",
        })

    checks.append({"name": "app_credentials", "ok": bool(app_id and app_secret)})
    cli = resolve_lark_cli()
    cli_available = Path(cli).is_file() if "/" in cli else bool(__import__("shutil").which(cli))
    checks.append({"name": "lark_cli", "ok": cli_available, "value": cli})

    if args.server_url:
        expected = args.server_url.rstrip("/") + "/api/auth/feishu/callback"
        redirect_ok = not redirect_uri or (redirect_uri == expected and not _is_loopback_url(redirect_uri))
        checks.append({"name": "server_redirect", "ok": redirect_ok, "expected": expected})
    elif redirect_uri:
        checks.append({"name": "redirect_syntax", "ok": bool(urlparse(redirect_uri).scheme and urlparse(redirect_uri).netloc)})

    if args.live and cli_available:
        for profile in profiles:
            try:
                payload = _run_json([cli, "whoami", "--as", "bot", "--profile", profile])
                checks.append({
                    "name": f"bot_profile:{profile}",
                    "ok": payload.get("identity") == "bot" and payload.get("available") is True,
                })
            except Exception as exc:
                checks.append({"name": f"bot_profile:{profile}", "ok": False, "error": str(exc)[:300]})

        directory_profile = str(
            os.environ.get("CMHK_FEISHU_DIRECTORY_PROFILE")
            or subscriptions.get("directory_profile")
            or ""
        )
        delivery_profile = str(
            os.environ.get("CMHK_FEISHU_DELIVERY_PROFILE")
            or subscriptions.get("delivery_profile")
            or ""
        )
        primary_profile = str(
            os.environ.get("CMHK_FEISHU_PROFILE")
            or bot.get("profile")
            or ""
        )
        live_commands = [
            (
                "contact_read",
                [cli, "api", "GET", "/open-apis/contact/v3/departments/0/children",
                 "--params", '{"department_id_type":"open_department_id","fetch_child":true,"page_size":1}',
                 "--as", "bot", "--profile", directory_profile, "--format", "json"],
            ),
            (
                "chat_read",
                [cli, "api", "GET", "/open-apis/im/v1/chats", "--params", '{"page_size":1}',
                 "--as", "bot", "--profile", delivery_profile, "--format", "json"],
            ),
        ]
        ledger = config.get("error_ledger") if isinstance(config.get("error_ledger"), dict) else {}
        spreadsheet_token = str(ledger.get("spreadsheet_token") or "")
        if spreadsheet_token:
            live_commands.append((
                "sheet_read",
                [cli, "sheets", "+workbook-info", "--spreadsheet-token", spreadsheet_token,
                 "--as", "bot", "--profile", primary_profile, "--format", "json"],
            ))
        if drive_probe_token:
            drive_probe_type = os.environ.get("CMHK_FEISHU_DRIVE_PROBE_TYPE", "file").strip()
            live_commands.append((
                "drive_statistics_read",
                [cli, "drive", "file.statistics", "get", "--file-token", drive_probe_token,
                 "--file-type", drive_probe_type, "--as", "bot", "--profile", delivery_profile,
                 "--format", "json"],
            ))
        for name, command in live_commands:
            try:
                _run_json(command)
                checks.append({"name": name, "ok": True})
            except Exception as exc:
                checks.append({"name": name, "ok": False, "error": str(exc)[:300]})

    ok = all(bool(item.get("ok")) for item in checks)
    print(json.dumps({"ok": ok, "live": args.live, "checks": checks}, ensure_ascii=False, indent=2))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
