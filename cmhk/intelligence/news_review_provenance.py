"""Anonymous review methods derived from final, field-level write evidence."""

from bisect import bisect_left, bisect_right
from datetime import datetime


LABELS = {"human": "人工筛选", "machine": "机器筛选", "unknown": "来源待核实", "pending": "待筛选"}
FIELDS = {"纳入滚动栏": 1, "纳入周报": 2}
ALIASES = {"是否纳入滚动": "纳入滚动栏", "纳入滚动": "纳入滚动栏", "是否纳入周报": "纳入周报"}
HUMAN_ROLES = {"ADMIN", "EXTERNAL", "MEMBER", "USER", "UNCONFIGURED"}
MACHINE_ROLES = {"SYSTEM", "BOT", "ROBOT", "SERVICE", "AUTOMATION"}


def timestamp(value):
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).timestamp()
    except (ValueError, TypeError):
        return 0.0


class EditorEvidence:
    """Never discard unresolved/bot operators to manufacture a unique human."""

    def __init__(self, events):
        self.events = sorted((event for event in events if isinstance(event, dict)), key=self.time)
        self.times = [self.time(event) for event in self.events]

    @staticmethod
    def time(event):
        try:
            return float(event.get("create_time_ms") or event.get("create_time") or 0) / 1000
        except (ValueError, TypeError):
            return 0.0

    def matching_event(self, cell):
        if not isinstance(cell, dict) or cell.get("is_ai_edit") is not False:
            return None
        at = timestamp(cell.get("create_time"))
        if not at:
            return None
        # Changesets and file-edit events use separate clocks/precision. Only
        # correlate a tight two-second window, never an entire polling cycle.
        nearby = self.events[bisect_left(self.times, at - 2):bisect_right(self.times, at + 2)]
        identities = set()
        candidates = []
        for event in nearby:
            operators = event.get("operators") or []
            if not operators:
                return None
            for operator in operators:
                if not isinstance(operator, dict):
                    return None
                open_id = str(operator.get("open_id") or "")
                if not open_id:
                    return None
                identities.add(open_id)
            candidates.append(event)
        if len(identities) != 1:
            return None
        return min(candidates, key=lambda event: abs(self.time(event) - at))

    def human_audit_matches(self, event):
        details = event.get("details") if isinstance(event.get("details"), dict) else {}
        matched = self.matching_event({
            "is_ai_edit": details.get("feishu_changeset_ai_edit"),
            "create_time": details.get("feishu_changeset_at"),
        })
        if not matched or not details.get("feishu_changeset_revision"):
            return False
        actor_id = str(event.get("actor_open_id") or "")
        return bool(actor_id and all(
            operator.get("open_id") == actor_id for operator in matched.get("operators") or []
        ))


def audit_kind(event, editors):
    details = event.get("details") if isinstance(event.get("details"), dict) else {}
    role = str(event.get("actor_role") or "").upper()
    if (role in MACHINE_ROLES or event.get("actor_id") == "news-auto-screening-bot"
            or details.get("agent_run_id") or details.get("feishu_changeset_ai_edit") is True):
        return "machine"
    if role not in HUMAN_ROLES or not event.get("actor_id"):
        return "unknown"
    if event.get("source") == "feishu_sheet":
        return "human" if editors.human_audit_matches(event) else "unknown"
    if event.get("source") == "local_app" and details.get("feishu_readback") is True:
        return "human"
    return "unknown"


def attach_screening_methods(snapshot, ranked_events, editor_events):
    """Newest write per field wins; a surviving human review takes row priority.

    An unverified newer write blocks fallback to an older machine/human author.
    Current values must agree with the write receipt. Names alone prove nothing.
    """
    editors = EditorEvidence(editor_events)
    by_record, by_title = {}, {}
    rows = [row for row in snapshot.get("rows", []) if isinstance(row, dict)]
    title_counts = {}
    for row in rows:
        values = row.get("values") or []
        title = str(values[7] if len(values) > 7 else "")
        title_counts[title] = title_counts.get(title, 0) + 1
    for event in ranked_events:
        if not isinstance(event, dict):
            continue
        if event.get("action") != "news_review.update" or event.get("result") != "success":
            continue
        details = event.get("details") if isinstance(event.get("details"), dict) else {}
        kind = audit_kind(event, editors)
        cells = details.get("cells") or [details]
        for cell in cells:
            if not isinstance(cell, dict):
                continue
            field = str(cell.get("field") or "")
            field = ALIASES.get(field, field)
            if field not in FIELDS or "after" not in cell:
                continue
            record_id = str(cell.get("news_id") or cell.get("record_id") or "")
            title = str(cell.get("title") or cell.get("target_label") or "")
            evidence = {"kind": kind, "after": str(cell.get("after") or "")}
            if record_id:
                by_record.setdefault((record_id, field), evidence)
            elif title and title_counts.get(title) == 1:
                by_title.setdefault((title, field), evidence)
    for row in rows:
        values = row.get("values") or []
        title = str(values[7] if len(values) > 7 else "")
        record_id = str(row.get("recordId") or "")
        kinds = {}
        for field, column in FIELDS.items():
            value = str(values[column] if len(values) > column else "")
            evidence = by_record.get((record_id, field)) or by_title.get((title, field))
            if evidence and evidence["after"] == value:
                kinds[field] = evidence["kind"]
            elif value in {"", "待审核"} and not evidence:
                kinds[field] = "pending"
            else:
                kinds[field] = "unknown"
        active = set(kinds.values()) - {"pending"}
        kind = ("human" if "human" in active else "unknown" if "unknown" in active
                else "machine" if "machine" in active else "pending")
        row["screening"] = {"kind": kind, "label": LABELS[kind], "fields": kinds}
    return snapshot
