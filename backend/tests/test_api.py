"""
API integration tests — mocks all DB calls at the app.main import level.
Runs without a live Supabase connection.
"""
import uuid
from unittest.mock import MagicMock, patch, call
import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def app_client():
    """
    Patches every DB function imported by app.main so no real Supabase calls
    are made. Yields a dict with the TestClient and key mock handles.
    """
    patches = {
        "get_client": patch("app.main.get_client"),
        "get_device": patch("app.main.get_device"),
        "get_stats": patch("app.main.get_stats"),
        "get_quest_progress": patch("app.main.get_quest_progress"),
        "award_xp": patch("app.main.award_xp"),
        "upsert_stats": patch("app.main.upsert_stats"),
        "upsert_quest_progress": patch("app.main.upsert_quest_progress"),
        "log_raw_event": patch("app.main.log_raw_event"),
        "is_already_processed": patch("app.main.is_already_processed"),
        "make_source_key": patch("app.main.make_source_key"),
    }
    started = {k: p.start() for k, p in patches.items()}

    # Sensible defaults
    started["get_device"].return_value = None
    started["get_stats"].return_value = {}
    started["get_quest_progress"].return_value = {}
    started["is_already_processed"].return_value = False
    started["make_source_key"].return_value = "deadbeef" * 4
    # Health check needs a DB call to succeed
    started["get_client"].return_value = MagicMock()

    from app.main import app
    with TestClient(app, raise_server_exceptions=False) as c:
        yield {"client": c, **started}

    for p in patches.values():
        p.stop()


def _make_device(device_id=None):
    return {
        "device_id": device_id or str(uuid.uuid4()),
        "character_name": "TestHero",
        "created_at": "2026-01-01T00:00:00",
        "show_on_leaderboard": True,
    }


def _make_stats(device_id, xp=150):
    return {
        "device_id": device_id,
        "total_xp": xp,
        "level": 1,
        "current_streak": 3,
        "longest_streak": 5,
        "total_commits": 10,
        "total_test_passes": 4,
        "total_sessions": 7,
        "last_session_date": "2026-02-28",
    }


# ── Health ────────────────────────────────────────────────────────────────────

class TestHealth:
    def test_health_ok(self, app_client):
        c = app_client["client"]
        res = c.get("/health")
        assert res.status_code == 200
        assert res.json()["status"] == "ok"


# ── Device registration ───────────────────────────────────────────────────────

class TestDeviceRegistration:
    def test_register_new_device(self, app_client):
        c = app_client["client"]
        app_client["get_device"].return_value = None
        res = c.post("/api/devices", json={"device_id": str(uuid.uuid4()), "character_name": "Hero"})
        assert res.status_code == 201
        assert res.json()["status"] == "registered"

    def test_register_already_registered(self, app_client):
        c = app_client["client"]
        device_id = str(uuid.uuid4())
        app_client["get_device"].return_value = _make_device(device_id)
        res = c.post("/api/devices", json={"device_id": device_id, "character_name": "Hero"})
        assert res.status_code == 201
        assert res.json()["status"] == "already_registered"

    def test_invalid_uuid_rejected(self, app_client):
        c = app_client["client"]
        res = c.post("/api/devices", json={"device_id": "not-a-uuid", "character_name": "Hero"})
        assert res.status_code == 422

    def test_empty_name_rejected(self, app_client):
        c = app_client["client"]
        res = c.post("/api/devices", json={"device_id": str(uuid.uuid4()), "character_name": ""})
        assert res.status_code == 422

    def test_name_too_long_rejected(self, app_client):
        c = app_client["client"]
        res = c.post("/api/devices", json={"device_id": str(uuid.uuid4()), "character_name": "x" * 31})
        assert res.status_code == 422


# ── Events ────────────────────────────────────────────────────────────────────

class TestEvents:
    def test_event_requires_bearer(self, app_client):
        c = app_client["client"]
        res = c.post("/api/events", json={"hook_event_name": "PostToolUse"})
        assert res.status_code == 422  # Header missing

    def test_event_unknown_device_returns_404(self, app_client):
        c = app_client["client"]
        app_client["get_device"].return_value = None
        res = c.post(
            "/api/events",
            json={"hook_event_name": "PostToolUse", "session_id": str(uuid.uuid4())},
            headers={"Authorization": f"Bearer {uuid.uuid4()}"},
        )
        assert res.status_code == 404

    def test_event_ok_for_known_device(self, app_client):
        c = app_client["client"]
        device_id = str(uuid.uuid4())
        app_client["get_device"].return_value = _make_device(device_id)
        app_client["get_stats"].return_value = _make_stats(device_id)
        res = c.post(
            "/api/events",
            json={"hook_event_name": "SessionStart", "session_id": str(uuid.uuid4())},
            headers={"Authorization": f"Bearer {device_id}"},
        )
        assert res.status_code == 200
        assert res.json()["status"] == "ok"

    def test_event_extra_fields_ignored(self, app_client):
        """HookEvent with extra fields should succeed (extra=ignore)."""
        c = app_client["client"]
        device_id = str(uuid.uuid4())
        app_client["get_device"].return_value = _make_device(device_id)
        app_client["get_stats"].return_value = _make_stats(device_id)
        res = c.post(
            "/api/events",
            json={
                "hook_event_name": "SessionStart",
                "session_id": str(uuid.uuid4()),
                "surprise_field": "should be silently dropped",
            },
            headers={"Authorization": f"Bearer {device_id}"},
        )
        assert res.status_code == 200

    def test_duplicate_event_returns_duplicate(self, app_client):
        c = app_client["client"]
        device_id = str(uuid.uuid4())
        app_client["get_device"].return_value = _make_device(device_id)
        app_client["is_already_processed"].return_value = True
        res = c.post(
            "/api/events",
            json={"hook_event_name": "PostToolUse", "session_id": str(uuid.uuid4())},
            headers={"Authorization": f"Bearer {device_id}"},
        )
        assert res.status_code == 200
        assert res.json()["status"] == "duplicate"


# ── XP accumulation (total_xp bug regression) ────────────────────────────────

class TestTotalXpAccumulation:
    def _commit_event(self, device_id):
        return {
            "hook_event_name": "PostToolUse",
            "tool_name": "Bash",
            "tool_input": {"command": "git commit -m 'fix: something'"},
            "tool_response": {"exit_code": 0},
            "session_id": str(uuid.uuid4()),
        }

    def _test_pass_event(self, device_id):
        return {
            "hook_event_name": "PostToolUse",
            "tool_name": "Bash",
            "tool_input": {"command": "pytest tests/"},
            "tool_response": {"exit_code": 0},
            "session_id": str(uuid.uuid4()),
        }

    def test_commit_event_updates_total_xp(self, app_client):
        """Commit XP (+15) must be persisted to total_xp in user_stats."""
        c = app_client["client"]
        device_id = str(uuid.uuid4())
        initial_xp = 100
        app_client["get_device"].return_value = _make_device(device_id)
        app_client["get_stats"].return_value = _make_stats(device_id, xp=initial_xp)

        # _count_session_commits uses db directly — patch it to return 0 so commit XP fires
        with patch("app.main._count_today_commits", return_value=0):
            res = c.post(
                "/api/events",
                json=self._commit_event(device_id),
                headers={"Authorization": f"Bearer {device_id}"},
            )

        assert res.status_code == 200
        assert res.json()["xp_awarded"] == 15

        upsert_calls = app_client["upsert_stats"].call_args_list
        total_xp_values = [
            c.args[2]["total_xp"]
            for c in upsert_calls
            if len(c.args) > 2 and "total_xp" in c.args[2]
        ]
        assert any(v == initial_xp + 15 for v in total_xp_values), (
            f"Expected total_xp={initial_xp + 15} in upsert_stats calls, got: {total_xp_values}"
        )

    def test_test_pass_event_updates_total_xp(self, app_client):
        """test_pass XP (+8) must be persisted to total_xp in user_stats."""
        c = app_client["client"]
        device_id = str(uuid.uuid4())
        initial_xp = 50
        app_client["get_device"].return_value = _make_device(device_id)
        app_client["get_stats"].return_value = _make_stats(device_id, xp=initial_xp)

        res = c.post(
            "/api/events",
            json=self._test_pass_event(device_id),
            headers={"Authorization": f"Bearer {device_id}"},
        )
        assert res.status_code == 200
        assert res.json()["xp_awarded"] == 8

        upsert_calls = app_client["upsert_stats"].call_args_list
        total_xp_values = [
            c.args[2]["total_xp"]
            for c in upsert_calls
            if len(c.args) > 2 and "total_xp" in c.args[2]
        ]
        assert any(v == initial_xp + 8 for v in total_xp_values), (
            f"Expected total_xp={initial_xp + 8} in upsert_stats calls, got: {total_xp_values}"
        )

    def test_non_xp_event_does_not_set_total_xp(self, app_client):
        """SessionStart with no XP should not write total_xp (beyond existing stats)."""
        c = app_client["client"]
        device_id = str(uuid.uuid4())
        app_client["get_device"].return_value = _make_device(device_id)
        app_client["get_stats"].return_value = _make_stats(device_id, xp=200)

        res = c.post(
            "/api/events",
            json={"hook_event_name": "SessionStart", "session_id": str(uuid.uuid4())},
            headers={"Authorization": f"Bearer {device_id}"},
        )
        assert res.status_code == 200
        assert res.json()["xp_awarded"] == 0

        upsert_calls = app_client["upsert_stats"].call_args_list
        total_xp_values = [
            c.args[2]["total_xp"]
            for c in upsert_calls
            if len(c.args) > 2 and "total_xp" in c.args[2]
        ]
        # No xp_amount > 0, so no total_xp write from the main XP block
        assert not total_xp_values, (
            f"Expected no total_xp upsert for zero-XP event, got: {total_xp_values}"
        )


# ── Profile ───────────────────────────────────────────────────────────────────

class TestProfile:
    def test_profile_not_found(self, app_client):
        c = app_client["client"]
        app_client["get_device"].return_value = None
        res = c.get(f"/api/profile/{uuid.uuid4()}")
        assert res.status_code == 404

    def test_profile_returns_expected_shape(self, app_client):
        c = app_client["client"]
        device_id = str(uuid.uuid4())
        app_client["get_device"].return_value = _make_device(device_id)
        app_client["get_stats"].return_value = _make_stats(device_id, xp=150)
        res = c.get(f"/api/profile/{device_id}")
        assert res.status_code == 200
        body = res.json()
        assert body["character_name"] == "TestHero"
        assert body["total_xp"] == 150
        assert body["level"] >= 1
        assert "quests" in body
        assert "xp_in_level" in body
        assert "xp_to_next_level" in body
        assert "current_streak" in body


# ── Leaderboard ───────────────────────────────────────────────────────────────

class TestLeaderboard:
    def test_leaderboard_ok(self, app_client):
        """Leaderboard endpoint responds 200 (data depends on DB mock)."""
        c = app_client["client"]
        res = c.get("/api/leaderboard")
        assert res.status_code == 200
        assert "leaderboard" in res.json()


# ── Delete ────────────────────────────────────────────────────────────────────

class TestDeleteMe:
    def test_delete_requires_auth(self, app_client):
        c = app_client["client"]
        res = c.delete("/api/me")
        assert res.status_code == 422

    def test_delete_unknown_device_returns_404(self, app_client):
        c = app_client["client"]
        app_client["get_device"].return_value = None
        res = c.delete("/api/me", headers={"Authorization": f"Bearer {uuid.uuid4()}"})
        assert res.status_code == 404

    def test_delete_known_device_succeeds(self, app_client):
        c = app_client["client"]
        device_id = str(uuid.uuid4())
        app_client["get_device"].return_value = _make_device(device_id)
        res = c.delete("/api/me", headers={"Authorization": f"Bearer {device_id}"})
        assert res.status_code == 200


# ── Deduplication key uses tool_use_id ────────────────────────────────────────

class TestDeduplicationKey:
    """
    Regression tests for the bug where tool_call_id was never parsed from the
    hook payload (extra=ignore), causing every PostToolUse in the same session
    to share the same source_key and be silently dropped as duplicates.
    """

    def test_tool_use_id_is_included_in_source_key(self, app_client):
        """Two events with different tool_use_ids must produce different source keys."""
        c = app_client["client"]
        device_id = str(uuid.uuid4())
        session_id = str(uuid.uuid4())
        app_client["get_device"].return_value = _make_device(device_id)
        app_client["get_stats"].return_value = _make_stats(device_id)
        app_client["make_source_key"].side_effect = lambda sid, key: f"{sid}:{key}"

        payload_1 = {
            "hook_event_name": "PostToolUse",
            "tool_name": "Bash",
            "session_id": session_id,
            "tool_use_id": "toolu_001",
            "tool_input": {"command": "git status"},
            "tool_response": {"exit_code": 0},
        }
        payload_2 = {**payload_1, "tool_use_id": "toolu_002"}

        with patch("app.main._count_today_commits", return_value=0):
            c.post("/api/events", json=payload_1, headers={"Authorization": f"Bearer {device_id}"})
            c.post("/api/events", json=payload_2, headers={"Authorization": f"Bearer {device_id}"})

        keys = [call.args[1] for call in app_client["make_source_key"].call_args_list]
        assert len(keys) == 2, f"Expected 2 source key calls, got {len(keys)}"
        assert keys[0] != keys[1], (
            f"Different tool_use_ids must produce different source keys, got: {keys}"
        )

    def test_tool_use_id_parsed_from_payload(self, app_client):
        """tool_use_id in the JSON payload must survive Pydantic parsing."""
        from app.models import HookEvent
        raw = {
            "hook_event_name": "PostToolUse",
            "tool_name": "Bash",
            "session_id": "abc",
            "tool_use_id": "toolu_XYZ",
            "tool_input": {"command": "git commit -m 'x'"},
            "tool_response": {"exit_code": 0},
        }
        event = HookEvent(**raw)
        assert event.tool_use_id == "toolu_XYZ"


# ── Bash output field (output vs stdout) ─────────────────────────────────────

class TestBashOutputField:
    """
    Regression tests for Claude Code sending Bash output as 'output' not 'stdout'.
    total_insertions must be parsed from whichever field is present.
    """

    def test_insertions_parsed_from_output_field(self, app_client):
        """If tool_response has 'output' (Claude Code), insertions must be counted."""
        c = app_client["client"]
        device_id = str(uuid.uuid4())
        app_client["get_device"].return_value = _make_device(device_id)
        app_client["get_stats"].return_value = _make_stats(device_id)

        with patch("app.main._count_today_commits", return_value=0):
            res = c.post(
                "/api/events",
                json={
                    "hook_event_name": "PostToolUse",
                    "tool_name": "Bash",
                    "session_id": str(uuid.uuid4()),
                    "tool_use_id": "toolu_ins_001",
                    "tool_input": {"command": "git commit -m 'feat: add thing'"},
                    "tool_response": {
                        "exit_code": 0,
                        "output": "[main abc1234] feat: add thing\n 2 files changed, 55 insertions(+), 3 deletions(-)",
                    },
                },
                headers={"Authorization": f"Bearer {device_id}"},
            )

        assert res.status_code == 200
        upsert_calls = app_client["upsert_stats"].call_args_list
        insertion_updates = [
            call.args[2]["total_insertions"]
            for call in upsert_calls
            if len(call.args) > 2 and "total_insertions" in call.args[2]
        ]
        assert insertion_updates == [55], (
            f"Expected total_insertions=55 from 'output' field, got: {insertion_updates}"
        )

    def test_insertions_parsed_from_stdout_field(self, app_client):
        """If tool_response has 'stdout' (legacy/manual), insertions still work."""
        c = app_client["client"]
        device_id = str(uuid.uuid4())
        app_client["get_device"].return_value = _make_device(device_id)
        app_client["get_stats"].return_value = _make_stats(device_id)

        with patch("app.main._count_today_commits", return_value=0):
            res = c.post(
                "/api/events",
                json={
                    "hook_event_name": "PostToolUse",
                    "tool_name": "Bash",
                    "session_id": str(uuid.uuid4()),
                    "tool_use_id": "toolu_ins_002",
                    "tool_input": {"command": "git commit -m 'fix: something'"},
                    "tool_response": {
                        "exit_code": 0,
                        "stdout": "1 file changed, 20 insertions(+)",
                    },
                },
                headers={"Authorization": f"Bearer {device_id}"},
            )

        assert res.status_code == 200
        upsert_calls = app_client["upsert_stats"].call_args_list
        insertion_updates = [
            call.args[2]["total_insertions"]
            for call in upsert_calls
            if len(call.args) > 2 and "total_insertions" in call.args[2]
        ]
        assert insertion_updates == [20], (
            f"Expected total_insertions=20 from 'stdout' field, got: {insertion_updates}"
        )


# ── Expanded test pattern detection ──────────────────────────────────────────

class TestExpandedTestPatterns:
    """Verify that all common test runner commands are detected as test events."""

    @pytest.mark.parametrize("cmd", [
        "npm run test",
        "python -m pytest tests/",
        "npx jest --verbose",
        "npx vitest run",
        "pnpm test",
        "pnpm run test",
        "yarn run test",
        "bun test",
        "make test",
    ])
    def test_new_test_commands_award_xp(self, app_client, cmd):
        c = app_client["client"]
        device_id = str(uuid.uuid4())
        app_client["get_device"].return_value = _make_device(device_id)
        app_client["get_stats"].return_value = _make_stats(device_id)

        res = c.post(
            "/api/events",
            json={
                "hook_event_name": "PostToolUse",
                "tool_name": "Bash",
                "session_id": str(uuid.uuid4()),
                "tool_use_id": f"toolu_test_{cmd[:10]}",
                "tool_input": {"command": cmd},
                "tool_response": {"exit_code": 0},
            },
            headers={"Authorization": f"Bearer {device_id}"},
        )
        assert res.status_code == 200
        assert res.json()["xp_awarded"] == 8, (
            f"Expected 8 XP for test command '{cmd}', got {res.json()['xp_awarded']}"
        )


# ── Git sync endpoint ────────────────────────────────────────────────────────

class TestGitSync:
    def test_sync_git_merges_stats(self, app_client):
        """sync-git takes max(current, submitted) for each field."""
        c = app_client["client"]
        device_id = str(uuid.uuid4())
        app_client["get_device"].return_value = _make_device(device_id)
        app_client["get_stats"].return_value = {
            **_make_stats(device_id),
            "total_branches": 2,
            "total_prs": 5,
            "total_merged_prs": 3,
            "total_insertions": 100,
            "file_extensions": ["py", "js"],
        }

        res = c.post(
            "/api/me/sync-git",
            json={
                "total_commits": 50,  # higher than 10 in _make_stats
                "total_prs": 3,       # lower than 5 — should keep 5
                "total_merged_prs": 10, # higher than 3
                "total_branches": 8,  # higher than 2
                "total_insertions": 5000,  # higher than 100
                "file_extensions": ["py", "sql", "md"],  # merges with existing
            },
            headers={"Authorization": f"Bearer {device_id}"},
        )
        assert res.status_code == 200
        assert "updated_fields" in res.json()

        upsert_calls = app_client["upsert_stats"].call_args_list
        # Find the sync-git upsert call (first one with file_extensions)
        updates = None
        for call in upsert_calls:
            args = call.args[2]
            if "file_extensions" in args:
                updates = args
                break
        assert updates is not None, "sync-git upsert call not found"
        assert updates["total_commits"] == 50     # max(10, 50)
        assert updates["total_prs"] == 5           # max(5, 3)
        assert updates["total_merged_prs"] == 10   # max(3, 10)
        assert updates["total_branches"] == 8      # max(2, 8)
        assert updates["total_insertions"] == 5000  # max(100, 5000)
        assert set(updates["file_extensions"]) == {"py", "js", "sql", "md"}

    def test_sync_git_requires_auth(self, app_client):
        c = app_client["client"]
        res = c.post("/api/me/sync-git", json={"total_commits": 1})
        assert res.status_code == 422


# ── Session sync (transcript-based) ──────────────────────────────────────────

class TestSyncSession:
    def _session_summary(self, **overrides):
        base = {
            "session_id": str(uuid.uuid4()),
            "started_at": "2026-03-03T10:00:00Z",
            "ended_at": "2026-03-03T11:30:00Z",
            "duration_minutes": 90,
            "commits": 3,
            "test_passes": 5,
            "branches": 1,
            "prs_created": 1,
            "prs_merged": 0,
            "file_extensions": ["py", "js"],
        }
        base.update(overrides)
        return base

    def test_sync_session_updates_stats(self, app_client):
        """sync-session should increment all stat counters and award XP."""
        c = app_client["client"]
        device_id = str(uuid.uuid4())
        app_client["get_device"].return_value = _make_device(device_id)
        app_client["get_stats"].return_value = _make_stats(device_id, xp=100)

        res = c.post(
            "/api/me/sync-session",
            json=self._session_summary(),
            headers={"Authorization": f"Bearer {device_id}"},
        )
        assert res.status_code == 200
        body = res.json()
        assert body["already_processed"] is False
        assert body["xp_awarded"] > 0

        # Check that stats were upserted
        upsert_calls = app_client["upsert_stats"].call_args_list
        assert len(upsert_calls) > 0
        # Find the main upsert call with total_sessions
        updates = None
        for call in upsert_calls:
            args = call.args[2]
            if "total_sessions" in args:
                updates = args
                break
        assert updates is not None, "sync-session upsert call not found"
        assert updates["total_sessions"] == 8  # was 7, +1
        assert updates["total_commits"] == 13  # was 10, +3
        assert updates["total_prs"] == 1  # was 0 (missing from _make_stats), +1

    def test_sync_session_dedup(self, app_client):
        """Sending the same session_id twice should return already_processed."""
        c = app_client["client"]
        device_id = str(uuid.uuid4())
        app_client["get_device"].return_value = _make_device(device_id)
        app_client["get_stats"].return_value = _make_stats(device_id)
        app_client["is_already_processed"].return_value = True

        res = c.post(
            "/api/me/sync-session",
            json=self._session_summary(),
            headers={"Authorization": f"Bearer {device_id}"},
        )
        assert res.status_code == 200
        assert res.json()["already_processed"] is True

    def test_sync_session_xp_breakdown(self, app_client):
        """Verify XP amounts: 3 commits * 15 + 5 tests * 8 + 1 PR * 12 + 1 branch * 5 + session_commit 20."""
        c = app_client["client"]
        device_id = str(uuid.uuid4())
        app_client["get_device"].return_value = _make_device(device_id)
        app_client["get_stats"].return_value = _make_stats(device_id, xp=100)

        res = c.post(
            "/api/me/sync-session",
            json=self._session_summary(commits=3, test_passes=5, prs_created=1, branches=1),
            headers={"Authorization": f"Bearer {device_id}"},
        )
        body = res.json()
        # 3*15=45 + 5*8=40 + 1*12=12 + 1*5=5 + 20(session_commit) + streak_xp
        # Streak XP depends on current streak (3 -> 4, so 40)
        expected_base = 45 + 40 + 12 + 5 + 20
        assert body["xp_awarded"] >= expected_base

    def test_sync_session_requires_auth(self, app_client):
        c = app_client["client"]
        res = c.post("/api/me/sync-session", json=self._session_summary())
        assert res.status_code == 422

    def test_sync_session_empty_session(self, app_client):
        """A session with no commits/tests should still count as a session."""
        c = app_client["client"]
        device_id = str(uuid.uuid4())
        app_client["get_device"].return_value = _make_device(device_id)
        app_client["get_stats"].return_value = _make_stats(device_id, xp=100)

        res = c.post(
            "/api/me/sync-session",
            json=self._session_summary(commits=0, test_passes=0, branches=0, prs_created=0),
            headers={"Authorization": f"Bearer {device_id}"},
        )
        assert res.status_code == 200
        body = res.json()
        assert body["already_processed"] is False
        # Should still award streak XP
        upsert_calls = app_client["upsert_stats"].call_args_list
        updates = None
        for call in upsert_calls:
            args = call.args[2]
            if "total_sessions" in args:
                updates = args
                break
        assert updates is not None
        assert updates["total_sessions"] == 8  # was 7, +1

    def test_sync_session_merges_file_extensions(self, app_client):
        """File extensions should be union-merged with existing ones."""
        c = app_client["client"]
        device_id = str(uuid.uuid4())
        app_client["get_device"].return_value = _make_device(device_id)
        app_client["get_stats"].return_value = {
            **_make_stats(device_id),
            "file_extensions": ["py", "js"],
        }

        res = c.post(
            "/api/me/sync-session",
            json=self._session_summary(file_extensions=["py", "sql", "md"]),
            headers={"Authorization": f"Bearer {device_id}"},
        )
        assert res.status_code == 200
        upsert_calls = app_client["upsert_stats"].call_args_list
        updates = None
        for call in upsert_calls:
            args = call.args[2]
            if "file_extensions" in args:
                updates = args
                break
        assert updates is not None
        assert set(updates["file_extensions"]) == {"py", "js", "sql", "md"}


# ── Debug endpoints ──────────────────────────────────────────────────────────

class TestDebugEndpoints:
    def test_last_event_not_found(self, app_client):
        c = app_client["client"]
        app_client["get_device"].return_value = None
        res = c.get(f"/api/debug/last-event/{uuid.uuid4()}")
        assert res.status_code == 404

    def test_event_count_not_found(self, app_client):
        c = app_client["client"]
        app_client["get_device"].return_value = None
        res = c.get(f"/api/debug/event-count/{uuid.uuid4()}")
        assert res.status_code == 404
