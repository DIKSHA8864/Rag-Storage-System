import sys

from app.segmentation.segmentation_manager import (
    process_all_documents,
)

sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def main():

    print("=" * 70)
    print(
        "PHASE 4 - DOCUMENT "
        "STRUCTURE & LOGICAL SEGMENTATION"
    )
    print("=" * 70)

    segments = (
        process_all_documents()
    )

    if not segments:

        print()
        print(
            "No segments were generated."
        )

        return

    documents = {}

    for segment in segments:

        filename = segment[
            "filename"
        ]

        documents.setdefault(
            filename,
            []
        ).append(
            segment
        )

    for filename, items in (
        documents.items()
    ):

        print()
        print("-" * 70)
        print(
            f"DOCUMENT: {filename}"
        )
        print("-" * 70)

        print(
            f"Segments: {len(items)}"
        )

        for segment in items:

            print()
            print(
                f"SEGMENT: "
                f"{segment['segment_id']}"
            )

            print(
                f"Pages: "
                f"{segment['start_page']} "
                f"-> "
                f"{segment['end_page']}"
            )

            print(
                f"Page count: "
                f"{segment['page_count']}"
            )

            print(
                f"Chapter: "
                f"{segment['chapter']}"
            )

            print(
                f"Section: "
                f"{segment['section']}"
            )

            print(
                f"Subsection: "
                f"{segment['subsection']}"
            )

            print(
                "Structures:"
            )

            for structure in (
                segment[
                    "structural_elements"
                ]
            ):

                print(
                    f"  [{structure['element_type']}] "
                    f"{structure['text']} "
                    f"(page "
                    f"{structure['page_number']})"
                )

            preview = (
                segment["text"]
                .replace(
                    "\n",
                    " "
                )
            )

            print(
                "Preview:"
            )

            print(
                preview[:500]
            )

    print()
    print("=" * 70)
    print(
        "SEGMENTATION SUMMARY"
    )
    print("=" * 70)

    print(
        f"Documents: "
        f"{len(documents)}"
    )

    print(
        f"Total logical segments: "
        f"{len(segments)}"
    )


if __name__ == "__main__":
    main()