import sys

from app.segmentation.chunker import (
    process_all_segments,
)

sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def main():

    print("=" * 70)
    print(
        "PHASE 5 - CHUNKING FOR EMBEDDING"
    )
    print("=" * 70)

    chunks = process_all_segments()

    if not chunks:

        print()
        print(
            "No chunks were generated."
        )

        return

    documents = {}

    for chunk in chunks:

        documents.setdefault(
            chunk["document_id"], []
        ).append(chunk)

    for document_id, items in documents.items():

        print()
        print("-" * 70)
        print(
            f"DOCUMENT: {document_id}"
        )
        print("-" * 70)

        print(
            f"Chunks: {len(items)}"
        )

        for chunk in items:

            print()
            print(
                f"CHUNK: {chunk['chunk_id']}"
            )

            print(
                f"Pages: "
                f"{chunk['start_page']} -> {chunk['end_page']}"
            )

            print(
                f"Words: {chunk['word_count']} "
                f"(~{chunk['approx_token_count']} tokens) "
                f"| reason: {chunk['split_reason']}"
            )

            print(
                f"Section: {chunk['section']} "
                f"| Subsection: {chunk['subsection']}"
            )

            preview = chunk["text"].replace("\n", " ")

            print("Preview:")
            print(preview[:300])

    word_counts = [c["word_count"] for c in chunks]

    print()
    print("=" * 70)
    print("CHUNKING SUMMARY")
    print("=" * 70)

    print(
        f"Documents: {len(documents)}"
    )

    print(
        f"Total chunks: {len(chunks)}"
    )

    print(
        f"Min / Avg / Max words per chunk: "
        f"{min(word_counts)} / "
        f"{sum(word_counts) // len(word_counts)} / "
        f"{max(word_counts)}"
    )


if __name__ == "__main__":
    main()
