"""Tests for the Claude session spawner."""

import json
from unittest.mock import patch, MagicMock

import pytest

from src.claude_session import (
    ClaudeSession,
    ModerationContext,
    ModerationDecision,
    build_prompt,
    extract_json_block,
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
        assert "json" in prompt.lower()

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


class TestExtractJsonBlock:
    """Tests for extracting the JSON decision block from Claude's free-text output."""

    def test_extract_fenced_json_block(self):
        """Test extracting a well-formed fenced JSON block."""
        output = """
        Based on my analysis, this is a legitimate FIRE milestone post.

        ```json
        {
          "action": "approve",
          "confidence": 0.95,
          "reason": "Genuine milestone post",
          "removal_reason_id": null
        }
        ```
        """

        data = extract_json_block(output)

        assert data is not None
        assert data["action"] == "approve"
        assert data["confidence"] == 0.95

    def test_extract_bare_json_object_fallback(self):
        """Test fallback extraction when Claude forgets the code fence."""
        output = '{"action": "remove", "confidence": 0.8, "reason": "spam"}'

        data = extract_json_block(output)

        assert data is not None
        assert data["action"] == "remove"

    def test_extract_returns_none_for_incomplete_json(self):
        """Test that a still-streaming/incomplete block returns None (not a parse error)."""
        output = """
        Thinking about this...

        ```json
        {
          "action": "approve",
          "confidence":
        """

        assert extract_json_block(output) is None

    def test_extract_returns_none_for_no_json(self):
        """Test that plain text with no JSON returns None."""
        assert extract_json_block("I don't know what to do with this.") is None


class TestModerationDecision:
    """Tests for parsing moderation decisions."""

    def test_parse_approve_decision(self):
        """Test parsing an approve decision from Claude output."""
        output = """
        Based on my analysis, this is a legitimate FIRE milestone post.

        ```json
        {
          "action": "approve",
          "confidence": 0.95,
          "reason": "This is a genuine post about reaching a FIRE milestone, which is on-topic for r/chubbyfire.",
          "removal_reason_id": null
        }
        ```
        """

        decision = ModerationDecision.parse(output)

        assert decision.action == "approve"
        assert decision.confidence == 0.95
        assert "milestone" in decision.reason.lower() or "genuine" in decision.reason.lower()

    def test_parse_remove_decision(self):
        """Test parsing a remove decision with reason ID."""
        output = """
        This appears to be spam promoting a course.

        ```json
        {
          "action": "remove",
          "confidence": 0.98,
          "reason": "Self-promotional spam content that violates community guidelines.",
          "removal_reason_id": "spam_reason_123"
        }
        ```
        """

        decision = ModerationDecision.parse(output)

        assert decision.action == "remove"
        assert decision.confidence == 0.98
        assert decision.removal_reason_id == "spam_reason_123"

    def test_parse_flag_decision(self):
        """Test parsing a flag for review decision."""
        output = """
        I'm not certain about this post. It could be legitimate but has some concerning elements.

        ```json
        {
          "action": "flag",
          "confidence": 0.65,
          "reason": "Mixed signals - could be genuine but tone is somewhat promotional. Human review recommended.",
          "removal_reason_id": null
        }
        ```
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
        ```json
        {
          "action": "approve",
          "confidence": 0.9,
          "reason": "Looks good."
        }
        ```
        """

        decision = ModerationDecision.parse(output)

        assert decision.action == "approve"
        assert decision.removal_reason_id is None

    def test_parse_clamps_invalid_action_and_confidence(self):
        """Test that an invalid action falls back to flag and confidence is clamped."""
        output = """
        ```json
        {
          "action": "delete_everything",
          "confidence": 5,
          "reason": "n/a"
        }
        ```
        """

        decision = ModerationDecision.parse(output)

        assert decision.action == "flag"
        assert decision.confidence == 1.0


class TestClaudeSession:
    """Tests for the Claude session spawner using Taskling API."""

    @patch("src.claude_session.ClaudeSession._wait_for_response")
    @patch("src.claude_session.ClaudeSession._get_chat_state")
    @patch("src.claude_session.urllib.request.urlopen")
    def test_spawn_session(self, mock_urlopen, mock_get_state, mock_wait):
        """Test spawning a Claude session via Taskling API."""
        # Mock API response
        mock_response = MagicMock()
        mock_response.read.return_value = json.dumps({
            "success": True,
        }).encode()
        mock_response.__enter__ = MagicMock(return_value=mock_response)
        mock_response.__exit__ = MagicMock(return_value=False)
        mock_urlopen.return_value = mock_response

        # Mock initial state
        mock_get_state.return_value = {"messages": []}

        # Mock response polling
        mock_wait.return_value = """
            This is a valid FIRE post.

            ```json
            {
              "action": "approve",
              "confidence": 0.92,
              "reason": "Legitimate milestone celebration post.",
              "removal_reason_id": null
            }
            ```
            """

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
        mock_urlopen.assert_called_once()

    @patch("src.claude_session.ClaudeSession._wait_for_response")
    @patch("src.claude_session.ClaudeSession._get_chat_state")
    @patch("src.claude_session.urllib.request.urlopen")
    def test_session_uses_taskling_api(self, mock_urlopen, mock_get_state, mock_wait):
        """Test that the session calls the Taskling API endpoint."""
        mock_response = MagicMock()
        mock_response.read.return_value = json.dumps({
            "success": True,
        }).encode()
        mock_response.__enter__ = MagicMock(return_value=mock_response)
        mock_response.__exit__ = MagicMock(return_value=False)
        mock_urlopen.return_value = mock_response

        mock_get_state.return_value = {"messages": []}
        mock_wait.return_value = '```json\n{"action": "approve", "confidence": 0.9, "reason": "ok"}\n```'

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

        # Check that Taskling API was called
        call_args = mock_urlopen.call_args
        request = call_args.args[0]
        assert "localhost:2525" in request.full_url
        assert "/api/chat/send" in request.full_url

    @patch("src.claude_session.ClaudeSession._wait_for_response")
    @patch("src.claude_session.ClaudeSession._get_chat_state")
    @patch("src.claude_session.urllib.request.urlopen")
    def test_session_requests_sonnet_5_model(self, mock_urlopen, mock_get_state, mock_wait):
        """Test that the session requests the claude-sonnet-5 model by default."""
        mock_response = MagicMock()
        mock_response.read.return_value = json.dumps({"success": True}).encode()
        mock_response.__enter__ = MagicMock(return_value=mock_response)
        mock_response.__exit__ = MagicMock(return_value=False)
        mock_urlopen.return_value = mock_response

        mock_get_state.return_value = {"messages": []}
        mock_wait.return_value = '```json\n{"action": "approve", "confidence": 0.9, "reason": "ok"}\n```'

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

        call_args = mock_urlopen.call_args
        request = call_args.args[0]
        payload = json.loads(request.data.decode("utf-8"))
        assert payload["model"] == "claude-sonnet-5"

    @patch("src.claude_session.ClaudeSession._get_chat_state")
    @patch("src.claude_session.urllib.request.urlopen")
    def test_session_handles_api_error(self, mock_urlopen, mock_get_state):
        """Test handling Taskling API errors."""
        mock_response = MagicMock()
        mock_response.read.return_value = json.dumps({
            "success": False,
            "error": "Session failed",
        }).encode()
        mock_response.__enter__ = MagicMock(return_value=mock_response)
        mock_response.__exit__ = MagicMock(return_value=False)
        mock_urlopen.return_value = mock_response

        mock_get_state.return_value = {"messages": []}

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

    @patch("src.claude_session.ClaudeSession._get_chat_state")
    @patch("src.claude_session.urllib.request.urlopen")
    def test_session_handles_connection_error(self, mock_urlopen, mock_get_state):
        """Test handling connection errors to Taskling API."""
        from urllib.error import URLError
        mock_urlopen.side_effect = URLError("Connection refused")
        mock_get_state.return_value = {"messages": []}

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

        # Should default to flag on connection error
        assert decision.action == "flag"
        assert "connection" in decision.reason.lower() or "error" in decision.reason.lower()

    @patch("src.claude_session.ClaudeSession._wait_for_response")
    @patch("src.claude_session.ClaudeSession._get_chat_state")
    @patch("src.claude_session.urllib.request.urlopen")
    def test_session_handles_timeout(self, mock_urlopen, mock_get_state, mock_wait):
        """Test handling timeout waiting for Claude response."""
        mock_response = MagicMock()
        mock_response.read.return_value = json.dumps({"success": True}).encode()
        mock_response.__enter__ = MagicMock(return_value=mock_response)
        mock_response.__exit__ = MagicMock(return_value=False)
        mock_urlopen.return_value = mock_response

        mock_get_state.return_value = {"messages": []}
        mock_wait.return_value = None  # Timeout

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

        assert decision.action == "flag"
        assert "timed out" in decision.reason.lower()
