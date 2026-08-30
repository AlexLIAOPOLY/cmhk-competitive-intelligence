from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class GitHubRepositorySyncTests(unittest.TestCase):
    def test_private_snapshot_excludes_dependency_and_test_caches(self) -> None:
        script = (ROOT / "scripts/sync_github_repositories.sh").read_text(encoding="utf-8")

        for exclusion in (
            "--exclude '/node_modules/'",
            "--exclude '/.pytest_cache/'",
            "--exclude '/.mypy_cache/'",
            "--exclude '/.ruff_cache/'",
            "--exclude '/.coverage'",
            "--exclude '/coverage.xml'",
            "--exclude '/htmlcov/'",
            "--exclude '/junit*.xml'",
            "--exclude '/frontend_test_results.txt'",
        ):
            with self.subTest(exclusion=exclusion):
                self.assertIn(exclusion, script)

        self.assertIn('git -C "$TMP_DIR" add -f -A', script)


if __name__ == "__main__":
    unittest.main()
