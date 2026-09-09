"""Normalize user-visible text before a Feishu interactive card is sent."""
from __future__ import annotations

import re
from typing import Any


_BOLD_MARKER_RE = re.compile(r"\\?\*\\?\*")


def without_markdown_bold_markers(card: dict[str, Any]) -> dict[str, Any]:
    """Return a copy of *card* with raw Markdown bold markers removed.

    Feishu card delivery has more than one rendering path.  Some clients show
    ``**`` literally even when the element is declared as Markdown.  Keeping
    the normalization at the outbound boundary protects every current and
    future card without disturbing links, mentions, colours, or callbacks.
    """

    def normalize(value: Any, *, key: str = "") -> Any:
        if isinstance(value, dict):
            return {item_key: normalize(item, key=item_key) for item_key, item in value.items()}
        if isinstance(value, list):
            return [normalize(item, key=key) for item in value]
        if key == "content" and isinstance(value, str):
            return _BOLD_MARKER_RE.sub("", value)
        return value

    return normalize(card)
