from datetime import datetime, timezone
from pathlib import Path

from newsflow.config import RssConfig, Settings
from newsflow.sources.opml import (
    entry_datetime,
    format_entry,
    parse_opml,
    run_opml_archive,
    stable_entry_id,
)

OPML = """<?xml version="1.0" encoding="UTF-8"?>
<opml version="1.1">
  <body>
    <outline text="News" title="News">
      <outline text="Feed A" xmlUrl="https://a.example.com/feed"/>
      <outline text="Feed B" xmlUrl="https://b.example.com/rss"/>
    </outline>
    <outline text="Feed A dup" xmlUrl="https://a.example.com/feed"/>
  </body>
</opml>
"""

RSS = """<?xml version="1.0"?>
<rss version="2.0"><channel><title>Feed A</title><link>https://a.example.com</link>
<item><title>Post one</title><link>https://a.example.com/1</link><guid>g1</guid>
<pubDate>Mon, 01 Jan 2026 10:00:00 GMT</pubDate>
<description>&lt;p&gt;Hello &lt;b&gt;world&lt;/b&gt;&lt;/p&gt;</description></item>
</channel></rss>
"""


def test_parse_opml_flat_and_dedup(tmp_path):
    opml = tmp_path / "subs.opml"
    opml.write_text(OPML, encoding="utf-8")
    feeds = parse_opml(opml)
    urls = [f["feed_url"] for f in feeds]
    assert urls == ["https://a.example.com/feed", "https://b.example.com/rss"]
    assert feeds[0]["folder"] == "News"


def test_stable_entry_id_prefers_id():
    assert stable_entry_id({"id": "abc", "link": "x"}) == "abc"
    assert stable_entry_id({"link": "x"}) == "x"
    assert stable_entry_id({"title": "t"}).startswith("sha256:")


def test_entry_datetime_parsed():
    dt = entry_datetime({"published_parsed": (2026, 1, 2, 3, 4, 5)})
    assert dt == datetime(2026, 1, 2, 3, 4, 5, tzinfo=timezone.utc)


def test_format_entry_html_to_text():
    feed = {"feed_url": "u", "feed_title": "F", "folder": "News"}
    entry = {
        "title": "<b>Hi</b>",
        "link": "https://x",
        "published_parsed": (2026, 1, 1, 0, 0, 0),
        "summary": "<p>Line1</p><p>Line2</p>",
    }
    out = format_entry(feed, entry)
    assert "Feed: F" in out and "Title: Hi" in out
    assert "Line1\nLine2" in out and "<p>" not in out


def test_run_opml_archive_two_runs(tmp_path):
    feed_file = tmp_path / "feed.xml"
    feed_file.write_text(RSS, encoding="utf-8")
    opml = tmp_path / "subs.opml"
    opml.write_text(
        OPML.replace("https://a.example.com/feed", feed_file.as_uri())
            .replace("https://b.example.com/rss", feed_file.as_uri()),
        encoding="utf-8",
    )
    settings = Settings(
        data_dir="data",
        base_dir=tmp_path,
        rss=RssConfig(
            opml_path=str(opml),
            archive_dir="archive",
            state_path="state.json",
            archive_initial=True,
        ),
    )
    # First run with archive_initial archives the existing entry
    assert run_opml_archive(settings) == 0
    archives = list((tmp_path / "data" / "archive").glob("feed-items-*.txt"))
    assert len(archives) == 1
    content = archives[0].read_text(encoding="utf-8")
    assert "Post one" in content and "Hello world" in content

    # Second run: entry already seen -> no new archive content
    assert run_opml_archive(settings) == 0
    assert archives[0].read_text(encoding="utf-8") == content

    # Add a new item to the feed -> archived on third run
    feed_file.write_text(RSS.replace("</channel>", """
<item><title>Post two</title><link>https://a.example.com/2</link><guid>g2</guid>
<pubDate>Tue, 02 Jan 2026 10:00:00 GMT</pubDate><description>Second</description></item>
</channel>"""), encoding="utf-8")
    assert run_opml_archive(settings) == 0
    content2 = archives[0].read_text(encoding="utf-8")
    assert "Post two" in content2 and content2 != content
