-- Backfill all stat columns from raw events for a specific device.
-- Replace the device_id value below before running.
-- Safe to run multiple times (full recompute, not additive).
--
-- Run this in: Supabase Dashboard → SQL Editor

DO $$
DECLARE
  v_device_id text := 'b752403a-b374-4be3-939f-9e28fc550027';

  v_total_commits        int;
  v_total_test_passes    int;
  v_total_branches       int;
  v_total_prs            int;
  v_total_merged_prs     int;
  v_total_insertions     int;
  v_total_sessions       int;
  v_total_session_minutes int;
  v_file_extensions      text[];
  v_rows                 int;

BEGIN

  -- ── Bash command stats ───────────────────────────────────────────────────

  SELECT
    COUNT(*)  FILTER (WHERE cmd ~ '\mgit\s+commit\M' AND ec = 0),
    COALESCE(SUM(
      CASE WHEN cmd ~ '\mgit\s+commit\M' AND ec = 0
           AND stdout ~ '\d+ insertions?\(\+\)'
      THEN (regexp_match(stdout, '(\d+) insertions?\(\+\)'))[1]::int
      ELSE 0 END
    ), 0),
    COUNT(*)  FILTER (
      WHERE cmd ~ '\m(pytest|jest|vitest|npm\s+test|yarn\s+test|go\s+test|cargo\s+test|rspec|mocha)\M'
      AND ec = 0
    ),
    COUNT(*)  FILTER (
      WHERE cmd ~ '\mgit\s+(checkout\s+-b|switch\s+-c)\s+\S' AND ec = 0
    ),
    COUNT(*)  FILTER (WHERE cmd ~ '\mgh\s+pr\s+create\M' AND ec = 0),
    COUNT(*)  FILTER (WHERE cmd ~ '\mgh\s+pr\s+merge\M'  AND ec = 0)
  INTO
    v_total_commits, v_total_insertions,
    v_total_test_passes,
    v_total_branches,
    v_total_prs, v_total_merged_prs
  FROM (
    SELECT
      data->'tool_input'->>'command'             AS cmd,
      data->'tool_response'->>'stdout'            AS stdout,
      (data->'tool_response'->>'exit_code')::int  AS ec
    FROM events
    WHERE device_id   = v_device_id
      AND event_type  = 'PostToolUse'
      AND data->>'tool_name' = 'Bash'
      AND data->'tool_response' IS NOT NULL
      AND data->'tool_response'->>'exit_code' IS NOT NULL
  ) bash;

  -- ── Sessions + coding time ───────────────────────────────────────────────

  SELECT
    COUNT(DISTINCT session_id),
    COALESCE(SUM(LEAST(
      EXTRACT(EPOCH FROM (end_time - start_time)) / 60,
      480  -- cap individual sessions at 8 h to ignore outliers
    ))::int, 0)
  INTO v_total_sessions, v_total_session_minutes
  FROM (
    SELECT
      session_id,
      MIN(received_at) FILTER (WHERE event_type = 'SessionStart') AS start_time,
      MAX(received_at) FILTER (WHERE event_type = 'SessionEnd')   AS end_time
    FROM events
    WHERE device_id   = v_device_id
      AND event_type  IN ('SessionStart', 'SessionEnd')
      AND session_id  IS NOT NULL
    GROUP BY session_id
  ) s
  WHERE start_time IS NOT NULL
    AND end_time   IS NOT NULL;

  -- ── File extensions from Edit/Write ──────────────────────────────────────

  SELECT COALESCE(
    (SELECT ARRAY_AGG(DISTINCT ext ORDER BY ext)
     FROM (
       SELECT LOWER(
         (regexp_match(
           -- filename only (after last slash)
           substring(data->'tool_input'->>'file_path' FROM '[^/]+$'),
           -- must start with non-dot, have chars, then .ext (1-10 alphanum)
           '^[^.].+\.([a-zA-Z0-9]{1,10})$'
         ))[1]
       ) AS ext
       FROM events
       WHERE device_id  = v_device_id
         AND event_type = 'PostToolUse'
         AND data->>'tool_name' IN ('Edit', 'Write')
         AND data->'tool_input'->>'file_path' IS NOT NULL
     ) x
     WHERE ext IS NOT NULL
    ),
    ARRAY[]::text[]
  ) INTO v_file_extensions;

  -- ── Preview (raise notice so you can see before the update fires) ────────

  RAISE NOTICE 'Backfill preview for %:', v_device_id;
  RAISE NOTICE '  total_commits         = %', v_total_commits;
  RAISE NOTICE '  total_test_passes     = %', v_total_test_passes;
  RAISE NOTICE '  total_sessions        = %', v_total_sessions;
  RAISE NOTICE '  total_branches        = %', v_total_branches;
  RAISE NOTICE '  total_prs             = %', v_total_prs;
  RAISE NOTICE '  total_merged_prs      = %', v_total_merged_prs;
  RAISE NOTICE '  total_insertions      = %', v_total_insertions;
  RAISE NOTICE '  total_session_minutes = %', v_total_session_minutes;
  RAISE NOTICE '  file_extensions       = %', v_file_extensions;

  -- ── Write ────────────────────────────────────────────────────────────────

  UPDATE user_stats SET
    total_commits         = v_total_commits,
    total_test_passes     = v_total_test_passes,
    total_sessions        = v_total_sessions,
    total_branches        = v_total_branches,
    total_prs             = v_total_prs,
    total_merged_prs      = v_total_merged_prs,
    total_insertions      = v_total_insertions,
    total_session_minutes = v_total_session_minutes,
    file_extensions       = v_file_extensions
  WHERE device_id = v_device_id;

  GET DIAGNOSTICS v_rows = ROW_COUNT;
  RAISE NOTICE 'Done. % row(s) updated.', v_rows;

END $$;
