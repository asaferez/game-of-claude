"""
Game of Claude — FastAPI backend
"""
import logging
import os
from datetime import date, datetime, timezone
from typing import Any

from contextlib import asynccontextmanager

from fastapi import FastAPI, Header, HTTPException, Depends, Request
from fastapi.middleware.cors import CORSMiddleware
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address

from .db import (
    get_client, get_device, get_stats, get_quest_progress,
    award_xp, upsert_stats, upsert_quest_progress,
    log_raw_event, is_already_processed, make_source_key,
    get_recent_events, get_today_session_count, count_today_xp_source,
    get_session_start_time, get_all_events, award_xp_at,
)
from .engine.xp import (
    compute_xp, compute_level, xp_for_level, level_title,
    parse_commit_stats, extract_file_extension,
)
from .engine.streak import compute_streak_xp
from .engine.quests import QUESTS, QUEST_BY_ID, get_counter_value, quests_to_check_for_event
from .models import HookEvent, DeviceRegister, ProfilePatch, GitSync, SessionSummary

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
logger = logging.getLogger(__name__)

limiter = Limiter(key_func=get_remote_address)


@asynccontextmanager
async def lifespan(app):
    """Verify migration 003 columns exist so stat tracking doesn't fail silently."""
    try:
        db = get_client()
        db.table("user_stats").select(
            "total_branches, total_prs, total_merged_prs, "
            "total_insertions, total_session_minutes, file_extensions"
        ).limit(1).execute()
        logger.info("Schema check passed: migration 003 columns present")
    except Exception as e:
        logger.error("SCHEMA CHECK FAILED: migration 003 columns missing! "
                     "Run supabase/migrations/003_raw_stats_columns.sql. Error: %s", e)
    yield


app = FastAPI(title="Game of Claude API", lifespan=lifespan)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

ALLOWED_ORIGINS = [
    "https://gameofclaude.online",
    "https://www.gameofclaude.online",
    "https://game-of-claude.vercel.app",
    "http://localhost:3000",
]
app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_methods=["GET", "POST", "PATCH", "DELETE"],
    allow_headers=["Authorization", "Content-Type"],
)


@app.get("/health")
def health():
    try:
        db = get_client()
        db.table("devices").select("device_id").limit(1).execute()
        return {"status": "ok", "db": "ok"}
    except Exception as e:
        logger.error("Health check DB failure: %s", e)
        raise HTTPException(status_code=503, detail="DB unavailable")


# ── Auth ──────────────────────────────────────────────────────────────────────

def get_device_id(authorization: str = Header(...)) -> str:
    if not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing Bearer token")
    return authorization.removeprefix("Bearer ").strip()


def require_device(device_id: str = Depends(get_device_id)) -> str:
    db = get_client()
    if not get_device(db, device_id):
        raise HTTPException(status_code=404, detail="Device not registered")
    return device_id


# ── Register ──────────────────────────────────────────────────────────────────

@app.post("/api/devices", status_code=201)
@limiter.limit("10/minute")
def register_device(request: Request, body: DeviceRegister):
    db = get_client()
    if get_device(db, body.device_id):
        return {"status": "already_registered"}
    db.table("devices").insert({"device_id": body.device_id, "character_name": body.character_name}).execute()
    upsert_stats(db, body.device_id, {"total_xp": 25})
    award_xp(db, body.device_id, "install", 25)
    logger.info("Device registered: %s (%s)", body.device_id[:8], body.character_name)
    return {"status": "registered", "xp_awarded": 25}


# ── Ingest events ─────────────────────────────────────────────────────────────

@app.post("/api/events", status_code=200)
@limiter.limit("60/minute")
def ingest_event(request: Request, body: HookEvent, device_id: str = Depends(require_device)):
    db = get_client()

    # tool_use_id is unique per tool call; fall back to session_id only for
    # session-level events (SessionStart/SessionEnd) which have no tool_use_id.
    tool_use_id = body.tool_use_id or body.session_id or "unknown"
    source_key = make_source_key(body.session_id or "no-session", f"{body.hook_event_name}:{tool_use_id}")
    if is_already_processed(db, source_key):
        return {"status": "duplicate"}

    log_raw_event(db, device_id, body.session_id, body.hook_event_name, body.model_dump())

    stats = get_stats(db, device_id)
    today = date.today()
    quest_progress = get_quest_progress(db, device_id)
    completions: list[dict] = []

    # One-time first-session bonus
    if body.hook_event_name == "SessionStart" and stats.get("total_sessions", 0) == 0:
        award_xp(db, device_id, "first_session", 10)
        upsert_stats(db, device_id, {"total_xp": (stats.get("total_xp") or 0) + 10})
        stats = get_stats(db, device_id)

    # ── Raw stat capture: file extensions from Edit/Write ─────────────────────
    if body.hook_event_name == "PostToolUse" and body.tool_name in ("Edit", "Write"):
        try:
            _track_file_extension(db, device_id, stats, body.tool_input or {})
            stats = get_stats(db, device_id)  # refresh after potential extension update
        except Exception as e:
            logger.warning("Could not track file extension for %s: %s", device_id[:8], e)

    xp_amount, xp_source = compute_xp(body.model_dump())

    # Cap daily commit XP but keep xp_source so stat counters still update
    if xp_source == "commit":
        if _count_today_commits(db, device_id) >= 10:
            xp_amount = 0

    # Award XP first — stat counter updates are secondary and must not block it
    if xp_amount > 0:
        award_xp(db, device_id, xp_source, xp_amount)
        new_total_xp = (stats.get("total_xp") or 0) + xp_amount
        upsert_stats(db, device_id, {"total_xp": new_total_xp})
        stats["total_xp"] = new_total_xp

    # Update stat counters — wrapped so a missing column can't block XP above
    if xp_source:
        try:
            stats = _update_running_totals(db, device_id, stats, xp_source)
        except Exception as e:
            logger.error("Could not update running totals for %s/%s: %s", device_id[:8], xp_source, e)

    if xp_source:
        completions += _check_quests(db, device_id, stats, quest_progress, xp_source, today)
        quest_progress = get_quest_progress(db, device_id)

    # ── Raw stat capture: commit insertions from git output ───────────────────
    if xp_source == "commit":
        try:
            _track_commit_insertions(db, device_id, stats, body.tool_response or {})
        except Exception as e:
            logger.warning("Could not track commit insertions for %s: %s", device_id[:8], e)

    if body.hook_event_name == "SessionEnd":
        completions += _handle_session_end(db, device_id, stats, body, today, quest_progress)

    fresh_stats = get_stats(db, device_id)
    new_level = compute_level(fresh_stats.get("total_xp", 0))
    if new_level != fresh_stats.get("level", 0):
        upsert_stats(db, device_id, {"level": new_level})

    if xp_amount > 0 or completions:
        logger.info("Event %s for %s...: +%d XP, %d quests",
                    body.hook_event_name, device_id[:8], xp_amount, len(completions))

    return {"status": "ok", "xp_awarded": xp_amount, "quest_completions": completions}


# ── Profile ───────────────────────────────────────────────────────────────────

@app.get("/api/profile/{profile_device_id}")
def get_profile(profile_device_id: str):
    db = get_client()
    device = get_device(db, profile_device_id)
    if not device:
        raise HTTPException(status_code=404, detail="Profile not found")

    stats = get_stats(db, profile_device_id)
    quest_progress = get_quest_progress(db, profile_device_id)
    today = date.today()

    total_xp = stats.get("total_xp", 0)
    level = compute_level(total_xp)
    current_level_xp = xp_for_level(level)
    next_level_xp = xp_for_level(level + 1)

    return {
        "character_name": device.get("character_name", "Anonymous"),
        "level": level,
        "level_title": level_title(level),
        "total_xp": total_xp,
        "xp_in_level": total_xp - current_level_xp,
        "xp_to_next_level": next_level_xp - current_level_xp,
        "current_streak": stats.get("current_streak", 0),
        "longest_streak": stats.get("longest_streak", 0),
        # career stats
        "total_commits": stats.get("total_commits", 0),
        "total_test_passes": stats.get("total_test_passes", 0),
        "total_sessions": stats.get("total_sessions", 0),
        "total_branches": stats.get("total_branches", 0),
        "total_prs": stats.get("total_prs", 0),
        "total_merged_prs": stats.get("total_merged_prs", 0),
        "total_insertions": stats.get("total_insertions", 0),
        "total_session_minutes": stats.get("total_session_minutes", 0),
        "unique_extensions": len(stats.get("file_extensions") or []),
        # today
        "commits_today": count_today_xp_source(db, profile_device_id, "commit"),
        "sessions_today": get_today_session_count(db, profile_device_id),
        "quests": _build_quest_states(stats, quest_progress, today),
        "member_since": device.get("created_at", ""),
    }


@app.patch("/api/profile/{profile_device_id}")
def update_profile(profile_device_id: str, body: ProfilePatch, device_id: str = Depends(require_device)):
    if device_id != profile_device_id:
        raise HTTPException(status_code=403, detail="Cannot edit another device's profile")
    db = get_client()
    db.table("devices").update({"character_name": body.character_name}).eq("device_id", device_id).execute()
    return {"status": "updated"}


# ── Activity heatmap ──────────────────────────────────────────────────────────

@app.get("/api/activity/{profile_device_id}")
def get_activity(profile_device_id: str):
    """Return daily XP event counts for the past 365 days (for activity heatmap)."""
    db = get_client()
    if not get_device(db, profile_device_id):
        raise HTTPException(status_code=404, detail="Profile not found")

    from datetime import timedelta
    since = (datetime.utcnow() - timedelta(days=365)).date().isoformat()
    rows = (
        db.table("xp_log")
        .select("created_at")
        .eq("device_id", profile_device_id)
        .gte("created_at", since)
        .execute()
    )

    counts: dict[str, int] = {}
    for row in rows.data:
        day = row["created_at"][:10]
        counts[day] = counts.get(day, 0) + 1

    return {"activity": counts}


# ── Coding stats ───────────────────────────────────────────────────────────────

@app.get("/api/stats/{profile_device_id}")
@limiter.limit("30/minute")
def get_coding_stats(request: Request, profile_device_id: str):
    """Aggregate raw hook events into top projects, tool usage, and peak coding hour."""
    db = get_client()
    if not get_device(db, profile_device_id):
        raise HTTPException(status_code=404, detail="Profile not found")

    rows = get_recent_events(db, profile_device_id, days=30)

    projects: dict[str, int] = {}
    tools: dict[str, int] = {}
    hours: dict[int, int] = {}

    for row in rows:
        data = row.get("data") or {}
        received_at = row.get("received_at", "")

        cwd = data.get("cwd")
        if cwd:
            parts = [p for p in cwd.split("/") if p]
            if parts:
                project = parts[-1]
                projects[project] = projects.get(project, 0) + 1

        tool = data.get("tool_name")
        if tool:
            tools[tool] = tools.get(tool, 0) + 1

        if len(received_at) >= 13:
            hour = int(received_at[11:13])
            hours[hour] = hours.get(hour, 0) + 1

    top_projects = sorted(projects.items(), key=lambda x: x[1], reverse=True)[:5]
    top_tools = sorted(tools.items(), key=lambda x: x[1], reverse=True)[:5]
    peak_hour = max(hours, key=hours.get) if hours else None

    return {
        "top_projects": [{"name": k, "count": v} for k, v in top_projects],
        "tool_usage": [{"tool": k, "count": v} for k, v in top_tools],
        "peak_hour": peak_hour,
    }


# ── Leaderboard ───────────────────────────────────────────────────────────────

@app.get("/api/leaderboard")
def get_leaderboard():
    """Return top 20 players by total XP. Respects show_on_leaderboard opt-out."""
    db = get_client()
    stats_rows = (
        db.table("user_stats")
        .select("device_id, total_xp, level, current_streak")
        .order("total_xp", desc=True)
        .limit(50)
        .execute()
    )
    if not stats_rows.data:
        return {"leaderboard": []}

    device_ids = [r["device_id"] for r in stats_rows.data]
    devices_rows = (
        db.table("devices")
        .select("device_id, character_name, show_on_leaderboard")
        .in_("device_id", device_ids)
        .execute()
    )
    device_map = {r["device_id"]: r for r in (devices_rows.data or [])}

    result = []
    for row in stats_rows.data:
        dev = device_map.get(row["device_id"])
        if not dev:
            continue
        if not dev.get("show_on_leaderboard", True):
            continue
        result.append({
            "device_id": row["device_id"],
            "character_name": dev["character_name"],
            "total_xp": row.get("total_xp", 0),
            "level": row.get("level", 0),
            "level_title": level_title(row.get("level", 0)),
            "current_streak": row.get("current_streak", 0),
        })
        if len(result) >= 20:
            break

    return {"leaderboard": result}


# ── Reprocess ─────────────────────────────────────────────────────────────────

@app.post("/api/me/reprocess", status_code=200)
@limiter.limit("10/hour")
def reprocess_my_events(request: Request, device_id: str = Depends(require_device)):
    """
    Replay all stored raw events through the XP engine to correct any gaps in
    xp_log and user_stats.  Safe to call multiple times — only inserts missing
    xp_log entries and rebuilds user_stats from the full event history.
    """
    db = get_client()
    result = _reprocess_events(db, device_id)
    logger.info(
        "Reprocess %s...: +%d XP across %d new entries",
        device_id[:8], result["xp_added"], result["entries_added"],
    )
    return {"status": "ok", **result}


def _reprocess_events(db, device_id: str) -> dict:
    """
    Core reprocess logic.  Returns {xp_added, entries_added, total_xp}.
    """
    from collections import defaultdict

    events = get_all_events(db, device_id)

    # ── Existing xp_log (count per source+day so we can compute the delta) ────
    xp_rows = (
        db.table("xp_log").select("source, amount, created_at")
        .eq("device_id", device_id).execute().data or []
    )
    # "install" was awarded at registration, not from an event — leave it alone
    existing: dict[tuple, int] = defaultdict(int)
    for row in xp_rows:
        if row["source"] != "install":
            existing[(row["source"], row["created_at"][:10])] += 1

    # ── Replay events ──────────────────────────────────────────────────────────
    expected: list[tuple[str, int, str]] = []   # (source, amount, day)
    commit_per_day: dict[str, int] = defaultdict(int)
    session_days: list[str] = []

    # For user_stats full rebuild
    stat_totals: dict[str, int] = defaultdict(int)
    total_insertions = 0
    file_exts: set[str] = set()
    session_starts: dict[str, str] = {}   # session_id -> received_at ISO
    total_session_minutes = 0

    for ev in events:
        etype = ev.get("event_type", "")
        data  = ev.get("data") or {}
        day   = ev["received_at"][:10]
        sid   = data.get("session_id")

        if etype == "SessionStart":
            if sid:
                session_starts[sid] = ev["received_at"]
            continue

        if etype == "SessionEnd":
            session_days.append(day)
            stat_totals["total_sessions"] += 1
            if sid and sid in session_starts:
                try:
                    t0 = datetime.fromisoformat(session_starts[sid].replace("Z", "+00:00"))
                    t1 = datetime.fromisoformat(ev["received_at"].replace("Z", "+00:00"))
                    total_session_minutes += min(int((t1 - t0).total_seconds() / 60), 480)
                except Exception:
                    pass
            continue

        if etype != "PostToolUse":
            continue

        tool = data.get("tool_name", "")

        # File-extension tracking (Edit / Write)
        if tool in ("Edit", "Write"):
            ext = extract_file_extension((data.get("tool_input") or {}).get("file_path", ""))
            if ext:
                file_exts.add(ext)

        if tool != "Bash":
            continue

        xp_amount, xp_source = compute_xp(data)
        if not xp_source:
            continue

        # Running stat counters
        if xp_source == "commit":
            stat_totals["total_commits"] += 1
            output = (data.get("tool_response") or {}).get("output") or \
                     (data.get("tool_response") or {}).get("stdout") or ""
            total_insertions += parse_commit_stats(output).get("insertions", 0)
        elif xp_source == "test_pass":
            stat_totals["total_test_passes"] += 1
        elif xp_source == "pr":
            stat_totals["total_prs"] += 1
        elif xp_source == "merged_pr":
            stat_totals["total_merged_prs"] += 1
        elif xp_source == "branch":
            stat_totals["total_branches"] += 1

        # Daily commit cap
        if xp_source == "commit" and xp_amount > 0:
            if commit_per_day[day] >= 10:
                continue
            commit_per_day[day] += 1

        if xp_amount > 0:
            expected.append((xp_source, xp_amount, day))

    # First-session bonus (one-time, on the day of first SessionStart)
    if session_starts:
        first_day = sorted(session_starts.values())[0][:10]
        expected.append(("first_session", 10, first_day))

    # Session-commit bonuses
    for day in sorted(set(session_days)):
        if commit_per_day[day] > 0:
            expected.append(("session_commit", 20, day))

    # Streak bonuses
    streak = 0
    prev_d: date | None = None
    for day_str in sorted(set(session_days)):
        d = date.fromisoformat(day_str)
        streak = (streak + 1) if (prev_d and (d - prev_d).days == 1) else 1
        prev_d = d
        expected.append(("streak", 10 * streak, day_str))

    # ── Compute delta: expected – already credited ─────────────────────────────
    exp_by_key: dict[tuple, list[int]] = defaultdict(list)
    for source, amount, day in expected:
        exp_by_key[(source, day)].append(amount)

    to_award: list[tuple[str, int, str]] = []
    for (source, day), amounts in sorted(exp_by_key.items()):
        gap = len(amounts) - existing[(source, day)]
        if gap > 0:
            for amount in amounts[-gap:]:      # take the last N (streak amounts grow daily)
                to_award.append((source, amount, day))

    # ── Insert missing entries ─────────────────────────────────────────────────
    for source, amount, day in to_award:
        award_xp_at(db, device_id, source, amount, f"{day}T12:00:00+00:00")

    # ── Rebuild user_stats ─────────────────────────────────────────────────────
    total_xp = sum(
        r["amount"] for r in
        (db.table("xp_log").select("amount").eq("device_id", device_id).execute().data or [])
    )

    # Streak from session days
    final_streak = longest = streak = 0
    prev_d = None
    for day_str in sorted(set(session_days)):
        d = date.fromisoformat(day_str)
        streak = (streak + 1) if (prev_d and (d - prev_d).days == 1) else 1
        prev_d = d
        longest = max(longest, streak)
    if session_days:
        last_d = date.fromisoformat(sorted(session_days)[-1])
        final_streak = streak if (date.today() - last_d).days <= 1 else 0

    # Preserve stats that can be populated by /api/me/sync-git or /api/me/sync-session.
    # Use max(event-derived, existing) so reprocess doesn't overwrite higher values.
    current_stats = get_stats(db, device_id)
    max_merge_fields = ("total_commits", "total_prs", "total_merged_prs",
                        "total_branches", "total_insertions",
                        "total_sessions", "total_session_minutes",
                        "current_streak", "longest_streak")

    new_stats: dict[str, Any] = {
        "total_xp":          total_xp,
        "level":             compute_level(total_xp),
        "total_commits":     stat_totals["total_commits"],
        "total_test_passes": stat_totals["total_test_passes"],
        "total_prs":         stat_totals["total_prs"],
        "total_merged_prs":  stat_totals["total_merged_prs"],
        "total_branches":    stat_totals["total_branches"],
        "total_sessions":    stat_totals["total_sessions"],
        "current_streak":    final_streak,
        "longest_streak":    longest,
        "total_insertions":  total_insertions,
        "total_session_minutes": total_session_minutes,
    }
    for field in max_merge_fields:
        new_stats[field] = max(new_stats[field], current_stats.get(field) or 0)

    if session_days:
        new_stats["last_session_date"] = sorted(session_days)[-1]
    if file_exts:
        existing_exts = set(current_stats.get("file_extensions") or [])
        new_stats["file_extensions"] = sorted(existing_exts | file_exts)
    elif current_stats.get("file_extensions"):
        new_stats["file_extensions"] = current_stats["file_extensions"]

    upsert_stats(db, device_id, new_stats)

    # Build diagnostic info
    existing_summary = {f"{s}@{d}": c for (s, d), c in sorted(existing.items()) if c > 0}
    expected_summary: dict[str, int] = defaultdict(int)
    for s, _, d in expected:
        expected_summary[f"{s}@{d}"] += 1

    return {
        "xp_added":     sum(a for _, a, _ in to_award),
        "entries_added": len(to_award),
        "total_xp":     total_xp,
        "_debug": {
            "xp_log_rows_read": len(xp_rows),
            "events_read": len(events),
            "existing": dict(existing_summary),
            "expected": dict(expected_summary),
            "to_award": [{"source": s, "amount": a, "day": d} for s, a, d in to_award],
        },
    }


# ── Git Sync ─────────────────────────────────────────────────────────────────

@app.post("/api/me/sync-git", status_code=200)
@limiter.limit("30/hour")
def sync_git_stats(request: Request, body: GitSync, device_id: str = Depends(require_device)):
    """
    Merge git/GitHub-derived stats with existing event-based stats.
    Uses max(current, submitted) for each field so stats only go up.
    Call this after /api/me/reprocess to layer git data on top.
    """
    db = get_client()
    stats = get_stats(db, device_id)
    updates: dict[str, Any] = {}

    for field in ("total_commits", "total_prs", "total_merged_prs",
                  "total_branches", "total_insertions"):
        submitted = getattr(body, field)
        if submitted is not None:
            current = stats.get(field) or 0
            updates[field] = max(current, submitted)

    if body.file_extensions is not None:
        existing = set(stats.get("file_extensions") or [])
        merged = sorted(existing | set(body.file_extensions))
        updates["file_extensions"] = merged

    if updates:
        upsert_stats(db, device_id, updates)
        logger.info("Git sync for %s...: updated %s", device_id[:8], list(updates.keys()))

    # Check quests that may now be completed with the updated stats
    merged_stats = {**stats, **updates}
    quest_progress = get_quest_progress(db, device_id)
    today = date.today()
    completions: list[dict] = []
    for source in ("commit", "pr", "merged_pr", "file_extension"):
        completions += _check_quests(db, device_id, merged_stats, quest_progress, source, today)
        quest_progress = get_quest_progress(db, device_id)  # refresh after changes

    return {
        "status": "ok",
        "updated_fields": list(updates.keys()),
        "quest_completions": completions,
    }


# ── Session Sync (transcript-based) ──────────────────────────────────────────

@app.post("/api/me/sync-session", status_code=200)
@limiter.limit("60/hour")
def sync_session(request: Request, body: SessionSummary, device_id: str = Depends(require_device)):
    """
    Accept a session summary from the transcript parser (process_session.py).
    Deduplicates by session_id — safe to call multiple times for the same session.
    Updates user_stats and awards XP for the session.
    """
    db = get_client()

    # Dedup by session_id: check if we've already processed this session
    source_key = make_source_key(body.session_id, "sync-session")
    if is_already_processed(db, source_key):
        return {"status": "ok", "already_processed": True}

    stats = get_stats(db, device_id)
    today = date.today()
    quest_progress = get_quest_progress(db, device_id)
    completions: list[dict] = []

    # ── Update stat counters (max-merge so we never go backwards) ────────
    updates: dict[str, Any] = {}

    # Additive stats: these come from this session only, so add them
    updates["total_sessions"] = (stats.get("total_sessions") or 0) + 1
    updates["total_session_minutes"] = (
        (stats.get("total_session_minutes") or 0) + body.duration_minutes
    )

    # For commit/test/branch/PR counts, use max-merge: the transcript count
    # is for this session only, but sync-git may have already set a higher
    # career total from git log. So add session counts to current value.
    if body.commits > 0:
        updates["total_commits"] = (stats.get("total_commits") or 0) + body.commits
    if body.test_passes > 0:
        updates["total_test_passes"] = (stats.get("total_test_passes") or 0) + body.test_passes
    if body.branches > 0:
        updates["total_branches"] = (stats.get("total_branches") or 0) + body.branches
    if body.prs_created > 0:
        updates["total_prs"] = (stats.get("total_prs") or 0) + body.prs_created
    if body.prs_merged > 0:
        updates["total_merged_prs"] = (stats.get("total_merged_prs") or 0) + body.prs_merged

    # File extensions: union merge
    if body.file_extensions:
        existing_exts = set(stats.get("file_extensions") or [])
        merged_exts = sorted(existing_exts | set(body.file_extensions))
        updates["file_extensions"] = merged_exts

    # ── Streak ───────────────────────────────────────────────────────────
    session_date = today
    if body.ended_at:
        try:
            session_date = datetime.fromisoformat(
                body.ended_at.replace("Z", "+00:00")
            ).date()
        except (ValueError, TypeError):
            pass

    last_date_str = stats.get("last_session_date")
    last_date = date.fromisoformat(last_date_str) if last_date_str else None
    streak_xp, new_streak = compute_streak_xp(
        last_date, stats.get("current_streak", 0), session_date
    )
    updates["last_session_date"] = session_date.isoformat()
    updates["current_streak"] = new_streak
    updates["longest_streak"] = max(stats.get("longest_streak", 0), new_streak)

    # ── XP ───────────────────────────────────────────────────────────────
    total_xp = stats.get("total_xp") or 0

    # Commit XP: 15 per commit, capped at 10 commits per day
    commit_xp = min(body.commits, 10) * 15
    if commit_xp > 0:
        award_xp(db, device_id, "commit", commit_xp)
        total_xp += commit_xp

    # Test XP: 8 per test run
    test_xp = body.test_passes * 8
    if test_xp > 0:
        award_xp(db, device_id, "test_pass", test_xp)
        total_xp += test_xp

    # PR XP: 12 per PR created
    pr_xp = body.prs_created * 12
    if pr_xp > 0:
        award_xp(db, device_id, "pr", pr_xp)
        total_xp += pr_xp

    # Branch XP: 5 per branch
    branch_xp = body.branches * 5
    if branch_xp > 0:
        award_xp(db, device_id, "branch", branch_xp)
        total_xp += branch_xp

    # Session-commit bonus: 20 XP if session had commits
    if body.commits > 0:
        award_xp(db, device_id, "session_commit", 20)
        total_xp += 20

    # Streak XP
    if streak_xp > 0:
        award_xp(db, device_id, "streak", streak_xp)
        total_xp += streak_xp

    updates["total_xp"] = total_xp
    updates["level"] = compute_level(total_xp)
    upsert_stats(db, device_id, updates)

    # ── Quest checking ───────────────────────────────────────────────────
    merged_stats = {**stats, **updates}
    for source in ("commit", "test_pass", "pr", "branch", "session_commit",
                    "streak", "file_extension"):
        completions += _check_quests(
            db, device_id, merged_stats, quest_progress, source, today
        )
        quest_progress = get_quest_progress(db, device_id)

    xp_awarded = commit_xp + test_xp + pr_xp + branch_xp + streak_xp + (20 if body.commits > 0 else 0)
    logger.info(
        "Session sync %s for %s...: +%d XP (%d commits, %d tests, %d PRs, %dd streak)",
        body.session_id[:8], device_id[:8], xp_awarded,
        body.commits, body.test_passes, body.prs_created, new_streak,
    )

    return {
        "status": "ok",
        "already_processed": False,
        "xp_awarded": xp_awarded,
        "quest_completions": completions,
    }


# ── Debug / Diagnostics ──────────────────────────────────────────────────────

@app.get("/api/debug/last-event/{profile_device_id}")
def debug_last_event(profile_device_id: str):
    """Return the timestamp of the most recently received event for diagnostics."""
    db = get_client()
    if not get_device(db, profile_device_id):
        raise HTTPException(status_code=404, detail="Device not found")
    res = (
        db.table("events")
        .select("event_type, received_at")
        .eq("device_id", profile_device_id)
        .order("received_at", desc=True)
        .limit(1)
        .execute()
    )
    if not res.data:
        return {"last_event": None, "message": "No events received yet"}
    return {"last_event": res.data[0]}


@app.get("/api/debug/event-count/{profile_device_id}")
def debug_event_count(profile_device_id: str):
    """Return event counts by type and day for the last 7 days."""
    db = get_client()
    if not get_device(db, profile_device_id):
        raise HTTPException(status_code=404, detail="Device not found")

    from datetime import timedelta
    since = (datetime.now(timezone.utc) - timedelta(days=7)).isoformat()
    res = (
        db.table("events")
        .select("event_type, received_at")
        .eq("device_id", profile_device_id)
        .gte("received_at", since)
        .execute()
    )

    by_day: dict[str, dict[str, int]] = {}
    total = 0
    for row in (res.data or []):
        day = row["received_at"][:10]
        etype = row["event_type"]
        by_day.setdefault(day, {})
        by_day[day][etype] = by_day[day].get(etype, 0) + 1
        total += 1

    return {"total_events": total, "by_day": by_day}


@app.get("/api/debug/xp-log/{profile_device_id}")
def debug_xp_log(profile_device_id: str):
    """Return xp_log entries for debugging reprocess idempotency."""
    db = get_client()
    if not get_device(db, profile_device_id):
        raise HTTPException(status_code=404, detail="Device not found")
    rows = (
        db.table("xp_log")
        .select("source, amount, created_at")
        .eq("device_id", profile_device_id)
        .order("created_at")
        .execute()
        .data or []
    )
    summary: dict[str, int] = {}
    for r in rows:
        key = f"{r['source']}@{r['created_at'][:10]}"
        summary[key] = summary.get(key, 0) + 1
    return {"total_entries": len(rows), "entries": rows, "summary": summary}


@app.post("/api/me/cleanup-xp", status_code=200)
@limiter.limit("5/hour")
def cleanup_xp_duplicates(request: Request, device_id: str = Depends(require_device)):
    """
    Remove duplicate xp_log entries caused by the -0 slice bug in reprocess.
    Keeps the correct number of entries per (source, day) based on event replay,
    then recalculates total_xp.
    """
    from collections import defaultdict

    db = get_client()
    events = get_all_events(db, device_id)

    # Replay events to get expected counts (same logic as _reprocess_events)
    expected_counts: dict[tuple, int] = defaultdict(int)
    commit_per_day: dict[str, int] = defaultdict(int)
    session_days: list[str] = []
    session_starts: dict[str, str] = {}

    for ev in events:
        etype = ev.get("event_type", "")
        data = ev.get("data") or {}
        day = ev["received_at"][:10]
        sid = data.get("session_id")

        if etype == "SessionStart":
            if sid:
                session_starts[sid] = ev["received_at"]
            continue
        if etype == "SessionEnd":
            session_days.append(day)
            continue
        if etype != "PostToolUse":
            continue
        if data.get("tool_name") != "Bash":
            continue

        xp_amount, xp_source = compute_xp(data)
        if not xp_source or xp_amount == 0:
            continue

        if xp_source == "commit":
            if commit_per_day[day] >= 10:
                continue
            commit_per_day[day] += 1

        expected_counts[(xp_source, day)] += 1

    # Add bonus entries
    if session_starts:
        first_day = sorted(session_starts.values())[0][:10]
        expected_counts[("first_session", first_day)] += 1
    for day in sorted(set(session_days)):
        if commit_per_day[day] > 0:
            expected_counts[("session_commit", day)] += 1
    streak = 0
    prev_d: date | None = None
    for day_str in sorted(set(session_days)):
        d = date.fromisoformat(day_str)
        streak = (streak + 1) if (prev_d and (d - prev_d).days == 1) else 1
        prev_d = d
        expected_counts[("streak", day_str)] += 1

    # Fetch all xp_log entries
    all_rows = (
        db.table("xp_log").select("id, source, amount, created_at")
        .eq("device_id", device_id).order("created_at").execute().data or []
    )

    # Group by (source, day), keep expected count, delete extras
    grouped: dict[tuple, list] = defaultdict(list)
    for row in all_rows:
        key = (row["source"], row["created_at"][:10])
        grouped[key].append(row)

    to_delete: list[str] = []
    for key, rows_for_key in grouped.items():
        keep = expected_counts.get(key, 0)
        # For quest_complete and install, keep all
        if key[0] in ("quest_complete", "install"):
            continue
        if len(rows_for_key) > keep:
            excess = rows_for_key[keep:]
            to_delete.extend(r["id"] for r in excess)

    deleted = 0
    for row_id in to_delete:
        db.table("xp_log").delete().eq("id", row_id).execute()
        deleted += 1

    # Recalculate total_xp
    total_xp = sum(
        r["amount"] for r in
        (db.table("xp_log").select("amount").eq("device_id", device_id).execute().data or [])
    )
    upsert_stats(db, device_id, {"total_xp": total_xp, "level": compute_level(total_xp)})

    return {
        "status": "ok",
        "deleted_entries": deleted,
        "remaining_entries": len(all_rows) - deleted,
        "total_xp": total_xp,
    }


# ── Delete ────────────────────────────────────────────────────────────────────

@app.delete("/api/me", status_code=200)
def delete_me(device_id: str = Depends(require_device)):
    db = get_client()
    db.table("devices").delete().eq("device_id", device_id).execute()
    logger.info("Device deleted: %s...", device_id[:8])
    return {"status": "deleted", "message": "All your data has been permanently deleted."}


# ── Helpers ───────────────────────────────────────────────────────────────────

def _count_today_commits(db, device_id: str) -> int:
    """Count XP-earning commits logged today (for daily cap)."""
    res = db.table("xp_log").select("id", count="exact").eq(
        "device_id", device_id
    ).eq("source", "commit").gte("created_at", date.today().isoformat()).execute()
    return res.count or 0


def _update_running_totals(db, device_id: str, stats: dict, xp_source: str) -> dict:
    updates: dict[str, Any] = {}
    if xp_source == "commit":
        updates["total_commits"] = (stats.get("total_commits") or 0) + 1
    elif xp_source == "test_pass":
        updates["total_test_passes"] = (stats.get("total_test_passes") or 0) + 1
    elif xp_source == "pr":
        updates["total_prs"] = (stats.get("total_prs") or 0) + 1
    elif xp_source == "merged_pr":
        updates["total_merged_prs"] = (stats.get("total_merged_prs") or 0) + 1
    elif xp_source == "branch":
        updates["total_branches"] = (stats.get("total_branches") or 0) + 1
    if updates:
        upsert_stats(db, device_id, updates)
        return {**stats, **updates}
    return stats


def _track_file_extension(db, device_id: str, stats: dict, tool_input: dict) -> None:
    """Extract file extension from Edit/Write event and add to user's extension set."""
    ext = extract_file_extension(tool_input.get("file_path", ""))
    if not ext:
        return
    extensions = list(stats.get("file_extensions") or [])
    if ext not in extensions:
        extensions.append(ext)
        upsert_stats(db, device_id, {"file_extensions": extensions})


def _track_commit_insertions(db, device_id: str, stats: dict, tool_response: dict) -> None:
    """Parse git commit output and accumulate total_insertions.

    Claude Code sends Bash output as 'output' (combined stdout) in PostToolUse
    hook payloads. Accept both 'output' and 'stdout' for forward-compatibility.
    """
    output = tool_response.get("output") or tool_response.get("stdout") or ""
    commit_stats = parse_commit_stats(output)
    insertions = commit_stats.get("insertions", 0)
    if insertions > 0:
        new_total = (stats.get("total_insertions") or 0) + insertions
        upsert_stats(db, device_id, {"total_insertions": new_total})


def _handle_session_end(db, device_id, stats, body, today, quest_progress) -> list[dict]:
    completions: list[dict] = []
    session_commits = _count_today_commits(db, device_id)

    last_date_str = stats.get("last_session_date")
    last_date = date.fromisoformat(last_date_str) if last_date_str else None
    streak_xp, new_streak = compute_streak_xp(last_date, stats.get("current_streak", 0), today)

    new_longest = max(stats.get("longest_streak", 0), new_streak)
    total_sessions = (stats.get("total_sessions") or 0) + 1
    total_xp = stats.get("total_xp") or 0

    # Core stat updates — columns present since migration 001, must always succeed
    stat_updates: dict[str, Any] = {
        "last_session_date": today.isoformat(),
        "current_streak": new_streak,
        "longest_streak": new_longest,
        "total_sessions": total_sessions,
    }

    if streak_xp > 0:
        award_xp(db, device_id, "streak", streak_xp)
        total_xp += streak_xp
        stat_updates["total_xp"] = total_xp

    if session_commits > 0:
        award_xp(db, device_id, "session_commit", 20)
        total_xp += 20
        stat_updates["total_xp"] = total_xp
        merged = {**stats, **stat_updates}
        completions += _check_quests(db, device_id, merged, quest_progress, "session_commit", today)
        total_xp = merged["total_xp"]
        stat_updates["total_xp"] = total_xp

    if streak_xp > 0:
        merged = {**stats, **stat_updates}
        completions += _check_quests(db, device_id, merged, quest_progress, "streak", today)
        total_xp = merged["total_xp"]
        stat_updates["total_xp"] = total_xp

    upsert_stats(db, device_id, stat_updates)

    # Session duration — total_session_minutes added in migration 004; wrapped so
    # a missing column can't roll back the core stat_updates above.
    session_mins = _compute_session_duration(db, device_id, body.session_id)
    if session_mins > 0:
        try:
            upsert_stats(db, device_id, {
                "total_session_minutes": (stats.get("total_session_minutes") or 0) + session_mins,
            })
        except Exception as e:
            logger.warning("Could not update session minutes for %s: %s", device_id[:8], e)

    return completions


def _compute_session_duration(db, device_id: str, session_id: str | None) -> int:
    """Return session length in minutes, capped at 8h to ignore outliers."""
    start_time = get_session_start_time(db, device_id, session_id)
    if not start_time:
        return 0
    minutes = int((datetime.now(timezone.utc) - start_time).total_seconds() / 60)
    return max(0, min(minutes, 480))


def _check_quests(db, device_id, stats, quest_progress, event_source, today) -> list[dict]:
    completions = []
    for quest in quests_to_check_for_event(event_source):
        progress_row = quest_progress.get(quest.id)
        if quest.type == "progressive" and progress_row and progress_row.get("completed_at"):
            continue

        current_val = get_counter_value(stats, progress_row, quest, today)

        if quest.type == "daily":
            is_new_day = not progress_row or progress_row.get("reset_at") != str(today)
            new_val = 1 if is_new_day else (progress_row.get("current_value", 0) + 1)
            upsert_quest_progress(db, device_id, quest.id, {"current_value": new_val, "reset_at": str(today)})
            current_val = new_val

        if current_val >= quest.goal:
            already_done = (
                progress_row and progress_row.get("completed_at") and
                (quest.type == "progressive" or progress_row.get("reset_at") == str(today))
            )
            if not already_done:
                upsert_quest_progress(db, device_id, quest.id, {"completed_at": "now()"})
                award_xp(db, device_id, "quest_complete", quest.xp_reward)
                stats["total_xp"] = (stats.get("total_xp") or 0) + quest.xp_reward
                upsert_stats(db, device_id, {"total_xp": stats["total_xp"]})
                completions.append({"quest_id": quest.id, "quest_name": quest.name, "xp_awarded": quest.xp_reward})

    return completions


def _build_quest_states(stats, quest_progress, today) -> list[dict]:
    states = []
    for quest in QUESTS:
        progress_row = quest_progress.get(quest.id)
        current_val = get_counter_value(stats, progress_row, quest, today)
        is_completed = bool(
            progress_row and progress_row.get("completed_at") and (
                quest.type == "progressive" or progress_row.get("reset_at") == str(today)
            )
        )
        states.append({
            "id": quest.id,
            "name": quest.name,
            "description": quest.description,
            "type": quest.type,
            "goal": quest.goal,
            "current": min(current_val, quest.goal),
            "completed": is_completed,
            "xp_reward": quest.xp_reward,
        })
    return states
