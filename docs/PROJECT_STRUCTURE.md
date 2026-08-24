# Project structure

The repository keeps a small compatibility layer at its root because macOS
LaunchAgents and the deployed runtime call several Python and shell entrypoints
by absolute path. Moving those entrypoints without a coordinated runtime
migration would break scheduled crawling and monitoring.

## Main directories

- `tests/`: import-safe automated regression tests.
- `tests/fixtures/`: committed inputs used by tests.
- `tools/manual_checks/`: operator and historical diagnostic scripts that are
  intentionally excluded from automatic discovery.
- `scripts/`: deployment, synchronization, publication, and maintenance tools.
- `deploy/launchd/`: macOS LaunchAgent templates; their configured runtime
  entrypoint paths remain unchanged.
- `web/static/`: browser application assets.
- `config/`: runtime configuration templates that contain no secrets.
- `agent_knowledge/`: source-backed local datasets and audit material.
- `data/`, `curation_data/`, `results/`, `var/`: operational data and state.
- `docs/`: architecture and operating documentation.
- `archives/`: ignored local recovery material; not application input.

## Root compatibility entrypoints

The root Python files are currently modules or externally referenced commands.
In particular, `web_app.py`, `scheduler.py`, `project_monitor.py`, and
`project_monitor_card_actions.py` must remain stable until their LaunchAgent
paths and runtime deployment contract are migrated together.

Generated reports remain a runtime concern. The formal application currently
indexes root-level Word outputs, so they are not silently relocated as part of
a source-only cleanup.

## Cleanup policy

1. Prove a file is generated, duplicated, or unreachable before removing it.
2. Preserve tracked files through Git history and preserve untracked cleanup
   candidates under a timestamped local recovery archive first.
3. Run `make check`, targeted regressions, formal API checks, and browser QA
   before synchronizing the change to both repositories.
