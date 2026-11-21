"""Email delivery.

Three selectable backends (``email.backend``):
- ``smtp``      — smtplib with TLS/SSL, proper multipart text+HTML (recommended)
- ``sendemail`` — the sendemail CLI (macOS Homebrew), as used by the original scripts
- ``sendmail``  — the local sendmail binary

The body file is treated as HTML; ``intro`` (if set) becomes the plain-text part.
"""

from __future__ import annotations

import logging
import smtplib
import subprocess
from email.message import EmailMessage
from pathlib import Path

from ..config import EmailConfig
from ..errors import ConfigError

log = logging.getLogger(__name__)


def _check(cfg: EmailConfig) -> None:
    if not cfg.to:
        raise ConfigError("email.to is empty — configure at least one recipient.")
    if cfg.backend == "smtp" and (not cfg.username or not cfg.password):
        raise ConfigError(
            "email.backend is 'smtp' but email.username/email.password are empty. "
            "Set them to ${SMTP_USERNAME}/${SMTP_PASSWORD} in the config."
        )


def send_smtp(cfg: EmailConfig, subject: str, body_file: Path, intro: str = "") -> None:
    _check(cfg)
    body_html = body_file.read_text(encoding="utf-8")
    message = EmailMessage()
    message["From"] = cfg.from_addr or cfg.username
    message["To"] = ", ".join(cfg.to)
    message["Subject"] = subject
    message.set_content(intro or "See the HTML version of this message.")
    message.add_alternative(body_html, subtype="html")

    if cfg.smtp_ssl:
        smtp_cls = smtplib.SMTP_SSL
    else:
        smtp_cls = smtplib.SMTP
    with smtp_cls(cfg.smtp_host, cfg.smtp_port, timeout=30) as smtp:
        if not cfg.smtp_ssl and cfg.starttls:
            smtp.starttls()
        smtp.login(cfg.username, cfg.password)
        smtp.send_message(message)
    log.info("Email sent to %s via SMTP", cfg.to)


def send_via_sendemail(cfg: EmailConfig, subject: str, body_file: Path) -> None:
    _check(cfg)
    command = [
        cfg.sendemail_path,
        "-f", cfg.from_addr or cfg.username,
        "-t", ",".join(cfg.to),
        "-u", subject,
        "-s", f"{cfg.smtp_host}:{cfg.smtp_port}",
        "-xu", cfg.username,
        "-xp", cfg.password,
        "-o", f"message-file={body_file}",
        "-o", "tls=auto",
        "-o", "message-content-type=html",
        "-o", "message-charset=UTF-8",
    ]
    subprocess.run(command, check=True)
    log.info("Email sent to %s via sendemail", cfg.to)


def send_via_sendmail(cfg: EmailConfig, subject: str, body_file: Path, intro: str = "") -> None:
    _check(cfg)
    body = body_file.read_text(encoding="utf-8")
    content = (
        f"To: {', '.join(cfg.to)}\n"
        f"From: {cfg.from_addr or cfg.username}\n"
        f"Subject: {subject}\n"
        f"Content-Type: text/html; charset=UTF-8\n"
        f"\n"
        f"{intro}\n\n{body}\n"
    )
    process = subprocess.Popen([cfg.sendmail_path, "-t"], stdin=subprocess.PIPE)
    process.communicate(input=content.encode("utf-8"))
    if process.returncode != 0:
        raise ConfigError(f"sendmail exited with code {process.returncode}")
    log.info("Email sent to %s via sendmail", cfg.to)


def send_email_file(cfg: EmailConfig, subject: str, body_file: str | Path, intro: str = "") -> None:
    """Send *body_file* (HTML) with *subject* using the configured backend."""
    body_file = Path(body_file)
    if not body_file.exists():
        raise ConfigError(f"Body file not found: {body_file}")
    if cfg.backend == "smtp":
        send_smtp(cfg, subject, body_file, intro)
    elif cfg.backend == "sendemail":
        send_via_sendemail(cfg, subject, body_file)
    elif cfg.backend == "sendmail":
        send_via_sendmail(cfg, subject, body_file, intro)
    else:
        raise ConfigError(
            f"Unknown email.backend {cfg.backend!r} (expected 'smtp', 'sendemail' or 'sendmail')."
        )
