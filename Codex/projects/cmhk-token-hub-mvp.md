# CMHK AI Token Hub MVP

- 日期：2026-08-15（香港时间）。
- 目标：在现有公共爬虫项目中增加香港 AI Token 客户端、后台管理端、服务端 LLM 调用和隔离客户线索爬虫。
- 已完成：
  - 客户端：`web/static/token-hub.html`、`token-hub.js`、`token-hub.css`；套餐、额度、香港企业助手、用量反馈。
  - 管理端：`web/static/token-hub-admin.html`、`token-hub-admin.js`；线索、消耗、爬虫运行记录和下一次调度时间。
  - 后端：`token_hub.py` 和 `web_app.py` 中 `/api/token-hub/*`；SQLite 数据位于 `var/token_hub/token_hub.sqlite3`。
  - LLM：复用服务端 `ai_config.json` 的公司内网配置，真实调用 `deepseek-v4` 成功；API key 不进入前端或日志。
  - 爬虫：`token_hub_crawl.py` 只读公开来源、只写 Token Hub 数据库；试跑抓到 28 个公开 Cyberport AI Pioneer 线索。
  - 定时：`com.liaowang.cmhk-token-hub-crawl.plist` 已加载到当前用户 LaunchAgent，2026-08-16 05:00 Asia/Hong_Kong 执行；不触发现有全量 CMHK 爬虫、Feishu 写回或群消息。
  - 部署：已通过 `start_backend_service.sh` 同步至 `/Users/liaowang/cmhk_public_crawl_app`，8765 页面和 Token Hub API 回读成功。
- 2026-08-15 增强：新增 `orders` 订单记录、演示支付状态和后台订单表；客户线索支持 `新线索/已联系/试用中/已转化/已忽略` 状态更新；后台动态显示下一次 05:00 调度时间。
- 2026-08-15 爬虫真实性复核：Cyberport AI Pioneer 页面对脚本请求返回 403，系统不再伪报实时成功；改为使用显式标注的公开快照并将运行状态记为 `partial`，保留 `page_fetched=false`，后台可见该限制。
- 验证证据：源码 py_compile 通过；套餐购买从 10,000 增至 1,010,000 credits；真实模型返回繁体中文客服欢迎语并扣除 431 tokens；浏览器桌面客户端、管理端 DOM/截图及移动布局检查通过；8765 页面回读无 console error。
- 当前边界：订单状态仍是演示支付，不是正式支付；用户身份为 demo-user，尚未接入 CMHK 登录、真实支付、退款、企业权限和正式客户联系流程。正式上线前需补充认证、支付、隐私/合规审核、真实公开客户源授权和爬虫速率/robots 策略。

## 2026-08-15 模型链路与公开 API 成本页

- 新增真实可运行页面：`web/static/token-hub-models.html`、`token-hub-models.js`、`token-hub-models.css`，入口为 `/token-hub-models.html`。
- 后端 `token_hub.py` 新增内部模型目录、任务路由、路由来源和用量审计字段；目录由公司内网 OpenAI-compatible 网关 `/models` 发现，并排除 embedding、OCR、ASR、TTS、reranker 等非聊天模型。
- 已真实验证的任务默认链路：客服与销售 → `Qwen3-30B-A3B-Instruct-2507`；翻译与改写 → `deepseek-v4`；线索研判 → `MiniMax-M2.1`；长文与知识库 → `DeepSeek-V4-Pro`；程式与自动化 → `Kimi-Code`。五条链路均通过内网真实调用返回。
- `/api/token-hub/model-lab` 只返回脱敏配置；新增模型必须先在内网 `/models` 目录发现，所有模型调用仍固定发往公司内网地址，不接受外部 Base URL 或前端密钥。
- 成本页的 Google、DeepSeek、OpenAI、Anthropic 价格链接均为 2026-08-15 通过官方页面核对的真实 URL；页面标注公开价格、缓存/工具/长上下文等限制，内部成本未填入前不下“外部一定更便宜”的结论。
- 本次新功能可正式部署，但上一节记录的 Token 套餐支付、身份认证和正式客户联系流程边界仍未被冒充为已完成；如要整套产品对外上线，必须先接入获批支付、CMHK 身份/RBAC、TLS/密钥托管和合规审查。

## 2026-08-15 峰谷成本与紧急外部算力

- `token_hub.py` 新增香港时间谷时 `00:00–08:00`、平时 `08:00–18:00/22:00–24:00`、峰时 `18:00–22:00`；时段明确标为运营规划，不伪称已批准内部电价。
- 新增 `model_tariff_costs`、`overflow_policy` 和扩展用量审计字段；模型链路页可按内部模型录入峰/平/谷输入、输出成本，并按所选时段比较内部、紧急适配器和官方公开 API 价格。
- 紧急适配器目前只允许 `https://api.deepseek.com` 官方域名；启用必须同时具备服务器端密钥、月度 HKD 预算、单次 token 上限和公开/脱敏数据标记，服务端会再做常见邮箱、电话、长编号和凭证模式脱敏。当前环境未配置外部密钥，API 与页面均显示关闭/不可用，不会外发请求。
- 实际验证：隔离 8877 API 通过峰谷/成本/策略表单与禁用外发门禁；正式 8765 页面回读 5 条任务路由、3 个时段、外部未配置状态；正式服务入口翻译任务真实返回 `冇問題。`，记录为 `internal/deepseek-v4/shoulder`，成本因未录入内部费率保持待录入；正式桌面 Browser、隔离 390px 手机 Browser 和正式页面控制台错误检查通过。
- 相关文件：`token_hub.py`、`web_app.py`、`web/static/token-hub-models.html`、`web/static/token-hub-models.js`、`web/static/token-hub-models.css`、`web/static/token-hub-models-overrides.css`、`web/static/token-hub.html`、`web/static/token-hub.js`；部署副本 `/Users/liaowang/cmhk_public_crawl_app`，端口 8765。

## 2026-08-15 模型治理页控制台改版

- 按 Ant Design Pro、Carbon、Grafana 等企业控制台的公开布局原则，将 `/token-hub-models.html` 从营销式大标题改为左侧模块导航、顶部真实状态摘要、任务表格和成本/韧性分区；保留全部真实 API、表单和官方价格链接。
- 首屏真实显示 5 条任务路由、11 个已启用内部模型、香港当前时段和外部故障转移状态；移动端 390px 收敛为横向模块栏和单列表单，页面级无横向溢出。
- 浏览器实测：8765 桌面 1280px 和手机 390px 渲染无 console error；价格表 4 行、时段 3 行、路由 5 行；点击“经济性”可定位到真实分区，修改计算器输入会即时重算且不写入配置。同步文件为 `web/static/token-hub-models.html`、`token-hub-models.css`、`token-hub-models.js`、`token-hub-models-overrides.css`。

## 2026-08-15 全量 AI UI 实测、持久化修复与操作录屏

- 按 Google People + AI Guidebook 和 Microsoft Agent/Copilot UX 指南，将服务入口改为对话优先工作区：提示词入口、任务/模型路由、明确的数据外发边界、加载/成功/失败状态和实际用量同屏可见；管理端改为运营数据工作台，并为线索状态更新增加成功/失败反馈。新增 `web/static/token-hub-client.css`、`token-hub-admin.css`，同步重写 `token-hub.html`、`token-hub.js`、`token-hub-admin.html`、`token-hub-admin.js`。
- 8765 真实运行 5 类任务：客服、翻译、线索研判、长文知识库、程式自动化均成功返回，分别命中 `Qwen3-30B-A3B-Instruct-2507`、`deepseek-v4`、`MiniMax-M2.1`、`DeepSeek-V4-Pro`、`Kimi-Code`；另复测空输入门禁、提示词入口、演示套餐建立订单、线索状态改动后恢复、模型登记、峰谷成本保存、经济性计算器和紧急外部算力拒绝门禁。
- 真实部署重启测试发现并修复 `sync_app_runtime.sh` 会覆盖运行副本 `var/` 导致订单/额度丢失的问题；现在同步脚本排除 `var/`。修复后订单 `TH-20260815-AB0AE19E` 在重启 8765 后仍可读，额度为 `1,026,876`，订单数为 2。
- 发现并修复模型登记表单异步 `event.currentTarget` 为空的前端 bug；空输入反馈也改为“本次未运行”，不再沿用上一轮 token 用量。最终三页 1280px 及 390px Browser 检查均无页面横向溢出，`dev.logs({error,warn})` 为空。
- 最终操作录屏：`/Users/liaowang/Desktop/cmhk_tokenhub_recording_final/cmhk-token-hub-operation-demo-final.mp4`，1280×720、18 秒；原始帧和 UI 审计截图分别位于 `cmhk_tokenhub_recording_final/`、`cmhk_tokenhub_ui_audit/`。
- 爬虫边界：一次源码隔离运行实际返回 `partial`（28 条公开快照，Cyberport 页面抓取受阻、CSV SSL 证书失败）；没有再次触发正式 CMHK 全量爬虫、Feishu 写回或群通知，管理端保留并显示该限制。

## 2026-08-17 服务入口视觉重构

- 按企业工作台而非营销落地页的布局规范重做 `web/static/token-hub-client.css`：减轻侧栏视觉重量、收紧首屏标题与对话区空白、将账户额度改为紧凑状态指标、将套餐按钮改为分层的轻量操作，并保留香港企业助手、峰谷/紧急外部算力边界和真实路由反馈。
- `web/static/token-hub.html` 仅更新客户端 CSS 缓存版本；后端 API、额度、订单和模型逻辑未改动。已通过 `sync_app_runtime.sh` 同步到 `/Users/liaowang/cmhk_public_crawl_app`。
- 浏览器实测：`http://127.0.0.1:8765/token-hub.html` 桌面 1280×720 与手机 390×844 均无页面横向溢出，顶栏三入口在手机仍可见，客户端 `dev.logs` 无 error/warning；最终页面保留在浏览器前台。
