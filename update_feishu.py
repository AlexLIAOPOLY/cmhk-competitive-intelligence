import sys
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.append(str(ROOT))

from daily_crawl_and_write import read_range, write_range, MAIN_SHEET_ID, col_to_a1, current_headers, cell_text

def main():
    headers = current_headers()
    # Find "具体需要收集的数据" column index
    try:
        col_idx = headers.index("具体需要收集的数据")
    except ValueError:
        try:
            col_idx = headers.index("具体需收集的数据")
        except ValueError:
            print("Could not find Need column")
            sys.exit(1)
            
    col_str = col_to_a1(col_idx + 1)
    print(f"Need column is {col_str}")
    
    # Target financial rows for the companies
    target_rows = [2, 5, 8, 11, 15, 17]
    
    # Read current data to preserve existing text
    data = read_range(f"{MAIN_SHEET_ID}!{col_str}1:{col_str}200")
    
    updates = []
    
    for r in target_rows:
        idx = r - 1 # 0-indexed
        if idx < len(data) and data[idx]:
            val = cell_text(data[idx][0])
        else:
            val = ""
            
        if "派息" not in val:
            if r == 15: # HGC
                val += "、派息（HGC不适用）、资本开支、战略升级、券商观点（HGC不适用）、市场反应（HGC不适用）"
            else:
                val += "、派息、资本开支、战略升级、券商观点、市场反应"
                
            updates.append((r, val))
            
    if updates:
        for r, val in updates:
            print(f"Updating row {r}: {val}")
            write_range(f"{MAIN_SHEET_ID}!{col_str}{r}:{col_str}{r}", [[val]])
        print("Updated successfully.")
    else:
        print("No updates needed.")

if __name__ == '__main__':
    main()
