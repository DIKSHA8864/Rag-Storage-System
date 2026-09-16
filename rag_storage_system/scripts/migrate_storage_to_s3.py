"""
One-off: copy everything already in storage/originals/ into the
configured S3 backend (MinIO locally).

    python scripts/migrate_storage_to_s3.py            # show what would happen
    python scripts/migrate_storage_to_s3.py --commit   # actually upload

Dry-run by default, because save() never overwrites - running it
twice against the same bucket would create _1 copies of every file
rather than doing nothing. Check the MinIO console at
http://localhost:9001 if you're unsure what's already there.
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.storage.s3_backend import S3StorageBackend  # noqa: E402
from config.settings import get_settings  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--commit",
        action="store_true",
        help="Actually upload. Without this, only prints what would be uploaded.",
    )
    args = parser.parse_args()

    settings = get_settings()
    originals = settings.resolve(settings.original_storage_path)

    if not originals.exists():
        print(f"Nothing to migrate - {originals} does not exist.")
        return 0

    files = [
        path
        for path in sorted(originals.rglob("*"))
        if path.is_file() and path.name != ".gitkeep"
    ]

    if not files:
        print(f"Nothing to migrate - no files under {originals}.")
        return 0

    if not args.commit:
        print(f"DRY RUN - {len(files)} file(s) would go to bucket "
              f"'{settings.s3_bucket}':\n")
        for path in files:
            category = path.parent.relative_to(originals).as_posix() or "uncategorized"
            print(f"  {category}/{path.name}  ({path.stat().st_size:,} bytes)")
        print("\nRe-run with --commit to upload.")
        return 0

    backend = S3StorageBackend(
        bucket=settings.s3_bucket,
        quarantine_bucket=settings.s3_quarantine_bucket,
        region=settings.s3_region,
        endpoint_url=settings.s3_endpoint_url,
        access_key_id=settings.s3_access_key_id,
        secret_access_key=settings.s3_secret_access_key,
    )

    for path in files:
        category = path.parent.relative_to(originals).as_posix() or "uncategorized"

        with path.open("rb") as handle:
            result = backend.save(category, path.name, handle)

        print(f"  {result['category']}/{result['stored_filename']}  "
              f"({result['size']:,} bytes)")

    print(f"\nMigrated {len(files)} file(s) to bucket '{settings.s3_bucket}'.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
