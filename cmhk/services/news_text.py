"""Deterministic reader-facing Chinese conversion; never change source evidence."""
from opencc import OpenCC

_CONVERTER = OpenCC("t2s")

def simplified_news_text(value) -> str:
    """Keep Latin case, URLs and punctuation intact while converting Chinese."""
    return _CONVERTER.convert(str(value or ""))
