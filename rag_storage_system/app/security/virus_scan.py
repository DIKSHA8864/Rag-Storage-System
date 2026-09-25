"""
Virus scanning of every uploaded file before it is stored (Work Plan M5:
"virus-scan uploads"). Covers library uploads and replacements, vault
sync, client intake uploads, and the Ask "compare a document" upload.

VIRUS_SCANNER=clamav streams the bytes to a ClamAV daemon (clamd) with
its INSTREAM command. It connects over TCP (CLAMAV_HOST / CLAMAV_PORT) or
a unix socket (CLAMAV_SOCKET). The protocol is small enough to speak
directly, so there is no extra dependency. clamd also scans inside ZIP
files. VIRUS_SCANNER=none (the default for local development) skips
scanning.

FAILS CLOSED: when scanning is on and clamd can't give a verdict
(unreachable, timed out, or the file is over clamd's StreamMaxLength),
this raises ScannerUnavailable. The caller then refuses the upload. It
never stores a file as "clean" that was not scanned. Set clamd's
StreamMaxLength at least as large as the largest upload allowed
(INTAKE_MAX_FILE_SIZE_MB) - see DOCS/RUNBOOK.md.
"""

import logging
import socket
import struct
from dataclasses import dataclass
from typing import Optional

from config.settings import get_settings

logger = logging.getLogger(__name__)

_CHUNK = 64 * 1024


class ScannerUnavailable(Exception):
    """Scanning is on but no verdict could be obtained - the file must not be accepted."""


@dataclass(frozen=True)
class ScanResult:
    clean: bool
    signature: Optional[str] = None  # e.g. "Win.Test.EICAR_HDB-1" when infected
    scanned: bool = True             # False = scanning is off (VIRUS_SCANNER=none)


def scanning_enabled() -> bool:
    return get_settings().virus_scanner.strip().lower() == "clamav"


def scan_bytes(data: bytes) -> ScanResult:
    scanner = get_settings().virus_scanner.strip().lower()
    if scanner in ("", "none"):
        return ScanResult(clean=True, scanned=False)
    if scanner != "clamav":
        raise ScannerUnavailable(f"Unknown VIRUS_SCANNER '{scanner}' (use 'clamav' or 'none').")
    return _clamd_instream(data)


def _connect() -> socket.socket:
    settings = get_settings()
    timeout = settings.clamav_timeout_seconds
    if settings.clamav_socket:
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        sock.settimeout(timeout)
        sock.connect(settings.clamav_socket)
        return sock
    return socket.create_connection((settings.clamav_host, settings.clamav_port), timeout=timeout)


def _clamd_instream(data: bytes) -> ScanResult:
    try:
        with _connect() as sock:
            sock.sendall(b"zINSTREAM\0")
            view = memoryview(data)
            for start in range(0, len(view), _CHUNK):
                chunk = view[start:start + _CHUNK]
                sock.sendall(struct.pack("!L", len(chunk)) + chunk.tobytes())
            sock.sendall(struct.pack("!L", 0))
            reply = b""
            while not reply.endswith(b"\0"):
                part = sock.recv(4096)
                if not part:
                    break
                reply += part
    except OSError as exc:
        logger.warning("Virus scan failed: clamd unreachable (%s).", exc)
        raise ScannerUnavailable("The virus scanner could not be reached.") from exc

    return parse_clamd_reply(reply.rstrip(b"\0").decode("utf-8", errors="replace").strip())


def parse_clamd_reply(text: str) -> ScanResult:
    """'stream: OK' | 'stream: <signature> FOUND' | '<anything> ERROR'."""

    body = text.split(":", 1)[1].strip() if ":" in text else text
    if body == "OK":
        return ScanResult(clean=True)
    if body.endswith(" FOUND"):
        return ScanResult(clean=False, signature=body[: -len(" FOUND")].strip() or "unknown")
    logger.warning("Virus scan gave no verdict: %r", text[:200])
    if "size limit" in text.lower():
        raise ScannerUnavailable("The file is larger than the virus scanner accepts (clamd StreamMaxLength).")
    raise ScannerUnavailable("The virus scanner returned an error.")


def ping() -> bool:
    """True when clamd answers PING (used by scripts/check_virus_scanner.py)."""

    try:
        with _connect() as sock:
            sock.sendall(b"zPING\0")
            return sock.recv(64).rstrip(b"\0").strip() == b"PONG"
    except OSError:
        return False
