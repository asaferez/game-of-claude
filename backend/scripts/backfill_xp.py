#!/usr/bin/env python3
"""
Retroactively award XP and fix user_stats for a device that had events
silently dropped because migration 004 columns were absent.

The events table always received every event — only the stat/XP updates
failed. This script replays those events against the existing xp_log to
award only the delta (idempotent: safe to run multiple times).

Usage:
    cd backend
    SUPABASE_URL=... SUPABASE_SERVICE_KEY=... python scripts/backfill_xp.py <device_id>

The device_id is the UUID in ~/.claude/gamify.json on the user's machine.
"""

import os
import sys
import logging
from collections import defaultdict
from datetime import date, timedelta

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from supabase import create_client
from app.engine.xp import (
    is_commit_command,
    is_test_command,
    is_pr_create_command,
    is_pr_merge_command,
    compute_level,
)

logging.basicConfig(level=logging.INFO, format="%(message)s")
log = logging.getLogger(__name__)

DAILY_COMMIT_CAP = 10


def main():
    device_id = sys.argv[1] if len(sys.argv) > 1 else os.environ.get("DEVICE_ID", "")
    if not device_id:
        sys.exit("Usage: python scripts/backfill_xp.py <device_id>")

    db = create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_SERVICE_KEY"])

    # ── Fetch raw events ──────────────────────────────────────────────────────
    log.info("Fetching events for device %s...", device_id[:8])
    events = (
        db.table("events")
        .select("event_type, received_at, data")
        .eq("device_id", device_id)
        .order("received_at")
        .execute()
        .data or []
    )
    log.info("  %d raw events found", len(events))

    # ── Fetch existing xp_log ─────────────────────────────────────────────────
    existing_xp_rows = (
        db.table("xp_log")
        .select("source, amount, created_at")
        .eq("device_id", device_id)
        .execute()
        .data or []
    )
    # How many entries per (source, YYYY-MM-DD) already exist?
    credited: dict[tuple, int] = defaultdict(int)
    for row in existing_xp_rows:
        credited[(row["source"], row["created_at"][:10])] += 1

    log.info("  %d existing xp_log entries", len(existing_xp_rows))

    # ── Replay events day by day ──────────────────────────────────────────────
    by_day: dict[str, list] = defaultdict(list)
    for ev in events:
        by_day[ev["received_at"][:10]].append(ev)

    to_award: list[tuple[str, int, str]] = []  # (source, amount, day)
    session_days: list[str] = []               # days that had a SessionEnd

    for day in sorted(by_day):
        commits = tests = prs = merged = 0
        had_session_end = False

        for ev in by_day[day]:
            etype = ev.get("event_type", "")
            if etype == "SessionEnd":
                had_session_end = True
                continue
            if etype != "PostToolUse":
                continue

            data = ev.get("data") or {}
            if data.get("tool_name") != "Bash":
                continue

            cmd = (data.get("tool_input") or {}).get("command", "")
            exit_code = (data.get("tool_response") or {}).get("exit_code")
            if exit_code != 0:
                continue

            if is_commit_command(cmd) and commits < DAILY_COMMIT_CAP:
                commits += 1
            elif is_test_command(cmd):
                tests += 1
            elif is_pr_create_command(cmd):
                prs += 1
            elif is_pr_merge_command(cmd):
                merged += 1

        # Commits
        gap = commits - credited[("commit", day)]
        if gap > 0:
            log.info("  %s  +%d commit(s)  → +%d XP missing", day, gap, gap * 15)
            to_award.extend(("commit", 15, day) for _ in range(gap))

        # Tests
        gap = tests - credited[("test_pass", day)]
        if gap > 0:
            log.info("  %s  +%d test pass(es) → +%d XP missing", day, gap, gap * 8)
            to_award.extend(("test_pass", 8, day) for _ in range(gap))

        # PRs created
        gap = prs - credited[("pr", day)]
        if gap > 0:
            log.info("  %s  +%d PR(s) created → +%d XP missing", day, gap, gap * 10)
            to_award.extend(("pr", 10, day) for _ in range(gap))

        # PRs merged
        gap = merged - credited[("merged_pr", day)]
        if gap > 0:
            log.info("  %s  +%d PR(s) merged → +%d XP missing", day, gap, gap * 20)
            to_award.extend(("merged_pr", 20, day) for _ in range(gap))

        # session_commit bonus (once per day when session ended with commits)
        if had_session_end and commits > 0 and credited[("session_commit", day)] == 0:
            log.info("  %s  session_commit bonus → +20 XP missing", day)
            to_award.append(("session_commit", 20, day))

        if had_session_end:
            session_days.append(day)

    # ── Streak XP backfill ────────────────────────────────────────────────────
    streak = 0
    prev: date | None = None
    for day_str in sorted(set(session_days)):
        d = date.fromisoformat(day_str)
        if prev is None:
            streak = 1
        elif (d - prev).days == 1:
            streak += 1
        else:
            streak = 1
        prev = d

        if credited[("streak", day_str)] == 0:
            streak_xp = 10 * streak
            log.info("  %s  streak day %d → +%d XP missing", day_str, streak, streak_xp)
            to_award.append(("streak", streak_xp, day_str))

    # ── Summary ───────────────────────────────────────────────────────────────
    if not to_award:
        log.info("\nNothing to backfill — xp_log already matches events.")
    else:
        total_missing = sum(amt for _, amt, _ in to_award)
        log.info("\n%d entries to insert, %d XP total", len(to_award), total_missing)

        confirm = input("Apply? [y/N] ").strip().lower()
        if confirm != "y":
            log.info("Aborted.")
            return

        for source, amount, day in to_award:
            db.table("xp_log").insert({
                "device_id": device_id,
                "source": source,
                "amount": amount,
                "created_at": f"{day}T12:00:00+00:00",  # noon UTC on that day
            }).execute()

        log.info("  xp_log entries inserted ✓")

    # ── Recompute user_stats ──────────────────────────────────────────────────
    stats = (
        db.table("user_stats")
        .select("*")
        .eq("device_id", device_id)
        .execute()
        .data or [{}]
    )[0]

    # total_xp: existing + newly awarded
    missing_xp = sum(amt for _, amt, _ in to_award)
    new_total_xp = (stats.get("total_xp") or 0) + missing_xp
    new_level = compute_level(new_total_xp)

    # total_sessions: count distinct SessionEnd events
    session_end_count = sum(1 for ev in events if ev.get("event_type") == "SessionEnd")

    # streak: replay from session_days
    final_streak = longest = 0
    prev = None
    streak = 0
    for day_str in sorted(set(session_days)):
        d = date.fromisoformat(day_str)
        if prev is None:
            streak = 1
        elif (d - prev).days == 1:
            streak += 1
        else:
            streak = 1
        prev = d
        longest = max(longest, streak)

    # Is the streak still live? (last session was today or yesterday)
    if session_days:
        last_day = date.fromisoformat(sorted(session_days)[-1])
        final_streak = streak if (date.today() - last_day).days <= 1 else 0
    last_session_date = sorted(session_days)[-1] if session_days else None

    stat_updates = {
        "total_xp": new_total_xp,
        "level": new_level,
        "total_sessions": max(stats.get("total_sessions") or 0, session_end_count),
        "current_streak": max(stats.get("current_streak") or 0, final_streak),
        "longest_streak": max(stats.get("longest_streak") or 0, longest),
    }
    if last_session_date:
        stat_updates["last_session_date"] = last_session_date

    db.table("user_stats").upsert({"device_id": device_id, **stat_updates}).execute()

    log.info("\n✅ user_stats updated:")
    log.info("  total_xp:       %d → %d", stats.get("total_xp") or 0, new_total_xp)
    log.info("  level:          %d → %d", stats.get("level") or 0, new_level)
    log.info("  total_sessions: %d → %d", stats.get("total_sessions") or 0, stat_updates["total_sessions"])
    log.info("  current_streak: %d → %d", stats.get("current_streak") or 0, stat_updates["current_streak"])
    log.info("  longest_streak: %d → %d", stats.get("longest_streak") or 0, stat_updates["longest_streak"])
    if last_session_date:
        log.info("  last_session_date: %s", last_session_date)
    log.info("\nNote: quests will self-heal on your next Claude Code event.")


if __name__ == "__main__":
    main()
