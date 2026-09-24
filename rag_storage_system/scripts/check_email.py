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

import smtplib
import socket
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from app.notifications.email_sender import get_email_sender  # noqa: E402
from config.settings import get_settings  # noqa: E402


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
    print()

    if settings.email_provider == "console":
        print("EMAIL_PROVIDER is 'console': codes are PRINTED in the API terminal, not emailed.")
        print("To send real email set EMAIL_PROVIDER=smtp in .env (see .env.example), then restart the API.")
        return 1

    if settings.smtp_password and " " in settings.smtp_password:
        print("Note: SMTP_PASSWORD contains spaces - remove them (Gmail shows the App Password in groups of 4).")
        print()

    try:
        get_email_sender().send(
            to_email,
            "AshiLegal test email",
            "This is a test email from AshiLegal. If you can read it, email delivery is working.",
        )
    except smtplib.SMTPAuthenticationError as exc:
        print(f"FAILED - the mail server rejected the username/password: {exc}")
        print("  - Use a Gmail App Password (16 letters, no spaces), not the normal Gmail password.")
        print("  - 2-Step Verification must be ON for SMTP_USERNAME's Google account.")
        print("  - The App Password must be created while signed in as SMTP_USERNAME.")
        return 1
    except smtplib.SMTPException as exc:
        # Before the OSError branch below: SMTPException subclasses OSError.
        print(f"FAILED - the mail server refused the message: {exc!r}")
        return 1
    except (socket.timeout, TimeoutError, ConnectionError, OSError) as exc:
        print(f"FAILED - could not connect to {settings.smtp_host}:{settings.smtp_port}: {exc!r}")
        print("  - This network (firewall/antivirus/office network) is probably blocking outgoing port 587.")
        print("  - Try another network (e.g. a mobile hotspot) or ask IT to allow it.")
        return 1
    except Exception as exc:
        print(f"FAILED - {exc!r}")
        return 1

    print(f"SENT to {to_email}. Check the inbox AND the Spam folder.")
    print("If this worked but sign-up codes still don't arrive: restart the API (Ctrl+C, then start it again)")
    print("so it picks up the new .env, and make sure the email is invited (status 'invited') on the Users page.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
