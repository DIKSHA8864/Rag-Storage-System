"""
The dashboard's "Today" panel: what needs the firm's attention since the
start of the viewer's day - new client intakes, reports waiting for
review, open "Talk to a person" requests, questions the library couldn't
answer, and uploads.

    GET /admin/today?since=<ISO timestamp of the viewer's local midnight>

The browser sends its own midnight so "today" means the viewer's day, not
the server's. Everything is the caller's organization only; an attorney
or paralegal sees only the matters assigned to them (same rule as
ensure_matter_access). Counts come from records the system already keeps.
"""

from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query

from app.api.schemas import TodayIntakeInfo, TodayResponse
from app.security.auth import ensure_matter_access, require_admin_key

router = APIRouter(prefix="/admin", tags=["today"], dependencies=[Depends(require_admin_key)])

HONEST_GAP = "insufficient_evidence"


def can_see_matter(owner: dict, matter_id: int, repo) -> bool:
    """Whether `owner` may see this matter's records - the tenant check included."""

    if not matter_id:
        # The legacy implicit "Default" matter belongs to the first organization only.
        return owner.get("role") == "owner" and int(owner.get("tenant_id", 1)) == 1
    try:
        ensure_matter_access(owner, matter_id, repo)
    except HTTPException:
        return False
    return True


def _as_utc(value) -> Optional[datetime]:
    if value is None:
        return None
    if isinstance(value, datetime):
        moment = value
    else:
        try:
            moment = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except ValueError:
            return None
    return moment if moment.tzinfo else moment.replace(tzinfo=timezone.utc)


def _resolve_since(since: Optional[str]) -> datetime:
    now = datetime.now(timezone.utc)
    moment = _as_utc(since) if since else None
    # Anything missing, in the future, or older than two days falls back to the server's midnight.
    if moment is None or moment > now or moment < now - timedelta(days=2):
        return now.replace(hour=0, minute=0, second=0, microsecond=0)
    return moment.astimezone(timezone.utc)


@router.get("/today", response_model=TodayResponse)
def today(since: Optional[str] = Query(None), owner: dict = Depends(require_admin_key)) -> TodayResponse:
    from app.api import storage_api

    repo = storage_api.metadata_repository
    tenant_id = owner["tenant_id"]
    start = _resolve_since(since)
    since_text = start.isoformat()

    new_intakes: list[TodayIntakeInfo] = []
    for matter in repo.list_matters_with_clients(tenant_id):
        if not can_see_matter(owner, matter["id"], repo):
            continue
        for session in repo.list_intake_sessions(matter["id"]):
            created = _as_utc(session["created_at"])
            if created is None or created < start:
                continue
            state = repo.get_interview_state(session["id"])
            new_intakes.append(TodayIntakeInfo(
                intake_session_id=session["id"], matter_id=matter["id"], matter_name=matter["name"],
                client_email=matter.get("client_email"), title=session["title"],
                stage=(state or {}).get("current_state") or "not_started", created_at=str(session["created_at"]),
            ))
    new_intakes.sort(key=lambda item: item.created_at, reverse=True)

    questions = [r for r in repo.list_llm_usage_since(tenant_id, since_text) if r["is_question"]]

    reports_pending = 0
    for review in repo.list_report_reviews(status="pending_review"):
        report = repo.get_report(review["report_id"])
        if report is not None and can_see_matter(owner, report["matter_id"], repo):
            reports_pending += 1

    handoffs = repo.list_handoff_requests(tenant_id)
    library_uploads = 0
    for document in repo.list_documents(tenant_id=tenant_id):
        uploaded = _as_utc(document.get("created_at"))
        if uploaded is not None and uploaded >= start:
            library_uploads += 1
    funnel = repo.intake_funnel_counts(tenant_id, since_text)

    return TodayResponse(
        since=since_text,
        new_intakes=new_intakes,
        intakes_started=len(new_intakes),
        intakes_completed=sum(1 for item in new_intakes if item.stage == "complete"),
        questions_asked=len(questions),
        no_authority=sum(1 for r in questions if r["citation_check_result"] == HONEST_GAP),
        reports_pending=reports_pending,
        requests_open=sum(1 for h in handoffs if h["status"] == "open"),
        requests_claimed=sum(1 for h in handoffs if h["status"] == "claimed"),
        library_uploads=library_uploads,
        case_documents=funnel.get("case_documents", 0),
        client_uploads=funnel.get("intake_uploads", 0),
    )
