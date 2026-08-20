from pathlib import Path
lines = [
    "-> /Users/liaowang/Desktop/揭榜挂帅需求/cmhk_public_crawl_20260521/weekly_report.md",
    "-> /Users/liaowang/Desktop/揭榜挂帅需求/cmhk_public_crawl_20260521/weekly_report.html",
    "-> /Users/liaowang/Desktop/揭榜挂帅需求/cmhk_public_crawl_20260521/6月8日周报 (3).docx",
    "-> /Users/liaowang/Desktop/揭榜挂帅需求/cmhk_public_crawl_20260521/weekly_report_template.md",
    "-> /Users/liaowang/Desktop/揭榜挂帅需求/cmhk_public_crawl_20260521/weekly_report_template.docx",
]

created_path = None
for text in lines:
    if text.startswith("->"):
        candidate = Path(text[2:].strip())
        print(f"Checking: {candidate.name}, exists: {candidate.exists()}, docx: {candidate.name.endswith('.docx')}, template: {'template' not in candidate.name}")
        if candidate.exists() and candidate.name.endswith(".docx") and "template" not in candidate.name:
            created_path = candidate
            print(f"Set created_path to {created_path}")
print("Final created_path:", created_path)
