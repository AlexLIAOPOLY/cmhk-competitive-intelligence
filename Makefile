.PHONY: check git-health git-health-strict install-git-hooks pycheck test

check: pycheck test git-health

pycheck:
	python3 -m py_compile agent.py web_app.py rag_llm.py agent_production.py agent_memory.py

test:
	python3 -m unittest test_web_app_curation

git-health:
	python3 scripts/git_health_check.py

git-health-strict:
	python3 scripts/git_health_check.py --strict

install-git-hooks:
	git config core.hooksPath .githooks
	chmod +x .githooks/pre-commit
