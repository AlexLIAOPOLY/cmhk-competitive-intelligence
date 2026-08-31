import pathlib
import re
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[1]
STATIC = ROOT / "web" / "static"
ASSETS = STATIC / "assets" / "model-providers"


class ModelProviderLogoTests(unittest.TestCase):
    def test_all_selectable_provider_logos_are_local_safe_svg_assets(self) -> None:
        for slug in ("deepseek", "kimi", "qwen", "minimax", "chatglm"):
            source = (ASSETS / f"{slug}.svg").read_text(encoding="utf-8")
            self.assertIn("<svg", source, slug)
            self.assertIn('viewBox="0 0 24 24"', source, slug)
            self.assertNotIn("<script", source.casefold(), slug)
            self.assertIsNone(
                re.search(r'(?:href|src)=["\']https?://', source, flags=re.IGNORECASE),
                slug,
            )

        self.assertTrue((ASSETS / "ASSET_PROVENANCE.md").is_file())
        self.assertTrue((ASSETS / "LICENSE-Lobe-Icons.txt").is_file())

    def test_model_catalog_names_map_to_provider_logos(self) -> None:
        source = (STATIC / "app.js").read_text(encoding="utf-8")

        self.assertIn('{ pattern: /deepseek/i, slug: "deepseek"', source)
        self.assertIn('{ pattern: /kimi/i, slug: "kimi"', source)
        self.assertIn('{ pattern: /qwen/i, slug: "qwen"', source)
        self.assertIn('{ pattern: /minimax/i, slug: "minimax"', source)
        self.assertIn('{ pattern: /(?:chatglm|glm)/i, slug: "chatglm"', source)
        self.assertIn("chatModelProviderLogoHtml(model)", source)
        self.assertIn("chatModelProviderLogoHtml(selectedModel)", source)
        self.assertIn('aria-label="${escapeHtml(model)}"', source)

    def test_picker_keeps_text_accessible_and_logo_decorative(self) -> None:
        markup = (STATIC / "index.html").read_text(encoding="utf-8")
        styles = (STATIC / "styles.css").read_text(encoding="utf-8")
        source = (STATIC / "app.js").read_text(encoding="utf-8")

        self.assertIn('aria-haspopup="listbox"', markup)
        self.assertIn('aria-controls="chatModelOptions"', markup)
        self.assertIn('role="listbox" aria-label="可用语言模型"', markup)
        self.assertIn('class="chat-model-provider-logo is-${provider.slug}" aria-hidden="true"', source)
        self.assertIn('alt=""', source)
        self.assertIn(".chat-model-provider-logo {", styles)
        self.assertIn(".chat-model-provider-logo.is-kimi { background: #101827; }", styles)
        self.assertIn("@media (max-width: 430px)", styles)
        self.assertIn(".dashboard-page .chat-model-menu,", styles)
        self.assertIn("position: fixed;", styles)
        self.assertIn("left: 12px;", styles)


if __name__ == "__main__":
    unittest.main()
