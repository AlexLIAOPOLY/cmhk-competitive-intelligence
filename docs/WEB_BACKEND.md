# Web 后端模块维护规范

2026-09-13：`web_app.py` 从 9,495 行拆为 449 行入口与 `cmhk/web/` 下的职责模块。现有启动命令、URL、响应格式、文件位置、服务状态和 `import web_app` 接口保留。

## 职责位置

| 模块 | 职责 |
| --- | --- |
| 根目录 `web_app.py` | 原有配置、共享状态、流会话类型、服务装配和启动 |
| `http_read.py` | GET / HEAD 路由与读取鉴权 |
| `http_write.py` | POST 路由、写入鉴权和请求身份上下文 |
| `http_resources.py` | 下载、预览、静态资源、音频 Range 与响应头 |
| `transport.py` | JSON、NDJSON、基础 SSE 与进程输出解析 |
| `lifecycle.py` | SSE 与报告生成的任务记录、完成、异常和清理 |
| `chat_history.py`、`chat_media.py`、`chat_approvals.py` | 聊天记录、标题、多模态输入、竞品分析和审批流 |
| `reports.py` | 报告文件、元数据、编辑、预览与删除 |
| `datasets.py` | 数据设置、上传、整理状态、证据及质量记录 |
| `overview.py`、`news_status.py` | 运行概览、调度概览、新闻轮次与筛选状态 |
| `pipelines.py` | 抓取、数据刷新、报告生成和子进程流 |
| `subscriptions.py`、`subscription_jobs.py` | 订阅设置、操作足迹、推送任务与状态 |
| `task_runs.py`、`task_monitor.py` | 任务持久化、恢复、日志、心跳、故障与音频任务 |
| `review_actors.py`、`review_audit.py` | 新闻审核人员归因、审核足迹、表格同步和巡检 |
| `_binding.py` | 保留旧入口的函数名称、签名和可导入身份 |

## 为什么显式绑定应用上下文

现有工作流、插件和测试会通过 `web_app.ROOT`、`web_app.AUTH` 及其他公开名称替换路径、服务或协作函数。直接把这些值复制到多个模块，会造成配置、锁和状态分叉。

每个模块的 `bind(app)` 接收当前入口模块，创建绑定到这个上下文的函数，再通过 `publish` 暴露在原入口上。实现通过 `app.ROOT`、`app.AUTH`、`app.some_function(...)` 在调用时读取共享依赖。同一模块内部的协作调用也使用上下文，因此原有 `patch.object(web_app, ...)` 仍然生效。局部变量、局部导入、生成器和嵌套工作线程维持原语义。绑定过程不启动后台任务。

这是普通 Python 函数闭包和 HTTP mixin 的组合，不依赖动态执行源码。不同上下文可以分别绑定，模块不存放全局的应用实例。`python web_app.py` 使用 `sys.modules[__name__]` 绑定到实际启动入口，避免再导入另一份 `web_app`。

基础 `write_sse` 和 `stream_report_generation` 必须先绑定，再保存 `_ORIGINAL_*` 引用，最后绑定 `lifecycle`。不能把生命周期包装器指回自己。`main()` 保持原启动顺序。

## 后续添加文件或功能

1. Web 业务实现放到上表对应模块；职责不匹配时在 `cmhk/web/` 新建语义明确的模块。禁止重新往根目录堆实现，也禁止把所有内容挪到另一个巨型文件。
2. 新 HTTP 接口放进相应路由，保留统一鉴权、资源路径校验和任务生命周期。业务处理放到职责模块，路由尽量只承担接入与响应。
3. 共享状态继续由应用上下文持有；不能在新模块重复创建认证服务、调度器、锁、会话缓存或推送队列。默认参数如引用其他绑定函数，须确保先完成其绑定。
4. 回归放到 `tests/`；人工诊断、压测及确定性重放分别按项目目录规范归位。既有读取后端源码的契约检查使用 `tests.web_source.read_web_source`，覆盖入口和全部实现，不能只检查空入口而漏掉实际业务。
5. 修改后运行 `make pycheck layout-check`、相关测试；结构调整运行 `make test-all` 并与调整前失败集合对照。模块兼容性测试见 `tests/test_web_app_modules.py`，覆盖共享路径、替换依赖、类型/导入身份、SSE 生命周期、真实 HTTP 鉴权/HEAD 和音频分段响应。
6. 提交并同步后，通过 `scripts/queue_web_app_reload.sh` 安全加载；验证队列激活记录、运行副本文件哈希、健康接口和相关页面。已有数据质量或历史测试失败必须如实记录，不能等同于本次拆分通过。
