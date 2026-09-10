import pytest


@pytest.fixture(autouse=True)
def isolated_internal_ai_key_health(tmp_path, monkeypatch):
    """Fault injection must never cool down real production keys or other tests."""
    monkeypatch.setenv("CMHK_INTERNAL_AI_KEY_STATE_PATH", str(tmp_path / "key-health.json"))
    monkeypatch.setenv("CMHK_INTERNAL_AI_RATE_STATE_PATH", str(tmp_path / "rate-limit.json"))
