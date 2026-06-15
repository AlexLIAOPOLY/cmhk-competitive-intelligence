import subprocess
import json
token = "VLzwsCBZzhMPbztyrLMcAy7Fn4e"
import datetime

title = "Test Write " + str(datetime.datetime.now().timestamp())
out = subprocess.run(["lark-cli", "sheets", "+create-sheet", "--spreadsheet-token", token, "--title", title, "-q", ".data.sheet_id"], capture_output=True, text=True)
sheet_id = out.stdout.strip()

# Add dimension
subprocess.run(["lark-cli", "sheets", "+add-dimension", "--spreadsheet-token", token, "--sheet-id", sheet_id, "--dimension", "COLUMNS", "--length", "150"])

data = [list(range(150))]
res = subprocess.run(["lark-cli", "sheets", "+write", "--spreadsheet-token", token, "--sheet-id", sheet_id, "--range", f"{sheet_id}!A1:ET1", "--values", json.dumps(data)], capture_output=True, text=True)
print("STDOUT:", res.stdout)
print("STDERR:", res.stderr)
