"""
app/notifications/email_sender.py's SMTP connection: port 465 uses
implicit TLS, anything else STARTTLS - and the server certificate is
verified on both, so the App Password is never sent to an impostor.
"""

import smtplib
import ssl

import pytest

from app.notifications import email_sender
from app.notifications.email_sender import open_smtp_connection


class _FakeSMTP:
    instances: list["_FakeSMTP"] = []

    def __init__(self, host, port, timeout=None, context=None):
        self.host, self.port, self.context = host, port, context
        self.starttls_context = None
        self.closed = False
        self.logged_in_as = None
        self.sent = []
        _FakeSMTP.instances.append(self)

    def starttls(self, context=None):
        self.starttls_context = context

    def login(self, username, password):
        self.logged_in_as = username

    def send_message(self, message):
        self.sent.append(message)

    def close(self):
        self.closed = True

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()


@pytest.fixture
def fake_smtp(monkeypatch):
    _FakeSMTP.instances = []
    ssl_calls = []

    class _FakeSMTPSSL(_FakeSMTP):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            ssl_calls.append(self)

    monkeypatch.setattr(smtplib, "SMTP", _FakeSMTP)
    monkeypatch.setattr(smtplib, "SMTP_SSL", _FakeSMTPSSL)
    return ssl_calls


def _verifies_certificates(context) -> bool:
    return (
        isinstance(context, ssl.SSLContext)
        and context.verify_mode == ssl.CERT_REQUIRED
        and context.check_hostname
    )


def test_port_587_upgrades_with_verified_starttls(fake_smtp):
    server = open_smtp_connection("smtp.gmail.com", 587, use_tls=True)

    assert fake_smtp == []
    assert (server.host, server.port) == ("smtp.gmail.com", 587)
    assert _verifies_certificates(server.starttls_context)


def test_port_465_uses_implicit_tls_with_verified_certificate(fake_smtp):
    server = open_smtp_connection("smtp.gmail.com", 465, use_tls=True)

    assert fake_smtp == [server]
    assert server.starttls_context is None
    assert _verifies_certificates(server.context)


def test_failed_starttls_closes_the_connection(monkeypatch, fake_smtp):
    def _cut_off(self, context=None):
        raise smtplib.SMTPServerDisconnected("Connection unexpectedly closed")

    monkeypatch.setattr(_FakeSMTP, "starttls", _cut_off)

    with pytest.raises(smtplib.SMTPServerDisconnected):
        open_smtp_connection("smtp.gmail.com", 587, use_tls=True)

    assert _FakeSMTP.instances[-1].closed


@pytest.mark.parametrize("port", [587, 465])
def test_sender_logs_in_and_sends_on_either_port(monkeypatch, fake_smtp, port):
    class _Settings:
        smtp_host = "smtp.gmail.com"
        smtp_port = port
        smtp_username = "firm@example.com"
        smtp_password = "abcdefghijklmnop"
        smtp_from_email = ""
        smtp_use_tls = True

    monkeypatch.setattr(email_sender, "get_settings", lambda: _Settings)

    email_sender.SMTPEmailSender().send("person@example.com", "Subject", "Body")

    server = _FakeSMTP.instances[-1]
    assert server.port == port
    assert server.logged_in_as == "firm@example.com"
    assert server.sent[0]["To"] == "person@example.com"
    assert server.sent[0]["From"] == "firm@example.com"
    assert server.closed
