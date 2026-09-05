#!/usr/bin/env bash
# Isolate harness dependencies from the existing web/scheduler interpreter.
set -euo pipefail
research_env="${CMHK_RESEARCH_VENV:-$HOME/Library/Application Support/CMHK/research-venv}"
research_python="${CMHK_BASE_PYTHON:-python3}"
"$research_python" -m venv --system-site-packages "$research_env"
"$research_env/bin/python" -m pip install 'deepagents==0.7.13' 'langchain-deepseek>=1.0,<2'
"$research_env/bin/python" -c 'from deepagents import create_deep_agent; from langchain_deepseek import ChatDeepSeek; print("Research harness imports verified")'
