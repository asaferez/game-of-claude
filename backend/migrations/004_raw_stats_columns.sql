-- Migration 004: add raw stat columns to user_stats
-- Run in Supabase SQL editor

ALTER TABLE user_stats
  ADD COLUMN IF NOT EXISTS total_branches       INT         NOT NULL DEFAULT 0,
  ADD COLUMN IF NOT EXISTS total_prs            INT         NOT NULL DEFAULT 0,
  ADD COLUMN IF NOT EXISTS total_merged_prs     INT         NOT NULL DEFAULT 0,
  ADD COLUMN IF NOT EXISTS total_insertions     INT         NOT NULL DEFAULT 0,
  ADD COLUMN IF NOT EXISTS total_session_minutes INT        NOT NULL DEFAULT 0,
  ADD COLUMN IF NOT EXISTS file_extensions      text[]      NOT NULL DEFAULT '{}';
