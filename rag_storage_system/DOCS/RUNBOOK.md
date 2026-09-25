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

## Library index stays in step with the library
- **Delete / Replace a file** (Vault): its text leaves search immediately. A
  replaced file is searchable again once processing (Re-index) has run.
- **Rename / move a folder**: indexed chunks are relabeled immediately.
- **Every processing run** rebuilds from `storage/originals` and removes any
  indexed library chunk it didn't produce (deleted, replaced, moved, or failed
  to extract) - the job result reports `stale_chunks_removed`. A Matter's own
  documents (`matter-<id>`) are never touched.
- `storage/processed|segments|chunks|embeddings` are build output: each run
  clears and rebuilds them (it refuses to run if one of them overlaps
  `storage/originals`), and git ignores them.
- **After upgrading to this version, run Re-index once**: document IDs now include
  the folder path, so the first run replaces every old chunk (expect a large
  `stale_chunks_removed`), including ones left by files deleted long ago.

## "No authority on this point was found" for a question the library covers
Run `python scripts/diagnose_ask.py "the exact question"` (add `--as person@firm.com`
to use an end user's organization). It prints each step of the Ask pipeline:
documents Indexed for that organization, the retrieval settings, every candidate
chunk with its score vs the threshold, and the relevance check's verdict (or why
it couldn't run - e.g. an invalid ANTHROPIC_API_KEY or no credit). A relevance
check that can't run is shown to users as "couldn't be verified - try again",
never as "No authority".

## Voice/Video (Client intake OCR/Speech-to-Text/Vision)
Real providers are opt-in (`OCR_PROVIDER`/`STT_PROVIDER`/`VISION_PROVIDER` in
`.env` — see `config/settings.py`); each defaults to `mock` (a clearly-labeled
placeholder, never fabricated text) until turned on:
- `OCR_PROVIDER=tesseract` — needs the `tesseract-ocr` system package
  (`apt-get install tesseract-ocr` / `brew install tesseract`). No API key,
  no network call at request time.
- `STT_PROVIDER=whisper` — needs no system package (faster-whisper bundles its
  own audio decoding), but downloads the chosen Whisper model
  (`WHISPER_MODEL_SIZE`, default `base`, ~75MB) from Hugging Face on first
  use, then caches it. Transcribes audio AND video files identically — no
  separate video-demuxing step (see app/multimodal/speech_to_text.py's
  WhisperSTTProvider docstring).
- `VISION_PROVIDER=claude` — needs `ANTHROPIC_API_KEY` (same key
  `NARRATIVE_PROVIDER=claude` already uses).
- `VIDEO_FRAME_SAMPLE_COUNT` (default `3`) — how many evenly-spaced frames
  app/multimodal/video_processor.py samples from an uploaded video (via
  PyAV, no ffmpeg subprocess needed) and captions through `VISION_PROVIDER`,
  in addition to transcribing its audio track. Set to `0` to skip frame
  captioning (audio-only) — useful to avoid per-frame cost once a paid
  Vision provider is configured.
- **"embedding model FAILED to load"**-style failure loading the Whisper
  model — same outbound-network restriction as the embedding model above;
  works once that restriction is lifted (a real deploy target, not this
  sandbox).

## User accounts (people who Ask and do Intake)
- The **admin** (created with `scripts/create_owner.py`, signs in at `/login`)
  invites people on the **Users** page. Only invited emails can sign up.
- Each person signs up once at `/portal/signup`: a 6-digit code is emailed to
  confirm the inbox, then they choose their own password. After that they sign
  in at `/portal/login` and see only **Ask** and **My Intake** - each person
  sees only their own history.
- **Someone leaves:** Users page -> **Deactivate**. Every open session ends
  immediately and they can't sign in again (their history stays for the admin).
- **Email delivery:** `EMAIL_PROVIDER=console` (default) prints codes in the API
  terminal for local testing. For real email set `EMAIL_PROVIDER=smtp` - see
  `.env.example` for Gmail App Password setup. Console mode is refused when
  `ENVIRONMENT=production`.
- **Codes not arriving?** The sign-up page answers the same way whether or not
  an email was sent, so check directly: `python scripts/check_email.py you@example.com`
  shows the active settings (and duplicate `.env` keys / environment-variable
  overrides), then connects step by step - reach, encrypt, login, send - and
  explains the step that failed (wrong App Password, antivirus mail scanning,
  blocked port, Gmail temporarily blocking after failed logins). If port 587 is
  blocked it tries 465 and says to set `SMTP_PORT=465` when that works. Restart
  the API after any `.env` change, and make sure the email is **invited** on the
  Users page.
- The API terminal logs every sign-up/reset request's outcome (never the code):
  `Sent signup code email to ...`, `NOT sent ...: this email has not been invited`,
  `NOT sent ...: the account is 'active'...` (already signed up - use Sign in /
  Forgot password), or `NOT resent ...: one was sent less than 60 seconds ago`.
- Matter access codes (Matters page) still work for API integrations only; the
  web portal uses accounts.

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