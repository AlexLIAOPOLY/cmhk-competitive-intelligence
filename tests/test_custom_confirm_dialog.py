import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "web" / "static"


class CustomConfirmDialogTests(unittest.TestCase):
    def test_shared_dialog_assets_are_loaded_before_feature_scripts(self):
        index = (STATIC / "index.html").read_text(encoding="utf-8")
        subscription = (STATIC / "subscription-admin.html").read_text(encoding="utf-8")
        self.assertIn('/static/confirm-dialog.css?v=1', index)
        self.assertLess(index.index('/static/confirm-dialog.js?v=3'), index.index('/static/app.js?v=312'))
        self.assertIn('/static/confirm-dialog.css?v=1', subscription)
        self.assertLess(subscription.index('/static/confirm-dialog.js?v=3'), subscription.index('/static/subscription-admin.js?v=23'))

    def test_feature_code_has_no_browser_native_dialog_calls(self):
        for name in ("app.js", "subscription-admin.js", "organization-admin.js"):
            source = (STATIC / name).read_text(encoding="utf-8")
            self.assertNotIn("window.confirm(", source)
            self.assertNotIn("window.alert(", source)
        app = (STATIC / "app.js").read_text(encoding="utf-8")
        self.assertNotIn("if (!confirm(", app)
        self.assertNotIn("    alert(", app)

    def test_dialog_uses_native_modal_and_accessible_labels(self):
        source = (STATIC / "confirm-dialog.js").read_text(encoding="utf-8")
        self.assertIn('document.createElement("dialog")', source)
        self.assertIn('dialog.showModal()', source)
        self.assertIn('aria-labelledby', source)
        self.assertIn('aria-describedby', source)
        self.assertIn('dialog.addEventListener("cancel"', source)
        self.assertIn('dialog.addEventListener("keydown"', source)
        self.assertIn("event.preventDefault()", source)


if __name__ == "__main__":
    unittest.main()
