"""Tests for scripts/health_check.py."""

import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

import health_check  # noqa: E402


def test_check_folder_writable_reports_ok(tmp_path):
    ok, message = health_check._check_folder_writable("test", tmp_path / "sub")
    assert ok is True
    assert "writable" in message


def test_check_folder_writable_reports_failure_when_blocked(tmp_path):
    blocker = tmp_path / "blocker"
    blocker.write_text("not a directory", encoding="utf-8")

    ok, message = health_check._check_folder_writable("test", blocker / "sub")
    assert ok is False
    assert "NOT writable" in message


def test_check_metadata_db_reports_ok():
    ok, message = health_check._check_metadata_db("test-backend")
    assert ok is True
    assert "reachable" in message


def test_check_metadata_db_reports_failure_when_repository_unreachable(monkeypatch):
    import app.metadata as metadata_package

    def _raise():
        raise RuntimeError("connection refused")

    # _check_metadata_db does `from app.metadata import
    # get_metadata_repository` inside its own body, so patching the
    # module attribute is what actually takes effect at call time.
    monkeypatch.setattr(metadata_package, "get_metadata_repository", _raise)

    ok, message = health_check._check_metadata_db("test-backend")
    assert ok is False
    assert "NOT reachable" in message


def test_check_embedding_model_reports_ok_for_configured_model():
    ok, message = health_check._check_embedding_model("all-MiniLM-L6-v2")
    assert ok is True
    assert "loads OK" in message


def test_check_embedding_model_reports_failure_for_bad_name():
    ok, message = health_check._check_embedding_model("not-a-real-model-xyz")
    assert ok is False
    assert "FAILED to load" in message


def test_run_health_check_against_real_project_env():
    """
    The real project environment (not tmp_path) should already pass
    every check - this is the same thing running the script directly
    verifies, just as an assertion instead of eyeballing output.
    """

    assert health_check.run_health_check() is True
