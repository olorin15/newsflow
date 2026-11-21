"""The `brief` pipeline: read a collected text file, summarize it with the
configured LLM, save the summary, deliver it (email / Medium / Substack),
and optionally clear the input file after success.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from .config import Settings
from .errors import ConfigError
from .llm import make_summarizer
from .notify.email import send_email_file
from .util import atomic_write_text

log = logging.getLogger(__name__)

DEFAULT_INPUT_PATTERNS = {
    "rss": "rss_archive/feed-items-{date}.txt",
    "file": "",  # must be given via --input
}
DEFAULT_OUTPUT_PATTERNS = {
    "telegram": "telegram/summary_{channels}.txt",
    "rss": "rss_archive/summary_rss.txt",
    "file": "summaries/summary.txt",
}


@dataclass
class BriefResult:
    input_file: Path
    output_file: Path
    summary: str
    emailed: bool
    cleared: bool


def resolve_paths(settings: Settings, source: str, channels: str, input_override: str | None,
                  output_override: str | None) -> tuple[Path, Path]:
    """Compute input/output files for a brief run."""
    brief = settings.brief
    date = f"{datetime.now().astimezone():%Y-%m-%d}"

    if source == "telegram":
        if settings.telegram is None:
            raise ConfigError("source=telegram needs a `telegram:` section in the config.")
        default_input = settings.telegram.output_pattern
    else:
        default_input = DEFAULT_INPUT_PATTERNS[source]

    input_pattern = input_override or brief.input_pattern or default_input
    output_pattern = output_override or brief.output_pattern or DEFAULT_OUTPUT_PATTERNS[source]

    fmt = {"channels": channels, "date": date}
    input_file = settings.data_path(input_pattern.format(**fmt))
    output_file = settings.data_path(output_pattern.format(**fmt))
    return input_file, output_file


def run_brief(settings: Settings, source: str = "telegram", channels: str | None = None,
              input_file: str | None = None, output_file: str | None = None,
              model: str | None = None, no_email: bool = False, no_clear: bool = False,
              publish: bool = False) -> BriefResult:
    """Run one summarize-and-deliver cycle. Returns what happened."""
    brief = settings.brief
    channels = channels or brief.channels
    if source not in {"telegram", "rss", "file"}:
        raise ConfigError(f"Unknown brief source {source!r} (telegram | rss | file).")

    in_path, out_path = resolve_paths(settings, source, channels, input_file, output_file)

    if not in_path.exists():
        raise ConfigError(f"Input file not found: {in_path}")
    text = in_path.read_text(encoding="utf-8")
    print(text)
    if not text.strip():
        print("No messages to summarize.")
        raise ConfigError(f"Input file {in_path} is empty.")

    llm_cfg = settings.llm.model_copy(update={"model": model} if model else {})
    summarizer = make_summarizer(llm_cfg)
    lang1 = brief.lang_map.get(channels, channels)
    summary = summarizer.summarize(text, settings.llm.prompt, lang1=lang1, lang2=brief.target_lang)
    if not summary:
        raise ConfigError("Failed to generate summary.")

    atomic_write_text(out_path, summary)
    print(f"Summary written to {out_path}")

    emailed = False
    if settings.email.enabled and not no_email:
        subject = settings.email.subject.format(channels=channels, lang=lang1, date=f"{datetime.now().astimezone():%Y-%m-%d}")
        send_email_file(settings.email, subject, out_path, intro=settings.email.intro)
        emailed = True
        print(f"Emailed to {settings.email.to}")

    cleared = False
    if brief.clear_input_after_success and not no_clear:
        atomic_write_text(in_path, "")
        cleared = True

    if publish:
        if brief.publish_medium or settings.brief.publish_medium:
            from .notify.medium import publish_to_medium
            title = settings.email.subject.format(channels=channels, lang=lang1, date=f"{datetime.now().astimezone():%Y-%m-%d}")
            result = publish_to_medium(out_path, title, settings.medium)
            print(f"Published to Medium: {result.get('data', {}).get('url') if result else None}")
        if brief.publish_substack or settings.brief.publish_substack:
            from .notify.substack import publish_note_from_file
            publish_note_from_file(out_path, settings.substack)
            print("Published to Substack notes.")

    return BriefResult(input_file=in_path, output_file=out_path, summary=summary,
                       emailed=emailed, cleared=cleared)
