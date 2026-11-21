"""Unified command line interface.

    newsflow --config configs/telegram_ru.yaml collect-telegram --set ru
    newsflow --config configs/rss.yaml collect-opml
    newsflow --config configs/telegram_ru.yaml serve-telegram-rss --port 8000
    newsflow --config configs/telegram_ru.yaml brief --source telegram --channels ru
    newsflow --config configs/rss.yaml brief --source rss
    newsflow --config configs/headlines.yaml collect-serp
    newsflow --config configs/feed_alert.yaml alert-feed --feed-url https://...

The config path may also be given via the NEWSFLOW_CONFIG env var.
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from .config import load_settings
from .errors import NewsflowError


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="newsflow",
        description="Configurable news pipelines: collect -> summarize -> deliver.",
    )
    parser.add_argument(
        "--config", "-c", default=None,
        help="Path to a YAML config file (default: $NEWSFLOW_CONFIG or ./newsflow.yaml).",
    )
    parser.add_argument("--verbose", "-v", action="store_true", help="Enable debug logging.")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("collect-telegram", help="Monitor Telegram channels and append messages to a text file (long-running).")
    p.add_argument("--set", required=True, dest="channel_set", help="Channel set name from telegram.channel_sets.")

    p = sub.add_parser("serve-telegram-rss", help="Serve watched Telegram channels as RSS feeds.")
    p.add_argument("--host", default=None)
    p.add_argument("--port", type=int, default=None)

    sub.add_parser("collect-opml", help="Archive new entries from all OPML feeds into daily text files (cron-friendly).")

    p = sub.add_parser("collect-serp", help="Fetch Google News headlines via SerpApi into a dated text file.")

    p = sub.add_parser("alert-feed", help="Email new entries of a single Atom/RSS feed.")
    p.add_argument("--feed-url", required=True)
    p.add_argument("--title", default=None, help="Display title for the alert email.")
    p.add_argument("--state", default=None, help="Override the state file path.")

    p = sub.add_parser("brief", help="Summarize a collected file with the configured LLM and deliver it.")
    p.add_argument("--source", choices=["telegram", "rss", "file"], default=None,
                   help="Where the input comes from (default: brief.source in config).")
    p.add_argument("--channels", default=None, help="Channel set name (telegram source).")
    p.add_argument("--input", default=None, help="Explicit input file (overrides patterns).")
    p.add_argument("--output", default=None, help="Explicit output file for the summary.")
    p.add_argument("--model", default=None, help="Override llm.model for this run.")
    p.add_argument("--no-email", action="store_true", help="Do not send email.")
    p.add_argument("--no-clear", action="store_true", help="Do not clear the input file after success.")
    p.add_argument("--publish", action="store_true", help="Also publish via configured publishers (Medium/Substack).")

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)s %(name)s: %(message)s",
    )

    # python-dotenv: load .env next to the config (or cwd) before expanding ${VARS}.
    try:
        from dotenv import load_dotenv
        config_path = args.config or __import__("os").environ.get("NEWSFLOW_CONFIG")
        env_file = (Path(config_path).parent / ".env") if config_path else Path(".env")
        load_dotenv(env_file if env_file.exists() else None)
    except ImportError:
        pass

    try:
        settings = load_settings(args.config)

        if args.command == "collect-telegram":
            from .sources.telegram import run_telegram_monitor
            run_telegram_monitor(settings, args.channel_set)

        elif args.command == "serve-telegram-rss":
            from .sources.telegram_rss import run_telegram_rss_server
            run_telegram_rss_server(settings, host=args.host, port=args.port)

        elif args.command == "collect-opml":
            from .sources.opml import run_opml_archive
            return run_opml_archive(settings)

        elif args.command == "collect-serp":
            from .sources.news_search import run_news_search
            return run_news_search(settings)

        elif args.command == "alert-feed":
            from .sources.feed_alert import run_feed_alert
            return run_feed_alert(settings, args.feed_url, title=args.title, state_path=args.state)

        elif args.command == "brief":
            from .pipeline import run_brief
            source = args.source or settings.brief.source
            result = run_brief(
                settings, source=source, channels=args.channels,
                input_file=args.input, output_file=args.output, model=args.model,
                no_email=args.no_email, no_clear=args.no_clear, publish=args.publish,
            )
            print(f"Done: summary at {result.output_file}"
                  + ("" if result.emailed else " (not emailed)")
                  + ("" if result.cleared else " (input kept)"))
            return 0

    except NewsflowError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        return 130
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
