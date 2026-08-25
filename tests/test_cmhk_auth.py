import io
import json
import os
import sqlite3
import tempfile
import unittest
from email.message import Message
from pathlib import Path
from unittest.mock import patch
from urllib.parse import urlparse

from cmhk.auth.service import AuthService, MODULE_LABELS, ROLE_MODULES


class FakeHandler:
    def __init__(self, *, body=None, cookie="", origin="http://127.0.0.1:8765", client="127.0.0.1"):
        self.headers = Message()
        self.headers["Host"] = "127.0.0.1:8765"
        if cookie:
            self.headers["Cookie"] = cookie
        if origin:
            self.headers["Origin"] = origin
        raw = json.dumps(body or {}).encode("utf-8")
        self.headers["Content-Length"] = str(len(raw))
        self.headers["User-Agent"] = "CMHK auth test"
        self.rfile = io.BytesIO(raw)
        self.wfile = io.BytesIO()
        self.client_address = (client, 12345)
        self.status = None
        self.response_headers = []

    def send_response(self, status):
        self.status = status

    def send_header(self, name, value):
        self.response_headers.append((name, value))

    def end_headers(self):
        pass

    def header(self, name):
        return next((value for key, value in self.response_headers if key.lower() == name.lower()), "")

    def payload(self):
        return json.loads(self.wfile.getvalue() or b"{}")


class AuthServiceTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.env = patch.dict(os.environ, {
            "CMHK_AUTH_REQUIRE_LOGIN": "1",
            "CMHK_AUTH_ALLOW_DEV_LOGIN": "1",
            "CMHK_AUTH_ENV_FILE": "",
            "CMHK_FEISHU_APP_ID": "",
            "CMHK_FEISHU_APP_SECRET": "",
        }, clear=False)
        self.env.start()
        self.service = AuthService(Path(self.temp.name))

    def tearDown(self):
        self.env.stop()
        self.temp.cleanup()

    def dev_login(self, account="local-admin"):
        handler = FakeHandler(body={"account": account})
        self.assertTrue(self.service.handle(handler, "POST", urlparse("/api/auth/dev-login")))
        self.assertEqual(handler.status, 200)
        session = handler.header("Set-Cookie").split(";", 1)[0]
        return handler, session

    def test_login_page_exposes_only_feishu_sign_in(self):
        static_root = Path(__file__).resolve().parents[1] / "web" / "static"
        page = (static_root / "login.html").read_text(encoding="utf-8")
        self.assertIn('id="feishuLogin"', page)
        self.assertIn('class="login-motion"', page)
        self.assertIn("使用飞书账号登录", page)
        self.assertIn("@keyframes orbit-spin", page)
        self.assertNotIn('class="scan-visual"', page)
        self.assertNotIn("动态二维码", page)
        self.assertIn("min-height:610px", page)
        self.assertIn("minmax(400px,520px)", page)
        self.assertIn("login-hong-kong-network-bg-v1.webp", page)
        self.assertTrue((static_root / "assets" / "login-hong-kong-network-bg-v1.webp").is_file())
        self.assertNotIn("测试身份", page)
        self.assertNotIn("/api/auth/dev-login", page)
        self.assertNotIn("身份由服务端校验", page)
        self.assertIn("width:min(1480px,calc(100% - 48px))", page)
        self.assertIn("white-space:nowrap", page)
        self.assertIn("font-size:clamp(28px,8.5vw,48px)", page)

    def test_role_defaults_keep_leader_on_dashboard_only(self):
        self.assertEqual(ROLE_MODULES["LEADER"], ["dashboard"])
        self.assertEqual(MODULE_LABELS["dashboard"], "战略总览")
        self.assertEqual(MODULE_LABELS["news"], "新闻采集")
        self.assertEqual(MODULE_LABELS["review"], "新闻审核")
        self.assertEqual(MODULE_LABELS["competitor"], "竞对分析")
        self.assertEqual(MODULE_LABELS["subscriptions"], "订阅与推送")
        self.assertEqual(MODULE_LABELS["ai"], "小竞AI")
        self.assertEqual(MODULE_LABELS["log"], "任务日志")
        self.assertEqual(MODULE_LABELS["fault"], "报警处置")
        self.assertEqual(set(ROLE_MODULES["ADMIN"]), set(MODULE_LABELS))
        self.assertNotIn("organization", ROLE_MODULES["ANALYST"])

    def test_operational_pdf_reports_follow_alert_and_log_permissions(self):
        self.assertEqual(self.service.module_for_api("/api/alert-report.pdf"), "fault")
        self.assertEqual(self.service.module_for_api("/api/log-report.pdf"), "log")

    def test_unauthenticated_api_and_page_are_blocked(self):
        api = FakeHandler(origin="")
        self.assertFalse(self.service.authorize_api(api, "/api/status"))
        self.assertEqual(api.status, 401)
        page = FakeHandler(origin="")
        self.assertFalse(self.service.authorize_page(page, "/"))
        self.assertEqual(page.status, 302)
        self.assertIn("/static/login.html", page.header("Location"))

    def test_loopback_health_is_available_without_exposing_other_apis(self):
        local = FakeHandler(origin="")
        self.assertTrue(self.service.authorize_api(local, "/api/health"))
        remote = FakeHandler(origin="", client="192.0.2.10")
        self.assertFalse(self.service.authorize_api(remote, "/api/health"))
        self.assertEqual(remote.status, 401)
        proxied = FakeHandler(origin="")
        proxied.headers["X-Forwarded-For"] = "192.0.2.10"
        self.assertFalse(self.service.authorize_api(proxied, "/api/health"))
        self.assertEqual(proxied.status, 401)

    def test_dev_login_is_loopback_only_and_creates_session(self):
        denied = FakeHandler(body={"account": "local-admin"}, client="192.0.2.10")
        self.service.handle(denied, "POST", urlparse("/api/auth/dev-login"))
        self.assertEqual(denied.status, 404)
        _, session = self.dev_login()
        me = FakeHandler(cookie=session, origin="")
        self.service.handle(me, "GET", urlparse("/api/auth/me"))
        self.assertTrue(me.payload()["authenticated"])
        self.assertEqual(me.payload()["user"]["role"], "ADMIN")
        self.assertTrue(me.payload()["user"]["developmentAccount"])

    def test_enabling_dev_login_seeds_an_existing_empty_user_store(self):
        empty_root = Path(self.temp.name) / "existing-empty"
        with patch.dict(os.environ, {"CMHK_AUTH_ALLOW_DEV_LOGIN": "0"}):
            disabled = AuthService(empty_root)
        self.assertEqual(disabled._users(), [])
        enabled = AuthService(empty_root)
        self.assertEqual(len(enabled._users()), 5)

    def test_admin_can_assign_leader_and_server_enforces_module(self):
        _, admin_session = self.dev_login()
        users = self.service._users()
        users.append({
            "id": "leader-1", "account": "leader", "name": "领导测试", "email": "",
            "department": "管理层", "role": "UNCONFIGURED", "status": "active",
            "module_overrides": {}, "credential_source": "development_seed",
        })
        self.service._write(self.service.users_path, users)
        update = FakeHandler(
            body={"role": "LEADER", "status": "active", "modules": {key: key == "dashboard" for key in MODULE_LABELS}},
            cookie=admin_session,
        )
        self.service.handle(update, "POST", urlparse("/api/auth/admin/users/leader-1"))
        self.assertEqual(update.status, 200)
        _, leader_session = self.dev_login("leader")
        dashboard = FakeHandler(cookie=leader_session, origin="")
        self.assertTrue(self.service.authorize_api(dashboard, "/api/status"))
        ai = FakeHandler(cookie=leader_session, origin="")
        self.assertFalse(self.service.authorize_api(ai, "/api/chat-starters"))
        self.assertEqual(ai.status, 403)
        mutation = FakeHandler(cookie=leader_session, origin="")
        self.assertFalse(self.service.authorize_api(mutation, "/api/status", "POST"))
        self.assertEqual(mutation.status, 403)
        self.assertEqual(mutation.payload()["message"], "领导账号仅可查看战略总览")

    def test_direct_business_resources_follow_module_permissions(self):
        _, leader_session = self.dev_login("local-leader")
        ordinary_asset = FakeHandler(cookie=leader_session, origin="")
        self.assertTrue(self.service.authorize_resource(ordinary_asset, "/static/app.js"))
        competitor_data = FakeHandler(cookie=leader_session, origin="")
        self.assertFalse(self.service.authorize_resource(competitor_data, "/static/competitor-workbench-data.json"))
        report = FakeHandler(cookie=leader_session, origin="")
        self.assertFalse(self.service.authorize_resource(report, "/outputs/example.docx"))
        login = FakeHandler(origin="")
        self.assertTrue(self.service.authorize_resource(login, "/static/login.html"))
        login_background = FakeHandler(origin="")
        self.assertTrue(self.service.authorize_resource(login_background, "/static/assets/login-hong-kong-network-bg-v1.webp"))

    def test_unknown_api_fails_closed_and_proxy_cannot_use_dev_login(self):
        _, session = self.dev_login()
        unknown = FakeHandler(cookie=session, origin="")
        self.assertFalse(self.service.authorize_api(unknown, "/api/future-dangerous-action", "POST"))
        self.assertEqual(unknown.status, 403)
        proxied = FakeHandler(body={"account": "local-admin"})
        proxied.headers["X-Forwarded-For"] = "203.0.113.10"
        self.service.handle(proxied, "POST", urlparse("/api/auth/dev-login"))
        self.assertEqual(proxied.status, 404)

    def test_admin_cannot_self_lock_or_send_string_booleans(self):
        _, session = self.dev_login()
        string_value = FakeHandler(
            body={"role": "ADMIN", "status": "active", "modules": {"organization": "false"}},
            cookie=session,
        )
        self.service.handle(string_value, "POST", urlparse("/api/auth/admin/users/local-admin"))
        self.assertEqual(string_value.status, 400)
        self_lock = FakeHandler(
            body={"role": "LEADER", "status": "active", "modules": {key: key == "dashboard" for key in MODULE_LABELS}},
            cookie=session,
        )
        self.service.handle(self_lock, "POST", urlparse("/api/auth/admin/users/local-admin"))
        self.assertEqual(self_lock.status, 409)

    def test_admin_cannot_override_feishu_employee_position(self):
        _, session = self.dev_login()
        users = self.service._users()
        target = next(item for item in users if item["id"] == "local-content")
        target["title"] = "经理"
        self.service._write(self.service.users_path, users)

        update = FakeHandler(body={"title": "伪造岗位"}, cookie=session)
        self.service.handle(update, "POST", urlparse("/api/auth/admin/users/local-content"))
        self.assertEqual(update.status, 200)
        self.assertEqual(update.payload()["user"]["title"], "经理")
        stored = next(item for item in self.service._users() if item["id"] == "local-content")
        self.assertEqual(stored["title"], "经理")
        event = self.service.operation_audit()[0]
        self.assertEqual(event["details"]["after"]["title"], "经理")

    def test_email_collision_does_not_bind_existing_admin(self):
        users = self.service._users()
        admin = users[0]
        admin["email"] = "admin@hk.chinamobile.com"
        self.service._write(self.service.users_path, users)
        created = self.service._upsert_feishu_user({
            "open_id": "ou-new-person",
            "union_id": "on-new-person",
            "tenant_key": "tenant",
            "enterprise_email": "admin@hk.chinamobile.com",
            "name": "邮箱碰撞用户",
        })
        self.assertNotEqual(created["id"], admin["id"])
        self.assertEqual(created["role"], "UNCONFIGURED")

    def test_oauth_state_is_signed_and_rejects_tampering(self):
        state, cookie = self.service._oauth_state("/#workspace=dashboard")
        self.assertEqual(self.service._verify_oauth_state(cookie, state)["next"], "/#workspace=dashboard")
        self.assertIsNone(self.service._verify_oauth_state(cookie + "x", state))

    def test_oauth_start_is_rate_limited_per_client(self):
        handler = FakeHandler(origin="")
        self.assertTrue(all(self.service._allow_oauth_start(handler) for _ in range(20)))
        self.assertFalse(self.service._allow_oauth_start(handler))

    def test_operation_audit_is_separate_and_admin_only(self):
        _, admin_session = self.dev_login()
        actor = self.service.current_actor(FakeHandler(cookie=admin_session, origin=""))
        event = self.service.record_operation(
            actor=actor,
            action="fault.mark_handled",
            target="incident-1",
            details={"feishu_sync": "readback_verified"},
        )
        self.assertTrue(self.service.operation_audit_path.exists())
        self.assertNotEqual(self.service.operation_audit_path, self.service.audit_path)
        self.assertEqual(self.service.operation_audit()[0]["id"], event["id"])
        admin = FakeHandler(cookie=admin_session, origin="")
        self.service.handle(admin, "GET", urlparse("/api/auth/admin/audit?limit=20"))
        self.assertEqual(admin.status, 200)
        self.assertEqual(admin.payload()["events"][0]["target"], "incident-1")
        _, operations_session = self.dev_login("local-operations")
        denied = FakeHandler(cookie=operations_session, origin="")
        self.service.handle(denied, "GET", urlparse("/api/auth/admin/audit"))
        self.assertEqual(denied.status, 403)

    def test_directory_search_keeps_real_avatar_and_job_title(self):
        directory_payload = {
            "data": {"users": [{
                "name": "测试成员",
                "enterprise_email": "member@hk.chinamobile.com",
                "department": "科创及数智化部 - 科技创新管理",
                "is_activated": True,
            }]}
        }
        completed = type("Completed", (), {"stdout": json.dumps(directory_payload)})()
        profile = {"avatar_url": "https://example.test/member.webp", "title": "Project Manager", "department": "缓存部门"}
        with patch("cmhk.auth.service.subprocess.run", return_value=completed), patch.object(self.service, "_cached_directory_profile", return_value=profile):
            users = self.service._search_directory_users("测试")
        self.assertEqual(users[0]["avatar_url"], "https://example.test/member.webp")
        self.assertEqual(users[0]["title"], "Project Manager")
        self.assertEqual(users[0]["department"], "科创及数智化部 / 科技创新管理")

    def test_directory_email_search_uses_simplified_position_for_new_member(self):
        directory_payload = {
            "data": {"users": [{
                "name": "徐亮 Alan XU Liang",
                "enterprise_email": "alanxu@hk.chinamobile.com",
                "department": "科创及数智化部 - 科技创新管理",
                "job_title": "Manager, Government & Enterprise Business Support Service",
                "is_activated": True,
            }]}
        }
        completed = type("Completed", (), {"stdout": json.dumps(directory_payload)})()
        with patch("cmhk.auth.service.subprocess.run", return_value=completed), patch.object(
            self.service,
            "_feishu_profile_by_email",
            return_value={"title": "经理", "avatar_url": "https://example.test/alan.webp"},
        ):
            users = self.service._search_directory_users("alanxu@hk.chinamobile.com")
        self.assertEqual(users[0]["title"], "经理")
        self.assertEqual(users[0]["avatar_url"], "https://example.test/alan.webp")

    def test_directory_profile_does_not_treat_department_as_position(self):
        db_path = Path(self.temp.name) / "var" / "subscriptions" / "subscriptions.sqlite3"
        db_path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(db_path) as connection:
            connection.execute(
                """CREATE TABLE subscription_directory_people (
                       display_name TEXT, avatar_url TEXT, job_title TEXT,
                       department_names TEXT, active INTEGER)"""
            )
            connection.execute(
                "INSERT INTO subscription_directory_people VALUES (?, ?, ?, ?, 1)",
                ("测试成员", "https://example.test/avatar.webp", "", json.dumps([
                    "2025 Graduate Trainee", "Technology & Innovation Management",
                ])),
            )
        profile = self.service._cached_directory_profile("测试成员")
        self.assertEqual(profile["title"], "")
        self.assertEqual(profile["department"], "2025 Graduate Trainee / Technology & Innovation Management")

    def test_simplified_position_uses_first_value_from_authoritative_custom_field(self):
        self.service._custom_attr_cache = ([{
            "id": "position-field",
            "i18n_name": [{"locale": "zh_cn", "value": "简中岗位"}],
        }], float("inf"))
        position = self.service._simplified_position({
            "job_title": "Manager, Government & Enterprise Business Support Service",
            "custom_attrs": [{"id": "position-field", "value": {"text": "经理, 科技创新管理, 算力网络技术专家"}}],
        }, "token")
        self.assertEqual(position, "经理")

    def test_missing_title_is_included_in_feishu_profile_backfill(self):
        users = self.service._users()
        users.append({
            "id": "fs-title-gap", "account": "feishu_title_gap",
            "email": "member@hk.chinamobile.com", "name": "测试成员",
            "department": "科技创新管理", "title": "",
            "avatar_url": "https://example.test/avatar.webp",
            "credential_source": "feishu_sso", "role": "UNCONFIGURED", "status": "active",
        })
        self.service._write(self.service.users_path, users)
        with patch.object(self.service, "_feishu_profile_by_email", return_value={
            "title": "经理", "avatar_url": "https://example.test/avatar.webp",
        }):
            self.service._refresh_missing_feishu_profiles()
        refreshed = next(item for item in self.service._users() if item["id"] == "fs-title-gap")
        self.assertEqual(refreshed["title"], "经理")

    def test_admin_can_delete_member_but_not_current_account(self):
        _, session = self.dev_login()
        delete = FakeHandler(cookie=session, origin="")
        self.service.handle(delete, "DELETE", urlparse("/api/auth/admin/users/local-content"))
        self.assertEqual(delete.status, 200)
        self.assertFalse(any(user["id"] == "local-content" for user in self.service._users()))
        self.assertEqual(self.service.operation_audit()[0]["action"], "organization.user_delete")
        self_delete = FakeHandler(cookie=session, origin="")
        self.service.handle(self_delete, "DELETE", urlparse("/api/auth/admin/users/local-admin"))
        self.assertEqual(self_delete.status, 409)


if __name__ == "__main__":
    unittest.main()
