from pathlib import Path
import tempfile
import json
import unittest
from scripts.check_workspace_layout import violations


class WorkspaceLayoutTests(unittest.TestCase):
    def test_root_policy_rejects_temporary_scripts_but_allows_classified_files(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'config').mkdir()
            (root / 'config/workspace_layout.json').write_text(json.dumps({'root_entries': ['tests', 'cmhk', 'README.md']}))
            self.assertEqual(violations(root, ['tests/test_work.py', 'cmhk/ai/client.py', 'README.md']), [])
            self.assertEqual(violations(root, ['quick_test.py', 'draft_123']), ['draft_123', 'quick_test.py'])
