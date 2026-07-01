# ChubbyFireBot

Automated moderation bot for r/chubbyfire (146K subscribers). Uses Claude to analyze posts and comments, takes automated actions on obvious violations, and sends Discord notifications for human review.

## Features

- **Mod Queue Monitor** - Checks reported posts/comments every 30 minutes
- **New Posts Monitor** - Proactively reviews new posts before they get reported
- **Claude-Powered Decisions** - Each item analyzed by Claude with full context
- **Discord Integration** - Rich embeds with approve/remove buttons
- **Learning System** - Logs all decisions in JSONL for pattern analysis
- **Dry Run Mode** - Test without taking any Reddit actions

## Quick Start

```bash
cd ~/code/ChubbyFireBot
source venv/bin/activate
pip install -r requirements.txt

# Test with dry run first
python -m src.main mod-queue --dry-run
python -m src.main new-posts --dry-run

# Production
python -m src.main mod-queue
python -m src.main new-posts
```

## Commands

| Command | Description |
|---------|-------------|
| `mod-queue` | Check mod queue for reported items |
| `new-posts` | Check new posts proactively |
| `all` | Run both monitors |
| `weekly-summary` | Generate stats report |

Add `--dry-run` to any command to test without taking actions.

## How It Works

```
                    ┌─────────────────┐
                    │   Cron Job      │
                    │  (every 30min)  │
                    └────────┬────────┘
                             │
              ┌──────────────┴──────────────┐
              │                             │
    ┌─────────▼─────────┐       ┌──────────▼──────────┐
    │   Mod Queue       │       │    New Posts        │
    │   (reported)      │       │    (proactive)      │
    └─────────┬─────────┘       └──────────┬──────────┘
              │                             │
              └──────────────┬──────────────┘
                             │
                   ┌─────────▼─────────┐
                   │   Claude Session  │
                   │   (per item)      │
                   │                   │
                   │  Context:         │
                   │  - Content        │
                   │  - Author info    │
                   │  - Subreddit rules│
                   │  - Past decisions │
                   └─────────┬─────────┘
                             │
              ┌──────────────┴──────────────┐
              │                             │
    ┌─────────▼─────────┐       ┌──────────▼──────────┐
    │  High Confidence  │       │   Low Confidence    │
    │  (95%+)           │       │   (<95%)            │
    │                   │       │                     │
    │  Auto-action on   │       │  Send to Discord    │
    │  Reddit           │       │  for human review   │
    └───────────────────┘       └──────────┬──────────┘
                                           │
                                 ┌─────────▼─────────┐
                                 │  Discord Message  │
                                 │  with buttons     │
                                 │                   │
                                 │  [Approve]        │
                                 │  [Remove: Spam]   │
                                 │  [Remove: Off-topic]
                                 └───────────────────┘
```

## Confidence Levels

| Confidence | Action |
|------------|--------|
| 95%+ approve | Auto-approve on Reddit |
| 95%+ remove | Auto-remove with reason |
| < 95% | Flag for human review via Discord |

## Cron Setup

```bash
# Add to crontab (crontab -e)

# Mod queue every 30 minutes
*/30 * * * * cd ~/code/ChubbyFireBot && ./venv/bin/python -m src.main mod-queue >> logs/cron.log 2>&1

# New posts every 30 minutes (offset by 15 min)
15,45 * * * * cd ~/code/ChubbyFireBot && ./venv/bin/python -m src.main new-posts >> logs/cron.log 2>&1

# Weekly summary Sunday midnight
0 0 * * 0 cd ~/code/ChubbyFireBot && ./venv/bin/python -m src.main weekly-summary >> logs/cron.log 2>&1
```

## Discord Bot Setup

- Bot: **ChubbyMod** (Application ID: `1519741720206512168`)
- Channel: `1519740049607102728`
- Bot invite link (all required permissions):
  `https://discord.com/oauth2/authorize?client_id=1519741720206512168&permissions=84992&scope=bot`
  - Send Messages + Embed Links + Read Message History

### Discord Notification Format

When a post needs review, ChubbyMod sends an embed with:
- **Full post/comment text** (up to Discord's 4096 char limit)
- **Author info** — username, karma, account age
- **Bot decision** — APPROVE / REMOVE / FLAG with confidence %
- **Reason** — Claude's explanation
- **Mod History** — how many posts/comments this author has had reviewed before, and outcomes (e.g. `2 posts seen — 1 approved, 1 removed`). Hidden for first-time authors.
- **Action buttons** — Approve or Remove

### Discord Actions
- Click **Approve** to approve on Reddit
- Click **Remove: [Reason]** to remove with that reason
- The embed updates to show it was handled (color changes, title prefixed)

### Important: Environment Variable Conflict

If running alongside Taskling, the shell environment may have a `DISCORD_BOT_TOKEN` set for the Taskling bot. The cron jobs use `load_dotenv(override=True)` in `src/main.py` to ensure the ChubbyMod token from `.env` is always used instead of the shell environment value.

## Reddit Integration

- Bot account: `u/ChubbyFireBot`
- Subreddit: `r/chubbyfire`
- Bot has moderator permissions
- Removal reasons are fetched from Reddit (not hardcoded)

## File Locations

| File | Purpose |
|------|---------|
| `data/decisions.jsonl` | All moderation decisions (append-only) |
| `data/weekly_summary.json` | Generated weekly stats |
| `data/discord_messages.json` | Discord msg ID to Reddit ID mapping |
| `logs/cron.log` | Cron execution logs |

## Development

**All changes must follow TDD** (see [AGENTS.md](AGENTS.md)).

```bash
# Run tests
pytest tests/ -v

# Run with coverage
pytest tests/ --cov=src --cov=monitors

# Currently: 56 tests passing
```

## Taskling Integration

Run configs are in `~/code/taskling/data/run-configs/chubbyfirebot.json`.

Available in Taskling UI:
- Mod Queue (Dry Run / Production)
- New Posts (Dry Run / Production)
- All Monitors
- Weekly Summary
- Tests

## Environment Variables

```bash
# Required (in .env)
REDDIT_CLIENT_ID=...
REDDIT_CLIENT_SECRET=...
REDDIT_USERNAME=ChubbyFireBot
REDDIT_PASSWORD=...
DISCORD_BOT_TOKEN=...
DISCORD_CHANNEL_ID=...

# Optional
SUBREDDIT=chubbyfire  # default
DRY_RUN=false         # default
LOG_LEVEL=INFO        # default
```

## Troubleshooting

### "Claude CLI not found"
Make sure `claude` is in your PATH and you're logged in.

### "Bot is NOT a moderator"
Add `u/ChubbyFireBot` as a mod in r/chubbyfire settings.

### Discord 403 Forbidden
The bot needs three permissions: **Send Messages**, **Embed Links**, and **Read Message History**. Use the invite link in the Discord Bot Setup section above to re-invite with all three. After re-inviting, verify the bot appears in Server Settings → Integrations.

### Discord sends as "taskling" instead of "ChubbyMod"
The shell environment has a `DISCORD_BOT_TOKEN` set by Taskling that overrides `.env`. This is fixed by `load_dotenv(override=True)` in `src/main.py`. If you see this again, verify that line hasn't been reverted.

### Async PRAW warning
This is harmless for cron jobs. The bot works correctly.

### Empty mod queue
If `Processed: 0`, there are simply no reported items. This is normal.

## Architecture

See [PLAN.md](PLAN.md) for full architecture documentation.
