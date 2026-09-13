"""Read the complete backend for existing source-level UI contract checks."""

from pathlib import Path


def read_web_source(root: Path) -> str:
    paths = [root / "web_app.py", *sorted((root / "cmhk" / "web").glob("*.py"))]
    return "\n".join(path.read_text(encoding="utf-8") for path in paths)
