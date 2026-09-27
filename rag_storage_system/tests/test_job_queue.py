"""Background jobs get JOB_TIMEOUT_SECONDS, not RQ's 180-second default - a first Dropbox sync or a full re-index takes longer."""

from app.jobs import queue
from config.settings import get_settings


def test_jobs_get_the_configured_time_limit(monkeypatch):
    monkeypatch.setattr(get_settings(), "job_timeout_seconds", 5400)
    assert queue.get_job_queue()._default_timeout == 5400


def test_default_time_limit_is_an_hour():
    assert type(get_settings()).model_fields["job_timeout_seconds"].default == 3600
