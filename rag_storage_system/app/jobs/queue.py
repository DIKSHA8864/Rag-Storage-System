"""
Background job queue - the single place that decides which Redis
connection and RQ queue POST /process enqueues work onto, mirroring
the get_storage_backend()/get_metadata_repository() factory pattern
used elsewhere in this app.

A worker process (see scripts/worker.py) listens on the same queue
name and actually runs the job; the API process only ever enqueues
and polls, so a slow document being processed never blocks it from
handling other requests.
"""

from functools import lru_cache

import redis
from rq import Queue
from rq.job import Job

from config.settings import get_settings


@lru_cache
def get_redis_connection() -> redis.Redis:
    return redis.from_url(get_settings().redis_url)


def get_job_queue() -> Queue:
    """
    Return the RQ queue POST /process enqueues onto.

    Not cached at module level (unlike get_redis_connection) so tests
    can monkeypatch this function directly to swap in a fake queue
    without needing a real Redis connection.
    """

    return Queue(get_settings().processing_queue_name, connection=get_redis_connection())


def fetch_job(job_id: str) -> Job | None:
    return get_job_queue().fetch_job(job_id)
