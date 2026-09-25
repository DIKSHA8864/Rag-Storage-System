"""
Sync the library from the configured Dropbox / Google Drive folder
(VAULT_SYNC_DIR, or DROPBOX_* - see .env.example), then index the changes.

Usage:
    python scripts/vault_sync.py                  # one sync now
    python scripts/vault_sync.py --watch          # keep syncing every VAULT_SYNC_INTERVAL_SECONDS (default 300)
    python scripts/vault_sync.py --allow-mass-delete
        # a run that would delete most synced files at once is refused by
        # default (an unmounted/signed-out folder looks "empty") - pass this
        # only when that deletion is really intended.
"""

import argparse
import logging
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from app.vault_sync.runner import VaultSyncNotConfigured, run_vault_sync  # noqa: E402
from config.settings import get_settings  # noqa: E402


def _print_run(run: dict) -> None:
    print(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {run['source']}: {run['status'].upper()}")
    if run.get("error"):
        print(f"  {run['error']}")
    print(f"  added {run['added']}, updated {run['updated']}, deleted {run['deleted']}, unchanged {run['unchanged']}")
    for skipped in run["skipped"]:
        print(f"  skipped {skipped['path']}: {skipped['reason']}")
    if run.get("processing"):
        print(f"  indexed: {run['processing']}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--watch", action="store_true")
    parser.add_argument("--allow-mass-delete", action="store_true")
    args = parser.parse_args()
    logging.basicConfig(level=logging.WARNING)

    while True:
        try:
            run = run_vault_sync(allow_mass_delete=args.allow_mass_delete)
        except VaultSyncNotConfigured as exc:
            print(exc)
            return 1
        _print_run(run)
        if not args.watch:
            return 0 if run["status"] == "ok" else 1
        time.sleep(get_settings().vault_sync_interval_seconds)


if __name__ == "__main__":
    raise SystemExit(main())
