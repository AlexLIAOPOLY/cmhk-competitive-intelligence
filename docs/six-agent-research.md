# 六 Agent 单向研究流程

## 执行结构

每天 03:00 分配任务 → 六个研究 Agent 并行 → 汇总与原文校验 → 四库更新 → AI 洞察及页面发布。

任务定义只有一个来源：`data_curation/research_plan.py`。六组分别负责香港、内地、亚太、欧洲、美洲与中东、全球云厂商，共覆盖现有 41 家公司；公司和指标是任务条目，不是额外 Agent。战略新闻的原有采集入口独立保留。

默认定时入口不再执行 01:00 搜索交接、固定 URL 全量轮询、公司级 Agent 扇出或缺口回抓。历史代码仍用于兼容旧记录，不是新定时任务的默认路径。已有官方入口可作为研究参考，但来源数量不构成架构层级或验收条件。

## 开源 harness 与 DeepSeek 输出保护

- 使用 [Deep Agents](https://github.com/langchain-ai/deepagents) 0.7.13，复用其工具执行、上下文压缩及 LangChain 有界重试。关闭隐式 general-purpose subagent 和宿主文件/执行工具。
- 六个长期存活的 harness 实例共享现有跨进程模型限流和密钥轮换，不另建模型调用循环。
- 每次只提交一项指标，不输出覆盖所有公司的长 JSON。通过原文片段编号提交，程序复制已读取的原文。
- 模型响应的 `finish_reason=length` 和不完整工具参数在执行提交工具前被拒绝；最多重试两次。响应完整不等于事实正确，仍需指标、原文、主体、值、期间及单位校验。
- 截断恢复仍由 harness 的重试中间件执行：当前指标的输出预算按 4096 → 8192 → 16384 有界提高，同时附加简短的单项提交指令。内部网关可能仍返回思考内容，不能仅凭请求已发送 `thinking.type=disabled` 就宣称思考已关闭；实际响应额度与结束原因写入时间线。
- 每个指标最多六轮模型决策；每轮协议恢复最多两次重试，重试不能冒充新的研究任务。查阅预算结束后只开放并指定 `submit_metric`，仍不能形成合格提交时明确保留待复核，不把预算耗尽伪装成指标不存在。
- 对于仅输出自由文本而未调用提交工具的响应，同样由 harness 拒绝并有界恢复，不把文本自行拼成事实。恢复请求在系统消息开头加入唯一编号，避免某些内部网关在尾部指令和预算已改变时仍复用旧的前缀缓存；编号不能进入证据。
- 每项提交后原子保存；后续指标超时不会抹去前面的结果。显式 `--resume` 复用已保存页面和已完成项，不重复抓取。不同运行编号或任务分配不能混用检查点。
- 传输重试及提交格式修正不属于业务回抓：不会重新派发公司任务或回到爬虫阶段。

官方参考：[自定义 harness](https://docs.langchain.com/oss/python/deepagents/customization)、[上下文管理](https://docs.langchain.com/oss/python/deepagents/context-engineering)、[DeepSeek 响应协议](https://api-docs.deepseek.com/api/create-chat-completion/)。

## 新闻与自动筛选：持久化执行保护

`cmhk/intelligence/agent_harness.py` 使用 Deep Agents 同生态的 LangGraph `StateGraph`、`RetryPolicy` 和 SQLite checkpointer。新闻决策本身是有明确输入输出的阶段，不添加工具或隐式子 Agent，也不增加研究 Agent 数量。

- `strategic_briefing._call_internal_ai`：涵盖新闻搜索规划、编辑审核、独立复审、语义去重及简报生成。格式恢复由 harness 有界重试，原有业务审核规则及传输层限流、路由切换继续保留。
- `news_selection_agent._invoke_langchain`：完整候选决策校验后保存检查点；所有恢复请求仍经过原有十次模型请求计数。人工作出的决定、分布门禁、待写计划及飞书逐格回读不被绕过。
- `market_news_insights.generate_market_news_insights`：四条洞察及引用 ID 校验完成后保存；若其后的应用缓存写入中断，恢复时复用完成的模型结果。显式“重新分析”仍使用新批次，不能被旧结果挡住。
- 三类入口和研究工具提交共用完整性门禁。即使返回文本碰巧是合法 JSON，`finish_reason=length/max_tokens` 仍不得作为完整结果接受；不使用思考内容代替最终输出。截断恢复提高预算并绕过网关缓存，超过上限保留失败，不能承诺上游永不截断。
- 检查点使用输入、协议和任务作用域指纹；SQLite 同步持久化与逐决策进程锁防止同一任务并发重复执行。只存完成的 JSON 结果，不存密钥或模型客户端。
- 进程在模型请求途中退出，该未完成请求可能重发；已落盘的决策不重做。已确认的飞书写入和消息发送继续依靠原有回读凭证与稳定幂等键防重，不能把模型检查点等同于外部系统的绝对 exactly-once 保证。

检查点位于各业务状态目录的 `agent_harness/` 或 `harness/` 下，不进入公开源码提交。旧正式任务在安全队列切换前仍使用旧代码，不能把隔离验收等同于正式服务已加载。

参考：[LangGraph 持久化](https://docs.langchain.com/oss/python/langgraph/persistence)、[容错与有界重试](https://docs.langchain.com/oss/python/langgraph/fault-tolerance)。

验证命令（新闻部分兼容现有 Web Python，不要求在运行中的服务里升级 Deep Agents）：

```bash
python -m unittest tests.test_agent_harness tests.test_news_selection_agent tests.test_strategic_briefing tests.test_competitor_intelligence_map
```

2026-09-05 隔离验收：新闻入口与自动筛选入口均完成真实内部 DeepSeek 调用；相同输入恢复不再次调用模型。故障注入测试覆盖合法 JSON 但截断、重试耗尽、实际进程退出后恢复、已完成结果跨进程复用、应用缓存写入失败后恢复。验收不写飞书、不发通知，不能代替正式发布回读。

## 四库更新边界

`executive_intelligence_pipeline.py` 只读取本轮目录内的已审核事实，不能误读全局上一轮文件。四库审核事实层按公司、指标、期间和单位增量合并；本轮缺失不会清除历史事实。宏观支持库不接受此六组任务的空结果覆盖。

现有主表继续使用各自的字段、期间和核验等级晋升门禁。审核事实发布、主表晋升、库文件变化、页面数字变化分别记账；有审核事实不代表所有 KPI 都被改写。页面发布沿用现有发布及外部版本回读，不能以 HTTP 服务存活代替整条任务完成。

## 安装与运行

标准部署安装 `requirements.txt`。macOS 现有 Web 环境可以保持不变，另建兼容的研究环境：

```bash
bash scripts/setup_research_harness.sh
```

定时派发优先使用 `CMHK_RESEARCH_PYTHON`，否则使用 macOS 的 `Library/Application Support/CMHK/research-venv/bin/python`，其他部署使用当前 Python。环境安装复用本机既有依赖，但 harness 的依赖升级限制在该 venv 内。

仅验证研究、不更新四库或外部页面：

```bash
"/Users/liaowang/Library/Application Support/CMHK/research-venv/bin/python" \
  -m data_curation.six_agent_research \
  --run-id research_validation \
  --output-dir /tmp/cmhk-research-validation
```

恢复上述同一研究可追加 `--resume`。正式每日入口为 `data_curation.daily_research`；部署更新必须经过项目的安全重载队列，不直接重启正在研究的进程。

## 界面与验收

`/api/news-research?date=YYYY-MM-DD` 返回所选日期的任务、逐公司指标、检索和原文读取记录。图上的每个节点可点击；研究节点提供输入、动作、输出、证据和原始时间线。手机端使用纵向卡片，不把整张图压缩成不可点击的小字。

自动化测试：

```bash
python -m unittest tests.test_research_harness tests.test_six_agent_pipeline tests.test_executive_intelligence_pipeline
```

这些测试验证截断拒绝、单项保存、恢复、六组任务上限、同轮隔离和四库幂等更新；真实网络、模型及发布需要另行运行验证，不能用模拟测试冒充真实完成。
