from pathlib import Path

import pytest

from newsflow.config import BriefConfig, EmailConfig, LlmConfig, Settings, TelegramConfig
from newsflow.errors import ConfigError
from newsflow.pipeline import resolve_paths, run_brief


class FakeSummarizer:
    def __init__(self, result="<p>fake summary</p>"):
        self.result = result
        self.calls = []

    def summarize(self, text, prompt_template, **fmt):
        self.calls.append((text, prompt_template, fmt))
        return self.result


@pytest.fixture
def settings(tmp_path):
    return Settings(
        data_dir="data",
        base_dir=tmp_path,
        telegram=TelegramConfig(
            api_id="1", api_hash="h", phone="+1",
            channel_sets={"ru": ["@x"]},
            output_pattern="telegram/telega_{channels}.txt",
        ),
        llm=LlmConfig(backend="ollama", model="m"),
        brief=BriefConfig(source="telegram", channels="ru"),
        email=EmailConfig(enabled=True, backend="smtp", username="u", password="p",
                          to=["a@example.com"], subject="{lang} Briefing"),
    )


def test_resolve_paths_telegram(settings, tmp_path):
    inp, out = resolve_paths(settings, "telegram", "ru", None, None)
    assert inp == (tmp_path / "data" / "telegram" / "telega_ru.txt").resolve()
    assert out == (tmp_path / "data" / "telegram" / "summary_ru.txt").resolve()


def test_resolve_paths_rss_date_pattern(settings):
    inp, out = resolve_paths(settings, "rss", "ru", None, None)
    assert inp.name.startswith("feed-items-") and inp.name.endswith(".txt")
    assert out.name == "summary_rss.txt"


def test_run_brief_happy_path(settings, tmp_path, monkeypatch):
    inp = tmp_path / "data" / "telegram" / "telega_ru.txt"
    inp.parent.mkdir(parents=True)
    inp.write_text("ChannelA: hello news", encoding="utf-8")

    fake = FakeSummarizer()
    monkeypatch.setattr("newsflow.pipeline.make_summarizer", lambda cfg: fake)
    sent = []
    monkeypatch.setattr(
        "newsflow.pipeline.send_email_file",
        lambda cfg, subject, body_file, intro="": sent.append((subject, Path(body_file).read_text())),
    )

    result = run_brief(settings, source="telegram", channels="ru")
    assert result.summary == "<p>fake summary</p>"
    assert result.output_file.read_text(encoding="utf-8") == "<p>fake summary</p>"
    # input cleared after success
    assert result.input_file.read_text(encoding="utf-8") == ""
    # email sent with formatted subject
    assert sent == [("Russian Briefing", "<p>fake summary</p>")]
    # prompt got lang placeholders
    assert fake.calls[0][2]["lang1"] == "Russian"
    assert fake.calls[0][2]["lang2"] == "English"


def test_run_brief_no_email_no_clear(settings, tmp_path, monkeypatch):
    inp = tmp_path / "data" / "telegram" / "telega_ru.txt"
    inp.parent.mkdir(parents=True)
    inp.write_text("some text", encoding="utf-8")
    monkeypatch.setattr("newsflow.pipeline.make_summarizer", lambda cfg: FakeSummarizer())
    monkeypatch.setattr(
        "newsflow.pipeline.send_email_file",
        lambda *a, **k: pytest.fail("should not email"),
    )
    result = run_brief(settings, source="telegram", channels="ru", no_email=True, no_clear=True)
    assert result.emailed is False and result.cleared is False
    assert inp.read_text(encoding="utf-8") == "some text"


def test_run_brief_empty_input_raises(settings, tmp_path, monkeypatch):
    inp = tmp_path / "data" / "telegram" / "telega_ru.txt"
    inp.parent.mkdir(parents=True)
    inp.write_text("   ", encoding="utf-8")
    with pytest.raises(ConfigError, match="empty"):
        run_brief(settings, source="telegram", channels="ru")


def test_run_brief_llm_failure_raises_and_keeps_input(settings, tmp_path, monkeypatch):
    inp = tmp_path / "data" / "telegram" / "telega_ru.txt"
    inp.parent.mkdir(parents=True)
    inp.write_text("text", encoding="utf-8")
    monkeypatch.setattr("newsflow.pipeline.make_summarizer", lambda cfg: FakeSummarizer(result=None))
    with pytest.raises(ConfigError, match="summary"):
        run_brief(settings, source="telegram", channels="ru")
    assert inp.read_text(encoding="utf-8") == "text"


def test_run_brief_file_source(settings, tmp_path, monkeypatch):
    src = tmp_path / "in.txt"
    src.write_text("headlines here", encoding="utf-8")
    monkeypatch.setattr("newsflow.pipeline.make_summarizer", lambda cfg: FakeSummarizer())
    monkeypatch.setattr("newsflow.pipeline.send_email_file", lambda *a, **k: None)
    result = run_brief(settings, source="file", input_file=str(src), output_file=str(tmp_path / "out.txt"),
                       no_email=True, no_clear=True)
    assert Path(tmp_path / "out.txt").read_text(encoding="utf-8") == "<p>fake summary</p>"
