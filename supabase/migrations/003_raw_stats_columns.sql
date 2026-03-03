-- 003_raw_stats_columns.sql
-- Adds raw stat tracking columns and fixes file_extensions type.
-- Run in Supabase SQL editor: Dashboard > SQL Editor > New query.

ALTER TABLE user_stats
  ADD COLUMN IF NOT EXISTS total_branches        INT  NOT NULL DEFAULT 0,
  ADD COLUMN IF NOT EXISTS total_prs             INT  NOT NULL DEFAULT 0,
  ADD COLUMN IF NOT EXISTS total_merged_prs      INT  NOT NULL DEFAULT 0,
  ADD COLUMN IF NOT EXISTS total_insertions      INT  NOT NULL DEFAULT 0,
  ADD COLUMN IF NOT EXISTS total_session_minutes INT  NOT NULL DEFAULT 0;

-- file_extensions was created as TEXT[] in 001; migrate to JSONB for
-- consistency with the Python client (which writes plain lists).
-- No-op if already JSONB.
ALTER TABLE user_stats
  ALTER COLUMN file_extensions TYPE JSONB
    USING to_jsonb(file_extensions);
