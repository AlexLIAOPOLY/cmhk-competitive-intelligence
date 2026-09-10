# 六 Agent 单向研究流程

## 执行结构

每天 03:00 分配任务 → 六个研究 Agent 并行 → 3路公司终审、单协调器汇总 → 四库更新 → AI 洞察及页面发布。

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

## 2026-09-07 最新前端交付适配

研究基线额外读取香港年度、云厂商十年和战略总览年度事实，统一 NTT DOCOMO、NTT Group、SoftBank Corp. 与研究任务的等价命名；保留来源和范围，不把云分部代理口径混成纯云收入。历史任务按自身保存的任务分工回读，不随当前公司目录变化。

四库和洞察通过后，发布前必须运行 `scripts/build_competitor_workbench_data.py`，重建竞对页面及其 AI 接口共用的数据文件。文件原子替换；重建失败则中止发布。公开发布包包含 `research-diagram.js`，发布回读同时比较新闻版本与竞对数据 SHA-256，不能仅凭新闻版本宣布最新前端数据已交付。

本次验证不触发模型研究、飞书写入或公开业务重发布；下次真实任务的成功与否仍以该轮归档和公开数据回读为准。

新增量研究的指标为原监控字段与当前首页四域关注指标的并集，直接读取前端快照定义；国际运营商因此包含营收、净利润、资本开支、移动ARPU。恢复已有公司任务时保留 checkpoint 的指标合同，不把新前端指标伪装成旧运行已处理。

手动整轮重跑使用独立编号 `research_YYYYMMDD_rerun_HHMMSS`，通过 `python -m data_curation.daily_research --root <正式运行目录> --run-id <独立编号>` 执行同一研究、入库和发布链。保留原日任务归档；定时器检测到独立研究或完整研究进程时不再派发另一轮。

## 2026-09-09 保持架构与证据范围的效率优化

- 同一次公司资料收集内，完全相同的查询只复用成功结果；仍逐指标记录实际查询与结果，并标明 `query_reused`。空结果保留原来的再次请求机会。最终审核的补查、跨轮最新披露搜索不使用此缓存。
- 搜索、首批页面、后续公告三个阶段维持原有依赖顺序；阶段内用最多3个 I/O 工作线程，六个研究 Agent 与最终审核共用进程内6请求上限。结果按原顺序合并，来源排序、官方域门禁及读取数量不变；线程不执行模型、写库或检查点操作。
- 模型输入保留全部历史期间、值、币种、口径和来源，以表格共用字段消除重复；完全相同的预览采用明确的来源引用。完整原文、相关片段和工具不删减，未降低模型预算或改用其他模型。
- 原文分段采用与旧正则相同的片段和偏移，消除超长无空格文本的回溯；同一页面文本未变化时复用解析索引，变化、失效或不可信时立即失效。索引最多保留当前公司页面，不跨轮缓存事实。
- 六个研究 Agent、单个最终审核、单个数据库写入与发布流程保留。公司和指标范围、截断拒绝、单项落盘、单位及主体校验、增量晋升、真实失败标签均保留。
- 记录每次模型响应、网络请求和资料收集的耗时，以及输入压缩前后字符数。使用 `python scripts/audit_research_efficiency.py <运行目录>` 只读汇总。旧日志缺失的耗时及用量显示未知；并行请求耗时之和不当作整轮耗时，字符减少不当作计费 Token 减少。

验收与测量范围见 [2026-09-09效率验收](research-efficiency-20260909.md)。

## 2026-09-09 用户授权适度调整架构：并行终审与分离检查点

本节更新此前“终审内部串行”的约束，六组初始研究与单一数据写入仍保留。最终审核节点内最多3个长期复用的独立 harness，从公司任务队列领取工作；公司内仍逐指标校验并保存。线程不共享模型上下文，跨进程模型限流与交互预留不变。所有公司结束后，唯一协调器按原任务顺序合并候选、写审核事实并交给既有四库发布流程。

`final-review.json` 变为轻量进度索引，按公司拆分 `final-review-companies/<公司SHA-256>/progress.json` 与 `pages.json`。指标保存只写进度；新原文只在初次收集或补查后写入。旧检查点自动无损迁移；恢复优先读取已落盘的公司进度，即使进程退出发生在根索引更新之前，也不重做已保存指标。`final-review.lock` 防止同轮两个终审进程重复处理。

`research_readback.py` 将新旧两种检查点恢复为相同的前端数据结构。页面轮询只读进度与原文元数据，不为展示终审状态加载全文。回退到旧代码前须先将新格式通过 `load_review(directory, evidence=True)` 导出为旧格式；不可让旧版本直接恢复新索引。调用 `review_run(..., workers=1)` 可使用新存储的串行审核，方便等量验证。

详细证据与局限见 [架构优化验收](research-architecture-20260909.md)。

## 2026-09-10 统一任务与详细日志

03:00 研究、最终审核、四库写入、AI 洞察和页面发布现在共用同一个任务编号，不再为四库刷新新建子任务。历史上已存在的研究父任务和刷新子任务在任务列表中合并为一条，详情保留并串联两份原始日志。

新运行追加六组任务分工、执行上下文、逐 Agent 结果、逐公司指标状态与资料页打开统计、最终审核统计，以及四库、洞察、发布和回读阶段记录。日志只写审计摘要和数量，不复制凭证或超长原文。
