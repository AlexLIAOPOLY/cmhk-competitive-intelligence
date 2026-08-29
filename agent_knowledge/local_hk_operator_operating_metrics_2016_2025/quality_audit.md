# 香港本地運營商經營指標庫質量審計

- 結構與來源門禁：`pass`
- 全網缺口補搜：`pending`（仍待逐格補搜 1134 行）
- 明細行：1434
- 有值行：298
- 明確缺口：1136
- 三家全量审计格：930/930
- 三家缺口有理由：677/677
- 三家缺口有复核来源：677/677
- 官方來源條目：99
- 重複鍵：0
- 無效來源引用：0

`pass` 只代表目前數據列的結構、來源綁定與缺口理由通過門禁，不代表所有公開網頁已搜尋完成。

## 質量規則

- Every audited operator × year × metric key must have exactly one row.
- Every value must have bound official evidence.
- Every gap must contain a structured reason and the reviewed official sources.
- Issuer-material review is not labelled as proof that the entire public web has no value.
- Related-scope public values are retained but never substituted for the requested metric.
- No analyst interpolation.
- Pre-commercial 5G zeroes and normalized qualitative disclosures must be explicitly labelled.
- A source gap is not silently treated as zero.
- Annual average ARPU and exit ARPU are separate metrics.
- Fiscal year end and scope breaks must be applied before comparison.
