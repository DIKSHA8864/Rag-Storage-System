"""
Phase 2 acceptance tests for the Research Console's answer service.

These drive app/research/answer_service.answer_question() end to end
through its injectable `retriever`/`answerer` seams (see that module's
own docstring) - no Postgres, no ANTHROPIC_API_KEY, no network. Passing
`system_prompt`/`prompt_version` directly also skips
app/research/prompts.get_active_prompt(), which is the only other
place this call chain would otherwise touch a database.

Each test corresponds to a rule the citation-lock design commits to:

    Threshold gate    a low-confidence question never reaches Claude
                       at all - checked in code, before any answerer
                       is even constructed.
    Verified answer    a well-cited answer passes through unchanged.
    Fabrication probe  an authority invented by the model - not
                       present in any retrieved chunk - is caught and
                       removed, even dressed up with a syntactically
                       valid [Sn] marker. A marker cannot launder a
                       citation the sources don't actually contain.
    Invalid marker     citing a source number that was never supplied
                       is an invented source slot, a distinct failure
                       from an invented authority.
    Corrective retry   one regeneration is allowed; it may recover the
                       answer, or the retry may still fail, in which
                       case the answer is stripped and flagged rather
                       than silently corrected or discarded.
    Honest refusal      clearing the relevance gate does not force an
                       answer - the model may still correctly refuse.
"""

from app.research.answer_service import (
    STATUS_NOT_IN_LIBRARY,
    STATUS_STRIPPED,
    STATUS_VERIFIED,
    answer_question,
)
from app.research.claude_answerer import AnswerCompletion

SYSTEM_PROMPT = "You are a legal research assistant. Cite only the numbered sources."
PROMPT_VERSION = 1


def _hit(chunk_id, text, score=0.6, filename="Employment_Handbook.pdf", category="Legal"):
    return {
        "chunk_id": chunk_id,
        "document_id": f"doc-{chunk_id}",
        "filename": filename,
        "category": category,
        "chapter": None,
        "section": None,
        "start_page": 1,
        "end_page": 1,
        "chunk_text": text,
        "final_score": score,
    }


def _retriever(hits):
    return lambda question, top_k=None, category=None: hits


class FakeAnswerer:
    """
    Returns each text in `responses` in order, one per .answer() call.
    Constructing it with an empty list and never calling it is how the
    threshold-gate tests prove Claude is never invoked - a call would
    raise IndexError instead of silently returning something.
    """

    def __init__(self, responses):
        self._responses = list(responses)
        self.calls = []

    def answer(self, system_prompt, question, hits, corrective=None):
        self.calls.append(
            {
                "system_prompt": system_prompt,
                "question": question,
                "hits": hits,
                "corrective": corrective,
            }
        )
        text = self._responses.pop(0)
        return AnswerCompletion(
            text=text, model="fake-model", input_tokens=10, output_tokens=10
        )


# ----------------------------------------------------------------------
# Threshold gate - Claude must never be called for a low-confidence
# question. This is deliberately code, not a prompt instruction: a
# model asked to admit ignorance will sometimes decline to.
# ----------------------------------------------------------------------


def test_no_hits_never_calls_claude():
    answerer = FakeAnswerer([])

    result = answer_question(
        "What is the meaning of life?",
        retriever=_retriever([]),
        answerer=answerer,
    )

    assert result.status == STATUS_NOT_IN_LIBRARY
    assert result.insufficient_authority is True
    assert result.sources == []
    assert answerer.calls == []


def test_below_score_threshold_never_calls_claude():
    answerer = FakeAnswerer([])
    low_score_hits = [_hit("c1", "Irrelevant filler text.", score=0.05)]

    result = answer_question(
        "What does the handbook say about overtime pay?",
        retriever=_retriever(low_score_hits),
        answerer=answerer,
    )

    assert result.status == STATUS_NOT_IN_LIBRARY
    assert answerer.calls == []


def test_below_min_chunks_never_calls_claude():
    """
    One chunk clears the relevance-score threshold but not the
    separate minimum-chunk-count gate (default ask_min_chunks=2) - a
    single strong match still isn't enough corroboration to answer
    from.
    """

    answerer = FakeAnswerer([])
    one_good_hit = [_hit("c1", "Overtime is paid at 1.5x after 8 hours.", score=0.9)]

    result = answer_question(
        "What does the handbook say about overtime pay?",
        retriever=_retriever(one_good_hit),
        answerer=answerer,
    )

    assert result.status == STATUS_NOT_IN_LIBRARY
    assert answerer.calls == []


# ----------------------------------------------------------------------
# A well-cited answer passes straight through, unmodified.
# ----------------------------------------------------------------------


def test_verified_answer_passes_through_unchanged():
    hits = [
        _hit(
            "c1",
            "Labor Code section 1102.5 protects employees who report "
            "suspected legal violations from retaliation.",
        ),
        _hit("c2", "Retaliation includes termination, demotion, or reduction in pay."),
    ]
    answer_text = (
        "Labor Code section 1102.5 protects employees who report violations [S1]. "
        "Retaliation includes termination or demotion [S2]."
    )
    answerer = FakeAnswerer([answer_text])

    result = answer_question(
        "Can my employer fire me for reporting a violation?",
        retriever=_retriever(hits),
        answerer=answerer,
        system_prompt=SYSTEM_PROMPT,
        prompt_version=PROMPT_VERSION,
    )

    assert result.status == STATUS_VERIFIED
    assert result.answer == answer_text
    assert result.retried is False
    assert len(answerer.calls) == 1
    assert len(result.sources) == 2
    assert result.citation_detail["unsupported_authorities"] == []
    assert result.citation_detail["invalid_markers"] == []


def test_invalid_marker_reference_is_caught_and_recovered():
    """Citing [S5] when only 2 sources were ever supplied is an
    invented source slot, distinct from an invented authority."""

    hits = [
        _hit("c1", "Labor Code section 1102.5 protects whistleblowers."),
        _hit("c2", "An employee handbook must state at-will status clearly."),
    ]
    answer_with_bad_marker = "Whistleblowers are protected [S5]."
    corrected_answer = "Whistleblowers are protected [S1]."
    answerer = FakeAnswerer([answer_with_bad_marker, corrected_answer])

    result = answer_question(
        "Are whistleblowers protected?",
        retriever=_retriever(hits),
        answerer=answerer,
        system_prompt=SYSTEM_PROMPT,
        prompt_version=PROMPT_VERSION,
    )

    assert answerer.calls[0]["corrective"] is None
    assert "[S5]" in answerer.calls[1]["corrective"]
    assert result.status == STATUS_VERIFIED
    assert result.answer == corrected_answer
    assert result.retried is True


# ----------------------------------------------------------------------
# Fabrication probe - a real, famous-sounding authority the model was
# never given must be caught, even carrying a syntactically valid
# marker.
# ----------------------------------------------------------------------


def test_fabrication_probe_recovers_on_corrective_retry():
    hits = [
        _hit("c1", "Labor Code section 1102.5 protects whistleblowers."),
        _hit("c2", "An employee handbook must state at-will status clearly."),
    ]
    fabricated_answer = (
        "This is squarely governed by Brown v. Board of Education [S1], "
        "which the library does not actually contain."
    )
    corrected_answer = "Labor Code section 1102.5 protects whistleblowers [S1]."
    answerer = FakeAnswerer([fabricated_answer, corrected_answer])

    result = answer_question(
        "What case governs this?",
        retriever=_retriever(hits),
        answerer=answerer,
        system_prompt=SYSTEM_PROMPT,
        prompt_version=PROMPT_VERSION,
    )

    assert len(answerer.calls) == 2
    assert answerer.calls[1]["corrective"] is not None
    assert "Brown v. Board of Education" in answerer.calls[1]["corrective"]
    assert result.status == STATUS_VERIFIED
    assert result.answer == corrected_answer
    assert result.retried is True


def test_fabrication_probe_strips_and_flags_when_retry_still_fails():
    hits = [
        _hit("c1", "Labor Code section 1102.5 protects whistleblowers."),
        _hit("c2", "An employee handbook must state at-will status clearly."),
    ]
    fabricated_answer = "Governed by Brown v. Board of Education [S1]."
    still_fabricated_answer = "Still governed by Brown v. Board of Education [S1]."
    answerer = FakeAnswerer([fabricated_answer, still_fabricated_answer])

    result = answer_question(
        "What case governs this?",
        retriever=_retriever(hits),
        answerer=answerer,
        system_prompt=SYSTEM_PROMPT,
        prompt_version=PROMPT_VERSION,
    )

    assert len(answerer.calls) == 2
    assert result.status == STATUS_STRIPPED
    assert "Brown v. Board of Education" not in result.answer
    assert "[citation removed - not in library]" in result.answer
    assert "Brown v. Board of Education" in result.citation_detail["unsupported_authorities"]


# ----------------------------------------------------------------------
# Honest refusal - clearing the relevance gate does not force an
# answer. The model may still correctly conclude the sources don't
# cover the actual question asked.
# ----------------------------------------------------------------------


def test_model_can_refuse_even_after_clearing_threshold():
    hits = [
        _hit("c1", "Overtime is paid at 1.5x after 8 hours.", score=0.6),
        _hit("c2", "Meal breaks are required after 5 hours.", score=0.5),
    ]
    refusal = "No authority on this point in the library."
    answerer = FakeAnswerer([refusal])

    result = answer_question(
        "What are the rules on parental leave?",
        retriever=_retriever(hits),
        answerer=answerer,
        system_prompt=SYSTEM_PROMPT,
        prompt_version=PROMPT_VERSION,
    )

    assert result.status == STATUS_NOT_IN_LIBRARY
    assert result.answer == refusal
    assert len(answerer.calls) == 1
