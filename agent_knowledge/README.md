# Agent Knowledge 数据接入规范

这个目录是小竞 AI 后端允许读取和检索的本地知识库根目录。

## 后端可访问范围

Agent 默认可访问以下本地数据：

- `weekly_report.md`
- `final_audit.md`
- `coverage_report.tsv`
- `run_log.tsv`
- `results/row_*.json`
- `agent_knowledge/*/` 下符合规范的数据集文件

其中 `agent_knowledge/*/` 是后续新增内部/外部数据的推荐入口。

## 爬虫日志保存策略

每一次全量爬虫完成后，后端会维护一个专门的数据集：

```text
agent_knowledge/crawl_run_logs/
  manifest.json
  README.md
  index.md
  index.json
  latest.json
  runs/<crawl_run_id>.json
```

这里不重复保存所有逐 URL 原始日志，而是保存轻量索引：

- 本次运行 ID
- 飞书日志子表 ID、标题和链接
- 本地审计文件路径
- 覆盖率、URL 成功/失败/兜底数量
- Agent 数据整理 run_id
- Agent trace 是否成功追加到飞书日志

完整日志以飞书日志子表为准：`daily_crawl_and_write.py` 会创建 `爬虫日志_YYYYMMDD_HHMMSS` 子表，写入 `run_log.tsv` 的逐 URL 记录；Agent 数据整理完成后，会继续把 Agent trace 追加到同一个飞书日志页。

Agent 查询爬虫运行状态时应优先读取 `agent_knowledge/crawl_run_logs/index.md` 或调用 `list_crawl_runs`，再按需打开飞书日志页、`run_log.tsv`、`coverage_report.tsv`、`final_audit.md`。

## 新增数据集方法

每个数据集放一个独立文件夹：

```text
agent_knowledge/<dataset_id>/
  manifest.json
  README.md
  data.csv 或 data.json 或 summary.md
  sources.json
```

`dataset_id` 建议使用英文、小写、数字、短横线，例如：

- `internal-mobile-arpu-2026`
- `external-industry-benchmark-2026`
- `partner-pricing-monitor-2026-q2`

## 必须文件

### manifest.json

后端通过 `manifest.json` 知道这个数据集是什么、适合回答什么问题、优先读哪些文件。

示例：

```json
{
  "id": "internal-mobile-arpu-2026",
  "title": "内部移动 ARPU 月度数据",
  "summary": "内部月度 ARPU、用户数和收入数据，供趋势分析和异常监测使用。",
  "source_type": "internal",
  "scope": "内部经营数据，禁止对外传播",
  "updated_at": "2026-06-17",
  "tags": ["内部数据", "ARPU", "月度趋势"],
  "keywords": ["ARPU", "用户数", "收入", "月度", "移动业务"],
  "entrypoints": ["README.md", "data.csv", "sources.json"],
  "quality": "内部口径，以财务/经营分析团队定义为准；如与外部公告冲突，必须说明口径差异。"
}
```

## 支持文件类型

后端会自动索引以下文本文件：

- `.md`
- `.txt`
- `.json`
- `.csv`
- `.tsv`

Word、PDF、Excel 建议先导出为 Markdown/CSV/JSON 放入数据集目录；原始文件可以另存，但当前 RAG 不直接索引二进制原件。

## 推荐文件职责

- `README.md`：人类可读说明，写清楚字段口径、时间范围、单位、使用限制。
- `data.csv`：结构化长表或宽表，适合问数和图表。
- `data.json`：结构化数据，适合 Agent 精确读取。
- `summary.md`：面向分析的摘要。
- `sources.json`：来源链接、内部系统来源、更新时间、负责人。

## 后端链路

- `rag_llm.py` 自动扫描 `agent_knowledge/*/manifest.json` 和允许文件类型。
- `agent.py` 的 `list_local_datasets` 工具会列出 Agent 当前能访问的数据集。
- `search_local_reports` 会检索这些数据集。
- `read_local_reference` 可以读取 `/references/agent_knowledge/<dataset_id>/<file>`。
- `web_app.py` 提供 `/api/agent-datasets` 用于检查后端当前识别到的数据集。

## 使用原则

- 内部数据必须在 `manifest.json` 的 `source_type` 标为 `internal`。
- 外部公开数据标为 `external` 或 `public`。
- 涉及冲突口径时，Agent 必须说明来源、期间、单位、币种、合并范围和建议采用口径。
- 不要把敏感原始系统导出文件直接丢进根目录；先整理成必要字段后放入独立数据集目录。
