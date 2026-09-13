# CMHK Competitive Intelligence

CMHK 竞争情报采集、研判、报告、订阅、监控和小竞AI系统。

## 目录导航

- `cmhk/`：按职责分类的生产代码库。
- `web/`：正式 Web 应用与静态资源。
- `tests/`：全部测试（自动回归、人工诊断、压测和场景重放分区）。
- `tools/`：维护、集成、质量检查和人工诊断工具。
- `scripts/`：部署、同步、发布和运行维护脚本。
- `data/`：按业务域分类的项目数据。
- `agent_knowledge/`：小竞AI知识库与审计证据。
- `artifacts/generated/`：本地生成的报告和调试产物，不属于源码。
- `runtime/local/`：本地日志、锁和临时运行状态。
- `archives/`：可恢复归档。
- `docs/`：项目结构和运维文档。

禁止随意向根目录新增文件。根目录现有文件仅作为正式运行入口、部署配置和历史路径契约保留；新建文件必须按职责进入分类目录。详细边界和清理规则见 [docs/PROJECT_STRUCTURE.md](docs/PROJECT_STRUCTURE.md)。

季度／半年度竞对经营指标是下游沙盘的统一数据源。刷新完成后会自动发布不可变 release，并原子更新 `current.json`；同机和跨服务器消费、鉴权与回滚说明见 [季度竞对数据发布](docs/QUARTERLY_DATA_RELEASES.md)。

## 验证

```bash
make layout-check
make test
make test-all
make check
```

Web 后端的职责划分、兼容入口和新增功能规则见 [Web 后端模块维护规范](docs/WEB_BACKEND.md)。
