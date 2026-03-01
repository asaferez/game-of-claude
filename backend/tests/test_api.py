"""
API integration tests — mocks all DB calls at the app.main import level.
Runs without a live Supabase connection.
"""
import uuid
from unittest.mock import MagicMock, patch
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
        assert res.json()["status"] == "deleted"
