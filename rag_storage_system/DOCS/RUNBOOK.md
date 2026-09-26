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

## Vault sync (Dropbox / Google Drive)
- **Owner connects Dropbox (recommended, no server settings to change):**
  Vault -> Automatic sync -> **Connect Dropbox** -> sign in on Dropbox's page
  and Allow -> **Choose folders** -> tick the folders -> **Save and sync**.
  Each ticked folder becomes a library folder (its sub-folders come along);
  un-ticking one ("Remove") takes its files out of the library on the next
  sync; **Disconnect** stops syncing and keeps the library. Each organization
  has its own connection; the refresh token is stored encrypted (derived from
  `JWT_SECRET_KEY` - rotating that key asks the owner to reconnect).
- **One-time developer step for that:** register the AshiLegal app in the
  Dropbox App Console (Scoped access, **Full Dropbox**; permissions
  `files.metadata.read`, `files.content.read`, `account_info.read`; redirect
  URI `<FRONTEND_BASE_URL>/vault/dropbox`, e.g.
  `http://localhost:3000/vault/dropbox`), then set `DROPBOX_APP_KEY` and
  `DROPBOX_APP_SECRET`. Nothing else - the owner does the rest.
- **Server-settings fallback (one organization, `VAULT_SYNC_TENANT_ID`):**
  `VAULT_SYNC_DIR` = a folder the Dropbox / Google Drive desktop app keeps in
  sync on the server, or `DROPBOX_REFRESH_TOKEN` (+ optional
  `DROPBOX_ROOT_PATH`). Sub-folders become library folders; files at the top
  level go to "Unfiled". An owner's connected Dropbox takes precedence.
- **Run it:** `python scripts/vault_sync.py --watch` (every
  `VAULT_SYNC_INTERVAL_SECONDS`, default 5 min, for every organization with a
  source - an owner who connects later is picked up without a restart) as a
  service next to the worker,
  or "Sync now" on the Vault page (Owner). Each run: add new files, replace
  changed ones (their old text leaves search at once), delete removed ones,
  then index. The Vault page shows the last run and every skipped file with
  its reason.
- **Safety:** it only changes files it synced itself - never a hand upload.
  A missing/empty sync folder (drive not mounted, app signed out) is refused
  with nothing changed, as is a run that would delete most synced files at
  once - confirm that on the Vault page ("Yes, remove those files") or with
  `--allow-mass-delete`.
- **Duplicates:** a file whose content is already in the library (upload or
  sync, any name/folder) is not stored again - the reason names the existing file.

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

## Guided intake (story first)

Every new interview: language -> terms -> the client's story -> up to 4
follow-up questions -> the screening checklist -> protected activity ->
key dates -> documents. Interviews started before this change finish on
the old order.

- **Follow-up questions** are drawn only from the library folder
  `INTAKE_FRAMEWORK_CATEGORY` (default "Question Frameworks") and need
  `ANTHROPIC_API_KEY`. No framework passage matches, no key, or a failed
  call means no follow-ups. The interview then goes straight to the checklist.
- **Checklist**: Admin -> Intake. The Blueprint's required topics can be
  reworded but not switched off. An interview keeps the checklist it
  started with.
- **Key dates** are checked: unreadable dates, future dates, and dates
  before the hire date are asked again. "Don't know" is always accepted.
- **Terms acceptance** records the time, the terms version, and the
  client's IP address. Behind a reverse proxy, start uvicorn with
  `--proxy-headers --forwarded-allow-ips=<proxy IP>`. Without that, every
  client's IP is recorded as the proxy's address.

## Case matters and case documents

- Each new intake from a signed-in client opens its own **case matter**,
  named "<intake title> (<client email>)". It shows under Matters as
  "Case". Intakes started earlier stay in the client's own matter. If the
  plan's matter limit is reached, a new intake goes into the client's own
  matter instead of failing.
- On a case's page, attorneys upload that case's **documents**
  (pleadings, orders, motions, discovery, correspondence, evidence).
  Each file is virus-scanned, stored in case storage (INTAKE_STORAGE_PATH,
  not the library), and indexed by the background worker into that
  matter only. "Searchable (N passages)" means it can now be cited by the
  matter's research, reports and complaint drafts. "Failed" usually means
  a scanned PDF with no text layer; fix it and use Retry, or upload a
  text version. Delete removes the file and its passages from search.

## Complaints: California pleading paper and firm templates

- Settings -> **Pleading details**: attorney, bar number, firm, address,
  phone, email, "Attorney for", court and default county. They're printed
  on every generated complaint; blank fields stay [BRACKETED].
- The complaint generator (matter page -> select an intake) offers:
  **California pleading paper** (default: 28 numbered lines, double rule
  left and single rule right, caption, footer with page number and
  title, per CRC 2.100-2.119), **Firm template: <name>**, or **Plain
  draft**. Plaintiff, defendant, case number and county can be filled per
  case; anything left blank stays a placeholder.
- Settings -> **Pleading templates**: upload the firm's own .docx. Put
  `{{body}}` on a paragraph of its own; you can also use
  `{{attorney_block}} {{court}} {{plaintiff}} {{defendant}}
  {{case_number}} {{title}} {{causes}}` anywhere, including headers,
  footers and tables. Unknown placeholders are refused at upload. The
  complaint text takes the formatting of the `{{body}}` paragraph.
- Research suggestions never go in the pleading itself. They're on a
  final "ATTORNEY NOTES - REMOVE BEFORE FILING" page.

## Claude-written report analysis and complaint allegations

- With `ANTHROPIC_API_KEY` set (and credit on the account), the intake
  report's analysis (fact summary, causes of action, strengths,
  weaknesses, missing information, research questions) and the
  complaint's allegations are written by `DRAFTING_MODEL`. Everything
  else Claude does uses `ANALYSIS_MODEL`.
- Claude only sees the intake and the passages retrieval found. Any
  statute/case/regulation it names that isn't in a library passage is
  replaced by "[citation removed - not in the firm's library]"; a
  complaint authority is kept only if it appears in the library passage
  it cites, and is printed with that file and section. Case documents
  are facts, never authority.
- Each report/complaint says how it was prepared ("Analysis method" /
  "Drafting method"). No key, no credit or a failed call -> the template
  version (element-by-element) is produced, and the note says why.
- The system prompts are on Prompts -> "Intake Report Analysis" and
  "Complaint Allegations"; the checks above apply whatever they say.

## Analytics

Admin -> Analytics (owner only, your organization only; 7/30/90 days):
questions per day and by where they were asked; how they were answered
(cited, honest gap, withheld, errors); median and 95th-percentile answer
time; the client intake funnel (started -> terms -> completed -> report
generated -> approved); uploads; the most-cited library files; and model
calls and tokens per model. Cost appears only after you set `LLM_PRICES`
(USD per million input/output tokens per model, from Anthropic's pricing
page). It is never guessed.

## Stripe payments

Off by default (`BILLING_PROVIDER=manual`). To take card payments:
1. In Stripe, create a Product + recurring Price for each paid plan.
2. Set `BILLING_PROVIDER=stripe`, `STRIPE_SECRET_KEY`, and
   `BILLING_PLAN_ADMIN_EMAILS` (who may create and price plans - plans are
   shared by every organization). Optionally set
   `STRIPE_FALLBACK_PLAN_SLUG` (e.g. a "free" plan) so paid limits end when
   payments end.
3. Create each plan (POST /admin/billing/plans with `provider_price_id`),
   or set the price later: PUT /admin/billing/plans/{id}/provider-price.
4. In Stripe -> Developers -> Webhooks, add
   `https://<api host>/billing/stripe/webhook` with the events
   `checkout.session.completed`, `checkout.session.async_payment_succeeded`,
   `customer.subscription.created/updated/deleted`, `invoice.paid` and
   `invoice.payment_failed`. Put its signing secret in
   `STRIPE_WEBHOOK_SECRET`.

How it behaves: Billing -> "Pay with card (Stripe)" opens Stripe
Checkout. The plan changes **only** when Stripe's signed webhook confirms
the subscription. Each event re-reads the subscription from Stripe, so
retries and out-of-order deliveries are safe. A paid plan can't be
assigned directly (409). "Manage billing" opens Stripe's Billing Portal
(card, invoices, cancel). Card details never reach this server. Test
with Stripe test keys and the Stripe CLI (`stripe listen --forward-to
localhost:8000/billing/stripe/webhook`), or point `STRIPE_API_BASE` at
`stripe-mock`.

## Voice interviewer and "Talk to a person"

- **Read aloud**: in the client intake, "Read questions aloud" makes the
  on-screen assistant speak each question in English or Spanish. It
  uses the browser's own voice, so nothing leaves the device and no
  service is needed.
- **Answer by voice** appears only when a real speech-to-text engine is
  set (`STT_PROVIDER=whisper`). The recording is transcribed on this
  server, the text goes into the answer box for the client to check and
  edit, and only what they then send is recorded. The recording is not
  kept.
- **Talk to a person**: the client leaves a phone number or email (plus
  a best time). Staff see it under Admin -> **Requests**, take it ("I'll
  take it"), contact the client and close it with a note. The client
  sees the status. Set `HANDOFF_NOTIFY_EMAILS` to also email new
  requests. There is one open request per client at a time.
- A realistic video avatar (a filmed or AI presenter) would need a paid
  service such as HeyGen or D-ID. The built-in presenter is an animated
  illustration.

## Virus scanning

Every upload is scanned before it is stored: library uploads and
replacements, vault sync, client intake files (ZIPs included), and Ask
"compare" files. Turn it on with `VIRUS_SCANNER=clamav`, pointed at a
ClamAV daemon (`CLAMAV_HOST`/`CLAMAV_PORT`, or `CLAMAV_SOCKET`). For
example, `docker compose --profile scan up -d clamav`.

- Check it: `python scripts/check_virus_scanner.py`. It confirms clamd
  answers and that the harmless EICAR test file is detected.
- Infected files: library files go to quarantine and are never added;
  intake files are refused with a plain message and logged on the
  session timeline ("upload_blocked"); vault sync skips the file and
  lists it on the Vault page on every run until it is removed from the
  synced folder.
- Scanner down: uploads are **refused** (library: "not stored",
  intake: 503 "try again in a few minutes"). Nothing is stored
  unscanned.
- Large files: set clamd's `StreamMaxLength` at least as large as
  `INTAKE_MAX_FILE_SIZE_MB`. Anything bigger is refused as "larger than
  the virus scanner accepts".

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