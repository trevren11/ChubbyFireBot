"""Main entry point for ChubbyFireBot."""

import argparse
import asyncio
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv

from src.reddit_client import RedditClient
from src.discord_bot import DiscordBot
from src.claude_session import ClaudeSession
from src.decision_logger import DecisionLogger
from monitors.mod_queue import ModQueueMonitor
from monitors.new_posts import NewPostsMonitor


def get_config() -> dict:
    """Load configuration from environment variables."""
    load_dotenv()

    required = [
        "REDDIT_CLIENT_ID",
        "REDDIT_CLIENT_SECRET",
        "REDDIT_USERNAME",
        "REDDIT_PASSWORD",
        "DISCORD_BOT_TOKEN",
        "DISCORD_CHANNEL_ID",
    ]

    missing = [key for key in required if not os.getenv(key)]
    if missing:
        print(f"Error: Missing required environment variables: {', '.join(missing)}")
        print("Please set them in .env file or environment.")
        sys.exit(1)

    return {
        "reddit": {
            "client_id": os.getenv("REDDIT_CLIENT_ID"),
            "client_secret": os.getenv("REDDIT_CLIENT_SECRET"),
            "username": os.getenv("REDDIT_USERNAME"),
            "password": os.getenv("REDDIT_PASSWORD"),
            "user_agent": os.getenv(
                "REDDIT_USER_AGENT",
                f"ChubbyFireBot/1.0 by u/{os.getenv('REDDIT_USERNAME')}",
            ),
            "subreddit": os.getenv("SUBREDDIT", "chubbyfire"),
        },
        "discord": {
            "token": os.getenv("DISCORD_BOT_TOKEN"),
            "channel_id": int(os.getenv("DISCORD_CHANNEL_ID")),
        },
        "dry_run": os.getenv("DRY_RUN", "false").lower() == "true",
        "data_dir": Path(os.getenv("DATA_DIR", "data")),
    }


async def run_mod_queue(config: dict, dry_run: bool) -> dict:
    """Run the mod queue monitor."""
    print(f"[{datetime.now()}] Starting mod queue check...")

    reddit = RedditClient(**config["reddit"])
    discord = DiscordBot(
        token=config["discord"]["token"],
        channel_id=config["discord"]["channel_id"],
        data_dir=config["data_dir"],
    )
    claude = ClaudeSession()
    logger = DecisionLogger(config["data_dir"] / "decisions.jsonl")

    # Set up action handlers for Discord
    discord.set_action_handlers(
        on_approve=lambda reddit_id: reddit.approve(reddit_id),
        on_remove=lambda reddit_id, reason_id: reddit.remove(reddit_id, reason_id=reason_id),
    )

    monitor = ModQueueMonitor(
        reddit_client=reddit,
        discord_bot=discord,
        claude_session=claude,
        decision_logger=logger,
        dry_run=dry_run,
    )

    results = await monitor.run()

    print(f"[{datetime.now()}] Mod queue check complete:")
    print(f"  Processed: {results['processed']}")
    print(f"  Approved: {results['approved']}")
    print(f"  Removed: {results['removed']}")
    print(f"  Flagged: {results['flagged']}")
    print(f"  Errors: {results['errors']}")

    return results


async def run_new_posts(config: dict, dry_run: bool) -> dict:
    """Run the new posts monitor."""
    print(f"[{datetime.now()}] Starting new posts check...")

    reddit = RedditClient(**config["reddit"])
    discord = DiscordBot(
        token=config["discord"]["token"],
        channel_id=config["discord"]["channel_id"],
        data_dir=config["data_dir"],
    )
    claude = ClaudeSession()
    logger = DecisionLogger(config["data_dir"] / "decisions.jsonl")

    # Set up action handlers for Discord
    discord.set_action_handlers(
        on_approve=lambda reddit_id: reddit.approve(reddit_id),
        on_remove=lambda reddit_id, reason_id: reddit.remove(reddit_id, reason_id=reason_id),
    )

    monitor = NewPostsMonitor(
        reddit_client=reddit,
        discord_bot=discord,
        claude_session=claude,
        decision_logger=logger,
        dry_run=dry_run,
    )

    results = await monitor.run()

    print(f"[{datetime.now()}] New posts check complete:")
    print(f"  Processed: {results['processed']}")
    print(f"  Approved: {results['approved']}")
    print(f"  Removed: {results['removed']}")
    print(f"  Flagged: {results['flagged']}")
    print(f"  Skipped: {results['skipped']}")
    print(f"  Errors: {results['errors']}")

    return results


def generate_weekly_summary(config: dict) -> None:
    """Generate weekly summary report."""
    print(f"[{datetime.now()}] Generating weekly summary...")

    logger = DecisionLogger(config["data_dir"] / "decisions.jsonl")
    counts = logger.count_actions()
    recent = logger.get_recent(limit=1000)  # Last ~1000 decisions

    # Calculate stats
    total = sum(counts.values())
    bot_decisions = [d for d in recent if d.decided_by == "bot"]
    human_decisions = [d for d in recent if d.decided_by == "human"]

    summary = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "total_decisions": total,
        "actions": counts,
        "bot_decisions": len(bot_decisions),
        "human_decisions": len(human_decisions),
        "confidence_avg": (
            sum(d.confidence for d in bot_decisions) / len(bot_decisions)
            if bot_decisions
            else 0
        ),
    }

    # Write to file
    summary_path = config["data_dir"] / "weekly_summary.json"
    config["data_dir"].mkdir(parents=True, exist_ok=True)
    with open(summary_path, "w") as f:
        json.dump(summary, f, indent=2)

    print(f"Weekly summary written to {summary_path}")
    print(f"  Total decisions: {total}")
    print(f"  Actions: {counts}")


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(description="ChubbyFireBot - Reddit moderation bot")
    parser.add_argument(
        "command",
        choices=["mod-queue", "new-posts", "weekly-summary", "all"],
        help="Command to run",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Don't take any actions on Reddit (log only)",
    )
    parser.add_argument(
        "--once",
        action="store_true",
        help="Run once and exit (default behavior)",
    )

    args = parser.parse_args()

    config = get_config()
    dry_run = args.dry_run or config["dry_run"]

    if dry_run:
        print("*** DRY RUN MODE - No actions will be taken on Reddit ***")

    # Ensure data directory exists
    config["data_dir"].mkdir(parents=True, exist_ok=True)

    if args.command == "mod-queue":
        asyncio.run(run_mod_queue(config, dry_run))
    elif args.command == "new-posts":
        asyncio.run(run_new_posts(config, dry_run))
    elif args.command == "weekly-summary":
        generate_weekly_summary(config)
    elif args.command == "all":
        asyncio.run(run_mod_queue(config, dry_run))
        asyncio.run(run_new_posts(config, dry_run))


if __name__ == "__main__":
    main()
