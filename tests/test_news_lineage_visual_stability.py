from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
INDEX = (ROOT / "web" / "static" / "index.html").read_text(encoding="utf-8")
SCRIPT = (ROOT / "web" / "static" / "workspace-tabs.js").read_text(encoding="utf-8")
STYLE = (ROOT / "web" / "static" / "workspace-tabs.css").read_text(encoding="utf-8")


class NewsLineageVisualStabilityTests(unittest.TestCase):
    def test_line_state_icons_are_semantic_stroke_svgs_without_circle_badges(self):
        self.assertIn(".news-lineage-status-icon {", STYLE)
        self.assertIn("fill: none; stroke: currentColor", STYLE)
        self.assertIn(".news-lineage-edge-state .news-lineage-status-icon", STYLE)
        self.assertNotIn(".news-lineage-edge-state i {", STYLE)
        self.assertNotIn(".news-lineage-edge-state.is-running", STYLE)

    def test_global_node_title_uses_dedicated_header_row(self):
        self.assertIn("padding: 29px 12px 9px", STYLE)
        self.assertIn(".news-lineage.is-global .news-lineage-node > span { min-height: 30px; padding-right: 0", STYLE)

    def test_crawler_diagram_uses_fine_subtle_grid_glass(self):
        self.assertIn(".news-lineage-viewport::before", STYLE)
        self.assertIn("rgba(26, 160, 214, .055)", STYLE)
        self.assertIn("rgba(126, 82, 226, .04)", STYLE)
        self.assertIn("linear-gradient(135deg, rgba(8, 34, 47, .62), rgba(6, 29, 42, .6))", STYLE)
        self.assertIn("background-size: 14px 14px, 14px 14px, 70px 70px, 70px 70px", STYLE)
        self.assertIn("backdrop-filter: blur(14px) saturate(128%)", STYLE)
        self.assertIn("rgba(126, 224, 244, .024)", STYLE)
        self.assertIn("rgba(141, 201, 246, .04)", STYLE)
        self.assertIn("radial-gradient(ellipse 54% 58% at center, #000 42%", STYLE)
        self.assertIn("backdrop-filter: blur(6px)", STYLE)
        self.assertIn("radial-gradient(ellipse 54% 58% at center, transparent 42%", STYLE)

    def test_quiet_fault_poll_does_not_rebuild_unchanged_news_lineage(self):
        self.assertIn("function newsLineageIncidentSignature(tasks)", SCRIPT)
        self.assertIn("if (newsLineageChanged && document.querySelector", SCRIPT)
        self.assertIn("--lineage-zoom:${initialLineageZoom}", SCRIPT)
        self.assertNotIn("transition: height .18s ease", STYLE)
        self.assertNotIn("transition: width .18s ease,height .18s ease", STYLE)
        self.assertNotIn("transition: transform .18s ease", STYLE)

    def test_news_lineage_live_refresh_is_fast_quiet_and_preserves_view(self):
        self.assertIn("function refreshNewsLiveData()", SCRIPT)
        self.assertIn("window.setInterval(refreshNewsLiveData, 4000)", SCRIPT)
        self.assertIn('activeWorkspaceModule() !== "news"', SCRIPT)
        self.assertIn("loadNewsRuns(selectedRunIds, { force: true, quiet: true })", SCRIPT)
        self.assertIn("function newsLiveRenderSignature()", SCRIPT)
        self.assertIn("if (nextSignature !== state.newsLiveSignature)", SCRIPT)
        self.assertIn("if (!dialogOpen)", SCRIPT)
        self.assertIn("function patchNewsLiveView()", SCRIPT)
        self.assertIn("if (!patchNewsLiveView()) renderNews({ preserveView: true })", SCRIPT)
        self.assertIn("currentItems.replaceWith(nextItems)", SCRIPT)
        self.assertNotIn('is-active")) renderNews();', SCRIPT)
        self.assertIn("function restoreNewsView(panel, snapshot)", SCRIPT)
        self.assertIn("window.scrollTo(snapshot.windowX, snapshot.windowY)", SCRIPT)

    def test_news_lineage_motion_keeps_wall_clock_phase_across_refresh_rebuilds(self):
        self.assertIn("function newsLineageMotionStyle()", SCRIPT)
        self.assertIn("wallClock % duration", SCRIPT)
        self.assertIn("${newsLineageMotionStyle()}width:${lineageWidth}px", SCRIPT)
        self.assertIn("animation-delay: var(--news-flow-delay,0ms)", STYLE)
        self.assertIn("animation-delay: var(--news-schedule-global-delay,0ms)", STYLE)
        self.assertIn("animation-delay: var(--news-feedback-global-delay,0ms)", STYLE)
        self.assertIn("--news-degraded-delay:${delay(4800)}", SCRIPT)
        self.assertIn("--news-schedule-degraded-delay:${delay(4500)}", SCRIPT)
        self.assertIn("--news-feedback-degraded-delay:${delay(8800)}", SCRIPT)
        self.assertNotIn("--news-breathe-delay", SCRIPT)

    def test_feedback_motion_loops_on_complete_dash_periods(self):
        self.assertIn("stroke-dasharray: 22 7 4 15", STYLE)
        self.assertIn("to { stroke-dashoffset: -96; }", STYLE)
        self.assertIn("stroke-dasharray: 26 9 5 18", STYLE)
        self.assertIn("to { stroke-dashoffset: -116; }", STYLE)
        self.assertNotIn("stroke-dashoffset: -108", STYLE)
        self.assertNotIn("stroke-dashoffset: -132", STYLE)

    def test_interrupted_and_unknown_lines_do_not_animate(self):
        self.assertIn(".news-lineage-edge.is-line-interrupted .news-lineage-pulse,.news-lineage-edge.is-line-unknown .news-lineage-pulse { display: none; }", STYLE)
        self.assertIn("filter: drop-shadow(0 0 5px rgba(240,128,120,.56)); animation: none;", STYLE)

    def test_degraded_lines_use_half_particle_density_and_speed(self):
        self.assertIn("stroke-dasharray: 2 50; animation-duration: 4.8s", STYLE)
        self.assertIn("stroke-dasharray: 3 39; animation-duration: 4.5s", STYLE)
        self.assertIn("stroke-dasharray: 26 38 5 47; animation-duration: 8.8s", STYLE)
        self.assertIn("animation-delay: var(--news-feedback-degraded-delay,0ms)", STYLE)

    def test_route_labels_and_status_icons_reserve_lane_title_space(self):
        self.assertIn('document.querySelectorAll("[data-news-lineage-node], [data-news-lineage-lane]")', SCRIPT)
        self.assertIn('data-news-lineage-lane data-x="${lane.position[0]}" data-y="${lane.position[1]}"', SCRIPT)
        self.assertIn('{ label: "C｜数据审核主链", position: [18, 425] }', SCRIPT)
        self.assertNotIn('C｜数据审核主链：抓取与提取', SCRIPT)

    def test_four_database_outbound_trunk_matches_inbound_centerline(self):
        self.assertIn('const databaseHub = box("database-hub")', SCRIPT)
        self.assertIn('const centerY = databaseHub ? databaseHub.y + databaseHub.h / 2 : ty', SCRIPT)
        self.assertIn('H ${targetRailX} V ${ty} H ${tx}', SCRIPT)

    def test_cache_versions_publish_the_fixed_assets(self):
        self.assertIn('/static/workspace-tabs.css?v=168', INDEX)
        self.assertIn('/static/workspace-tabs.js?v=202', INDEX)


if __name__ == "__main__":
    unittest.main()
