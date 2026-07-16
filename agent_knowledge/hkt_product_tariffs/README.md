# HKT/csl/1O1O/HKT SME/NETVIGATOR 产品资费监测数据库

更新时间（HKT）：2026-07-13T08:53:30+08:00

## 覆盖范围

- csl 5G 消费者套餐公开资费页
- 1O1O 5G 高端/多用户套餐公开资费页
- HKT SME 5G Business Mobile 公开资费页
- NETVIGATOR 家庭宽频当前优惠页和官方标准价目表
- HKT/csl 官方 Internet Access、Business Broadband、Premium Broadband、MegaLink、Datapak/Private Circuit、Metro IP、Flexible Bandwidth、Telecommunications Backup、one communications、eye Service、Home Phone/Local Telephone、2G/3G/4G Mobile、U-plan、Smart Pama、The Club SIM 与 csl/1O1O 2018 postpaid PDF 资费表（作为官方 tariff/list price，不等同促销价）
- HKT Enterprise 5G 企业移动/宽频产品公开页面（若页面只披露产品描述，则标记为 review_required 或 source_fetched_no_plan_rows）

## 当前抓取概览

- 覆盖品牌：1O1O, HKT, HKT Enterprise, HKT SME, NETVIGATOR, csl
- 当前记录：97 条
- 已结构化解析：93 条
- 来源页面：17 个
- 官方历史快照：169 个
- 历史记录：1229 条，其中已结构化 1228 条
- 历史覆盖年份：2007, 2008, 2009, 2010, 2011, 2012, 2013, 2014, 2015, 2016, 2017, 2018, 2019, 2020, 2021, 2022, 2023, 2024, 2025, 2026
- 来源缺口：5 条；缺口不估算。

## 主要文件

- `latest_products.csv`：本次抓取的最新套餐/产品结构化表。
- `historical_tariffs.csv`：公开官方归档快照和官方 PDF 资费表解析出的历史套餐表。
- `structured_current_plans.csv`：面向分析和人工审核的当前套餐宽表。
- `structured_historical_plans.csv`：面向分析和人工审核的历史套餐宽表。
- `structured_source_gaps.csv`：可访问但不能结构化、或抓取失败的缺口清单，禁止估算。
- `hkt_product_tariffs_structured.xlsx`：包含当前套餐、历史套餐、来源缺口和字段说明的人工审核工作簿。
- `product_history.csv`：按产品特征去重后的历史快照，保留 first_seen/last_seen。
- `source_snapshots.json`：每个官方页面的抓取状态、哈希和证据摘录。
- `change_log.md`：相对上一次运行的新增/消失记录。

## 合规口径

仅抓取公开官方页面；不登录、不绕过权限、不抓取个人数据；沿用主爬虫的 source_registry、robots、代理和敏感信息过滤流程。
