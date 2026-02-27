"""
Quest definitions and progress logic.
"""
from dataclasses import dataclass
from datetime import date


@dataclass
class Quest:
    id: str
    name: str
    type: str           # 'daily' | 'progressive'
    goal: int
    xp_reward: int
    counter: str        # which user_stats column drives this quest
    description: str


QUESTS: list[Quest] = [
    # Daily quests
    Quest("daily_ship_it",        "Ship It",        "daily",       1,   15, "commits_today",              "Make at least 1 commit today"),
    Quest("daily_quality_check",  "Quality Check",  "daily",       1,   10, "test_passes_today",          "Run tests and pass them today"),
    Quest("daily_code_today",     "Code Today",     "daily",       1,   20, "sessions_with_commit_today", "End a session with a commit"),

    # Progressive: commits
    Quest("prog_first_blood",     "First Blood",       "progressive", 1,   50,  "total_commits", "Make your first commit"),
    Quest("prog_getting_started", "Getting Started",   "progressive", 5,   75,  "total_commits", "Make 5 commits"),
    Quest("prog_shipping_machine","Shipping Machine",  "progressive", 50,  200, "total_commits", "Make 50 commits"),

    # Progressive: tests
    Quest("prog_test_believer",   "Test Believer",    "progressive", 10,  100, "total_test_passes", "Pass tests 10 times"),
    Quest("prog_test_evangelist", "Test Evangelist",  "progressive", 100, 500, "total_test_passes", "Pass tests 100 times"),

    # Progressive: streaks
    Quest("prog_streak_7",  "Consistent Coder",  "progressive", 7,  150,  "longest_streak", "7-day coding streak"),
    Quest("prog_streak_30", "Legendary Streak",  "progressive", 30, 1000, "longest_streak", "30-day coding streak"),

    # Progressive: PRs
    Quest("prog_pr_maker",   "PR Maker",   "progressive", 1,  100, "total_prs", "Create your first PR"),
    Quest("prog_pr_machine", "PR Machine", "progressive", 10, 300, "total_prs", "Create 10 PRs"),

    # Craft
    Quest("craft_polyglot", "Polyglot", "progressive", 5, 75, "unique_extensions", "Work in 5 different file types"),
]

QUEST_BY_ID: dict[str, Quest] = {q.id: q for q in QUESTS}


def get_counter_value(stats: dict, progress_row: dict | None, quest: Quest, today: date) -> int:
    if quest.type == "daily":
        if progress_row is None:
            return 0
        if progress_row.get("reset_at") != str(today):
            return 0
        return progress_row.get("current_value", 0)
    else:
        if quest.counter == "unique_extensions":
            return len(stats.get("file_extensions") or [])
        return stats.get(quest.counter, 0)


def quests_to_check_for_event(event_source: str) -> list[Quest]:
    relevant: dict[str, list[str]] = {
        "commit":         ["daily_ship_it", "daily_code_today",
                           "prog_first_blood", "prog_getting_started", "prog_shipping_machine"],
        "test_pass":      ["daily_quality_check", "prog_test_believer", "prog_test_evangelist"],
        "streak":         ["prog_streak_7", "prog_streak_30"],
        "session_commit": ["daily_code_today"],
        "pr":             ["prog_pr_maker", "prog_pr_machine"],
        "file_extension": ["craft_polyglot"],
    }
    ids = relevant.get(event_source, [])
    return [QUEST_BY_ID[i] for i in ids if i in QUEST_BY_ID]
