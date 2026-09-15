-- Adds chunk location fields to chunk_embeddings (0002_pgvector.sql) -
-- chapter/section/start_page/end_page were already computed for every
-- chunk (app/segmentation/chunker.py) and carried through embedding
-- generation (app/embeddings/embedding_manager.py), just not persisted
-- to pgvector yet. Needed so app/analysis/'s comparison report can
-- cite exact evidence (file name, page, section, chunk) for every
-- claim, not just the chunk's raw text.

ALTER TABLE chunk_embeddings ADD COLUMN IF NOT EXISTS chapter TEXT;
ALTER TABLE chunk_embeddings ADD COLUMN IF NOT EXISTS section TEXT;
ALTER TABLE chunk_embeddings ADD COLUMN IF NOT EXISTS start_page INTEGER;
ALTER TABLE chunk_embeddings ADD COLUMN IF NOT EXISTS end_page INTEGER;
