# CMHK Project Codex Instructions

This repository has two GitHub destinations with different responsibilities and intentionally different `main` histories. Do not treat them as interchangeable clones.

## Repository topology

- Public development repository (`origin`): `https://github.com/AlexLIAOPOLY/cmhk-competitive-intelligence.git`
  - Contains source code and deployable project files that are safe to publish.
  - The active development branch is normally `codex-render-python-deploy`.
- Private complete-project repository (`private`): `https://github.com/AlexLIAOPOLY/cmhk-public-crawl-private.git`
  - Its `main` branch is a complete project snapshot containing private documents, current data, Agent knowledge and operational records.
  - It also receives the active development branch so committed source history is available in both repositories.

The two `main` branches must not be merged, mirrored or force-pushed over each other. Their histories are intentionally separate: the public repository is the source/deployment history, while private `main` is the complete snapshot history.

## Required synchronization workflow

After committing intended source changes, run:

```bash
./scripts/sync_github_repositories.sh
```

The script performs three operations in order:

1. Pushes the current committed branch to the public repository.
2. Pushes the same committed branch to the private repository.
3. Creates a sanitized snapshot of the current working directory and fast-forwards private `main` to that snapshot.

Before every private `main` update, the script creates a timestamped `backup/main-before-sync-*` branch. Never bypass the backup or use a force push during normal synchronization.

Uncommitted files are included only in the private complete snapshot. They are not included in either repository's development branch until explicitly committed.

## Mandatory completion and remote synchronization

- Every completed project update that changes code, configuration, documentation or generated operational state in this workspace must be synchronized to the remote repositories before the task is reported complete.
- Unless the user explicitly says not to synchronize, Codex must perform the following in the same task: inspect the current branch and targeted status, stage only the files intentionally changed for the task, create a descriptive commit when source-controlled files changed, and run `./scripts/sync_github_repositories.sh`.
- Do not stop after updating only the local source tree or runtime mirror. A finished update is not complete until the public development branch, private development branch and private `main` complete snapshot have all been synchronized successfully.
- If a task changes only an external system and leaves no project file or operational state in this workspace, a repository synchronization is not required.
- If synchronization fails, report the exact failed destination and keep working or clearly report the blocker. Never claim that an update is complete while required remote synchronization is still pending.
- Continue to exclude unrelated runtime files and secrets from the public development commit. The synchronization script remains the only approved path for including the sanitized complete workspace snapshot in private `main`.
- Git commit and repository synchronization must never wait for a running `strategic-news` task. They are independent of runtime activation and should complete immediately. If Web code needs loading while a strategic task is active, run `./scripts/queue_web_app_reload.sh`; it records one coalesced background request and returns without waiting. Report repository submission separately from pending/live runtime activation.

## Secrets and internal model configuration

- The internal model key is stored in the private repository as the encrypted GitHub Actions secret `CMHK_LLM_API_KEY`.
- The local runtime may keep the key in ignored `ai_config.json` or environment variables.
- Never commit, print, log, copy into documentation, or upload the plaintext key as a Git blob, even though the destination repository is private.
- `ai_config.json`, `.env*` and other credential files must remain excluded from snapshots.
- GitHub encrypted secrets are not restored by cloning. A deployment must explicitly map `CMHK_LLM_API_KEY` into the application's runtime environment.

## Safety rules for Codex

- Re-read every targeted file from the current working tree immediately before editing and treat that newest version as the baseline; multiple workers may update this repository concurrently, so prior-turn file contents must never be assumed current.
- Do not make an interactive worker wait for a running `strategic-news` task. Use `./scripts/queue_web_app_reload.sh`; the single background worker coalesces all pending source changes, waits for two consecutive idle checks, synchronizes the latest source and reloads once. If the task is still active at the next Hong Kong midnight, the worker may interrupt it at that explicit daily cutoff, then load the queued release. Direct ad-hoc Web restarts remain prohibited.
- When another worker has changed a targeted file, preserve those changes and layer the active request onto the latest version. Stop only when a same-line conflict cannot be merged safely without clarification.
- Inspect the current branch and targeted file status before committing because this working tree may contain unrelated user edits.
- Stage only files required by the active request; never clean, reset or revert unrelated changes.
- Use `origin` for the public repository and `private` for the private repository.
- Do not add the private repository as another push URL of `origin`; use the synchronization script so private files cannot leak to the public repository.
- For an exact rollback of private `main`, use the newest applicable `backup/main-before-sync-*` branch and require explicit user confirmation before any force-with-lease operation.

The `Codex/` directory is a persistent context vault. Follow `Codex/AGENTS.md` when updating its people, project, agent, notes and TODO records.

## 文件归位规则（2026-09-13，持续适用）

- **禁止随意在项目根目录新增任何文件或目录**，包括测试脚本、临时 Python/JS/Shell、草稿、截图、日志、报告、导出数据和备份；忽略文件也适用。
- 新建文件前先阅读本文件及项目目录说明，查找已有同类文件，按职责放入现有分类目录；不得为了省事放到根目录，也不得新建同义的平行目录。
- 根目录现有服务入口、构建清单、仓库级配置和兼容运行文件属于明确的历史契约，不代表允许继续追加。确有根目录技术约束时，必须在目录说明记录用途、调用方、不能放入子目录的原因，并同步更新检查清单；普通产物不能作为例外。
- 自动化测试和人工诊断均归入测试目录；人工诊断、联网压测和可能写入外部系统的脚本必须与自动发现的回归测试隔离。测试输入放 fixtures，测试产物放忽略的产物目录。
- 脚本必须显式确定项目根目录与输出目录，不能默认把产物写进当前工作目录；新增路径应随输出目录自动创建，文档、调用方和测试一起更新。
- 整理文件时先检查服务、定时任务、导入、资源路径、部署和同步引用，保留正在运行的入口与状态契约。验证迁移后的导入、测试发现、读写及服务可用性，再交付。
- 完成任务前检查新增文件列表与目录归属，只提交本任务文件，保留其他人的修改；文档中的历史路径注明迁移去向，不删除业务数据或凭证。

本项目的具体归属、根目录清单和检查方式见 [目录规范](docs/PROJECT_STRUCTURE.md)。执行 `make layout-check`；根目录新增项必须通过 `config/workspace_layout.json` 的明确登记。

### Web 后端拆分约束

`web_app.py` 仅保留既有入口、共享配置/状态和装配；新增 Web 业务写入 `cmhk/web/` 对应职责模块。必须遵守 [docs/WEB_BACKEND.md](docs/WEB_BACKEND.md)：使用显式应用上下文，保留原有公开调用、统一鉴权和任务生命周期，禁止重复创建服务或锁。测试放 `tests/`，不能再把实现或测试散落到根目录。
