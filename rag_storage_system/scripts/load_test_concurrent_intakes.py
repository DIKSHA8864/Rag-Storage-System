"""
Load sanity check (Milestone 7): fires N concurrent intake sessions -
create session, submit a few interview messages, upload a small file
- against a RUNNING server (not TestClient - this measures real
latency under concurrency) and reports latency percentiles and error
rate. Not a full load-testing framework (Locust/k6) - a quick sanity
gate to run before a demo or release.

Usage:
    python scripts/load_test_concurrent_intakes.py --base-url http://localhost:8000 \
        --end-user-key <key> --concurrency 20 --sessions-per-worker 3
"""

import argparse
import concurrent.futures
import io
import statistics
import time

import httpx


def _run_one_intake(base_url: str, headers: dict) -> tuple[bool, float]:
    start = time.perf_counter()
    try:
        with httpx.Client(base_url=base_url, headers=headers, timeout=30.0) as client:
            session = client.post("/end-user/intake/sessions", json={"title": "Load test"})
            session.raise_for_status()
            session_id = session.json()["id"]

            client.post(f"/end-user/intake/sessions/{session_id}/interview/start").raise_for_status()
            client.post(
                f"/end-user/intake/sessions/{session_id}/interview/message", json={"message": "english"}
            ).raise_for_status()
            client.post(
                f"/end-user/intake/sessions/{session_id}/interview/message", json={"message": "I agree"}
            ).raise_for_status()

            upload = client.post(
                f"/end-user/intake/sessions/{session_id}/uploads",
                files={"file": ("notes.txt", io.BytesIO(b"Load test upload."), "text/plain")},
            )
            upload.raise_for_status()

        return True, time.perf_counter() - start
    except Exception:
        return False, time.perf_counter() - start


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--end-user-key", required=True)
    parser.add_argument("--concurrency", type=int, default=20)
    parser.add_argument("--sessions-per-worker", type=int, default=3)
    args = parser.parse_args()

    headers = {"X-End-User-Key": args.end_user_key}
    total_runs = args.concurrency * args.sessions_per_worker

    results = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=args.concurrency) as executor:
        futures = [
            executor.submit(_run_one_intake, args.base_url, headers) for _ in range(total_runs)
        ]
        for future in concurrent.futures.as_completed(futures):
            results.append(future.result())

    successes = [latency for ok, latency in results if ok]
    failures = [latency for ok, latency in results if not ok]

    print("=" * 60)
    print(f"LOAD SANITY CHECK — {total_runs} concurrent intake runs, concurrency={args.concurrency}")
    print("=" * 60)
    print(f"Success: {len(successes)}/{total_runs} ({100 * len(successes) / total_runs:.1f}%)")
    print(f"Failed:  {len(failures)}/{total_runs}")
    if successes:
        print(f"Latency (s): p50={statistics.median(successes):.2f}  "
              f"p95={sorted(successes)[int(0.95 * len(successes))]:.2f}  "
              f"max={max(successes):.2f}")


if __name__ == "__main__":
    main()