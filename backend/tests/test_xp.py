import pytest
from app.engine.xp import (
    compute_xp, compute_level, xp_for_level, level_title,
    parse_commit_stats, extract_file_extension,
)


def make_bash_event(cmd: str, exit_code: int = 0, stdout: str = "") -> dict:
    return {
        "hook_event_name": "PostToolUse",
        "tool_name": "Bash",
        "session_id": "test-session",
        "tool_input": {"command": cmd},
        "tool_response": {"exit_code": exit_code, "stdout": stdout},
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

    def test_commit_fail_no_xp(self):
        xp, _ = compute_xp(make_bash_event("git commit -m 'wip'", exit_code=1))
        assert xp == 0

    def test_test_pass_awards_xp(self):
        for cmd in ["pytest", "jest", "vitest", "npm test", "go test ./...", "cargo test"]:
            xp, source = compute_xp(make_bash_event(cmd, exit_code=0))
            assert xp == 8, f"Expected 8 XP for: {cmd}"
            assert source == "test_pass"

    def test_test_fail_no_xp(self):
        xp, _ = compute_xp(make_bash_event("pytest", exit_code=1))
        assert xp == 0

    def test_branch_checkout_b(self):
        xp, source = compute_xp(make_bash_event("git checkout -b feat/new-thing"))
        assert xp == 0
        assert source == "branch"

    def test_branch_switch_c(self):
        xp, source = compute_xp(make_bash_event("git switch -c fix/bug"))
        assert xp == 0
        assert source == "branch"

    def test_branch_no_name_no_source(self):
        # "git checkout -b" with no branch name shouldn't match
        xp, source = compute_xp(make_bash_event("git checkout -b"))
        assert xp == 0
        assert source == ""

    def test_pr_create_awards_xp(self):
        xp, source = compute_xp(make_bash_event("gh pr create --title 'feat'"))
        assert xp == 10
        assert source == "pr"

    def test_pr_merge_awards_xp(self):
        xp, source = compute_xp(make_bash_event("gh pr merge 42"))
        assert xp == 20
        assert source == "merged_pr"

    def test_pr_create_fail_no_xp(self):
        xp, _ = compute_xp(make_bash_event("gh pr create --title 'feat'", exit_code=1))
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


class TestParseCommitStats:
    def test_full_output(self):
        stdout = "[main abc123] fix bug\n 3 files changed, 42 insertions(+), 7 deletions(-)"
        stats = parse_commit_stats(stdout)
        assert stats == {"files_changed": 3, "insertions": 42, "deletions": 7}

    def test_only_insertions(self):
        stdout = "1 file changed, 10 insertions(+)"
        stats = parse_commit_stats(stdout)
        assert stats["files_changed"] == 1
        assert stats["insertions"] == 10
        assert stats["deletions"] == 0

    def test_only_deletions(self):
        stdout = "2 files changed, 5 deletions(-)"
        stats = parse_commit_stats(stdout)
        assert stats["files_changed"] == 2
        assert stats["insertions"] == 0
        assert stats["deletions"] == 5

    def test_empty_stdout(self):
        assert parse_commit_stats("") == {}
        assert parse_commit_stats(None) == {}

    def test_no_match(self):
        assert parse_commit_stats("nothing to commit") == {}


class TestExtractFileExtension:
    def test_py_file(self):
        assert extract_file_extension("/home/user/project/main.py") == "py"

    def test_tsx_file(self):
        assert extract_file_extension("src/components/Button.tsx") == "tsx"

    def test_no_extension(self):
        assert extract_file_extension("Makefile") == ""
        assert extract_file_extension("") == ""

    def test_hidden_file_no_ext(self):
        assert extract_file_extension(".gitignore") == ""

    def test_long_extension_ignored(self):
        assert extract_file_extension("file.verylongextension") == ""

    def test_case_normalized(self):
        assert extract_file_extension("Script.PY") == "py"


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
