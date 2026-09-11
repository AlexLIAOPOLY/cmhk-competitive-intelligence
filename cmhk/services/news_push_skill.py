"""The runtime reads the same installed skill used by the interactive agent."""
from functools import lru_cache
import hashlib
from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parents[1] / 'skills/cmhk-strategic-news-push'
TEMPLATE_VERSION = 'direct-source-list-v1'
PREPARATION_LEAD_MINUTES = 60


@lru_cache(maxsize=1)
def skill_contract() -> tuple[str, str]:
    content = (SKILL_DIR / 'SKILL.md').read_text(encoding='utf-8')
    content += '\n\n' + (SKILL_DIR / 'references/editorial.md').read_text(encoding='utf-8')
    return content, hashlib.sha256(content.encode()).hexdigest()
