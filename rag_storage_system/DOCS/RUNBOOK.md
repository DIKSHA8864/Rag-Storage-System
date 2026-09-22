# AshiLegal Platform — Operations Runbook

## Starting the stack (local/staging)
    docker compose up -d          # Postgres (pgvector) + Redis
    python scripts/health_check.py
    uvicorn app.api.storage_api:app --reload
    python scripts/worker.py      # background job worker (uploads/processing)

## Common failures
- **"embedding model FAILED to load"** — outbound network to huggingface.co is
  blocked; the app needs it once to download all-MiniLM-L6-v2, then caches it.
- **psycopg import error** — see app/security/owner_repository.py's deferred
  import pattern; usually a missing libpq / blocked binary on Windows.
- **Stale test failures after a pull** — clear __pycache__:
  `Get-ChildItem -Recurse -Directory -Filter __pycache__ | Remove-Item -Recurse -Force`

## Backup / restore
See scripts/backup_postgres.sh / restore_postgres.sh. Run the drill quarterly;
log date + operator + row-count verification below.

| Date | Operator | Backup size | Restore verified? |
|------|----------|-------------|--------------------|
|      |          |             |                    |

## Credential rotation (see section 4.4 below for the full procedure)

## Deploy
1. CI (.github/workflows/ci.yml) must be green on the target commit.
2. [fill in your actual deploy mechanism — Railway/Render/AWS — once chosen]
3. Run scripts/smoke_test.py against the deployed URL immediately after.

## Owner loads the production library (post-handover)
1. POST /categories to create the folder structure (or reuse existing).
2. POST /categories/{category}/documents/batch to upload real library files
   (owner's own login, not a developer's).
3. POST /process to run extraction → chunking → embedding for the new files.
4. GET /documents to confirm every file reached status "Indexed".
5. Run scripts/smoke_test.py against production to confirm retrieval now
   returns real citations from the production library.