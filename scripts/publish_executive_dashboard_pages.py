#!/usr/bin/env python3
from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
STATIC_DIR = ROOT / "web" / "static"
DATA_DIR = ROOT / "strategy_briefing"
STATE_PATH = DATA_DIR / "dashboard_pages_publish_state.json"
LOCK_PATH = DATA_DIR / "dashboard_pages_publish.lock"
HKT = ZoneInfo("Asia/Hong_Kong")
DEFAULT_REPOSITORY = "https://github.com/AlexLIAOPOLY/cmhk-competitive-intelligence.git"
DEFAULT_PUBLIC_URL = "https://alexliaopoly.github.io/cmhk-competitive-intelligence/"


def _run(
    command: list[str],
    *,
    cwd: Path | None = None,
    check: bool = True,
) -> subprocess.CompletedProcess[str]:
    environment = os.environ.copy()
    for name in (
        "HTTP_PROXY",
        "HTTPS_PROXY",
        "ALL_PROXY",
        "http_proxy",
        "https_proxy",
        "all_proxy",
    ):
        environment.pop(name, None)
    return subprocess.run(
        command,
        cwd=str(cwd) if cwd else None,
        env=environment,
        text=True,
        capture_output=True,
        check=check,
    )


def _git(*parts: str) -> list[str]:
    return ["git", "-c", "http.proxy=", "-c", "https.proxy=", *parts]


def _read_state() -> dict[str, Any]:
    try:
        value = json.loads(STATE_PATH.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def _write_state(payload: dict[str, Any]) -> None:
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    temporary = STATE_PATH.with_suffix(".json.tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    temporary.replace(STATE_PATH)


def _now_iso() -> str:
    return datetime.now(HKT).isoformat(timespec="seconds")


def _public_news_payload() -> dict[str, Any]:
    from strategic_briefing import public_snapshot

    snapshot = public_snapshot()
    published_path = DATA_DIR / "published.json"
    try:
        published_payload = json.loads(published_path.read_text(encoding="utf-8"))
        generated_at = str(published_payload.get("updated_at") or "")
    except (OSError, json.JSONDecodeError, AttributeError):
        generated_at = ""
    items: list[dict[str, Any]] = []
    for item in (snapshot.get("items") or [])[:8]:
        if not isinstance(item, dict):
            continue
        items.append(
            {
                key: item.get(key)
                for key in (
                    "id",
                    "title",
                    "summary",
                    "category",
                    "source_url",
                    "published_at",
                )
            }
        )
    return {"ok": True, "generated_at": generated_at, "items": items}


def _build_site(destination: Path) -> tuple[str, dict[str, Any]]:
    destination.mkdir(parents=True, exist_ok=True)
    html = (STATIC_DIR / "executive-dashboard-demo.html").read_text(encoding="utf-8")
    html = html.replace(
        'href="/static/executive-dashboard-demo.css',
        'href="./executive-dashboard-demo.css',
    )
    html = html.replace(
        'src="/static/assets/executive-dashboard/',
        'src="./assets/executive-dashboard/',
    )
    html = html.replace(
        'src="/static/executive-dashboard-demo.js',
        'src="./executive-dashboard-demo.js',
    )
    html = html.replace(
        'src="/static/executive-dashboard-drilldown.js',
        'src="./executive-dashboard-drilldown.js',
    )
    (destination / "index.html").write_text(html, encoding="utf-8")
    shutil.copy2(
        STATIC_DIR / "executive-dashboard-demo.css",
        destination / "executive-dashboard-demo.css",
    )
    script = (STATIC_DIR / "executive-dashboard-demo.js").read_text(encoding="utf-8")
    script = script.replace(
        'fetch("/api/strategic-briefs"',
        'fetch("./strategic-briefs.json"',
    )
    (destination / "executive-dashboard-demo.js").write_text(script, encoding="utf-8")
    shutil.copy2(
        STATIC_DIR / "executive-dashboard-drilldown.js",
        destination / "executive-dashboard-drilldown.js",
    )
    shutil.copytree(
        STATIC_DIR / "assets" / "executive-dashboard",
        destination / "assets" / "executive-dashboard",
    )
    (destination / ".nojekyll").touch()

    payload = dict(_public_news_payload())
    digest = hashlib.sha256()
    for path in sorted(item for item in destination.rglob("*") if item.is_file()):
        if path.name == ".DS_Store":
            continue
        digest.update(str(path.relative_to(destination)).encode("utf-8"))
        digest.update(path.read_bytes())
    digest.update(
        json.dumps(
            {
                "ok": bool(payload.get("ok")),
                "items": payload.get("items") or [],
            },
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    )
    site_version = digest.hexdigest()
    payload["site_version"] = site_version
    (destination / "strategic-briefs.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return site_version, payload


def _verify(public_url: str, site_version: str) -> None:
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    target = public_url.rstrip("/") + "/strategic-briefs.json"
    last_error = ""
    for _ in range(24):
        try:
            request = urllib.request.Request(
                target,
                headers={"User-Agent": "CMHK dashboard publisher"},
            )
            with opener.open(request, timeout=20) as response:
                payload = json.loads(response.read().decode("utf-8"))
            if response.status == 200 and payload.get("site_version") == site_version:
                return
            last_error = "deployed snapshot has not reached the expected version"
        except Exception as exc:
            last_error = str(exc)
        time.sleep(5)
    raise RuntimeError(last_error or "public verification timed out")


def publish(*, force: bool = False, dry_run: bool = False) -> dict[str, Any]:
    repository = os.environ.get(
        "CMHK_DASHBOARD_PAGES_REPOSITORY",
        DEFAULT_REPOSITORY,
    ).strip()
    branch = os.environ.get("CMHK_DASHBOARD_PAGES_BRANCH", "gh-pages").strip()
    public_url = os.environ.get(
        "CMHK_DASHBOARD_PAGES_PUBLIC_URL",
        DEFAULT_PUBLIC_URL,
    ).strip()

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    with LOCK_PATH.open("a+") as lock:
        try:
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return {"status": "busy"}

        state = _read_state()
        state["last_started_at"] = _now_iso()
        _write_state(state)
        try:
            with tempfile.TemporaryDirectory(prefix="cmhk-dashboard-pages-") as temp:
                temp_root = Path(temp)
                generated = temp_root / "generated"
                site_version, payload = _build_site(generated)
                if not force and site_version == state.get("last_site_version"):
                    return {
                        "status": "unchanged",
                        "site_version": site_version,
                        "item_count": len(payload["items"]),
                        "public_url": public_url,
                    }
                if dry_run:
                    return {
                        "status": "dry_run",
                        "site_version": site_version,
                        "item_count": len(payload["items"]),
                        "public_url": public_url,
                    }

                checkout = temp_root / "checkout"
                _run(
                    _git(
                        "clone",
                        "--depth",
                        "1",
                        "--branch",
                        branch,
                        repository,
                        str(checkout),
                    )
                )
                for child in checkout.iterdir():
                    if child.name == ".git":
                        continue
                    if child.is_dir() and not child.is_symlink():
                        shutil.rmtree(child)
                    else:
                        child.unlink()
                for child in generated.iterdir():
                    target = checkout / child.name
                    if child.is_dir():
                        shutil.copytree(child, target)
                    else:
                        shutil.copy2(child, target)

                _run(_git("add", "-A"), cwd=checkout)
                changed = bool(
                    _run(_git("status", "--porcelain"), cwd=checkout).stdout.strip()
                )
                if changed:
                    _run(
                        _git("config", "user.name", "CMHK Dashboard Publisher"),
                        cwd=checkout,
                    )
                    _run(
                        _git(
                            "config",
                            "user.email",
                            "cmhk-dashboard@users.noreply.github.com",
                        ),
                        cwd=checkout,
                    )
                    _run(
                        _git("commit", "-m", "Update public dashboard snapshot"),
                        cwd=checkout,
                    )
                    _run(_git("push", "origin", branch), cwd=checkout)
                commit = _run(_git("rev-parse", "HEAD"), cwd=checkout).stdout.strip()
                _verify(public_url, site_version)
                result = {
                    "status": "published" if changed else "verified",
                    "site_version": site_version,
                    "item_count": len(payload["items"]),
                    "public_url": public_url,
                    "commit": commit,
                }
                _write_state(
                    {
                        **state,
                        "last_site_version": site_version,
                        "last_published_at": _now_iso(),
                        "last_result": result,
                        "last_error": "",
                    }
                )
                return result
        except Exception as exc:
            _write_state(
                {
                    **state,
                    "last_error_at": _now_iso(),
                    "last_error": str(exc)[:1000],
                }
            )
            raise


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    print(
        json.dumps(
            publish(force=args.force, dry_run=args.dry_run),
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
