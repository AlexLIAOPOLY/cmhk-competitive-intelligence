import sys, json, subprocess
from pathlib import Path

latest_path = Path("/Users/liaowang/Desktop/揭榜挂帅需求/cmhk_public_crawl_20260521/6月8日周报 (3).docx")

code = "import sys, json\nfrom pathlib import Path\nfrom tts_service import synthesize_report_audio\ntry:\n    res = synthesize_report_audio(Path(sys.argv[1]), force=sys.argv[2] == 'True')\n    print(json.dumps({'ok': True, 'result': res}))\nexcept Exception as e:\n    print(json.dumps({'ok': False, 'error': str(e)}))"

proc_audio = subprocess.run([sys.executable, "-c", code, str(latest_path), "True"], capture_output=True, text=True)
print("stdout:", proc_audio.stdout)
print("stderr:", proc_audio.stderr)
