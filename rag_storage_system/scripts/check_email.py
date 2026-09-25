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
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from app.notifications.email_sender import get_email_sender  # noqa: E402
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
