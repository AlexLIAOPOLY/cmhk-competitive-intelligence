# Source URL Reachability Audit (2026-06-19)

- Unique URLs checked: 705
- OK: 571
- Reachable/restricted: 133
- HTTP errors: 0
- Timeouts: 0
- SSL errors: 1
- Network errors: 0

## Status Counts

- ok: 571
- reachable_restricted: 133
- ssl_error: 1

## Hosts With Non-OK Results

- reg.hkbn.net: reachable_restricted=38
- wap.sasac.gov.cn: ssl_error=1
- www.sec.gov: reachable_restricted=95

## Scope

- Checks each unique URL referenced by official_source_url, primary_source_url, and verification_sources across the three main packages.
- `ok` means HTTP 2xx/3xx was returned by HEAD or small-range GET.
- `reachable_restricted` means the host responded with an access-control status such as 401/403/405/429; these require browser/manual review when adding or refreshing data, but still indicate the URL host is live.
- This audit does not re-validate every numeric value; it verifies that preserved source links remain machine-checkable or explicitly flagged.
