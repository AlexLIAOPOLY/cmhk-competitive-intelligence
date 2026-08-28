# 季度竞对数据发布

## 数据职责

`agent_knowledge/quarterly_competitor_metrics_2026-06-18` 是季度／半年度经营指标的唯一维护源。国际经营指标刷新通过质量门禁并完成原子晋级后，`executive_intelligence_pipeline.py` 自动调用发布器；沙盘只消费发布包，不再复制维护基础 CSV。

发布器只复制 manifest 声明的入口文件，拒绝目录穿越、符号链接、清单行数漂移、缺失自然键、重复自然键和不完整字段。每个版本按内容哈希命名，旧版本保留；`current.json` 通过原子替换指向最新完整版本。

## 手工发布与检查

```bash
python3 scripts/publish_quarterly_metrics_release.py
curl -fsS http://127.0.0.1:8765/data-releases/quarterly/current.json
```

默认发布目录为 `runtime/local/data_releases/quarterly_competitor_metrics`，可用 `CMHK_QUARTERLY_RELEASE_ROOT` 指定服务器持久卷。该目录属于运行态，不提交 Git。

## 跨服务器访问

环回客户端在未配置 token 时可以只读访问。存在远程客户端时必须通过部署环境设置 `CMHK_DATA_RELEASE_TOKEN`，客户端以 Bearer token 访问；应用使用常量时间比较鉴权。生产环境还应在反向代理层配置 HTTPS、来源网络 ACL、请求限速和访问日志，token 由密钥管理系统注入，不写入仓库或命令历史。

只读接口范围为：

```text
GET/HEAD /data-releases/quarterly/current.json
GET/HEAD /data-releases/quarterly/releases/<release_id>/release.json
GET/HEAD /data-releases/quarterly/releases/<release_id>/<artifact>
```

## 回滚与保留

发布失败发生在 `current.json` 切换之前，不影响原版本。需要回退时，不修改或删除历史 release；核对目标 release 的 `release.json` 与 artifact 哈希后，用运维脚本原子更新 `current.json`。沙盘侧仍会独立重新校验所有哈希和质量门禁，且先构建候选数据库再切换。
