"""Publish a local file to Medium as a new story (optional)."""

from __future__ import annotations

from pathlib import Path

import requests

from ..config import MediumConfig
from ..errors import ConfigError

MEDIUM_API = "https://api.medium.com/v1/users/{user_id}/posts"


def publish_to_medium(file_path: str | Path, title: str, cfg: MediumConfig) -> dict | None:
    if not cfg.token or not cfg.user_id:
        raise ConfigError(
            "Medium publishing needs medium.token (${MEDIUM_TOKEN}) and medium.user_id "
            "(${MEDIUM_USER_ID}) in the config."
        )
    file_path = Path(file_path)
    try:
        content = file_path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ConfigError(f"Error reading {file_path}: {exc}") from exc

    story = {
        "title": title,
        "contentFormat": cfg.content_format,
        "content": content,
        "publishStatus": cfg.publish_status,
    }
    headers = {
        "Authorization": f"Bearer {cfg.token}",
        "Content-Type": "application/json",
        "Accept": "application/json",
        "Accept-Charset": "utf-8",
    }
    try:
        response = requests.post(
            MEDIUM_API.format(user_id=cfg.user_id), headers=headers, json=story, timeout=30
        )
        response.raise_for_status()
        return response.json()
    except requests.exceptions.RequestException as exc:
        raise ConfigError(f"Error publishing to Medium: {exc}") from exc
