from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parent
INDEX = (ROOT / "web" / "static" / "index.html").read_text(encoding="utf-8")
STYLE = (ROOT / "web" / "static" / "workspace-tabs.css").read_text(encoding="utf-8")


class WorkspaceBrandLogoTests(unittest.TestCase):
    def test_china_mobile_logo_stays_visible_in_every_workspace(self):
        self.assertIn('class="brand-mark" href="/"', INDEX)
        self.assertIn('src="/static/assets/china-mobile-blue-logo.png"', INDEX)
        self.assertRegex(INDEX, r'/static/workspace-tabs\.css\?v=\d+')
        self.assertIn(
            ".dashboard-page:not(.workspace-dashboard-active) .brand-mark { visibility: visible !important; }",
            STYLE,
        )
        self.assertNotIn(
            ".dashboard-page:not(.workspace-dashboard-active) .brand-mark { visibility: hidden; }",
            STYLE,
        )

    def test_collapsed_navigation_toggle_stays_right_of_logo(self):
        self.assertIn(
            ".workspace-layout.is-nav-collapsed .workspace-tabs { position: absolute; top: -54px; left: 180px;",
            STYLE,
        )
        self.assertNotIn(
            ".workspace-layout.is-nav-collapsed .workspace-tabs { position: absolute; top: -54px; left: 10px;",
            STYLE,
        )

    def test_navigation_toggle_uses_panel_icon_instead_of_solid_chevron(self):
        self.assertIn('class="workspace-nav-icon"', INDEX)
        self.assertIn('class="workspace-nav-icon-arrow"', INDEX)
        self.assertIn('<rect x="3" y="3" width="18" height="18" rx="2"></rect>', INDEX)
        self.assertIn(".workspace-layout.is-nav-collapsed .workspace-nav-icon-arrow { transform: rotate(180deg); }", STYLE)
        self.assertNotIn("clip-path: polygon(13% 5%", STYLE)


if __name__ == "__main__":
    unittest.main()
