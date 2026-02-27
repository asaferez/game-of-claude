# Game of Claude

Gamification layer for [Claude Code](https://claude.ai/code). Level up and complete quests while you ship real work — rewarded for good coding practices, never for raw volume.

**MVP**: personal-only experience. Your character, your quests, your stats.

---

## Install

```bash
npx game-of-claude install
```

This will:
1. Ask for a character name
2. Generate an anonymous `device_id` (no email, no account)
3. Write hooks to `~/.claude/settings.json`
4. Give you a dashboard URL

---

## Commands

```bash
game-of-claude status        # XP, level, daily quest progress
game-of-claude stop          # pause tracking (keeps data)
game-of-claude delete-data   # permanently delete all your data
game-of-claude rename        # change character name
```

---

## What earns XP

| Activity | XP | Why |
|----------|-----|-----|
| Git commit | 15 | You shipped something |
| Test passed | 8 | Quality mindset |
| Session ended with a commit | 20 | Productive session |
| Daily streak | 10 × day | Consistency |
| Quest completion | varies | See below |

**Never awarded**: token count, number of prompts, files edited, session length alone.

## Quests

**Daily** (reset each day):
- Ship It — make 1 commit
- Quality Check — pass tests
- Code Today — session ending in a commit

**Progressive**:
- First Blood → Getting Started → Shipping Machine (commit milestones)
- Test Believer → Test Evangelist (test pass milestones)
- 7-day and 30-day streaks
- PR Maker → PR Machine
- Polyglot — 5 different file types

---

## Privacy

- **No PII stored** — only a random `device_id` UUID and your chosen character name
- **Stop anytime**: `game-of-claude stop` removes all hooks instantly
- **Delete anytime**: `game-of-claude delete-data` wipes everything server-side in < 1 second
- Bash commands are received but only `git commit` and test runner patterns are acted on

Full details: [docs/privacy.md](docs/privacy.md)

---

## Architecture

```
packages/cli/       ← npm package (Node.js installer + CLI)
backend/            ← Python FastAPI (Railway)
dashboard/          ← Next.js (Vercel) — coming in Phase 3
supabase/           ← DB migrations
docs/               ← privacy policy, XP rules
```

### Running the backend locally

```bash
cd backend
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # fill in Supabase credentials
uvicorn app.main:app --reload
```

### Running tests

```bash
cd backend
pytest tests/ -v
```

---

## Contributing

PRs welcome. See [docs/xp-rules.md](docs/xp-rules.md) for the XP design rationale.
Open an issue to propose new quest ideas.
