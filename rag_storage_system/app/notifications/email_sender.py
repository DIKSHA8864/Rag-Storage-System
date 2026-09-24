"""
Outbound email - verification codes and invites for end-user accounts
(app/security/end_user_accounts.py). Same swappable-provider pattern as
app/billing/provider.py: callers only ever use get_email_sender(),
selected by EMAIL_PROVIDER (config/settings.py).
"""

import logging
import smtplib
from abc import ABC, abstractmethod
from email.message import EmailMessage

from config.settings import get_settings

logger = logging.getLogger(__name__)


class EmailSender(ABC):

    @abstractmethod
    def send(self, to_email: str, subject: str, body: str) -> None:
        raise NotImplementedError


class ConsoleEmailSender(EmailSender):
    """
    Local-testing only: prints the message to the API server's own
    terminal instead of sending it, so signup/password-reset can be
    tried with no mail server. get_email_sender() refuses it when
    ENVIRONMENT=production, since it would put live login codes in logs.
    """

    def send(self, to_email: str, subject: str, body: str) -> None:
        banner = "=" * 60
        print(f"\n{banner}\n[EMAIL - console mode, not actually sent]\nTo: {to_email}\nSubject: {subject}\n\n{body}\n{banner}\n", flush=True)


class SMTPEmailSender(EmailSender):
    """A real mail server over SMTP (STARTTLS by default) - e.g. Gmail with an App Password."""

    def __init__(self):
        settings = get_settings()

        if not settings.smtp_username or not settings.smtp_password:
            raise RuntimeError("EMAIL_PROVIDER=smtp requires SMTP_USERNAME and SMTP_PASSWORD to be set.")

        self._host = settings.smtp_host
        self._port = settings.smtp_port
        self._username = settings.smtp_username
        self._password = settings.smtp_password
        self._from_email = settings.smtp_from_email or settings.smtp_username
        self._use_tls = settings.smtp_use_tls

    def send(self, to_email: str, subject: str, body: str) -> None:
        message = EmailMessage()
        message["From"] = self._from_email
        message["To"] = to_email
        message["Subject"] = subject
        message.set_content(body)

        with smtplib.SMTP(self._host, self._port, timeout=20) as server:
            if self._use_tls:
                server.starttls()
            server.login(self._username, self._password)
            server.send_message(message)


def get_email_sender() -> EmailSender:
    settings = get_settings()

    if settings.email_provider == "console":
        if settings.environment == "production":
            raise RuntimeError(
                "EMAIL_PROVIDER=console is not allowed when ENVIRONMENT=production - "
                "it would print live login codes to the server logs. Configure EMAIL_PROVIDER=smtp."
            )
        return ConsoleEmailSender()

    if settings.email_provider == "smtp":
        return SMTPEmailSender()

    raise RuntimeError(f"Unknown EMAIL_PROVIDER: {settings.email_provider!r}")
