# Credential Rotation Procedure (run at handover, and periodically after)

1. **JWT_SECRET_KEY** — generate a new random 32+ byte value, set in the
   owner's production .env/secrets manager. Rotating this invalidates every
   existing Owner session (expected — everyone logs back in).

2. **ANTHROPIC_API_KEY** — owner creates a new key in their own Anthropic
   Console account, sets it in production secrets, revokes the
   developer-issued key from the Anthropic Console.

3. **Postgres password** — `ALTER USER raguser WITH PASSWORD '<new>';`
   then update POSTGRES_PASSWORD in production secrets and restart the app.

4. **END_USER_API_KEY** (legacy single shared key) — rotate in production
   secrets; any integration using it needs the new value.

5. **Per-Matter API keys** — these are already rotatable per-Matter without
   any downtime: POST /admin/matters/{id}/assignments doesn't touch the key,
   but re-issuing a Matter's key requires a new "regenerate key" endpoint
   (not yet built — today a Matter's key is fixed at creation; add
   POST /admin/matters/{id}/regenerate-key mirroring create_matter()'s
   secrets.token_urlsafe(32) + hash_api_key() pattern in app/api/storage_api.py
   if the owner needs per-Matter key rotation).

6. **Revoke developer credentials** — remove the developer's GitHub access
   to the AshiLegal-owned repo, remove them from the hosting/Postgres/
   Anthropic accounts entirely (not just rotate — actually remove their
   individual access where the platform supports it).