#!/bin/zsh
set -euo pipefail

repo_dir="${0:A:h:h}"
runtime_dir="${CMHK_RUNTIME_ROOT:-$HOME/cmhk_public_crawl_app}"
label="com.liaowang.cmhk-feishu-media-metrics"
agent_file="$HOME/Library/LaunchAgents/${label}.plist"
log_dir="$runtime_dir/var/feishu_media_metrics"
first_install=0
if [[ ! -f "$agent_file" ]]; then
  first_install=1
fi

mkdir -p "$HOME/Library/LaunchAgents" "$log_dir"

# First installation is a test-only activation: acknowledge today's elapsed
# slots so loading the daemon can never cause an immediate group send.
python3 - "$repo_dir/var/feishu_media_metrics/state.json" "$runtime_dir/var/feishu_media_metrics/state.json" "$first_install" <<'PY'
import json
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

target = Path(sys.argv[1])
mirror = Path(sys.argv[2])
first_install = sys.argv[3] == "1"
state_source = mirror if mirror.exists() else target
state = json.loads(state_source.read_text(encoding="utf-8")) if state_source.exists() else {}
sent = state.setdefault("sent_slots", {})
if first_install:
    now = datetime.now(ZoneInfo("Asia/Hong_Kong"))
    for hour in (10, 17):
        scheduled = now.replace(hour=hour, minute=0, second=0, microsecond=0)
        if scheduled <= now:
            sent.setdefault(scheduled.strftime("%Y%m%d-%H00"), "suppressed-at-test-install")
target.parent.mkdir(parents=True, exist_ok=True)
target.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
mirror.parent.mkdir(parents=True, exist_ok=True)
mirror.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
PY

python3 - "$agent_file" "$repo_dir" "$log_dir" "$runtime_dir" <<'PY'
import plistlib
import sys
from pathlib import Path

target = Path(sys.argv[1])
root = Path(sys.argv[2])
logs = Path(sys.argv[3])
runtime = Path(sys.argv[4])
payload = {
    "Label": "com.liaowang.cmhk-feishu-media-metrics",
    "ProgramArguments": [
        "/usr/bin/env",
        "python3",
        str(runtime / "scripts" / "feishu_media_metrics_report.py"),
        "--config",
        str(runtime / "config" / "feishu_media_metrics.local.json"),
        "--state",
        str(runtime / "var" / "feishu_media_metrics" / "state.json"),
        "--daemon",
    ],
    "WorkingDirectory": str(runtime),
    "RunAtLoad": True,
    "KeepAlive": {"SuccessfulExit": False},
    "ThrottleInterval": 30,
    "ProcessType": "Background",
    "EnvironmentVariables": {
        "PATH": "/opt/homebrew/Caskroom/miniconda/base/bin:/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin",
        "LARK_CLI_NO_PROXY": "1",
        "LARKSUITE_CLI_NO_UPDATE_NOTIFIER": "1",
        "LARKSUITE_CLI_NO_SKILLS_NOTIFIER": "1",
    },
    "StandardOutPath": str(logs / "daemon.stdout.log"),
    "StandardErrorPath": str(logs / "daemon.stderr.log"),
}
target.write_bytes(plistlib.dumps(payload, sort_keys=False))
PY

domain="gui/$(id -u)"
launchctl bootout "$domain" "$agent_file" >/dev/null 2>&1 || true
launchctl bootstrap "$domain" "$agent_file"
launchctl enable "$domain/$label"
launchctl kickstart -k "$domain/$label"
launchctl print "$domain/$label" >/dev/null

echo "installed:$label"
