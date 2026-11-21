"""Live Telegram channel monitor: appends new messages to a per-set text file.

Long-running process. The file it writes is the input for
``newsflow brief --source telegram``.
"""

from __future__ import annotations

from pathlib import Path

from ..config import Settings, TelegramConfig
from ..errors import ConfigError


def make_telegram_client(cfg: TelegramConfig, session_path: Path):
    """Create a Telethon client bound to *session_path*.

    A session file written by a different Telethon version raises a raw
    ValueError from deep inside telethon; convert it into an actionable
    message here.
    """
    try:
        from telethon.sync import TelegramClient
        import telethon
    except ImportError as exc:
        raise ConfigError(
            "Telegram support requires extra dependencies: pip install 'newsflow[telegram]'"
        ) from exc

    session_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        return TelegramClient(str(session_path), cfg.api_id, cfg.api_hash)
    except ValueError as exc:
        raise ConfigError(
            f"Could not load Telegram session file {session_path}: {exc}\n"
            f"This almost always means the session was written by a different Telethon "
            f"version than the one installed here (installed: {telethon.__version__}). "
            f"Either upgrade to match the version that wrote the file "
            f"(pip install -U telethon), or delete/move the session file and log in again."
        ) from exc


def run_telegram_monitor(settings: Settings, channel_set: str) -> None:
    """Monitor the given channel set and append new messages to its text file."""
    cfg = settings.telegram
    if cfg is None:
        raise ConfigError("This command needs a `telegram:` section in the config file.")
    if channel_set not in cfg.channel_sets:
        available = ", ".join(sorted(cfg.channel_sets)) or "(none defined)"
        raise ConfigError(
            f"Unknown channel set {channel_set!r}. Configured sets: {available}"
        )

    try:
        from telethon.events import NewMessage
    except ImportError as exc:
        raise ConfigError(
            "Telegram support requires extra dependencies: pip install 'newsflow[telegram]'"
        ) from exc

    channels = cfg.channel_sets[channel_set]
    session_path = settings.data_path(
        cfg.session_pattern.format(session_prefix=cfg.session_prefix, channels=channel_set)
    )
    out_file = settings.data_path(cfg.output_pattern.format(channels=channel_set))
    out_file.parent.mkdir(parents=True, exist_ok=True)

    client = make_telegram_client(cfg, session_path)
    client.start(cfg.phone)
    print(f"Monitoring {len(channels)} channel(s) for set {channel_set!r} -> {out_file}")

    @client.on(NewMessage(chats=channels))
    async def handler(event):
        print(f"\n{event.chat.title}: {event.message.text}")
        with out_file.open("a", encoding="utf-8") as f:
            f.write(f"\n{event.chat.title}: {event.message.text}\n")

    client.run_until_disconnected()
