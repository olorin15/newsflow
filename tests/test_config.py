import pytest

from newsflow.config import Settings, expand_env, load_settings
from newsflow.errors import ConfigError


def test_expand_env_simple(monkeypatch):
    monkeypatch.setenv("MY_VAR", "hello")
    assert expand_env("say ${MY_VAR}!") == "say hello!"


def test_expand_env_default(monkeypatch):
    monkeypatch.delenv("MISSING_VAR", raising=False)
    assert expand_env("${MISSING_VAR:-fallback}") == "fallback"


def test_expand_env_missing_raises(monkeypatch):
    monkeypatch.delenv("NOPE_VAR", raising=False)
    with pytest.raises(ConfigError, match="NOPE_VAR"):
        expand_env("${NOPE_VAR}")


def test_expand_env_nested():
    import os
    os.environ["NF_TEST_KEY"] = "k"
    try:
        data = {"a": {"b": ["${NF_TEST_KEY}", 1]}, "c": 2}
        out = expand_env(data)
        assert out == {"a": {"b": ["k", 1]}, "c": 2}
    finally:
        del os.environ["NF_TEST_KEY"]


def test_load_settings_from_yaml(tmp_path, monkeypatch):
    monkeypatch.setenv("NF_API_KEY", "secret123")
    cfg_file = tmp_path / "cfg.yaml"
    cfg_file.write_text(
        "data_dir: mydata\n"
        "llm:\n"
        "  backend: ollama\n"
        "  model: test-model\n"
        "email:\n"
        "  to: [a@example.com]\n"
        "  password: ${NF_API_KEY}\n"
        "custom_free_form: ${NF_API_KEY}\n",
        encoding="utf-8",
    )
    settings = load_settings(cfg_file)
    assert settings.llm.model == "test-model"
    assert settings.email.password == "secret123"
    assert settings.email.to == ["a@example.com"]
    assert settings.base_dir == tmp_path
    # relative paths resolve against the config dir
    assert settings.resolve("x.txt") == (tmp_path / "x.txt").resolve()
    assert settings.data_path("y.txt") == (tmp_path / "mydata" / "y.txt").resolve()


def test_load_settings_missing_file(tmp_path):
    with pytest.raises(ConfigError, match="not found"):
        load_settings(tmp_path / "nope.yaml")


def test_settings_defaults():
    s = Settings()
    assert s.llm.backend == "ollama"
    assert s.brief.clear_input_after_success is True


def test_email_recipients_comma_split():
    from newsflow.config import EmailConfig
    cfg = EmailConfig(to="a@x.com, b@y.com ,c@z.com")
    assert cfg.to == ["a@x.com", "b@y.com", "c@z.com"]
    cfg2 = EmailConfig(to=["a@x.com", "b@y.com,c@z.com"])
    assert cfg2.to == ["a@x.com", "b@y.com", "c@z.com"]
