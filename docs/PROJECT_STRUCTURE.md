# 项目目录与文件归位标准

自 2026-09-13 起持续执行。**任何新文件都必须先分类，禁止随意添加到根目录，忽略文件也不例外。** 行为约束见 [AGENTS.md](../AGENTS.md)，可执行根目录清单见 [workspace_layout.json](../config/workspace_layout.json)。

## 文件放在哪里

| 内容 | 指定位置 |
| --- | --- |
| 公共 AI 配置、并发、密钥轮换、响应兼容 | `cmhk/ai/` |
| Agent、认证、采集、数据、集成、研判、报告和订阅 | `cmhk/agent/`、`auth/`、`crawl/`、`data/`、`integrations/`、`intelligence/`、`reporting/`、`services/` |
| 数据研究流程 | `data_curation/` |
| Web 页面与静态资源 | `web/`、`web/static/` |
| Go 工具与第三方依赖 | `cmd/`、`vendor/` |
| Python / JavaScript 自动回归 | `tests/test_*.py`、`tests/test_*.cjs` |
| 测试共享输入 | `tests/fixtures/`；共享辅助模块放 `tests/` |
| 人工诊断与历史测试 | `tests/manual/`；旧脚本放 `tests/manual/legacy/` |
| 隔离压测与确定性重放 | `tests/load/`、`tests/scenarios/` |
| 启动、部署、同步与运维脚本 | `scripts/`；部署模板放 `deploy/` |
| 一次性维护、集成和质量工具 | `tools/maintenance/`、`tools/integrations/`、`tools/quality/`、`tools/reports/` |
| 非敏感配置、测试配置与目录清单 | `config/` |
| 按业务域组织的数据 | `data/carrier_performance/`、`company_metrics/`、`feishu/`、`reporting/`、`weekly_report/` |
| 文档草稿与周报原始参考 | `data/reporting/drafts/`、`data/reporting/reference_reports/`，不提交公开源码 |
| Agent 知识、原始证据与规范审计 | `agent_knowledge/`，保持每个数据集原有粒度和 manifest |
| 报告预览、诊断导出、临时评测 | `artifacts/generated/`，下设业务/任务目录 |
| 验收截图与证据 | `artifacts/` 中已有对应任务目录；不在根目录放图片 |
| 日志、锁、临时状态 | `runtime/local/` 或所属服务的 `var/` 子目录 |
| 运维说明、变更记录与设计图 | `docs/`；审计放 `docs/audits/`，图放 `docs/assets/` |
| 示例、补丁、可恢复历史归档 | `examples/`、`patches/`、`archives/` |
| 跨会话项目记录 | `Codex/`，按其自身 AGENTS.md 分类 |

## 保留的运行路径

根目录的 `web_app.py`、`scheduler.py`、`project_monitor.py`、`project_monitor_card_actions.py`、`crawl.py`、`strategic_briefing.py` 和报告/数据工作流 CLI，以及现有启动和同步 Shell，仍被部署配置、macOS LaunchAgent 或外部工具引用。当前保留这些入口路径；**新业务实现放入 `cmhk/`，不能继续新增根目录模块**。

`ai_config.json` 是既有私有配置路径，绝不提交。模板 `weekly_report_template.docx`、`carrier_performance_template.docx`、当前周报 `weekly_report.*`、`sources.json`、`source_registry.json`、`run_log.*`、`coverage_report.tsv`、`final_audit.md`、调度状态与当前日志仍是现有生产读写契约，暂时保留。新增产物必须使用分类目录。

`results/`、`curation_data/`、`strategy_briefing/`、`agent_runs/`、`agent_chat_threads/`、`evidence_cache/`、`raw/`、`outputs/`、`audio/`、`models/`、`logs/`、`tmp/`、`var/` 和 `runtime/` 是已有服务状态、输入或缓存位置。不能仅因目录较多就删除、合并或覆盖；迁移须同时验证读写双方和运行时同步排除项。第三方依赖、`.git/` 和虚拟环境由对应工具管理，不做递归重排。

开发目录与 `/Users/liaowang/cmhk_public_crawl_app` 正式运行副本相互独立。运行更新只通过 `scripts/queue_web_app_reload.sh` 等候安全空闲窗口；Git 同步不等待运行激活。

## 本次迁移映射

- 原根目录 `ai_config.py`、`ai_dispatch.py`、`ai_key_rotation.py`、`ai_rate_limit.py`、`ai_response_compat.py` → `cmhk/ai/`；统一使用完整包导入。
- `network_utils.py` → `cmhk/integrations/`；`executive_intelligence_prompts.py` → `cmhk/intelligence/`；`report_audio_pipeline.py` → `cmhk/reporting/`。
- `tools/manual_checks/` → `tests/manual/`。
- `scripts/load_test_ai_concurrency.py` → `tests/load/`；`scripts/simulate_ai_output_retries.py` → `tests/scenarios/`；`scripts/run_xiaojing_agent_evals.py` → `tests/manual/`。
- `draft_*_folder/` → `data/reporting/drafts/`，保留各草稿目录名称与原始内容。
- `参考周报/` → `data/reporting/reference_reports/`。
- `weekly_report_from_word_template.docx`、`weekly_report_render/` → `artifacts/generated/reports/`；这是历史输出，正式模板仍保留。
- `agent_evals/` → `artifacts/generated/agent_evals/`；评测脚本默认输出同步修改。
- 未使用的空文件 `cmhk_competitive_intelligence.db` → `runtime/local/legacy/`，未删除。

## 新建与验证流程

1. 先读本规范，搜索同类文件，选已有目录；脚本显式计算项目路径和输出位置，不向任意当前目录写文件。
2. 根目录如确有无法替代的工具入口约束，在本文件记录技术原因和调用方，再更新 `config/workspace_layout.json`。普通脚本、报告、截图和测试不能登记为例外。
3. 修改文件路径时一并修正导入、子进程代码、资源定位、测试 mock、文档命令和部署配置。私有数据与正在写入的状态不能随源码覆盖。
4. 执行 `make layout-check`、相关回归和导入检查；较大结构调整执行 `make test-all`。提交钩子用暂存区清单检查，CI 再次验证。
5. 自动测试在可丢弃快照中运行；完整入口包括 pytest 函数测试、unittest 测试类与 Node 测试。`manual/`、`load/`、`scenarios/` 不自动递归发现。人工联网或外部写入脚本仍需其原本授权。
6. 交付前检查运行服务与相关资源，更新文档，按 AGENTS.md 提交和同步。数据质量失败、历史告警与运行不可用必须区分，不以 HTTP 200 代表所有业务结果正确。

```bash
make layout-check
make test
make test-all
python3 tests/load/load_test_ai_concurrency.py --users 50 --output /tmp/cmhk-ai-load-50.json
python3 tests/scenarios/simulate_ai_output_retries.py --help
```
