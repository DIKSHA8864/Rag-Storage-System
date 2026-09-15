import json
from pathlib import Path

from app.extraction.extractor_manager import extract_document
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")


PROJECT_ROOT = Path(__file__).resolve().parents[1]

ORIGINALS = PROJECT_ROOT / "storage" / "originals"
PROCESSED = PROJECT_ROOT / "storage" / "processed"


def main():

    print("=" * 70)
    print("PHASE 3 - DOCUMENT EXTRACTION TEST")
    print("=" * 70)

    if not ORIGINALS.exists():
        print("\nOriginal storage folder does not exist.")
        return

    files = [
        path
        for path in ORIGINALS.rglob("*")
        if path.is_file()
        and path.suffix.lower() in {
            ".pdf",
            ".docx",
            ".txt",
        }
    ]

    if not files:
        print("\nNo supported documents found in:")
        print(ORIGINALS)
        return

    PROCESSED.mkdir(
        parents=True,
        exist_ok=True,
    )

    successful = 0
    failed = 0

    for file_path in files:

        print("\n" + "-" * 70)
        print(f"FILE: {file_path.name}")
        print("-" * 70)

        try:

            result = extract_document(file_path)

            print(f"Type: {result['file_type']}")

            if result["file_type"] == "pdf":

                print(
                    f"Pages: {result['page_count']}"
                )

                for page in result["pages"][:3]:

                    preview = page["text"][:150]

                    print(
                        f"\nPage {page['page_number']}:"
                    )

                    print(preview)

            elif result["file_type"] == "docx":

                print(
                    f"Paragraphs: "
                    f"{result['paragraph_count']}"
                )

                for paragraph in result["paragraphs"][:5]:

                    print(
                        f"\nParagraph "
                        f"{paragraph['paragraph_number']}:"
                    )

                    print(paragraph["text"][:150])

                    print(
                        f"Style: "
                        f"{paragraph['style']}"
                    )

            elif result["file_type"] == "txt":

                print(
                    f"Characters: "
                    f"{result['character_count']}"
                )

                print(
                    f"Lines: "
                    f"{result['line_count']}"
                )

                print("\nPreview:")

                print(
                    result["text"][:300]
                )

            # Save extracted structure
            relative_path = file_path.relative_to(
                ORIGINALS
            )

            output_directory = (
                PROCESSED
                / relative_path.parent
                / relative_path.stem
            )

            output_directory.mkdir(
                parents=True,
                exist_ok=True,
            )

            output_file = (
                output_directory
                / "extracted.json"
            )

            output_file.write_text(
                json.dumps(
                    result,
                    indent=2,
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            print(
                f"\nSaved extraction:"
            )

            print(output_file)

            successful += 1

        except Exception as exc:

            print(
                f"\nERROR: {exc}"
            )

            failed += 1

    print("\n" + "=" * 70)
    print("EXTRACTION SUMMARY")
    print("=" * 70)

    print(f"Successful: {successful}")
    print(f"Failed:     {failed}")


if __name__ == "__main__":
    main()