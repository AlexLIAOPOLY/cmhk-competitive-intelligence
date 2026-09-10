"""Recover one archived research run locally, without model calls or publication."""
from __future__ import annotations

import argparse
import fcntl
import json
import re
import shutil
from datetime import datetime
from pathlib import Path

from .research_storage import DOMAIN_PATHS, MAIN_PATH, audit_storage, domain_for, merge_domain, project_fact, read_object
from .storage import atomic_write_json


def repair(root: Path, run_id: str, *, apply: bool = False) -> dict:
    from .six_agent_research import now
    from cmhk.data.daily_financial_promotion import promote_daily_financial_facts
    from executive_intelligence_pipeline import _accepted_fact
    if not re.fullmatch(r"research_[A-Za-z0-9_-]+", run_id):
        raise ValueError("Invalid research run ID")
    root = root.resolve(strict=True)
    directory = root / "curation_data/research_runs" / run_id
    manifest = read_object(directory / "manifest.json")
    if manifest.get("run_id") != run_id or manifest.get("architecture") != "six_research_agents_v1":
        raise ValueError("Research archive identity mismatch")
    if manifest.get("status") not in {"completed", "partial"}:
        raise ValueError("Cannot repair an active or incomplete research archive")
    facts_path = directory / "verified_facts.jsonl"
    facts = [json.loads(line) for line in facts_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    if len(facts) != int(manifest.get("accepted") or 0):
        raise ValueError("Accepted count does not match archive; refusing partial recovery")
    if not all(_accepted_fact(fact) and fact.get("source_tier") == "official" and fact.get("evidence_hash") and domain_for(fact) for fact in facts):
        raise ValueError("Archive contains an ineligible fact")
    before = audit_storage(root, facts, expected=len(facts))
    if not apply:
        return {"dry_run": True, "agent_run_id": run_id, "readback": before}
    # Shared with the production pipeline; never repair while it is writing.
    with (root / "agent_knowledge/executive_intelligence_refresh/.refresh.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        for relative in DOMAIN_PATHS.values():
            read_object(root / relative, missing_ok=True)
        read_object(root / MAIN_PATH)
        stamp = datetime.now().strftime("%Y%m%dT%H%M%S%f")
        backup = root / "curation_data/backups/research-storage" / (run_id + "-" + stamp)
        targets = [*DOMAIN_PATHS.values(), MAIN_PATH,
                   str(Path(MAIN_PATH).with_suffix(".csv")),
                   str(Path(MAIN_PATH).with_name("quarterly_metrics_human_readable.csv")),
                   str(Path(MAIN_PATH).with_name("manifest.json")),
                   str((directory / "storage_receipt.json").relative_to(root))]
        for relative in targets:
            if (root / relative).exists():
                target = backup / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(root / relative, target)
        writes = {domain: merge_domain(root / relative,
                    [project_fact(fact) for fact in facts if domain_for(fact) == domain],
                    domain=domain, run_id=run_id, generated_at=now())
                  for domain, relative in DOMAIN_PATHS.items()}
        if not all(write["ok"] for write in writes.values()):
            raise ValueError(f"Source-fact conflict: recovery incomplete; backup retained at {backup}")
        promotion = promote_daily_financial_facts(database_path=root / MAIN_PATH,
            local_financial_path=root / "agent_knowledge/hk_competitor_product_tariffs/local_financial_results.json",
            verified_facts_path=facts_path, incremental_only=True)
        after = audit_storage(root, facts, expected=len(facts))
        result = {"agent_run_id": run_id, "repair_at": stamp, "backup_path": str(backup),
                  "before": before, "readback": after, "writes": writes, "main_table": promotion,
                  "scope": "local_storage_only_no_model_no_external_publish"}
        atomic_write_json(directory / "storage-repairs" / (stamp + ".json"), result)
        atomic_write_json(directory / "storage_receipt.json", result)
        if not after["ok"]:
            raise ValueError("Post-repair readback failed; see storage receipt and backup")
        return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    result = repair(args.root, args.run_id, apply=args.apply)
    print(json.dumps({key: value for key, value in result.items() if key not in {"before", "writes", "readback"}}, ensure_ascii=False))
    print(json.dumps({key: value for key, value in result["readback"].items() if key != "items"}, ensure_ascii=False))


if __name__ == "__main__":
    main()
