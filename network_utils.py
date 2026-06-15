from __future__ import annotations

import os
import re
import socket
import urllib.error
import urllib.request


LOCAL_PROXY_CANDIDATES = (
    "http://127.0.0.1:7897",
    "http://127.0.0.1:7890",
)


def _available_proxy_urls() -> list[str]:
    configured = [
        os.environ.get(key, "")
        for key in ("HTTPS_PROXY", "HTTP_PROXY", "ALL_PROXY", "https_proxy", "http_proxy", "all_proxy")
    ]
    available: list[str] = []
    for proxy_url in dict.fromkeys([*configured, *LOCAL_PROXY_CANDIDATES]):
        if not proxy_url:
            continue
        match = re.match(r"^https?://([^:/]+):(\d+)$", proxy_url)
        if not match:
            continue
        try:
            with socket.create_connection((match.group(1), int(match.group(2))), timeout=0.8):
                pass
        except OSError:
            continue
        available.append(proxy_url)
    return available


def urlopen_with_local_proxy_fallback(
    request: urllib.request.Request,
    *,
    timeout: float,
):
    try:
        return urllib.request.urlopen(request, timeout=timeout)
    except urllib.error.URLError as direct_error:
        last_error: Exception = direct_error
        for proxy_url in _available_proxy_urls():
            opener = urllib.request.build_opener(
                urllib.request.ProxyHandler({"http": proxy_url, "https": proxy_url})
            )
            try:
                return opener.open(request, timeout=timeout)
            except Exception as exc:
                last_error = exc
        raise last_error
