"""
Encrypts secrets the app must keep in its own database - today, each
organization's Dropbox refresh token (app/api/dropbox_api.py) - so a
database dump or backup alone never exposes a working credential.

Fernet (AES-128-CBC + HMAC-SHA256) with a key derived from JWT_SECRET_KEY,
which the app already requires and keeps out of the database. Rotating
JWT_SECRET_KEY makes stored tokens unreadable: the owner then reconnects
Dropbox on the Vault page (the app says so instead of failing silently).
"""

import base64
import hashlib

from cryptography.fernet import Fernet, InvalidToken

from config.settings import get_settings

_PURPOSE = b"ashilegal:secret-box:v1:"


class SecretUnreadable(Exception):
    """The value was encrypted with a different key (e.g. JWT_SECRET_KEY was rotated)."""


def _fernet() -> Fernet:
    secret = get_settings().jwt_secret_key.encode()
    return Fernet(base64.urlsafe_b64encode(hashlib.sha256(_PURPOSE + secret).digest()))


def encrypt(plaintext: str) -> str:
    return _fernet().encrypt(plaintext.encode()).decode()


def decrypt(token: str) -> str:
    try:
        return _fernet().decrypt(token.encode()).decode()
    except InvalidToken as exc:
        raise SecretUnreadable("This stored secret can't be read with the current key.") from exc
