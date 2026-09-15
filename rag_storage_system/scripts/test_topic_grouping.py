import json
from pathlib import Path

from app.segmentation.semantic_segmenter import (
    segment_document,
)

import sys

from app.segmentation.topic_group import (
    group_segments_by_topic,
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
        "PHASE 4B - CROSS-DOCUMENT TOPIC GROUPING TEST"
    )
    print("=" * 70)

    json_files = list(
        PROCESSED.rglob("extracted.json")
    )

    if not json_files:

        print(
            "\nNo extracted JSON files found."
        )

        return

    all_segments = []

    # ----------------------------------------------------------
    # Extract logical segments from every document.
    # ----------------------------------------------------------

    for json_file in json_files:

        try:

            document_data = json.loads(
                json_file.read_text(
                    encoding="utf-8"
                )
            )

            segments = segment_document(
                document_data
            )

            all_segments.extend(
                segments
            )

        except Exception as exc:

            print(
                f"\nERROR processing "
                f"{json_file}: {exc}"
            )

    # ----------------------------------------------------------
    # Group segments.
    # ----------------------------------------------------------

    groups = group_segments_by_topic(
        all_segments
    )

    # ----------------------------------------------------------
    # Display result.
    # ----------------------------------------------------------

    print(
        f"\nDocuments found: "
        f"{len(json_files)}"
    )

    print(
        f"Logical segments: "
        f"{len(all_segments)}"
    )

    print(
        f"Topic groups: "
        f"{len(groups)}"
    )

    for group in groups:

        print("\n")
        print("-" * 70)

        print(
            f"TOPIC: {group.topic_id}"
        )

        print(
            f"Chapter: {group.chapter}"
        )

        print(
            f"Total pages: "
            f"{group.total_pages}"
        )

        print(
            f"Source documents: "
            f"{len(group.source_documents)}"
        )

        for document in group.source_documents:

            print(
                f"  ✓ {document}"
            )

        print("\nSections:")

        for section in group.sections:

            print(
                f"  • {section}"
            )

        print("\nSegments:")

        for segment in group.segments:

            print(
                f"  • {segment.segment_id}"
                f" | pages "
                f"{segment.start_page}"
                f" -> "
                f"{segment.end_page}"
            )

    print("\n")
    print("=" * 70)
    print("TOPIC GROUPING SUMMARY")
    print("=" * 70)

    print(
        f"Total topic groups: "
        f"{len(groups)}"
    )


if __name__ == "__main__":
    main()