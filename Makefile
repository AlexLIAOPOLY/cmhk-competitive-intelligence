.PHONY: check ci git-health git-health-strict install-git-hooks pycheck test test-all test-all-index test-all-in-place

check: pycheck test git-health

pycheck:
	python3 -m compileall -q cmhk
	python3 -m py_compile agent.py web_app.py crawl.py scheduler.py project_monitor.py strategic_briefing.py

test:
	python3 scripts/run_tests_isolated.py -- \
		tests.test_web_app_curation \
		tests.test_agent_memory \
		tests.test_news_review_sheet

test-all:
	python3 scripts/run_tests_isolated.py

test-all-index:
	python3 scripts/run_tests_isolated.py --index

test-all-in-place:
	python3 -m unittest discover -s tests -t .

ci: pycheck test-all-index git-health-strict

git-health:
	python3 scripts/git_health_check.py

git-health-strict:
	python3 scripts/git_health_check.py --strict

install-git-hooks:
	git config core.hooksPath .githooks
	chmod +x .githooks/pre-commit
