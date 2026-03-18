"""
Tests for OTLP receiver endpoints (/v1/metrics and /v1/logs).
Mocks all DB calls — runs without a live Supabase connection.
"""
import uuid
from unittest.mock import MagicMock, patch
import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def app_client():
    """Patches DB functions for both app.main and app.otlp modules."""
    patches = {
        "main_get_client": patch("app.main.get_client"),
        "main_get_device": patch("app.main.get_device"),
        "main_get_stats": patch("app.main.get_stats"),
        "main_get_quest_progress": patch("app.main.get_quest_progress"),
        "main_award_xp": patch("app.main.award_xp"),
        "main_upsert_stats": patch("app.main.upsert_stats"),
        "main_upsert_quest_progress": patch("app.main.upsert_quest_progress"),
        "main_log_raw_event": patch("app.main.log_raw_event"),
        "main_is_already_processed": patch("app.main.is_already_processed"),
        "main_make_source_key": patch("app.main.make_source_key"),
        # OTLP module patches
        "otlp_get_client": patch("app.otlp.get_client"),
        "otlp_get_device": patch("app.otlp.get_device"),
        "otlp_get_stats": patch("app.otlp.get_stats"),
        "otlp_get_quest_progress": patch("app.otlp.get_quest_progress"),
        "otlp_award_xp": patch("app.otlp.award_xp"),
        "otlp_upsert_stats": patch("app.otlp.upsert_stats"),
        "otlp_upsert_quest_progress": patch("app.otlp.upsert_quest_progress"),
        "otlp_log_raw_event": patch("app.otlp.log_raw_event"),
        "otlp_is_already_processed": patch("app.otlp.is_already_processed"),
        "otlp_make_source_key": patch("app.otlp.make_source_key"),
        "otlp_count_today_xp_source": patch("app.otlp.count_today_xp_source"),
    }
    started = {k: p.start() for k, p in patches.items()}

    # Sensible defaults
    for prefix in ("main_", "otlp_"):
        if f"{prefix}get_device" in started:
            started[f"{prefix}get_device"].return_value = None
        if f"{prefix}get_stats" in started:
            started[f"{prefix}get_stats"].return_value = {}
        if f"{prefix}get_quest_progress" in started:
            started[f"{prefix}get_quest_progress"].return_value = {}
        if f"{prefix}is_already_processed" in started:
            started[f"{prefix}is_already_processed"].return_value = False
        if f"{prefix}make_source_key" in started:
            started[f"{prefix}make_source_key"].side_effect = lambda s, k: f"{s}:{k}"[:32]

    started["main_get_client"].return_value = MagicMock()
    started["otlp_get_client"].return_value = MagicMock()
    started["otlp_count_today_xp_source"].return_value = 0

    from app.main import app
    with TestClient(app, raise_server_exceptions=False) as c:
        yield {"client": c, **started}

    for p in patches.values():
        p.stop()


def _device(device_id=None):
    return {
        "device_id": device_id or str(uuid.uuid4()),
        "character_name": "TestHero",
        "created_at": "2026-01-01T00:00:00",
    }


def _stats(device_id, xp=100):
    return {
        "device_id": device_id,
        "total_xp": xp,
        "level": 1,
        "current_streak": 2,
        "longest_streak": 5,
        "total_commits": 10,
        "total_test_passes": 4,
        "total_sessions": 3,
        "total_prs": 1,
        "total_merged_prs": 0,
        "total_branches": 2,
        "total_insertions": 500,
        "total_session_minutes": 120,
        "last_session_date": "2026-03-15",
        "file_extensions": ["py", "js"],
    }


def _make_metrics_payload(metric_name, value=1, attributes=None):
    """Build an ExportMetricsServiceRequest JSON with a single Sum metric."""
    dp_attrs = []
    if attributes:
        dp_attrs = [
            {"key": k, "value": {"stringValue": v}} for k, v in attributes.items()
        ]
    return {
        "resourceMetrics": [{
            "resource": {
                "attributes": [
                    {"key": "session.id", "value": {"stringValue": "test-session-123"}},
                ]
            },
            "scopeMetrics": [{
                "metrics": [{
                    "name": metric_name,
                    "sum": {
                        "dataPoints": [{
                            "asInt": str(value),
                            "timeUnixNano": "1710000000000000000",
                            "startTimeUnixNano": "1709999000000000000",
                            "attributes": dp_attrs,
                        }]
                    }
                }]
            }]
        }]
    }


def _make_logs_payload(event_name, tool_name="Bash", success="true", tool_params=None):
    """Build an ExportLogsServiceRequest JSON with a single tool_result log record."""
    attrs = [
        {"key": "tool_name", "value": {"stringValue": tool_name}},
        {"key": "success", "value": {"stringValue": success}},
    ]
    if tool_params:
        import json
        attrs.append({"key": "tool_parameters", "value": {"stringValue": json.dumps(tool_params)}})
    return {
        "resourceLogs": [{
            "resource": {
                "attributes": [
                    {"key": "session.id", "value": {"stringValue": "test-session-123"}},
                ]
            },
            "scopeLogs": [{
                "logRecords": [{
                    "timeUnixNano": "1710000000000000000",
                    "body": {"stringValue": event_name},
                    "attributes": attrs,
                }]
            }]
        }]
    }


# ── OTLP Metrics endpoint ────────────────────────────────────────────────────

class TestOtlpMetrics:
    def test_requires_auth(self, app_client):
        c = app_client["client"]
        res = c.post("/v1/metrics", json=_make_metrics_payload("claude_code.commit.count"))
        assert res.status_code == 401

    def test_unknown_device_returns_404(self, app_client):
        c = app_client["client"]
        app_client["main_get_device"].return_value = None
        res = c.post(
            "/v1/metrics",
            json=_make_metrics_payload("claude_code.commit.count"),
            headers={"Authorization": f"Bearer {uuid.uuid4()}"},
        )
        assert res.status_code == 404

    def test_commit_metric_awards_xp(self, app_client):
        c = app_client["client"]
        device_id = str(uuid.uuid4())
        app_client["main_get_device"].return_value = _device(device_id)
        app_client["otlp_get_device"].return_value = _device(device_id)
        app_client["otlp_get_stats"].return_value = _stats(device_id)

        res = c.post(
            "/v1/metrics",
            json=_make_metrics_payload("claude_code.commit.count"),
            headers={"Authorization": f"Bearer {device_id}"},
        )
        assert res.status_code == 200
        body = res.json()
        # 15 XP for commit + 20 XP session-commit bonus (first commit in session)
        assert body["xp_awarded"] == 35

        # Verify award_xp was called with "commit" and "session_commit"
        app_client["otlp_award_xp"].assert_called()
        calls = app_client["otlp_award_xp"].call_args_list
        commit_calls = [c for c in calls if c.args[2] == "commit"]
        assert len(commit_calls) == 1
        assert commit_calls[0].args[3] == 15
        session_commit_calls = [c for c in calls if c.args[2] == "session_commit"]
        assert len(session_commit_calls) == 1
        assert session_commit_calls[0].args[3] == 20

    def test_pr_metric_awards_xp(self, app_client):
        c = app_client["client"]
        device_id = str(uuid.uuid4())
        app_client["main_get_device"].return_value = _device(device_id)
        app_client["otlp_get_device"].return_value = _device(device_id)
        app_client["otlp_get_stats"].return_value = _stats(device_id)

        res = c.post(
            "/v1/metrics",
            json=_make_metrics_payload("claude_code.pull_request.count"),
            headers={"Authorization": f"Bearer {device_id}"},
        )
        assert res.status_code == 200
        assert res.json()["xp_awarded"] == 12

    def test_session_metric_updates_streak(self, app_client):
        c = app_client["client"]
        device_id = str(uuid.uuid4())
        app_client["main_get_device"].return_value = _device(device_id)
        app_client["otlp_get_device"].return_value = _device(device_id)
        app_client["otlp_get_stats"].return_value = _stats(device_id)

        res = c.post(
            "/v1/metrics",
            json=_make_metrics_payload("claude_code.session.count"),
            headers={"Authorization": f"Bearer {device_id}"},
        )
        assert res.status_code == 200

        # Should have upserted stats with streak info
        upsert_calls = app_client["otlp_upsert_stats"].call_args_list
        streak_updates = [
            c.args[2] for c in upsert_calls
            if len(c.args) > 2 and "current_streak" in c.args[2]
        ]
        assert len(streak_updates) > 0

    def test_loc_metric_tracks_insertions(self, app_client):
        c = app_client["client"]
        device_id = str(uuid.uuid4())
        app_client["main_get_device"].return_value = _device(device_id)
        app_client["otlp_get_device"].return_value = _device(device_id)
        app_client["otlp_get_stats"].return_value = _stats(device_id)

        res = c.post(
            "/v1/metrics",
            json=_make_metrics_payload("claude_code.lines_of_code.count", value=42, attributes={"type": "added"}),
            headers={"Authorization": f"Bearer {device_id}"},
        )
        assert res.status_code == 200

        upsert_calls = app_client["otlp_upsert_stats"].call_args_list
        insertion_updates = [
            c.args[2]["total_insertions"] for c in upsert_calls
            if len(c.args) > 2 and "total_insertions" in c.args[2]
        ]
        assert 542 in insertion_updates  # 500 existing + 42 new

    def test_commit_metric_capped_at_10_per_day(self, app_client):
        c = app_client["client"]
        device_id = str(uuid.uuid4())
        app_client["main_get_device"].return_value = _device(device_id)
        app_client["otlp_get_device"].return_value = _device(device_id)
        app_client["otlp_get_stats"].return_value = _stats(device_id)
        app_client["otlp_count_today_xp_source"].return_value = 10  # already at cap

        res = c.post(
            "/v1/metrics",
            json=_make_metrics_payload("claude_code.commit.count"),
            headers={"Authorization": f"Bearer {device_id}"},
        )
        assert res.status_code == 200
        # Commit XP is 0 (capped), but session-commit bonus (20) still fires
        assert res.json()["xp_awarded"] == 20

    def test_dedup_skips_already_processed(self, app_client):
        c = app_client["client"]
        device_id = str(uuid.uuid4())
        app_client["main_get_device"].return_value = _device(device_id)
        app_client["otlp_get_device"].return_value = _device(device_id)
        app_client["otlp_get_stats"].return_value = _stats(device_id)
        app_client["otlp_is_already_processed"].return_value = True

        res = c.post(
            "/v1/metrics",
            json=_make_metrics_payload("claude_code.commit.count"),
            headers={"Authorization": f"Bearer {device_id}"},
        )
        assert res.status_code == 200
        assert res.json()["xp_awarded"] == 0

    def test_unknown_metric_ignored(self, app_client):
        c = app_client["client"]
        device_id = str(uuid.uuid4())
        app_client["main_get_device"].return_value = _device(device_id)
        app_client["otlp_get_device"].return_value = _device(device_id)
        app_client["otlp_get_stats"].return_value = _stats(device_id)

        res = c.post(
            "/v1/metrics",
            json=_make_metrics_payload("claude_code.token.usage", value=1000),
            headers={"Authorization": f"Bearer {device_id}"},
        )
        assert res.status_code == 200
        assert res.json()["xp_awarded"] == 0


# ── OTLP Logs endpoint ───────────────────────────────────────────────────────

class TestOtlpLogs:
    def test_requires_auth(self, app_client):
        c = app_client["client"]
        res = c.post("/v1/logs", json=_make_logs_payload("claude_code.tool_result"))
        assert res.status_code == 401

    def test_test_pass_awards_xp(self, app_client):
        c = app_client["client"]
        device_id = str(uuid.uuid4())
        app_client["main_get_device"].return_value = _device(device_id)
        app_client["otlp_get_device"].return_value = _device(device_id)
        app_client["otlp_get_stats"].return_value = _stats(device_id)

        res = c.post(
            "/v1/logs",
            json=_make_logs_payload(
                "claude_code.tool_result",
                tool_name="Bash",
                success="true",
                tool_params={"bash_command": "pytest tests/"},
            ),
            headers={"Authorization": f"Bearer {device_id}"},
        )
        assert res.status_code == 200
        assert res.json()["xp_awarded"] == 8

    def test_test_fail_no_xp(self, app_client):
        c = app_client["client"]
        device_id = str(uuid.uuid4())
        app_client["main_get_device"].return_value = _device(device_id)
        app_client["otlp_get_device"].return_value = _device(device_id)
        app_client["otlp_get_stats"].return_value = _stats(device_id)

        res = c.post(
            "/v1/logs",
            json=_make_logs_payload(
                "claude_code.tool_result",
                tool_name="Bash",
                success="false",
                tool_params={"bash_command": "pytest tests/"},
            ),
            headers={"Authorization": f"Bearer {device_id}"},
        )
        assert res.status_code == 200
        assert res.json()["xp_awarded"] == 0

    def test_branch_creation_tracked(self, app_client):
        c = app_client["client"]
        device_id = str(uuid.uuid4())
        app_client["main_get_device"].return_value = _device(device_id)
        app_client["otlp_get_device"].return_value = _device(device_id)
        app_client["otlp_get_stats"].return_value = _stats(device_id)

        res = c.post(
            "/v1/logs",
            json=_make_logs_payload(
                "claude_code.tool_result",
                tool_name="Bash",
                success="true",
                tool_params={"bash_command": "git checkout -b feature/new"},
            ),
            headers={"Authorization": f"Bearer {device_id}"},
        )
        assert res.status_code == 200
        assert res.json()["xp_awarded"] == 5

        upsert_calls = app_client["otlp_upsert_stats"].call_args_list
        branch_updates = [
            c.args[2]["total_branches"] for c in upsert_calls
            if len(c.args) > 2 and "total_branches" in c.args[2]
        ]
        assert 3 in branch_updates  # was 2, +1

    def test_pr_merge_awards_xp(self, app_client):
        c = app_client["client"]
        device_id = str(uuid.uuid4())
        app_client["main_get_device"].return_value = _device(device_id)
        app_client["otlp_get_device"].return_value = _device(device_id)
        app_client["otlp_get_stats"].return_value = _stats(device_id)

        res = c.post(
            "/v1/logs",
            json=_make_logs_payload(
                "claude_code.tool_result",
                tool_name="Bash",
                success="true",
                tool_params={"bash_command": "gh pr merge 42"},
            ),
            headers={"Authorization": f"Bearer {device_id}"},
        )
        assert res.status_code == 200
        assert res.json()["xp_awarded"] == 20

    def test_edit_tool_tracks_file_extension(self, app_client):
        c = app_client["client"]
        device_id = str(uuid.uuid4())
        app_client["main_get_device"].return_value = _device(device_id)
        app_client["otlp_get_device"].return_value = _device(device_id)
        app_client["otlp_get_stats"].return_value = _stats(device_id)

        res = c.post(
            "/v1/logs",
            json=_make_logs_payload(
                "claude_code.tool_result",
                tool_name="Write",
                success="true",
                tool_params={"file_path": "/home/user/project/schema.sql"},
            ),
            headers={"Authorization": f"Bearer {device_id}"},
        )
        assert res.status_code == 200

        upsert_calls = app_client["otlp_upsert_stats"].call_args_list
        ext_updates = [
            c.args[2]["file_extensions"] for c in upsert_calls
            if len(c.args) > 2 and "file_extensions" in c.args[2]
        ]
        assert any("sql" in exts for exts in ext_updates)

    def test_non_tool_result_event_ignored(self, app_client):
        c = app_client["client"]
        device_id = str(uuid.uuid4())
        app_client["main_get_device"].return_value = _device(device_id)
        app_client["otlp_get_device"].return_value = _device(device_id)
        app_client["otlp_get_stats"].return_value = _stats(device_id)

        res = c.post(
            "/v1/logs",
            json=_make_logs_payload("claude_code.user_prompt"),
            headers={"Authorization": f"Bearer {device_id}"},
        )
        assert res.status_code == 200
        assert res.json()["xp_awarded"] == 0

    def test_various_test_commands(self, app_client):
        """Verify common test runners are detected from OTEL tool_parameters."""
        c = app_client["client"]
        device_id = str(uuid.uuid4())

        for cmd in ["jest", "npm test", "vitest", "go test ./...", "cargo test", "make test"]:
            app_client["main_get_device"].return_value = _device(device_id)
            app_client["otlp_get_device"].return_value = _device(device_id)
            app_client["otlp_get_stats"].return_value = _stats(device_id)
            app_client["otlp_is_already_processed"].return_value = False

            res = c.post(
                "/v1/logs",
                json=_make_logs_payload(
                    "claude_code.tool_result",
                    tool_name="Bash",
                    success="true",
                    tool_params={"bash_command": cmd},
                ),
                headers={"Authorization": f"Bearer {device_id}"},
            )
            assert res.status_code == 200
            assert res.json()["xp_awarded"] == 8, f"Expected 8 XP for test command '{cmd}'"
