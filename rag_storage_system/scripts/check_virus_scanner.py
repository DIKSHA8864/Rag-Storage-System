"""
Check that upload virus scanning works end to end: clamd answers, and the
harmless EICAR test file is reported as infected.

Usage:
    python scripts/check_virus_scanner.py
"""

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from app.security.virus_scan import ScannerUnavailable, ping, scan_bytes, scanning_enabled  # noqa: E402
from config.settings import get_settings  # noqa: E402

# The standard anti-virus test string - not a virus; every scanner flags it on purpose.
EICAR = rb"X5O!P%@AP[4\PZX54(P^)7CC)7}$EICAR-STANDARD-ANTIVIRUS-TEST-FILE!$H+H*"


def main() -> int:
    settings = get_settings()
    if not scanning_enabled():
        print(f"VIRUS_SCANNER={settings.virus_scanner!r}: scanning is OFF - uploads are stored without a virus scan.")
        print("Set VIRUS_SCANNER=clamav (and CLAMAV_HOST/CLAMAV_PORT or CLAMAV_SOCKET) to turn it on.")
        return 1

    where = settings.clamav_socket or f"{settings.clamav_host}:{settings.clamav_port}"
    if not ping():
        print(f"FAIL: ClamAV (clamd) did not answer at {where}. Uploads are being refused until it does.")
        return 1
    print(f"OK: clamd answers at {where}.")

    try:
        clean = scan_bytes(b"An ordinary text file.")
        infected = scan_bytes(EICAR)
    except ScannerUnavailable as exc:
        print(f"FAIL: {exc}")
        return 1
    if not clean.clean:
        print(f"FAIL: a harmless file was flagged ({clean.signature}).")
        return 1
    if infected.clean:
        print("FAIL: the EICAR test file was NOT detected - check that ClamAV's signatures are loaded (freshclam).")
        return 1
    print(f"OK: the EICAR test file is detected ({infected.signature}). Upload scanning is working.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
