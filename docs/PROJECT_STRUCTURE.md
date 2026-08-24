# Project structure

The repository keeps a small compatibility layer at its root because macOS
LaunchAgents and the deployed runtime call several Python and shell entrypoints
by absolute path. Moving those entrypoints without a coordinated runtime
migration would break scheduled crawling and monitoring.

## Main directories

- `cmhk/`: importable production library, split by business responsibility:
  `agent/`, `auth/`, `crawl/`, `data/`, `integrations/`, `intelligence/`,
  `reporting/`, and `services/`.
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
- `data/`: committed application data, grouped by carrier performance,
  company metrics, Feishu readback, reporting, and weekly-report support.
- `artifacts/generated/`: ignored local reports, debug readbacks, media, and
  other generated outputs; these are not imported as source code.
- `runtime/local/`: ignored local logs, locks, and transient state.
- `curation_data/`, `results/`, `var/`: operational datasets and service state.
- `docs/`: architecture and operating documentation.
- `archives/`: ignored local recovery material; not application input.

## Root compatibility entrypoints

The root now contains only externally referenced commands, high-level workflow
entrypoints, deployment metadata, and the small set of root-level operational
files that are part of the existing runtime contract. Reusable implementation
modules live under `cmhk/`; one-off maintenance commands live under `tools/`.

In particular, `web_app.py`, `scheduler.py`, `project_monitor.py`,
`strategic_briefing.py`, `crawl.py`, and their coordinated workflow entrypoints
remain stable because macOS LaunchAgents and the deployed runtime invoke them by
absolute path.

Historical Word reports and diagnostic readbacks have moved to
`artifacts/generated/`. The few root report files that remain are current
runtime references or committed templates and are intentionally covered by
tests before any later migration.

## Cleanup policy

1. Prove a file is generated, duplicated, or unreachable before removing it.
2. Preserve tracked files through Git history and preserve untracked cleanup
   candidates under a timestamped local recovery archive first.
3. Run `make check`, targeted regressions, formal API checks, and browser QA
   before synchronizing the change to both repositories.
