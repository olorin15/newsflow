"""Collect Google News headlines via SerpApi into a dated text file.

The output file is meant to be fed to ``newsflow brief --source file``.
"""

from __future__ import annotations

from datetime import datetime

import requests

from ..config import Settings
from ..errors import ConfigError
from ..util import atomic_write_text

SERPAPI_URL = "https://serpapi.com/search"


def get_combined_headlines(cfg) -> list[dict[str, str]]:
    """Query SerpApi Google News and tag each result with a source label."""
    if not cfg.serp_api_key:
        raise ConfigError("news_search.serp_api_key is empty (set ${SERP_API_KEY} in the config).")
    params = {
        "engine": "google_news_light",
        "q": cfg.query,
        "no_cache": True,
        "api_key": cfg.serp_api_key,
    }
    response = requests.get(SERPAPI_URL, params=params, timeout=30)
    response.raise_for_status()
    data = response.json()

    headlines = []
    for result in data.get("news_results", []):
        link = result.get("link", "")
        source = "News"
        for needle, label in cfg.source_map.items():
            if needle in link:
                source = label
                break
        headlines.append({
            "source": source,
            "title": result.get("title", ""),
            "link": link,
            "date": result.get("date", "N/A"),
        })
    return headlines


def render_headlines(headlines: list[dict[str, str]]) -> str:
    lines = []
    for idx, headline in enumerate(headlines, 1):
        lines.append(f"{idx}. {headline['source']}: {headline['title']} ({headline['date']})")
        lines.append(f"   Link: {headline['link']}")
    return "\n".join(lines) + "\n"


def run_news_search(settings: Settings) -> int:
    """Fetch headlines and write them to the configured output file."""
    cfg = settings.news_search
    if cfg is None:
        raise ConfigError("This command needs a `news_search:` section in the config file.")

    headlines = get_combined_headlines(cfg)
    if not headlines:
        print("No headlines returned.")
        return 0
    out = settings.data_path(cfg.output_pattern.format(date=f"{datetime.now().astimezone():%Y-%m-%d}"))
    atomic_write_text(out, render_headlines(headlines))
    print(f"Wrote {len(headlines)} headlines to {out}")
    return 0
