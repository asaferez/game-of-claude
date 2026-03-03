#!/usr/bin/env python3
"""
Process Claude Code session transcripts and send summaries to the backend.

Called as a SessionStart/SessionEnd command hook. Scans all transcript files
across all projects, finds unprocessed ones, and syncs them.

Can also be called directly:
    python3 process_session.py --transcript /path/to/session.jsonl --device-id <id>
    python3 process_session.py --sync-all --device-id <id>
"""

import argparse
import json
import os
import re
import sys
from datetime import datetime
from pathlib import Path

# ── Patterns (mirrors backend/app/engine/xp.py) ────────────────────────────

COMMIT_PATTERN = re.compile(r"\bgit\s+commit\b")
TEST_PATTERNS = re.compile(
    r"\b(pytest|python\s+-m\s+pytest|"
    r"jest|npx\s+jest|"
    r"vitest|npx\s+vitest|"
    r"npm\s+test|npm\s+run\s+test|"
    r"pnpm\s+test|pnpm\s+run\s+test|"
    r"yarn\s+test|yarn\s+run\s+test|"
    r"bun\s+test|"
    r"go\s+test|cargo\s+test|"
    r"rspec|mocha|phpunit|"
    r"dotnet\s+test|mvn\s+test|gradle\s+test|"
    r"make\s+test)\b"
)
PR_CREATE_PATTERN = re.compile(r"\bgh\s+pr\s+create\b")
PR_MERGE_PATTERN = re.compile(r"\bgh\s+pr\s+merge\b")
BRANCH_PATTERN = re.compile(r"\bgit\s+(?:checkout\s+-b|switch\s+-c)\s+\S")

GAMIFY_CONFIG = Path.home() / ".claude" / "gamify.json"
SYNCED_SESSIONS_FILE = Path.home() / ".claude" / "gamify_synced.json"
DEFAULT_API_BASE = "https://api.gameofclaude.online"


def extract_file_extension(file_path: str) -> str:
    if not file_path:
        return ""
    name = file_path.split("/")[-1]
    parts = name.rsplit(".", 1)
    if len(parts) == 2 and parts[0] and parts[1] and len(parts[1]) <= 10:
        ext = parts[1].lower()
        if ext not in ("lock",):
            return ext
    return ""


def parse_transcript(transcript_path: str) -> dict:
    """Parse a .jsonl transcript file and return a session summary."""
    commits = 0
    test_passes = 0
    branches = 0
    prs_created = 0
    prs_merged = 0
    file_extensions: set[str] = set()
    first_ts = None
    last_ts = None
    session_id = None

    with open(transcript_path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue

            ts = entry.get("timestamp")
            if ts:
                if not first_ts:
                    first_ts = ts
                last_ts = ts

            if not session_id:
                session_id = entry.get("sessionId")

            if entry.get("type") != "assistant":
                continue

            msg = entry.get("message", {})
            for block in msg.get("content", []):
                if block.get("type") != "tool_use":
                    continue

                tool_name = block.get("name", "")
                tool_input = block.get("input", {})

                if tool_name == "Bash":
                    cmd = tool_input.get("command", "")
                    if COMMIT_PATTERN.search(cmd):
                        commits += 1
                    if TEST_PATTERNS.search(cmd):
                        test_passes += 1
                    if BRANCH_PATTERN.search(cmd):
                        branches += 1
                    if PR_CREATE_PATTERN.search(cmd):
                        prs_created += 1
                    if PR_MERGE_PATTERN.search(cmd):
                        prs_merged += 1
                elif tool_name in ("Edit", "Write"):
                    ext = extract_file_extension(tool_input.get("file_path", ""))
                    if ext:
                        file_extensions.add(ext)

    duration_minutes = 0
    if first_ts and last_ts:
        try:
            t0 = datetime.fromisoformat(first_ts.replace("Z", "+00:00"))
            t1 = datetime.fromisoformat(last_ts.replace("Z", "+00:00"))
            duration_minutes = min(int((t1 - t0).total_seconds() / 60), 480)
        except (ValueError, TypeError):
            pass

    return {
        "session_id": session_id,
        "started_at": first_ts,
        "ended_at": last_ts,
        "duration_minutes": duration_minutes,
        "commits": commits,
        "test_passes": test_passes,
        "branches": branches,
        "prs_created": prs_created,
        "prs_merged": prs_merged,
        "file_extensions": sorted(file_extensions),
    }


def send_summary(api_base: str, device_id: str, summary: dict) -> dict | None:
    """POST the session summary to the backend. Returns response JSON or None."""
    import urllib.request
    import urllib.error

    url = f"{api_base}/api/me/sync-session"
    data = json.dumps(summary).encode()
    req = urllib.request.Request(
        url,
        data=data,
        headers={
            "Authorization": f"Bearer {device_id}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return json.loads(resp.read())
    except (urllib.error.URLError, urllib.error.HTTPError, Exception) as e:
        print(f"sync-session failed: {e}", file=sys.stderr)
        return None


def load_synced_sessions() -> set[str]:
    """Load the set of locally-known synced session IDs."""
    try:
        data = json.loads(SYNCED_SESSIONS_FILE.read_text())
        return set(data.get("synced", []))
    except (FileNotFoundError, json.JSONDecodeError):
        return set()


def save_synced_sessions(synced: set[str]) -> None:
    """Persist synced session IDs locally to avoid re-parsing."""
    SYNCED_SESSIONS_FILE.write_text(json.dumps({"synced": sorted(synced)}, indent=2))


def find_all_transcripts() -> list[Path]:
    """Find all .jsonl transcript files across all Claude Code projects."""
    projects_dir = Path.home() / ".claude" / "projects"
    if not projects_dir.exists():
        return []
    return sorted(projects_dir.glob("*/*.jsonl"))


def extract_session_id_fast(transcript_path: Path) -> str | None:
    """Read just the first line to get sessionId without parsing the whole file."""
    try:
        with open(transcript_path) as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                entry = json.loads(line)
                return entry.get("sessionId")
    except (json.JSONDecodeError, OSError):
        pass
    return None


def sync_all(api_base: str, device_id: str, dry_run: bool = False) -> None:
    """Scan all transcripts, send unprocessed ones to backend."""
    synced = load_synced_sessions()
    transcripts = find_all_transcripts()

    if not transcripts:
        return

    new_count = 0
    skip_count = 0

    for path in transcripts:
        session_id = extract_session_id_fast(path)
        if not session_id:
            continue

        # Skip if we already synced this locally
        if session_id in synced:
            skip_count += 1
            continue

        # Skip tiny transcripts (< 3 lines = probably empty/aborted session)
        try:
            line_count = sum(1 for _ in open(path))
            if line_count < 3:
                synced.add(session_id)
                continue
        except OSError:
            continue

        summary = parse_transcript(str(path))
        if not summary.get("session_id"):
            continue

        if dry_run:
            print(json.dumps(summary, indent=2))
            new_count += 1
            continue

        result = send_summary(api_base, device_id, summary)
        if result:
            synced.add(session_id)
            status = "skipped (already processed)" if result.get("already_processed") else "synced"
            print(f"Session {session_id[:8]}: {status}")
            new_count += 1
        else:
            # Don't mark as synced if the request failed — retry next time
            pass

    if not dry_run:
        save_synced_sessions(synced)

    if new_count == 0 and not dry_run:
        pass  # Silence on no-op (common case for hooks)


def main():
    parser = argparse.ArgumentParser(description="Process Claude Code session transcripts")
    parser.add_argument("--transcript", help="Path to a single transcript .jsonl file")
    parser.add_argument("--sync-all", action="store_true", help="Scan and sync all unprocessed transcripts")
    parser.add_argument("--device-id", help="Device ID (overrides gamify.json)")
    parser.add_argument("--api-base", help="API base URL (overrides gamify.json)")
    parser.add_argument("--dry-run", action="store_true", help="Parse and print without sending")
    args = parser.parse_args()

    # Load config
    device_id = args.device_id
    api_base = args.api_base or DEFAULT_API_BASE
    if not device_id:
        try:
            config = json.loads(GAMIFY_CONFIG.read_text())
            device_id = config["device_id"]
            api_base = config.get("api_base", api_base)
        except (FileNotFoundError, KeyError, json.JSONDecodeError):
            print(f"Config not found: {GAMIFY_CONFIG}", file=sys.stderr)
            sys.exit(1)

    # If called as a hook (no flags), default to sync-all
    if not args.transcript and not args.sync_all:
        # Try reading stdin for hook context (backwards compat)
        try:
            stdin_data = json.loads(sys.stdin.read())
            # Got hook context — run sync-all (covers this + any missed sessions)
        except (json.JSONDecodeError, Exception):
            pass
        sync_all(api_base, device_id, args.dry_run)
        return

    if args.sync_all:
        sync_all(api_base, device_id, args.dry_run)
        return

    # Single transcript mode
    if not args.transcript or not os.path.exists(args.transcript):
        print(f"No transcript found: {args.transcript}", file=sys.stderr)
        sys.exit(1)

    summary = parse_transcript(args.transcript)
    if args.dry_run:
        print(json.dumps(summary, indent=2))
        return

    result = send_summary(api_base, device_id, summary)
    if result:
        status = "skipped (already processed)" if result.get("already_processed") else "synced"
        print(f"Session {summary['session_id'][:8]}: {status}")
        # Also mark it locally
        synced = load_synced_sessions()
        synced.add(summary["session_id"])
        save_synced_sessions(synced)


if __name__ == "__main__":
    main()
