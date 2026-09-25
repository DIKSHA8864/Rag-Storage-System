"""
Contract tests for the metadata repository interface
(app/metadata/base.py), run against both implementations:

- SQLiteMetadataRepository - always runs, no external dependency.
- PostgresMetadataRepository - runs against rag_storage_test, a
  separate database on the real docker-compose Postgres server (see
  tests/postgres_test_support.py) if it's reachable, otherwise these
  cases are skipped (not failed) so the suite stays runnable without
  Docker. Never the real rag_storage database - these tests TRUNCATE.

Both backends must satisfy the exact same behavior - that's the point
of the interface - so every test below runs unchanged against
whichever backend the `repo` fixture hands it.
"""

import pytest

from app.metadata.models import DocumentStatus
from app.metadata.sqlite_repository import SQLiteMetadataRepository
from tests.postgres_test_support import TEST_DSN, postgres_reachable


def _make_postgres_repo():
    from app.metadata.postgres_repository import PostgresMetadataRepository

    repo = PostgresMetadataRepository(TEST_DSN)
    # Isolate this test from whatever any other test/run left behind -
    # a real server persists data between tests, unlike a fresh
    # tmp_path SQLite file.
    with repo._connect() as conn:
        conn.execute("TRUNCATE documents, folders RESTART IDENTITY CASCADE")
    return repo


@pytest.fixture(params=["sqlite", "postgres"])
def repo(request, tmp_path):
    if request.param == "sqlite":
        return SQLiteMetadataRepository(tmp_path / "metadata.db")

    if not postgres_reachable():
        pytest.skip("Postgres not reachable at localhost:5432 (docker compose up -d)")

    return _make_postgres_repo()


# ---------------------------------------------------------------------
# Folders
# ---------------------------------------------------------------------


def test_create_folder_also_creates_ancestors(repo):
    repo.create_folder("Contracts/2024/Signed")

    names = {f["name"] for f in repo.list_folders()}
    assert names == {"Contracts", "Contracts/2024", "Contracts/2024/Signed"}


def test_list_folders_reports_document_count_including_descendants(repo):
    repo.create_folder("Contracts/2024")
    repo.upsert_document("Contracts/2024", "a.txt", ".txt", 10, "sha-a")
    repo.upsert_document("Contracts", "b.txt", ".txt", 10, "sha-b")

    counts = {f["name"]: f["document_count"] for f in repo.list_folders()}
    assert counts["Contracts/2024"] == 1
    assert counts["Contracts"] == 2  # includes the nested document


def test_rename_folder_moves_descendant_folders_and_documents(repo):
    repo.create_folder("Contracts/2024")
    repo.upsert_document("Contracts/2024", "a.txt", ".txt", 10, "sha-a")

    repo.rename_folder("Contracts", "Agreements")

    names = {f["name"] for f in repo.list_folders()}
    assert "Agreements" in names
    assert "Agreements/2024" in names
    assert "Contracts" not in names

    documents = repo.list_documents("Agreements/2024")
    assert len(documents) == 1
    assert documents[0]["relative_path"] == "Agreements/2024/a.txt"


def test_delete_folder_cascades_to_documents_and_subfolders(repo):
    repo.create_folder("Contracts/2024")
    repo.upsert_document("Contracts/2024", "a.txt", ".txt", 10, "sha-a")

    repo.delete_folder("Contracts")

    assert repo.list_folders() == []
    assert repo.list_documents() == []


# ---------------------------------------------------------------------
# Documents
# ---------------------------------------------------------------------


def test_upsert_document_then_get(repo):
    repo.upsert_document("Docs", "report.txt", ".txt", 123, "abc123")

    document = repo.get_document("Docs", "report.txt")
    assert document["size"] == 123
    assert document["sha256"] == "abc123"
    assert document["status"] == DocumentStatus.UPLOADED.value


def test_upsert_document_updates_existing_row_in_place(repo):
    repo.upsert_document("Docs", "report.txt", ".txt", 100, "old-hash")
    repo.upsert_document("Docs", "report.txt", ".txt", 200, "new-hash")

    documents = repo.list_documents("Docs")
    assert len(documents) == 1
    assert documents[0]["size"] == 200
    assert documents[0]["sha256"] == "new-hash"


def test_delete_document(repo):
    repo.upsert_document("Docs", "report.txt", ".txt", 10, "abc")
    assert repo.delete_document("Docs", "report.txt") is True
    assert repo.get_document("Docs", "report.txt") is None
    assert repo.delete_document("Docs", "report.txt") is False


def test_list_documents_filters_by_category_including_nested(repo):
    repo.upsert_document("Contracts", "top.txt", ".txt", 10, "a")
    repo.upsert_document("Contracts/2024", "nested.txt", ".txt", 10, "b")
    repo.upsert_document("Other", "other.txt", ".txt", 10, "c")

    names = {d["filename"] for d in repo.list_documents("Contracts")}
    assert names == {"top.txt", "nested.txt"}


def test_update_document_status(repo):
    repo.upsert_document("Docs", "report.txt", ".txt", 10, "abc")
    repo.update_document_status("Docs", "report.txt", DocumentStatus.PROCESSING.value)

    document = repo.get_document("Docs", "report.txt")
    assert document["status"] == DocumentStatus.PROCESSING.value


def test_update_document_status_with_detail_on_failure(repo):
    repo.upsert_document("Docs", "report.txt", ".txt", 10, "abc")
    repo.update_document_status(
        "Docs", "report.txt", DocumentStatus.FAILED.value, status_detail="bad pdf"
    )

    document = repo.get_document("Docs", "report.txt")
    assert document["status"] == DocumentStatus.FAILED.value
    assert document["status_detail"] == "bad pdf"


def test_update_status_where_bulk_transitions(repo):
    repo.upsert_document("Docs", "a.txt", ".txt", 10, "a", status=DocumentStatus.PROCESSING.value)
    repo.upsert_document("Docs", "b.txt", ".txt", 10, "b", status=DocumentStatus.PROCESSING.value)
    repo.upsert_document("Docs", "c.txt", ".txt", 10, "c", status=DocumentStatus.UPLOADED.value)

    updated = repo.update_status_where(
        DocumentStatus.PROCESSING.value, DocumentStatus.INDEXED.value
    )

    assert updated == 2
    statuses = {d["filename"]: d["status"] for d in repo.list_documents("Docs")}
    assert statuses["a.txt"] == DocumentStatus.INDEXED.value
    assert statuses["b.txt"] == DocumentStatus.INDEXED.value
    assert statuses["c.txt"] == DocumentStatus.UPLOADED.value


def test_repository_sees_data_written_by_another_instance(repo, tmp_path):
    """
    Two separate repository instances pointed at the same underlying
    storage must see the same data - a fresh SQLiteMetadataRepository
    re-opening the same file, or a second PostgresMetadataRepository
    connecting to the same live server.
    """

    repo.upsert_document("Docs", "report.txt", ".txt", 10, "abc")

    if isinstance(repo, SQLiteMetadataRepository):
        other = SQLiteMetadataRepository(repo.db_path)
    else:
        from app.metadata.postgres_repository import PostgresMetadataRepository

        other = PostgresMetadataRepository(repo.dsn)

    assert other.get_document("Docs", "report.txt") is not None


# ---------------------------------------------------------------------
# Intake extracted content
# ---------------------------------------------------------------------


@pytest.mark.parametrize("content_type", ["text", "ocr_text", "transcript", "caption", "frame_caption"])
def test_every_extracted_content_type_the_pipeline_produces_can_be_stored(repo, content_type):
    """
    Regression: Postgres' CHECK constraint on extracted_information
    once omitted "frame_caption" (video frame analysis), so every video
    upload failed there while SQLite-only tests stayed green. Runs on
    both backends for exactly that reason.
    """

    import uuid

    matter = repo.create_matter("Intake Matter", f"hash-{uuid.uuid4().hex}")
    session = repo.create_intake_session(matter["id"], "Intake")
    uploaded = repo.create_uploaded_input(
        intake_session_id=session["id"], matter_id=matter["id"], original_filename="clip.mp4",
        stored_category="c", stored_filename="clip.mp4", media_type="video", size=1, sha256=None,
    )

    repo.add_extracted_information(
        uploaded_input_id=uploaded["id"], content_type=content_type, text="[1.5s] A person at a desk.",
        provider="mock", is_mock=True,
    )

    assert [row["content_type"] for row in repo.list_extracted_information(uploaded["id"])] == [content_type]


# ---------------------------------------------------------------------
# Per-organization disclaimer and retrieval settings
# ---------------------------------------------------------------------


def _reset_settings(repo):
    """Postgres persists between tests - clear settings rows and make sure tenant 2 exists."""

    if isinstance(repo, SQLiteMetadataRepository):
        return
    with repo._connect() as conn:
        conn.execute("TRUNCATE tenant_disclaimers, tenant_retrieval_settings")
        conn.execute("DELETE FROM disclaimer")
        conn.execute("DELETE FROM retrieval_settings")
        conn.execute("INSERT INTO tenants (id, name, slug) VALUES (2, 'Second Firm', 'second-firm') ON CONFLICT DO NOTHING")


def test_each_organization_has_its_own_disclaimer_and_retrieval_settings(repo):
    _reset_settings(repo)

    repo.update_disclaimer("Firm two's disclaimer.", updated_by="two@example.com", tenant_id=2)
    repo.update_retrieval_settings(top_k=9, score_threshold=0.45, min_chunks=2, tenant_id=2)

    assert repo.get_disclaimer(tenant_id=1) is None
    assert repo.get_retrieval_settings(tenant_id=1) is None
    assert repo.get_disclaimer(tenant_id=2)["text"] == "Firm two's disclaimer."
    assert repo.get_retrieval_settings(tenant_id=2)["top_k"] == 9

    repo.update_retrieval_settings(top_k=4, score_threshold=0.3, min_chunks=1, tenant_id=1)

    assert repo.get_retrieval_settings(tenant_id=1)["top_k"] == 4
    assert repo.get_retrieval_settings(tenant_id=2)["top_k"] == 9


def test_default_organization_keeps_settings_saved_before_they_were_per_organization(repo):
    _reset_settings(repo)
    with repo._connect() as conn:
        if isinstance(repo, SQLiteMetadataRepository):
            conn.execute("INSERT INTO disclaimer (id, text, updated_at) VALUES (1, 'Saved earlier.', '2026-01-01')")
            conn.execute(
                "INSERT INTO retrieval_settings (id, top_k, score_threshold, min_chunks, updated_at) "
                "VALUES (1, 7, 0.35, 1, '2026-01-01')"
            )
        else:
            conn.execute("INSERT INTO disclaimer (id, text) VALUES (1, 'Saved earlier.')")
            conn.execute("INSERT INTO retrieval_settings (id, top_k, score_threshold, min_chunks) VALUES (1, 7, 0.35, 1)")

    assert repo.get_disclaimer(tenant_id=1)["text"] == "Saved earlier."
    assert repo.get_retrieval_settings(tenant_id=1)["top_k"] == 7
    # ...but another organization never inherits them.
    assert repo.get_disclaimer(tenant_id=2) is None
    assert repo.get_retrieval_settings(tenant_id=2) is None


def test_list_llm_usage_log_is_per_organization_and_decodes_chunk_lists(repo):
    if not isinstance(repo, SQLiteMetadataRepository):
        with repo._connect() as conn:
            conn.execute("TRUNCATE llm_usage_log")
            conn.execute("INSERT INTO tenants (id, name, slug) VALUES (2, 'Second Firm', 'second-firm') ON CONFLICT DO NOTHING")

    repo.add_llm_usage_log(None, None, "owner_research", "claude-opus-5", 100, 20, 900, query_text="q1",
                           retrieved_chunk_ids=["a", "b"], retrieved_chunk_scores=[0.4, 0.6],
                           citation_check_result="grounded", tenant_id=1)
    repo.add_llm_usage_log(None, None, "owner_research", "n/a", 0, 0, 5, query_text="other firm", tenant_id=2)

    rows, total = repo.list_llm_usage_log(1, questions_only=True)

    assert total == 1
    assert rows[0]["query_text"] == "q1"
    assert rows[0]["retrieved_chunk_ids"] == ["a", "b"]
    assert [float(s) for s in rows[0]["retrieved_chunk_scores"]] == [0.4, 0.6]


def test_research_threads_are_per_owner_and_keep_sources(repo):
    if not isinstance(repo, SQLiteMetadataRepository):
        with repo._connect() as conn:
            conn.execute("TRUNCATE research_threads, research_messages RESTART IDENTITY CASCADE")
            conn.execute("INSERT INTO tenants (id, name, slug) VALUES (2, 'Second Firm', 'second-firm') ON CONFLICT DO NOTHING")

    thread = repo.create_research_thread(1, "7", "Discovery")
    repo.add_research_exchange(thread["id"], "Q?", "A [x.pdf].", [{"filename": "x.pdf", "excerpt": "passage"}])

    assert repo.get_research_thread(thread["id"], 1, "8") is None
    assert repo.get_research_thread(thread["id"], 2, "7") is None
    assert [t["message_count"] for t in repo.list_research_threads(1, "7")] == [2]
    messages = repo.list_research_messages(thread["id"])
    assert [m["role"] for m in messages] == ["user", "assistant"]
    assert messages[1]["sources"] == [{"filename": "x.pdf", "excerpt": "passage"}]

    assert repo.rename_research_thread(thread["id"], 1, "8", "hijack") is None
    assert repo.rename_research_thread(thread["id"], 1, "7", "Discovery memo")["title"] == "Discovery memo"
    assert repo.delete_research_thread(thread["id"], 1, "8") is False
    assert repo.delete_research_thread(thread["id"], 1, "7") is True
    assert repo.list_research_messages(thread["id"]) == []


def test_vault_sync_manifest_runs_and_duplicate_lookup(repo):
    if not isinstance(repo, SQLiteMetadataRepository):
        with repo._connect() as conn:
            conn.execute("TRUNCATE vault_sync_manifest, vault_sync_runs RESTART IDENTITY")
            conn.execute("INSERT INTO tenants (id, name, slug) VALUES (2, 'Second Firm', 'second-firm') ON CONFLICT DO NOTHING")

    repo.upsert_document("Harassment", "a.pdf", ".pdf", 10, "sha-a", tenant_id=1)
    assert repo.find_document_by_sha256("sha-a", 1)["filename"] == "a.pdf"
    assert repo.find_document_by_sha256("sha-a", 2) is None

    repo.upsert_vault_manifest(1, "Harassment/a.pdf", "Harassment", "a.pdf", "sha-a", 10, 1700000000.5)
    repo.upsert_vault_manifest(1, "Harassment/a.pdf", "Harassment", "a.pdf", "sha-b", 11, 1700000001.5)
    (row,) = repo.list_vault_manifest(1)
    assert (row["sha256"], row["size"], float(row["mtime"])) == ("sha-b", 11, 1700000001.5)
    assert repo.list_vault_manifest(2) == []
    repo.delete_vault_manifest(1, "Harassment/a.pdf")
    assert repo.list_vault_manifest(1) == []

    base = {"source": "Folder /x", "added": 1, "updated": 0, "deleted": 0, "unchanged": 2, "error": None,
            "started_at": "2026-09-25T00:00:00+00:00"}
    repo.add_vault_sync_run(1, {**base, "status": "ok", "skipped": []})
    repo.add_vault_sync_run(1, {**base, "status": "refused", "skipped": [{"path": "p", "reason": "r"}], "error": "empty"})
    last = repo.latest_vault_sync_run(1)
    assert (last["status"], last["error"], last["skipped"]) == ("refused", "empty", [{"path": "p", "reason": "r"}])
    assert repo.latest_vault_sync_run(2) is None


def test_interview_extras_and_intake_checklist(repo):
    if not isinstance(repo, SQLiteMetadataRepository):
        with repo._connect() as conn:
            conn.execute("TRUNCATE intake_checklist_questions RESTART IDENTITY")
            conn.execute("INSERT INTO tenants (id, name, slug) VALUES (2, 'Second Firm', 'second-firm') ON CONFLICT DO NOTHING")

    import uuid

    matter = repo.create_matter(f"Flow v2 {uuid.uuid4().hex[:8]}", uuid.uuid4().hex)
    session = repo.create_intake_session(matter_id=matter["id"], title="Intake")
    repo.create_interview_state(session["id"])
    assert repo.get_interview_state(session["id"])["flow_version"] == 1  # rows from before flow 2 read as flow 1

    snapshot = [{"key": "overtime", "prompt_en": "OT?", "prompt_es": "Horas extra?"}]
    repo.set_interview_extras(session["id"], flow_version=2, checklist_snapshot=snapshot)
    repo.set_interview_extras(session["id"], terms_accepted_ip="203.0.113.7", follow_up_questions=[])
    state = repo.get_interview_state(session["id"])
    assert (state["flow_version"], state["terms_accepted_ip"]) == (2, "203.0.113.7")
    assert state["checklist_snapshot"] == snapshot
    assert state["follow_up_questions"] == []  # "generated, none" - distinct from never generated (None)

    items = [
        {"key": "overtime", "prompt_en": "OT?", "prompt_es": "Horas extra?", "is_active": True},
        {"key": "tips", "prompt_en": "Tips?", "prompt_es": "Propinas?", "is_active": False},
    ]
    saved = repo.replace_intake_checklist(1, items, "owner@example.com")
    assert [(r["key"], bool(r["is_active"])) for r in saved] == [("overtime", True), ("tips", False)]
    assert repo.get_intake_checklist(2) == []
    repo.replace_intake_checklist(1, list(reversed(items)), None)
    assert [r["key"] for r in repo.get_intake_checklist(1)] == ["tips", "overtime"]
    repo.replace_intake_checklist(1, [], None)
    assert repo.get_intake_checklist(1) == []


def test_case_matters_and_matter_documents(repo):
    import uuid
    from datetime import datetime, timezone

    if not isinstance(repo, SQLiteMetadataRepository):
        with repo._connect() as conn:
            conn.execute("TRUNCATE matter_documents RESTART IDENTITY")

    personal = repo.create_matter(f"Personal {uuid.uuid4().hex[:6]}", uuid.uuid4().hex)
    email = f"case-test-{uuid.uuid4().hex[:6]}@example.com"
    account = repo.create_end_user_invite(email, 1, None)
    repo.activate_end_user(account["id"], "hash", personal["id"], datetime.now(timezone.utc).isoformat())

    case = repo.create_case_matter("Overtime (x)", uuid.uuid4().hex, 1, account["id"])
    assert (case["kind"], case["end_user_id"]) == ("case", account["id"])
    assert repo.get_matter(personal["id"])["kind"] == "client"
    assert [m["id"] for m in repo.list_case_matters_for_end_user(account["id"], 1)] == [case["id"]]
    assert repo.list_case_matters_for_end_user(account["id"], 2) == []
    emails = {m["id"]: m["client_email"] for m in repo.list_matters_with_clients(1)}
    assert emails[case["id"]] == emails[personal["id"]] == email

    doc = repo.create_matter_document(1, case["id"], "pleading", "complaint.pdf", "matter_1/case_documents",
                                      "complaint.pdf", 10, "sha", "owner@example.com")
    assert (doc["status"], doc["chunk_count"]) == ("queued", 0)
    repo.update_matter_document_status(doc["id"], "indexed", 4)
    assert repo.get_matter_document(doc["id"], case["id"])["chunk_count"] == 4
    assert repo.get_matter_document(doc["id"], personal["id"]) is None
    assert [d["id"] for d in repo.list_matter_documents(case["id"])] == [doc["id"]]
    assert repo.delete_matter_document(doc["id"], personal["id"]) is False
    assert repo.delete_matter_document(doc["id"], case["id"]) is True
    assert repo.list_matter_documents(case["id"]) == []


def test_pleading_settings_and_document_templates(repo):
    if not isinstance(repo, SQLiteMetadataRepository):
        with repo._connect() as conn:
            conn.execute("TRUNCATE tenant_pleading_settings, document_templates RESTART IDENTITY")
            conn.execute("INSERT INTO tenants (id, name, slug) VALUES (2, 'Second Firm', 'second-firm') ON CONFLICT DO NOTHING")

    assert repo.get_pleading_settings(1) is None
    repo.save_pleading_settings(1, {"attorney_name": "Jane", "county": "Los Angeles"}, "owner@example.com")
    saved = repo.save_pleading_settings(1, {"attorney_name": "Jane Q.", "bar_number": "123"}, "owner2@example.com")
    assert (saved["attorney_name"], saved["bar_number"], saved["county"], saved["updated_by"]) == ("Jane Q.", "123", "", "owner2@example.com")
    assert repo.get_pleading_settings(2) is None

    template = repo.create_document_template(1, "Firm", "complaint", "firm.docx", "templates/tenant-1", "firm.docx",
                                             ["body", "plaintiff"], "owner@example.com")
    assert template["placeholders"] == ["body", "plaintiff"]
    assert [t["id"] for t in repo.list_document_templates(1, "complaint")] == [template["id"]]
    assert repo.list_document_templates(2) == []
    assert repo.get_document_template(template["id"], 2) is None
    assert repo.delete_document_template(template["id"], 2) is False
    assert repo.delete_document_template(template["id"], 1) is True


def test_analytics_queries(repo):
    import uuid
    from datetime import datetime, timezone

    if not isinstance(repo, SQLiteMetadataRepository):
        with repo._connect() as conn:
            conn.execute("TRUNCATE llm_usage_log")
            conn.execute("INSERT INTO tenants (id, name, slug) VALUES (2, 'Second Firm', 'second-firm') ON CONFLICT DO NOTHING")
    since = datetime(2000, 1, 1, tzinfo=timezone.utc).isoformat()
    before = repo.intake_funnel_counts(1, since)

    repo.add_llm_usage_log(None, None, "owner_research", "m", 5, 1, 10, query_text="q", retrieved_chunk_ids=["a"],
                           retrieved_chunk_scores=[0.5], citation_check_result="grounded", tenant_id=1)
    repo.add_llm_usage_log(None, None, "relevance_filter", "m", 5, 1, 10, tenant_id=1)
    rows = repo.list_llm_usage_since(1, since)
    assert [(r["is_question"], r["retrieved_chunk_ids"]) for r in rows] == [(True, ["a"]), (False, [])]
    assert repo.list_llm_usage_since(2, since) == []

    matter = repo.create_matter(f"Analytics {uuid.uuid4().hex[:6]}", uuid.uuid4().hex)
    session = repo.create_intake_session(matter["id"], "A")
    repo.create_interview_state(session["id"])
    after = repo.intake_funnel_counts(1, since)
    assert after["sessions"] == before["sessions"] + 1
    assert after["interviews_started"] == before["interviews_started"] + 1
    assert set(after) >= {"reports_approved", "intake_uploads", "case_documents"}


def test_payment_provider_sync(repo):
    import uuid

    if not isinstance(repo, SQLiteMetadataRepository):
        with repo._connect() as conn:
            conn.execute("TRUNCATE billing_provider_events")
            conn.execute("INSERT INTO tenants (id, name, slug) VALUES (2, 'Second Firm', 'second-firm') ON CONFLICT DO NOTHING")
            conn.execute("DELETE FROM tenant_subscriptions WHERE tenant_id = 2")

    plan = repo.create_plan(slug=f"pro-{uuid.uuid4().hex[:6]}", name="Pro", price_cents=900)
    price = f"price_{uuid.uuid4().hex[:8]}"
    assert repo.set_plan_provider_price(plan["id"], price)["provider_price_id"] == price
    assert repo.get_plan_by_provider_price(price)["id"] == plan["id"]

    sub_id = f"sub_{uuid.uuid4().hex[:8]}"
    synced = repo.sync_provider_subscription(2, plan["id"], "active", "2026-09-01T00:00:00+00:00",
                                             "2026-10-01T00:00:00+00:00", "stripe", "cus_1", sub_id)
    assert (synced["plan_id"], synced["status"], synced["provider_subscription_id"]) == (plan["id"], "active", sub_id)
    again = repo.sync_provider_subscription(2, plan["id"], "past_due", "2026-09-01T00:00:00+00:00",
                                            "2026-10-01T00:00:00+00:00", "stripe", "cus_1", sub_id)
    assert again["status"] == "past_due" and again["id"] == synced["id"]
    assert repo.get_subscription_by_provider_id(sub_id)["tenant_id"] == 2

    event = f"evt_{uuid.uuid4().hex[:8]}"
    assert repo.record_provider_event(event, "stripe", "invoice.paid", 2) is True
    assert repo.record_provider_event(event, "stripe", "invoice.paid", 2) is False
