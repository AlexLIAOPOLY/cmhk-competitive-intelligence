from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parent
INDEX = (ROOT / "web" / "static" / "index.html").read_text(encoding="utf-8")
STYLE = (ROOT / "web" / "static" / "workspace-tabs.css").read_text(encoding="utf-8")


class WorkspaceBrandLogoTests(unittest.TestCase):
    def test_china_mobile_logo_stays_visible_in_every_workspace(self):
        self.assertIn('class="brand-mark" href="/"', INDEX)
        self.assertIn('src="/static/assets/china-mobile-blue-logo.png"', INDEX)
        self.assertIn('/static/workspace-tabs.css?v=78', INDEX)
        self.assertIn(
            ".dashboard-page:not(.workspace-dashboard-active) .brand-mark { visibility: visible !important; }",
            STYLE,
        )
        self.assertNotIn(
            ".dashboard-page:not(.workspace-dashboard-active) .brand-mark { visibility: hidden; }",
            STYLE,
        )


if __name__ == "__main__":
    unittest.main()
