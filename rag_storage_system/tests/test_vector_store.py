"""
Tests for the vector store interface (app/vector_store/base.py),
against the real implementation (PgVectorRepository, pgvector on
Postgres - app/vector_store/vector_repository.py).

Runs against rag_storage_test, a separate database on the real
docker-compose Postgres server (now pgvector/pgvector:pg16, not plain
postgres:16 - see its comment in docker-compose.yml; and see
tests/postgres_test_support.py for why a separate database) if it's
reachable, otherwise every test here is skipped (not failed), the same
convention tests/test_metadata_repository.py uses for its Postgres
cases - there is no in-memory/sqlite alternative for pgvector, so
unlike that file this one has only one backend to test. Never the
real rag_storage database - these tests TRUNCATE chunk_embeddings.

Uses the real embedding model (not mocked) so similarity_search()'s
ranking is a genuine nearest-neighbor result, not a stand-in - the
whole point of these tests is confirming pgvector returns something
sensible for a real query (see the project's step "Test similarity
search works at all" before building retrieval on top of it).
"""

import pytest

from app.embeddings.embedding_manager import embed_texts
from tests.postgres_test_support import TEST_DSN, postgres_reachable


@pytest.fixture
def repo():
    if not postgres_reachable():
        pytest.skip("Postgres not reachable at localhost:5432 (docker compose up -d)")

    from app.vector_store.vector_repository import PgVectorRepository

    repository = PgVectorRepository(TEST_DSN)
    # Isolate this test from whatever any other test/run left behind -
    # a real server persists data between tests.
    with repository._connect() as conn:
        conn.execute("TRUNCATE chunk_embeddings RESTART IDENTITY")
    return repository


def _seed(repo, texts: list[str], category: str = "Docs") -> None:
    embeddings = embed_texts(texts)

    for index, (text, embedding) in enumerate(zip(texts, embeddings)):
        repo.upsert_chunk_embedding(
            chunk_id=f"{category}-chunk-{index}",
            document_id="doc",
            category=category,
            filename="doc.txt",
            chunk_text=text,
            embedding=embedding,
            model_name="all-MiniLM-L6-v2",
        )


# ---------------------------------------------------------------------
# upsert_chunk_embedding / count
# ---------------------------------------------------------------------


def test_upsert_then_count(repo):
    _seed(repo, ["The quarterly report covers vendor risk assessments."])
    assert repo.count() == 1


def test_upsert_same_chunk_id_replaces_in_place(repo):
    embedding = embed_texts(["first version"])[0]
    repo.upsert_chunk_embedding(
        chunk_id="c-1", document_id="doc", category="Docs", filename="doc.txt",
        chunk_text="first version", embedding=embedding, model_name="all-MiniLM-L6-v2",
    )
    repo.upsert_chunk_embedding(
        chunk_id="c-1", document_id="doc", category="Docs", filename="doc.txt",
        chunk_text="second version", embedding=embedding, model_name="all-MiniLM-L6-v2",
    )

    assert repo.count() == 1
    [result] = repo.similarity_search(embedding, top_k=1)
    assert result["chunk_text"] == "second version"


# ---------------------------------------------------------------------
# similarity_search - the actual nearest-neighbor sanity check
# ---------------------------------------------------------------------


def test_similarity_search_ranks_the_closest_chunk_first(repo):
    _seed(
        repo,
        [
            "The vendor risk assessment policy requires annual review of third-party contracts.",
            "Employees may request remote work arrangements through their manager.",
            "The office cafeteria menu changes weekly on Mondays.",
        ],
    )

    query_embedding = embed_texts(["What is the policy on reviewing vendor contracts?"])[0]
    results = repo.similarity_search(query_embedding, top_k=3)

    assert len(results) == 3
    assert results[0]["chunk_text"].startswith("The vendor risk assessment policy")
    # Nearest-first ordering.
    assert results[0]["score"] >= results[1]["score"] >= results[2]["score"]


def test_similarity_search_filters_by_category(repo):
    _seed(repo, ["A chunk about contracts."], category="Contracts")
    _seed(repo, ["A chunk about HR policy."], category="HR")

    results = repo.similarity_search(
        embed_texts(["contracts"])[0], top_k=5, category="Contracts"
    )

    assert len(results) == 1
    assert results[0]["category"] == "Contracts"


def test_similarity_search_category_filter_includes_subfolders(repo):
    _seed(repo, ["A nested contract chunk."], category="Contracts/2024")

    results = repo.similarity_search(
        embed_texts(["contract"])[0], top_k=5, category="Contracts"
    )

    assert len(results) == 1
    assert results[0]["category"] == "Contracts/2024"


# ---------------------------------------------------------------------
# keyword_search
# ---------------------------------------------------------------------


def test_keyword_search_matches_literal_text(repo):
    _seed(
        repo,
        [
            "Invoice number INV-90210 was submitted for reimbursement.",
            "General onboarding information for new employees.",
        ],
    )

    results = repo.keyword_search("INV-90210", top_k=5)

    assert len(results) == 1
    assert "INV-90210" in results[0]["chunk_text"]


def test_keyword_search_no_match_returns_empty(repo):
    _seed(repo, ["Nothing relevant here."])
    assert repo.keyword_search("zzz_no_such_term_zzz", top_k=5) == []


# ---------------------------------------------------------------------
# Keeping the index in step with the library (delete / replace / rename /
# full re-index sweep). Fixed vectors - these test the SQL, not ranking.
# ---------------------------------------------------------------------


def _put(repo, chunk_id, category, filename="doc.txt", tenant_id=1):
    repo.upsert_chunk_embedding(
        chunk_id=chunk_id, document_id=chunk_id.rsplit("-", 1)[0], category=category, filename=filename,
        chunk_text=f"text of {chunk_id}", embedding=[0.1] * 384, model_name="test", tenant_id=tenant_id,
    )


def _chunk_categories(repo) -> dict[str, str]:
    with repo._connect() as conn:
        return {r["chunk_id"]: r["category"] for r in conn.execute("SELECT chunk_id, category FROM chunk_embeddings")}


def test_delete_document_chunks_removes_only_that_file_in_that_tenant(repo):
    _put(repo, "a-1", "Harassment", "discovery.pdf")
    _put(repo, "a-2", "Harassment", "discovery.pdf")
    _put(repo, "b-1", "Harassment", "evidence.pdf")
    _put(repo, "c-1", "Harassment", "discovery.pdf", tenant_id=2)
    _put(repo, "m-1", "matter-4", "discovery.pdf")

    assert repo.delete_document_chunks("Harassment", "discovery.pdf", tenant_id=1) == 2
    assert set(_chunk_categories(repo)) == {"b-1", "c-1", "m-1"}


def test_folder_operations_match_the_folder_literally_not_as_a_like_pattern(repo):
    _put(repo, "a-1", "Employment_law")
    _put(repo, "a-2", "Employment_law/Termination")
    _put(repo, "x-1", "EmploymentXlaw")          # "_" would match "X" under LIKE
    _put(repo, "p-1", "Employment_lawyers")      # same prefix, different folder

    assert repo.rename_category_chunks("Employment_law", "Employment Law", tenant_id=1) == 2
    assert _chunk_categories(repo) == {
        "a-1": "Employment Law", "a-2": "Employment Law/Termination",
        "x-1": "EmploymentXlaw", "p-1": "Employment_lawyers",
    }

    assert repo.delete_category_chunks("Employment Law", tenant_id=1) == 2
    assert set(_chunk_categories(repo)) == {"x-1", "p-1"}


def test_full_reindex_sweep_keeps_the_current_library_and_every_matter_namespace(repo):
    _put(repo, "current-1", "Docs")
    _put(repo, "deleted-1", "Docs")
    _put(repo, "other-tenant-stale-1", "Docs", tenant_id=2)
    _put(repo, "matter-9-upload-1-chunk-0000", "matter-9")

    removed = repo.delete_library_chunks_except({"current-1"})

    assert removed == 2
    assert set(_chunk_categories(repo)) == {"current-1", "matter-9-upload-1-chunk-0000"}


def test_full_reindex_sweep_with_an_empty_library_clears_library_chunks_only(repo):
    _put(repo, "gone-1", "Docs")
    _put(repo, "matter-2-upload-1-chunk-0000", "matter-2")

    assert repo.delete_library_chunks_except(set()) == 1
    assert set(_chunk_categories(repo)) == {"matter-2-upload-1-chunk-0000"}
