# Cloud Vendor Data Index

## Formal Sources

| Purpose | Source package | Notes |
| --- | --- | --- |
| Period-level cloud vendor metrics | `agent_knowledge/quarterly_competitor_metrics_2026-06-18/` | Use for formal quarterly/period values, source-gap status, `official_value`, evidence notes and verification count. |
| Concise FY2023-FY2025 cloud summary | `agent_knowledge/cloud_vendor_metrics_2026-06-17/` | Hidden from default picker; useful for quick three-year cloud business summaries. |
| External downloadable dataset assessment | `agent_knowledge/external_dataset_assessment_2026-06-19/` | Hidden from default picker; use when users ask whether SEC/HKEX/Kaggle/Finnhub/etc. can replace the current data. |
| Source-gap and forecast boundaries | `agent_knowledge/quarterly_competitor_metrics_2026-06-18/cloud_source_gap_integrity_2026-06-18.md` | Use before forecasting or comparing cloud vendors with different disclosure boundaries. |

## User-Facing Rule

When the user asks about cloud vendors, treat this database as the front door. Internally retrieve the formal rows and audit files listed above.

## Disclosure Caveats

- Microsoft Azure is not disclosed as standalone Azure revenue; use Intelligent Cloud / Server products and cloud services proxy with caveats.
- Tencent Cloud is not disclosed as standalone cloud revenue; use Tencent FinTech and Business Services proxy only with caveats.
- Huawei Cloud has limited public periodic disclosure and remains source-gap/limited-disclosure unless official periodic values are available.
- Google Cloud, Alibaba Cloud and Oracle Cloud have historical disclosure-boundary gaps; do not estimate missing quarters.

