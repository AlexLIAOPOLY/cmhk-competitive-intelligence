import copy
import unittest

from cmhk.intelligence.news_review_provenance import EditorEvidence, attach_screening_methods


def row(app="接受", weekly="待审核", record_id="NEWS-1", name="旧姓名"):
    return {"rowNumber": 160, "recordId": record_id,
            "values": [name, app, weekly, "", "", "", "", "同一新闻"]}


def event(kind, after="接受", field="纳入滚动栏", record_id="NEWS-1"):
    return {"action": "news_review.update", "result": "success", "source": "local_app",
            "actor_id": "robot" if kind == "machine" else "user-1",
            "actor_role": "SYSTEM" if kind == "machine" else "USER",
            "actor_name": "不能显示的姓名", "actor_avatar_url": "https://private.example/avatar",
            "details": {"news_id": record_id, "field": field, "after": after,
                        "feishu_readback": kind == "human"}}


def editor(open_id="human-1", offset=0):
    return {"event_id": open_id, "create_time_ms": 1788773407000 + offset,
            "operators": [{"open_id": open_id}]}


class ScreeningProvenanceTests(unittest.TestCase):
    def classify(self, events, item=None, editors=None):
        snapshot = {"rows": [item or row()]}
        attach_screening_methods(snapshot, events, editors or [])
        return snapshot["rows"][0]["screening"]

    def test_machine_then_human_is_human(self):
        result = self.classify([event("human"), event("machine", "不接受")])
        self.assertEqual(result["kind"], "human")
        self.assertEqual(result["label"], "人工筛选")
        self.assertNotIn("姓名", str(result))
        self.assertNotIn("avatar", str(result))

    def test_confirmed_human_same_value_still_wins(self):
        self.assertEqual(self.classify([event("human"), event("machine")])["kind"], "human")

    def test_machine_only(self):
        self.assertEqual(self.classify([event("machine")])["label"], "机器筛选")

    def test_later_machine_replacing_human_is_machine(self):
        self.assertEqual(self.classify([event("machine"), event("human", "不接受")])["kind"], "machine")

    def test_human_on_either_final_field_takes_priority(self):
        events = [event("machine"), event("human", field="纳入周报")]
        result = self.classify(events, row(weekly="接受"))
        self.assertEqual(result["kind"], "human")
        self.assertEqual(result["fields"], {"纳入滚动栏": "machine", "纳入周报": "human"})

    def test_unknown_new_write_blocks_older_machine(self):
        self.assertEqual(self.classify([event("unknown"), event("machine")])["kind"], "unknown")

    def test_receipt_must_match_current_value(self):
        self.assertEqual(self.classify([event("human", "不接受")])["kind"], "unknown")

    def test_historical_person_or_bot_name_is_not_evidence(self):
        for name in ["廖望 Alex LIAO Wang", "新闻自动初筛机器人", "人工筛选"]:
            self.assertEqual(self.classify([], row(name=name))["kind"], "unknown")

    def test_pending_has_no_claimed_author(self):
        self.assertEqual(self.classify([], row(app="待审核"))["kind"], "pending")

    def test_stable_id_survives_row_moves_without_borrowing_other_id(self):
        item = row(); item["rowNumber"] = 301
        self.assertEqual(self.classify([event("human")], item)["kind"], "human")
        self.assertEqual(self.classify([event("human", record_id="OTHER")], item)["kind"], "unknown")

    def test_batch_edit_only_attributes_its_exact_fields(self):
        e = event("human")
        e["details"] = {"feishu_readback": True, "cells": [{"news_id": "NEWS-1", "field": "纳入周报", "after": "接受"}]}
        result = self.classify([e, event("machine")], row(weekly="接受"))
        self.assertEqual(result["kind"], "human")
        self.assertEqual(result["fields"]["纳入滚动栏"], "machine")

    def test_failed_edit_does_not_replace_machine(self):
        failed = event("human"); failed["result"] = "error"
        self.assertEqual(self.classify([failed, event("machine")])["kind"], "machine")

    def test_local_history_and_live_rows_use_same_rules(self):
        item = row(); item.update(readOnly=True, storageSource="local_history")
        self.assertEqual(self.classify([event("human")], item)["kind"], "human")

    def test_exact_feishu_cell_and_unique_human_event(self):
        e = event("human")
        e.update(source="feishu_sheet", actor_open_id="human-1")
        e["details"].update(feishu_changeset_revision=56494,
                            feishu_changeset_at="2026-09-07T17:30:07+08:00", feishu_changeset_ai_edit=False)
        self.assertEqual(self.classify([e], editors=[editor()])["kind"], "human")
        # The incident: an older workbook event was incorrectly used for a later cell.
        self.assertEqual(self.classify([e], editors=[editor(offset=-17000), editor("bot")])["kind"], "unknown")
        self.assertEqual(self.classify([e], editors=[editor(), editor("bot")])["kind"], "unknown")
        self.assertEqual(self.classify([e], editors=[editor("another-human")])["kind"], "unknown")

    def test_missing_ai_flag_is_not_manual_evidence(self):
        evidence = EditorEvidence([editor()])
        for flag in [None, True, "false"]:
            self.assertIsNone(evidence.matching_event({"is_ai_edit": flag, "create_time": "2026-09-07T17:30:07+08:00"}))

    def test_ui_projection_does_not_change_archived_values(self):
        snapshot = {"rows": [row()]}; original = copy.deepcopy(snapshot["rows"][0]["values"])
        attach_screening_methods(snapshot, [event("human")], [])
        self.assertEqual(snapshot["rows"][0]["values"], original)


class ScreeningAuditIntegrationTests(unittest.TestCase):
    def run_audit(self, flag, editor_events, profile, *, stale_machine=None):
        from pathlib import Path
        from tempfile import TemporaryDirectory
        from unittest import mock
        import web_app
        from cmhk.auth.service import AuthService
        from cmhk.intelligence.news_review_sheet import HEADERS

        before = {"sheetId": "SHEET", "headers": HEADERS, "spreadsheetRevision": 100,
                  "rows": [row(app="待审核")]}
        after = {"sheetId": "SHEET", "headers": HEADERS, "spreadsheetRevision": 101,
                 "rows": [row(app="接受")]}
        with TemporaryDirectory() as directory:
            auth = AuthService(Path(directory))
            with (
                mock.patch.object(web_app, "AUTH", auth),
                mock.patch.object(web_app, "NEWS_REVIEW_AUDIT_STATE_PATH", Path(directory) / "state.json"),
                mock.patch.object(web_app, "sheet_edit_events", side_effect=[[], editor_events]),
                mock.patch.object(auth, "feishu_profile_by_open_id", side_effect=lambda oid, uid: profile if oid == "human-1" else {}),
                mock.patch.object(web_app, "_news_auto_screening_decisions", return_value=[]),
                mock.patch.object(web_app, "_news_auto_screening_match", return_value=stale_machine),
                mock.patch.object(web_app, "_news_review_changeset_cell_evidence", return_value={
                    (160, 1): {"is_ai_edit": flag, "revision": 101,
                               "create_time": "2026-09-07T17:30:07+08:00", "action": "setRangeValues"},
                }),
            ):
                web_app.sync_news_review_sheet_audit(before)
                return web_app.sync_news_review_sheet_audit(after)

    def test_incident_does_not_attribute_bot_time_to_earlier_human(self):
        events = self.run_audit(False, [editor(offset=-17000), editor("bot")],
                                {"id": "human-1", "name": "Person"})
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["actor_role"], "UNKNOWN")
        self.assertEqual(events[0]["actor_name"], "来源待核实")

    def test_verified_later_human_overrides_stale_matching_machine_receipt(self):
        events = self.run_audit(False, [editor()], {"id": "human-1", "name": "Person"},
                                stale_machine={"agent_run_id": "OLD", "recorded_at_iso": "2026-09-07T17:00:00+08:00"})
        self.assertEqual(events[0]["actor_role"], "EXTERNAL")
        self.assertEqual(events[0]["actor_open_id"], "human-1")
        self.assertNotIn("agent_run_id", events[0]["details"])

    def test_absent_ai_flag_does_not_become_false_and_human(self):
        events = self.run_audit(None, [editor()], {"id": "human-1", "name": "Person"})
        self.assertEqual(events[0]["actor_role"], "UNKNOWN")
        self.assertIsNone(events[0]["details"]["feishu_changeset_ai_edit"])

    def test_machine_receipt_is_not_relabelled_human_by_user_credentials(self):
        events = self.run_audit(False, [editor()], {"id": "human-1", "name": "Person"},
                                stale_machine={"agent_run_id": "CURRENT", "recorded_at_iso": "2026-09-07T17:30:08+08:00"})
        self.assertEqual(events[0]["actor_role"], "SYSTEM")
        self.assertEqual(events[0]["details"]["agent_run_id"], "CURRENT")


if __name__ == "__main__":
    unittest.main()
