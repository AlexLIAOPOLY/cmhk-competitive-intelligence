# 飞书 OAuth 本机与内网部署

> 通讯录、消息、表格、卡片事件和服务器 profile 的完整配置见 [FEISHU_SERVER_DEPLOYMENT.md](FEISHU_SERVER_DEPLOYMENT.md)。

## 公司内网直连

服务默认监听 `0.0.0.0:8765`，不需要 ngrok 或另外的代理程序。运行下列命令可自动识别当前 Mac 的 RFC1918 内网 IP，并验证首页、鉴权配置和飞书回调地址：

```bash
python3 scripts/check_intranet_access.py
```

将输出中的 `PASS` 地址发给同事即可。同事的设备必须连接同一公司内网；若公司 Wi-Fi/VLAN 开启客户端隔离，则需要 IT 放行访问这台 Mac 的 TCP 8765。Mac 内网 IP 可能在重连网络后变化，变化后重新运行自检即可。

内网访问仍强制每人使用自己的 CMHK 飞书账号。服务端使用飞书 `open_id/union_id` 绑定稳定用户身份，并在管理员可见的操作审计中记录登录人、登录时间、内网来源 IP、访问主机与设备 User-Agent；不记录密码、OAuth code 或 session token。

所有内网浏览器连接的是同一个 8765 服务进程及同一份服务端状态，不通过浏览器本地数据库分叉业务数据。业务修改仍遵循各接口的服务端写入与读回校验；用户 A 写入成功后，用户 B 重新请求同一接口会读到同一权威状态。

飞书登录回调固定使用以下路径：

```text
/api/auth/feishu/callback
```

服务默认根据浏览器当前访问的协议与 `Host` 生成完整回调地址。因此：

- 本机打开 `http://127.0.0.1:8765` 时，回调为 `http://127.0.0.1:8765/api/auth/feishu/callback`。
- 内网打开 `http://10.20.30.10:8765` 时，回调为 `http://10.20.30.10:8765/api/auth/feishu/callback`。
- 使用内网域名访问时，回调中的主机名就是该内网域名。

即使部署环境误带了旧的本机 `CMHK_FEISHU_REDIRECT_URI`，外部请求也会忽略该回环地址，避免登录后跳回用户自己的电脑。

## 推荐的服务器配置

正式服务器最好明确设置唯一外部地址：

```text
CMHK_FEISHU_REDIRECT_URI=https://cmhk-intelligence.internal/api/auth/feishu/callback
CMHK_AUTH_COOKIE_SECURE=1
```

兼容已有部署时，也可以使用 `FEISHU_REDIRECT_URI`；若两者同时存在，以 `CMHK_FEISHU_REDIRECT_URI` 为准。

如果 Nginx 等反向代理没有保留原始 `Host`，应让代理发送 `X-Forwarded-Host` 和 `X-Forwarded-Proto`，并在仅受信任代理可访问应用端口的前提下设置：

```text
CMHK_AUTH_TRUST_PROXY_HEADERS=1
```

## 飞书开放平台登记

在飞书应用的安全设置中同时登记实际使用的回调 URL。本机与内网都要使用时，应至少登记：

```text
http://127.0.0.1:8765/api/auth/feishu/callback
https://cmhk-intelligence.internal/api/auth/feishu/callback
```

第二条必须替换成真实内网协议、域名或 IP 和端口，并与 `/api/auth/config` 返回的 `feishu.callbackUri` 完全一致。未登记的地址会被飞书拒绝，代码无法绕过飞书的回调白名单。
