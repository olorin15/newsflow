"""Small shared helpers: atomic writes, JSON state, HTML-to-text."""

from __future__ import annotations

import html
import json
import os
import re
import tempfile
from pathlib import Path


def atomic_write_text(path: Path | str, content: str) -> Path:
    """Write text to *path* atomically (temp file + rename)."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=f".{path.name}-", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
    return path


def load_json_state(path: Path | str, default: dict) -> dict:
    """Load a JSON state file, returning *default* when it does not exist."""
    path = Path(path)
    if not path.exists():
        return default
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def save_json_state(path: Path | str, state: dict) -> None:
    """Save state as pretty JSON, atomically."""
    atomic_write_text(Path(path), json.dumps(state, indent=2, ensure_ascii=False, sort_keys=True) + "\n")


def html_to_text(value: object) -> str:
    """Convert an HTML-ish feed field to readable, normalized plain text."""
    if value is None:
        return ""
    value = html.unescape(str(value))
    value = re.sub(r"(?is)<(script|style).*?>.*?</\1>", "", value)
    value = re.sub(r"(?i)<br\s*/?>", "\n", value)
    value = re.sub(r"(?i)</(p|div|li|h[1-6]|blockquote|tr)\s*>", "\n", value)
    value = re.sub(r"(?s)<[^>]+>", "", value)
    value = re.sub(r"[ \t]+", " ", value)
    value = re.sub(r"\n\s*\n\s*", "\n\n", value)
    return value.strip()
