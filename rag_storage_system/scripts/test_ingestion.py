from pathlib import Path
import json

from app.ingestion.ingestion_manager import ingest
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")


PROJECT_ROOT = Path(__file__).resolve().parents[1]

TEST_INPUT = PROJECT_ROOT / "test_data" / "documents"


def main():
    print("=" * 70)
    print("PHASE 2 - SECURE FILE INGESTION TEST")
    print("=" * 70)

    if not TEST_INPUT.exists():
        print(f"\nTest folder does not exist:")
        print(TEST_INPUT)
        return

    result = ingest(str(TEST_INPUT))

    print("\nRESULT")
    print("-" * 70)

    print(f"Total found:     {result['total_found']}")
    print(f"Total stored:    {result['total_stored']}")
    print(f"Total rejected:  {result['total_rejected']}")
    print(f"Total failed:    {result['total_failed']}")

    print("\nStored files:")
    for item in result["successful"]:
        print(f"  ✓ {item['filename']}")
        print(f"    SHA256: {item['sha256']}")

    print("\nRejected files:")
    for item in result["rejected"]:
        print(f"  ✗ {item['path']}")
        print(f"    Reason: {item['reason']}")

    print("\nFull result:")
    print(
        json.dumps(
            result,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()