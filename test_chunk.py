import subprocess
import json
token = "VLzwsCBZzhMPbztyrLMcAy7Fn4e"
import datetime

title = "Test Chunk Write " + str(datetime.datetime.now().timestamp())
out = subprocess.run(["lark-cli", "sheets", "+create-sheet", "--spreadsheet-token", token, "--title", title, "-q", ".data.sheet_id"], capture_output=True, text=True)
sheet_id = out.stdout.strip()

# Add dimension
subprocess.run(["lark-cli", "sheets", "+add-dimension", "--spreadsheet-token", token, "--sheet-id", sheet_id, "--dimension", "COLUMNS", "--length", "150"])

def get_col_letter(n):
    res = ""
    n += 1
    while n > 0:
        n, rem = divmod(n - 1, 26)
        res = chr(65 + rem) + res
    return res

data = [list(range(150)) for _ in range(2)]

# Write first chunk
chunk1 = [row[:100] for row in data]
r1 = f"{sheet_id}!A1:{get_col_letter(99)}2"
res1 = subprocess.run(["lark-cli", "sheets", "+write", "--spreadsheet-token", token, "--sheet-id", sheet_id, "--range", r1, "--values", json.dumps(chunk1)], capture_output=True, text=True)
print("CHUNK 1:", res1.stderr or res1.stdout)

# Write second chunk
chunk2 = [row[100:] for row in data]
r2 = f"{sheet_id}!{get_col_letter(100)}1:{get_col_letter(149)}2"
res2 = subprocess.run(["lark-cli", "sheets", "+write", "--spreadsheet-token", token, "--sheet-id", sheet_id, "--range", r2, "--values", json.dumps(chunk2)], capture_output=True, text=True)
print("CHUNK 2:", res2.stderr or res2.stdout)
