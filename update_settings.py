import json

with open("crawl_settings.json", "r", encoding="utf-8") as f:
    data = json.load(f)

new_fields = ["派息", "资本开支", "战略升级", "券商观点", "市场反应"]
rows_to_update = ["2", "5", "8", "11", "15", "17"]

for row in rows_to_update:
    if row in data.get("rows", {}):
        existing_fields = data["rows"][row].get("fields", [])
        for field in new_fields:
            if field not in existing_fields:
                existing_fields.append(field)
        data["rows"][row]["fields"] = existing_fields

with open("crawl_settings.json", "w", encoding="utf-8") as f:
    json.dump(data, f, ensure_ascii=False, indent=2)

print("Successfully updated crawl_settings.json")
