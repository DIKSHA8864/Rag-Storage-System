"""
S3-compatible storage backend.

One implementation covers three deployments - only the endpoint and
credentials differ:

    MinIO (local dev)  S3_ENDPOINT_URL=http://localhost:9000
    AWS S3             S3_ENDPOINT_URL=          (blank)
    Cloudflare R2      S3_ENDPOINT_URL=https://<account>.r2.cloudflarestorage.com

WHY THIS ISN'T A DROP-IN COPY OF LocalStorageBackend

Object stores have no directories. "Contracts/2024/a.pdf" is a single
flat key that happens to contain slashes, so:

  - An empty category cannot exist on its own. create_category()
    therefore writes a zero-byte marker object (_FOLDER_MARKER) to
    keep the empty-folder behaviour storage_api.py already promises.
    The marker is filtered out of every listing and never counted as
    a document.

  - There is no atomic rename. rename_category() copies every object
    under the old prefix and then deletes the originals - O(n) API
    calls, and a crash halfway leaves the category split across two
    prefixes. Acceptable at the current scale; see the README note.

Everything else matches LocalStorageBackend's contract exactly
(sanitization, collision avoidance, sha256, recursive category
counts), so tests/test_storage_backend.py passes against both.
"""

import hashlib
import io
from pathlib import Path
from typing import BinaryIO, Iterator, Optional

import boto3
from botocore.client import Config
from botocore.exceptions import ClientError

from app.security.path_security import sanitize_category_path, sanitize_path_segment
from app.storage.base import StorageBackend

# Zero-byte object that lets a category with no documents exist.
_FOLDER_MARKER = ".keep"

# S3's DeleteObjects caps at 1000 keys per request.
_DELETE_BATCH_SIZE = 1000


class S3StorageBackend(StorageBackend):

    def __init__(
        self,
        bucket: str,
        quarantine_bucket: str,
        region: str = "us-east-1",
        endpoint_url: str = "",
        access_key_id: str = "",
        secret_access_key: str = "",
    ):
        self._bucket = bucket
        self._quarantine_bucket = quarantine_bucket
        self._region = region

        self._client = boto3.client(
            "s3",
            region_name=region or None,
            endpoint_url=endpoint_url or None,
            aws_access_key_id=access_key_id or None,
            aws_secret_access_key=secret_access_key or None,
            # Path-style addressing: MinIO serves every bucket from one
            # host and has no per-bucket DNS entry to use instead.
            config=Config(
                signature_version="s3v4",
                s3={"addressing_style": "path"},
            ),
        )

        self._ensure_bucket(self._bucket)
        self._ensure_bucket(self._quarantine_bucket)

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _ensure_bucket(self, bucket: str) -> None:
        try:
            self._client.head_bucket(Bucket=bucket)
            return
        except ClientError:
            pass

        params: dict = {"Bucket": bucket}

        # Real AWS rejects a LocationConstraint of us-east-1 but
        # requires one everywhere else. MinIO accepts either.
        if self._region and self._region != "us-east-1":
            params["CreateBucketConfiguration"] = {"LocationConstraint": self._region}

        try:
            self._client.create_bucket(**params)
        except ClientError as exc:
            code = exc.response.get("Error", {}).get("Code", "")
            if code not in ("BucketAlreadyOwnedByYou", "BucketAlreadyExists"):
                raise OSError(f"Could not create or reach bucket '{bucket}': {exc}") from exc

    @staticmethod
    def _safe_names(category: str, filename: str) -> tuple[str, str]:
        """Sanitize exactly as LocalStorageBackend does, in the same order."""

        return (
            sanitize_category_path(category),
            sanitize_path_segment(Path(filename).name),
        )

    def _key(self, category: str, filename: str) -> str:
        safe_category, safe_filename = self._safe_names(category, filename)
        return f"{safe_category}/{safe_filename}"

    def _list(self, bucket: str, prefix: str = "") -> Iterator[dict]:
        """Every object under `prefix`, paginated (list_objects_v2 caps at 1000)."""

        paginator = self._client.get_paginator("list_objects_v2")
        for page in paginator.paginate(Bucket=bucket, Prefix=prefix):
            yield from page.get("Contents", [])

    @staticmethod
    def _is_marker(key: str) -> bool:
        return key.rsplit("/", 1)[-1] == _FOLDER_MARKER

    def _delete_keys(self, bucket: str, keys: list[str]) -> None:
        for start in range(0, len(keys), _DELETE_BATCH_SIZE):
            batch = keys[start : start + _DELETE_BATCH_SIZE]
            self._client.delete_objects(
                Bucket=bucket,
                Delete={"Objects": [{"Key": key} for key in batch]},
            )

    def _head(self, bucket: str, key: str) -> Optional[dict]:
        try:
            return self._client.head_object(Bucket=bucket, Key=key)
        except ClientError:
            return None

    def _put(self, bucket: str, key: str, data: bytes) -> dict:
        digest = hashlib.sha256(data).hexdigest()
        self._client.put_object(
            Bucket=bucket, Key=key, Body=data, Metadata={"sha256": digest}
        )
        return {"size": len(data), "sha256": digest}

    def _non_colliding(self, safe_category: str, safe_filename: str) -> str:
        """
        Never overwrite: append _1, _2, ... exactly like
        local_backend._avoid_collision().
        """

        parsed = Path(safe_filename)
        base, suffix = parsed.stem, parsed.suffix

        candidate = safe_filename
        counter = 1

        while self._head(self._bucket, f"{safe_category}/{candidate}") is not None:
            candidate = f"{base}_{counter}{suffix}"
            counter += 1

        return candidate

    # ------------------------------------------------------------------
    # Categories
    # ------------------------------------------------------------------

    def create_category(self, category: str) -> str:
        safe_category = sanitize_category_path(category)
        self._client.put_object(
            Bucket=self._bucket, Key=f"{safe_category}/{_FOLDER_MARKER}", Body=b""
        )
        return safe_category

    def list_categories(self) -> list[dict]:
        """
        Every category and subcategory, with a RECURSIVE document
        count - "Contracts" includes files in "Contracts/2024", to
        match LocalStorageBackend's rglob-based count.
        """

        counts: dict[str, int] = {}

        for obj in self._list(self._bucket):
            key = obj["Key"]
            parent_segments = key.split("/")[:-1]

            for depth in range(1, len(parent_segments) + 1):
                prefix = "/".join(parent_segments[:depth])
                counts.setdefault(prefix, 0)

                if not self._is_marker(key):
                    counts[prefix] += 1

        return [
            {"name": name, "document_count": count}
            for name, count in sorted(counts.items())
        ]

    def rename_category(self, old_name: str, new_name: str) -> str:
        safe_old = sanitize_category_path(old_name)
        safe_new = sanitize_category_path(new_name)

        existing = [obj["Key"] for obj in self._list(self._bucket, f"{safe_old}/")]

        if not existing:
            raise FileNotFoundError(f"Category not found: {safe_old}")

        if any(True for _ in self._list(self._bucket, f"{safe_new}/")):
            raise ValueError(f"Category already exists: {safe_new}")

        # No atomic rename in an object store - copy, then delete.
        for key in existing:
            self._client.copy_object(
                Bucket=self._bucket,
                CopySource={"Bucket": self._bucket, "Key": key},
                Key=safe_new + key[len(safe_old) :],
            )

        self._delete_keys(self._bucket, existing)
        return safe_new

    def delete_category(self, category: str, force: bool = False) -> bool:
        safe_category = sanitize_category_path(category)

        keys = [obj["Key"] for obj in self._list(self._bucket, f"{safe_category}/")]

        if not keys:
            return False

        if not force and any(not self._is_marker(key) for key in keys):
            raise ValueError(
                f"Category '{safe_category}' is not empty. "
                "Pass force=True to delete it anyway."
            )

        self._delete_keys(self._bucket, keys)
        return True

    # ------------------------------------------------------------------
    # Files
    # ------------------------------------------------------------------

    def save(self, category: str, filename: str, file_obj: BinaryIO) -> dict:
        safe_category, safe_filename = self._safe_names(category, filename)

        # Registers the category, so an upload into a brand-new one
        # behaves like local disk's mkdir(parents=True).
        self.create_category(safe_category)

        stored_filename = self._non_colliding(safe_category, safe_filename)
        result = self._put(
            self._bucket, f"{safe_category}/{stored_filename}", file_obj.read()
        )

        return {
            "stored_filename": stored_filename,
            "category": safe_category,
            **result,
        }

    def replace(self, category: str, filename: str, file_obj: BinaryIO) -> dict:
        safe_category, safe_filename = self._safe_names(category, filename)
        key = f"{safe_category}/{safe_filename}"

        if self._head(self._bucket, key) is None:
            raise FileNotFoundError(
                f"Cannot replace - file not found: {safe_category}/{safe_filename}"
            )

        result = self._put(self._bucket, key, file_obj.read())

        return {
            "stored_filename": safe_filename,
            "category": safe_category,
            **result,
        }

    def delete(self, category: str, filename: str) -> bool:
        key = self._key(category, filename)

        if self._head(self._bucket, key) is None:
            return False

        self._client.delete_object(Bucket=self._bucket, Key=key)
        return True

    def exists(self, category: str, filename: str) -> bool:
        return self._head(self._bucket, self._key(category, filename)) is not None

    def open_file(self, category: str, filename: str) -> BinaryIO:
        safe_category, safe_filename = self._safe_names(category, filename)
        key = f"{safe_category}/{safe_filename}"

        try:
            response = self._client.get_object(Bucket=self._bucket, Key=key)
        except ClientError as exc:
            raise FileNotFoundError(
                f"File not found: {safe_category}/{safe_filename}"
            ) from exc

        # Buffered rather than streamed: PyMuPDF and python-docx both
        # seek, which S3's StreamingBody does not support. Uploads are
        # capped at MAX_FILE_SIZE_MB, so this stays bounded.
        return io.BytesIO(response["Body"].read())

    def list_files(self, category: Optional[str] = None) -> list[dict]:
        prefix = f"{sanitize_category_path(category)}/" if category else ""

        documents = []

        for obj in self._list(self._bucket, prefix):
            key = obj["Key"]

            if self._is_marker(key):
                continue

            obj_category, _, name = key.rpartition("/")
            parsed = Path(name)

            documents.append(
                {
                    "filename": name,
                    "category": obj_category or "uncategorized",
                    "relative_path": key,
                    "extension": parsed.suffix.lower(),
                    "size": obj["Size"],
                }
            )

        return sorted(documents, key=lambda document: document["relative_path"])

    # ------------------------------------------------------------------
    # Quarantine
    # ------------------------------------------------------------------

    def quarantine(self, category: str, filename: str, file_obj: BinaryIO) -> dict:
        safe_category, safe_filename = self._safe_names(category, filename)

        result = self._put(
            self._quarantine_bucket,
            f"{safe_category}/{safe_filename}",
            file_obj.read(),
        )

        return {
            "stored_filename": safe_filename,
            "category": safe_category,
            **result,
        }

    # ------------------------------------------------------------------
    # Pre-signed URLs
    # ------------------------------------------------------------------

    def presigned_upload_url(
        self, category: str, filename: str, expires_in: int = 900
    ) -> str:
        return self._client.generate_presigned_url(
            "put_object",
            Params={"Bucket": self._bucket, "Key": self._key(category, filename)},
            ExpiresIn=expires_in,
        )

    def presigned_download_url(
        self, category: str, filename: str, expires_in: int = 900
    ) -> str:
        return self._client.generate_presigned_url(
            "get_object",
            Params={"Bucket": self._bucket, "Key": self._key(category, filename)},
            ExpiresIn=expires_in,
        )
