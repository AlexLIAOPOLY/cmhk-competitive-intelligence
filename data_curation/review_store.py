"""Company checkpoints separate progress from large, unchanged evidence pages."""
from __future__ import annotations

import hashlib
import json
import threading
from pathlib import Path

from .storage import atomic_write_json


FORMAT = "company_review_checkpoints_v1"


def company_directory(directory: Path, company: str) -> Path:
    return directory / "final-review-companies" / hashlib.sha256(company.encode()).hexdigest()


def load_company(directory: Path, company: str, *, evidence: bool, run_id: str | None = None) -> dict | None:
    folder = company_directory(directory, company)
    path = folder / "progress.json"
    if not path.exists():
        return None
    checkpoint = json.loads(path.read_text(encoding="utf-8"))
    if not checkpoint.get("run_id") or (run_id is not None and checkpoint["run_id"] != run_id):
        raise ValueError("公司审核检查点不属于本轮")
    report = checkpoint["report"]
    if report.get("company") != company:
        raise ValueError("审核检查点公司不匹配")
    if evidence:
        report["pages"] = json.loads((folder / "pages.json").read_text(encoding="utf-8"))
    return report


def load_review(directory: Path, *, evidence: bool = False) -> dict:
    payload = json.loads((directory / "final-review.json").read_text(encoding="utf-8"))
    if payload.get("checkpoint_format") == FORMAT:
        reports = []
        for row in payload.get("reports", []):
            report = load_company(directory, row["company"], evidence=evidence, run_id=payload["run_id"])
            if report is None:
                raise ValueError("公司审核检查点缺失")
            reports.append(report)
        payload["reports"] = reports
    if not evidence:
        for report in payload.get("reports", []):
            report["pages"] = {url: {k: v for k, v in page.items() if k != "text"}
                               for url, page in report.get("pages", {}).items()}
    return payload


class ReviewStore:
    def __init__(self, directory: Path, task: dict, run_id: str, companies: list[str], workers: int):
        if len(companies) != len(set(companies)):
            raise ValueError("最终审核公司任务不可重复")
        self.directory, self.companies = directory, companies
        self.run_id = run_id
        self.lock = threading.Lock()
        path = directory / "final-review.json"
        previous = json.loads(path.read_text()) if path.exists() else {}
        if previous.get("run_id", run_id) != run_id:
            raise ValueError("最终审核检查点不属于本轮")
        if previous.get("checkpoint_format") == FORMAT and previous.get("companies") != companies:
            raise ValueError("最终审核检查点任务分配发生变化")
        self.index = {**task, "run_id": run_id, "checkpoint_format": FORMAT,
                      "workers": workers, "companies": companies, "status": "running", "reports": []}
        self.entries = {}
        # Migrate old progress once, before replacing the old root checkpoint.
        # Existing shards may be ahead of the root index after an interrupted save.
        for report in previous.get("reports", []):
            company = report["company"]
            if company not in companies:
                raise ValueError("最终审核检查点包含未分配公司")
            if previous.get("checkpoint_format") != FORMAT:
                self._write_report(report, evidence_changed=True)
        for company in companies:
            report = load_company(directory, company, evidence=False, run_id=run_id)
            if report is not None:
                self._record(report)
        self._write_index()

    def _write_report(self, report: dict, *, evidence_changed: bool):
        folder = company_directory(self.directory, report["company"])
        if evidence_changed:
            atomic_write_json(folder / "pages.json", report.get("pages", {}))
        metadata = {**report, "pages": {
            url: {k: v for k, v in page.items() if k != "text"}
            for url, page in report.get("pages", {}).items()}}
        atomic_write_json(folder / "progress.json", {"run_id": self.run_id, "report": metadata})

    def _record(self, report):
        self.entries[report["company"]] = {k: report[k] for k in
            ("company", "status", "review_completed") if k in report}

    def _write_index(self):
        self.index["reports"] = [self.entries[c] for c in self.companies if c in self.entries]
        atomic_write_json(self.directory / "final-review.json", self.index)

    def save(self, report: dict, *, evidence_changed: bool = False):
        self._write_report(report, evidence_changed=evidence_changed)
        with self.lock:
            self._record(report)
            self._write_index()

    def complete(self):
        with self.lock:
            if set(self.entries) != set(self.companies) or not all(
                row.get("review_completed") for row in self.entries.values()
            ):
                raise RuntimeError("公司审核未齐，不能完成汇总")
            self.index["status"] = "completed"
            self._write_index()
