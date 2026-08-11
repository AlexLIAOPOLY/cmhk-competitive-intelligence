# Model Picker Design QA

- Source visual truth: `/var/folders/72/7jv3g1p53s5bnfg_4wh4wqwm0000gn/T/codex-clipboard-6be5ff41-3b71-4593-b2ec-74c1642a373f.png`
- Implementation full screenshot: `/Users/liaowang/.codex/visualizations/2026/07/28/cmhk-model-menu-final-small.png`
- Implementation focused screenshot: `/Users/liaowang/.codex/visualizations/2026/07/28/cmhk-model-menu-final-small-crop.png`
- Side-by-side comparison: `/Users/liaowang/.codex/visualizations/2026/07/28/cmhk-model-menu-final-comparison.png`
- Browser viewport: 1280 × 720 CSS px, density 1
- Source pixels: 590 × 608
- Implementation menu: 280 × 316 CSS px
- Comparison normalization: source and implementation focused captures scaled to the same 334 px height
- State: model picker open, `deepseek-v4` selected

## Full-view comparison

The compact menu occupies only a small lower-right interaction area without covering the main empty-state content. It remains anchored above the model button and keeps the existing composer controls visible.

## Focused comparison

The side-by-side image confirms the requested visual language: white surface, fine blue-gray border, generous rounded corners, dark blue semibold model names, no separators, no metadata badges, and a right-edge scrollbar. The implementation intentionally uses a smaller scale than the reference after the user rejected the initial 560 × 600 version as oversized.

## Required fidelity surfaces

- Fonts and typography: system sans-serif, 13 px/700 in the implementation; same dark blue semibold hierarchy as the source, scaled for the existing chat interface.
- Spacing and layout rhythm: 40 px rows, 9 px horizontal item padding, 16 px menu radius; compact but still easily scannable.
- Colors and visual tokens: white background, `#36536f` text, `#d4e0eb` border, `#c7d4e1` scrollbar; selected state uses a restrained pale blue.
- Image quality and assets: no image assets are present in the source component; none were substituted or approximated.
- Copy and content: only real model names are shown. Existing metadata tags and check glyphs are visually suppressed.

## Findings

No actionable P0, P1, or P2 differences remain. The selected-row background is an intentional functional state not visible in the supplied reference crop.

## Comparison history

1. Initial implementation measured 560 × 600 px with 64 px rows and 19 px type.
   - Finding: P1, the menu dominated the chat surface and obscured too much content.
   - Fix: reduced the menu to 320 × 380 px, rows to 46 px, type to 14 px, and radius to 18 px while preserving the reference styling.
2. The first compact revision measured 320 × 380 px; user feedback requested another size reduction.
   - Fix: reduced the menu to 280 × 316 px, rows to 40 px, type to 13 px, and radius to 16 px.
3. Final implementation measured 280 × 316 px.
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

---

# AI Logo Background Design QA

- Source visual truth: `/var/folders/72/7jv3g1p53s5bnfg_4wh4wqwm0000gn/T/codex-clipboard-fd3c49b1-8025-48df-84bd-e33e5604fea5.png`
- User clarification for stroke weight: `/var/folders/72/7jv3g1p53s5bnfg_4wh4wqwm0000gn/T/codex-clipboard-0cd921d0-85a2-460c-9b1c-d5266b02bd1b.png`
- Implementation full screenshot: `artifacts/design-qa/ai-panel-full.png`
- Implementation focused screenshot: `artifacts/design-qa/ai-logo-background-implemented.png`
- Side-by-side comparison: `artifacts/design-qa/ai-logo-background-comparison.jpg`
- Browser viewport: 1280 × 720 CSS px, density 1
- Source pixels: 86 × 90
- Implementation empty-state mark: 48 × 48 CSS px before responsive page scaling
- State: 小竞AI panel open on the empty conversation view

## Full-view comparison

The new dark rounded-square base sits quietly above the empty-state heading and does not compete with the surrounding content. The same treatment is shared by assistant-message avatars at their smaller size.

## Focused comparison

The reference contributes only the base treatment: a dark navy surface, fine cyan outline, rounded corners, and restrained inner depth. The central artwork remains the existing CMHK 小竞AI logo asset. Its original stroke is expanded by sub-pixel same-color shadows so the mark remains legible on the dark base without becoming a glow.

## Required fidelity surfaces

- Shape: rounded square with 14 px radius on the 48 px empty-state mark.
- Border: 1 px cyan outline at 58% opacity.
- Surface: solid `#0a202a` with subtle inset depth and no light fill.
- Brand asset: unchanged `/static/assets/logo/xiaojing-ai-logo-mark.png?v=2`.
- Stroke treatment: approximately 1 px visual thickening at the empty-state size and a reduced expansion for chat avatars.

## Findings and comparison history

1. First dark-base pass preserved the original logo but left its dark blue stroke too faint.
   - Fix: raised brightness and contrast while keeping the source asset unchanged.
2. User feedback showed the logo line was still too thin at the responsive rendered size.
   - Fix: added balanced 0.55 px same-color expansion on the empty-state mark and 0.4 px on assistant avatars.
3. Final focused comparison confirms the original mark is recognizable, the stroke is visibly heavier, and the base stays visually restrained.

## Interaction and console verification

- Open 小竞AI panel: passed.
- Empty-state logo uses the original asset path: passed.
- Computed dark base, border, inset shadow, and thickened-line filter: passed.
- Browser console errors/warnings: 0.
- Automated targeted regression: 165 tests passed.

## Follow-up polish

None required.

final result: passed
