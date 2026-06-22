# External Dataset Replacement / Augmentation Assessment

Build date: 2026-06-19

## Bottom Line

No downloaded external dataset is suitable to replace the current audited `quarterly_competitor_metrics_2026-06-18` competitor/cloud package.

The current package should stay as the formal operating-metrics source because it preserves row-level `official_value`, evidence notes, `verification_count`, conflict status and source-gap status. The external datasets found are useful only as source discovery or macro-context inputs.

Current formal package size: `quarterly_competitor_metrics_2026-06-18/quarterly_metrics.csv` has 3,013 rows. If another process note mentions an intermediate 3,005-row rebuild, treat that as superseded and use the manifest, integrity audit and primary CSV row count instead.

## What Was Downloaded

SEC official companyfacts JSON was downloaded and cached for:

- `data/external_dataset_candidates/sec_companyfacts/AMZN_CIK0001018724.json`
- `data/external_dataset_candidates/sec_companyfacts/MSFT_CIK0000789019.json`
- `data/external_dataset_candidates/sec_companyfacts/GOOGL_CIK0001652044.json`
- `data/external_dataset_candidates/sec_companyfacts/ORCL_CIK0001341439.json`

Assessment result: keep these as auxiliary official filing data. Do not adapt them as replacement quarterly cloud vendor metrics because companyfacts does not expose a complete cloud-segment quarterly series for AWS, Intelligent Cloud, Google Cloud or Oracle Cloud.

Additional source-page snapshots were cached for audit traceability:

- `data/external_dataset_candidates/source_pages/sec_financial_statement_data_sets.html`
- `data/external_dataset_candidates/source_pages/hkex_historical_data_products.html`
- `data/external_dataset_candidates/source_pages/financialreports_eu_home.html`

These snapshots are not normalized metric datasets. They only document that the source families were reviewed.

## Candidate Decisions

| Candidate | Decision | Reason |
| --- | --- | --- |
| HK data.gov.hk / OFCA / C&SD | Already adapted | Official, downloadable public-sector source; already integrated in `cmhk_macro_policy_2026-06-19`. |
| SEC companyfacts API | Augment only | Official and downloadable, but dimensional segment cloud series are incomplete or unavailable in companyfacts. Use for filing discovery/cross-check, not formal cloud segment conclusions. |
| SEC Financial Statement Data Sets | Reject as replacement / possible auxiliary | Official downloadable quarterly ZIPs since 2009, but they provide XBRL face financial statement data and are explicitly not a substitute for full filings. They do not solve cloud segment/product-line disclosure boundaries. |
| HKEX Historical Data Products - corporate documents | Reject as replacement / paid filing archive | Main Board annual/interim report archive and GEM annual/quarterly report archive are paid historical document products, not a free structured operating-metric dataset. They may help source discovery if subscribed, but do not replace row-level metric extraction. |
| FinancialReports.eu filing index/API | Reject as replacement / possible filing discovery | Broad filing index across markets with free web search and paid/API/S3 options. It indexes filings rather than providing audited target metric rows, and its own disclaimer does not guarantee completeness or accuracy. |
| Finnhub / commercial fundamentals APIs | Reject as replacement | API-based financial statement products can be useful for screening, but they require API access and do not preserve the required official evidence notes, verification_count, conflict handling and source-gap status for each target metric. |
| Company IR filings and reports | Keep as primary row-level source | Official reports remain the best evidence for segment/product-line operating metrics. Existing curated rows preserve official values and source-gap controls. |
| Kaggle cloud service providers financials | Reject as replacement | Non-official secondary dataset; no reliable row-level official evidence and verification-count controls in the accessible metadata. |
| MacroMicro cloud chart | Reject as replacement | Useful as a public chart reference, but not an official downloadable audited dataset for formal conclusions. |
| Synergy Research / Statista / Dataxis / commercial market datasets | Reject as replacement | Paywalled or secondary market-share/research data; cannot satisfy row-level official/public source preservation for each operating data point. |

## Agent Use

- If a user asks whether a more comprehensive downloadable dataset replaced the current database, answer: no replacement was found; official/public external datasets were assessed, and the audited local package remains authoritative.
- If a user asks whether SEC data can be used, answer: it can help locate filings for AMZN/MSFT/GOOGL/ORCL, but it must not replace the official segment/product-line extraction in the quarterly package.
- If a user asks whether HKEX, FinancialReports.eu, Finnhub or other financial-data APIs should replace the current package, answer: they may help discover filings or screen values, but they do not satisfy the row-level official-source/evidence/verification/source-gap requirements unless every extracted value is re-verified and normalized into the current audit schema.
- If a user asks for macro/policy context, use `cmhk_macro_policy_2026-06-19`; those government data sources are already adapted.
- If a user asks for competitor/cloud operating metrics, use `quarterly_competitor_metrics_2026-06-18` and its audits.

## Current Formal Sources After Assessment

- Competitor and cloud operating metrics: `agent_knowledge/quarterly_competitor_metrics_2026-06-18/`
- Legacy three-year cloud summary: `agent_knowledge/cloud_vendor_metrics_2026-06-17/` remains useful for concise FY2023-FY2025 summaries, but the newer quarterly package is preferred for period-level analysis.
- CMHK macro/policy/institutional context: `agent_knowledge/cmhk_macro_policy_2026-06-19/`
