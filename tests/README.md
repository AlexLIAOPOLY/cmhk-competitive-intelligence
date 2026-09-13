# 统一测试目录

所有测试脚本集中于本目录，按用途隔离：

| 位置 | 用途 |
| --- | --- |
| `test_*.py` | pytest 函数测试与 unittest 回归类 |
| `test_*.cjs` | Node 自动回归 |
| `fixtures/` | 固定测试输入 |
| `manual/` | 人工诊断、Agent 评测；`legacy/` 保留历史检查 |
| `load/` | 显式运行的隔离并发压测 |
| `scenarios/` | 可复用确定性流程重放，由回归测试显式导入 |

`make test` 跑关键回归；`make test-all` 在可丢弃工作区运行全部 pytest 与 Node 测试；`make test-all-index` 只验证暂存区版本。依赖见 `config/requirements-test.txt`，发现规则见 `config/pytest.ini`。

人工诊断目录没有包初始化文件，unittest 不递归进入；pytest 也显式排除 manual、load、scenarios、fixtures。历史脚本可能调用真实 API、写文件或发送内容，不能批量执行。

测试固定从项目根定位资源，临时状态与模型健康状态仅写入隔离测试区。输出不得随意落在项目根目录；评测默认产物在 `artifacts/generated/agent_evals/`。

本机 Makefile 优先使用既有 `research-venv`；其他机器使用 PATH 中的 Python。可通过 `make PYTHON=/path/to/python test-all` 指定环境，先用该解释器安装 `config/requirements-test.txt`。全量测试每例默认上限 60 秒，超时会报告失败并继续，避免旧诊断逻辑无限挂起。
