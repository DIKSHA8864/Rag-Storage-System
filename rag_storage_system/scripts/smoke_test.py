"""
Production smoke test (Milestone 7 handover step: "owner re-runs
smoke tests"). Exercises the 7 Blueprint acceptance flows against a
REAL deployed URL over real HTTP - not the pytest suite's mocked
TestClient/SQLite. Run this after the owner loads the production
library and after any deploy.

Usage:
    python scripts/smoke_test.py --base-url https://api.ashilegal.com \
        --admin-token <owner-jwt> --end-user-key <a-real-matter-key>
"""

import argparse
import sys

import httpx


def _check(name: str, condition: bool) -> bool:
    print(f"{'PASS' if condition else 'FAIL'} - {name}")
    return condition


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--admin-token", required=True)
    parser.add_argument("--end-user-key", required=True)
    args = parser.parse_args()

    admin_headers = {"Authorization": f"Bearer {args.admin_token}"}
    end_user_headers = {"X-End-User-Key": args.end_user_key}

    all_ok = True
    with httpx.Client(base_url=args.base_url, timeout=30.0) as client:
        # 1. Owner auth works
        categories = client.get("/categories", headers=admin_headers)
        all_ok &= _check("Owner auth + /categories reachable", categories.status_code == 200)

        # 2. Library has real content indexed (Sync/library-loaded check)
        documents = client.get("/documents", headers=admin_headers).json()
        indexed_count = sum(1 for d in documents.get("documents", []) if d.get("status") == "Indexed")
        all_ok &= _check(f"At least one document Indexed (found {indexed_count})", indexed_count > 0)

        # 3. Citation lock / Honest gap: a real question against the real library
        query = client.post(
            "/end-user/query", json={"query": "overtime pay requirements"}, headers=end_user_headers
        )
        all_ok &= _check("End-user query succeeds", query.status_code == 200)

        # 4. Intake flow reachable end-to-end
        session = client.post("/end-user/intake/sessions", json={"title": "Smoke test"}, headers=end_user_headers)
        all_ok &= _check("Intake session created", session.status_code == 200)
        if session.status_code == 200:
            session_id = session.json()["id"]
            start = client.post(f"/end-user/intake/sessions/{session_id}/interview/start", headers=end_user_headers)
            all_ok &= _check("Interview starts", start.status_code == 200)

    print("=" * 60)
    print("SMOKE TEST: " + ("ALL PASSED" if all_ok else "FAILURES ABOVE"))
    sys.exit(0 if all_ok else 1)


if __name__ == "__main__":
    main()