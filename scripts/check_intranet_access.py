#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from cmhk.intranet import intranet_access_urls


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _request(url: str) -> tuple[int, bytes, dict[str, str]]:
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), _NoRedirect())
    request = urllib.request.Request(url, headers={"User-Agent": "CMHK intranet self-check/1.0"})
    try:
        with opener.open(request, timeout=5) as response:
            return response.status, response.read(), dict(response.headers)
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read(), dict(exc.headers)


def check_url(base_url: str) -> tuple[bool, str]:
    try:
        root_status, _, root_headers = _request(base_url + "/")
        config_status, config_body, _ = _request(base_url + "/api/auth/config")
        config = json.loads(config_body.decode("utf-8"))
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        return False, str(exc)

    expected_callback = base_url + "/api/auth/feishu/callback"
    actual_callback = str(config.get("feishu", {}).get("callbackUri", ""))
    root_ok = root_status in {200, 302}
    config_ok = config_status == 200 and config.get("ok") is True
    callback_ok = actual_callback == expected_callback
    collaboration = config.get("collaboration") if isinstance(config.get("collaboration"), dict) else {}
    identity_ok = collaboration.get("perUserIdentity") is True
    login_audit_ok = collaboration.get("loginAudit") is True
    shared_state_ok = collaboration.get("sharedServerState") is True
    message = (
        f"root={root_status}, auth-config={config_status}, "
        f"callback={'matched' if callback_ok else actual_callback or 'missing'}, "
        f"identity={'per-user' if identity_ok else 'not-ready'}, "
        f"login-audit={'enabled' if login_audit_ok else 'missing'}, "
        f"shared-state={'server' if shared_state_ok else 'missing'}"
    )
    return (
        root_ok
        and config_ok
        and callback_ok
        and identity_ok
        and login_audit_ok
        and shared_state_ok
        and bool(root_headers)
    ), message


def main() -> int:
    parser = argparse.ArgumentParser(description="Check CMHK access through this Mac's intranet IP.")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--host", default="0.0.0.0")
    args = parser.parse_args()

    urls = intranet_access_urls(args.port, host=args.host)
    if not urls:
        print("未找到可用的 RFC1918 内网 IPv4 地址。", file=sys.stderr)
        return 2

    passed = False
    print("内网访问地址：")
    for url in urls:
        ok, detail = check_url(url)
        passed = passed or ok
        print(f"  {'PASS' if ok else 'FAIL'}  {url}  ({detail})")
    if passed:
        print("同事连接同一公司内网后，可直接打开上述 PASS 地址。")
        return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
