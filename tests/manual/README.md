# Manual checks

These scripts are operator diagnostics, not automated tests. Some legacy checks
can call the live model, local web service, TTS, or Feishu-facing code and may
create files in the current directory.

The original scripts are retained under `legacy/` for traceability. Review a
script before running it and use an isolated working directory where possible.
Do not add this directory to unittest discovery.
