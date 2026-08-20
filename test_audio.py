import json
from pathlib import Path
from tts_service import audio_info_for_report
print(audio_info_for_report(Path("6月8日周报 (1).docx")))
