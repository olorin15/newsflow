"""Publish an HTML file as a Substack note (optional, lazy dependency)."""

from __future__ import annotations

import json
from pathlib import Path

import requests

from ..config import SubstackConfig
from ..errors import ConfigError

NOTE_ENDPOINT = "https://substack.com/api/v1/comment/feed"


def _html_to_note_content(html_text: str) -> list[dict]:
    """Naive mapping: each non-empty line becomes a ProseMirror paragraph."""
    content = []
    for line in html_text.splitlines():
        stripped = line.strip()
        if stripped:
            content.append({
                "type": "paragraph",
                "content": [{"type": "text", "text": stripped}],
            })
        else:
            content.append({"type": "paragraph"})
    return content


def publish_note_from_file(html_file: str | Path, cfg: SubstackConfig) -> dict:
    if not cfg.email or not cfg.password:
        raise ConfigError(
            "Substack publishing needs substack.email (${SUBSTACK_EMAIL}) and "
            "substack.password (${SUBSTACK_PASSWORD}) in the config."
        )
    try:
        from substack import Api
    except ImportError as exc:
        raise ConfigError(
            "Substack publishing requires a client providing the `substack` module "
            "(e.g. pip install python-substack)."
        ) from exc

    api = Api(email=cfg.email, password=cfg.password)
    _ = api.get_user_id()  # authenticate; cookies land in api.session
    session = requests.Session()
    session.cookies.update(api.session.cookies)

    payload = {
        "bodyJson": {
            "type": "doc",
            "attrs": {"schemaVersion": "v1"},
            "content": _html_to_note_content(Path(html_file).read_text(encoding="utf-8")),
        },
        "tabId": cfg.tab_id,
        "replyMinimumRole": "everyone",
    }
    response = session.post(NOTE_ENDPOINT, headers={"Content-Type": "application/json"},
                            data=json.dumps(payload), timeout=30)
    response.raise_for_status()
    return response.json()
