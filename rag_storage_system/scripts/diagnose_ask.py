"""
Explain, step by step, why a question gets the answer it gets - the
same retrieval, threshold, and relevance check the Ask / Research pages
run (app/api/end_user_api.py, app/analysis/answer_generation.py), but
printing what each step kept or dropped.

"No authority on this point was found in the firm's legal library" can
mean several different things: the file was never indexed, it belongs to
a different organization (tenant), its score fell under the threshold,
or the relevance check removed it. This tells you which.

Usage:
    python scripts/diagnose_ask.py "your question"
    python scripts/diagnose_ask.py "your question" --as person@firm.com   (an end user's organization)
    python scripts/diagnose_ask.py "your question" --tenant 2
"""

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from app.analysis.relevance_guard import RelevanceCheckUnavailable, filter_materially_relevant_chunks  # noqa: E402
from app.metadata import get_metadata_repository  # noqa: E402
from app.retrieval.retriever import retrieve  # noqa: E402
from app.retrieval_settings import get_current_retrieval_settings  # noqa: E402
from config.settings import get_settings  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("question")
    parser.add_argument("--as", dest="end_user_email", help="use this end user's organization (tenant)")
    parser.add_argument("--tenant", type=int, default=1)
    args = parser.parse_args()

    settings = get_settings()
    repo = get_metadata_repository()

    tenant_id = args.tenant
    if args.end_user_email:
        account = repo.get_end_user_by_email(args.end_user_email.strip().lower())
        if account is None:
            print(f"No end-user account for {args.end_user_email}.")
            return 1
        tenant_id = account["tenant_id"]
        print(f"End user {args.end_user_email}: status '{account['status']}', organization (tenant) {tenant_id}")

    print("\n1. Library")
    documents = repo.list_documents(tenant_id=tenant_id)
    by_status: dict[str, int] = {}
    for doc in documents:
        by_status[doc["status"]] = by_status.get(doc["status"], 0) + 1
    print(f"   Organization {tenant_id} has {len(documents)} document(s): {by_status or 'none'}")
    if not by_status.get("Indexed"):
        print("   -> Nothing is Indexed, so nothing can be found. Upload in Vault, then run processing (worker must be running).")
        return 1

    retrieval = get_current_retrieval_settings(repo)
    print("\n2. Retrieval settings")
    print(f"   top_k={retrieval.top_k}  score_threshold={retrieval.score_threshold}  min_chunks={retrieval.min_chunks}")

    print("\n3. Retrieval (best matches, before the threshold)")
    candidates = retrieve(args.question, top_k=retrieval.top_k, score_threshold=0.0, tenant_id=tenant_id)
    if not candidates:
        print("   -> No chunks found at all for this organization.")
        return 1
    for i, chunk in enumerate(candidates):
        passed = chunk["final_score"] >= retrieval.score_threshold
        print(
            f"   [{i}] {'PASS' if passed else 'below threshold'}  score={chunk['final_score']:.3f} "
            f"(vector {chunk['vector_score']:.3f}, keyword {chunk['keyword_score']:.3f})  "
            f"{chunk['filename']} p{chunk.get('start_page')}"
        )
        print(f"        {chunk['chunk_text'][:110]!r}")
    kept = [c for c in candidates if c["final_score"] >= retrieval.score_threshold]
    if len(kept) < retrieval.min_chunks:
        print(f"   -> Only {len(kept)} chunk(s) reached the threshold (need {retrieval.min_chunks}): this is why it said 'No authority'.")
        return 0

    print("\n4. Relevance check (Claude)")
    if not settings.anthropic_api_key:
        print("   ANTHROPIC_API_KEY is not set - the check is off and every chunk above passes.")
        relevant = kept
    else:
        print(f"   model={settings.analysis_model}")
        try:
            relevant = filter_materially_relevant_chunks(args.question, kept, tenant_id=tenant_id)
        except RelevanceCheckUnavailable as exc:
            print(f"   -> The check could not run: {exc}")
            if exc.__cause__ is not None:
                print(f"      Cause: {type(exc.__cause__).__name__}: {exc.__cause__}")
            print("      The app now reports this as 'couldn't be verified', never as 'No authority'.")
            print("      Check ANTHROPIC_API_KEY, the account's credit balance, and ANALYSIS_MODEL in .env.")
            return 1
        kept_ids = {c["chunk_id"] for c in relevant}
        for i, chunk in enumerate(kept):
            print(f"   [{i}] {'relevant' if chunk['chunk_id'] in kept_ids else 'REMOVED as not relevant'}  {chunk['filename']}")

    print("\n5. Result")
    if len(relevant) < retrieval.min_chunks:
        print("   -> 'No authority on this point was found in the firm's legal library.'")
    else:
        print(f"   -> Answered from {len(relevant)} source(s): {sorted({c['filename'] for c in relevant})}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
