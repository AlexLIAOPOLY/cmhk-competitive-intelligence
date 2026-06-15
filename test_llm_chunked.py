import json
from pathlib import Path
from verification import get_verification_llm
from langchain_core.messages import SystemMessage, HumanMessage
import concurrent.futures

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

def process_batch(batch_dict):
    llm = get_verification_llm()
    prompt = f"""你是一个数据提取专家。下面是从网页提取的各企业原始文本。
请你从这些文本中严格提取出**纯数字/数值**（可带单位，如“5.2亿”、“30%”），以及**来源链接**，填入JSON。

规则：
1. 每个字段提取一个对象，包含 "value" (纯数字/数值) 和 "source" (来源链接，通常以 SOURCE: 开头)。
2. "value" 绝对不要包含长篇描述，只能是极简的数据（如：12.5亿港元、450万）。
3. 如果原文找不到具体数值，"value" 填 ""。找不到 SOURCE 链接，"source" 填 ""。
4. 保持字段名不变，输出严格的JSON格式。

原始数据：
{json.dumps(batch_dict, ensure_ascii=False)}

输出格式示例：
{{
  "公司A": {{"字段1": {{"value": "5.2亿", "source": "https://..."}}, "字段2": {{"value": "", "source": ""}}}}
}}
"""
    try:
        resp = llm.invoke([
            SystemMessage(content="You are a JSON-only response bot. Only output valid JSON without any markdown."),
            HumanMessage(content=prompt)
        ])
        content = resp.content.strip()
        if content.startswith("```json"):
            content = content[7:-3].strip()
        elif content.startswith("```"):
            content = content[3:-3].strip()
        return json.loads(content)
    except Exception as e:
        print("Batch error:", e)
        return {}

items = list(companies_with_data.items())
batch_size = 5
batches = [dict(items[i:i + batch_size]) for i in range(0, len(items), batch_size)]

print(f"Total batches: {len(batches)}")
# test first batch
res = process_batch(batches[0])
print(json.dumps(res, ensure_ascii=False, indent=2))
