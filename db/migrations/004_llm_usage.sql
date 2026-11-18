-- Phase 9: one row per LLM-backed request, for cost and latency reporting (GET /admin/usage).
CREATE TABLE IF NOT EXISTS llm_usage (
    id             BIGSERIAL PRIMARY KEY,
    at             TIMESTAMPTZ NOT NULL DEFAULT now(),
    endpoint       TEXT NOT NULL,                 -- 'ask' | 'chat'
    user_id        INT,
    model          TEXT NOT NULL,                 -- which model answered (shows when fallback kicked in)
    llm_calls      INT NOT NULL,
    input_tokens   INT NOT NULL,
    output_tokens  INT NOT NULL,
    latency_ms     INT NOT NULL,
    ok             BOOLEAN NOT NULL
);
CREATE INDEX IF NOT EXISTS llm_usage_at_idx ON llm_usage (at);
