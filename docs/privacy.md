# Privacy Policy

**tl;dr**: We store only a random UUID and your chosen character name. No email, no real identity. Delete everything in one command.

## What we store

| Data | Notes |
|------|-------|
| `device_id` (UUID v4) | Random, generated locally at install |
| `character_name` | Your chosen display name, no verification |
| `session_id` | Opaque string from Claude Code |
| `event_type` | e.g. `PostToolUse`, `SessionEnd` |
| Hook `data` payload | See below |
| XP log entries | source + amount + timestamp |
| Quest progress | current value + completion timestamp |

## What's in hook payloads

We receive the full Claude Code hook payload. We act only on:
- `tool_input.command` matching `git commit` → XP
- `tool_input.command` matching test runner patterns + exit_code=0 → XP

We do **not** act on command arguments, file contents, prompt text, or Claude's responses.

## What we do NOT store

- Email address or real name
- GitHub handle
- IP address (beyond Railway's transient request logs)
- Prompt text sent to Claude
- File contents or tool output

## Stop & delete

```bash
game-of-claude stop          # removes hooks from ~/.claude/settings.json instantly
game-of-claude delete-data   # DELETE /api/me — cascades all rows in <1s
```

## Retention

Raw events: 90 days, then purged. XP log and quest progress: until you delete.
