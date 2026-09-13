# Prefer the configured local research runtime; CI and other machines use PATH.
PYTHON ?= $(shell if [ -x "$(HOME)/Library/Application Support/CMHK/research-venv/bin/python" ]; then printf '%s' "$(HOME)/Library/Application Support/CMHK/research-venv/bin/python"; else command -v python3; fi)

.PHONY: check ci git-health git-health-strict install-git-hooks pycheck test test-all test-all-index test-all-in-place

check: layout-check pycheck test git-health

pycheck:
	"$(PYTHON)" -m compileall -q cmhk
	"$(PYTHON)" -m py_compile agent.py web_app.py crawl.py scheduler.py project_monitor.py strategic_briefing.py

test:
	"$(PYTHON)" scripts/run_tests_isolated.py -- \
		tests.test_web_app_curation \
		tests.test_agent_memory \
		tests.test_news_review_sheet

test-all:
	"$(PYTHON)" scripts/run_tests_isolated.py --pytest --javascript

test-all-index:
	"$(PYTHON)" scripts/run_tests_isolated.py --index --pytest --javascript

test-all-in-place:
	"$(PYTHON)" -m unittest discover -s tests -t .

ci: layout-check pycheck test-all-index git-health-strict

git-health:
	"$(PYTHON)" scripts/git_health_check.py

git-health-strict:
	"$(PYTHON)" scripts/git_health_check.py --strict

install-git-hooks:
	git config core.hooksPath .githooks
	chmod +x .githooks/pre-commit

.PHONY: layout-check
layout-check:
	"$(PYTHON)" scripts/check_workspace_layout.py
