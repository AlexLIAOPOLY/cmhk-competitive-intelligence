import json
from web_app import build_status
status = build_status()
for o in status["outputs"]:
    if "6月8日周报" in o["name"]:
        print(type(o["audio"]))
        print(o["audio"].get("exists"))
