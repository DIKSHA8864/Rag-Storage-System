"""
Small helpers shared between app/api/intake_api.py (uploads/reports)
and app/api/interview_api.py (the Guided Intake Engine) - both are
Matter-scoped the same way app/api/end_user_api.py's threads are.

A signed-in client owns their personal matter plus every case matter
they opened (one per intake - migration 0024). Someone using a
per-matter access code (X-End-User-Key) owns just that one matter.
"""

import logging
import secrets

from fastapi import HTTPException

from app.security.auth import hash_api_key

logger = logging.getLogger(__name__)


def owned_matter_ids(repo, matter: dict) -> set[int]:
    ids = {matter["id"]}
    if matter.get("end_user_id"):
        ids |= {m["id"] for m in repo.list_case_matters_for_end_user(matter["end_user_id"], matter.get("tenant_id", 1))}
    return ids


def get_owned_intake_session(repo, session_id: int, matter: dict) -> dict:
    session = repo.get_intake_session_by_id(session_id)
    if session is None or session["matter_id"] not in owned_matter_ids(repo, matter):
        raise HTTPException(status_code=404, detail="Intake session not found.")
    return session


def list_owned_intake_sessions(repo, matter: dict) -> list[dict]:
    sessions = [s for matter_id in owned_matter_ids(repo, matter) for s in repo.list_intake_sessions(matter_id)]
    return sorted(sessions, key=lambda s: (str(s["created_at"]), s["id"]), reverse=True)


def matter_for_new_intake(repo, matter: dict, title: str) -> int:
    """
    The matter a new intake goes into: a new case matter of its own for a
    signed-in client ("one matter per case", Blueprint Phase 4) - or the
    caller's own matter for an access-code caller, or when the
    organization's plan has no room for another matter.
    """

    end_user_id = matter.get("end_user_id")
    if not end_user_id:
        return matter["id"]

    tenant_id = matter.get("tenant_id", 1)
    from app.billing import get_billing_service
    from app.billing.service import RESOURCE_MATTERS, PlanLimitExceededError

    try:
        get_billing_service(repo).check_limit(tenant_id, RESOURCE_MATTERS)
    except PlanLimitExceededError:
        logger.warning("Matter limit reached for tenant %s - intake filed under the client's own matter.", tenant_id)
        return matter["id"]

    account = repo.get_end_user(end_user_id)
    who = account["email"] if account else f"client {end_user_id}"
    # A case matter is never signed into with an access code - its key is random and never shown.
    case = repo.create_case_matter(f"{title} ({who})"[:255], hash_api_key(secrets.token_urlsafe(32)), tenant_id, end_user_id)
    return case["id"]
