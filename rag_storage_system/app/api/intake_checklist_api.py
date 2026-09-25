"""
The owner-editable ancillary checklist for guided intake (Work Plan M5:
"the admin can edit the checklist"). New interviews freeze the active
questions when they start (app/intake_engine/engine.py), so an edit never
shifts the questions under a client who is mid-interview.

The Blueprint's required sweep topics (mandatory_sweep.REQUIRED_CHECKLIST_KEYS)
can be reworded but not switched off or removed. Scoped to the caller's
own organization.

    GET /admin/intake/checklist     the current checklist (the built-in default until saved)
    PUT /admin/intake/checklist     replace it (order = list order)
    DELETE /admin/intake/checklist  back to the built-in default
"""

import re

from fastapi import APIRouter, Depends, HTTPException

from app.api.schemas import IntakeChecklistItem, IntakeChecklistResponse, IntakeChecklistUpdate
from app.intake_engine.mandatory_sweep import REQUIRED_CHECKLIST_KEYS, tenant_checklist
from app.security.auth import require_owner_role

router = APIRouter(prefix="/admin/intake", tags=["intake-checklist"], dependencies=[Depends(require_owner_role)])

MAX_CHECKLIST_QUESTIONS = 30
_KEY_PATTERN = re.compile(r"^[a-z][a-z0-9_]{1,59}$")
# Keys the interview itself uses for other answers - a checklist key must not collide with them.
_RESERVED_KEYS = {
    "client_story", "narrative_summary", "documents_available", "reported_concern", "participated_in_investigation",
    "exercised_legal_right", "date_hired", "date_problem_started", "date_first_complaint", "date_last_day",
}


def _response(repository, tenant_id: int) -> IntakeChecklistResponse:
    saved = bool(repository.get_intake_checklist(tenant_id))
    return IntakeChecklistResponse(
        items=[IntakeChecklistItem(**item) for item in tenant_checklist(repository, tenant_id)],
        customized=saved,
        required_keys=sorted(REQUIRED_CHECKLIST_KEYS),
    )


@router.get("/checklist", response_model=IntakeChecklistResponse)
def get_checklist(owner: dict = Depends(require_owner_role)) -> IntakeChecklistResponse:
    from app.api import storage_api

    return _response(storage_api.metadata_repository, owner["tenant_id"])


@router.put("/checklist", response_model=IntakeChecklistResponse)
def save_checklist(body: IntakeChecklistUpdate, owner: dict = Depends(require_owner_role)) -> IntakeChecklistResponse:
    from app.api import storage_api

    items = body.items
    if not items:
        raise HTTPException(status_code=400, detail="The checklist needs at least one question.")
    if len(items) > MAX_CHECKLIST_QUESTIONS:
        raise HTTPException(status_code=400, detail=f"At most {MAX_CHECKLIST_QUESTIONS} checklist questions.")

    seen = set()
    cleaned = []
    for item in items:
        key = item.key.strip()
        if not _KEY_PATTERN.match(key):
            raise HTTPException(
                status_code=400,
                detail=f"'{key}': a key is 2-60 lowercase letters, digits or underscores, starting with a letter.",
            )
        if key in _RESERVED_KEYS or key.startswith("follow_up_"):
            raise HTTPException(status_code=400, detail=f"'{key}' is used by another part of the interview - pick another key.")
        if key in seen:
            raise HTTPException(status_code=400, detail=f"'{key}' appears twice.")
        seen.add(key)
        prompt_en, prompt_es = item.prompt_en.strip(), item.prompt_es.strip()
        if not prompt_en or not prompt_es:
            raise HTTPException(status_code=400, detail=f"'{key}' needs both the English and the Spanish question.")
        if key in REQUIRED_CHECKLIST_KEYS and not item.is_active:
            raise HTTPException(status_code=400, detail=f"'{key}' is a required topic and can't be switched off.")
        cleaned.append({"key": key, "prompt_en": prompt_en[:1000], "prompt_es": prompt_es[:1000], "is_active": item.is_active})

    missing = REQUIRED_CHECKLIST_KEYS - seen
    if missing:
        raise HTTPException(status_code=400, detail=f"Required topics can't be removed: {', '.join(sorted(missing))}.")

    repository = storage_api.metadata_repository
    repository.replace_intake_checklist(owner["tenant_id"], cleaned, owner.get("email"))
    return _response(repository, owner["tenant_id"])


@router.delete("/checklist", response_model=IntakeChecklistResponse)
def reset_checklist(owner: dict = Depends(require_owner_role)) -> IntakeChecklistResponse:
    from app.api import storage_api

    repository = storage_api.metadata_repository
    repository.replace_intake_checklist(owner["tenant_id"], [], owner.get("email"))
    return _response(repository, owner["tenant_id"])
