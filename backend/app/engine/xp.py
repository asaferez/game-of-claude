"""
XP computation rules — pure functions, no DB access.
"""
import re
import math

TEST_PATTERNS = re.compile(
    r"\b(pytest|jest|vitest|npm\s+test|yarn\s+test|go\s+test|cargo\s+test|"
    r"rspec|mocha|phpunit|dotnet\s+test|mvn\s+test|gradle\s+test)\b"
)
COMMIT_PATTERN = re.compile(r"\bgit\s+commit\b")
BRANCH_PATTERN = re.compile(r"\bgit\s+(?:checkout\s+-b|switch\s+-c)\s+\S")
PR_CREATE_PATTERN = re.compile(r"\bgh\s+pr\s+create\b")
PR_MERGE_PATTERN = re.compile(r"\bgh\s+pr\s+merge\b")

# git commit output: "3 files changed, 42 insertions(+), 7 deletions(-)"
COMMIT_STATS_RE = re.compile(
    r"(\d+) files? changed"
    r"(?:, (\d+) insertions?\(\+\))?"
    r"(?:, (\d+) deletions?\(-\))?"
)


def is_commit_command(cmd: str) -> bool:
    return bool(COMMIT_PATTERN.search(cmd))


def is_test_command(cmd: str) -> bool:
    return bool(TEST_PATTERNS.search(cmd))


def is_branch_command(cmd: str) -> bool:
    return bool(BRANCH_PATTERN.search(cmd))


def is_pr_create_command(cmd: str) -> bool:
    return bool(PR_CREATE_PATTERN.search(cmd))


def is_pr_merge_command(cmd: str) -> bool:
    return bool(PR_MERGE_PATTERN.search(cmd))


def parse_commit_stats(stdout: str) -> dict:
    """
    Parse git commit output for files_changed, insertions, deletions.
    Returns empty dict if not found.
    """
    m = COMMIT_STATS_RE.search(stdout or "")
    if not m:
        return {}
    return {
        "files_changed": int(m.group(1)),
        "insertions": int(m.group(2) or 0),
        "deletions": int(m.group(3) or 0),
    }


def extract_file_extension(file_path: str) -> str:
    """Return lowercase file extension (no dot) from a path, or empty string."""
    if not file_path:
        return ""
    name = (file_path.split("/"))[-1]
    parts = name.rsplit(".", 1)
    if len(parts) == 2 and parts[0] and parts[1] and len(parts[1]) <= 10:
        return parts[1].lower()
    return ""


def compute_xp(event: dict) -> tuple[int, str]:
    """
    Returns (xp_amount, source_label).
    source_label can be non-empty even when xp_amount == 0 (e.g. branch tracking).
    Returns (0, '') if no XP or stat source applies.
    """
    hook = event.get("hook_event_name", "")
    tool = event.get("tool_name", "")
    tool_input = event.get("tool_input") or {}
    tool_response = event.get("tool_response") or {}

    if hook == "PostToolUse" and tool == "Bash":
        cmd = tool_input.get("command", "")
        exit_code = tool_response.get("exit_code")

        if is_commit_command(cmd) and exit_code == 0:
            return 15, "commit"

        if is_test_command(cmd) and exit_code == 0:
            return 8, "test_pass"

        if is_branch_command(cmd) and exit_code == 0:
            return 0, "branch"

        if is_pr_create_command(cmd) and exit_code == 0:
            return 10, "pr"

        if is_pr_merge_command(cmd) and exit_code == 0:
            return 20, "merged_pr"

    return 0, ""


def compute_level(total_xp: int) -> int:
    """level = floor(sqrt(total_xp / 50))"""
    return int(math.floor(math.sqrt(max(total_xp, 0) / 50)))


def xp_for_level(level: int) -> int:
    """Minimum XP needed to reach this level."""
    return level * level * 50


def level_title(level: int) -> str:
    titles = [
        (30, "Legendary Promptsmith"),
        (20, "Architecture Overlord"),
        (15, "Refactor Mage"),
        (10, "Code Conjurer"),
        (5,  "Context Crafter"),
        (1,  "Prompt Padawan"),
        (0,  "New Recruit"),
    ]
    for threshold, title in titles:
        if level >= threshold:
            return title
    return "New Recruit"
