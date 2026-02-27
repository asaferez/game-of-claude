-- Game of Claude: initial schema
-- Run in Supabase SQL editor

-- One row per anonymous device (no PII)
CREATE TABLE devices (
  id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  device_id    TEXT UNIQUE NOT NULL,   -- UUID from ~/.claude/gamify.json
  character_name TEXT,                  -- user-chosen display name
  created_at   TIMESTAMPTZ DEFAULT NOW()
  -- Future leaderboard: add display_on_leaderboard BOOLEAN DEFAULT FALSE, claimed_username TEXT
);

-- Raw event log (append-only, never deleted except via DELETE /api/me)
CREATE TABLE events (
  id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  device_id    TEXT NOT NULL REFERENCES devices(device_id) ON DELETE CASCADE,
  session_id   TEXT,
  event_type   TEXT NOT NULL,   -- 'session_start' | 'tool_use' | 'session_end'
  data         JSONB,
  received_at  TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX events_device_id_idx ON events (device_id);
CREATE INDEX events_session_id_idx ON events (session_id);

-- Idempotency guard: prevents double-XP on retried hook deliveries
CREATE TABLE processed_events (
  source_key TEXT PRIMARY KEY  -- sha256(session_id + tool_call_id) or OTel metric key
);

-- XP audit log
CREATE TABLE xp_log (
  id         UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  device_id  TEXT NOT NULL REFERENCES devices(device_id) ON DELETE CASCADE,
  source     TEXT NOT NULL,    -- 'commit' | 'test_pass' | 'streak' | 'quest_complete' | 'session_commit'
  amount     INTEGER NOT NULL,
  created_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX xp_log_device_id_idx ON xp_log (device_id);

-- Quest progress (one row per device+quest; daily quests reset via reset_at)
CREATE TABLE quest_progress (
  device_id     TEXT NOT NULL REFERENCES devices(device_id) ON DELETE CASCADE,
  quest_id      TEXT NOT NULL,
  current_value INTEGER DEFAULT 0,
  completed_at  TIMESTAMPTZ,   -- NULL = not yet; set on first completion
  reset_at      DATE,          -- for daily quests: the date they were last reset
  PRIMARY KEY (device_id, quest_id)
);

-- Materialized running totals — updated in-request to avoid full scans on every read
CREATE TABLE user_stats (
  device_id           TEXT PRIMARY KEY REFERENCES devices(device_id) ON DELETE CASCADE,
  total_xp            INTEGER DEFAULT 0,
  level               INTEGER DEFAULT 0,
  current_streak      INTEGER DEFAULT 0,
  longest_streak      INTEGER DEFAULT 0,
  last_session_date   DATE,
  total_commits       INTEGER DEFAULT 0,
  total_test_passes   INTEGER DEFAULT 0,
  total_sessions      INTEGER DEFAULT 0,
  file_extensions     TEXT[]  DEFAULT '{}'   -- tracked for Polyglot quest
);
