# Secure RAG Storage System

A document storage, processing, and retrieval pipeline for RAG (Retrieval-Augmented
Generation): upload PDF/DOCX/TXT files into categorized folders, run them through
extraction → segmentation → chunking → embedding generation → pgvector indexing in
the background, then query them back through a hybrid retrieval pipeline (vector
search + keyword search + metadata filtering → reranking). On top of that, a
separate [End User API](#end-user-api) lets someone who isn't the Owner/Admin ask
questions and submit a document to be compared against the knowledge base, getting
back a structured match report - not just a chatbot answer. See
[What's not built yet](#whats-not-built-yet) for what's still missing.

## Setup

Every command below is run from the `rag_storage_system/` directory.

```bash
# 1. Create and activate a virtual environment
python -m venv .venv
.venv\Scripts\activate          # Windows
source .venv/bin/activate       # macOS/Linux

# 2. Install dependencies (pulls torch + sentence-transformers, a
#    multi-GB download the first time)
pip install -r requirements.txt

# 3. Copy the example environment file
copy .env.example .env          # Windows
cp .env.example .env            # macOS/Linux

# 4. Start Postgres (metadata + pgvector) and Redis (the background
#    processing queue's message broker)
docker compose up -d

# 5. Create the Owner account you'll log in with (prompts for email
#    and password; pass them as arguments instead if you don't mind
#    the password landing in your shell history)
python scripts/create_owner.py
```

`docker compose up -d` returns as soon as the containers start, a moment
before Postgres finishes initializing on a first run - if step 5 fails with a
connection error, wait for the healthcheck to pass
(`docker compose ps` shows `healthy`) and run it again.

Open `.env` and set `JWT_SECRET_KEY` to a long random secret - it signs every
Owner access token (see [Authentication](#authentication)), and the fallback
in `config/settings.py` is a placeholder committed to this repository, so
anyone who can read the source could mint a valid Owner token against a
deployment that never overrode it. Change `END_USER_API_KEY` too before
running this anywhere beyond your own machine. Leave `ANTHROPIC_API_KEY` blank
unless you want `/end-user/compare`'s report prose written by Claude instead
of the free built-in template - see [End User API](#end-user-api).

Step 5 is required - there is no default login. `scripts/create_owner.py`
creates the `owners` table if it doesn't exist yet and inserts one Owner with
an Argon2-hashed password; without it `POST /auth/login` has nothing to
authenticate against and every Owner/Admin endpoint stays locked. Run it again
with a different email to add another Owner:

```bash
python scripts/create_owner.py second-owner@example.com their-password
```

No separate migration step is needed - every file in `database/migrations/`
is applied automatically (idempotently) the first time the app opens a
Postgres connection.

Don't want to run Redis yourself? Point `REDIS_URL` in `.env` at a free tier
like [Upstash](https://upstash.com/) instead - `app/jobs/queue.py` just needs
a reachable Redis URL, it doesn't care where it's hosted.

Postgres, however, is not optional. `METADATA_BACKEND=sqlite` swaps only the
*folder/document* metadata store for a local file at `database/metadata.db`.
Owner accounts (`app/security/owner_repository.py`) and chunk embeddings
(`app/vector_store/`, pgvector - there's no sqlite equivalent for vector
search, see [Retrieval](#retrieval)) both connect to Postgres directly and
ignore that setting, so `POST /auth/login`, `POST /process` and `POST /search`
all need `docker compose up -d` whichever backend you pick. The test suite is
the exception - it always uses SQLite and skips the cases that need a real
Postgres (see [Testing](#testing)).

## Run

Check the environment first - a broken one is much cheaper to catch here than
mid-demo:

```bash
python scripts/health_check.py
```

It verifies every storage folder is writable, the metadata database is
reachable, and the embedding model can load (downloading it on first run,
~90MB) - exits non-zero if anything fails.

Then start the two processes, each in its own terminal:

```bash
# Terminal 1 - the API
uvicorn app.api.storage_api:app --reload

# Terminal 2 - the background worker
python scripts/worker.py
```

The worker is not optional. `POST /process` doesn't run the pipeline itself -
it enqueues a job onto Redis and the worker picks it up (see
[Background processing](#background-processing)). With no worker running, jobs
sit in the queue as `queued` indefinitely and nothing is ever extracted,
embedded, or indexed.

| URL | What it is |
|---|---|
| http://127.0.0.1:8000/docs | Swagger UI - every endpoint, with "Try it out" |
| http://127.0.0.1:8000/admin/dashboard | Owner Dashboard - log in, browse and manage categories/documents, trigger processing |
| http://127.0.0.1:8000/analyze | End User page - paste text or upload a file, see the comparison report rendered |

To use "Try it out" on an Owner/Admin endpoint in Swagger UI, call
`POST /auth/login` there first, copy `access_token` out of the response, then
click **Authorize** (top right) and paste that token on its own - no `Bearer `
prefix, Swagger adds it. `/end-user/*` uses the separate `X-End-User-Key`
field in the same Authorize dialog.

## Authentication

Owner/Admin endpoints authenticate with **email + password exchanged for a
JWT**, not a shared key. Log in with the account `scripts/create_owner.py`
created in step 5 of [Setup](#setup):

```bash
curl -X POST http://127.0.0.1:8000/auth/login \
  -H "Content-Type: application/json" \
  -d '{"email": "you@example.com", "password": "your-password"}'
```

```json
{"access_token": "eyJhbGciOi...", "token_type": "bearer", "expires_in": 3600}
```

Send that token as an `Authorization: Bearer` header on every Owner/Admin
request:

```bash
TOKEN=eyJhbGciOi...
curl -H "Authorization: Bearer $TOKEN" http://127.0.0.1:8000/categories
```

Tokens are signed with `JWT_SECRET_KEY` and expire after
`ACCESS_TOKEN_EXPIRE_MINUTES` (default 60), both from `.env`. Passwords are
hashed with Argon2 (`pwdlib`) and never stored in plaintext. Owner rows live
in the `owners` table on Postgres (`database/migrations/0004_owners.sql`,
`app/security/owner_repository.py`) - which is why Postgres is needed even
with `METADATA_BACKEND=sqlite`. See `app/security/auth.py` for the token
helpers and the `require_admin_key` dependency each protected endpoint
carries.

Exempt from Owner auth: `GET /`, `/docs`, `/openapi.json`, `POST /auth/login`,
and the HTML page routes (`/admin/dashboard`, `/analyze`, `/upload-test`) - a
plain browser navigation can't attach an `Authorization` header, so the pages
themselves are unauthenticated static HTML. Every API call their JavaScript
makes attaches the real credential and is checked exactly like a curl or
Swagger call to the same endpoint.

`/end-user/*` (see [End User API](#end-user-api)) is authenticated separately -
a different header (`X-End-User-Key`), a different secret (`END_USER_API_KEY`)
- so an Owner token grants it no access, and an End User key grants no access
to anything Owner/Admin. Only the Owner side has real accounts; the End User
scope is still a single shared secret.

## Audit logging

Every upload, replace, delete, rename, and category deletion is appended as
one JSON line to `logs/audit.log` (timestamp, action, category, filename,
status, detail). See `app/security/audit_log.py`.

## Endpoints

| Method | Path | Description |
|---|---|---|
| POST | `/auth/login` | Exchange an Owner email + password for a JWT access token *(no auth required)* |
| POST | `/categories` | Create a category (folder); pass `parent` to nest it under an existing one |
| GET | `/categories` | List categories/subfolders with document counts |
| PATCH | `/categories/{category}` | Rename/move a category (path may include subfolders, e.g. `Contracts/2024`) |
| DELETE | `/categories/{category}` | Delete a category (`?force=true` if it still has files) |
| POST | `/categories/{category}/documents` | Upload one PDF/DOCX/TXT file |
| POST | `/categories/{category}/documents/batch` | Upload several files at once |
| PUT | `/categories/{category}/documents/{filename}` | Replace a file's contents, keeping its name |
| DELETE | `/categories/{category}/documents/{filename}` | Delete one file |
| GET | `/documents` | List stored documents, with per-file processing status - poll this while a job runs |
| POST | `/process` | Enqueue extraction → segmentation → chunking → embeddings as a background job; returns `{job_id, status: "queued"}` immediately |
| GET | `/process/{job_id}` | Poll a background processing job's status (`queued`/`started`/`finished`/`failed`) and result |
| POST | `/search` | Hybrid retrieval (vector + keyword + metadata filter → rerank) over `Indexed` chunks |
| GET | `/admin/stats` | Document/category/status counts and storage usage, for the dashboard |
| GET | `/admin/dashboard` | Owner Dashboard UI (HTML page; its JavaScript logs in and calls the endpoints above) |
| GET | `/analyze` | End User UI (HTML page wrapping `POST /end-user/compare`) |
| GET | `/upload-test` | Legacy plain-HTML batch-upload page - **stale: its JavaScript still sends the retired `X-API-Key` header, so its uploads now fail.** Use `/admin/dashboard` or `/docs` |
| POST | `/end-user/query` *(End User scope)* | Q&A over the knowledge base - same hybrid retrieval as `/search` |
| POST | `/end-user/compare` *(End User scope)* | Submit text or a PDF/DOCX/TXT file, get a full comparison report against the knowledge base |

A file that fails validation (unsupported extension, empty, over the size
limit) is moved to quarantine instead of protected storage and reported back
with the rejection reason, rather than erroring the whole request.

### A note on `/docs` and multi-file upload

Swagger UI's own array-of-files widget needs the older OpenAPI 3.0
`format: binary` keyword to render a file picker; FastAPI's default OpenAPI
3.1 output doesn't include it. `storage_api.py` patches the generated schema
to add it back for the batch endpoint, so `/docs` renders a real "Choose
Files" picker there too. `/upload-test` predates that patch and hasn't been
updated for JWT auth (see the endpoint table above) - `/docs` and
`/admin/dashboard` both handle batch upload correctly.

## Document lifecycle

Each uploaded document moves through these statuses (visible via
`GET /documents`):

```
Uploaded → Processing → Embedding → Indexed
                      \→ Failed  (extraction error; see status_detail)
```

`Processing` covers extraction/segmentation/chunking; `Embedding` covers
generating each chunk's vector and writing it to pgvector (see
[Retrieval](#retrieval)). `POST /process` enqueues a background job that runs
the full pipeline and updates every document's status accordingly - safe to
call repeatedly, it always reprocesses everything currently in storage.

## Background processing

`POST /process` used to run extraction → segmentation → chunking →
embeddings inline, blocking the request until every document in storage was
reprocessed - a large document meant the whole API was unresponsive (new
uploads, status polls, everything) until it finished. It now just enqueues a
job and returns:

```json
{"job_id": "db70337a-...", "status": "queued"}
```

A separate worker process (`python scripts/worker.py`) picks the job off a
Redis-backed queue (`app/jobs/queue.py`) and actually runs it
(`app/jobs/processing.py:run_processing_job` - the same extraction →
segmentation → chunking → embeddings logic as before, unchanged). Poll
`GET /process/{job_id}` for the job itself, or `GET /documents` for
per-document status - either way, the API keeps answering other requests
the whole time.

Requires Redis running - `docker compose up -d` starts one, or point
`REDIS_URL` at a hosted free tier (e.g. Upstash) instead. The worker uses
`rq.worker.SimpleWorker` rather than the default `Worker`: RQ's default
forks a child process per job (`os.fork`), which doesn't exist on Windows.

The test suite doesn't need Redis or a worker running - `tests/conftest.py`
swaps in a fake in-process queue that runs each job synchronously, so
`POST /process` and `GET /process/{job_id}` can still be tested end-to-end
without either.

## Metadata database

Folders and documents (including per-document status) are tracked in a
normalized database, not by scanning the filesystem - see
`app/metadata/base.py` for the repository interface, `postgres_repository.py`
/ `sqlite_repository.py` for the two implementations (chosen via
`METADATA_BACKEND`), and `database/migrations/0001_initial_schema.sql` for
the full schema.

Only `folders` and `documents` are populated today. The schema also defines
`users`, `document_versions`, `chunks`, `embeddings`, `permissions`,
`analysis_requests`/`analysis_reports`, and `audit_logs` - not wired up to
application code yet, but structured now so later features (real user
accounts, version history, a queryable record of chunks/embeddings
alongside the JSON files in `storage/`, RAG query tracking) have a schema
to land in instead of fighting one. `app/api/storage_api.py` only ever
calls methods on the `MetadataRepository` interface, so it doesn't change
at all when the backend does.

Inspect the database directly:

```bash
docker exec -it rag_storage_postgres psql -U raguser -d rag_storage
```

## Pipeline phases

| Phase | Module | Input → Output |
|---|---|---|
| 1. Ingestion | `app/ingestion/` | Raw files → validated files in protected storage |
| 2. Extraction | `app/extraction/` | `storage/originals/` → `storage/processed/*/extracted.json` |
| 3. Segmentation | `app/segmentation/` | Extracted pages → `storage/segments/*/*.json` (logical sections) |
| 4. Chunking | `app/segmentation/chunker.py` | Segments → `storage/chunks/*/*.json` (embedding-sized pieces) |
| 5. Embeddings | `app/embeddings/` | Chunks → `storage/embeddings/*/*.json` (384-dim vectors, `all-MiniLM-L6-v2`) |
| 6. Vector indexing | `app/vector_store/` | Embeddings → `chunk_embeddings` table (pgvector) |
| 7. Retrieval | `app/retrieval/` | Query → hybrid search (vector + keyword + metadata filter) → reranked chunks |

All storage paths, the embedding provider/model, upload size/extension limits,
the admin key, the Redis URL, and the audit log path are centralized in
`config/settings.py` / `.env` - changing any of them, or swapping the local
disk storage backend for S3/R2/Azure/GCS/MinIO (`app/storage/base.py`
defines the interface), is a config change, not a rewrite of the endpoints.

## Retrieval

Phases 6-7 turn the embeddings Phase 5 already produces into something
queryable:

**Embedding provider** (`app/embeddings/base.py`) - `embed_texts()`
(`app/embeddings/embedding_manager.py`) goes through an `EmbeddingProvider`
interface rather than calling sentence-transformers directly, the same
swappable-backend principle as storage/metadata. `SentenceTransformerEmbeddingProvider`
(`app/embeddings/sentence_transformer_provider.py`) is the only one implemented -
free, local, no API key - selected via `EMBEDDING_PROVIDER` (`config/settings.py`).
A hosted provider (OpenAI, Cohere, ...) can be added later as a new class behind
the same interface, gated in `app/embeddings/__init__.py`'s `get_embedding_provider()`.

**Vector store** (`app/vector_store/base.py`) - `PgVectorRepository`
(`app/vector_store/vector_repository.py`) is the only `VectorStore` implementation:
pgvector on the same Postgres already running for metadata (see
`database/migrations/0002_pgvector.sql` for the enabled extension and the
`chunk_embeddings` table: `chunk_id`, `document_id`, `category`, `filename`,
`chunk_text`, `embedding vector(384)`, plus `metadata`) - no separate vector
database needed. `app/jobs/processing.py`'s background job writes each chunk's
embedding here right after Phase 5, transitioning every document's status
`Processing → Embedding → Indexed` as it goes.

**Hybrid retrieval** (`app/retrieval/retriever.py`) - `POST /search` runs:

```
query → query embedding
      → vector search (cosine similarity) + keyword search (Postgres full-text) + category filter, run together
      → reranking (weighted score fusion)
      → top_k chunks
```

Plain vector similarity alone misses exact keyword/number/proper-noun matches,
so `app/retrieval/search.py` runs both `vector_search()` and `keyword_search()`
against `chunk_embeddings` (the `category` argument is the "metadata filtering"
stage, narrowing the candidate set before either search runs) and
`app/retrieval/reranker.py` fuses their two, differently-scaled score sets into
one ranked list - a chunk found by both signals outranks one found by only one.
The reranker is a simple weighted sum today, not a learned/cross-encoder model -
a stronger reranker can slot in behind `rerank()`'s same signature later.

Both scores are put on a comparable scale with a **fixed** transform (cosine
similarity used as-is; `ts_rank` divided by a constant and clamped), never
per-query min-max normalization - min-max would rescale whatever range showed
up in one query's results to fill `[0, 1]`, making the best-of-a-bad-lot
candidate always look like a perfect match. `final_score` needs to mean the
same thing across different queries because `app/analysis/matcher.py` uses it
as an absolute confidence threshold (see [End User API](#end-user-api)), not
just to rank one query's own results against each other.

Only chunks from `Indexed` documents are searchable (that's when they land in
`chunk_embeddings`) - upload and `POST /process` a document before searching it.

## End User API

`app/api/end_user_api.py` (`/end-user/query`, `/end-user/compare`) is a
separate, more restricted surface on top of the same pipeline, for an actual
End User rather than the Owner/Admin - authenticated with a different header
and secret (`X-End-User-Key` / `END_USER_API_KEY`, see
[Authentication](#authentication)) so it can never reach `/categories`,
`/documents`, `/process`, or `/search`.

**`POST /end-user/query`** - plain Q&A: a text query in, the same hybrid
retrieval pipeline as `/search` (just scoped to this key) back out.

**`POST /end-user/compare`** - the actual deliverable: submit `query` (pasted
text) or `file` (a PDF/DOCX/TXT upload - audio/video is a later phase, not yet
supported) and get back a full structured comparison report, not just an
answer:

```
submission (text or file)
  → extraction → segmentation → chunking → embedding      (app/analysis/ingestion.py -
                                                             the exact same functions Owner
                                                             uploads go through; nothing here
                                                             is ever persisted - it exists only
                                                             for this one request)
  → per-chunk hybrid retrieval + classification            (app/analysis/matcher.py)
  → narrative generation                                   (app/analysis/ - template or Claude)
  → hallucination guard + report assembly                  (app/analysis/report_builder.py)
```

Each of the submission's chunks is compared against the knowledge base and
classified **match** / **partial_match** / **gap** by a fixed threshold on its
best retrieval score (`MATCH_SCORE_THRESHOLD_MATCH`/`_PARTIAL`,
config/settings.py) - never by an LLM. A cheap, deterministic
numeric/date-mismatch check (`app/analysis/matcher.py`) additionally flags
likely **conflicts** among matched items - "these are about the same thing but
cite different numbers" - without needing an LLM either.

**Match-score methodology** - `overall_match_score` (0-100) is:

```
coverage_ratio  = (matches + 0.5 x partial_matches) / total_chunks
avg_confidence  = mean(best retrieval score across every chunk)
overall_match_score = 100 x (COVERAGE_WEIGHT x coverage_ratio + CONFIDENCE_WEIGHT x avg_confidence)
```

Both weights and both classification thresholds are `.env` config
(`MATCH_SCORE_*`), not hardcoded, and were calibrated against this project's
default embedding model (all-MiniLM-L6-v2) - re-tune them if you switch
`EMBEDDING_MODEL` (see `config/settings.py`'s comment for the calibration
readings this project used).

**The report** (`AnalysisReport`, `app/api/schemas.py`) has an executive
summary, the overall match score with its breakdown, detailed matching
(similarities/differences/gaps/conflicts, each with cited sources - file name,
category, chapter, section, page range, chunk id, and score), recommendations,
and a flat, deduplicated source list. Every piece of text in the report is
tagged with a `provenance`: `"retrieved"` (a raw fact from the knowledge base),
`"generated"` (prose interpreting that fact), or `"recommendation"` (inferred
suggestion, not a retrieved fact) - so a reader never has to guess which is
which (`provenance_legend` in every response spells this out too).

**Hallucination control**: if not one chunk of the submission clears even the
partial-match threshold, the narrative generator is never called at all -
`executive_summary` is the fixed string `"Insufficient information found in
the available knowledge base."`, `overall_match_score` is `0`, and
`insufficient_evidence` is `true`. Per item, a `"gap"` classification always
gets the fixed `"No matching information found..."` narrative, regardless of
which narrative provider is active - never something an LLM wrote.

**Narrative provider** (the report's prose only - never the score or the
match/partial_match/gap classification): `app/analysis/base.py`'s
`NarrativeGenerator` interface, same swappable-provider pattern as embeddings.
`TemplateNarrativeGenerator` (default, free, deterministic, no API key) is
always available; `ClaudeNarrativeGenerator` (`NARRATIVE_PROVIDER=claude` +
`ANTHROPIC_API_KEY`) asks Claude to write the summary/per-item descriptions/
recommendations in one request, strictly grounded in the already-computed,
already-cited comparison data (never given the knowledge base itself, never
allowed to change a classification or score) - and its output is validated
JSON; a malformed response or API error falls back to the template provider
rather than breaking the report.

## What's not built yet

- A learned/cross-encoder reranker (today's `app/retrieval/reranker.py` is a
  simple weighted score fusion - see [Retrieval](#retrieval))
- A hosted embedding provider (today's only `EmbeddingProvider` is the free
  local sentence-transformers one - see [Retrieval](#retrieval))
- Audio/video input to `POST /end-user/compare` (PDF/DOCX/TXT only today -
  see [End User API](#end-user-api))
- Real semantic conflict detection (today's is a numeric/date-mismatch
  heuristic on already-matched pairs, not an NLI-style contradiction check -
  see [End User API](#end-user-api))
- `app/security/access_control.py` - RBAC. The Owner side has real accounts
  now (email + password + JWT, see [Authentication](#authentication)), but
  every Owner gets the single `owner` role, and the End User scope is still
  one shared key rather than accounts
- Rewriting `tests/test_auth.py` for JWT auth (see [Testing](#testing))
- `GET /upload-test` still sends the retired `X-API-Key` header (see the
  endpoint table)
- The `users`, `document_versions`, `permissions`, `analysis_requests`/
  `analysis_reports`, and `audit_logs` tables exist in the schema but aren't
  populated by application code yet (`chunks`/`embeddings` are also unused -
  `chunk_embeddings`, in `0002_pgvector.sql`, is what's actually populated;
  Owner logins live in the separate `owners` table from `0004_owners.sql`,
  not in `users`)

## Testing

```bash
pytest tests/ -q
```

Tests use throwaway storage backends and metadata databases (via `tmp_path`
fixtures) - nothing in the suite touches real project data, and the suite
always uses the SQLite metadata backend regardless of `METADATA_BACKEND` in
`.env`, so it runs without Docker/Postgres. `POST /process`'s tests use a fake
in-process queue and a fake in-memory vector store (`tests/conftest.py`) for
the same reason.

The metadata repository contract tests (`tests/test_metadata_repository.py`)
and the vector store tests (`tests/test_vector_store.py`) do need a real
Postgres/pgvector, and both TRUNCATE tables to isolate one test from the
next - so both point at `rag_storage_test`, a separate database on the same
docker-compose Postgres server, never at the real `rag_storage` database
(see `tests/postgres_test_support.py`). `rag_storage_test` is created
automatically on first test run if it doesn't exist yet; if Postgres itself
isn't reachable at all (`docker compose up -d` not run), those specific
cases are skipped rather than failed. A few tests (embeddings, vector store,
retrieval, analysis ingestion) load the real embedding model rather than
mocking it, so the first run may take a little longer while it downloads and
caches (~90MB, one-time). `tests/test_claude_narrative.py` mocks the Anthropic
client entirely - no `ANTHROPIC_API_KEY` needed to run the suite.

**Known failure:** `tests/test_auth.py` still tests the retired shared-key
scheme - it reads `get_settings().admin_api_key`, a setting the move to JWT
removed from `config/settings.py`, so those cases error out. The rest of the
suite is unaffected (`tests/conftest.py` overrides the auth dependency for
every other file). Rewriting them against `POST /auth/login` is outstanding
work, not a broken environment on your side.

## Project layout

```
app/
  api/            FastAPI app(s): storage_api.py (Owner/Admin), end_user_api.py (End User), auth_api.py (login), schemas
  ingestion/      File scanning + validation (Phase 1)
  extraction/     PDF/DOCX/TXT text extraction (Phase 2)
  segmentation/   Structure detection, logical segmentation, chunking (Phases 3-4)
  embeddings/     EmbeddingProvider interface + sentence-transformers implementation (Phase 5)
  vector_store/   VectorStore interface + pgvector implementation (Phase 6)
  retrieval/      Hybrid retrieval: vector + keyword search, reranking (Phase 7)
  analysis/       End User document comparison: ingestion, matching/scoring, narrative, report assembly
  storage/        Storage backend interface + local disk implementation
  metadata/       Metadata repository interface + Postgres/SQLite implementations
  jobs/           Background processing queue (app/jobs/queue.py) + the job itself (processing.py)
  security/       Path sanitization, Owner password/JWT auth + owners table, End User key auth, audit logging
  static/         Admin Dashboard + End User HTML pages, served straight off disk (no build step)
config/           Central settings (config/settings.py, .env)
database/
  migrations/     Postgres schema (0001_initial_schema.sql, pgvector in 0002/0003, owners in 0004)
  metadata.db     SQLite database when METADATA_BACKEND=sqlite (gitignored)
scripts/          create_owner.py (Owner account), health_check.py, worker.py (background job worker) + manual phase-testing scripts
tests/            pytest suite
storage/          Generated pipeline output (gitignored)
logs/             audit.log (gitignored)
docker-compose.yml  Local Postgres + Redis for development
```
