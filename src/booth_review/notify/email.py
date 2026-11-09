"""Send a plain-text email over SMTP (the user's own mailbox, never a data source).

Settings come from the environment or `.env` (locally) and from repository
secrets in the scheduled job. Nothing here logs the password, the addresses or
the message body.
"""

from __future__ import annotations

import smtplib
import ssl
from collections.abc import Callable
from dataclasses import dataclass
from email.message import EmailMessage
from pathlib import Path

from booth_review.config import read_env_value
from booth_review.errors import BoothReviewError

ENV_HOST = "BOOTH_REVIEW_SMTP_HOST"
ENV_PORT = "BOOTH_REVIEW_SMTP_PORT"
ENV_USER = "BOOTH_REVIEW_SMTP_USER"
ENV_PASSWORD = "BOOTH_REVIEW_SMTP_PASSWORD"
ENV_TO = "BOOTH_REVIEW_ALERT_TO"
ENV_FROM = "BOOTH_REVIEW_ALERT_FROM"

REQUIRED_ENV = (ENV_HOST, ENV_USER, ENV_PASSWORD, ENV_TO)

DEFAULT_PORT = 587
_SSL_PORT = 465
_TIMEOUT_S = 30.0


class EmailConfigError(BoothReviewError):
    """Email settings are missing or invalid (the message names variables, never values)."""


class EmailSendError(BoothReviewError):
    """The SMTP server refused the message or could not be reached."""


@dataclass(frozen=True)
class EmailSettings:
    host: str
    port: int
    user: str
    password: str
    to: tuple[str, ...]
    sender: str

    def __repr__(self) -> str:  # never print the password or addresses
        return f"EmailSettings(host={self.host!r}, port={self.port})"

    @classmethod
    def from_env(cls, env_file: Path = Path(".env")) -> EmailSettings:
        values = {name: read_env_value(name, env_file) for name in (*REQUIRED_ENV, ENV_PORT)}
        missing = [name for name in REQUIRED_ENV if not values[name]]
        if missing:
            raise EmailConfigError(f"email settings not set: {', '.join(missing)}")
        raw_port = values[ENV_PORT]
        try:
            port = int(raw_port) if raw_port else DEFAULT_PORT
        except ValueError as exc:
            raise EmailConfigError(f"{ENV_PORT} is not a port number") from exc
        to = tuple(addr.strip() for addr in str(values[ENV_TO]).split(",") if addr.strip())
        if not to:
            raise EmailConfigError(f"{ENV_TO} names no address")
        user = str(values[ENV_USER])
        return cls(
            host=str(values[ENV_HOST]),
            port=port,
            user=user,
            password=str(values[ENV_PASSWORD]),
            to=to,
            sender=read_env_value(ENV_FROM, env_file) or user,
        )


SmtpFactory = Callable[[EmailSettings], smtplib.SMTP]


def _connect(settings: EmailSettings) -> smtplib.SMTP:
    context = ssl.create_default_context()
    if settings.port == _SSL_PORT:
        return smtplib.SMTP_SSL(settings.host, settings.port, timeout=_TIMEOUT_S, context=context)
    smtp = smtplib.SMTP(settings.host, settings.port, timeout=_TIMEOUT_S)
    smtp.starttls(context=context)
    return smtp


def send_email(
    settings: EmailSettings, subject: str, body: str, *, connect: SmtpFactory = _connect
) -> None:
    """Send one plain-text message to every `settings.to` address."""
    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = settings.sender
    message["To"] = ", ".join(settings.to)
    message.set_content(body)
    try:
        with connect(settings) as smtp:
            smtp.login(settings.user, settings.password)
            refused = smtp.send_message(message)
    except (OSError, smtplib.SMTPException) as exc:
        raise EmailSendError(f"email not sent ({type(exc).__name__})") from exc
    if refused:
        # Some recipients were accepted; the caller still treats the send as failed, so
        # the items are retried (and the accepted recipients may get them twice).
        raise EmailSendError(f"email refused for {len(refused)} of {len(settings.to)} recipients")
