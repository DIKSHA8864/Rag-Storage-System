"""Tests for app/multimodal/zip_processor.py - secure ZIP extraction (zip-slip, member count/size caps, no nested ZIPs)."""

import io
import zipfile

import pytest

from app.multimodal.zip_processor import ZipValidationError, extract_zip_members
from config.settings import get_settings


def _make_zip(entries: dict[str, bytes]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for name, data in entries.items():
            archive.writestr(name, data)
    return buffer.getvalue()


def test_extracts_every_member(tmp_path):
    zip_bytes = _make_zip({"a.txt": b"hello", "b.txt": b"world"})

    members = extract_zip_members(zip_bytes, tmp_path / "out")

    assert {name for name, _ in members} == {"a.txt", "b.txt"}
    assert (tmp_path / "out" / "a.txt").read_bytes() == b"hello"
    assert (tmp_path / "out" / "b.txt").read_bytes() == b"world"


def test_rejects_a_path_traversal_member(tmp_path):
    zip_bytes = _make_zip({"../../etc/passwd": b"malicious"})

    members = extract_zip_members(zip_bytes, tmp_path / "out")

    assert len(members) == 1
    _, extracted_path = members[0]
    assert extracted_path == tmp_path / "out" / "passwd"


def test_rejects_nested_zip_member(tmp_path):
    zip_bytes = _make_zip({"inner.zip": b"PK\x03\x04fake"})

    with pytest.raises(ZipValidationError, match="Nested ZIP"):
        extract_zip_members(zip_bytes, tmp_path / "out")


def test_rejects_too_many_files(tmp_path, monkeypatch):
    monkeypatch.setattr(get_settings(), "intake_zip_max_files", 2)

    zip_bytes = _make_zip({"a.txt": b"1", "b.txt": b"2", "c.txt": b"3"})

    with pytest.raises(ZipValidationError, match="exceeding the limit"):
        extract_zip_members(zip_bytes, tmp_path / "out")


def test_rejects_zip_bomb_by_total_uncompressed_size(tmp_path, monkeypatch):
    monkeypatch.setattr(get_settings(), "intake_zip_max_total_size_mb", 0)

    zip_bytes = _make_zip({"a.txt": b"some content"})

    with pytest.raises(ZipValidationError, match="uncompressed contents"):
        extract_zip_members(zip_bytes, tmp_path / "out")
