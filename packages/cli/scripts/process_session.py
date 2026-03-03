#!/usr/bin/env python3
"""
Process a Claude Code session transcript and send a summary to the backend.

Called as a SessionEnd command hook. Reads hook context from stdin (JSON with
session_id, transcript_path), parses the transcript, and POSTs a session
summary to /api/me/sync-session.

Can also be called directly for backfill:
    python3 process_session.py --transcript /path/to/session.jsonl --device-id <id>
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

    with open(transcript_path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue

            # Track timestamps
            ts = entry.get("timestamp")
            if ts:
                if not first_ts:
                    first_ts = ts
                last_ts = ts

            # Extract session_id from first entry
            session_id = entry.get("sessionId")

            # Look for tool_use blocks in assistant messages
            if entry.get("type") != "assistant":
                continue

            msg = entry.get("message", {})
            for block in msg.get("content", []):
                if block.get("type") != "tool_use":
                    continue

                tool_name = block.get("name", "")
                tool_input = block.get("input", {})

                # Bash commands
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

                # File extensions from Edit/Write
                elif tool_name in ("Edit", "Write"):
                    ext = extract_file_extension(tool_input.get("file_path", ""))
                    if ext:
                        file_extensions.add(ext)

    # Calculate session duration in minutes
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


def main():
    parser = argparse.ArgumentParser(description="Process a Claude Code session transcript")
    parser.add_argument("--transcript", help="Path to transcript .jsonl file")
    parser.add_argument("--device-id", help="Device ID (overrides gamify.json)")
    parser.add_argument("--api-base", help="API base URL (overrides gamify.json)")
    parser.add_argument("--dry-run", action="store_true", help="Parse and print summary without sending")
    args = parser.parse_args()

    # Read hook context from stdin if no --transcript flag
    transcript_path = args.transcript
    if not transcript_path:
        try:
            stdin_data = json.loads(sys.stdin.read())
            transcript_path = stdin_data.get("transcript_path")
        except (json.JSONDecodeError, Exception):
            pass

    if not transcript_path or not os.path.exists(transcript_path):
        print(f"No transcript found: {transcript_path}", file=sys.stderr)
        sys.exit(1)

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

    # Parse transcript
    summary = parse_transcript(transcript_path)

    if args.dry_run:
        print(json.dumps(summary, indent=2))
        return

    # Send to backend
    result = send_summary(api_base, device_id, summary)
    if result:
        status = "skipped (already processed)" if result.get("already_processed") else "synced"
        print(f"Session {summary['session_id'][:8]}: {status}")


if __name__ == "__main__":
    main()
