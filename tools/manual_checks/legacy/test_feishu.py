import json

cache = json.loads(open("results/_dashboard_cache.json").read())
cleaned = cache["stats"]

field_set = set()
for comp, fields in cleaned.items():
    for k in fields.keys():
        field_set.add(k)
field_list = sorted(list(field_set))

headers = ["公司"] + field_list + ["置信度", "校验原因"]

def get_col_letter(n):
    res = ""
    n += 1
    while n > 0:
        n, rem = divmod(n - 1, 26)
        res = chr(65 + rem) + res
    return res

range_str = f"A1:{get_col_letter(len(headers)-1)}{len(cleaned) + 1}"
print("Headers length:", len(headers))
print("Matrix length:", len(cleaned) + 1)
print("Range string:", range_str)
