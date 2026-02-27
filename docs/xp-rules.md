# XP Rules

## Design principles

1. **Reward completion, not activity** — a commit > 10 file edits
2. **Quality signals over quantity** — passing tests > running tests > editing files
3. **Never reward volume** — no XP for token count, prompt count, or session duration alone
4. **Cap spam vectors** — commits capped at 3 XP awards per session

## Per-event XP

| Trigger | XP | Signal |
|---------|-----|--------|
| `git commit` in Bash | 15 | Completion |
| Test command + exit_code=0 | 8 | Quality |
| Session ended with ≥1 commit | 20 | Productive session |
| Daily streak (day N) | 10 × N | Consistency |

## Level formula

`level = floor(sqrt(total_xp / 50))`

## Proposing new rules

Open a GitHub issue with the signal source, why it represents positive behavior, and anti-gaming considerations.
