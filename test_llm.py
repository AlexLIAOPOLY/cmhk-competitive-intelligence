import json
from pathlib import Path
ROOT = Path(".")
results_dir = ROOT / "results"
row_files = sorted(results_dir.glob("row_*.json")) if results_dir.exists() else []

companies_raw = {}
for f in row_files:
    try:
        data = json.loads(f.read_text(encoding="utf-8"))
        for entity_result in data.get("entity_results", []):
            entity = entity_result.get("entity")
            if not entity: continue
            if entity_result.get("status") == "no_extraction": continue
            if entity not in companies_raw:
                companies_raw[entity] = {"fields": {}}
            extracted = entity_result.get("extracted", {})
            for k, v in extracted.items():
                if v and isinstance(v, str):
                    if k not in companies_raw[entity]["fields"]:
                        companies_raw[entity]["fields"][k] = v
                    else:
                        companies_raw[entity]["fields"][k] += " | " + v
    except Exception:
        pass

companies_with_data = {k: v for k, v in companies_raw.items() if v["fields"]}
field_set = set()
for info in companies_with_data.values():
    for k in info["fields"].keys():
        field_set.add(k)

raw_dump = {}
for comp, info in companies_with_data.items():
    truncated_fields = {}
    for k, v in info["fields"].items():
        truncated_fields[k] = v[:2000]
    raw_dump[comp] = truncated_fields

prompt_text = json.dumps(raw_dump, ensure_ascii=False)
print("Prompt length:", len(prompt_text))
print("Companies count:", len(companies_with_data))
print("Total unique fields:", len(field_set))
print("Total field-values to extract:", sum(len(c["fields"]) for c in companies_with_data.values()))
