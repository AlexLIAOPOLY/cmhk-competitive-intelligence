# 爬虫运行日志索引

这个数据集用于让小竞 AI 明确知道每次爬虫日志在哪里、如何追溯、如何调度使用。

## 保存策略

- 飞书日志子表：保存完整逐 URL 爬虫日志，并在 Agent 数据整理完成后追加 Agent 处理流程与结果。
- 本地运行索引：保存轻量摘要、飞书日志页链接、本地审计文件路径和 Agent run_id，供 Agent 快速检索。

## 主要文件

- `index.md`：最近运行的人类可读索引。
- `index.json`：最近多次运行的结构化索引。
- `latest.json`：最新一次运行摘要。
- `runs/<crawl_run_id>.json`：单次运行详情。

## Agent 使用规则

当用户询问爬虫运行、失败链接、覆盖率、飞书日志、Agent 调度或上次爬虫结果时，先读取本数据集，再按需要读取 `/references/run_log.tsv`、`/references/coverage_report.tsv`、`/references/final_audit.md` 或打开飞书日志页。
