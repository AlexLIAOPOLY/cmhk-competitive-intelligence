# 飞书 OAuth 本机与内网部署

> 通讯录、消息、表格、卡片事件和服务器 profile 的完整配置见 [FEISHU_SERVER_DEPLOYMENT.md](FEISHU_SERVER_DEPLOYMENT.md)。

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
