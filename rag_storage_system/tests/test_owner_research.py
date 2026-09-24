"""
Tests for POST /research/ask (app/api/storage_api.py's owner_research_ask())
- the Owner/Attorney/Paralegal-scope equivalent of the End User's
POST /end-user/query/stream real answer, reusing the exact same
shared function (app/analysis/answer_generation.py's
stream_grounded_answer()) rather than a second implementation.

Covers Step 2 of the audit follow-up: real retrieval, real Claude-or-
template answer generation, code-enforced citation grounding, honest-
gap refusal, role-based access, and library-only (never Matter-scoped)
isolation - all through the real HTTP surface with a real JWT, not a
bypassed/mocked auth dependency.
"""

import asyncio
from dataclasses import dataclass
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app.api import storage_api
from app.metadata.sqlite_repository import SQLiteMetadataRepository
from app.security.auth import create_access_token, require_admin_key, require_end_user_key
from config.settings import get_settings


@pytest.fixture
def repo(tmp_path):
    return SQLiteMetadataRepository(tmp_path / "metadata.db")


@pytest.fixture
def client(monkeypatch, repo):
    # Real auth, not the autouse bypass - these tests exist specifically
    # to prove authentication/authorization on this endpoint, the same
    # convention as tests/test_auth.py and tests/test_matter_workspace.py.
    storage_api.app.dependency_overrides.pop(require_admin_key, None)
    storage_api.app.dependency_overrides.pop(require_end_user_key, None)

    monkeypatch.setattr(storage_api, "metadata_repository", repo)

    yield TestClient(storage_api.app)

    storage_api.app.dependency_overrides.pop(require_admin_key, None)
    storage_api.app.dependency_overrides.pop(require_end_user_key, None)


def _owner_header(owner_id: int = 1, role: str = "owner") -> dict:
    token = create_access_token(owner_id=owner_id, email=f"user{owner_id}@example.com", role=role)
    return {"Authorization": f"Bearer {token}"}


def _hit(filename: str, category: str, score: float) -> dict:
    return {
        "chunk_id": "c-1", "document_id": "doc", "category": category, "filename": filename,
        "chunk_text": "Overtime must be paid at 1.5x for hours over 40 in a week.",
        "section": "2.1", "start_page": 1, "end_page": 1, "final_score": score,
    }


@dataclass
class _FakeClaudeSettings:
    narrative_provider: str = "claude"
    anthropic_api_key: str = "test-key"
    analysis_model: str = "claude-opus-5"


class _FakeAsyncMessages:
    def __init__(self, response_text: str):
        self._response_text = response_text
        self.last_call: dict | None = None

    async def create(self, **kwargs):
        self.last_call = kwargs
        block = SimpleNamespace(type="text", text=self._response_text)
        return SimpleNamespace(content=[block])


def _fake_async_anthropic(response_text: str):
    fake_messages = _FakeAsyncMessages(response_text)

    class _FakeAsyncAnthropic:
        def __init__(self, api_key=None):
            self.messages = fake_messages

    return _FakeAsyncAnthropic, fake_messages


def _fake_relevance_client(response_text: str):
    """A fake SYNCHRONOUS anthropic.Anthropic client, for app/analysis/relevance_guard.py's relevance-classification call (separate from the async generation client above)."""

    block = SimpleNamespace(type="text", text=response_text)
    usage = SimpleNamespace(input_tokens=5, output_tokens=5)
    response = SimpleNamespace(content=[block], usage=usage)

    class _FakeMessages:
        def create(self, **kwargs):
            return response

    return SimpleNamespace(messages=_FakeMessages())


# ---------------------------------------------------------------------
# 1/3. Authenticated Owner asks a real question and gets grounded citations
# ---------------------------------------------------------------------


def test_authenticated_owner_can_ask_a_real_library_question_and_gets_grounded_citations(client, monkeypatch):
    monkeypatch.setattr(
        storage_api, "retrieve",
        lambda query, top_k, category=None, score_threshold=0.0, tenant_id=1: [_hit("overtime_policy.pdf", "Wage & Hour", 0.9)],
    )

    response = client.post(
        "/research/ask", json={"query": "Is overtime required after 40 hours?"}, headers=_owner_header()
    )

    assert response.status_code == 200
    body = response.json()
    assert body["query"] == "Is overtime required after 40 hours?"
    assert body["answer"].strip() != ""
    assert body["sources"] == [
        {
            "filename": "overtime_policy.pdf", "category": "Wage & Hour", "section": "2.1",
            "start_page": 1, "end_page": 1, "score": 0.9,
        }
    ]
    # Citation lock: every source traces to exactly what retrieve() returned.
    assert {s["filename"] for s in body["sources"]} == {"overtime_policy.pdf"}


# ---------------------------------------------------------------------
# 2. The real Claude path (not just the template fallback) is reachable
# ---------------------------------------------------------------------


def test_owner_receives_a_real_llm_generated_answer_via_the_existing_claude_path(client, monkeypatch):
    monkeypatch.setattr(
        storage_api, "retrieve",
        lambda query, top_k, category=None, score_threshold=0.0, tenant_id=1: [_hit("overtime_policy.pdf", "Wage & Hour", 0.9)],
    )
    monkeypatch.setattr("app.analysis.answer_generation.get_settings", lambda: _FakeClaudeSettings())

    grounded_text = "Overtime is required after 40 hours per week [overtime_policy.pdf]."
    fake_client_cls, fake_messages = _fake_async_anthropic(grounded_text)
    monkeypatch.setattr("anthropic.AsyncAnthropic", fake_client_cls)

    response = client.post(
        "/research/ask", json={"query": "Is overtime required after 40 hours?"}, headers=_owner_header()
    )

    assert response.status_code == 200
    body = response.json()
    assert fake_messages.last_call is not None  # proves the real Claude call actually executed
    assert "Overtime is required after 40 hours" in body["answer"]
    assert "[overtime_policy.pdf]" in body["answer"]


# ---------------------------------------------------------------------
# 4. Honest-gap: unsupported questions are refused, never guessed at
# ---------------------------------------------------------------------


def test_unsupported_question_triggers_honest_gap_behavior(client, monkeypatch):
    monkeypatch.setattr(storage_api, "retrieve", lambda query, top_k, category=None, score_threshold=0.0, tenant_id=1: [])

    response = client.post(
        "/research/ask", json={"query": "What is the capital of France?"}, headers=_owner_header()
    )

    assert response.status_code == 200
    body = response.json()
    assert body["answer"] == "No authority on this point was found in the firm's legal library."
    assert body["sources"] == []


# ---------------------------------------------------------------------
# 4b. Relevance gate: retrieved chunks that only share vocabulary with
# the question (a CGL/D&O/Workers' Comp/defamation document, say) must
# never become "supporting" sources or reach the answer generator -
# see app/analysis/relevance_guard.py.
# ---------------------------------------------------------------------


def _cgl_exclusion_hit() -> dict:
    return _hit(
        "cgl_policy_exclusions.pdf", "Insurance",
        # score_threshold=0.0 is what these tests pass into the fake
        # retrieve() anyway (see its lambda signature) - final_score
        # here just needs to be a plausible "retrieval thought this was
        # worth returning" value, exactly like a real, keyword-matched
        # but topically unrelated chunk would get.
        0.42,
    )


def test_a_loosely_keyword_matched_but_unrelated_document_never_becomes_a_source(client, monkeypatch):
    """
    Reproduces the reported bug: retrieval surfaces only a CGL policy's
    exclusions clause (it happens to mention "employment", "termination",
    "discrimination", "complaint") for an employment discrimination
    question. The relevance gate must recognize it as NOT materially
    relevant and refuse to answer, rather than generating a substantive
    answer "grounded" in an unrelated insurance document.
    """

    monkeypatch.setattr(
        storage_api, "retrieve",
        lambda query, top_k, category=None, score_threshold=0.0, tenant_id=1: [_cgl_exclusion_hit()],
    )
    monkeypatch.setattr(
        "app.analysis.relevance_guard.get_settings",
        lambda: SimpleNamespace(anthropic_api_key="test-key", analysis_model="claude-opus-5"),
    )
    monkeypatch.setattr("anthropic.Anthropic", lambda api_key: _fake_relevance_client("[]"))

    response = client.post(
        "/research/ask",
        json={"query": "Can an employee be fired for filing a discrimination complaint?"},
        headers=_owner_header(),
    )

    assert response.status_code == 200
    body = response.json()
    assert body["answer"] == "No authority on this point was found in the firm's legal library."
    assert body["sources"] == []
    assert "cgl_policy_exclusions.pdf" not in str(body)


def test_relevant_source_is_kept_and_the_unrelated_one_is_dropped_before_generation(client, monkeypatch):
    """The generator must never even SEE the excluded chunk - proves filtering happens before generation, not just before citation display."""

    relevant_hit = _hit("employment_handbook.pdf", "HR Policy", 0.85)
    monkeypatch.setattr(
        storage_api, "retrieve",
        lambda query, top_k, category=None, score_threshold=0.0, tenant_id=1: [relevant_hit, _cgl_exclusion_hit()],
    )
    monkeypatch.setattr(
        "app.analysis.relevance_guard.get_settings",
        lambda: SimpleNamespace(anthropic_api_key="test-key", analysis_model="claude-opus-5"),
    )
    # Only index 0 (the employment handbook) is materially relevant.
    monkeypatch.setattr("anthropic.Anthropic", lambda api_key: _fake_relevance_client("[0]"))
    monkeypatch.setattr("app.analysis.answer_generation.get_settings", lambda: _FakeClaudeSettings())

    grounded_text = "An employee may be terminated only for lawful reasons [employment_handbook.pdf]."
    fake_client_cls, fake_messages = _fake_async_anthropic(grounded_text)
    monkeypatch.setattr("anthropic.AsyncAnthropic", fake_client_cls)

    response = client.post(
        "/research/ask",
        json={"query": "Can an employee be fired for filing a discrimination complaint?"},
        headers=_owner_header(),
    )

    assert response.status_code == 200
    body = response.json()
    assert body["sources"] == [
        {
            "filename": "employment_handbook.pdf", "category": "HR Policy", "section": "2.1",
            "start_page": 1, "end_page": 1, "score": 0.85,
        }
    ]
    # The excluded chunk's text never reached the generator's prompt.
    sent_prompt = str(fake_messages.last_call)
    assert "cgl_policy_exclusions.pdf" not in sent_prompt


# ---------------------------------------------------------------------
# 5. Ungrounded/fabricated citations are rejected, not returned
# ---------------------------------------------------------------------


def test_fabricated_citation_is_rejected_and_falls_back_to_the_grounded_template_answer(client, monkeypatch):
    monkeypatch.setattr(
        storage_api, "retrieve",
        lambda query, top_k, category=None, score_threshold=0.0, tenant_id=1: [_hit("overtime_policy.pdf", "Wage & Hour", 0.9)],
    )
    monkeypatch.setattr("app.analysis.answer_generation.get_settings", lambda: _FakeClaudeSettings())

    fabricated_text = "According to [made_up_case_law.pdf], overtime is not required."
    fake_client_cls, fake_messages = _fake_async_anthropic(fabricated_text)
    monkeypatch.setattr("anthropic.AsyncAnthropic", fake_client_cls)

    response = client.post(
        "/research/ask", json={"query": "Is overtime required after 40 hours?"}, headers=_owner_header()
    )

    assert response.status_code == 200
    body = response.json()
    # The fabricated citation/text must never reach the client...
    assert "made_up_case_law.pdf" not in body["answer"]
    assert fabricated_text not in body["answer"]
    # ...it's discarded entirely; the real, retrieved source is still cited.
    assert body["sources"][0]["filename"] == "overtime_policy.pdf"
    assert "made_up_case_law.pdf" not in {s["filename"] for s in body["sources"]}


# ---------------------------------------------------------------------
# 6. Unauthorized callers cannot reach Owner research
# ---------------------------------------------------------------------


def test_request_without_any_token_is_rejected(client):
    response = client.post("/research/ask", json={"query": "Is overtime required?"})
    assert response.status_code == 401


def test_request_with_an_invalid_token_is_rejected(client):
    response = client.post(
        "/research/ask", json={"query": "Is overtime required?"},
        headers={"Authorization": "Bearer not-a-real-token"},
    )
    assert response.status_code == 401


def test_end_user_key_does_not_grant_owner_research_access(client):
    end_user_key = get_settings().end_user_api_key

    response = client.post(
        "/research/ask", json={"query": "Is overtime required?"},
        headers={"X-End-User-Key": end_user_key},
    )
    assert response.status_code == 401


def test_attorney_and_paralegal_roles_can_access_owner_research(client, monkeypatch):
    """
    Owner research isn't Matter-scoped, so any authenticated staff role
    (owner/attorney/paralegal) may use it - the same role set
    require_admin_key already accepts everywhere else.
    """

    monkeypatch.setattr(
        storage_api, "retrieve",
        lambda query, top_k, category=None, score_threshold=0.0, tenant_id=1: [_hit("policy.pdf", "HR", 0.9)],
    )

    for role in ("attorney", "paralegal"):
        response = client.post(
            "/research/ask", json={"query": "wage policy"}, headers=_owner_header(role=role)
        )
        assert response.status_code == 200, role


# ---------------------------------------------------------------------
# 7. Matter isolation: never scoped to a Matter's namespace
# ---------------------------------------------------------------------


def test_matter_scoped_documents_do_not_leak_into_owner_research(client, monkeypatch):
    """
    The Owner research endpoint must call the library-wide retrieve()
    (which already excludes every "matter-<id>" namespace - see
    app/vector_store/vector_repository.py and
    tests/test_matter_rag.py::test_library_wide_search_excludes_every_matter_namespace)
    - never retrieve_for_matter() - so no Matter's uploaded documents
    can ever reach this Owner-scope endpoint, exactly like POST /search.
    """

    captured_calls = []

    def _fake_retrieve(query, top_k, category=None, score_threshold=0.0, tenant_id=1):
        captured_calls.append(category)
        return [_hit("library_policy.pdf", "HR", 0.9)]

    monkeypatch.setattr(storage_api, "retrieve", _fake_retrieve)

    response = client.post("/research/ask", json={"query": "wage policy"}, headers=_owner_header())

    assert response.status_code == 200
    assert captured_calls  # retrieve() was actually called
    assert all(category is None or not category.startswith("matter-") for category in captured_calls)
    assert response.json()["sources"][0]["filename"] == "library_policy.pdf"


# ---------------------------------------------------------------------
# 8. Existing End-User RAG behavior is unaffected - same shared function
# ---------------------------------------------------------------------


def test_owner_and_end_user_paths_share_the_exact_same_answer_generation_function():
    """
    Proves there is no second implementation: both scopes call the
    identical stream_grounded_answer object from
    app/analysis/answer_generation.py.
    """

    from app.analysis.answer_generation import stream_grounded_answer as shared_fn
    from app.api.end_user_api import stream_grounded_answer as end_user_ref
    from app.api.storage_api import stream_grounded_answer as owner_ref

    assert end_user_ref is shared_fn
    assert owner_ref is shared_fn


def test_search_endpoint_still_works_unchanged(client, monkeypatch):
    """POST /search (raw chunks, no LLM) must remain available and unmodified."""

    monkeypatch.setattr(
        storage_api, "retrieve",
        lambda query, top_k, category=None, tenant_id=1: [
            {
                "chunk_id": "c-1", "document_id": "doc", "category": "HR", "filename": "policy.pdf",
                "chunk_text": "text", "vector_score": 0.8, "keyword_score": 0.5, "final_score": 0.9,
            }
        ],
    )

    response = client.post("/search", json={"query": "policy"}, headers=_owner_header())

    assert response.status_code == 200
    body = response.json()
    assert body["results"][0]["filename"] == "policy.pdf"
    assert "answer" not in body  # /search still returns raw chunks only, no generated answer
