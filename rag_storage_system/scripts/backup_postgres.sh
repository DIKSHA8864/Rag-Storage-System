#!/usr/bin/env bash
# Backs up the full Postgres database (metadata tables AND
# chunk_embeddings/pgvector data - same database, see
# app/vector_store/vector_repository.py's docstring) to a timestamped
# dump file. Requires pg_dump matching the server's major version.
#
# Usage: ./scripts/backup_postgres.sh [output_dir]

set -euo pipefail

OUTPUT_DIR="${1:-./backups}"
mkdir -p "$OUTPUT_DIR"

TIMESTAMP=$(date -u +"%Y%m%dT%H%M%SZ")
OUTPUT_FILE="$OUTPUT_DIR/rag_storage_backup_${TIMESTAMP}.dump"

: "${POSTGRES_HOST:?Set POSTGRES_HOST}"
: "${POSTGRES_PORT:=5432}"
: "${POSTGRES_DB:?Set POSTGRES_DB}"
: "${POSTGRES_USER:?Set POSTGRES_USER}"
: "${PGPASSWORD:?Set PGPASSWORD (the Postgres password)}"

pg_dump \
  --host="$POSTGRES_HOST" \
  --port="$POSTGRES_PORT" \
  --username="$POSTGRES_USER" \
  --dbname="$POSTGRES_DB" \
  --format=custom \
  --file="$OUTPUT_FILE"

echo "Backup written to $OUTPUT_FILE"
echo "Row counts at backup time:"
PGPASSWORD="$PGPASSWORD" psql -h "$POSTGRES_HOST" -p "$POSTGRES_PORT" -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c \
  "SELECT 'documents' AS table, count(*) FROM documents
   UNION ALL SELECT 'intake_sessions', count(*) FROM intake_sessions
   UNION ALL SELECT 'chunk_embeddings', count(*) FROM chunk_embeddings;"