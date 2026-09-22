#!/usr/bin/env bash
# Restores a backup produced by backup_postgres.sh into a target
# database - use a DIFFERENT database/instance for drills, never
# restore over the live production database during a test.
#
# Usage: ./scripts/restore_postgres.sh <dump_file> <target_db_name>

set -euo pipefail

DUMP_FILE="${1:?Usage: restore_postgres.sh <dump_file> <target_db_name>}"
TARGET_DB="${2:?Usage: restore_postgres.sh <dump_file> <target_db_name>}"

: "${POSTGRES_HOST:?Set POSTGRES_HOST}"
: "${POSTGRES_PORT:=5432}"
: "${POSTGRES_USER:?Set POSTGRES_USER}"
: "${PGPASSWORD:?Set PGPASSWORD}"

echo "Creating target database '$TARGET_DB' if it doesn't exist..."
PGPASSWORD="$PGPASSWORD" createdb -h "$POSTGRES_HOST" -p "$POSTGRES_PORT" -U "$POSTGRES_USER" "$TARGET_DB" 2>/dev/null || true

pg_restore \
  --host="$POSTGRES_HOST" \
  --port="$POSTGRES_PORT" \
  --username="$POSTGRES_USER" \
  --dbname="$TARGET_DB" \
  --clean --if-exists \
  "$DUMP_FILE"

echo "Restored into '$TARGET_DB'. Verifying row counts:"
PGPASSWORD="$PGPASSWORD" psql -h "$POSTGRES_HOST" -p "$POSTGRES_PORT" -U "$POSTGRES_USER" -d "$TARGET_DB" -c \
  "SELECT 'documents' AS table, count(*) FROM documents
   UNION ALL SELECT 'intake_sessions', count(*) FROM intake_sessions
   UNION ALL SELECT 'chunk_embeddings', count(*) FROM chunk_embeddings;"