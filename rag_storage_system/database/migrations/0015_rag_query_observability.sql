-- 0015_rag_query_observability.sql
-- Extends the existing llm_usage_log table (0014_llm_usage_log.sql)
-- with per-query RAG observability fields - Owner research, Matter
-- research, and End User Q&A now log the query text, the retrieved
-- chunk ids/scores, and the citation-check outcome alongside the
-- existing model/token/latency columns. Same table, same system - not
-- a second logging mechanism. See app/observability/usage_log.py's
-- log_rag_query().

ALTER TABLE llm_usage_log ADD COLUMN IF NOT EXISTS query_text TEXT;
ALTER TABLE llm_usage_log ADD COLUMN IF NOT EXISTS retrieved_chunk_ids JSONB;
ALTER TABLE llm_usage_log ADD COLUMN IF NOT EXISTS retrieved_chunk_scores JSONB;
ALTER TABLE llm_usage_log ADD COLUMN IF NOT EXISTS citation_check_result VARCHAR(50);
