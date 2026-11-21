"""Serve watched Telegram channels as RSS feeds (FastAPI + SQLite backend).

Each configured slug is available at ``/feeds/{slug}.rss``; ``/healthz``
reports connection status. State is durable: new messages and edits are
upserted into SQLite, so restarts do not duplicate items.
"""

from __future__ import annotations

import html
from contextlib import asynccontextmanager
from datetime import datetime, timezone

from ..config import Settings
from ..errors import ConfigError


def iso_utc(dt: datetime | None) -> str | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).isoformat()


def message_title(text: str, fallback: str) -> str:
    cleaned = " ".join(text.split())
    if not cleaned:
        return fallback
    return cleaned[:160] + ("…" if len(cleaned) > 160 else "")


def as_html(text: str) -> str:
    # Safe baseline. Can be upgraded to use Telegram message entities for
    # correctly preserving text-link and formatting offsets.
    return html.escape(text).replace("\n", "<br>\n")


def create_app(settings: Settings):
    """Build the FastAPI app from settings. Extra deps imported lazily."""
    cfg = settings.telegram
    if cfg is None:
        raise ConfigError("This command needs a `telegram:` section in the config file.")
    if not cfg.watched_channels:
        raise ConfigError("telegram.watched_channels is empty — nothing to serve.")

    try:
        import aiosqlite
        import uvicorn  # noqa: F401  (ensures the extra is installed)
        from fastapi import FastAPI, HTTPException, Request, Response
        from feedgen.feed import FeedGenerator
        from telethon import events
    except ImportError as exc:
        raise ConfigError(
            "Telegram RSS server requires extra dependencies: pip install 'newsflow[telegram]'"
        ) from exc

    db_path = str(settings.data_path(cfg.rss_db_path))
    from .telegram import make_telegram_client
    client = make_telegram_client(cfg, settings.data_path(cfg.rss_session_path))
    slug_by_chat_id: dict[int, str] = {}

    async def init_db():
        async with aiosqlite.connect(db_path) as db:
            await db.executescript("""
            PRAGMA journal_mode = WAL;

            CREATE TABLE IF NOT EXISTS sources (
                chat_id INTEGER PRIMARY KEY,
                slug TEXT NOT NULL UNIQUE,
                username TEXT,
                title TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS posts (
                chat_id INTEGER NOT NULL,
                message_id INTEGER NOT NULL,
                published_at TEXT NOT NULL,
                edited_at TEXT,
                title TEXT NOT NULL,
                content_html TEXT NOT NULL,
                permalink TEXT,
                raw_text TEXT,
                PRIMARY KEY (chat_id, message_id),
                FOREIGN KEY (chat_id) REFERENCES sources(chat_id)
            );

            CREATE INDEX IF NOT EXISTS ix_posts_feed
                ON posts(chat_id, published_at DESC, message_id DESC);
            """)
            await db.commit()

    async def resolve_sources() -> dict[int, str]:
        """Resolve source entities once; return {chat_id: slug}."""
        resolved = {}
        for slug, entity_ref in cfg.watched_channels.items():
            entity = await client.get_entity(entity_ref)
            chat_id = int(entity.id)
            username = getattr(entity, "username", None)
            title = getattr(entity, "title", None) or username or slug

            async with aiosqlite.connect(db_path) as db:
                await db.execute("""
                    INSERT INTO sources(chat_id, slug, username, title, updated_at)
                    VALUES (?, ?, ?, ?, ?)
                    ON CONFLICT(chat_id) DO UPDATE SET
                        slug = excluded.slug,
                        username = excluded.username,
                        title = excluded.title,
                        updated_at = excluded.updated_at
                """, (chat_id, slug, username, title, iso_utc(datetime.now(timezone.utc))))
                await db.commit()

            resolved[chat_id] = slug
        return resolved

    async def canonical_permalink(event) -> str | None:
        # Public-channel permalink only; never expose a private-channel feed publicly.
        chat = await event.get_chat()
        username = getattr(chat, "username", None)
        if username:
            return f"https://t.me/{username}/{event.message.id}"
        return None

    async def upsert_event(event) -> None:
        msg = event.message
        chat_id = int(event.chat_id)
        if chat_id not in slug_by_chat_id:
            return

        text = msg.raw_text or ""
        title = message_title(text, f"Telegram post {msg.id}")
        content_html = as_html(text)
        permalink = await canonical_permalink(event)

        if msg.media and not text:
            content_html = (
                "<p>[Telegram post contains media]</p>"
                + (f'<p><a href="{html.escape(permalink, quote=True)}">Open in Telegram</a></p>'
                   if permalink else "")
            )

        async with aiosqlite.connect(db_path) as db:
            await db.execute("""
                INSERT INTO posts (
                    chat_id, message_id, published_at, edited_at,
                    title, content_html, permalink, raw_text
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(chat_id, message_id) DO UPDATE SET
                    edited_at = excluded.edited_at,
                    title = excluded.title,
                    content_html = excluded.content_html,
                    permalink = excluded.permalink,
                    raw_text = excluded.raw_text
            """, (
                chat_id, msg.id,
                iso_utc(msg.date),
                iso_utc(getattr(msg, "edit_date", None)),
                title, content_html, permalink, text,
            ))
            await db.commit()

    @client.on(events.NewMessage)
    async def on_new_message(event):
        await upsert_event(event)

    @client.on(events.MessageEdited)
    async def on_message_edited(event):
        await upsert_event(event)

    async def build_rss(slug: str, request: Request) -> str:
        async with aiosqlite.connect(db_path) as db:
            db.row_factory = aiosqlite.Row
            source = await (
                await db.execute("""
                    SELECT chat_id, slug, username, title
                    FROM sources
                    WHERE slug = ?
                """, (slug,))
            ).fetchone()

            if source is None:
                raise HTTPException(status_code=404, detail="Unknown feed")

            rows = await (
                await db.execute("""
                    SELECT message_id, published_at, edited_at, title,
                           content_html, permalink
                    FROM posts
                    WHERE chat_id = ?
                    ORDER BY published_at DESC, message_id DESC
                    LIMIT 100
                """, (source["chat_id"],))
            ).fetchall()

        feed_url = str(request.url)
        fg = FeedGenerator()
        fg.id(f"urn:telegram-rss:{source['chat_id']}")
        fg.title(source["title"])
        fg.link(href=feed_url, rel="self")
        fg.description(f"Telegram channel feed: {source['title']}")
        fg.language("en")

        for row in reversed(rows):  # RSS items generated oldest -> newest
            entry = fg.add_entry()
            entry.id(f"urn:telegram:{source['chat_id']}:{row['message_id']}")
            entry.title(row["title"])
            entry.content(row["content_html"], type="html")
            entry.published(row["published_at"])
            entry.updated(row["edited_at"] or row["published_at"])
            if row["permalink"]:
                entry.link(href=row["permalink"])

        return fg.rss_str(pretty=True).decode("utf-8")

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        await init_db()
        await client.start()
        global slug_by_chat_id
        slug_by_chat_id = await resolve_sources()
        try:
            yield
        finally:
            await client.disconnect()

    app = FastAPI(lifespan=lifespan)

    @app.get("/feeds/{slug}.rss", include_in_schema=False)
    async def rss_feed(slug: str, request: Request):
        xml = await build_rss(slug, request)
        return Response(content=xml, media_type="application/rss+xml; charset=utf-8")

    @app.get("/healthz", include_in_schema=False)
    async def healthz():
        return {"ok": client.is_connected()}

    return app


def run_telegram_rss_server(settings: Settings, host: str | None = None, port: int | None = None) -> None:
    """Start the Telegram-to-RSS server (blocking)."""
    cfg = settings.telegram
    if cfg is None:
        raise ConfigError("This command needs a `telegram:` section in the config file.")
    try:
        import uvicorn
    except ImportError as exc:
        raise ConfigError(
            "The RSS server requires extra dependencies: pip install 'newsflow[telegram]'"
        ) from exc

    app = create_app(settings)
    uvicorn.run(app, host=host or cfg.server_host, port=port or cfg.server_port)
