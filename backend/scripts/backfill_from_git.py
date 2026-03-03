#!/usr/bin/env python3
"""
Backfill stats from git log and GitHub API.

The events table lost most historical data due to the pre-fix dedup bug
(PR #13). This script uses git/GitHub as the authoritative source for
commits, PRs, branches, insertions, and file types — then syncs them
to the backend via the /api/me/sync-git endpoint.

Usage:
    python scripts/backfill_from_git.py --repo ~/Private/game-of-claude
    python scripts/backfill_from_git.py --repo ~/Private/game-of-claude --repo ~/Private/other-project
    python scripts/backfill_from_git.py --repo ~/Private/game-of-claude --dry-run

Reads device_id and API base from ~/.claude/gamify.json.
Requires `git` and `gh` CLI tools.
"""

import argparse
import json
import logging
import os
import re
import subprocess
import sys
from pathlib import Path

import requests

logging.basicConfig(level=logging.INFO, format="%(message)s")
log = logging.getLogger(__name__)

GAMIFY_CONFIG = Path.home() / ".claude" / "gamify.json"
DEFAULT_API_BASE = "https://api.gameofclaude.online"

COMMIT_STATS_RE = re.compile(
    r"(\d+) files? changed"
    r"(?:, (\d+) insertions?\(\+\))?"
    r"(?:, (\d+) deletions?\(-\))?"
)


def load_config() -> dict:
    if not GAMIFY_CONFIG.exists():
        sys.exit(f"Config not found: {GAMIFY_CONFIG}\nRun 'npx game-of-claude' to install first.")
    return json.loads(GAMIFY_CONFIG.read_text())


def run(cmd: list[str], cwd: str | None = None) -> str:
    result = subprocess.run(cmd, capture_output=True, text=True, cwd=cwd)
    return result.stdout.strip()


def get_registration_date(api_base: str, device_id: str) -> str | None:
    """Fetch the member_since date from the profile API."""
    try:
        res = requests.get(
            f"{api_base}/api/profile/{device_id}",
            headers={"Authorization": f"Bearer {device_id}"},
            timeout=10,
        )
        if res.ok:
            member_since = res.json().get("member_since", "")
            return member_since[:10] if member_since else None
    except Exception:
        pass
    return None


def count_git_commits(repo_path: str, since: str | None) -> tuple[int, int, set[str]]:
    """Return (commit_count, total_insertions, file_extensions) from git log."""
    cmd = ["git", "log", "--format=", "--shortstat"]
    if since:
        cmd.append(f"--after={since}")

    output = run(cmd, cwd=repo_path)
    total_commits = 0
    total_insertions = 0
    for line in output.splitlines():
        line = line.strip()
        if not line:
            continue
        total_commits += 1
        m = COMMIT_STATS_RE.search(line)
        if m:
            total_insertions += int(m.group(2) or 0)

    # Get file extensions from changed files
    cmd_files = ["git", "log", "--format=", "--name-only"]
    if since:
        cmd_files.append(f"--after={since}")
    files_output = run(cmd_files, cwd=repo_path)

    extensions: set[str] = set()
    for line in files_output.splitlines():
        line = line.strip()
        if not line or "/" not in line and "." not in line:
            continue
        if "." in line:
            ext = line.rsplit(".", 1)[-1].lower()
            if ext and len(ext) <= 10 and ext not in ("lock",):
                extensions.add(ext)

    return total_commits, total_insertions, extensions


def count_git_branches(repo_path: str) -> int:
    """Count remote branches (excluding HEAD)."""
    output = run(["git", "branch", "-r"], cwd=repo_path)
    count = 0
    for line in output.splitlines():
        line = line.strip()
        if line and "HEAD" not in line:
            count += 1
    return count


def get_github_repo_name(repo_path: str) -> str | None:
    """Extract owner/repo from git remote origin URL."""
    output = run(["git", "remote", "get-url", "origin"], cwd=repo_path)
    if not output:
        return None
    # Handle SSH: git@github.com:owner/repo.git
    m = re.search(r"github\.com[:/](.+?)(?:\.git)?$", output)
    return m.group(1) if m else None


def count_github_prs(repo_name: str) -> tuple[int, int]:
    """Return (total_prs, merged_prs) from GitHub API via gh CLI."""
    try:
        output = run([
            "gh", "pr", "list",
            "--state", "all",
            "--limit", "1000",
            "--repo", repo_name,
            "--json", "state",
        ])
        if not output:
            return 0, 0
        prs = json.loads(output)
        total = len(prs)
        merged = sum(1 for p in prs if p.get("state") == "MERGED")
        return total, merged
    except Exception as e:
        log.warning("  Could not query GitHub PRs for %s: %s", repo_name, e)
        return 0, 0


def gather_stats(repo_paths: list[str], since: str | None) -> dict:
    """Aggregate stats across all repos."""
    total_commits = 0
    total_insertions = 0
    total_branches = 0
    total_prs = 0
    total_merged_prs = 0
    all_extensions: set[str] = set()

    for repo_path in repo_paths:
        repo_path = os.path.expanduser(repo_path)
        if not os.path.isdir(os.path.join(repo_path, ".git")):
            log.warning("  Skipping %s (not a git repo)", repo_path)
            continue

        repo_name = os.path.basename(repo_path)
        log.info("\n--- %s ---", repo_name)

        commits, insertions, extensions = count_git_commits(repo_path, since)
        branches = count_git_branches(repo_path)
        log.info("  Commits: %d, Insertions: %d, Branches: %d", commits, insertions, branches)
        log.info("  File types: %s", sorted(extensions))

        total_commits += commits
        total_insertions += insertions
        total_branches += branches
        all_extensions |= extensions

        gh_repo = get_github_repo_name(repo_path)
        if gh_repo:
            prs, merged = count_github_prs(gh_repo)
            log.info("  PRs: %d created, %d merged (from GitHub)", prs, merged)
            total_prs += prs
            total_merged_prs += merged

    return {
        "total_commits": total_commits,
        "total_prs": total_prs,
        "total_merged_prs": total_merged_prs,
        "total_branches": total_branches,
        "total_insertions": total_insertions,
        "file_extensions": sorted(all_extensions),
    }


def main():
    parser = argparse.ArgumentParser(description="Backfill stats from git/GitHub")
    parser.add_argument("--repo", action="append", required=True, help="Path to a git repo (can specify multiple)")
    parser.add_argument("--dry-run", action="store_true", help="Show what would change without writing")
    args = parser.parse_args()

    config = load_config()
    device_id = config["device_id"]
    api_base = config.get("api_base", DEFAULT_API_BASE)

    log.info("Device: %s", device_id[:8])
    log.info("API: %s", api_base)

    # Get registration date to scope git log
    since = get_registration_date(api_base, device_id)
    if since:
        log.info("Member since: %s (filtering git log to this date)", since)
    else:
        log.info("Could not determine registration date, using all git history")

    # Step 1: Call reprocess to get the best stats from existing events
    log.info("\n=== Step 1: Reprocess existing events ===")
    try:
        res = requests.post(
            f"{api_base}/api/me/reprocess",
            headers={"Authorization": f"Bearer {device_id}"},
            timeout=30,
        )
        if res.ok:
            data = res.json()
            log.info("  Reprocess: +%d XP across %d new entries (total: %d XP)",
                     data.get("xp_added", 0), data.get("entries_added", 0), data.get("total_xp", 0))
        else:
            log.warning("  Reprocess failed: %s %s", res.status_code, res.text[:200])
    except Exception as e:
        log.warning("  Reprocess request failed: %s", e)

    # Step 2: Gather stats from git/GitHub
    log.info("\n=== Step 2: Gather git/GitHub stats ===")
    git_stats = gather_stats(args.repo, since)

    log.info("\n=== Aggregated git stats ===")
    for key, val in git_stats.items():
        log.info("  %s: %s", key, val)

    # Step 3: Fetch current profile to show the diff
    log.info("\n=== Step 3: Current vs git stats ===")
    try:
        res = requests.get(
            f"{api_base}/api/profile/{device_id}",
            headers={"Authorization": f"Bearer {device_id}"},
            timeout=10,
        )
        if res.ok:
            profile = res.json()
            fields = ["total_commits", "total_prs", "total_merged_prs",
                      "total_branches", "total_insertions"]
            for field in fields:
                current = profile.get(field, 0)
                git_val = git_stats.get(field, 0)
                marker = " <-- DRIFT" if git_val > current else ""
                log.info("  %-20s current=%-6s git=%-6s%s", field, current, git_val, marker)
            current_exts = profile.get("unique_extensions", 0)
            git_exts = len(git_stats.get("file_extensions", []))
            marker = " <-- DRIFT" if git_exts > current_exts else ""
            log.info("  %-20s current=%-6s git=%-6s%s", "unique_extensions", current_exts, git_exts, marker)
    except Exception as e:
        log.warning("  Could not fetch profile: %s", e)

    if args.dry_run:
        log.info("\n--dry-run: no changes written")
        return

    # Step 4: Sync git stats to backend
    log.info("\n=== Step 4: Syncing to backend ===")
    try:
        res = requests.post(
            f"{api_base}/api/me/sync-git",
            headers={
                "Authorization": f"Bearer {device_id}",
                "Content-Type": "application/json",
            },
            json=git_stats,
            timeout=10,
        )
        if res.ok:
            data = res.json()
            log.info("  Sync complete: updated %s", data.get("updated_fields", []))
        else:
            log.error("  Sync failed: %s %s", res.status_code, res.text[:200])
    except Exception as e:
        log.error("  Sync request failed: %s", e)

    # Step 5: Show final profile
    log.info("\n=== Final profile ===")
    try:
        res = requests.get(
            f"{api_base}/api/profile/{device_id}",
            headers={"Authorization": f"Bearer {device_id}"},
            timeout=10,
        )
        if res.ok:
            profile = res.json()
            log.info("  Total XP: %d (Level %d — %s)", profile["total_xp"], profile["level"], profile["level_title"])
            log.info("  Commits: %d, PRs: %d, Merged: %d, Branches: %d",
                     profile["total_commits"], profile["total_prs"],
                     profile["total_merged_prs"], profile["total_branches"])
            log.info("  Insertions: %d, Languages: %d, Sessions: %d",
                     profile["total_insertions"], profile["unique_extensions"],
                     profile["total_sessions"])
            log.info("  Streak: %dd (best: %dd), Coding time: %dm",
                     profile["current_streak"], profile["longest_streak"],
                     profile["total_session_minutes"])
    except Exception as e:
        log.warning("  Could not fetch final profile: %s", e)


if __name__ == "__main__":
    main()
