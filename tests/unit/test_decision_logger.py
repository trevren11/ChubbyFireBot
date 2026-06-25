"""Tests for the decision logger (JSONL storage)."""

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from src.decision_logger import DecisionLogger, Decision


class TestDecision:
    """Tests for the Decision dataclass."""

    def test_decision_creation(self):
        """Test creating a Decision with all required fields."""
        decision = Decision(
            reddit_id="t3_abc123",
            content_type="post",
            author="test_user",
            action="approve",
            reason="Relevant content",
            confidence=0.95,
            decided_by="bot",
        )
        assert decision.reddit_id == "t3_abc123"
        assert decision.content_type == "post"
        assert decision.action == "approve"
        assert decision.confidence == 0.95

    def test_decision_to_dict(self):
        """Test converting Decision to dictionary."""
        decision = Decision(
            reddit_id="t3_abc123",
            content_type="post",
            author="test_user",
            action="remove",
            reason="Spam",
            confidence=0.98,
            decided_by="bot",
        )
        d = decision.to_dict()
        assert d["reddit_id"] == "t3_abc123"
        assert d["action"] == "remove"
        assert "timestamp" in d

    def test_decision_from_dict(self):
        """Test creating Decision from dictionary."""
        data = {
            "reddit_id": "t1_xyz789",
            "content_type": "comment",
            "author": "user123",
            "action": "approve",
            "reason": "Good discussion",
            "confidence": 0.85,
            "decided_by": "human",
            "timestamp": "2024-01-15T10:30:00+00:00",
        }
        decision = Decision.from_dict(data)
        assert decision.reddit_id == "t1_xyz789"
        assert decision.content_type == "comment"
        assert decision.decided_by == "human"


class TestDecisionLogger:
    """Tests for the DecisionLogger class."""

    def test_init_creates_file_if_not_exists(self, temp_data_dir: Path):
        """Test that logger creates the log file if it doesn't exist."""
        log_path = temp_data_dir / "decisions.jsonl"
        logger = DecisionLogger(log_path)
        assert log_path.exists()

    def test_log_decision(self, temp_data_dir: Path):
        """Test logging a single decision."""
        log_path = temp_data_dir / "decisions.jsonl"
        logger = DecisionLogger(log_path)

        decision = Decision(
            reddit_id="t3_test123",
            content_type="post",
            author="test_author",
            action="approve",
            reason="Good content",
            confidence=0.92,
            decided_by="bot",
        )
        logger.log(decision)

        # Read back and verify
        with open(log_path) as f:
            line = f.readline()
            data = json.loads(line)
            assert data["reddit_id"] == "t3_test123"
            assert data["action"] == "approve"

    def test_log_multiple_decisions(self, temp_data_dir: Path):
        """Test logging multiple decisions appends to file."""
        log_path = temp_data_dir / "decisions.jsonl"
        logger = DecisionLogger(log_path)

        for i in range(3):
            decision = Decision(
                reddit_id=f"t3_test{i}",
                content_type="post",
                author=f"author{i}",
                action="approve" if i % 2 == 0 else "remove",
                reason=f"Reason {i}",
                confidence=0.9 + i * 0.01,
                decided_by="bot",
            )
            logger.log(decision)

        # Verify all three were logged
        with open(log_path) as f:
            lines = f.readlines()
            assert len(lines) == 3

    def test_get_recent_decisions(self, temp_data_dir: Path):
        """Test retrieving recent decisions."""
        log_path = temp_data_dir / "decisions.jsonl"
        logger = DecisionLogger(log_path)

        # Log 5 decisions
        for i in range(5):
            decision = Decision(
                reddit_id=f"t3_test{i}",
                content_type="post",
                author=f"author{i}",
                action="approve",
                reason=f"Reason {i}",
                confidence=0.9,
                decided_by="bot",
            )
            logger.log(decision)

        # Get last 3
        recent = logger.get_recent(limit=3)
        assert len(recent) == 3
        # Most recent should be first
        assert recent[0].reddit_id == "t3_test4"

    def test_get_decision_by_id(self, temp_data_dir: Path):
        """Test finding a specific decision by Reddit ID."""
        log_path = temp_data_dir / "decisions.jsonl"
        logger = DecisionLogger(log_path)

        decision = Decision(
            reddit_id="t3_findme",
            content_type="post",
            author="test_user",
            action="remove",
            reason="Spam",
            confidence=0.99,
            decided_by="bot",
        )
        logger.log(decision)

        found = logger.get_by_id("t3_findme")
        assert found is not None
        assert found.action == "remove"

    def test_get_decision_by_id_not_found(self, temp_data_dir: Path):
        """Test returns None when decision not found."""
        log_path = temp_data_dir / "decisions.jsonl"
        logger = DecisionLogger(log_path)

        found = logger.get_by_id("t3_nonexistent")
        assert found is None

    def test_get_decisions_by_author(self, temp_data_dir: Path):
        """Test filtering decisions by author."""
        log_path = temp_data_dir / "decisions.jsonl"
        logger = DecisionLogger(log_path)

        # Log decisions for different authors
        for author in ["user1", "user2", "user1", "user3", "user1"]:
            decision = Decision(
                reddit_id=f"t3_{author}_{hash(author)}",
                content_type="post",
                author=author,
                action="approve",
                reason="Test",
                confidence=0.9,
                decided_by="bot",
            )
            logger.log(decision)

        user1_decisions = logger.get_by_author("user1")
        assert len(user1_decisions) == 3

    def test_count_actions(self, temp_data_dir: Path):
        """Test counting actions by type."""
        log_path = temp_data_dir / "decisions.jsonl"
        logger = DecisionLogger(log_path)

        # Log 3 approves and 2 removes
        actions = ["approve", "approve", "remove", "approve", "remove"]
        for i, action in enumerate(actions):
            decision = Decision(
                reddit_id=f"t3_test{i}",
                content_type="post",
                author="test",
                action=action,
                reason="Test",
                confidence=0.9,
                decided_by="bot",
            )
            logger.log(decision)

        counts = logger.count_actions()
        assert counts["approve"] == 3
        assert counts["remove"] == 2
