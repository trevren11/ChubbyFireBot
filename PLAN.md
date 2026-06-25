# ChubbyFireBot - Automated Moderation System

## Overview

Automated moderation system for r/chubbyfire that monitors the mod queue and new posts. Each item triggers a Claude session to make moderation decisions. Learns from past actions and human feedback via Discord.

**Key Principles:**
- Test-Driven Development (TDD) for all features
- Uses logged-in Anthropic account (no API key needed)
- Fetches removal reasons from Reddit (no duplication)
- Self-contained in this repository

---

## Core Requirements

### 1. Mod Queue Monitor
- Check mod queue every 30 minutes via cron
- Each reported post/comment triggers a Claude session
- Claude analyzes content with full context
- Auto-action on obvious violations (high confidence)
- Send Discord notification for unclear cases

### 2. New Posts Monitor (SEPARATE)
- Separate check for new posts (every 30 minutes)
- Same core decision logic as mod queue
- Proactive community protection
- Different trigger, same Claude session pattern

### 3. Claude Session Per Decision
- Each post/comment spawns a new Claude session
- Session receives:
  - Post/comment content and metadata
  - Author history (karma, account age, past removals)
  - Subreddit rules (fetched from Reddit)
  - Recent similar decisions for context
- Claude returns: decision, confidence, reasoning

### 4. Discord Bot Integration
- Full Discord bot (not just webhook) for bidirectional interaction
- Send embed messages with action buttons
- Support emoji reactions for quick actions:
  - Approve
  - Remove (with reason selector)
- Track message IDs to correlate Discord actions with Reddit items
- Learn from human decisions

### 5. Learning System
- Sync manual mod actions from Reddit mod log
- Learn from Discord feedback (approve/remove reactions)
- Update decision patterns based on corrections
- Self-updating without code changes

---

## Credentials

### Discord Bot
- **App Name**: ChubbyFireDBot
- **Application ID**: `1519741720206512168`
- **Public Key**: `99b0ea556ebf87fe8d5a117a9e224a6d1c8ae638903fb8f99952a7d7912319b1`
- **Bot Token**: (in .env)

### Reddit Account
- **Username**: `ChubbyFireBot`
- **Password**: (in .env)
- **Client ID/Secret**: Create at https://www.reddit.com/prefs/apps

### Anthropic
- Uses logged-in account via `claude` CLI
- No API key needed

---

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                        ChubbyFireBot                             │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  ┌──────────────┐    ┌──────────────┐    ┌──────────────┐      │
│  │  Mod Queue   │    │  New Posts   │    │   Learning   │      │
│  │   Monitor    │    │   Monitor    │    │    Sync      │      │
│  │  (cron 30m)  │    │  (cron 30m)  │    │  (on action) │      │
│  └──────┬───────┘    └──────┬───────┘    └──────┬───────┘      │
│         │                   │                   │               │
│         └───────────┬───────┴───────────────────┘               │
│                     │                                            │
│         ┌───────────▼───────────┐                               │
│         │   Claude Session      │  <-- Each item = new session  │
│         │   (via claude CLI)    │                               │
│         │                       │                               │
│         │  Context provided:    │                               │
│         │  - Content + metadata │                               │
│         │  - Reddit rules       │                               │
│         │  - Author history     │                               │
│         │  - Past decisions     │                               │
│         └───────────┬───────────┘                               │
│                     │                                            │
│    ┌────────────────┼────────────────┐                          │
│    │                │                │                          │
│    ▼                ▼                ▼                          │
│ ┌──────┐     ┌──────────┐    ┌──────────┐                      │
│ │Reddit│     │ Discord  │    │  JSONL   │                      │
│ │Action│     │   Bot    │    │   Log    │                      │
│ └──────┘     └────┬─────┘    └──────────┘                      │
│                   │                                              │
│              ┌────▼────┐                                        │
│              │ Buttons │  <-- Human can approve/remove          │
│              │ Reacts  │      via Discord interaction           │
│              └─────────┘                                        │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
```

---

## File Structure

```
ChubbyFireBot/
├── PLAN.md                     # This file
├── AGENTS.md                   # Agent guidelines, TDD requirements
├── README.md                   # Setup and usage documentation
├── requirements.txt            # Python dependencies
├── .env.example                # Template for environment variables
├── .gitignore                  # Ignore secrets, data, logs
│
├── .claude/
│   └── CLAUDE.md               # Points to AGENTS.md
│
├── src/
│   ├── __init__.py
│   ├── main.py                 # Entry point
│   ├── reddit_client.py        # Reddit API wrapper (PRAW)
│   ├── discord_bot.py          # Discord bot with reactions/buttons
│   ├── claude_session.py       # Spawn Claude sessions for decisions
│   ├── decision_logger.py      # JSONL logging
│   └── learning.py             # Learn from manual actions
│
├── monitors/
│   ├── __init__.py
│   ├── mod_queue.py            # Mod queue monitor
│   └── new_posts.py            # New posts monitor
│
├── data/                       # All gitignored
│   ├── decisions.jsonl         # Decision log (append-only)
│   ├── weekly_summary.json     # Generated weekly
│   └── discord_messages.json   # Message ID → Reddit ID mapping
│
├── logs/                       # Gitignored
│   └── bot.log
│
└── tests/
    ├── __init__.py
    ├── conftest.py             # Shared fixtures
    ├── unit/
    │   ├── test_reddit_client.py
    │   ├── test_discord_bot.py
    │   ├── test_claude_session.py
    │   └── test_decision_logger.py
    └── integration/
        ├── test_mod_queue_flow.py
        └── test_discord_actions.py
```

---

## Decision Flow

### For Each Item (Post or Comment)

```python
# Pseudocode
def process_item(item):
    # 1. Gather context
    context = {
        "content": item.body or item.selftext,
        "title": item.title if hasattr(item, 'title') else None,
        "author": item.author.name,
        "author_karma": item.author.link_karma + item.author.comment_karma,
        "account_age_days": (now - item.author.created_utc).days,
        "reports": item.mod_reports + item.user_reports,
        "subreddit_rules": fetch_subreddit_rules(),
        "removal_reasons": fetch_removal_reasons(),  # From Reddit!
        "recent_decisions": get_recent_similar_decisions(5),
    }
    
    # 2. Spawn Claude session
    decision = spawn_claude_session(context)
    # Returns: { action, confidence, reason, removal_reason_id }
    
    # 3. Take action based on confidence
    if decision.confidence >= 0.95:
        # Auto-action
        if decision.action == "remove":
            item.mod.remove(reason_id=decision.removal_reason_id)
        else:
            item.mod.approve()
        notify_discord(item, decision, auto=True)
    else:
        # Flag for review
        notify_discord(item, decision, auto=False)
    
    # 4. Log decision
    log_decision(item, decision)
```

---

## Discord Interaction

### Message Format (Embed)

```
┌────────────────────────────────────────┐
│ [POST] Title of the post               │
│                                        │
│ Author: u/username (1.2k karma, 45d)   │
│ Reports: 2 (spam, off-topic)           │
│                                        │
│ Content preview (first 500 chars)...   │
│                                        │
│ ─────────────────────────────────────  │
│ Bot Decision: REMOVE (87% confidence)  │
│ Reason: Appears to be promotional spam │
│                                        │
│ [Approve] [Remove: Spam] [Remove: Off] │
└────────────────────────────────────────┘
```

### Reaction/Button Actions

| Action | Effect |
|--------|--------|
| Approve button | Approve on Reddit, log as human decision |
| Remove: [Reason] | Remove with specific Reddit reason |
| Emoji reactions | Alternative to buttons (backup) |

---

## Reddit Removal Reasons

**DO NOT hardcode removal reasons.** Fetch from Reddit:

```python
def fetch_removal_reasons(subreddit):
    """Fetch removal reasons configured in r/chubbyfire mod tools."""
    reasons = []
    for reason in subreddit.mod.removal_reasons:
        reasons.append({
            "id": reason.id,
            "title": reason.title,
            "message": reason.message,
        })
    return reasons
```

This ensures:
- Reasons stay in sync with Reddit
- Changes on Reddit are automatically reflected
- No duplicate configuration to maintain

---

## Data Storage (JSONL)

Simple append-only log instead of SQLite:

### decisions.jsonl
```json
{"id": "t3_abc123", "type": "post", "author": "user1", "action": "remove", "reason": "spam", "confidence": 0.95, "decided_by": "bot", "timestamp": "2024-01-15T10:30:00Z"}
{"id": "t1_def456", "type": "comment", "author": "user2", "action": "approve", "reason": null, "confidence": 0.92, "decided_by": "human", "timestamp": "2024-01-15T10:35:00Z"}
```

### discord_messages.json
```json
{
  "discord_msg_id": {"reddit_id": "t3_abc123", "created": "2024-01-15T10:30:00Z"}
}
```

---

## Weekly Summary

Generated every Sunday, written to `data/weekly_summary.json` (gitignored):

```json
{
  "week_of": "2024-01-15",
  "total_processed": 142,
  "actions": {
    "auto_approved": 85,
    "auto_removed": 23,
    "human_approved": 20,
    "human_removed": 14
  },
  "accuracy": {
    "bot_decisions_overridden": 3,
    "override_rate": 0.028
  },
  "top_removal_reasons": [
    {"reason": "spam", "count": 18},
    {"reason": "off-topic", "count": 12}
  ],
  "flagged_users": ["suspicious_user1"]
}
```

---

## Dry Run Mode

Enabled via `--dry-run` flag or `DRY_RUN=true` env var:

- Fetches and analyzes all items normally
- Claude makes decisions
- Logs decisions to `data/decisions_dry_run.jsonl`
- Sends Discord notifications with `[DRY RUN]` prefix
- **Does NOT take any action on Reddit**

Essential for:
- Testing new deployments
- Validating rule changes
- Training the system before going live

---

## Environment Variables

```bash
# .env file

# Reddit API (create app at https://www.reddit.com/prefs/apps)
REDDIT_CLIENT_ID=
REDDIT_CLIENT_SECRET=
REDDIT_USERNAME=ChubbyFireBot
REDDIT_PASSWORD=Marmite25
REDDIT_USER_AGENT=ChubbyFireBot/1.0 by u/ChubbyFireBot

# Discord Bot
DISCORD_BOT_TOKEN=
DISCORD_CHANNEL_ID=
DISCORD_APPLICATION_ID=1519741720206512168
DISCORD_PUBLIC_KEY=99b0ea556ebf87fe8d5a117a9e224a6d1c8ae638903fb8f99952a7d7912319b1

# Configuration
SUBREDDIT=chubbyfire
DRY_RUN=false
LOG_LEVEL=INFO
```

---

## Implementation Phases

### Phase 1: Foundation
- [ ] Project structure and test setup
- [ ] Reddit client with PRAW (TDD)
- [ ] Decision logger (JSONL) (TDD)
- [ ] Basic mod queue monitor (TDD)
- [ ] Basic new posts monitor (TDD)

### Phase 2: Claude Integration
- [ ] Claude session spawner (TDD)
- [ ] Context builder for decisions
- [ ] Confidence-based action logic
- [ ] Dry run mode

### Phase 3: Discord Bot
- [ ] Discord bot setup (TDD)
- [ ] Embed message formatting
- [ ] Button/reaction handlers
- [ ] Message ID tracking

### Phase 4: Learning & Polish
- [ ] Sync manual Reddit mod actions
- [ ] Learn from Discord feedback
- [ ] Weekly summary generation
- [ ] Cron setup (30-minute schedule)

---

## Cron Setup

```bash
# Check mod queue every 30 minutes
*/30 * * * * cd ~/code/ChubbyFireBot && ./venv/bin/python -m src.main mod-queue >> logs/cron.log 2>&1

# Check new posts every 30 minutes (offset by 15 min to spread load)
15,45 * * * * cd ~/code/ChubbyFireBot && ./venv/bin/python -m src.main new-posts >> logs/cron.log 2>&1

# Generate weekly summary on Sunday at midnight
0 0 * * 0 cd ~/code/ChubbyFireBot && ./venv/bin/python -m src.main weekly-summary >> logs/cron.log 2>&1
```

---

## Quick Start

```bash
# Clone and setup
cd ~/code/ChubbyFireBot
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
# Edit .env with credentials

# Run tests (ALWAYS before any code changes)
pytest tests/

# Dry run to test without taking actions
python -m src.main mod-queue --dry-run
python -m src.main new-posts --dry-run

# Production run
python -m src.main mod-queue
python -m src.main new-posts
```

---

## Not Implementing (Deferred)

These features were considered but deferred:
- Brigading detection
- Flair-based rules
- Sentiment tracking
- Quiet hours
- Daily summaries (weekly instead)
- SQLite database (JSONL instead)
- Anthropic API key (using logged-in account)

---

## Next Steps

1. **Approve this plan**
2. Create Reddit app at https://www.reddit.com/prefs/apps
3. Get Discord bot token from Developer Portal
4. Set up .env with all credentials
5. Begin Phase 1 with TDD
