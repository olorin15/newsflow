"""Summarizer protocol + factory."""

from __future__ import annotations

from typing import Protocol

from ..config import LlmConfig
from ..errors import ConfigError


class Summarizer(Protocol):
    def summarize(self, text: str, prompt_template: str, **fmt) -> str | None:
        """Return the model's response for *text*, or None on failure."""
        ...


def make_summarizer(cfg: LlmConfig) -> Summarizer:
    """Instantiate the backend named in ``cfg.backend``."""
    if cfg.backend == "ollama":
        from .ollama import OllamaSummarizer
        return OllamaSummarizer(cfg)
    if cfg.backend == "mistral":
        from .mistral import MistralSummarizer
        return MistralSummarizer(cfg)
    raise ConfigError(f"Unknown llm.backend {cfg.backend!r} (expected 'ollama' or 'mistral').")
