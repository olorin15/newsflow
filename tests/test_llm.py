import requests

from newsflow.config import LlmConfig
from newsflow.llm import make_summarizer
from newsflow.llm.ollama import OllamaSummarizer


class FakeResponse:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        pass

    def json(self):
        return self._payload


def test_ollama_payload_and_result(monkeypatch):
    captured = {}

    def fake_post(url, json=None, timeout=None):
        captured["url"] = url
        captured["json"] = json
        captured["timeout"] = timeout
        return FakeResponse({"message": {"content": "<ul><li>summary</li></ul>"}})

    monkeypatch.setattr(requests, "post", fake_post)
    cfg = LlmConfig(backend="ollama", model="gemma4:12b", url="http://localhost:11434/api/chat", timeout=42)
    s = OllamaSummarizer(cfg)
    out = s.summarize("raw text", "Summarize {lang1} in {lang2}: {text}", lang1="Russian", lang2="English")
    assert out == "<ul><li>summary</li></ul>"
    assert captured["url"] == "http://localhost:11434/api/chat"
    assert captured["json"]["model"] == "gemma4:12b"
    assert captured["json"]["stream"] is False
    assert captured["json"]["messages"][0]["content"] == "Summarize Russian in English: raw text"
    assert captured["timeout"] == 42


def test_ollama_connection_error_returns_none(monkeypatch):
    def fake_post(url, json=None, timeout=None):
        raise requests.exceptions.ConnectionError("no ollama")

    monkeypatch.setattr(requests, "post", fake_post)
    s = OllamaSummarizer(LlmConfig())
    assert s.summarize("x", "{text}") is None


def test_make_summarizer_factory():
    assert isinstance(make_summarizer(LlmConfig(backend="ollama")), OllamaSummarizer)
