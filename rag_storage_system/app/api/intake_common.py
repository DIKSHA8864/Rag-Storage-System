"""
Small helper shared between app/api/intake_api.py (uploads/reports)
and app/api/interview_api.py (the Guided Intake Engine) - both are
Matter-scoped the same way app/api/end_user_api.py's threads are.
"""

from fastapi import HTTPException


def get_owned_intake_session(repo, session_id: int, matter: dict) -> dict:
    session = repo.get_intake_session(session_id, matter["id"])
    if session is None:
        raise HTTPException(status_code=404, detail="Intake session not found.")
    return session