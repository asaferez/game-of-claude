"""
Backfill stats for a device from raw events stored in the events table.

Recomputes ALL stat columns from scratch so they match what the current
ingest pipeline would have produced. Safe to run multiple times (idempotent).

Usage:
    cd backend
    SUPABASE_URL=... SUPABASE_SERVICE_KEY=... python scripts/backfill_stats.py <device_id>

Or with a .env file:
    pip install python-dotenv  # if needed
    python scripts/backfill_stats.py <device_id>
"""
import os
import sys
from datetime import datetime, timezone
from collections import defaultdict

# Load .env if present
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

# Add project root to path so we can import engine modules
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.engine.xp import (
    is_commit_command, is_test_command, is_branch_command,
    is_pr_create_command, is_pr_merge_command,
    parse_commit_stats, extract_file_extension,
)
from app.db import get_client


PAGE_SIZE = 1000  # Supabase row limit per request


def fetch_all_events(db, device_id: str) -> list[dict]:
    """Fetch all events for a device in pages."""
    events = []
    offset = 0
    while True:
        res = (
            db.table("events")
            .select("session_id, event_type, data, received_at")
            .eq("device_id", device_id)
            .order("received_at")
            .range(offset, offset + PAGE_SIZE - 1)
            .execute()
        )
        batch = res.data or []
        events.extend(batch)
        print(f"  fetched {len(events)} events...", end="\r")
        if len(batch) < PAGE_SIZE:
            break
        offset += PAGE_SIZE
    print(f"  fetched {len(events)} events total          ")
    return events


def parse_timestamp(ts: str) -> datetime | None:
    if not ts:
        return None
    try:
        return datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except Exception:
        return None


def compute_backfill(events: list[dict]) -> dict:
    """
    Process raw events and return the full set of stat values to write.
    This produces a ground-truth recount of everything trackable from raw data.
    """
    total_commits = 0
    total_test_passes = 0
    total_branches = 0
    total_prs = 0
    total_merged_prs = 0
    total_insertions = 0
    file_extensions: set[str] = set()

    # session tracking
    session_starts: dict[str, datetime] = {}  # session_id → start time
    session_ends: dict[str, datetime] = {}    # session_id → end time
    sessions_with_data: set[str] = set()      # session_ids that had any event

    for ev in events:
        event_type = ev.get("event_type", "")
        session_id = ev.get("session_id")
        data = ev.get("data") or {}
        received_at = parse_timestamp(ev.get("received_at", ""))

        if session_id:
            sessions_with_data.add(session_id)

        if event_type == "SessionStart" and session_id and received_at:
            session_starts[session_id] = received_at

        elif event_type == "SessionEnd" and session_id and received_at:
            session_ends[session_id] = received_at

        elif event_type == "PostToolUse":
            tool_name = data.get("tool_name", "")
            tool_input = data.get("tool_input") or {}
            tool_response = data.get("tool_response") or {}
            exit_code = tool_response.get("exit_code")

            if tool_name == "Bash":
                cmd = tool_input.get("command", "")
                stdout = tool_response.get("stdout", "")

                if is_commit_command(cmd) and exit_code == 0:
                    total_commits += 1
                    cs = parse_commit_stats(stdout)
                    total_insertions += cs.get("insertions", 0)

                elif is_test_command(cmd) and exit_code == 0:
                    total_test_passes += 1

                elif is_branch_command(cmd) and exit_code == 0:
                    total_branches += 1

                elif is_pr_create_command(cmd) and exit_code == 0:
                    total_prs += 1

                elif is_pr_merge_command(cmd) and exit_code == 0:
                    total_merged_prs += 1

            elif tool_name in ("Edit", "Write"):
                ext = extract_file_extension(tool_input.get("file_path", ""))
                if ext:
                    file_extensions.add(ext)

    # Session minutes: sum all (end - start) pairs, cap each at 8h
    total_session_minutes = 0
    for sid, start in session_starts.items():
        end = session_ends.get(sid)
        if end and end > start:
            mins = int((end - start).total_seconds() / 60)
            total_session_minutes += min(mins, 480)

    # Session count: use sessions that have a SessionStart (most reliable)
    total_sessions = len(session_starts)

    return {
        "total_commits": total_commits,
        "total_test_passes": total_test_passes,
        "total_sessions": total_sessions,
        "total_branches": total_branches,
        "total_prs": total_prs,
        "total_merged_prs": total_merged_prs,
        "total_insertions": total_insertions,
        "total_session_minutes": total_session_minutes,
        "file_extensions": sorted(file_extensions),
    }


def run(device_id: str, dry_run: bool = False):
    print(f"\n🔍 Backfilling stats for device: {device_id[:8]}...\n")

    db = get_client()

    # Verify device exists
    res = db.table("devices").select("device_id, character_name").eq("device_id", device_id).execute()
    if not res.data:
        print(f"❌ Device not found: {device_id}")
        sys.exit(1)
    name = res.data[0]["character_name"]
    print(f"  Character: {name}")

    # Read current stats for comparison
    cur = db.table("user_stats").select("*").eq("device_id", device_id).execute()
    current = cur.data[0] if cur.data else {}
    print(f"\n  Current stats:")
    for k in ["total_commits", "total_test_passes", "total_sessions",
              "total_branches", "total_prs", "total_merged_prs",
              "total_insertions", "total_session_minutes"]:
        print(f"    {k}: {current.get(k, 0)}")
    print(f"    file_extensions: {current.get('file_extensions', [])}")

    # Fetch and process all events
    print(f"\n  Fetching events...")
    events = fetch_all_events(db, device_id)

    if not events:
        print("  No events found — nothing to backfill.")
        return

    # Compute new stats
    new_stats = compute_backfill(events)

    print(f"\n  Computed stats (from {len(events)} raw events):")
    for k, v in new_stats.items():
        current_val = current.get(k, 0)
        marker = " ✅" if v == current_val else f" 📈 (was {current_val})"
        print(f"    {k}: {v}{marker}")

    if dry_run:
        print("\n  DRY RUN — no changes written.")
        return

    # Write
    db.table("user_stats").upsert({"device_id": device_id, **new_stats}).execute()
    print(f"\n✅ Stats updated for {name}!\n")


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if a != "--dry-run"]
    dry = "--dry-run" in sys.argv

    if not args:
        print("Usage: python scripts/backfill_stats.py <device_id> [--dry-run]")
        sys.exit(1)

    run(args[0], dry_run=dry)
