"""The runtime reads the same installed skill used by the interactive agent."""
from functools import lru_cache
import json
import hashlib
import os
from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parents[1] / 'skills/cmhk-strategic-news-push'
TEMPLATE_VERSION = 'direct-source-list-v7-prefer-single-card'
PREPARATION_LEAD_MINUTES = 60


def text_model() -> str:
    """Personal-news prose, review and dedupe prefer the user's V4 Pro route."""
    return os.environ.get('CMHK_NEWS_TEXT_MODEL', 'DeepSeek-V4-Pro').strip() or 'DeepSeek-V4-Pro'


@lru_cache(maxsize=1)
def skill_contract() -> tuple[str, str]:
    content = (SKILL_DIR / 'SKILL.md').read_text(encoding='utf-8')
    content += '\n\n' + (SKILL_DIR / 'references/editorial.md').read_text(encoding='utf-8')
    return content, hashlib.sha256(content.encode()).hexdigest()


def compatible_skill_hashes() -> tuple[str, ...]:
    """Exact release mapping only; an unknown skill edit invalidates old reviews."""
    current = skill_contract()[1]
    try:
        mapping = json.loads((SKILL_DIR / 'references/cache-compatibility.json').read_text())
        compatible = mapping.get(current, {}).get('compatible_hashes', [])
    except (OSError, ValueError, AttributeError):
        compatible = []
    return tuple(dict.fromkeys([current, *compatible]))
