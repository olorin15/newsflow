"""Archive new entries from OPML-exported RSS feeds into daily text files.

Ported from the NetNewsWire archiver script; every path and knob comes from
the ``rss:`` config section. Run once to initialize state (existing entries
are not archived unless ``rss.archive_initial: true``), then schedule with
cron — each later run appends unseen entries to ``feed-items-YYYY-MM-DD.txt``.
"""

from __future__ import annotations

import hashlib
import sys
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path

import feedparser

from ..config import Settings
from ..errors import ConfigError
from ..util import html_to_text, load_json_state, save_json_state


def parse_opml(path: Path) -> list[dict[str, str]]:
    """Parse an OPML file into a flat list of feed dicts (folders preserved)."""
    if not path.exists():
        raise ConfigError(
            f"OPML file not found: {path}\n"
            "In NetNewsWire, use File > Export Subscriptions and point rss.opml_path at it."
        )

    root = ET.parse(path).getroot()
    body = root.find("body")
    if body is None:
        raise ConfigError(f"Invalid OPML: no <body> element in {path}")

    feeds: list[dict[str, str]] = []

    def walk(node: ET.Element, folders: list[str]) -> None:
        for outline in node.findall("outline"):
            title = (outline.attrib.get("title") or outline.attrib.get("text") or "").strip()
            url = outline.attrib.get("xmlUrl", "").strip()
            if url:
                feeds.append({
                    "feed_url": url,
                    "feed_title": title or url,
                    "folder": " / ".join(folders),
                })
            else:
                walk(outline, folders + ([title] if title else []))

    walk(body, [])
    deduplicated: dict[str, dict[str, str]] = {}
    for feed in feeds:
        deduplicated.setdefault(feed["feed_url"], feed)
    return list(deduplicated.values())


def stable_entry_id(entry) -> str:
    candidate = entry.get("id") or entry.get("link")
    if candidate:
        return str(candidate).strip()
    material = "\x1f".join(
        str(entry.get(key, "")) for key in ("title", "published", "updated", "summary", "description")
    )
    return "sha256:" + hashlib.sha256(material.encode("utf-8")).hexdigest()


def entry_datetime(entry) -> datetime:
    for key in ("published_parsed", "updated_parsed"):
        value = entry.get(key)
        if value:
            return datetime(*value[:6], tzinfo=timezone.utc)
    for key in ("published", "updated"):
        value = entry.get(key)
        if value:
            try:
                parsed = parsedate_to_datetime(str(value))
                return parsed.astimezone(timezone.utc) if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
            except (TypeError, ValueError, IndexError):
                pass
    return datetime.now(timezone.utc)


def format_entry(feed: dict[str, str], entry) -> str:
    received = datetime.now().astimezone().isoformat(timespec="seconds")
    published = entry_datetime(entry).astimezone().isoformat(timespec="seconds")
    title = html_to_text(entry.get("title")) or "(Untitled entry)"
    link = str(entry.get("link") or "").strip()
    content = entry.get("content", [])
    body = ""
    if content:
        body = html_to_text(content[0].get("value", ""))
    if not body:
        body = html_to_text(entry.get("summary") or entry.get("description"))

    header = [
        "=" * 78,
        f"Feed: {feed['feed_title']}",
        f"Feed URL: {feed['feed_url']}",
    ]
    if feed["folder"]:
        header.append(f"Folder: {feed['folder']}")
    header += [
        f"Received: {received}",
        f"Published: {published}",
        f"Title: {title}",
    ]
    if link:
        header.append(f"Link: {link}")
    header += ["", body or "(No content provided by the feed.)", ""]
    return "\n".join(header)


def append_entries(archive_dir: Path, records: list[tuple[dict[str, str], object]]) -> Path:
    archive_dir.mkdir(parents=True, exist_ok=True)
    archive_path = archive_dir / f"feed-items-{datetime.now().astimezone():%Y-%m-%d}.txt"
    with archive_path.open("a", encoding="utf-8") as handle:
        for feed, entry in records:
            handle.write(format_entry(feed, entry))
            handle.write("\n")
    return archive_path


def run_opml_archive(settings: Settings) -> int:
    """Fetch all OPML feeds once and archive unseen entries. Returns exit code."""
    cfg = settings.rss
    if cfg is None:
        raise ConfigError("This command needs an `rss:` section in the config file.")

    opml_path = settings.resolve(cfg.opml_path)
    archive_dir = settings.data_path(cfg.archive_dir)
    state_path = settings.data_path(cfg.state_path)

    feeds = parse_opml(opml_path)
    state = load_json_state(state_path, {"version": 1, "feeds": {}})
    first_run = not state["feeds"]
    newly_found: list[tuple[dict[str, str], object]] = []
    checked = 0
    failures = []

    for feed in feeds:
        checked += 1
        parsed = feedparser.parse(feed["feed_url"], agent=cfg.user_agent)
        if getattr(parsed, "bozo", False) and not parsed.entries:
            failures.append(f"{feed['feed_title']}: {parsed.bozo_exception}")
            continue
        if not parsed.entries:
            continue

        feed_state = state["feeds"].get(feed["feed_url"], {"seen_ids": []})
        prior_seen = set(feed_state.get("seen_ids", []))
        entries = list(parsed.entries)
        unseen = [entry for entry in entries if stable_entry_id(entry) not in prior_seen]

        if feed["feed_url"] in state["feeds"] or cfg.archive_initial:
            newly_found.extend((feed, entry) for entry in reversed(unseen))

        ordered_ids = []
        for entry in entries + [{"id": value} for value in feed_state.get("seen_ids", [])]:
            identifier = stable_entry_id(entry)
            if identifier not in ordered_ids:
                ordered_ids.append(identifier)
        state["feeds"][feed["feed_url"]] = {
            "title": feed["feed_title"],
            "seen_ids": ordered_ids[: cfg.max_seen_per_feed],
            "last_checked": datetime.now(timezone.utc).isoformat(),
        }

    if newly_found:
        archive_path = append_entries(archive_dir, newly_found)
        print(f"Archived {len(newly_found)} new entries to {archive_path}")
    elif first_run and not cfg.archive_initial:
        print(f"Initialized {len(state['feeds'])} feeds; existing entries were not archived.")
    else:
        print(f"No new entries across {checked} feeds.")

    save_json_state(state_path, state)

    if failures:
        print(f"WARNING: {len(failures)} feed(s) could not be read:", file=sys.stderr)
        for failure in failures:
            print(f"  {failure}", file=sys.stderr)
    return 0
