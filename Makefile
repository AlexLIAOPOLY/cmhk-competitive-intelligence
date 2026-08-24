.PHONY: check git-health git-health-strict install-git-hooks pycheck test test-all

check: pycheck test git-health

pycheck:
	python3 -m py_compile agent.py web_app.py rag_llm.py agent_production.py agent_memory.py

test:
	python3 -m unittest \
		tests.test_web_app_curation \
		tests.test_agent_memory \
		tests.test_news_review_sheet

test-all:
	python3 -m unittest discover -s tests -t .

git-health:
	python3 scripts/git_health_check.py

git-health-strict:
	python3 scripts/git_health_check.py --strict

install-git-hooks:
	git config core.hooksPath .githooks
	chmod +x .githooks/pre-commit
