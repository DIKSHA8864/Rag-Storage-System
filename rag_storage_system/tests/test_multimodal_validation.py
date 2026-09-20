"""Tests for app/multimodal/validation.py - intake-specific upload validation, wider than app/ingestion/file_validator.py's PDF/DOCX/TXT-only rules."""

from app.multimodal.validation import validate_intake_file
from config.settings import get_settings


def test_accepts_a_supported_image_extension():
    assert validate_intake_file("photo.png", 1000) == (True, "valid")


def test_accepts_a_supported_audio_extension():
    assert validate_intake_file("recording.mp3", 1000) == (True, "valid")


def test_accepts_a_zip_extension():
    assert validate_intake_file("bundle.zip", 1000) == (True, "valid")


def test_rejects_an_unsupported_extension():
    is_valid, reason = validate_intake_file("virus.exe", 1000)
    assert is_valid is False
    assert reason == "unsupported_extension:.exe"


def test_rejects_an_empty_file():
    is_valid, reason = validate_intake_file("a.png", 0)
    assert is_valid is False
    assert reason == "empty_file"


def test_rejects_a_file_over_the_size_limit(monkeypatch):
    monkeypatch.setattr(get_settings(), "intake_max_file_size_mb", 1)

    is_valid, reason = validate_intake_file("a.png", 2 * 1024 * 1024)
    assert is_valid is False
    assert reason == "file_too_large"
