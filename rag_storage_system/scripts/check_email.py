"""
Send one test email with the current .env email settings and explain
exactly what went wrong if it fails.

The sign-up / password-reset pages deliberately give the same answer
whether or not an email was actually sent (so they can't be used to
discover which emails have accounts) - which also means a broken email
setup is invisible there. Run this to check it directly.

Usage:
    python scripts/check_email.py <send-a-test-to@example.com>
"""

import os
import smtplib
import socket
import ssl
import sys
from email.message import EmailMessage
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from app.notifications.email_sender import SMTP_SSL_PORT, open_smtp_connection  # noqa: E402
from config.settings import get_settings  # noqa: E402


EMAIL_KEYS = ("EMAIL_PROVIDER", "SMTP_HOST", "SMTP_PORT", "SMTP_USERNAME", "SMTP_PASSWORD", "SMTP_FROM_EMAIL", "SMTP_USE_TLS")


def find_hidden_overrides(env_path: Path) -> list[str]:
    """
    Problems that make the app use a different value than the one you
    just typed into .env - invisible from just looking at the top of it.
    """

    problems = []

    if not env_path.exists():
        return [f"No .env file at {env_path} - run the API and this script from the project folder."]

    seen: dict[str, list[int]] = {}
    for number, raw in enumerate(env_path.read_text(encoding="utf-8-sig").splitlines(), start=1):
        line = raw.strip()
        if line.startswith("export "):
            line = line[len("export "):]
        if not line or line.startswith("#") or "=" not in line:
            continue
        key = line.split("=", 1)[0].strip().upper()
        if key in EMAIL_KEYS:
            seen.setdefault(key, []).append(number)

    for key, lines in seen.items():
        if len(lines) > 1:
            problems.append(
                f"{key} appears {len(lines)} times in .env (lines {', '.join(map(str, lines))}) - "
                f"the LAST one (line {lines[-1]}) wins. Delete the extra lines."
            )

    for key in EMAIL_KEYS:
        if key in os.environ or key.lower() in os.environ:
            problems.append(
                f"{key} is also set as a Windows/terminal environment variable, which OVERRIDES .env. "
                f"Remove it (PowerShell: Remove-Item Env:{key}) or open a new terminal."
            )

    return problems


def check_password_shape(password: str) -> list[str]:
    problems = []
    if any(ch in password for ch in "<>\"'"):
        problems.append("SMTP_PASSWORD contains < > or quotes - paste only the 16 letters, nothing around them.")
    if " " in password:
        problems.append("SMTP_PASSWORD contains spaces - remove them (Gmail shows the App Password in groups of 4).")
    compact = password.replace(" ", "")
    if len(compact) != 16 or not compact.isalpha():
        problems.append(
            f"SMTP_PASSWORD is {len(compact)} characters - a Gmail App Password is exactly 16 letters. "
            f"This looks like the normal Gmail password or a copy/paste mistake."
        )
    return problems


class StepFailure:
    def __init__(self, step: str, port: int, error: Exception):
        self.step = step
        self.port = port
        self.error = error


def try_send(settings, port: int, to_email: str) -> "StepFailure | None":
    """
    The same connection the app makes (app/notifications/email_sender.py),
    one step at a time, printing each - so a failure says WHERE it broke.
    """

    host = settings.smtp_host
    print(f"Port {port}:")

    step = "reach"
    try:
        socket.create_connection((host, port), timeout=15).close()
        print(f"  [ok] reach {host}:{port}")

        step = "secure"
        with open_smtp_connection(host, port, settings.smtp_use_tls, timeout=20) as server:
            print("  [ok] encrypted connection (certificate verified)")

            step = "login"
            server.login(settings.smtp_username, settings.smtp_password)
            print(f"  [ok] login as {settings.smtp_username}")

            step = "send"
            message = EmailMessage()
            message["From"] = settings.smtp_from_email or settings.smtp_username
            message["To"] = to_email
            message["Subject"] = "AshiLegal test email"
            message.set_content("This is a test email from AshiLegal. If you can read it, email delivery is working.")
            server.send_message(message)
            print(f"  [ok] message accepted for {to_email}")
    except Exception as exc:
        print(f"  [FAILED] {step}: {exc!r}")
        return StepFailure(step, port, exc)

    return None


def explain(failure: StepFailure) -> None:
    step, error = failure.step, failure.error
    print()

    if step == "reach":
        print("The computer can't even reach Gmail's mail server on this port:")
        print("  - a firewall, antivirus, VPN, or office/college network is blocking outgoing mail.")
        print("  - Try a mobile hotspot to confirm, or ask IT to allow it.")
    elif step == "secure" and isinstance(error, ssl.SSLCertVerificationError):
        print("Something between this computer and Gmail replaced Gmail's security certificate.")
        print("  - That is almost always antivirus 'Mail Shield' / 'Email protection' scanning outgoing mail")
        print("    (Avast, AVG, Kaspersky, ESET, Quick Heal...). Turn that feature off, or add an exception")
        print("    for smtp.gmail.com, then run this again.")
    elif step == "secure":
        print("Gmail was reached, but the connection was cut while setting up encryption.")
        print("  - Usually antivirus 'Mail Shield' / 'Email protection', a VPN, or a network filter.")
        print("  - Turn off the antivirus email-scanning feature (or disconnect the VPN) and run this again.")
    elif step == "login" and isinstance(error, smtplib.SMTPAuthenticationError):
        print("Gmail rejected the username/password:")
        print("  - Use a Gmail App Password (16 letters, no spaces), not the normal Gmail password.")
        print("  - 2-Step Verification must be ON for SMTP_USERNAME's Google account.")
        print("  - The App Password must be created while signed in as SMTP_USERNAME.")
    elif step == "login":
        print("Gmail closed the connection during login instead of answering yes/no.")
        print("  - After several failed logins Gmail temporarily blocks new ones: wait 30-60 minutes.")
        print("  - Sign in to SMTP_USERNAME's Gmail in a browser and check for a 'blocked sign-in'")
        print("    security alert (https://myaccount.google.com/notifications) - confirm it was you.")
        print("  - Antivirus email scanning can also do this - try with it turned off.")
    else:
        print("Logged in, but Gmail refused this message:")
        print(f"  - {error!r}")
        print("  - Check the recipient address, and that SMTP_FROM_EMAIL is the same as SMTP_USERNAME.")


def main() -> int:
    if len(sys.argv) != 2:
        print("Usage: python scripts/check_email.py <send-a-test-to@example.com>")
        return 2

    to_email = sys.argv[1]
    settings = get_settings()

    print("Current email settings (from .env):")
    print(f"  EMAIL_PROVIDER  = {settings.email_provider}")
    print(f"  SMTP_HOST       = {settings.smtp_host}:{settings.smtp_port} (TLS={settings.smtp_use_tls})")
    print(f"  SMTP_USERNAME   = {settings.smtp_username or '(empty)'}")
    print(f"  SMTP_PASSWORD   = {'(empty)' if not settings.smtp_password else f'set, {len(settings.smtp_password)} characters'}")
    print(f"  SMTP_FROM_EMAIL = {settings.smtp_from_email or '(empty - uses SMTP_USERNAME)'}")
    print(f"  read from       = {Path('.env').resolve()}")
    print()

    problems = find_hidden_overrides(Path(".env"))
    if settings.email_provider == "smtp" and settings.smtp_password:
        problems += check_password_shape(settings.smtp_password)
    if problems:
        print("Problems found:")
        for problem in problems:
            print(f"  - {problem}")
        print()

    if settings.email_provider == "console":
        print("EMAIL_PROVIDER is 'console': codes are PRINTED in the API terminal, not emailed.")
        print("To send real email set EMAIL_PROVIDER=smtp in .env (see .env.example), then restart the API.")
        return 1

    if not settings.smtp_username or not settings.smtp_password:
        print("FAILED - SMTP_USERNAME and SMTP_PASSWORD must both be set in .env.")
        return 1

    port = settings.smtp_port
    failure = try_send(settings, port, to_email)
    if failure is not None:
        explain(failure)
        if failure.step == "login" and isinstance(failure.error, smtplib.SMTPAuthenticationError):
            return 1

        other_port = 587 if port == SMTP_SSL_PORT else SMTP_SSL_PORT
        print()
        print(f"Trying the other Gmail port ({other_port}) instead...")
        if try_send(settings, other_port, to_email) is not None:
            print(f"Port {other_port} fails too - fix the cause above (antivirus / network / wait), then run this again.")
            return 1
        print(f"SENT to {to_email} on port {other_port} - port {port} is blocked on this computer/network, {other_port} works.")
        print(f"FIX: in .env set  SMTP_PORT={other_port}  then restart the API.")

    print()
    print(f"SENT. Check the inbox AND the Spam folder of {to_email}.")
    print("If this worked but sign-up codes still don't arrive: restart the API (Ctrl+C, then start it again)")
    print("so it picks up the new .env, and make sure the email is invited (status 'invited') on the Users page.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
