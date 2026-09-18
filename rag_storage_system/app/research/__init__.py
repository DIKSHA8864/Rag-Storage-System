"""
PHASE 2 - PRIVATE RESEARCH CONSOLE

The answer service the Blueprint calls the heart of the product:

    question -> retrieve from the private library
             -> threshold gate (low confidence = "not in the library",
                Claude never called)
             -> prompt assembly under the owner's citation-lock prompt
             -> Claude
             -> citation verification IN CODE
             -> answer + structured source list

Modules:
    prompts.py         owner-editable, versioned system prompt registry
    citations.py       citation extraction + verification (code, not prompt)
    claude_answerer.py the Claude call itself
    answer_service.py  the orchestration above, end to end
    threads.py         persisted threads/messages
    query_log.py       per-request observability

app/retrieval/ is reused unchanged - this package never runs its own
parallel search.
"""