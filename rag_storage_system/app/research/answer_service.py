"""
POST /ask, end to end. This is Work Plan Milestone 2's service - "the
heart of the product; everything else is a client of it."

    question
      -> retrieve (app/retrieval/retriever.py, unchanged)
      -> THRESHOLD GATE: top score < ask_score_threshold, or fewer than
         ask_min_chunks qualify  ->  "No authority on this point in the
         library." Claude is NEVER CALLED. This short circuit is
         Blueprint Test 2, and it is deliberately code: a model asked
         to admit ignorance will sometimes decline to.
      -> prompt assembly under the owner's active citation-lock prompt
      -> Claude
      -> citation verification (app/research/citations.py)
      -> invalid? ONE corrective regeneration
      -> still invalid? strip the unverifiable citations and flag
      -> answer + structured source list

`retriever` and `answerer` are injectable so the acceptance tests can
drive the whole decision tree - threshold gate, citation lock,
fabrication probe, the retry, the strip - with no database, no API
key, and no network. See tests/acceptance/.
"""

import time
from dataclasses import dataclass, field
from typing import Callable, Optional

from app.research.citations import CitationCheck, strip_unsupported, verify_answer
from app.research.prompts import get_active_prompt
from app.retrieval.retriever import retrieve
from config.settings import get_settings

NOT_IN_LIBRARY_MESSAGE = "No authority on this point in the library."

# Answer statuses, also the stored citation_status values.
STATUS_VERIFIED = "verified"
STATUS_STRIPPED = "stripped"
STATUS_NOT_IN_LIBRARY = "not_in_library"


@dataclass
class AnswerResult:
    answer: str
    status: str
    sources: list[dict] = field(default_factory=list)
    top_score: float = 0.0
    answered_by_model: bool = False
    model: Optional[str] = None
    prompt_version: Optional[int] = None
    input_tokens: int = 0
    output_tokens: int = 0
    latency_ms: int = 0
    citation_detail: dict = field(default_factory=dict)
    retried: bool = False

    @property
    def insufficient_authority(self) -> bool:
        return self.status == STATUS_NOT_IN_LIBRARY


def _to_source(index: int, hit: dict) -> dict:
    """
    One entry of the structured source list returned with every answer
    - filename + section, so "a human can verify in seconds"
    (Blueprint Section 2). `marker` ties it to the [Sn] in the answer
    text, which is what the console's source panel keys on.
    """

    return {
        "marker": f"S{index}",
        "chunk_id": hit.get("chunk_id"),
        "document_id": hit.get("document_id"),
        "filename": hit.get("filename"),
        "category": hit.get("category"),
        "chapter": hit.get("chapter"),
        "section": hit.get("section"),
        "start_page": hit.get("start_page"),
        "end_page": hit.get("end_page"),
        "chunk_text": hit.get("chunk_text", ""),
        "score": round(float(hit.get("final_score", 0.0)), 3),
    }


def answer_question(
    question: str,
    *,
    category: Optional[str] = None,
    top_k: Optional[int] = None,
    retriever: Callable[..., list[dict]] = retrieve,
    answerer=None,
    system_prompt: Optional[str] = None,
    prompt_version: Optional[int] = None,
) -> AnswerResult:
    """
    Answer `question` from the library.

    Never raises on a low-confidence question - that path returns a
    normal AnswerResult with status="not_in_library", because refusing
    is a correct answer (Blueprint Phase 2 step 3: "this is a feature,
    not an error").
    """

    settings = get_settings()
    started = time.monotonic()

    k = top_k or settings.ask_top_k

    hits = retriever(question, top_k=k, category=category)

    top_score = float(hits[0]["final_score"]) if hits else 0.0

    qualifying = [
        hit for hit in hits
        if float(hit.get("final_score", 0.0)) >= settings.ask_score_threshold
    ]

    # ---------------- THRESHOLD GATE (Blueprint Test 2) ----------------
    if not qualifying or len(qualifying) < settings.ask_min_chunks:
        return AnswerResult(
            answer=NOT_IN_LIBRARY_MESSAGE,
            status=STATUS_NOT_IN_LIBRARY,
            sources=[],
            top_score=top_score,
            answered_by_model=False,
            latency_ms=int((time.monotonic() - started) * 1000),
            citation_detail={
                "reason": "below_threshold",
                "threshold": settings.ask_score_threshold,
                "qualifying_chunks": len(qualifying),
                "min_required": settings.ask_min_chunks,
            },
        )

    if system_prompt is None:
        active = get_active_prompt()
        system_prompt = active["content"]
        prompt_version = active["version"]

    if answerer is None:
        from app.research.claude_answerer import ClaudeAnswerer

        answerer = ClaudeAnswerer()

    completion = answerer.answer(system_prompt, question, qualifying)
    input_tokens = completion.input_tokens
    output_tokens = completion.output_tokens
    retried = False

    check = verify_answer(completion.text, qualifying)

    # -------- ONE corrective regeneration, then strip and flag --------
    if not check.is_valid:
        retried = True
        retry = answerer.answer(
            system_prompt, question, qualifying,
            corrective=check.corrective_instruction(),
        )
        input_tokens += retry.input_tokens
        output_tokens += retry.output_tokens

        retry_check = verify_answer(retry.text, qualifying)

        if retry_check.is_valid:
            completion, check = retry, retry_check
        else:
            completion, check = retry, retry_check
            retry.text = strip_unsupported(retry.text, retry_check)

    status = STATUS_VERIFIED if check.is_valid else STATUS_STRIPPED

    # The model may still conclude the sources don't cover the point
    # even after clearing the threshold - honour that as a refusal
    # rather than presenting it as a cited answer.
    if NOT_IN_LIBRARY_MESSAGE.lower() in completion.text.lower() and len(completion.text) < 200:
        status = STATUS_NOT_IN_LIBRARY

    return AnswerResult(
        answer=completion.text,
        status=status,
        sources=[_to_source(i, hit) for i, hit in enumerate(qualifying, start=1)],
        top_score=top_score,
        answered_by_model=True,
        model=completion.model,
        prompt_version=prompt_version,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        latency_ms=int((time.monotonic() - started) * 1000),
        citation_detail=check.as_dict(),
        retried=retried,
    )