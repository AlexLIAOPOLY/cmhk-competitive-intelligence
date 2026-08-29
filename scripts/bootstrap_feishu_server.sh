#!/usr/bin/env bash
set -euo pipefail

project_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$project_dir"

lark_cli="${LARK_CLI_PATH:-${LARK_CLI:-lark-cli}}"
primary_app_id="${CMHK_FEISHU_APP_ID:-${FEISHU_APP_ID:-}}"
primary_secret="${CMHK_FEISHU_APP_SECRET:-${FEISHU_APP_SECRET:-}}"
primary_profile="${CMHK_FEISHU_PROFILE:-${primary_app_id}}"
delivery_app_id="${CMHK_FEISHU_DELIVERY_APP_ID:-}"
delivery_secret="${CMHK_FEISHU_DELIVERY_APP_SECRET:-}"
delivery_profile="${CMHK_FEISHU_DELIVERY_PROFILE:-cmhk-innovation-digital}"
database_token="${CMHK_DATABASE_SHEET_SPREADSHEET_TOKEN:-ZrzWsMF4Dhq5zDtXZZ4cpHcKnfA}"
database_profile="${CMHK_DATABASE_SHEET_PROFILE:-${primary_profile}}"
database_identity="${CMHK_DATABASE_SHEET_IDENTITY:-bot}"

if [[ -z "$primary_app_id" || -z "$primary_secret" ]]; then
  echo "Missing CMHK_FEISHU_APP_ID or CMHK_FEISHU_APP_SECRET" >&2
  exit 2
fi

if ! command -v "$lark_cli" >/dev/null 2>&1 && [[ ! -x "$lark_cli" ]]; then
  echo "lark-cli not found; set LARK_CLI_PATH to its absolute server path" >&2
  exit 2
fi

printf '%s' "$primary_secret" | "$lark_cli" config init \
  --app-id "$primary_app_id" --app-secret-stdin --brand feishu --name "$primary_profile"
"$lark_cli" config default-as bot --profile "$primary_profile" >/dev/null
"$lark_cli" whoami --as bot --profile "$primary_profile" >/dev/null

if [[ "$database_identity" != "bot" ]]; then
  echo "Server database-sheet sync requires CMHK_DATABASE_SHEET_IDENTITY=bot" >&2
  exit 2
fi
if [[ "$database_profile" != "$primary_profile" ]]; then
  printf '%s' "$primary_secret" | "$lark_cli" config init \
    --app-id "$primary_app_id" --app-secret-stdin --brand feishu --name "$database_profile"
fi
"$lark_cli" whoami --as bot --profile "$database_profile" >/dev/null
"$lark_cli" sheets +workbook-info \
  --spreadsheet-token "$database_token" \
  --as bot --profile "$database_profile" --format json >/dev/null

if [[ -n "$delivery_app_id" || -n "$delivery_secret" ]]; then
  if [[ -z "$delivery_app_id" || -z "$delivery_secret" ]]; then
    echo "CMHK_FEISHU_DELIVERY_APP_ID and CMHK_FEISHU_DELIVERY_APP_SECRET must be set together" >&2
    exit 2
  fi
  printf '%s' "$delivery_secret" | "$lark_cli" config init \
    --app-id "$delivery_app_id" --app-secret-stdin --brand feishu --name "$delivery_profile"
  "$lark_cli" config default-as bot --profile "$delivery_profile" >/dev/null
  "$lark_cli" whoami --as bot --profile "$delivery_profile" >/dev/null
fi

echo "Feishu server profiles initialized; bot identity and database workbook access verified."
echo "Run: python3 scripts/check_feishu_server_readiness.py --live --require-drive --require-database-sheet"
