# Prompt Registry

## Owner-editable (DB-versioned, GET/POST /admin/prompts/{name})
- narrative_system_prompt — app/analysis/claude_narrative.py
- answer_system_prompt — app/analysis/answer_generation.py

## Code-hardcoded (requires a deploy to change)
- Intake interview EN/ES strings — app/intake_engine/i18n.py
- Mandatory sweep questions — app/intake_engine/mandatory_sweep.py
- Protected activity questions — app/intake_engine/protected_activity.py

If the owner needs to edit intake questions without a deploy, that's a
follow-up feature (move these into the same prompt_versions pattern) —
not done here; flagging as a known gap, not implementing it now.