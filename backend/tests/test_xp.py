import pytest
from app.engine.xp import compute_xp, compute_level, xp_for_level, level_title


def make_bash_event(cmd: str, exit_code: int = 0) -> dict:
    return {
        "hook_event_name": "PostToolUse",
        "tool_name": "Bash",
        "session_id": "test-session",
        "tool_input": {"command": cmd},
        "tool_response": {"exit_code": exit_code},
    }


class TestComputeXP:
    def test_commit_awards_xp(self):
        xp, source = compute_xp(make_bash_event("git commit -m 'fix bug'"))
        assert xp == 15
        assert source == "commit"

    def test_commit_with_message_variants(self):
        for cmd in ["git commit -m 'test'", "git commit --amend", "git commit -am 'wip'"]:
            xp, source = compute_xp(make_bash_event(cmd))
            assert xp == 15, f"Expected 15 XP for: {cmd}"
            assert source == "commit"

    def test_test_pass_awards_xp(self):
        for cmd in ["pytest", "jest", "vitest", "npm test", "go test ./...", "cargo test"]:
            xp, source = compute_xp(make_bash_event(cmd, exit_code=0))
            assert xp == 8, f"Expected 8 XP for: {cmd}"
            assert source == "test_pass"

    def test_test_fail_no_xp(self):
        xp, _ = compute_xp(make_bash_event("pytest", exit_code=1))
        assert xp == 0

    def test_unknown_bash_command_no_xp(self):
        xp, _ = compute_xp(make_bash_event("ls -la"))
        assert xp == 0

    def test_non_bash_tool_no_xp(self):
        xp, _ = compute_xp({"hook_event_name": "PostToolUse", "tool_name": "Edit", "session_id": "s1", "tool_input": {"file_path": "foo.py"}})
        assert xp == 0

    def test_session_start_no_xp(self):
        xp, _ = compute_xp({"hook_event_name": "SessionStart", "session_id": "s1"})
        assert xp == 0


class TestComputeLevel:
    def test_zero_xp_is_level_0(self):
        assert compute_level(0) == 0

    def test_level_1_at_50(self):
        assert compute_level(50) == 1

    def test_level_5_at_1250(self):
        assert compute_level(1250) == 5

    def test_level_10_at_5000(self):
        assert compute_level(5000) == 10

    def test_negative_xp_safe(self):
        assert compute_level(-100) == 0

    def test_xp_for_level_roundtrips(self):
        for lvl in range(1, 20):
            assert compute_level(xp_for_level(lvl)) == lvl


class TestLevelTitle:
    def test_level_0_is_new_recruit(self):
        assert level_title(0) == "New Recruit"

    def test_level_1_is_padawan(self):
        assert level_title(1) == "Prompt Padawan"

    def test_level_30_is_legendary(self):
        assert level_title(30) == "Legendary Promptsmith"
