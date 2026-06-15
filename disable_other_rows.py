import json

with open("crawl_settings.json", "r", encoding="utf-8") as f:
    data = json.load(f)

for row_key, row_val in data.get("rows", {}).items():
    if row_key == "15":
        row_val["enabled"] = True
    else:
        row_val["enabled"] = False

with open("crawl_settings.json", "w", encoding="utf-8") as f:
    json.dump(data, f, ensure_ascii=False, indent=2)

print("Set all rows except 15 to enabled: false")
