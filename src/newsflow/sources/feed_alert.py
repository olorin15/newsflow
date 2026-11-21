"""Monitor a single Atom/RSS feed and email newly published entries.

First run only records the current entries as seen (no email); later runs
send one alert per batch of new entries. State is saved only after delivery
succeeds, so a mail failure retries on the next run instead of losing alerts.
"""

from __future__ import annotations

from datetime import datetime, timezone
from html import escape
from pathlib import Path

import feedparser

from ..config import EmailConfig, Settings
from ..errors import ConfigError
from ..notify.email import send_email_file
from ..util import load_json_state, save_json_state

DEFAULT_STATE_PATH = "state/feed_alert.json"
MAX_SEEN = 500


def entry_id(entry) -> str:
    value = entry.get("id") or entry.get("link") or entry.get("title")
    if not value:
        raise ConfigError("Feed entry has no id, link, or title")
    return str(value)


def render_entry(entry, feed_url: str) -> tuple[str, str]:
    title = str(entry.get("title", "(Untitled post)"))
    link = str(entry.get("link", feed_url))
    published = str(entry.get("published", entry.get("updated", "")))
    summary = str(entry.get("summary", entry.get("description", ""))).strip()

    text = f"{title}\n{link}"
    if published:
        text += f"\nPublished: {published}"
    if summary:
        text += f"\n\n{summary}"

    html = f"<h2><a href=\"{escape(link, quote=True)}\">{escape(title)}</a></h2>"
    if published:
        html += f"<p><strong>Published:</strong> {escape(published)}</p>"
    if summary:
        html += f"<div>{summary}</div>"
    html += f"<p><a href=\"{escape(link, quote=True)}\">Open post</a></p>"
    return text, html


def run_feed_alert(settings: Settings, feed_url: str, title: str | None = None,
                   state_path: str | None = None) -> int:
    """Check one feed; email new entries if any. Returns exit code."""
    email_cfg = settings.email
    if not email_cfg.to:
        raise ConfigError("email.to is empty — configure at least one recipient.")

    state_file = Path(state_path) if state_path else settings.data_path(DEFAULT_STATE_PATH)
    feed = feedparser.parse(feed_url)
    if getattr(feed, "bozo", False) and not feed.entries:
        raise ConfigError(f"Unable to parse feed {feed_url}: {feed.bozo_exception}")
    if not feed.entries:
        raise ConfigError(f"The feed {feed_url} returned no entries; retaining existing state.")

    entries = list(feed.entries)
    entries.reverse()  # feeds arrive newest-first; alerts read oldest -> newest
    current_ids = [entry_id(entry) for entry in entries]
    state = load_json_state(state_file, {"initialized": False, "seen_ids": []})

    if not state.get("initialized", False):
        save_json_state(state_file, {
            "initialized": True,
            "seen_ids": current_ids[:MAX_SEEN],
            "initialized_at": datetime.now(timezone.utc).isoformat(),
            "feed_url": feed_url,
        })
        print(f"Initialized with {len(current_ids)} current entries; no email sent.")
        return 0

    seen_ids = set(state["seen_ids"])
    new_entries = [entry for entry in entries if entry_id(entry) not in seen_ids]

    if new_entries:
        feed_title = title or feed.feed.get("title", feed_url)
        noun = "post" if len(new_entries) == 1 else "posts"
        text_parts = [f"{len(new_entries)} new {noun} in {feed_title}."]
        html_parts = [f"<p>{len(new_entries)} new {noun} in {escape(feed_title)}.</p>"]
        for entry in new_entries:
            text, html = render_entry(entry, feed_url)
            text_parts.append(text)
            html_parts.append(html)

        from ..util import atomic_write_text
        body_file = settings.data_path(f"alert-{datetime.now().astimezone():%Y-%m-%d-%H%M%S}.html")
        atomic_write_text(body_file, "\n<hr>\n".join(html_parts))
        send_email_file(
            email_cfg,
            subject=f"{feed_title}: {len(new_entries)} new {noun}",
            body_file=body_file,
            intro="\n\n".join(text_parts),
        )
        print(f"Sent alert for {len(new_entries)} new post(s).")
    else:
        print("No new posts.")

    updated_seen_ids = []
    for value in current_ids + state["seen_ids"]:
        if value not in updated_seen_ids:
            updated_seen_ids.append(value)
    save_json_state(state_file, {
        "initialized": True,
        "seen_ids": updated_seen_ids[:MAX_SEEN],
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "feed_url": feed_url,
    })
    return 0
