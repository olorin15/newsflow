import smtplib

import pytest

from newsflow.config import EmailConfig
from newsflow.errors import ConfigError
from newsflow.notify.email import send_email_file


def test_smtp_message_shape(tmp_path, monkeypatch):
    sent = {}

    class FakeSMTP:
        def __init__(self, host, port, timeout=None):
            sent["host"] = host
            sent["port"] = port

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def starttls(self):
            sent["tls"] = True

        def login(self, user, password):
            sent["login"] = (user, password)

        def send_message(self, msg):
            sent["msg"] = msg

    monkeypatch.setattr(smtplib, "SMTP", FakeSMTP)
    body = tmp_path / "summary.html"
    body.write_text("<h1>Brief</h1>", encoding="utf-8")
    cfg = EmailConfig(
        backend="smtp", smtp_host="smtp.gmail.com", smtp_port=587,
        username="u", password="p", from_addr="u@gmail.com",
        to=["a@example.com", "b@example.com"],
    )
    send_email_file(cfg, "Daily Briefing", body, intro="intro text")
    assert sent["host"] == "smtp.gmail.com" and sent["port"] == 587
    assert sent.get("tls") is True
    assert sent["login"] == ("u", "p")
    msg = sent["msg"]
    assert msg["Subject"] == "Daily Briefing"
    assert msg["To"] == "a@example.com, b@example.com"
    assert msg["From"] == "u@gmail.com"
    # multipart: plain intro + html alternative
    parts = [p.get_content_type() for p in msg.walk()]
    assert "text/plain" in parts and "text/html" in parts


def test_smtp_requires_credentials(tmp_path):
    body = tmp_path / "b.html"
    body.write_text("x")
    cfg = EmailConfig(backend="smtp", to=["a@example.com"])
    with pytest.raises(ConfigError, match="username"):
        send_email_file(cfg, "s", body)


def test_unknown_backend(tmp_path):
    body = tmp_path / "b.html"
    body.write_text("x")
    cfg = EmailConfig(backend="pigeon", to=["a@example.com"])
    with pytest.raises(ConfigError, match="pigeon"):
        send_email_file(cfg, "s", body)


def test_missing_body_file(tmp_path):
    cfg = EmailConfig(backend="smtp", username="u", password="p", to=["a@example.com"])
    with pytest.raises(ConfigError, match="not found"):
        send_email_file(cfg, "s", tmp_path / "nope.html")
