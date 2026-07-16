#!/usr/bin/env bash
set -euo pipefail

LABEL="com.liaowang.cmhk-web-app"
DOMAIN="gui/$(id -u)"

launchctl bootout "$DOMAIN/$LABEL" >/dev/null 2>&1 || true
launchctl disable "$DOMAIN/$LABEL"

echo "CMHK APP service stopped and disabled."
