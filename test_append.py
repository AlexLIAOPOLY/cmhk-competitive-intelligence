import subprocess
import json
token = "VLzwsCBZzhMPbztyrLMcAy7Fn4e"
import datetime

title = "Test Append " + str(datetime.datetime.now().timestamp())
out = subprocess.run(["lark-cli", "sheets", "+create-sheet", "--spreadsheet-token", token, "--title", title, "-q", ".data.sheet_id"], capture_output=True, text=True)
sheet_id = out.stdout.strip()
print("Sheet ID:", sheet_id)

data = [list(range(150))]
res = subprocess.run(["lark-cli", "sheets", "+append", "--spreadsheet-token", token, "--sheet-id", sheet_id, "--values", json.dumps(data)], capture_output=True, text=True)
print("STDOUT:", res.stdout)
print("STDERR:", res.stderr)
