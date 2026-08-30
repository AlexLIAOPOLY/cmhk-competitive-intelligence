"""Shared fail-closed content checks for publishable weekly reports."""
from __future__ import annotations

import re
from typing import Any


_SORT_CONTROL_RE = re.compile(
    r"(?:數據用量|数据用量|價格|价格|合約期限|合约期限|月費|月费|排序)\s*"
    r"[-–—:：]\s*(?:高至低|低至高|長至短|长至短|短至長|短至长|升序|降序)",
    flags=re.I,
)

_NAVIGATION_MARKETING_PATTERNS = (
    r"總有一個適合你|总有一个适合你",
    r"5G\s*計劃任你揀|5G\s*计划任你拣",
    r"選擇此計劃|选择此计划",
    r"領取\s*SmarT\s*Pass|领取\s*SmarT\s*Pass",
    r"發掘\s*SmarTone\s*精選服務計劃|发掘\s*SmarTone\s*精选服务计划",
)


def weekly_text_has_navigation_noise(value: Any) -> bool:
    """Reject filter controls and promotional page chrome copied as report prose."""
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    if not text:
        return False
    if len(_SORT_CONTROL_RE.findall(text)) >= 2:
        return True
    return any(re.search(pattern, text, flags=re.I) for pattern in _NAVIGATION_MARKETING_PATTERNS)
