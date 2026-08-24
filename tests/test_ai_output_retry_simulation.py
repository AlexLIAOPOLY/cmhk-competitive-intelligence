from pathlib import Path

from scripts.simulate_ai_output_retries import ROOT, WORKFLOWS, run_matrix


def test_complete_internal_ai_retry_matrix_is_fail_closed_and_side_effect_free():
    report = run_matrix(ROOT)
    assert report["ok"] is True
    assert report["workflow_count"] == len(WORKFLOWS) == 18
    assert report["structured_source_gate_count"] == 9
    assert report["side_effects"] == {
        "crawler_started": False,
        "feishu_written": False,
        "message_sent": False,
    }
    for result in report["results"]:
        assert result["attempts"] == 3
        assert len(result["rejected"]) == 2
        if result["kind"] != "text":
            assert result["repaired_terminal_delimiters"] is True


def test_formal_runtime_can_run_the_same_retry_matrix_when_present():
    runtime = Path("/Users/liaowang/cmhk_public_crawl_app")
    if not (runtime / "scripts" / "simulate_ai_output_retries.py").exists():
        return
    report = run_matrix(runtime)
    assert report["ok"] is True
