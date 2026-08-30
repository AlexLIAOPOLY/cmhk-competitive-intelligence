import pathlib
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[1]
STATIC = ROOT / "web" / "static"


class CustomSelectAssetTests(unittest.TestCase):
    def test_primary_pages_load_custom_select_assets_before_feature_scripts(self):
        index = (STATIC / "index.html").read_text(encoding="utf-8")
        company = (STATIC / "company-data.html").read_text(encoding="utf-8")

        self.assertIn('/static/custom-select.css?v=2', index)
        self.assertIn('/static/custom-select.css?v=2', company)
        self.assertLess(index.index('/static/custom-select.js?v=2'), index.index('/static/app.js?v=313'))
        self.assertLess(company.index('/static/custom-select.js?v=2'), company.index('/static/company-data.js?v=14'))

    def test_component_covers_dynamic_selects_and_accessible_interaction(self):
        source = (STATIC / "custom-select.js").read_text(encoding="utf-8")

        self.assertIn('new MutationObserver', source)
        self.assertIn('role", "combobox', source)
        self.assertIn('role", "listbox', source)
        self.assertIn('role", "option', source)
        self.assertIn('select.setAttribute("aria-hidden", "true")', source)
        self.assertIn('select.setAttribute("data-cmhk-select-source", "")', source)
        self.assertIn('event.key === "Escape"', source)
        self.assertIn('event.key === "ArrowDown"', source)
        self.assertIn('dispatchEvent(new Event("change", { bubbles: true }))', source)

    def test_only_intentionally_hidden_select_stays_native(self):
        html = (STATIC / "index.html").read_text(encoding="utf-8")
        self.assertIn('class="sr-only" id="chatModelSelect"', html)
        self.assertIn('select.classList.contains("sr-only")', (STATIC / "custom-select.js").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
