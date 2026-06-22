# External Dataset Search Audit

Date: 2026-06-19

## Requirement Being Audited

Assess whether downloadable external datasets can replace or augment the current competitor/cloud-vendor/CMHK-related data work. If more complete verified datasets are available, adapt them; otherwise keep the existing collected data.

## Search Findings

### Official / Public Sources

- **SEC companyfacts API**: downloaded AMZN, MSFT, GOOGL and ORCL JSON. Decision: augment only. It does not expose a complete comparable cloud-segment quarterly sequence for AWS, Intelligent Cloud, Google Cloud or Oracle Cloud.
- **SEC Financial Statement Data Sets**: official quarterly ZIPs since 2009. Decision: reject as replacement, possible auxiliary. They cover XBRL face financial statements and do not solve cloud segment/product-line disclosure boundaries.
- **HK data.gov.hk / OFCA / C&SD**: official public-sector datasets. Decision: already adapted in `cmhk_macro_policy_2026-06-19`.
- **HKEX Historical Data Products**: corporate-document archives are downloadable after subscription/payment. Decision: reject as replacement because they are paid document archives, not structured verified operating-metric rows.
- **Company IR filings and official reports**: remain the primary source family for period-level operating metrics. Decision: keep primary.

### Filing Indexes / APIs

- **FinancialReports.eu**: broad filing index across 109 markets, free web search, paid/API/S3 options. Decision: possible filing discovery only. It is not a verified target metric dataset and should not replace the current audit schema.
- **Finnhub and similar financial fundamentals APIs**: useful for screening but require API access and do not preserve the row-level official evidence and verification fields. Decision: reject as formal replacement.

### Secondary / Commercial Market Sources

- **Kaggle cloud service providers financials**: secondary community dataset. Decision: reject as replacement because accessible metadata does not prove official row-level evidence or verification controls.
- **MacroMicro cloud chart**: public chart reference. Decision: reject as replacement.
- **Synergy Research / Statista / Dataxis / Bloomberg / LSEG / IBISWorld / similar commercial products**: useful market context or paid data products, but not directly usable as formal operating metric rows without independent official verification. Decision: reject as replacement; use only as qualitative context or source-discovery leads.

## Current Decision

No external dataset found so far is more complete and audit-ready than the existing `quarterly_competitor_metrics_2026-06-18` operating metrics package. The current formal package remains authoritative because it preserves:

- `official_value`
- evidence notes
- `verification_count`
- source links
- conflict status
- source-gap status
- forecast exclusion boundaries

External datasets may be used only as auxiliary filing discovery or screening inputs unless their values are re-extracted from official/public sources and loaded into the current row-level schema.
