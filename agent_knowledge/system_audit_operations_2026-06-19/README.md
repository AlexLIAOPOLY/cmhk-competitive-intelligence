# 系统审计与运行记录

这个数据库是给小竞AI前台使用的合并入口，避免把多个审计明细包和运行日志包都作为平级数据库展示。

## 什么时候使用

- 用户问“数据准不准”“来源完整吗”“URL还能不能访问”。
- 用户问“小竞AI能不能检索到数据库”“为什么某个库看不到”。
- 用户问“预测工具有没有排除 source-gap / legacy 非预测口径”。
- 用户问“目标完成了吗”“还有哪些缺口”。
- 用户问“之前爬虫或运行日志怎么样”。

## 当前处理方式

前台默认只显示这个合并入口；下面的明细包仍保留在原路径，但已从默认数据库列表隐藏：

- `agent_knowledge/agent_dataset_visibility_audits/`
- `agent_knowledge/agent_guidance_alignment_audits/`
- `agent_knowledge/forecast_readiness_audits/`
- `agent_knowledge/goal_readiness_audits/`
- `agent_knowledge/knowledge_integrity_audits/`
- `agent_knowledge/source_evidence_audits/`
- `agent_knowledge/source_url_reachability_audits/`
- `agent_knowledge/crawl_run_logs/`

如需正式结论，优先读取 `audit_index.md`，再按里面列出的原始审计路径读取明细文件。

