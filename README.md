# CMHK 竞对动态监测与行业趋势研判系统

面向 CMHK 商用场景的情报平台：7x24 自动检索 + AI 研判 + 周报/研报生成 + Word/PDF 导出。

## 1. 功能概览

- 全网监测：财报、产品发布会、中标公示、高管言论、政策法规、宏观数据
- 智能研判：自动提炼关键事实、影响点、引用来源
- 报告中心：周报（固定模板）+ 行业趋势研判报告（正式格式）
- 可控执行：支持扫描截停、心跳定时策略、任务日志全链路记录
- 导出能力：Word / PDF

## 2. 技术架构

- Backend: Node.js + Express
- Scheduler: node-cron
- Search: Tavily API（真实网络检索）
- LLM: DeepSeek API（真实推理）
- Storage: JSON 文件存储（默认 `data/db.json`，可通过 `DATA_DIR` / `DB_PATH` 改路径）

## 3. 本地环境准备

### 3.1 前置条件

- Node.js 20.x 或 22.x
- npm 10+

### 3.2 安装与启动

```bash
npm install
cp .env.example .env
# 编辑 .env 填入真实 DS_API_KEY / TAVILY_API_KEY
npm start
```

默认访问：`http://localhost:3000`  
健康检查：`GET /api/health`

## 4. 环境变量

必填：

- `DS_API_KEY`
- `TAVILY_API_KEY`

常用：

- `PORT`：服务端口（默认 `3000`）
- `SCAN_SCHEDULE`：Cron（默认 `*/30 * * * *`）
- `SCAN_TIMEZONE`：默认 `Asia/Hong_Kong`
- `SCAN_INTERVAL_MINUTES`：扫描间隔（心跳策略默认值）
- `MAX_RESULTS_PER_QUERY`：每条 query 检索上限（默认 `8`）
- `DS_MODEL`：默认 `deepseek-chat`
- `DS_TIMEOUT_MS` / `DS_REPORT_TIMEOUT_MS` / `DS_REPORT_QA_TIMEOUT_MS`
- `TAVILY_TIMEOUT_MS`
- `DATA_DIR`：数据目录（Render 推荐 `/var/data`）
- `DB_PATH`：可选，直接指定 db 文件路径（优先级高于 `DATA_DIR`）
- `CHROME_PATH`：高保真 PDF 导出浏览器路径（Docker 部署默认 `/usr/bin/chromium`）

## 5. API（核心）

- `GET /api/health`
- `GET /api/config`
- `PUT /api/config/competitors`
- `GET /api/status`
- `GET /api/scan/state`
- `POST /api/scan/run`
- `POST /api/scan/stop`
- `GET /api/findings`
- `POST /api/reports/weekly/generate`
- `POST /api/reports/trends/generate`
- `GET /api/reports`
- `GET /api/reports/:id/export/word`
- `GET /api/reports/:id/export/pdf`
- `GET /api/jobs`

## 6. 测试

```bash
npm run test:smoke   # 基础联通（会调用真实 API）
npm run test:e2e     # 端到端（会调用真实 API）
```

## 7. 部署准备（已就绪）

仓库已提供：

- `Dockerfile`
- `render.yaml`
- `.env.example`
- 存储路径可配置（`DATA_DIR` / `DB_PATH`）

部署建议：

- 使用 Render Docker Web Service（保证 PDF 导出可用）
- 挂载 Persistent Disk，避免重启丢数据

## 8. GitHub 公开推送（命令行）

先在 GitHub 网页新建一个 **Public** 仓库（例如 `cmhk-competitive-intelligence`），然后执行：

```bash
git init
git branch -M main
git add .
git commit -m "feat: prepare production deployment for render"
git remote add origin <你的GitHub仓库URL>
git push -u origin main
```

说明：

- `.env`、`data/`、`node_modules/` 已在 `.gitignore` 中，不会被推送
- 不要把 API Key 提交到仓库

若 `git push` 报 `Could not resolve host: github.com` 或本地代理不可用，可先临时关闭 Git 代理再推送：

```bash
git -c http.proxy= -c https.proxy= push -u origin main
```

## 9. Render 部署步骤

### 9.1 创建服务

1. Render 控制台 -> New -> Blueprint
2. 选择你的 GitHub 仓库（包含 `render.yaml`）
3. 确认服务配置：
   - Runtime: Docker
   - Health Check Path: `/api/health`
   - Persistent Disk: `/var/data`（10GB）

### 9.2 配置密钥

在 Render 环境变量中填入：

- `DS_API_KEY`
- `TAVILY_API_KEY`

其余变量可沿用 `render.yaml` 默认值。

### 9.3 部署验证

部署成功后验证：

- `GET https://<your-service>.onrender.com/api/health`
- 页面可访问
- 扫描可执行
- 可生成周报并导出 Word/PDF

## 10. 商用上线注意

- 强烈建议使用 Starter 或以上（Persistent Disk 需要非 Free 计划）
- 建议开启监控与告警（响应超时、5xx、扫描失败率）
- 生产环境请轮换 API Key，并最小化可见权限
