# Model Picker Design QA

- Source visual truth: `/var/folders/72/7jv3g1p53s5bnfg_4wh4wqwm0000gn/T/codex-clipboard-6be5ff41-3b71-4593-b2ec-74c1642a373f.png`
- Implementation full screenshot: `/Users/liaowang/.codex/visualizations/2026/07/28/cmhk-model-menu-full.png`
- Implementation focused screenshot: `/Users/liaowang/.codex/visualizations/2026/07/28/cmhk-model-menu-compact.png`
- Side-by-side comparison: `/Users/liaowang/.codex/visualizations/2026/07/28/cmhk-model-menu-comparison.png`
- Browser viewport: 1280 × 720 CSS px, density 1
- Source pixels: 590 × 608
- Implementation menu: 320 × 380 CSS px; focused capture 336 × 396 px
- Comparison normalization: source and implementation focused captures scaled to the same 396 px height
- State: model picker open, `deepseek-v4` selected

## Full-view comparison

The compact menu occupies the lower-right interaction area without covering the main empty-state content or most of the chat surface. It remains anchored above the model button and keeps the existing composer controls visible.

## Focused comparison

The side-by-side image confirms the requested visual language: white surface, fine blue-gray border, generous rounded corners, dark blue semibold model names, no separators, no metadata badges, and a right-edge scrollbar. The implementation intentionally uses a smaller scale than the reference after the user rejected the initial 560 × 600 version as oversized.

## Required fidelity surfaces

- Fonts and typography: system sans-serif, 14 px/700 in the implementation; same dark blue semibold hierarchy as the source, scaled for the existing chat interface.
- Spacing and layout rhythm: 46 px rows, 10 px horizontal item padding, 18 px menu radius; compact but still easily scannable.
- Colors and visual tokens: white background, `#36536f` text, `#d4e0eb` border, `#c7d4e1` scrollbar; selected state uses a restrained pale blue.
- Image quality and assets: no image assets are present in the source component; none were substituted or approximated.
- Copy and content: only real model names are shown. Existing metadata tags and check glyphs are visually suppressed.

## Findings

No actionable P0, P1, or P2 differences remain. The selected-row background is an intentional functional state not visible in the supplied reference crop.

## Comparison history

1. Initial implementation measured 560 × 600 px with 64 px rows and 19 px type.
   - Finding: P1, the menu dominated the chat surface and obscured too much content.
   - Fix: reduced the menu to 320 × 380 px, rows to 46 px, type to 14 px, and radius to 18 px while preserving the reference styling.
2. Post-fix implementation measured 320 × 380 px.
   - Evidence: focused and full-page screenshots above.
   - Result: the menu is compact, scrollable, visually faithful in style, and interaction testing passed.

## Interaction and console verification

- Open model picker: passed.
- Current model highlight: passed (`deepseek-v4`).
- Scroll container present for 17 models: passed.
- Clicking the current model closes the menu and keeps the model unchanged: passed.
- Browser console errors/warnings: 0.
- Automated regression: `test_web_app_curation.py`, 123 tests passed.

## Follow-up polish

None required.

final result: passed
