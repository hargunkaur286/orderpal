-- Phase 6: long-term memory. One row per (user, fact). Keys are a fixed list on purpose:
-- the agent may only remember things we've decided are useful and safe to keep.
CREATE TABLE IF NOT EXISTS user_preferences (
    user_id     INT  NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    key         TEXT NOT NULL CHECK (key IN ('diet', 'allergies', 'spice_level', 'language', 'favourite_cuisine')),
    value       TEXT NOT NULL CHECK (length(value) <= 200),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (user_id, key)            -- remembering a key again overwrites it (upsert)
);
