# 飞书模块服务器部署

服务器统一使用企业自建应用身份（`tenant_access_token`）访问通讯录、消息、群聊和表格，不复制开发者本机的个人 token，也不依赖 Homebrew 路径或 macOS Keychain。

## 开放平台配置

### 网站登录

- 在「安全设置 → 重定向 URL」同时保留本机和服务器回调地址。
- 本机：`http://127.0.0.1:8765/api/auth/feishu/callback`
- 服务器：`https://<正式域名>/api/auth/feishu/callback`；内网无 HTTPS 时可用 `http://<内网IP:端口>/api/auth/feishu/callback`。
- 登录权限、应用可用范围和最新版本必须已发布。

### 人员查找与组织资料

服务器使用应用身份读子部门和部门直属用户，不再调用本机 `contact +search-user --as user`。检查：

- `contact:user.base:readonly`
- `contact:department.base:readonly`
- `contact:contact.base:readonly`
- 如要用邮箱搜索或展示邮箱，再开启用户邮箱读权限。
- 应用可用范围和通讯录权限范围都要包含目标人员。

### 消息和群聊

- 启用机器人能力。
- 开启并发布 `im:message:send_as_bot`、`im:message:readonly`、`im:chat:read` 以及实际功能需要的其他 IM 权限。
- 机器人必须在目标群内；应用可用范围必须包含直发用户。
- `open_id`、`image_key` 和 `file_key` 有应用边界。跨应用时通过 `union_id` 重新解析 `open_id`，图片和文件由发送应用上传。

### 电子表格和云文档

- 开启并发布 `sheets:spreadsheet` 及实际需要的 Drive/Docs 权限。
- 媒体指标的文件访问量统计需要 `drive:drive`、`drive:drive:readonly` 或 `drive:drive.metadata:readonly` 中至少一项，并把目标文件授权给执行统计的应用。
- 对每一份现有表格，把执行读写的应用添加为协作者，并授予查看或编辑权限。只开 scope 不等于已获得具体文档的访问权。
- 服务器设置 `CMHK_FEISHU_SHEETS_IDENTITY=bot`；本机未设置时仍保留现有用户身份链路。

### 卡片和长连接事件

- 启用长连接事件，发布项目使用的 `card.action.trigger` 和文档编辑事件。
- 服务器使用 `CMHK_FEISHU_EVENT_APP_ID` / `CMHK_FEISHU_EVENT_APP_SECRET`；未单独配置时复用主应用凭证。

## 服务器环境变量

```bash
CMHK_FEISHU_APP_ID=cli_xxx
CMHK_FEISHU_APP_SECRET=<secret manager injection>
CMHK_FEISHU_TENANT_KEY=<tenant key>
CMHK_FEISHU_REDIRECT_URI=https://cmhk-intelligence.internal/api/auth/feishu/callback
CMHK_AUTH_TRUST_PROXY_HEADERS=1

CMHK_FEISHU_PROFILE=cli_xxx
CMHK_FEISHU_ENTRY_PROFILE=cli_xxx
CMHK_FEISHU_DELIVERY_APP_ID=cli_yyy
CMHK_FEISHU_DELIVERY_APP_SECRET=<secret manager injection>
CMHK_FEISHU_DELIVERY_PROFILE=cmhk-innovation-digital
CMHK_FEISHU_DIRECTORY_PROFILE=cmhk-innovation-digital
CMHK_FEISHU_SHEETS_IDENTITY=bot
CMHK_FEISHU_SHEETS_PROFILE=cmhk-innovation-digital
CMHK_FEISHU_DRIVE_IDENTITY=bot
CMHK_FEISHU_DRIVE_PROFILE=cmhk-innovation-digital
CMHK_FEISHU_DRIVE_PROBE_TOKEN=<an existing app-accessible file token>
CMHK_FEISHU_DRIVE_PROBE_TYPE=file
LARK_CLI_PATH=/usr/local/bin/lark-cli
```

`CMHK_AUTH_TRUST_PROXY_HEADERS=1` 只能用在可信反向代理已清理用户伪造 `X-Forwarded-*` 头的场景。Secret 必须由 systemd `EnvironmentFile`、Docker/Kubernetes Secret 或企业密钥管理器注入，不得写入 Git、镜像、日志或启动参数。

## 初始化与只读验收

```bash
./scripts/bootstrap_feishu_server.sh
python3 scripts/prewarm_feishu_directory.py \
  --runtime-root /srv/cmhk \
  --env-file /etc/cmhk/feishu.env
python3 scripts/check_feishu_server_readiness.py \
  --server-url https://cmhk-intelligence.internal \
  --live \
  --require-drive
```

Bootstrap 脚本从标准输入传递 Secret，建立命名 profile，不会把 Secret 放进程参数。通讯录预热使用应用身份全量拉取一次授权范围，并在切流前生成本地快取，避免第一次页面搜索等待逐部门分页。Readiness 脚本只读，不发消息、不改表。服务器上必须设置 `CMHK_FEISHU_DRIVE_PROBE_TOKEN` 和可选的 `CMHK_FEISHU_DRIVE_PROBE_TYPE`，并使用 `--require-drive`；缺少探针或权限时验收会直接失败，不再跳过云盘链路。

## IP 白名单

默认不需要开启。如企业安全政策要求开启，填服务器访问飞书时的固定公网出口 IP，不是 `127.0.0.1`，也通常不是 `10.x` 内网地址。出口 IP 不固定时不应贸然启用。
