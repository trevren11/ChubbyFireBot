"""Mod queue monitor - checks reported posts and comments."""

from dataclasses import dataclass
from typing import Optional

from src.reddit_client import RedditClient, RedditItem
from src.discord_bot import DiscordBot
from src.claude_session import ClaudeSession, ModerationDecision
from src.decision_logger import DecisionLogger, Decision


# Confidence threshold for auto-actions
AUTO_ACTION_THRESHOLD = 0.95


@dataclass
class MonitorResults:
    """Results from a monitor run."""

    processed: int = 0
    approved: int = 0
    removed: int = 0
    flagged: int = 0
    skipped: int = 0
    errors: int = 0


class ModQueueMonitor:
    """Monitor for the Reddit mod queue."""

    def __init__(
        self,
        reddit_client: RedditClient,
        discord_bot: DiscordBot,
        claude_session: ClaudeSession,
        decision_logger: DecisionLogger,
        dry_run: bool = False,
    ):
        """Initialize the mod queue monitor."""
        self.reddit = reddit_client
        self.discord = discord_bot
        self.claude = claude_session
        self.logger = decision_logger
        self.dry_run = dry_run

    async def run(self, limit: int = 100) -> dict:
        """Run the mod queue check."""
        results = MonitorResults()

        # Fetch context
        removal_reasons = self.reddit.get_removal_reasons()
        subreddit_rules = self.reddit.get_subreddit_rules()
        recent_decisions = self.logger.get_recent(limit=5)

        # Get mod queue items
        items = self.reddit.get_mod_queue(limit=limit)

        for item in items:
            try:
                await self._process_item(
                    item=item,
                    removal_reasons=removal_reasons,
                    subreddit_rules=subreddit_rules,
                    recent_decisions=recent_decisions,
                    results=results,
                )
            except Exception as e:
                results.errors += 1
                print(f"Error processing {item.reddit_id}: {e}")

        return {
            "processed": results.processed,
            "approved": results.approved,
            "removed": results.removed,
            "flagged": results.flagged,
            "skipped": results.skipped,
            "errors": results.errors,
        }

    async def _process_item(
        self,
        item: RedditItem,
        removal_reasons: list,
        subreddit_rules: list,
        recent_decisions: list,
        results: MonitorResults,
    ) -> None:
        """Process a single item from the mod queue."""
        results.processed += 1

        # Get Claude's decision
        decision = self.claude.get_decision(
            item=item,
            subreddit_rules=subreddit_rules,
            removal_reasons=removal_reasons,
            recent_decisions=recent_decisions,
        )

        # Determine action based on confidence
        should_auto_action = decision.confidence >= AUTO_ACTION_THRESHOLD

        if decision.action == "approve" and should_auto_action:
            results.approved += 1
            if not self.dry_run:
                self.reddit.approve(item.reddit_id)
            decided_by = "bot"
        elif decision.action == "remove" and should_auto_action:
            results.removed += 1
            if not self.dry_run:
                self.reddit.remove(item.reddit_id, reason_id=decision.removal_reason_id)
            decided_by = "bot"
        else:
            # Flag for review - don't take action
            results.flagged += 1
            decided_by = "bot"  # Still bot decision, just flagged

        # Send Discord notification (try bot client first, fall back to REST API)
        try:
            await self.discord.send_moderation_message(
                item=item,
                bot_decision=decision.action,
                confidence=decision.confidence,
                reason=decision.reason,
                removal_reasons=removal_reasons,
                dry_run=self.dry_run,
            )
        except Exception as e:
            # Fall back to bot REST API
            from src.discord_bot import send_bot_message
            send_bot_message(
                item=item,
                bot_decision=decision.action,
                confidence=decision.confidence,
                reason=decision.reason,
                dry_run=self.dry_run,
            )

        # Log the decision
        self.logger.log(Decision(
            reddit_id=item.reddit_id,
            content_type=item.content_type,
            author=item.author,
            action=decision.action,
            reason=decision.reason,
            confidence=decision.confidence,
            decided_by=decided_by,
            removal_reason_id=decision.removal_reason_id,
        ))
