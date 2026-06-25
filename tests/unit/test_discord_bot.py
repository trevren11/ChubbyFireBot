"""Tests for the Discord bot."""

import json
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.discord_bot import (
    DiscordBot,
    ModerationEmbed,
    MessageTracker,
    ActionButton,
)
from src.reddit_client import RedditItem, RemovalReason


class TestModerationEmbed:
    """Tests for the ModerationEmbed builder."""

    def test_create_post_embed(self):
        """Test creating an embed for a post."""
        item = RedditItem(
            reddit_id="t3_abc123",
            content_type="post",
            title="My FIRE journey",
            body="I've been saving for 10 years...",
            author="fire_user",
            author_karma=5000,
            account_age_days=365,
            url="https://reddit.com/r/chubbyfire/abc123",
            reports=[{"reason": "spam", "count": 1, "type": "user"}],
            created_utc=1700000000,
        )

        embed = ModerationEmbed.create(
            item=item,
            bot_decision="approve",
            confidence=0.92,
            reason="Relevant FIRE content",
        )

        assert embed.title == "[POST] My FIRE journey"
        assert "fire_user" in embed.description
        assert "5,000" in embed.description or "5000" in embed.description
        assert "92%" in str(embed.fields) or "0.92" in str(embed.fields)

    def test_create_comment_embed(self):
        """Test creating an embed for a comment."""
        item = RedditItem(
            reddit_id="t1_xyz789",
            content_type="comment",
            title=None,
            body="Great advice! I'll try that approach.",
            author="helpful_commenter",
            author_karma=1200,
            account_age_days=90,
            url="https://reddit.com/r/chubbyfire/abc123/comment/xyz789",
            reports=[],
            created_utc=1700000000,
        )

        embed = ModerationEmbed.create(
            item=item,
            bot_decision="approve",
            confidence=0.95,
            reason="Constructive comment",
        )

        assert embed.title == "[COMMENT] Review Needed"
        assert "helpful_commenter" in embed.description

    def test_embed_includes_reports(self):
        """Test that embed shows report information."""
        item = RedditItem(
            reddit_id="t3_reported",
            content_type="post",
            title="Suspicious post",
            body="Buy my course!",
            author="spammer",
            author_karma=10,
            account_age_days=2,
            url="https://reddit.com/r/chubbyfire/reported",
            reports=[
                {"reason": "spam", "count": 3, "type": "user"},
                {"reason": "self-promotion", "by": "mod1", "type": "mod"},
            ],
            created_utc=1700000000,
        )

        embed = ModerationEmbed.create(
            item=item,
            bot_decision="remove",
            confidence=0.98,
            reason="Spam detected",
        )

        # Should mention reports somewhere
        embed_str = str(embed.fields) + str(embed.description)
        assert "spam" in embed_str.lower() or "report" in embed_str.lower()

    def test_embed_truncates_long_content(self):
        """Test that long content is truncated."""
        long_body = "A" * 2000

        item = RedditItem(
            reddit_id="t3_longpost",
            content_type="post",
            title="Long post",
            body=long_body,
            author="verbose_user",
            author_karma=100,
            account_age_days=30,
            url="https://reddit.com/r/chubbyfire/longpost",
            reports=[],
            created_utc=1700000000,
        )

        embed = ModerationEmbed.create(
            item=item,
            bot_decision="flag",
            confidence=0.6,
            reason="Needs review",
        )

        # Content should be truncated
        assert len(embed.description) <= 1024


class TestMessageTracker:
    """Tests for Discord message to Reddit item tracking."""

    def test_save_and_load_mapping(self, temp_data_dir: Path):
        """Test saving and loading message mappings."""
        tracker = MessageTracker(temp_data_dir / "messages.json")

        tracker.save("discord_123", "t3_reddit456")
        tracker.save("discord_789", "t1_comment123")

        # Reload from disk
        tracker2 = MessageTracker(temp_data_dir / "messages.json")
        assert tracker2.get_reddit_id("discord_123") == "t3_reddit456"
        assert tracker2.get_reddit_id("discord_789") == "t1_comment123"

    def test_get_nonexistent_mapping(self, temp_data_dir: Path):
        """Test getting a mapping that doesn't exist."""
        tracker = MessageTracker(temp_data_dir / "messages.json")
        assert tracker.get_reddit_id("nonexistent") is None

    def test_delete_mapping(self, temp_data_dir: Path):
        """Test deleting a mapping."""
        tracker = MessageTracker(temp_data_dir / "messages.json")
        tracker.save("discord_123", "t3_reddit456")
        tracker.delete("discord_123")
        assert tracker.get_reddit_id("discord_123") is None


class TestActionButton:
    """Tests for action buttons."""

    def test_create_approve_button(self):
        """Test creating an approve button."""
        button = ActionButton.approve()
        assert button.label == "Approve"
        assert button.custom_id == "approve"
        assert button.style.name == "success" or button.style.value == 3

    def test_create_remove_button_with_reason(self):
        """Test creating a remove button with a reason."""
        reason = RemovalReason(id="spam_id", title="Spam", message="Removed for spam")
        button = ActionButton.remove(reason)
        assert "Spam" in button.label
        assert "spam_id" in button.custom_id


class TestDiscordBot:
    """Tests for the DiscordBot class."""

    @pytest.fixture
    def bot_config(self, temp_data_dir: Path):
        """Bot configuration for tests."""
        return {
            "token": "test_token",
            "channel_id": 123456789,
            "data_dir": temp_data_dir,
        }

    def test_init(self, bot_config):
        """Test bot initialization."""
        with patch("src.discord_bot.commands.Bot"):
            bot = DiscordBot(**bot_config)
            assert bot.channel_id == 123456789

    @pytest.mark.asyncio
    async def test_send_moderation_message(self, bot_config):
        """Test sending a moderation message."""
        with patch("src.discord_bot.commands.Bot") as mock_bot_class:
            mock_bot = MagicMock()
            mock_bot_class.return_value = mock_bot

            mock_channel = AsyncMock()
            mock_message = MagicMock()
            mock_message.id = 111222333
            mock_channel.send = AsyncMock(return_value=mock_message)
            mock_bot.get_channel = MagicMock(return_value=mock_channel)

            bot = DiscordBot(**bot_config)
            bot._bot = mock_bot

            item = RedditItem(
                reddit_id="t3_test123",
                content_type="post",
                title="Test Post",
                body="Test content",
                author="tester",
                author_karma=100,
                account_age_days=30,
                url="https://reddit.com/test",
                reports=[],
                created_utc=1700000000,
            )

            removal_reasons = [
                RemovalReason(id="r1", title="Spam", message="Spam message"),
                RemovalReason(id="r2", title="Off-topic", message="Off-topic message"),
            ]

            message_id = await bot.send_moderation_message(
                item=item,
                bot_decision="flag",
                confidence=0.75,
                reason="Needs human review",
                removal_reasons=removal_reasons,
                dry_run=False,
            )

            assert message_id == "111222333"
            mock_channel.send.assert_called_once()

    @pytest.mark.asyncio
    async def test_send_dry_run_message(self, bot_config):
        """Test that dry run messages are marked."""
        with patch("src.discord_bot.commands.Bot") as mock_bot_class:
            mock_bot = MagicMock()
            mock_bot_class.return_value = mock_bot

            mock_channel = AsyncMock()
            mock_message = MagicMock()
            mock_message.id = 999888777
            mock_channel.send = AsyncMock(return_value=mock_message)
            mock_bot.get_channel = MagicMock(return_value=mock_channel)

            bot = DiscordBot(**bot_config)
            bot._bot = mock_bot

            item = RedditItem(
                reddit_id="t3_dryrun",
                content_type="post",
                title="Dry Run Test",
                body="Content",
                author="user",
                author_karma=100,
                account_age_days=30,
                url="https://reddit.com/test",
                reports=[],
                created_utc=1700000000,
            )

            await bot.send_moderation_message(
                item=item,
                bot_decision="remove",
                confidence=0.99,
                reason="Test removal",
                removal_reasons=[],
                dry_run=True,
            )

            # Check that the call included dry run indicator
            call_kwargs = mock_channel.send.call_args
            embed = call_kwargs.kwargs.get("embed") or call_kwargs.args[0]
            assert "[DRY RUN]" in embed.title

    def test_on_button_callback_registered(self, bot_config):
        """Test that button callbacks are properly set up."""
        with patch("src.discord_bot.commands.Bot"):
            bot = DiscordBot(**bot_config)
            # The bot should have interaction handlers set up
            assert hasattr(bot, "handle_approve")
            assert hasattr(bot, "handle_remove")
