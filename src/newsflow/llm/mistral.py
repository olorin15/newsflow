"""Mistral cloud backend with model fallback chain."""

from __future__ import annotations

import logging

from ..config import LlmConfig
from ..errors import ConfigError

log = logging.getLogger(__name__)


class MistralSummarizer:
    def __init__(self, cfg: LlmConfig):
        if not cfg.mistral_api_key:
            raise ConfigError(
                "llm.mistral_api_key is empty — set it to ${MISTRAL_API_KEY} in the config."
            )
        try:
            from mistralai import Mistral
        except ImportError as exc:
            raise ConfigError(
                "Mistral backend requires: pip install 'newsflow[mistral]'"
            ) from exc
        self.cfg = cfg
        self.client = Mistral(api_key=cfg.mistral_api_key)

    def _complete(self, model: str, prompt: str) -> str | None:
        try:
            response = self.client.chat.complete(
                model=model,
                messages=[{"role": "user", "content": prompt}],
            )
            return response.choices[0].message.content
        except Exception as exc:
            log.error("Mistral API request failed (model=%s): %s", model, exc)
            return None

    def summarize(self, text: str, prompt_template: str, **fmt) -> str | None:
        prompt = prompt_template.format(text=text, **fmt)
        for model in [self.cfg.model, *self.cfg.mistral_fallback_models]:
            result = self._complete(model, prompt)
            if result:
                return result
        return None
