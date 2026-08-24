from web_app import current_report_files
for f in current_report_files():
    if "6月8日周报 1" in f.name:
        print(f.name)
