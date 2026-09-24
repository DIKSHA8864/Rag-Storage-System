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