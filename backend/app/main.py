"""
Game of Claude — FastAPI backend
"""
import logging
import os
from datetime import date
from typing import Any

from fastapi import FastAPI, Header, HTTPException, Depends, Request
from fastapi.middleware.cors import CORSMiddleware
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address

from .db import (
    get_client, get_device, get_stats, get_quest_progress,
    award_xp, upsert_stats, upsert_quest_progress,
    log_raw_event, is_already_processed, make_source_key,
)
from .engine.xp import compute_xp, compute_level, xp_for_level, level_title
from .engine.streak import compute_streak_xp
from .engine.quests import QUESTS, QUEST_BY_ID, get_counter_value, quests_to_check_for_event
from .models import HookEvent, DeviceRegister, ProfilePatch

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
logger = logging.getLogger(__name__)

limiter = Limiter(key_func=get_remote_address)
app = FastAPI(title="Game of Claude API")
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

ALLOWED_ORIGINS = [
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

    tool_call_id = str(getattr(body, "tool_call_id", "")) or body.session_id or "unknown"
    source_key = make_source_key(body.session_id or "no-session", f"{body.hook_event_name}:{tool_call_id}")
    if is_already_processed(db, source_key):
        return {"status": "duplicate"}

    log_raw_event(db, device_id, body.session_id, body.hook_event_name, body.model_dump())

    stats = get_stats(db, device_id)
    today = date.today()
    quest_progress = get_quest_progress(db, device_id)
    completions: list[dict] = []

    # One-time first-session bonus: hooks are working, player is in the game
    if body.hook_event_name == "SessionStart" and stats.get("total_sessions", 0) == 0:
        award_xp(db, device_id, "first_session", 10)
        upsert_stats(db, device_id, {"total_xp": (stats.get("total_xp") or 0) + 10})
        stats = get_stats(db, device_id)

    xp_amount, xp_source = compute_xp(body.model_dump())

    if xp_source == "commit":
        session_commits = _count_session_commits(db, device_id)
        if session_commits >= 3:
            xp_amount, xp_source = 0, ""

    if xp_amount > 0:
        award_xp(db, device_id, xp_source, xp_amount)
        new_total_xp = (stats.get("total_xp") or 0) + xp_amount
        upsert_stats(db, device_id, {"total_xp": new_total_xp})
        stats = _update_running_totals(db, device_id, stats, xp_source)
        stats["total_xp"] = new_total_xp
        completions += _check_quests(db, device_id, stats, quest_progress, xp_source, today)
        quest_progress = get_quest_progress(db, device_id)

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
        "total_commits": stats.get("total_commits", 0),
        "total_test_passes": stats.get("total_test_passes", 0),
        "total_sessions": stats.get("total_sessions", 0),
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

    from datetime import datetime, timedelta
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
        day = row["created_at"][:10]  # "YYYY-MM-DD"
        counts[day] = counts.get(day, 0) + 1

    return {"activity": counts}


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
        # show_on_leaderboard defaults to True if column not yet present
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


# ── Delete ────────────────────────────────────────────────────────────────────

@app.delete("/api/me", status_code=200)
def delete_me(device_id: str = Depends(require_device)):
    db = get_client()
    db.table("devices").delete().eq("device_id", device_id).execute()
    logger.info("Device deleted: %s...", device_id[:8])
    return {"status": "deleted", "message": "All your data has been permanently deleted."}


# ── Helpers ───────────────────────────────────────────────────────────────────

def _count_session_commits(db, device_id: str) -> int:
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
    if updates:
        upsert_stats(db, device_id, updates)
        return {**stats, **updates}
    return stats


def _handle_session_end(db, device_id, stats, body, today, quest_progress) -> list[dict]:
    completions: list[dict] = []
    session_commits = _count_session_commits(db, device_id)

    last_date_str = stats.get("last_session_date")
    last_date = date.fromisoformat(last_date_str) if last_date_str else None
    streak_xp, new_streak = compute_streak_xp(last_date, stats.get("current_streak", 0), today)

    new_longest = max(stats.get("longest_streak", 0), new_streak)
    total_sessions = (stats.get("total_sessions") or 0) + 1
    total_xp = stats.get("total_xp") or 0

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
        # Sync back: _check_quests may have added quest XP to merged["total_xp"]
        total_xp = merged["total_xp"]
        stat_updates["total_xp"] = total_xp

    if streak_xp > 0:
        merged = {**stats, **stat_updates}
        completions += _check_quests(db, device_id, merged, quest_progress, "streak", today)
        # Sync back: _check_quests may have added quest XP to merged["total_xp"]
        total_xp = merged["total_xp"]
        stat_updates["total_xp"] = total_xp

    upsert_stats(db, device_id, stat_updates)
    return completions


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
