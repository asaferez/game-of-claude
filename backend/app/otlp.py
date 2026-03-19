"""
OTLP JSON receiver — parses OpenTelemetry metrics and log events
from Claude Code's telemetry export and maps them to gamification events.

Endpoints:
  POST /v1/metrics  — ExportMetricsServiceRequest (JSON)
  POST /v1/logs     — ExportLogsServiceRequest (JSON)
"""
import json
import logging
from datetime import date, datetime, timezone
from typing import Any

from .engine.xp import (
    is_test_command, is_commit_command, is_branch_command,
    is_pr_create_command, is_pr_merge_command, extract_file_extension,
    compute_level,
)
from .engine.streak import compute_streak_xp
from .engine.quests import quests_to_check_for_event
from .db import (
    get_client, get_stats, get_quest_progress,
    award_xp, upsert_stats, upsert_quest_progress,
    is_already_processed, make_source_key, log_raw_event,
    count_today_xp_source, get_device,
)

logger = logging.getLogger(__name__)

# ── Metric names we care about ────────────────────────────────────────────────

METRIC_COMMIT = "claude_code.commit.count"
METRIC_PR = "claude_code.pull_request.count"
METRIC_SESSION = "claude_code.session.count"
METRIC_LOC = "claude_code.lines_of_code.count"
METRIC_ACTIVE_TIME = "claude_code.active_time.total"

# ── Helpers ───────────────────────────────────────────────────────────────────


def _get_attr(attributes: list[dict], key: str) -> str | None:
    """Extract a string attribute value from an OTLP attributes array."""
    for attr in (attributes or []):
        if attr.get("key") == key:
            val = attr.get("value", {})
            return (
                val.get("stringValue")
                or val.get("intValue")
                or val.get("doubleValue")
                or str(val.get("boolValue", ""))
            )
    return None


def _extract_session_id(attributes: list[dict]) -> str | None:
    return _get_attr(attributes, "session.id")


def _nano_to_datetime(nano_str: str | int | None) -> datetime | None:
    if not nano_str:
        return None
    try:
        ns = int(nano_str)
        return datetime.fromtimestamp(ns / 1e9, tz=timezone.utc)
    except (ValueError, OSError):
        return None


# ── Metric processing ─────────────────────────────────────────────────────────


def _extract_sum_delta(metric_data: dict) -> list[dict]:
    """Extract data points from a Sum metric (cumulative or delta counters)."""
    data_points = metric_data.get("dataPoints", [])
    results = []
    for dp in data_points:
        value = dp.get("asInt") or dp.get("asDouble") or 0
        try:
            value = int(value)
        except (ValueError, TypeError):
            value = 0
        results.append({
            "value": value,
            "attributes": dp.get("attributes", []),
            "time_unix_nano": dp.get("timeUnixNano"),
            "start_time_unix_nano": dp.get("startTimeUnixNano"),
        })
    return results


def process_metrics(payload: dict, device_id: str) -> dict:
    """
    Process an ExportMetricsServiceRequest JSON payload.
    Returns summary of what was processed.
    """
    db = get_client()
    stats = get_stats(db, device_id)
    today = date.today()
    quest_progress = get_quest_progress(db, device_id)
    completions: list[dict] = []
    total_xp_awarded = 0

    resource_metrics = payload.get("resourceMetrics", [])

    for rm in resource_metrics:
        resource_attrs = (rm.get("resource") or {}).get("attributes", [])
        session_id = _extract_session_id(resource_attrs)

        for sm in rm.get("scopeMetrics", []):
            for metric in sm.get("metrics", []):
                name = metric.get("name", "")
                sum_data = metric.get("sum")
                if not sum_data:
                    continue

                data_points = _extract_sum_delta(sum_data)
                for dp in data_points:
                    dp_session = _extract_session_id(dp["attributes"]) or session_id
                    dp_time = dp.get("time_unix_nano", "")
                    dedup_key = f"otel:{name}:{dp_session or 'no-session'}:{dp_time}"
                    source_key = make_source_key(dp_session or "no-session", dedup_key)

                    if is_already_processed(db, source_key):
                        continue

                    xp, src, stat_updates = _process_metric_point(
                        name, dp, stats, db, device_id, today, dp_session
                    )

                    if stat_updates:
                        upsert_stats(db, device_id, stat_updates)
                        stats = {**stats, **stat_updates}

                    if xp > 0:
                        award_xp(db, device_id, src, xp)
                        total_xp_awarded += xp
                        stats["total_xp"] = (stats.get("total_xp") or 0) + xp
                        upsert_stats(db, device_id, {"total_xp": stats["total_xp"]})

                    # Session-commit bonus: 20 XP once per session
                    if name == METRIC_COMMIT and dp_session:
                        sc_key = make_source_key(dp_session, f"otel:session_commit:{dp_session}")
                        if not is_already_processed(db, sc_key):
                            award_xp(db, device_id, "session_commit", 20)
                            total_xp_awarded += 20
                            stats["total_xp"] = (stats.get("total_xp") or 0) + 20
                            upsert_stats(db, device_id, {"total_xp": stats["total_xp"]})

                    if src:
                        new_completions = _check_quests_safe(
                            db, device_id, stats, quest_progress, src, today
                        )
                        completions += new_completions
                        quest_progress = get_quest_progress(db, device_id)

                    log_raw_event(db, device_id, dp_session, f"otel:{name}", {
                        "metric_name": name, "value": dp["value"],
                        "attributes": dp["attributes"],
                    })

    # Update level
    if total_xp_awarded > 0:
        fresh_stats = get_stats(db, device_id)
        new_level = compute_level(fresh_stats.get("total_xp", 0))
        if new_level != fresh_stats.get("level", 0):
            upsert_stats(db, device_id, {"level": new_level})

    return {
        "status": "ok",
        "xp_awarded": total_xp_awarded,
        "quest_completions": completions,
    }


def _process_metric_point(
    name: str, dp: dict, stats: dict, db, device_id: str, today: date,
    session_id: str | None = None,
) -> tuple[int, str, dict]:
    """
    Process a single metric data point. Returns (xp, source, stat_updates).
    """
    value = dp["value"]
    if value <= 0:
        return 0, "", {}

    if name == METRIC_COMMIT:
        # Each increment = 1 commit
        today_commits = count_today_xp_source(db, device_id, "commit")
        xp = 15 if today_commits < 10 else 0
        return xp, "commit", {
            "total_commits": (stats.get("total_commits") or 0) + 1,
        }

    if name == METRIC_PR:
        return 12, "pr", {
            "total_prs": (stats.get("total_prs") or 0) + 1,
        }

    if name == METRIC_SESSION:
        # Session start — handle streak + first-session bonus
        updates: dict[str, Any] = {
            "total_sessions": (stats.get("total_sessions") or 0) + 1,
        }

        # First-session bonus
        if stats.get("total_sessions", 0) == 0:
            award_xp(db, device_id, "first_session", 10)
            stats["total_xp"] = (stats.get("total_xp") or 0) + 10
            updates["total_xp"] = stats["total_xp"]

        # Streak
        last_date_str = stats.get("last_session_date")
        last_date = date.fromisoformat(last_date_str) if last_date_str else None
        streak_xp, new_streak = compute_streak_xp(
            last_date, stats.get("current_streak", 0), today
        )
        updates["last_session_date"] = today.isoformat()
        updates["current_streak"] = new_streak
        updates["longest_streak"] = max(stats.get("longest_streak", 0), new_streak)

        if streak_xp > 0:
            award_xp(db, device_id, "streak", streak_xp)
            stats["total_xp"] = (stats.get("total_xp") or 0) + streak_xp
            updates["total_xp"] = stats["total_xp"]

        return 0, "streak" if streak_xp > 0 else "", updates

    if name == METRIC_LOC:
        loc_type = _get_attr(dp["attributes"], "type")
        if loc_type == "added":
            return 0, "", {
                "total_insertions": (stats.get("total_insertions") or 0) + value,
            }
        return 0, "", {}

    if name == METRIC_ACTIVE_TIME:
        time_type = _get_attr(dp["attributes"], "type")
        if time_type == "user":
            minutes = value // 60
            if minutes > 0:
                return 0, "", {
                    "total_session_minutes": (
                        (stats.get("total_session_minutes") or 0) + minutes
                    ),
                }
        return 0, "", {}

    return 0, "", {}


# ── Log/event processing ─────────────────────────────────────────────────────


def process_logs(payload: dict, device_id: str) -> dict:
    """
    Process an ExportLogsServiceRequest JSON payload.
    Extracts tool_result events for test pass detection and file extension tracking.
    """
    db = get_client()
    stats = get_stats(db, device_id)
    today = date.today()
    quest_progress = get_quest_progress(db, device_id)
    completions: list[dict] = []
    total_xp_awarded = 0

    resource_logs = payload.get("resourceLogs", [])

    for rl in resource_logs:
        resource_attrs = (rl.get("resource") or {}).get("attributes", [])
        session_id = _extract_session_id(resource_attrs)

        for sl in rl.get("scopeLogs", []):
            for record in sl.get("logRecords", []):
                xp, src, stat_updates = _process_log_record(
                    record, resource_attrs, session_id, stats, db, device_id, today
                )

                if stat_updates:
                    upsert_stats(db, device_id, stat_updates)
                    stats = {**stats, **stat_updates}

                if xp > 0:
                    award_xp(db, device_id, src, xp)
                    total_xp_awarded += xp
                    stats["total_xp"] = (stats.get("total_xp") or 0) + xp
                    upsert_stats(db, device_id, {"total_xp": stats["total_xp"]})

                if src:
                    new_completions = _check_quests_safe(
                        db, device_id, stats, quest_progress, src, today
                    )
                    completions += new_completions
                    quest_progress = get_quest_progress(db, device_id)

    # Update level
    if total_xp_awarded > 0:
        fresh_stats = get_stats(db, device_id)
        new_level = compute_level(fresh_stats.get("total_xp", 0))
        if new_level != fresh_stats.get("level", 0):
            upsert_stats(db, device_id, {"level": new_level})

    return {
        "status": "ok",
        "xp_awarded": total_xp_awarded,
        "quest_completions": completions,
    }


def _process_log_record(
    record: dict, resource_attrs: list, session_id: str | None,
    stats: dict, db, device_id: str, today: date,
) -> tuple[int, str, dict]:
    """Process a single log record. Returns (xp, source, stat_updates)."""
    attrs = record.get("attributes", [])
    body = record.get("body", {})
    time_nano = record.get("timeUnixNano", "")

    # Get event name from body (Claude Code sends event name as body stringValue)
    event_name = body.get("stringValue", "") if isinstance(body, dict) else str(body)

    # Also check for event name in attributes
    if not event_name:
        event_name = _get_attr(attrs, "event.name") or ""

    record_session = _extract_session_id(attrs) or session_id

    # Dedup
    dedup_key = f"otel-log:{event_name}:{record_session or 'no-session'}:{time_nano}"
    source_key = make_source_key(record_session or "no-session", dedup_key)
    if is_already_processed(db, source_key):
        return 0, "", {}

    # Log raw event
    log_raw_event(db, device_id, record_session, f"otel:{event_name}", {
        "event_name": event_name,
        "attributes": attrs,
        "time_unix_nano": time_nano,
    })

    # We care about tool_result events
    if event_name != "claude_code.tool_result":
        return 0, "", {}

    tool_name = _get_attr(attrs, "tool_name") or ""
    success = _get_attr(attrs, "success")
    tool_params_str = _get_attr(attrs, "tool_parameters") or ""

    # Parse tool_parameters JSON
    tool_params = {}
    if tool_params_str:
        try:
            tool_params = json.loads(tool_params_str)
        except (json.JSONDecodeError, TypeError):
            pass

    # Bash tool — check for test commands
    if tool_name == "Bash" and success == "true":
        command = tool_params.get("bash_command") or tool_params.get("full_command") or ""

        if is_test_command(command):
            return 8, "test_pass", {
                "total_test_passes": (stats.get("total_test_passes") or 0) + 1,
            }

        # Branch detection from OTEL logs (backup — metrics may not cover this)
        if is_branch_command(command):
            return 5, "branch", {
                "total_branches": (stats.get("total_branches") or 0) + 1,
            }

        # PR merge detection from OTEL logs
        if is_pr_merge_command(command):
            return 20, "merged_pr", {
                "total_merged_prs": (stats.get("total_merged_prs") or 0) + 1,
            }

    # Edit/Write tool — track file extensions
    if tool_name in ("Edit", "Write"):
        file_path = tool_params.get("file_path", "")
        ext = extract_file_extension(file_path)
        if ext:
            extensions = list(stats.get("file_extensions") or [])
            if ext not in extensions:
                extensions.append(ext)
                return 0, "file_extension", {"file_extensions": extensions}

    return 0, "", {}


# ── Quest helper ──────────────────────────────────────────────────────────────


def _check_quests_safe(db, device_id, stats, quest_progress, event_source, today) -> list[dict]:
    """Check quests with error handling — same logic as main._check_quests."""
    completions = []
    try:
        for quest in quests_to_check_for_event(event_source):
            from .engine.quests import get_counter_value
            progress_row = quest_progress.get(quest.id)
            if quest.type == "progressive" and progress_row and progress_row.get("completed_at"):
                continue

            current_val = get_counter_value(stats, progress_row, quest, today)

            if quest.type == "daily":
                is_new_day = not progress_row or progress_row.get("reset_at") != str(today)
                new_val = 1 if is_new_day else (progress_row.get("current_value", 0) + 1)
                upsert_quest_progress(db, device_id, quest.id, {
                    "current_value": new_val, "reset_at": str(today)
                })
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
                    completions.append({
                        "quest_id": quest.id,
                        "quest_name": quest.name,
                        "xp_awarded": quest.xp_reward,
                    })
    except Exception as e:
        logger.error("Quest check failed for %s/%s: %s", device_id[:8], event_source, e)

    return completions
