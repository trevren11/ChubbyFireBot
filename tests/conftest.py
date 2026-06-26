"""Shared test fixtures for ChubbyFireBot tests."""

import json
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Generator
from unittest.mock import MagicMock

import pytest


@pytest.fixture
def temp_data_dir() -> Generator[Path, None, None]:
    """Create a temporary data directory for tests."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)


@pytest.fixture
def sample_post() -> dict:
    """Sample Reddit post data."""
    return {
        "id": "t3_abc123",
        "type": "post",
        "title": "Hit my chubbyFIRE number!",
        "body": "Finally reached $2.5M after 15 years of saving.",
        "author": "fire_achiever",
        "author_karma": 5000,
        "account_age_days": 365,
        "url": "https://reddit.com/r/chubbyfire/comments/abc123",
        "reports": [],
        "created_utc": datetime.now(timezone.utc).isoformat(),
    }


@pytest.fixture
def sample_comment() -> dict:
    """Sample Reddit comment data."""
    return {
        "id": "t1_def456",
        "type": "comment",
        "body": "Congratulations! What was your savings rate?",
        "author": "curious_user",
        "author_karma": 1200,
        "account_age_days": 180,
        "url": "https://reddit.com/r/chubbyfire/comments/abc123/comment/def456",
        "reports": [{"reason": "spam", "count": 1}],
        "created_utc": datetime.now(timezone.utc).isoformat(),
    }


@pytest.fixture
def sample_decision() -> dict:
    """Sample moderation decision."""
    return {
        "id": "t3_abc123",
        "type": "post",
        "author": "fire_achiever",
        "action": "approve",
        "reason": "Relevant FIRE milestone post",
        "confidence": 0.95,
        "decided_by": "bot",
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


@pytest.fixture
def mock_reddit() -> MagicMock:
    """Mock Reddit client."""
    mock = MagicMock()
    mock.subreddit.return_value.mod.modqueue.return_value = []
    mock.subreddit.return_value.new.return_value = []
    return mock


@pytest.fixture
def mock_discord() -> MagicMock:
    """Mock Discord client."""
    mock = MagicMock()
    mock.send_message = MagicMock(return_value="msg_123")
    return mock
