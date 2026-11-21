# newsflow

One configurable project for your personal news flows: **collect** news from
Telegram channels, RSS/OPML feeds (e.g. a NetNewsWire export) or Google News
search, **summarize** the collected text with a local [Ollama](https://ollama.com)
model (or Mistral cloud API), and **deliver** the briefing by email, Medium or
Substack notes.

Everything that should not be hard-coded — channel lists, models, prompts, file
paths, SMTP settings, recipients, subjects — lives in a YAML config file.
Secrets are referenced as `${ENV_VARS}` and loaded from a git-ignored `.env`.

## Layout

```
newsflow/
├── pyproject.toml            # package + `newsflow` console command
├── configs/                  # one YAML per flow (telegram_ru, telegram_en, rss, ...)
│   └── subscriptions.opml    # example OPML feed list (replace with your own export)
│   └── telegram.yaml         # example telegram channels (replace with your own export)
├── src/newsflow/
│   ├── cli.py                # argparse entry point (subcommands below)
│   ├── config.py             # YAML + ${ENV} loading, path resolution, validation
│   ├── pipeline.py           # the `brief` pipeline: read -> summarize -> deliver -> clear
│   ├── sources/              # telegram.py, telegram_rss.py, opml.py, news_search.py, feed_alert.py
│   ├── llm/                  # ollama.py, mistral.py
│   └── notify/               # email.py (smtp/sendemail/sendmail), medium.py, substack.py
└── tests/
```

## Install

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -e .            # core: requests, pyyaml, pydantic, feedparser
pip install -e '.[telegram]'  # + telethon/fastapi/uvicorn/aiosqlite/feedgen
pip install -e '.[mistral]'   # + mistralai (only for llm.backend: mistral)
```

## Configure

```bash
cp .env.example .env        # fill in your secrets
$EDITOR .env
```

Pick a config from `configs/` and adjust it. Every `${VAR}` is expanded from the
environment; `${VAR:-default}` allows a fallback. Relative paths resolve against
the config file's directory, and `data_dir` is where collected files, state and
summaries go. The config file path can also be set once via `NEWSFLOW_CONFIG`.

## Commands

```bash
# 1. Telegram live monitor (long-running) — appends new messages to a text file
newsflow -c configs/telegram.yaml collect-telegram --set en

# 2. Telegram channels as RSS feeds (FastAPI server, SQLite-backed)
newsflow -c configs/telegram.yaml serve-telegram-rss --host 127.0.0.1 --port 8000
#    feeds at http://127.0.0.1:8000/feeds/<slug>.rss, health at /healthz

# 3. Archive new entries from all OPML feeds into daily text files (cron-friendly)
newsflow -c configs/rss.yaml collect-opml

# 4. Google News headlines via SerpApi into a dated text file
newsflow -c configs/headlines.yaml collect-serp

# 5. Email new entries of a single Atom/RSS feed
newsflow -c configs/feed_alert.yaml alert-feed --feed-url "https://example.com/feed"

# 6. Summarize a collected file and deliver it (the "brief")
newsflow -c configs/telegram.yaml brief --source telegram --channels en
newsflow -c configs/rss.yaml brief --source rss
newsflow -c configs/headlines.yaml brief --source file --input ../data/headlines/2026-01-01.txt
```

Useful `brief` flags: `--model` (override llm.model), `--input`/`--output`
(explicit files), `--no-email`, `--no-clear` (keep the input file),
`--publish` (also publish via Medium/Substack if configured).

### Structure of outputs

When `collect` commands are run, the output will look something like this:

```
data
├── rss_archive
│   └── feed-items-2026-11-19.txt
├── state
│   └── rss_archiver.json
└── telegram
    ├── telega_en.txt
    └── telega_ru.txt
```

### Typical cron setup

```cron
*/30 * * * *  newsflow -c /path/to/newsflow/configs/rss.yaml collect-opml
0 8 * * *     newsflow -c /path/to/newsflow/configs/rss.yaml brief --source rss
0 9 * * *     newsflow -c /path/to/newsflow/configs/telegram_ru.yaml brief --source telegram --channels ru
```

## Configuration reference (YAML)

| Section                   | Key                                                                   | Meaning                                                                                                                                       |
| ------------------------- | --------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------- |
| `data_dir`              |                                                                       | Base directory for collected files, state and summaries                                                                                       |
| `telegram`              | `api_id` / `api_hash` / `phone`                                 | Telegram credentials (`${TELEGRAM_API_ID}` etc.)                                                                                            |
|                           | `channel_sets`                                                      | name -> list of `@channel`s for the monitor                                                                                                 |
|                           | `output_pattern`                                                    | where the monitor appends messages (`{channels}` placeholder)                                                                               |
|                           | `watched_channels`                                                  | slug -> `@channel` for the RSS server                                                                                                       |
|                           | `rss_db_path`, `server_host`, `server_port`                     | RSS server settings                                                                                                                           |
| `rss`                   | `opml_path`, `archive_dir`, `state_path`                        | OPML archiver paths                                                                                                                           |
|                           | `archive_initial`, `max_seen_per_feed`, `user_agent`            | archiver behavior                                                                                                                             |
| `news_search`           | `serp_api_key`, `query`, `source_map`, `output_pattern`       | SerpApi headlines                                                                                                                             |
| `llm`                   | `backend`                                                           | `ollama` or `mistral`                                                                                                                     |
|                           | `model`, `url`, `timeout`, `prompt`                           | model + prompt template (`{text}`, `{lang1}`, `{lang2}`)                                                                                |
| `brief`                 | `source`, `channels`, `input_pattern`, `output_pattern`       | pipeline files (`{date}`, `{channels}`)                                                                                                   |
|                           | `clear_input_after_success`, `lang_map`, `target_lang`          | pipeline behavior                                                                                                                             |
| `email`                 | `backend`                                                           | `smtp` (recommended), `sendemail`, `sendmail`                                                                                           |
|                           | `smtp_host`, `smtp_port`, `smtp_ssl`, `starttls`, credentials | SMTP settings                                                                                                                                 |
|                           | `to`, `subject`, `intro`                                        | recipients and message (`{lang}`, `{channels}`, `{date}`); `to` accepts a list or comma-separated string, typically `- ${EMAIL_TO}` |
| `medium` / `substack` | tokens/credentials                                                    | optional publishers for `brief --publish`                                                                                                   |

## Troubleshooting

**`ValueError: too many values to unpack (expected 5)` when starting a Telegram command**
— the Telethon session file (default: `data/telegram/telega_<set>.session`,
`data/state/telegram_rss.session`) was written by a *different Telethon version*
than the one running newsflow. Telethon can upgrade older session files itself,
but not newer ones. Fix either way:

```bash
pip install -U telethon        # match the version that wrote the session (recommended)
# or: delete the .session file and log in again (SMS code) on first start
```

Run newsflow from **one consistent environment** (ideally the project venv) so the
session format stays stable. Session files are never committed (`*.session` in
`.gitignore`).

**`ConfigError: Environment variable ... is not set`** — copy `.env.example` to
`.env` and fill it in; the config references secrets as `${VAR}`.

## Security

- **Never commit `.env`**, `*.session`, `*.sqlite3` or anything under `data/` —
  all are in `.gitignore`.
- This project itself contains no secrets — configs reference env vars only.

## Development

```bash
pip install -e . pytest
pytest
```
