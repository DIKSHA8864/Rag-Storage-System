import json
from pathlib import Path

from app.segmentation.semantic_segmenter import (
    segment_document,
)

import sys

from app.segmentation.safe_splitter import (
    find_safe_split_points,
)

sys.stdout.reconfigure(encoding="utf-8", errors="replace")


PROJECT_ROOT = Path(__file__).resolve().parents[1]

PROCESSED = (
    PROJECT_ROOT
    / "storage"
    / "processed"
)


def main():

    print("=" * 70)
    print(
        "PHASE 4D - SAFE SPLIT POINT DETECTION TEST"
    )
    print("=" * 70)

    json_files = list(
        PROCESSED.rglob("extracted.json")
    )

    for json_file in json_files:

        document_data = json.loads(
            json_file.read_text(
                encoding="utf-8"
            )
        )

        segments = segment_document(
            document_data
        )

        print("\n")
        print("-" * 70)

        print(
            f"DOCUMENT: "
            f"{document_data['filename']}"
        )

        for segment in segments:

            print("\n")

            print(
                f"Segment: "
                f"{segment.segment_id}"
            )

            print(
                f"Pages: "
                f"{segment.start_page}"
                f" -> "
                f"{segment.end_page}"
            )

            points = find_safe_split_points(
                segment
            )

            print(
                f"Safe split points: "
                f"{len(points)}"
            )

            if not points:

                print(
                    "  No internal structural "
                    "split points found."
                )

            for point in points:

                print(
                    f"  ✓ Page "
                    f"{point.page_number}"
                    f" | "
                    f"{point.reason}"
                    f" | priority "
                    f"{point.priority}"
                )

    print("\n")
    print("=" * 70)
    print("SAFE SPLIT TEST COMPLETE")
    print("=" * 70)


if __name__ == "__main__":
    main()