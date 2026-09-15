"""
Audit logging.

Every upload, replace, delete, rename, and category deletion in
app/api/storage_api.py is recorded here as one JSON line appended to
AUDIT_LOG_PATH (config/settings.py / .env - defaults to
logs/audit.log). JSON Lines rather than free-text so entries stay
easy to grep, tail, or load into a real log pipeline later without a
format migration.

There is no per-user identity to log yet (see app/security/auth.py -
a single shared admin key, not accounts), so `actor` is always
"admin" for now; the field exists so a future multi-user auth layer
can populate it without changing every call site or the log format.
"""

import json
from datetime import datetime, timezone
from typing import Optional

from config.settings import get_settings


def log_audit_event(
    action: str,
    category: Optional[str] = None,
    filename: Optional[str] = None,
    status: str = "success",
    detail: Optional[str] = None,
    actor: str = "admin",
) -> None:
    """
    Append one audit entry. Never raises - a logging failure (e.g. a
    read-only logs/ folder) must not block the action it's recording.
    """

    entry = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "actor": actor,
        "action": action,
        "category": category,
        "filename": filename,
        "status": status,
        "detail": detail,
    }

    settings = get_settings()
    log_path = settings.resolve(settings.audit_log_path)

    try:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        with open(log_path, "a", encoding="utf-8") as file:
            file.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except OSError:
        pass
