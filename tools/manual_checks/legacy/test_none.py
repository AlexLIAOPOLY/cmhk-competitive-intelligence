import json, sys
from pathlib import Path
from tts_service import synthesize_report_audio


def main():
    res = synthesize_report_audio(Path("None"), force=True)
    print(res)


if __name__ == "__main__":
    main()
