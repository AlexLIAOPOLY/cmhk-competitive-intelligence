import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parent
STATIC = ROOT / "web" / "static"


class SiteThemeTests(unittest.TestCase):
    def test_all_served_pages_load_shared_theme_assets_and_toggle(self):
        for name in ("index.html", "company-data.html", "executive-dashboard-demo.html"):
            markup = (STATIC / name).read_text(encoding="utf-8")
            with self.subTest(page=name):
                self.assertIn('data-theme-toggle', markup)
                self.assertIn('/static/theme.css?v=2', markup)
                self.assertIn('/static/theme.js?v=1', markup)
                self.assertIn('cmhk-color-theme', markup)

    def test_theme_defaults_to_dark_and_persists_light_choice(self):
        script = (STATIC / "theme.js").read_text(encoding="utf-8")
        self.assertIn('return "dark"', script)
        self.assertIn('window.localStorage.setItem(STORAGE_KEY, resolved)', script)
        self.assertIn('document.documentElement.dataset.theme = resolved', script)

    def test_light_theme_uses_dedicated_generated_background(self):
        styles = (STATIC / "theme.css").read_text(encoding="utf-8")
        asset = STATIC / "assets" / "mobile-intelligence-bg-light.png"
        self.assertIn('/static/assets/mobile-intelligence-bg-light.png', styles)
        self.assertTrue(asset.exists())
        self.assertGreater(asset.stat().st_size, 100_000)


if __name__ == "__main__":
    unittest.main()
