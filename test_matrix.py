import json

cache_path = "results/_dashboard_cache.json"
try:
    with open(cache_path, "r", encoding="utf-8") as f:
        cleaned = json.loads(f.read())["stats"]
except Exception as e:
    print(e)
    exit(1)

field_set = set()
for comp, fields in cleaned.items():
    for k in fields.keys():
        field_set.add(k)
field_list = sorted(list(field_set))

headers = ["公司"] + field_list + ["置信度", "校验原因"]
print(f"Headers len: {len(headers)}")

def get_col_letter(n):
    res = ""
    n += 1
    while n > 0:
        n, rem = divmod(n - 1, 26)
        res = chr(65 + rem) + res
    return res

range_str = f"A1:{get_col_letter(len(headers)-1)}{1 + len(cleaned)}"
print(f"Range: {range_str}")
