# Prompt Registry

## Owner-editable (DB-versioned, GET/POST /admin/prompts/{name})
- narrative_system_prompt — app/analysis/claude_narrative.py
- answer_system_prompt — app/analysis/answer_generation.py
- intake_report_system_prompt — app/report/claude_analysis.py (DRAFTING_MODEL)
- complaint_drafting_system_prompt — app/complaint/claude_drafting.py (DRAFTING_MODEL)

An empty slot uses the default written in that module. Whatever a prompt
says, the citation lock (app/analysis/citation_lock.py) runs on the
report and complaint output in code: a statute/case/regulation that is not
in a library passage given to the model is removed, and a complaint
authority is kept only if it appears in the library passage it points to.

## Models
- ANALYSIS_MODEL (default claude-sonnet-5) — answers, relevance check,
  intake follow-ups, document reading, comparison narrative.
- DRAFTING_MODEL (default claude-opus-5-5) — the intake report analysis
  and complaint allegations only.

## Code-hardcoded (requires a deploy to change)
- Intake interview EN/ES strings — app/intake_engine/i18n.py
- Mandatory sweep questions — app/intake_engine/mandatory_sweep.py
- Protected activity questions — app/intake_engine/protected_activity.py

If the owner needs to edit intake questions without a deploy, that's a
follow-up feature (move these into the same prompt_versions pattern) —
not done here; flagging as a known gap, not implementing it now.