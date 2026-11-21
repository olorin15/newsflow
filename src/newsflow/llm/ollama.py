"""Local Ollama backend (http://localhost:11434 by default)."""

from __future__ import annotations

import logging

import requests

from ..config import LlmConfig

log = logging.getLogger(__name__)


class OllamaSummarizer:
    """Send text to a local Ollama model's /api/chat endpoint."""

    def __init__(self, cfg: LlmConfig):
        self.cfg = cfg

    def summarize(self, text: str, prompt_template: str, **fmt) -> str | None:
        prompt = prompt_template.format(text=text, **fmt)
        payload = {
            "model": self.cfg.model,
            "messages": [{"role": "user", "content": prompt}],
            "stream": False,
        }
        try:
            response = requests.post(self.cfg.url, json=payload, timeout=self.cfg.timeout)
            response.raise_for_status()
            return response.json()["message"]["content"]
        except requests.exceptions.ConnectionError:
            log.error("Could not connect to Ollama at %s. Is Ollama running?", self.cfg.url)
            return None
        except Exception as exc:
            log.error("Ollama request failed: %s", exc)
            return None
