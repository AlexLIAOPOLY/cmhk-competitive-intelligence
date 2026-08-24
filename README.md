# CMHK Competitive Intelligence

CMHK 竞争情报采集、研判、报告、订阅、监控和小竞AI系统。

## 目录导航

- `cmhk/`：按职责分类的生产代码库。
- `web/`：正式 Web 应用与静态资源。
- `tests/`：可安全自动发现的回归测试。
- `tools/`：维护、集成、质量检查和人工诊断工具。
- `scripts/`：部署、同步、发布和运行维护脚本。
- `data/`：按业务域分类的项目数据。
- `agent_knowledge/`：小竞AI知识库与审计证据。
- `artifacts/generated/`：本地生成的报告和调试产物，不属于源码。
- `runtime/local/`：本地日志、锁和临时运行状态。
- `archives/`：可恢复归档。
- `docs/`：项目结构和运维文档。

根目录只保留正式运行入口、部署文件以及尚有兼容约束的当前运行文件。详细边界和清理规则见 [docs/PROJECT_STRUCTURE.md](docs/PROJECT_STRUCTURE.md)。

## 验证

```bash
make test
make test-all
make check
```
