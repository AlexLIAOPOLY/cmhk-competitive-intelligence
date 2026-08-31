from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
INDEX = (ROOT / "web" / "static" / "index.html").read_text(encoding="utf-8")
APP = (ROOT / "web" / "static" / "app.js").read_text(encoding="utf-8")
AUTH = (ROOT / "web" / "static" / "auth-client.js").read_text(encoding="utf-8")
STYLE = (ROOT / "web" / "static" / "styles.css").read_text(encoding="utf-8")


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

    def test_changed_assets_are_cache_busted(self):
        self.assertIn('/static/styles.css?v=292', INDEX)
        self.assertIn('/static/auth-client.js?v=4', INDEX)
        self.assertIn('/static/app.js?v=319', INDEX)


if __name__ == "__main__":
    unittest.main()
