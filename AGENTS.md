# ChubbyFireBot Agent Guidelines

## Test-Driven Development (MANDATORY)

**ALL features and changes MUST follow TDD.**

### TDD Workflow

1. **RED**: Write a failing test first
2. **GREEN**: Write minimal code to make the test pass
3. **REFACTOR**: Clean up while keeping tests green

### Rules

- No production code without a failing test
- Tests must be committed with the feature code
- Run full test suite before committing: `pytest tests/`
- Minimum 80% coverage for new code
- Mock external services (Reddit, Discord, Claude) in tests

### Test Structure

```
tests/
├── unit/                    # Fast, isolated tests
│   ├── test_decision_engine.py
│   ├── test_rule_engine.py
│   └── test_reddit_client.py
├── integration/             # Tests with mocked external services
│   ├── test_mod_queue_monitor.py
│   └── test_discord_integration.py
└── conftest.py              # Shared fixtures
```

---

## Credential Management

### Environment Variables

All secrets go in `.env` (gitignored). Template is `.env.example`.

### Required Credentials

| Variable | Description | Source |
|----------|-------------|--------|
| `REDDIT_CLIENT_ID` | Reddit app client ID | https://www.reddit.com/prefs/apps |
| `REDDIT_CLIENT_SECRET` | Reddit app secret | Same as above |
| `REDDIT_USERNAME` | Bot account username | `ChubbyFireBot` |
| `REDDIT_PASSWORD` | Bot account password | Stored securely |
| `DISCORD_BOT_TOKEN` | Discord bot token | Discord Developer Portal |
| `DISCORD_CHANNEL_ID` | Channel for notifications | Discord channel settings |
| `DISCORD_APPLICATION_ID` | Discord app ID | `1519741720206512168` |
| `DISCORD_PUBLIC_KEY` | Discord public key | See PLAN.md |

### Credential Storage Locations

Credentials must be maintained in TWO places:

1. **This repo**: `/Users/trenshaw/code/tasks/chubbyfire/ChubbyFireBot-chubbyfire-automated-moderating/.env`
2. **Base repo**: `/Users/trenshaw/code/ChubbyFireBot/.env`

When adding or updating credentials:
```bash
# Update both locations
cp .env ~/code/ChubbyFireBot/.env
```

### GitHub Secrets

For CI/CD, add secrets to both repos:
- `REDDIT_CLIENT_ID`
- `REDDIT_CLIENT_SECRET`
- `REDDIT_USERNAME`
- `REDDIT_PASSWORD`
- `DISCORD_BOT_TOKEN`
- `DISCORD_CHANNEL_ID`

---

## Architecture Decisions

### Claude Sessions

Each moderation decision spawns a new Claude session with:
- Post/comment content
- Author info and history
- Subreddit rules (fetched from Reddit)
- Recent decision context

Uses logged-in Anthropic account (no API key needed).

### Reddit Removal Reasons

**DO NOT duplicate removal reasons.** Fetch from Reddit's configured removal reasons:
```python
# Fetch removal reasons from Reddit
subreddit.mod.removal_reasons
```

If rules change on Reddit, the bot automatically uses the updated reasons.

### Database

Simple JSON Lines file for logging decisions:
```
data/decisions.jsonl  # One JSON object per line
data/weekly_summary.json  # Generated weekly, gitignored
```

### Discord Interaction

- Bot sends embed messages with action buttons
- React with emoji or click buttons to approve/remove
- Bot tracks message IDs to correlate actions

---

## Running the Bot

### Development
```bash
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
pytest tests/  # Run tests first!
python -m src.main --dry-run  # Test without taking actions
```

### Production
```bash
python -m src.main  # Runs every 30 minutes
```

### Cron Setup
```bash
# Check mod queue and new posts every 30 minutes
*/30 * * * * cd /path/to/ChubbyFireBot && /path/to/venv/bin/python -m src.main >> logs/cron.log 2>&1
```

---

## Weekly Summary

- Generated every Sunday at midnight
- Written to `data/weekly_summary.json` (gitignored)
- Contains: actions taken, accuracy, common patterns

---

## Code Style

- Python 3.11+
- Type hints required
- Black formatting
- Ruff linting
- Docstrings for public functions

---

## Commit Messages

Format: `[CHUBBY-XXX] Brief description`

Or for non-ticketed work:
- `feat: Add new feature`
- `fix: Fix bug`
- `test: Add tests`
- `docs: Update documentation`

---

## Current Status

**Implemented and Working:**
- 56 unit tests passing
- Reddit client (PRAW) - login verified
- Discord bot with action buttons
- Claude session spawner
- Mod queue monitor
- New posts monitor
- Decision logger (JSONL)
- Dry run mode

**Credentials Configured:**
- Reddit: `u/ChubbyFireBot` (moderator of r/chubbyfire)
- Discord: ChubbyFireDBot in channel `1519740049607102728`
- GitHub Secrets: All 6 secrets set

---

## Taskling Integration

Run config: `~/code/taskling/data/run-configs/chubbyfirebot.json`

Click-to-run commands available in Taskling UI:
- **Moderation (Dry Run)**: Test without actions
- **Moderation (Production)**: Live moderation
- **Reports**: Weekly summary
- **Test**: Run test suite

---

## Operational Notes

### When Claude Session Hangs
Each new post spawns a Claude session via CLI. If processing 25 posts, this can take several minutes. This is normal.

### Async PRAW Warning
The warning about async PRAW is informational only. The bot works correctly in cron/script mode.

### Removal Reasons
Removal reasons are fetched live from Reddit. If you update them in r/chubbyfire mod settings, the bot will use the new reasons automatically.

### Decision Logging
Every decision is appended to `data/decisions.jsonl`. Review with:
```bash
tail -20 data/decisions.jsonl | jq .
```

### Confidence Threshold
Auto-actions only happen at 95%+ confidence. Adjust in `monitors/mod_queue.py` and `monitors/new_posts.py`:
```python
AUTO_ACTION_THRESHOLD = 0.95
```
