"""Tests for the Claude session spawner."""

import json
from unittest.mock import patch, MagicMock

import pytest

from src.claude_session import (
    ClaudeSession,
    ModerationContext,
    ModerationDecision,
    build_prompt,
)
from src.reddit_client import RedditItem, RemovalReason
from src.decision_logger import Decision


class TestModerationContext:
    """Tests for the ModerationContext dataclass."""

    def test_to_prompt_string(self):
        """Test converting context to prompt string."""
        item = RedditItem(
            reddit_id="t3_test123",
            content_type="post",
            title="My FIRE journey",
            body="I've been saving for 10 years and finally hit $2M.",
            author="fire_saver",
            author_karma=5000,
            account_age_days=365,
            url="https://reddit.com/r/chubbyfire/test123",
            reports=[],
            created_utc=1700000000,
        )

        rules = [
            {"short_name": "Be civil", "description": "No insults or attacks"},
            {"short_name": "Stay on topic", "description": "Posts must be FIRE related"},
        ]

        removal_reasons = [
            RemovalReason(id="r1", title="Spam", message="Removed for spam"),
            RemovalReason(id="r2", title="Off-topic", message="Not FIRE related"),
        ]

        recent_decisions = [
            Decision(
                reddit_id="t3_prev1",
                content_type="post",
                author="user1",
                action="approve",
                reason="Relevant FIRE post",
                confidence=0.95,
                decided_by="bot",
            )
        ]

        context = ModerationContext(
            item=item,
            subreddit_rules=rules,
            removal_reasons=removal_reasons,
            recent_decisions=recent_decisions,
        )

        prompt = context.to_prompt()

        assert "FIRE journey" in prompt
        assert "fire_saver" in prompt
        assert "5,000" in prompt or "5000" in prompt
        assert "Be civil" in prompt
        assert "Spam" in prompt
        assert "r1" in prompt  # Removal reason ID


class TestBuildPrompt:
    """Tests for the prompt builder."""

    def test_build_prompt_includes_instructions(self):
        """Test that the prompt includes moderation instructions."""
        item = RedditItem(
            reddit_id="t3_test",
            content_type="post",
            title="Test",
            body="Test content",
            author="user",
            author_karma=100,
            account_age_days=30,
            url="https://reddit.com/test",
            reports=[],
            created_utc=1700000000,
        )

        prompt = build_prompt(
            item=item,
            subreddit_rules=[],
            removal_reasons=[],
            recent_decisions=[],
        )

        assert "moderator" in prompt.lower() or "moderation" in prompt.lower()
        assert "approve" in prompt.lower()
        assert "remove" in prompt.lower()
        assert "confidence" in prompt.lower()

    def test_build_prompt_for_reported_content(self):
        """Test prompt for content with reports."""
        item = RedditItem(
            reddit_id="t3_reported",
            content_type="post",
            title="Suspicious",
            body="Buy my course!",
            author="spammer",
            author_karma=10,
            account_age_days=1,
            url="https://reddit.com/test",
            reports=[{"reason": "spam", "count": 3, "type": "user"}],
            created_utc=1700000000,
        )

        prompt = build_prompt(
            item=item,
            subreddit_rules=[],
            removal_reasons=[],
            recent_decisions=[],
        )

        assert "spam" in prompt.lower()
        assert "3" in prompt  # Report count


class TestModerationDecision:
    """Tests for parsing moderation decisions."""

    def test_parse_approve_decision(self):
        """Test parsing an approve decision from Claude output."""
        output = """
        Based on my analysis, this is a legitimate FIRE milestone post.

        DECISION: approve
        CONFIDENCE: 0.95
        REASON: This is a genuine post about reaching a FIRE milestone, which is on-topic for r/chubbyfire.
        """

        decision = ModerationDecision.parse(output)

        assert decision.action == "approve"
        assert decision.confidence == 0.95
        assert "milestone" in decision.reason.lower() or "genuine" in decision.reason.lower()

    def test_parse_remove_decision(self):
        """Test parsing a remove decision with reason ID."""
        output = """
        This appears to be spam promoting a course.

        DECISION: remove
        CONFIDENCE: 0.98
        REASON: Self-promotional spam content that violates community guidelines.
        REMOVAL_REASON_ID: spam_reason_123
        """

        decision = ModerationDecision.parse(output)

        assert decision.action == "remove"
        assert decision.confidence == 0.98
        assert decision.removal_reason_id == "spam_reason_123"

    def test_parse_flag_decision(self):
        """Test parsing a flag for review decision."""
        output = """
        I'm not certain about this post. It could be legitimate but has some concerning elements.

        DECISION: flag
        CONFIDENCE: 0.65
        REASON: Mixed signals - could be genuine but tone is somewhat promotional. Human review recommended.
        """

        decision = ModerationDecision.parse(output)

        assert decision.action == "flag"
        assert decision.confidence == 0.65

    def test_parse_invalid_output_returns_flag(self):
        """Test that invalid output defaults to flag for review."""
        output = "I don't know what to do with this."

        decision = ModerationDecision.parse(output)

        assert decision.action == "flag"
        assert decision.confidence < 0.5

    def test_parse_handles_missing_fields(self):
        """Test handling output with missing optional fields."""
        output = """
        DECISION: approve
        CONFIDENCE: 0.9
        REASON: Looks good.
        """

        decision = ModerationDecision.parse(output)

        assert decision.action == "approve"
        assert decision.removal_reason_id is None


class TestClaudeSession:
    """Tests for the Claude session spawner."""

    @patch("src.claude_session.subprocess.run")
    def test_spawn_session(self, mock_run):
        """Test spawning a Claude session."""
        mock_run.return_value = MagicMock(
            stdout="""
            This is a valid FIRE post.

            DECISION: approve
            CONFIDENCE: 0.92
            REASON: Legitimate milestone celebration post.
            """,
            returncode=0,
        )

        item = RedditItem(
            reddit_id="t3_test",
            content_type="post",
            title="Hit $2M!",
            body="Finally reached my goal.",
            author="fire_winner",
            author_karma=5000,
            account_age_days=365,
            url="https://reddit.com/test",
            reports=[],
            created_utc=1700000000,
        )

        session = ClaudeSession()
        decision = session.get_decision(
            item=item,
            subreddit_rules=[],
            removal_reasons=[],
            recent_decisions=[],
        )

        assert decision.action == "approve"
        assert decision.confidence == 0.92
        mock_run.assert_called_once()

    @patch("src.claude_session.subprocess.run")
    def test_session_uses_claude_cli(self, mock_run):
        """Test that the session invokes the claude CLI."""
        mock_run.return_value = MagicMock(
            stdout="DECISION: approve\nCONFIDENCE: 0.9\nREASON: ok",
            returncode=0,
        )

        item = RedditItem(
            reddit_id="t3_test",
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

        session = ClaudeSession()
        session.get_decision(
            item=item,
            subreddit_rules=[],
            removal_reasons=[],
            recent_decisions=[],
        )

        # Check that claude CLI was called
        call_args = mock_run.call_args
        assert "claude" in call_args.args[0][0]

    @patch("src.claude_session.subprocess.run")
    def test_session_handles_error(self, mock_run):
        """Test handling Claude CLI errors."""
        mock_run.return_value = MagicMock(
            stdout="",
            stderr="Error: rate limited",
            returncode=1,
        )

        item = RedditItem(
            reddit_id="t3_test",
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

        session = ClaudeSession()
        decision = session.get_decision(
            item=item,
            subreddit_rules=[],
            removal_reasons=[],
            recent_decisions=[],
        )

        # Should default to flag on error
        assert decision.action == "flag"
        assert decision.confidence < 0.5
