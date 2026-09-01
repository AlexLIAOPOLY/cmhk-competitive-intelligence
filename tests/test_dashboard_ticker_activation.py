from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
APP = (ROOT / "web/static/app.js").read_text(encoding="utf-8")
INDEX = (ROOT / "web/static/index.html").read_text(encoding="utf-8")


class DashboardTickerActivationTests(unittest.TestCase):
    def test_dashboard_activation_restarts_hidden_ticker_after_layout(self):
        self.assertIn('window.addEventListener("workspace-tab-change"', APP)
        self.assertIn('event.detail.tab !== "dashboard"', APP)
        self.assertIn("window.requestAnimationFrame(restartScroll)", APP)

    def test_non_dashboard_modules_pause_the_ticker(self):
        listener = APP.rsplit('window.addEventListener("workspace-tab-change"', 1)[1]
        self.assertIn("pauseScroll();", listener[:500])

    def test_app_asset_cache_version_is_bumped(self):
        self.assertIn('/static/app.js?v=321', INDEX)


if __name__ == "__main__":
    unittest.main()
