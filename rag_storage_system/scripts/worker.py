"""
Background worker process.

Listens on the Redis-backed queue POST /process enqueues onto (see
app/jobs/queue.py) and runs each job (app/jobs/processing.py:
run_processing_job - extraction -> segmentation -> chunking ->
embeddings) as it arrives. Keeping this in a separate process from
the API (uvicorn) is the whole point: a slow document being processed
here never blocks the API from answering other requests.

Requires Redis running (docker-compose.yml, or a free tier like
Upstash - see REDIS_URL in .env).

Usage (run in its own terminal, alongside `uvicorn app.api.storage_api:app`):
    python scripts/worker.py
"""

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from rq.worker import SimpleWorker  # noqa: E402

from app.jobs.queue import get_job_queue, get_redis_connection  # noqa: E402
from config.settings import get_settings  # noqa: E402


def run_worker() -> None:
    settings = get_settings()
    print(f"Listening on queue '{settings.processing_queue_name}' at {settings.redis_url} ...")

    # RQ's default Worker forks a child process per job (os.fork), which
    # doesn't exist on Windows. SimpleWorker runs each job in-process
    # instead (no fork, so no per-job hard timeout/crash isolation) -
    # the tradeoff that actually works cross-platform, which matters
    # more here than per-job isolation for this project's scale.
    worker = SimpleWorker([get_job_queue()], connection=get_redis_connection())
    worker.work()


if __name__ == "__main__":
    run_worker()
