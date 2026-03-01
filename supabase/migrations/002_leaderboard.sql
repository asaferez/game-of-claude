-- 002_leaderboard.sql
-- Adds opt-out column for leaderboard visibility.
-- Default TRUE: all existing and new players appear on the leaderboard.
-- Run in Supabase SQL editor: Dashboard > SQL Editor > New query.

ALTER TABLE devices
  ADD COLUMN IF NOT EXISTS show_on_leaderboard BOOLEAN NOT NULL DEFAULT true;
