"""Portable runtime helpers shared by every Feishu integration.

The production server must not inherit Homebrew paths or a developer's macOS
keychain.  Commands resolve from explicit deployment configuration first and
then from PATH; named lark-cli profiles remain the boundary between Feishu apps.
"""
from __future__ import annotations

import os
import shutil
from collections.abc import Mapping, Sequence


PROXY_ENV_KEYS = (
    "HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY",
    "http_proxy", "https_proxy", "all_proxy",
)


def resolve_lark_cli(environ: Mapping[str, str] | None = None) -> str:
    env = environ or os.environ
    configured = str(env.get("LARK_CLI_PATH") or env.get("LARK_CLI") or "").strip()
    if configured:
        return shutil.which(configured) or configured
    return shutil.which("lark-cli") or "lark-cli"


def lark_cli_env(environ: Mapping[str, str] | None = None) -> dict[str, str]:
    env = dict(environ or os.environ)
    env["LARK_CLI_NO_PROXY"] = "1"
    env["LARKSUITE_CLI_NO_UPDATE_NOTIFIER"] = "1"
    env["LARKSUITE_CLI_NO_SKILLS_NOTIFIER"] = "1"
    for key in PROXY_ENV_KEYS:
        env.pop(key, None)
    return env


def portable_lark_argv(
    argv: Sequence[str],
    environ: Mapping[str, str] | None = None,
) -> list[str]:
    command = [str(item) for item in argv]
    if command and command[0] == "lark-cli":
        command[0] = resolve_lark_cli(environ)
    return command
