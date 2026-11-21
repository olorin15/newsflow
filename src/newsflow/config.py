"""Configuration loading: one YAML file + environment variable expansion.

Every previously hard-coded value lives in the YAML config. Secrets are
referenced as ``${ENV_VAR}`` (optionally ``${ENV_VAR:-default}``) and resolved
from the process environment, so no credential is ever stored in the repo.

Relative paths in the config are resolved against the config file's directory,
so a project can be checked out anywhere and still find its data files.
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field, ValidationError, field_validator

from .errors import ConfigError

_ENV_RE = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)(?::-([^}]*))?\}")

DEFAULT_SUMMARIZE_PROMPT = (
    "Summarize the following {lang1} text in {lang2}, using bullet points and "
    "formatting output as HTML. Start with the top 5 key takeaways. Limit the "
    "context to the provided sources and avoid diluting the original content.\n\n{text}"
)

DEFAULT_TRANSLATE_PROMPT = (
    "Translate the following text in {lang1} to {lang2}, keeping the HTML tag "
    "structure and CSS styling:\n\n{text}"
)


def expand_env(value: Any, source: str = "config") -> Any:
    """Recursively expand ``${VAR}`` / ``${VAR:-default}`` in strings."""
    if isinstance(value, str):
        def repl(match: re.Match) -> str:
            var, default = match.group(1), match.group(2)
            if var in os.environ:
                return os.environ[var]
            if default is not None:
                return default
            raise ConfigError(
                f"Environment variable {var!r} is referenced in {source} but is not set. "
                f"Add it to your environment or to a .env file (see .env.example)."
            )
        return _ENV_RE.sub(repl, value)
    if isinstance(value, dict):
        return {key: expand_env(item, source) for key, item in value.items()}
    if isinstance(value, list):
        return [expand_env(item, source) for item in value]
    return value


class TelegramConfig(BaseModel):
    """Telegram source settings (api credentials come from env vars)."""
    api_id: str
    api_hash: str
    phone: str
    #: Channel sets for the live monitor: name -> list of @usernames.
    channel_sets: dict[str, list[str]] = Field(default_factory=dict)
    #: Where the monitor appends raw messages, e.g. "telegram/{channels}.txt".
    output_pattern: str = "telegram/{channels}.txt"
    session_prefix: str = "telega"
    #: Telethon session file for the monitor, relative to data_dir.
    #: {session_prefix} and {channels} placeholders are available.
    session_pattern: str = "telegram/{session_prefix}_{channels}.session"
    #: Slug -> @username for the Telegram-to-RSS server.
    watched_channels: dict[str, str] = Field(default_factory=dict)
    #: Telethon session file for the RSS server, relative to data_dir.
    rss_session_path: str = "state/telegram_rss.session"
    rss_db_path: str = "state/telegram_rss.sqlite3"
    server_host: str = "127.0.0.1"
    server_port: int = 8000


class RssConfig(BaseModel):
    """OPML / NetNewsWire archiver settings."""
    opml_path: str
    archive_dir: str = "rss_archive"
    state_path: str = "state/rss_archiver.json"
    #: Archive entries already present on the first run (like NNW_ARCHIVE_INITIAL=1).
    archive_initial: bool = False
    max_seen_per_feed: int = 1000
    user_agent: str = "newsflow-opml-archiver/1.0 (+personal-use)"


class NewsSearchConfig(BaseModel):
    """SerpApi Google News headline collection (`collect-serp`)."""
    serp_api_key: str = ""
    query: str = ""
    #: Substring in result link -> source label, checked in order.
    source_map: dict[str, str] = Field(default_factory=dict)
    output_pattern: str = "headlines/{date}.txt"


class LlmConfig(BaseModel):
    """Summarization backend settings."""
    backend: str = "ollama"  # ollama | mistral
    model: str = "gemma4:12b"
    #: Ollama chat endpoint.
    url: str = "http://localhost:11434/api/chat"
    timeout: float = 600.0
    #: Prompt template; may use {text}, {lang1}, {lang2}.
    prompt: str = DEFAULT_SUMMARIZE_PROMPT
    mistral_api_key: str = ""
    #: Models tried in order when `model` fails (Mistral backend).
    mistral_fallback_models: list[str] = Field(
        default_factory=lambda: ["mistral-medium-latest", "mistral-small-latest"]
    )


class EmailConfig(BaseModel):
    """Email delivery settings. backend: smtp | sendemail | sendmail."""
    enabled: bool = True
    backend: str = "smtp"
    smtp_host: str = "smtp.gmail.com"
    smtp_port: int = 587
    #: Use SMTP_SSL (port 465 style) instead of STARTTLS.
    smtp_ssl: bool = False
    starttls: bool = True
    username: str = ""
    password: str = ""
    from_addr: str = ""
    to: list[str] = Field(default_factory=list)

    @field_validator("to", mode="before")
    @classmethod
    def _split_recipients(cls, value):
        """Allow a single string (e.g. from ${EMAIL_TO}) or comma-separated lists."""
        if isinstance(value, str):
            value = [value]
        recipients: list[str] = []
        for item in value:
            recipients.extend(part.strip() for part in str(item).split(",") if part.strip())
        return recipients

    subject: str = "Daily Briefing"
    #: Plain-text intro line prepended to the HTML body.
    intro: str = ""
    sendemail_path: str = "/opt/homebrew/bin/sendemail"
    sendmail_path: str = "sendmail"


class MediumConfig(BaseModel):
    token: str = ""
    user_id: str = ""
    content_format: str = "markdown"
    publish_status: str = "public"


class SubstackConfig(BaseModel):
    email: str = ""
    password: str = ""
    tab_id: str = "for-you"


class BriefConfig(BaseModel):
    """The summarize-and-deliver pipeline (`brief`)."""
    #: telegram | rss | file
    source: str = "telegram"
    channels: str = "ru"
    #: Input file pattern. Defaults depend on source; {channels} and {date} are
    #: available placeholders ({date} = local YYYY-MM-DD).
    input_pattern: str = ""
    output_pattern: str = ""
    clear_input_after_success: bool = True
    #: Maps channel-set name -> language name used in the prompt ({lang1}).
    lang_map: dict[str, str] = Field(default_factory=lambda: {"ru": "Russian", "en": "English"})
    target_lang: str = "English"
    publish_medium: bool = False
    publish_substack: bool = False


class Settings(BaseModel):
    """Root configuration."""
    data_dir: str = "data"
    telegram: TelegramConfig | None = None
    rss: RssConfig | None = None
    news_search: NewsSearchConfig | None = None
    llm: LlmConfig = Field(default_factory=LlmConfig)
    email: EmailConfig = Field(default_factory=EmailConfig)
    brief: BriefConfig = Field(default_factory=BriefConfig)
    medium: MediumConfig = Field(default_factory=MediumConfig)
    substack: SubstackConfig = Field(default_factory=SubstackConfig)

    #: Directory of the YAML file the settings were loaded from; relative
    #: paths in the config resolve against it.
    base_dir: Path = Field(default_factory=Path.cwd, exclude=True)

    def resolve(self, path: str | Path) -> Path:
        """Resolve *path* against the config file's directory."""
        p = Path(path).expanduser()
        return p if p.is_absolute() else (self.base_dir / p).resolve()

    def data_path(self, path: str | Path) -> Path:
        """Resolve a path against data_dir (itself resolved against base_dir)."""
        p = Path(path).expanduser()
        if p.is_absolute():
            return p
        return self.resolve(self.data_dir) / p


def load_settings(config_path: str | Path | None = None) -> Settings:
    """Load settings from a YAML file with ${ENV} expansion.

    If *config_path* is None, the NEWSFLOW_CONFIG env var is used; when that is
    also unset, an empty default Settings is returned (commands that need a
    section will raise a clear ConfigError).
    """
    if config_path is None:
        config_path = os.environ.get("NEWSFLOW_CONFIG")
    if config_path is None:
        return Settings(base_dir=Path.cwd())

    path = Path(config_path).expanduser()
    if not path.exists():
        raise ConfigError(f"Config file not found: {path}")
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as exc:
        raise ConfigError(f"Invalid YAML in {path}: {exc}") from exc
    if not isinstance(raw, dict):
        raise ConfigError(f"Config root must be a mapping in {path}")

    raw = expand_env(raw, source=str(path))
    try:
        return Settings(**raw, base_dir=path.resolve().parent)
    except ValidationError as exc:
        raise ConfigError(f"Invalid configuration in {path}:\n{exc}") from exc
