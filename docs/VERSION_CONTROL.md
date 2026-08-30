# Version Control Guide

本项目的 Git 目标是：只跟踪可维护的源码、配置、审计脚本、稳定知识库入口和项目文档；运行时状态、临时报告、截图、音频、聊天线程和大批量生成物不再继续进入版本历史。

## 当前问题

- 普通开发分支曾跟踪大量运行态、PDF、SQLite、预览文件和重复知识发布，造成 clone、status 与对象库持续膨胀。
- `tmp/`、`agent_runs/`、`agent_chat_threads/`、`agent_knowledge/generated_charts/`、日志、pid、周报导出物等会随着每次本地测试变化，导致 `git status` 被噪声污染。
- 这些文件多数是可再生成或本地状态，不适合作为长期版本历史。

## 该进入 Git 的内容

- Python/JS/CSS/HTML 源码。
- 测试、审计脚本、构建脚本和轻量配置。
- 人工维护的 README、项目文档、数据口径说明、manifest、正式审计摘要。
- 必须随代码一起演进的模板文件，例如 `weekly_report_template.docx`、`weekly_report_from_word_template.docx` 和 `carrier_performance_template.docx`。

## 不该进入 Git 的内容

- 运行状态：`tmp/`、`*.pid`、`agent_runs/`、`agent_chat_threads/*.json*`。
- 日志和本地回读：`*.log`、`readback_*.json`、`payload_*.json`、`feishu_live_*.json`。
- 导出物：周报 Word/HTML/Markdown、音频、临时图表、测试截图。
- 可再生成的大型图表和工作簿：`agent_knowledge/generated_charts/`、`*_human_readable.xlsx`。
- 报告预览、下载缓存和来源 PDF：`web/static/report-previews/`、`data/**/http_cache/`、`data/quarterly_sources/**/*.pdf`。
- SQLite 检查点、历史 curation run、UI QA 截图和文件名带 ` 2` 的重复知识发布。
- 本地密钥和环境：`.env*`、`ai_config.json`。

这些文件仍可保留在本机运行目录。`scripts/sync_github_repositories.sh` 会继续把经过清理的完整工作区快照写入私有 `main`；普通开发分支只承载可维护源码和当前必需的轻量结构化知识。不要为了瘦身删除本机文件，也不要改写两个远端的历史。

## 本机私库跟踪缓存

私有 `main` 每次更新前都会建立远端 `backup/main-before-sync-*` 回滚分支。这些远端备份必须保留，但开发工作区没有必要把完整快照 `main` 或全部备份分支下载为本地远端跟踪引用。`private` 的 fetch 范围应只包含当前开发分支；同步脚本会在独立临时仓库中按需读取私有 `main`。清理本机 `refs/remotes/private/main` 和 `refs/remotes/private/backup/*` 不会删除 GitHub 上的任何分支。

本机完成一次引用收敛后，再执行标准 Git 垃圾回收，才能真正释放旧 pack 占用。操作前应确认远端可访问，并保留当前提交和脏工作区回滚分支；禁止把这套本机缓存清理改成远端分支删除或历史改写。

## 日常工作流

1. 开始前看状态：

   ```bash
   git status --short
   python3 scripts/git_health_check.py
   ```

2. 首次在本机启用提交保护：

   ```bash
   make install-git-hooks
   ```

   该 hook 只拦截将要提交的运行态/生成物，不影响本地运行项目。

3. 每次只做一个逻辑改动。业务功能、数据包、前端样式、运维脚本尽量分开提交。

4. 提交前运行：

   ```bash
   make check
   git diff --check
   git status --short
   ```

   `make check` 与 `make test-all` 都在一次性副本中测试当前工作区；完成精确暂存后，`make ci` 会改为测试 Git 索引中的拟提交内容，避免并行工作者的未暂存数据影响结论。

4. 如果 `git_health_check.py` 提示 tracked runtime 文件被修改，先判断是不是运行服务产生的本地状态，不要直接混进功能提交。

## 已经被跟踪的生成物怎么处理

`.gitignore` 只能阻止新的未跟踪文件进入 Git，不能自动移除历史中已经被跟踪的文件。建议单独开一次“索引瘦身”提交，只从 Git 索引移除，不删除本地文件：

```bash
git ls-files -ci --exclude-standard -z | git update-index --force-remove -z --stdin
git add .gitignore .gitattributes docs/VERSION_CONTROL.md scripts/git_health_check.py Makefile
python3 scripts/git_health_check.py --strict
git commit -m "Clean generated runtime artifacts from git index"
```

执行前必须先确认 `git status --short` 中没有用户未保存的重要业务改动。上面的索引命令不会删除本地文件，只是不再让 Git 跟踪这些生成物。提交后的普通分支不会再携带来源 PDF、SQLite 或预览文件；正式运行使用既有本机/运行目录数据，私有完整快照仍保留可恢复副本。

## 分支和提交建议

- `main` 或稳定分支只放已验证版本。
- 日常迭代使用 `codex/<topic>` 或现有 `codex-render-python-deploy` 分支。
- 提交信息建议用动作开头：
  - `Add quarterly source audit`
  - `Fix agent chart retry guard`
  - `Document git hygiene workflow`

## 发布前检查

最小检查：

```bash
make check
python3 scripts/git_health_check.py --strict
git status --short
```

涉及知识库、RAG、预测、来源核验时，继续运行对应审计脚本：

```bash
python3 scripts/audit_source_evidence_integrity.py
python3 scripts/audit_source_url_reachability.py
python3 scripts/audit_agent_dataset_visibility.py
python3 scripts/audit_agent_knowledge_integrity.py
```
