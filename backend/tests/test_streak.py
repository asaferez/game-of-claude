from datetime import date, timedelta
from app.engine.streak import compute_streak_xp

TODAY = date(2026, 2, 27)
YESTERDAY = TODAY - timedelta(days=1)
TWO_DAYS_AGO = TODAY - timedelta(days=2)


class TestComputeStreakXP:
    def test_first_session_ever_starts_streak_at_1(self):
        xp, new_streak = compute_streak_xp(None, 0, TODAY)
        assert new_streak == 1
        assert xp == 10

    def test_consecutive_day_increments_streak(self):
        xp, new_streak = compute_streak_xp(YESTERDAY, 5, TODAY)
        assert new_streak == 6
        assert xp == 60

    def test_same_day_returns_zero(self):
        xp, new_streak = compute_streak_xp(TODAY, 5, TODAY)
        assert xp == 0
        assert new_streak == 5

    def test_broken_streak_resets_to_1(self):
        xp, new_streak = compute_streak_xp(TWO_DAYS_AGO, 10, TODAY)
        assert new_streak == 1
        assert xp == 10

    def test_streak_xp_scales(self):
        xp, streak = compute_streak_xp(YESTERDAY, 29, TODAY)
        assert streak == 30
        assert xp == 300
