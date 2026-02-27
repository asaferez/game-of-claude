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


def is_commit_command(cmd: str) -> bool:
    return bool(COMMIT_PATTERN.search(cmd))


def is_test_command(cmd: str) -> bool:
    return bool(TEST_PATTERNS.search(cmd))


def compute_xp(event: dict) -> tuple[int, str]:
    """
    Returns (xp_amount, source_label).
    Returns (0, '') if no XP applies.
    """
    hook = event.get("hook_event_name", "")
    tool = event.get("tool_name", "")
    tool_input = event.get("tool_input") or {}
    tool_response = event.get("tool_response") or {}

    if hook == "PostToolUse" and tool == "Bash":
        cmd = tool_input.get("command", "")
        exit_code = tool_response.get("exit_code")

        if is_commit_command(cmd):
            return 15, "commit"

        if is_test_command(cmd) and exit_code == 0:
            return 8, "test_pass"

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
