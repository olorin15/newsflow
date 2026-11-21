import pytest

from newsflow.config import Settings, TelegramConfig
from newsflow.errors import ConfigError
from newsflow.sources import telegram as telegram_mod
from newsflow.sources.telegram import make_telegram_client

telethon = pytest.importorskip("telethon")


def make_cfg(**kw):
    return TelegramConfig(api_id="1", api_hash="h", phone="+1", **kw)


def test_fresh_session_path_constructs_client(tmp_path):
    cfg = make_cfg()
    session = tmp_path / "data" / "telegram" / "telega_ru.session"
    client = make_telegram_client(cfg, session)
    assert session.exists()  # telethon created a fresh session file
    client.session.close()


def test_incompatible_session_raises_actionable_error(tmp_path, monkeypatch):
    session = tmp_path / "old.session"
    session.write_bytes(b"not really a session")

    def boom(*a, **k):
        raise ValueError("too many values to unpack (expected 5)")

    monkeypatch.setattr("telethon.sync.TelegramClient", boom)
    with pytest.raises(ConfigError, match="different Telethon version"):
        make_telegram_client(make_cfg(), session)


def test_monitor_resolves_session_under_data_dir(tmp_path, monkeypatch):
    """The monitor must bind its session under data_dir, never the current cwd."""
    settings = Settings(
        data_dir="data", base_dir=tmp_path,
        telegram=make_cfg(channel_sets={"ru": ["@x"]}),
    )
    captured = {}

    class FakeClient:
        def __init__(self, session, api_id, api_hash):
            captured["session"] = session

        def start(self, phone):
            raise KeyboardInterrupt  # stop before any network use

        def on(self, event):
            return lambda f: f

        def run_until_disconnected(self):
            pass

    def fake_make_client(cfg, path):
        captured["path"] = path
        return FakeClient(str(path), cfg.api_id, cfg.api_hash)

    monkeypatch.setattr(telegram_mod, "make_telegram_client", fake_make_client)
    with pytest.raises(KeyboardInterrupt):
        telegram_mod.run_telegram_monitor(settings, "ru")
    assert captured["path"] == (tmp_path / "data" / "telegram" / "telega_ru.session").resolve()
