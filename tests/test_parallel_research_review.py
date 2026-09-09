import fcntl
import json
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from data_curation.research_final_review import review_run
from data_curation.review_store import ReviewStore, company_directory, load_company, load_review


def fixture(directory, companies):
    task = {"key": "test-group", "title": "Test", "companies": companies}
    reports = [{"company": c, "metrics": ["收入", "资本开支"], "baseline": {},
                "pages": {}, "items": [{"company": c, "metric": m, "status": "missing", "value": ""}
                                        for m in ["收入", "资本开支"]]} for c in companies]
    (directory / "manifest.json").write_text(json.dumps({"run_id": "test", "plan": [task]}))
    (directory / "test-group.json").write_text(json.dumps({**task, "reports": reports}))
    return reports


def collector(company, *args):
    return {f"https://official.test/{company}": {"opened": True, "official": True,
            "text": f"{company} revenue and capex for 2026 were USD 100 million."}}, []


class ParallelReviewTests(unittest.TestCase):
    def test_process_exit_after_metric_save_resumes_only_the_remaining_metric(self):
        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp)
            fixture(directory, ["HKT"])
            script = f'''
import os
from pathlib import Path
from data_curation.research_final_review import review_run
from tests.test_parallel_research_review import collector
class Harness:
    def __init__(self, *args): pass
    def extract(self, company, metric, pages, save, **kwargs):
        save({{"company":company,"metric":metric,"status":"missing","value":""}})
        os._exit(17)
review_run(Path({str(directory)!r}), model_factory=lambda:None, collector=collector, harness_factory=Harness)
'''
            child = subprocess.run([sys.executable, "-c", script], capture_output=True, timeout=30)
            self.assertEqual(child.returncode, 17, child.stderr.decode())
            calls = []
            class ResumeHarness:
                def __init__(self, *args): pass
                def extract(self, company, metric, pages, save, **kwargs):
                    calls.append(metric)
                    save({"company":company, "metric":metric, "status":"missing", "value":""})
            result = review_run(directory, model_factory=lambda:None,
                                collector=lambda *args: self.fail("completed search repeated"),
                                harness_factory=ResumeHarness)
            self.assertEqual(calls, ["资本开支"])
            self.assertEqual(result["tasks"], 2)

    def test_parallel_and_serial_results_equal_with_isolated_harnesses_and_one_merge(self):
        outputs = []
        peaks = []
        for workers in [1, 3]:
            with tempfile.TemporaryDirectory() as temp:
                directory = Path(temp)
                fixture(directory, ["HKT", "SmarTone", "SK Telecom", "KDDI", "Telstra", "NTT"])
                lock = threading.Lock()
                active = peak = 0
                class Harness:
                    def __init__(self, *args): self.owner = threading.get_ident()
                    def extract(self, company, metric, pages, save, **kwargs):
                        nonlocal active, peak
                        self_test.assertEqual(threading.get_ident(), self.owner)
                        self.company = company
                        with lock:
                            active += 1
                            peak = max(peak, active)
                        time.sleep(.02)
                        self_test.assertEqual(company, self.company)
                        save({"company": company, "metric": metric, "status": "missing", "value": "",
                              "reason": "Same evidence is insufficient"})
                        with lock: active -= 1
                self_test = self
                with patch("data_curation.research_final_review.merge_results", wraps=__import__(
                        "data_curation.six_agent_research", fromlist=["merge_results"]).merge_results) as merge:
                    result = review_run(directory, model_factory=lambda: None, collector=collector,
                                        harness_factory=Harness, workers=workers)
                self.assertEqual(merge.call_count, 1)
                self.assertEqual(result["tasks"], 12)
                self.assertEqual(result["final_review"]["workers"], workers)
                outputs.append((result["outcome_counts"], (directory / "candidate_facts.jsonl").read_text()))
                peaks.append(peak)
                restored = load_review(directory, evidence=True)
                self.assertEqual(len(restored["reports"]), 6)
                self.assertTrue(all(r["review_completed"] for r in restored["reports"]))
                for report in load_review(directory)["reports"]:
                    self.assertTrue(all("text" not in page for page in report["pages"].values()))
                review_run(directory, model_factory=lambda: self.fail("completed run must not call a model"))
        self.assertEqual(outputs[0], outputs[1])
        self.assertEqual(peaks, [1, 3])

    def test_metric_save_does_not_rewrite_evidence_and_resume_restores_it(self):
        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp)
            store = ReviewStore(directory, {"key": "final-review"}, "test", ["HKT"], 3)
            report = {"company": "HKT", "status": "running", "items": [], "pages": collector("HKT")[0]}
            store.save(report, evidence_changed=True)
            evidence = company_directory(directory, "HKT") / "pages.json"
            initial_mtime = evidence.stat().st_mtime_ns
            report["items"] = [{"metric": "收入", "status": "missing"}]
            store.save(report)
            self.assertEqual(initial_mtime, evidence.stat().st_mtime_ns)
            self.assertEqual(load_company(directory, "HKT", evidence=True), report)
            self.assertLess((directory / "final-review.json").stat().st_size, 1000)
            with self.assertRaises(RuntimeError): store.complete()

    def test_resume_after_partial_metric_commit_never_repeats_saved_metric_or_search(self):
        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp)
            reports = fixture(directory, ["HKT"])
            store = ReviewStore(directory, {"key": "final-review"}, "test", ["HKT"], 3)
            report = reports[0]
            report.update(pages=collector("HKT")[0], review_search_completed=True, reviewed_metrics=["收入"])
            store.save(report, evidence_changed=True)
            calls = []
            class Harness:
                def __init__(self, *args): pass
                def extract(self, company, metric, pages, save, **kwargs):
                    calls.append(metric)
                    save({"company": company, "metric": metric, "status": "missing", "value": ""})
            review_run(directory, model_factory=lambda: None, collector=lambda *args: self.fail("search replay"),
                       harness_factory=Harness)
            self.assertEqual(calls, ["资本开支"])

    def test_legacy_completed_company_migrates_without_model_and_root_write_failure_recovers(self):
        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp)
            reports = fixture(directory, ["HKT"])
            reports[0].update(review_completed=True, status="partial", pages=collector("HKT")[0])
            (directory / "final-review.json").write_text(json.dumps({"reports": reports}))
            store = ReviewStore(directory, {"key": "final-review"}, "test", ["HKT"], 3)
            self.assertEqual(load_company(directory, "HKT", evidence=True), reports[0])
            reports[0]["note"] = "saved before root index failed"
            with patch.object(store, "_write_index", side_effect=OSError("injected")):
                with self.assertRaises(OSError): store.save(reports[0])
            restored = ReviewStore(directory, {"key": "final-review"}, "test", ["HKT"], 3)
            self.assertEqual(load_company(directory, "HKT", evidence=True)["note"], reports[0]["note"])
            result = review_run(directory, model_factory=lambda: self.fail("model replay"))
            self.assertEqual(result["final_review"]["status"], "completed")

    def test_process_lock_and_changed_contract_fail_closed(self):
        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp)
            fixture(directory, ["HKT"])
            with (directory / "final-review.lock").open("a") as lock:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                with self.assertRaises(BlockingIOError): review_run(directory)
            ReviewStore(directory, {}, "test", ["HKT"], 3)
            with self.assertRaises(ValueError): ReviewStore(directory, {}, "other", ["HKT"], 3)
            with self.assertRaises(ValueError): ReviewStore(directory, {}, "test", ["KDDI"], 3)
            store = ReviewStore(directory, {}, "test", ["HKT"], 3)
            store.save({"company": "HKT", "pages": {}}, evidence_changed=True)
            (directory / "final-review.json").unlink()
            with self.assertRaises(ValueError): ReviewStore(directory, {}, "other", ["HKT"], 3)
