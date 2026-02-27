"""
Streak tracking — pure functions, no DB access.
"""
from datetime import date, timedelta


def compute_streak_xp(
    last_session_date: date | None,
    current_streak: int,
    today: date,
) -> tuple[int, int]:
    """
    Returns (xp_to_award, new_streak_value).
    Call once per day; caller deduplicates via last_session_date.
    """
    if last_session_date == today:
        return 0, current_streak

    yesterday = today - timedelta(days=1)

    if last_session_date == yesterday:
        new_streak = current_streak + 1
    else:
        new_streak = 1

    xp = 10 * new_streak
    return xp, new_streak
