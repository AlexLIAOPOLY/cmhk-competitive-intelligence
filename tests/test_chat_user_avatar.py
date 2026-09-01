from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
INDEX = (ROOT / "web" / "static" / "index.html").read_text(encoding="utf-8")
APP = (ROOT / "web" / "static" / "app.js").read_text(encoding="utf-8")
AUTH = (ROOT / "web" / "static" / "auth-client.js").read_text(encoding="utf-8")
STYLE = (ROOT / "web" / "static" / "styles.css").read_text(encoding="utf-8")
ORGANIZATION_STYLE = (ROOT / "web" / "static" / "organization-admin.css").read_text(encoding="utf-8")


class ChatUserAvatarTests(unittest.TestCase):
    def test_user_messages_use_the_current_login_avatar(self):
        self.assertIn('document.createElement(role === "user" ? "button" : "span")', APP)
        self.assertIn('user?.avatarUrl', APP)
        self.assertIn('Promise.resolve(window.CMHKAuth?.ready)', APP)
        self.assertIn('classList.add("chat-user-avatar-button")', APP)
        self.assertIn('.message.user .chat-user-avatar-button img', STYLE)
        self.assertIn('position: absolute;', STYLE)
        self.assertIn('inset: 0;', STYLE)

    def test_user_avatar_opens_an_accessible_profile_card(self):
        self.assertIn('avatar.setAttribute("aria-haspopup", "dialog")', APP)
        self.assertIn('window.CMHKAuth?.openProfile(user, avatar)', APP)
        self.assertIn('className = "organization-profile-card auth-user-profile-card"', AUTH)
        self.assertIn('card.setAttribute("role", "dialog")', AUTH)
        self.assertIn('profileField("所属部门", user.department)', AUTH)
        self.assertIn('profileField("企业邮箱", user.email)', AUTH)
        self.assertIn('if (profileCard)', AUTH)
        self.assertIn('function positionProfileCard(card, anchor)', AUTH)
        self.assertIn('anchor?.getBoundingClientRect?.()', AUTH)
        self.assertIn('card.style.left', AUTH)
        self.assertIn('card.style.top', AUTH)
        self.assertIn('.organization-profile-card.auth-user-profile-card', ORGANIZATION_STYLE)

    def test_changed_assets_are_cache_busted(self):
        self.assertIn('/static/styles.css?v=293', INDEX)
        self.assertIn('/static/auth-client.js?v=5', INDEX)
        self.assertIn('/static/organization-admin.css?v=28', INDEX)
        self.assertIn('/static/app.js?v=320', INDEX)


if __name__ == "__main__":
    unittest.main()
