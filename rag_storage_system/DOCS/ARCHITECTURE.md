# Architecture

## Data flow
Upload (Owner: /categories/.../documents, Client: /end-user/intake/.../uploads)
  → extraction (app/extraction/) → segmentation (app/segmentation/)
  → chunking + embedding (app/embeddings/, sentence-transformers/all-MiniLM-L6-v2)
  → pgvector upsert (app/vector_store/) → hybrid retrieval (app/retrieval/)
  → Claude answer/report generation (app/analysis/, app/report/) with code-enforced citation lock
  → document rendering (app/report/*_renderer.py, python-docx/PDF)

## Namespaces (Matter isolation)
chunk_embeddings.category: Owner library = arbitrary category names;
Matter documents = "matter-<id>" (app/matter_rag/). Library-wide search
explicitly excludes every "matter-%" category (app/vector_store/vector_repository.py).

## Auth scopes
- Owner/Admin: JWT Bearer (app/security/auth.py), roles: owner/attorney/paralegal
- End User (Matter/Client): X-End-User-Key header, isolated per Matter

## Key tables
matters, intake_sessions, uploaded_inputs, extracted_information, reports,
report_reviews, interview_state, intake_facts, cause_of_action_library,
complaints, matter_assignments, chunk_embeddings, llm_usage_log

[Diagram: attach one via the artifact-diagramming skill if a visual is wanted.]