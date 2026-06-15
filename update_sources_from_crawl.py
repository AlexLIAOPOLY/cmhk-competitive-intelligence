import json
import sys
from pathlib import Path

ROOT = Path(__file__).parent
SOURCES_FILE = ROOT / "carrier_performance_sources.json"
OUTPUT_FILE = ROOT / "carrier_performance_candidates.json"
RESULTS_DIR = ROOT / "results"

ROW_TO_COMPANY = {
    2: "HKT / csl / 1O1O",
    5: "3HK / Hutchison",
    8: "SmarTone",
    11: "HKBN",
    15: "HGC",
    17: "i-CABLE"
}

def main():
    if not SOURCES_FILE.exists():
        print(f"File not found: {SOURCES_FILE}")
        sys.exit(1)
        
    try:
        sources = json.loads(SOURCES_FILE.read_text(encoding="utf-8"))
    except Exception as e:
        print(f"Error reading sources file: {e}")
        sys.exit(1)
    
    candidates = {}
    for row_no, company in ROW_TO_COMPANY.items():
        result_file = RESULTS_DIR / f"row_{row_no}.json"
        if not result_file.exists():
            continue
            
        try:
            result = json.loads(result_file.read_text(encoding="utf-8"))
        except Exception as e:
            print(f"Error reading {result_file}: {e}")
            continue
        
        extracted_data = {}
        # Try to pull from entity_results
        for entity_res in result.get("entity_results", []):
            if "extracted" in entity_res:
                extracted_data.update(entity_res["extracted"])
                
        # Fallback to top-level extracted
        if "extracted" in result:
             extracted_data.update(result["extracted"])
             
        if not extracted_data:
            continue
            
        if company not in sources.get("companies", {}):
            continue
        
        mapping = {
            "派息": "dividend",
            "资本开支": "capex",
            "战略升级": "strategy",
            "券商观点": "broker",
            "市场反应": "market"
        }
        
        for cn_key, en_key in mapping.items():
            if cn_key in extracted_data:
                val = str(extracted_data[cn_key]).strip()
                if val and val != "None":
                    candidates.setdefault(company, {})[en_key] = val
                    
    if candidates:
        OUTPUT_FILE.write_text(json.dumps(candidates, ensure_ascii=False, indent=2), encoding="utf-8")
        print("Saved crawl candidates for manual verification; publication fields were not overwritten.")
    else:
        print("No new carrier performance candidates found.")

if __name__ == "__main__":
    main()
