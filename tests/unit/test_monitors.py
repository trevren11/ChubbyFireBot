"""Tests for the mod queue and new posts monitors."""

from pathlib import Path
from unittest.mock import MagicMock, AsyncMock, patch

import pytest

from src.reddit_client import RedditItem, RemovalReason
from src.decision_logger import DecisionLogger, Decision
from src.claude_session import ModerationDecision
from monitors.mod_queue import ModQueueMonitor
from monitors.new_posts import NewPostsMonitor


@pytest.fixture
def mock_reddit_client():
    """Create a mock Reddit client."""
    client = MagicMock()
    client.get_mod_queue.return_value = []
    client.get_new_posts.return_value = []
    client.get_removal_reasons.return_value = [
        RemovalReason(id="r1", title="Spam", message="Spam message"),
        RemovalReason(id="r2", title="Off-topic", message="Off-topic message"),
    ]
    client.get_subreddit_rules.return_value = [
        {"short_name": "Be civil", "description": "No insults"},
    ]
    return client


@pytest.fixture
def mock_discord_bot():
    """Create a mock Discord bot."""
    bot = MagicMock()
    bot.send_moderation_message = AsyncMock(return_value="msg_123")
    return bot


@pytest.fixture
def mock_claude_session():
    """Create a mock Claude session."""
    session = MagicMock()
    session.get_decision.return_value = ModerationDecision(
        action="approve",
        confidence=0.95,
        reason="Legitimate content",
    )
    return session


class TestModQueueMonitor:
    """Tests for the mod queue monitor."""

    def test_init(self, mock_reddit_client, mock_discord_bot, mock_claude_session, temp_data_dir):
        """Test monitor initialization."""
        logger = DecisionLogger(temp_data_dir / "decisions.jsonl")
        monitor = ModQueueMonitor(
            reddit_client=mock_reddit_client,
            discord_bot=mock_discord_bot,
            claude_session=mock_claude_session,
            decision_logger=logger,
            dry_run=False,
        )
        assert monitor.dry_run is False

    @pytest.mark.asyncio
    async def test_process_empty_queue(
        self, mock_reddit_client, mock_discord_bot, mock_claude_session, temp_data_dir
    ):
        """Test processing an empty mod queue."""
        logger = DecisionLogger(temp_data_dir / "decisions.jsonl")
        monitor = ModQueueMonitor(
            reddit_client=mock_reddit_client,
            discord_bot=mock_discord_bot,
            claude_session=mock_claude_session,
            decision_logger=logger,
            dry_run=False,
        )

        results = await monitor.run()

        assert results["processed"] == 0
        assert results["approved"] == 0
        assert results["removed"] == 0

    @pytest.mark.asyncio
    async def test_process_item_auto_approve(
        self, mock_reddit_client, mock_discord_bot, mock_claude_session, temp_data_dir
    ):
        """Test auto-approving an item with high confidence."""
        item = RedditItem(
            reddit_id="t3_test123",
            content_type="post",
            title="FIRE milestone",
            body="Hit my goal!",
            author="user1",
            author_karma=5000,
            account_age_days=365,
            url="https://reddit.com/test",
            reports=[],
            created_utc=1700000000,
        )
        mock_reddit_client.get_mod_queue.return_value = [item]
        mock_claude_session.get_decision.return_value = ModerationDecision(
            action="approve",
            confidence=0.96,
            reason="Valid FIRE post",
        )

        logger = DecisionLogger(temp_data_dir / "decisions.jsonl")
        monitor = ModQueueMonitor(
            reddit_client=mock_reddit_client,
            discord_bot=mock_discord_bot,
            claude_session=mock_claude_session,
            decision_logger=logger,
            dry_run=False,
        )

        results = await monitor.run()

        assert results["approved"] == 1
        mock_reddit_client.approve.assert_called_once_with("t3_test123")

    @pytest.mark.asyncio
    async def test_process_item_auto_remove(
        self, mock_reddit_client, mock_discord_bot, mock_claude_session, temp_data_dir
    ):
        """Test auto-removing an item with high confidence."""
        item = RedditItem(
            reddit_id="t3_spam123",
            content_type="post",
            title="BUY MY COURSE",
            body="Click here for free money!",
            author="spammer",
            author_karma=10,
            account_age_days=1,
            url="https://reddit.com/test",
            reports=[{"reason": "spam", "count": 5, "type": "user"}],
            created_utc=1700000000,
        )
        mock_reddit_client.get_mod_queue.return_value = [item]
        mock_claude_session.get_decision.return_value = ModerationDecision(
            action="remove",
            confidence=0.98,
            reason="Clear spam",
            removal_reason_id="r1",
        )

        logger = DecisionLogger(temp_data_dir / "decisions.jsonl")
        monitor = ModQueueMonitor(
            reddit_client=mock_reddit_client,
            discord_bot=mock_discord_bot,
            claude_session=mock_claude_session,
            decision_logger=logger,
            dry_run=False,
        )

        results = await monitor.run()

        assert results["removed"] == 1
        mock_reddit_client.remove.assert_called_once_with("t3_spam123", reason_id="r1")

    @pytest.mark.asyncio
    async def test_process_item_flag_for_review(
        self, mock_reddit_client, mock_discord_bot, mock_claude_session, temp_data_dir
    ):
        """Test flagging an item for human review."""
        item = RedditItem(
            reddit_id="t3_unclear",
            content_type="post",
            title="Maybe off-topic?",
            body="Not sure about this...",
            author="user2",
            author_karma=1000,
            account_age_days=100,
            url="https://reddit.com/test",
            reports=[],
            created_utc=1700000000,
        )
        mock_reddit_client.get_mod_queue.return_value = [item]
        mock_claude_session.get_decision.return_value = ModerationDecision(
            action="flag",
            confidence=0.65,
            reason="Uncertain, needs human review",
        )

        logger = DecisionLogger(temp_data_dir / "decisions.jsonl")
        monitor = ModQueueMonitor(
            reddit_client=mock_reddit_client,
            discord_bot=mock_discord_bot,
            claude_session=mock_claude_session,
            decision_logger=logger,
            dry_run=False,
        )

        results = await monitor.run()

        assert results["flagged"] == 1
        # Should NOT take action on Reddit
        mock_reddit_client.approve.assert_not_called()
        mock_reddit_client.remove.assert_not_called()
        # Should send Discord notification
        mock_discord_bot.send_moderation_message.assert_called_once()

    @pytest.mark.asyncio
    async def test_dry_run_no_actions(
        self, mock_reddit_client, mock_discord_bot, mock_claude_session, temp_data_dir
    ):
        """Test that dry run mode doesn't take actions."""
        item = RedditItem(
            reddit_id="t3_drytest",
            content_type="post",
            title="Test",
            body="Content",
            author="user",
            author_karma=100,
            account_age_days=30,
            url="https://reddit.com/test",
            reports=[],
            created_utc=1700000000,
        )
        mock_reddit_client.get_mod_queue.return_value = [item]
        mock_claude_session.get_decision.return_value = ModerationDecision(
            action="remove",
            confidence=0.99,
            reason="Test removal",
            removal_reason_id="r1",
        )

        logger = DecisionLogger(temp_data_dir / "decisions.jsonl")
        monitor = ModQueueMonitor(
            reddit_client=mock_reddit_client,
            discord_bot=mock_discord_bot,
            claude_session=mock_claude_session,
            decision_logger=logger,
            dry_run=True,  # DRY RUN
        )

        await monitor.run()

        # Should NOT take any Reddit actions
        mock_reddit_client.approve.assert_not_called()
        mock_reddit_client.remove.assert_not_called()

    @pytest.mark.asyncio
    async def test_logs_decisions(
        self, mock_reddit_client, mock_discord_bot, mock_claude_session, temp_data_dir
    ):
        """Test that decisions are logged."""
        item = RedditItem(
            reddit_id="t3_logged",
            content_type="post",
            title="Log test",
            body="Content",
            author="logger",
            author_karma=100,
            account_age_days=30,
            url="https://reddit.com/test",
            reports=[],
            created_utc=1700000000,
        )
        mock_reddit_client.get_mod_queue.return_value = [item]

        logger = DecisionLogger(temp_data_dir / "decisions.jsonl")
        monitor = ModQueueMonitor(
            reddit_client=mock_reddit_client,
            discord_bot=mock_discord_bot,
            claude_session=mock_claude_session,
            decision_logger=logger,
            dry_run=False,
        )

        await monitor.run()

        # Check that decision was logged
        logged = logger.get_by_id("t3_logged")
        assert logged is not None
        assert logged.action == "approve"


class TestNewPostsMonitor:
    """Tests for the new posts monitor."""

    def test_init(self, mock_reddit_client, mock_discord_bot, mock_claude_session, temp_data_dir):
        """Test monitor initialization."""
        logger = DecisionLogger(temp_data_dir / "decisions.jsonl")
        monitor = NewPostsMonitor(
            reddit_client=mock_reddit_client,
            discord_bot=mock_discord_bot,
            claude_session=mock_claude_session,
            decision_logger=logger,
            dry_run=False,
        )
        assert monitor.dry_run is False

    @pytest.mark.asyncio
    async def test_skips_already_processed(
        self, mock_reddit_client, mock_discord_bot, mock_claude_session, temp_data_dir
    ):
        """Test that already-processed posts are skipped."""
        item = RedditItem(
            reddit_id="t3_already",
            content_type="post",
            title="Already seen",
            body="Content",
            author="user",
            author_karma=100,
            account_age_days=30,
            url="https://reddit.com/test",
            reports=[],
            created_utc=1700000000,
        )
        mock_reddit_client.get_new_posts.return_value = [item]

        # Pre-log a decision for this item
        logger = DecisionLogger(temp_data_dir / "decisions.jsonl")
        logger.log(Decision(
            reddit_id="t3_already",
            content_type="post",
            author="user",
            action="approve",
            reason="Already processed",
            confidence=0.9,
            decided_by="bot",
        ))

        monitor = NewPostsMonitor(
            reddit_client=mock_reddit_client,
            discord_bot=mock_discord_bot,
            claude_session=mock_claude_session,
            decision_logger=logger,
            dry_run=False,
        )

        results = await monitor.run()

        # Should skip the already-processed item
        assert results["skipped"] == 1
        mock_claude_session.get_decision.assert_not_called()

    @pytest.mark.asyncio
    async def test_processes_new_posts(
        self, mock_reddit_client, mock_discord_bot, mock_claude_session, temp_data_dir
    ):
        """Test processing new posts."""
        item = RedditItem(
            reddit_id="t3_newpost",
            content_type="post",
            title="Brand new post",
            body="Content",
            author="newuser",
            author_karma=500,
            account_age_days=60,
            url="https://reddit.com/test",
            reports=[],
            created_utc=1700000000,
        )
        mock_reddit_client.get_new_posts.return_value = [item]

        logger = DecisionLogger(temp_data_dir / "decisions.jsonl")
        monitor = NewPostsMonitor(
            reddit_client=mock_reddit_client,
            discord_bot=mock_discord_bot,
            claude_session=mock_claude_session,
            decision_logger=logger,
            dry_run=False,
        )

        results = await monitor.run()

        assert results["processed"] == 1
        mock_claude_session.get_decision.assert_called_once()
