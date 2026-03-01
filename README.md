# Game of Claude

Gamification layer for [Claude Code](https://claude.ai/code). Level up and complete quests while you ship real work — rewarded for good coding practices, never for raw volume.

**[Install](https://gameofclaude.online/install)** · **[Leaderboard](https://gameofclaude.online/leaderboard)**

---

## Quick start (2 minutes)

```bash
npx game-of-claude install
```

1. Enter a character name (no email, no account)
2. Hooks are written to `~/.claude/settings.json` automatically
3. Bookmark the dashboard URL it prints
4. **Restart Claude Code** — hooks activate on the next session
5. Code as usual — XP flows as you work

> **Tip:** For a persistent global binary run `npm install -g game-of-claude` once.
> Then `game-of-claude status` works anywhere without re-downloading.

---

## Commands

```bash
game-of-claude status        # XP, level, daily quest progress in terminal
game-of-claude stop          # pause tracking (keeps all data)
game-of-claude rename        # change character name
game-of-claude delete-data   # permanently delete all your data
```

---

## What earns XP

| Activity | XP | Why |
|----------|-----|-----|
| Install | +25 | Welcome bonus — you're in |
| First session | +10 | Hooks confirmed working |
| Git commit | +15 | You shipped something |
| Test passed | +8 | Quality mindset |
| Session ended with a commit | +20 | Productive session |
| Daily streak (day N) | +10×N | Consistency |
| Quest completion | varies | See below |

**Never awarded**: token count, number of prompts, files edited, session length alone.

---

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
- **What's tracked**: session start/end, `git commit` commands, test runner exit codes
- **What's NOT tracked**: prompt text, file contents, code diffs, error messages
- **Stop anytime**: `game-of-claude stop` removes all hooks instantly
- **Delete anytime**: `game-of-claude delete-data` wipes everything server-side in < 1 second

Full details: [docs/privacy.md](docs/privacy.md)

---

## Architecture

```
packages/cli/       ← npm package (Node.js installer + CLI)
backend/            ← Python FastAPI (Railway)
dashboard/          ← Next.js dashboard (Vercel)
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

### Running the dashboard locally

```bash
cd dashboard
npm install
cp .env.local.example .env.local   # set NEXT_PUBLIC_API_BASE
npm run dev
```

---

## Contributing

PRs welcome. See [docs/xp-rules.md](docs/xp-rules.md) for the XP design rationale.
Open an issue to propose new quest ideas.
