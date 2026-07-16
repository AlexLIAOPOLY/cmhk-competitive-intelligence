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

## Secrets and internal model configuration

- The internal model key is stored in the private repository as the encrypted GitHub Actions secret `CMHK_LLM_API_KEY`.
- The local runtime may keep the key in ignored `ai_config.json` or environment variables.
- Never commit, print, log, copy into documentation, or upload the plaintext key as a Git blob, even though the destination repository is private.
- `ai_config.json`, `.env*` and other credential files must remain excluded from snapshots.
- GitHub encrypted secrets are not restored by cloning. A deployment must explicitly map `CMHK_LLM_API_KEY` into the application's runtime environment.

## Safety rules for Codex

- Inspect the current branch and targeted file status before committing because this working tree may contain unrelated user edits.
- Stage only files required by the active request; never clean, reset or revert unrelated changes.
- Use `origin` for the public repository and `private` for the private repository.
- Do not add the private repository as another push URL of `origin`; use the synchronization script so private files cannot leak to the public repository.
- For an exact rollback of private `main`, use the newest applicable `backup/main-before-sync-*` branch and require explicit user confirmation before any force-with-lease operation.

The `Codex/` directory is a persistent context vault. Follow `Codex/AGENTS.md` when updating its people, project, agent, notes and TODO records.
