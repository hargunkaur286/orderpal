-- Phase 7: keyword search next to vector search.
-- A GENERATED column: Postgres computes the tsvector from `content` itself on every insert/update,
-- so it can never drift out of sync with the text. GIN = inverted index, word -> chunks containing it.
ALTER TABLE chunks ADD COLUMN IF NOT EXISTS tsv tsvector
    GENERATED ALWAYS AS (to_tsvector('english', content)) STORED;
CREATE INDEX IF NOT EXISTS chunks_tsv_gin ON chunks USING gin (tsv);
