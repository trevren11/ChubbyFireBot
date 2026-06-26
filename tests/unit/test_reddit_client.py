"""Tests for the Reddit client wrapper."""

from unittest.mock import MagicMock, patch, PropertyMock
from datetime import datetime, timezone

import pytest

from src.reddit_client import RedditClient, RedditItem, RemovalReason


class TestRedditItem:
    """Tests for the RedditItem dataclass."""

    def test_from_submission(self):
        """Test creating RedditItem from a Reddit submission."""
        mock_submission = MagicMock()
        mock_submission.id = "abc123"
        mock_submission.title = "Test Post"
        mock_submission.selftext = "Post body"
        mock_submission.author.name = "test_user"
        mock_submission.author.link_karma = 1000
        mock_submission.author.comment_karma = 500
        mock_submission.author.created_utc = 1600000000
        mock_submission.url = "https://reddit.com/r/test/abc123"
        mock_submission.mod_reports = []
        mock_submission.user_reports = [["spam", 1]]
        mock_submission.created_utc = 1700000000

        item = RedditItem.from_submission(mock_submission)

        assert item.reddit_id == "t3_abc123"
        assert item.content_type == "post"
        assert item.title == "Test Post"
        assert item.body == "Post body"
        assert item.author == "test_user"
        assert item.author_karma == 1500

    def test_from_comment(self):
        """Test creating RedditItem from a Reddit comment."""
        mock_comment = MagicMock()
        mock_comment.id = "xyz789"
        mock_comment.body = "Comment text"
        mock_comment.author.name = "commenter"
        mock_comment.author.link_karma = 200
        mock_comment.author.comment_karma = 800
        mock_comment.author.created_utc = 1600000000
        mock_comment.permalink = "/r/test/comments/abc/test/xyz789"
        mock_comment.mod_reports = [["off-topic", "mod1"]]
        mock_comment.user_reports = []
        mock_comment.created_utc = 1700000000

        item = RedditItem.from_comment(mock_comment)

        assert item.reddit_id == "t1_xyz789"
        assert item.content_type == "comment"
        assert item.title is None
        assert item.body == "Comment text"
        assert item.author == "commenter"


class TestRemovalReason:
    """Tests for the RemovalReason dataclass."""

    def test_from_reddit_reason(self):
        """Test creating RemovalReason from Reddit API object."""
        mock_reason = MagicMock()
        mock_reason.id = "reason123"
        mock_reason.title = "Spam"
        mock_reason.message = "Your post was removed for spam."

        reason = RemovalReason.from_reddit(mock_reason)

        assert reason.id == "reason123"
        assert reason.title == "Spam"
        assert reason.message == "Your post was removed for spam."


class TestRedditClient:
    """Tests for the RedditClient class."""

    @patch("src.reddit_client.praw.Reddit")
    def test_init(self, mock_reddit_class):
        """Test client initialization."""
        client = RedditClient(
            client_id="test_id",
            client_secret="test_secret",
            username="test_user",
            password="test_pass",
            user_agent="TestBot/1.0",
            subreddit="chubbyfire",
        )

        mock_reddit_class.assert_called_once()
        assert client.subreddit_name == "chubbyfire"

    @patch("src.reddit_client.praw.Reddit")
    def test_get_mod_queue(self, mock_reddit_class):
        """Test fetching mod queue items."""
        # Setup mock
        mock_reddit = MagicMock()
        mock_reddit_class.return_value = mock_reddit

        mock_sub = MagicMock()
        mock_reddit.subreddit.return_value = mock_sub

        # Create mock items in mod queue
        mock_post = MagicMock()
        mock_post.id = "post1"
        mock_post.title = "Test Post"
        mock_post.selftext = "Body"
        mock_post.author.name = "user1"
        mock_post.author.link_karma = 100
        mock_post.author.comment_karma = 100
        mock_post.author.created_utc = 1600000000
        mock_post.url = "https://reddit.com/r/test/post1"
        mock_post.mod_reports = []
        mock_post.user_reports = []
        mock_post.created_utc = 1700000000
        # Submissions have title attribute
        type(mock_post).title = PropertyMock(return_value="Test Post")

        mock_sub.mod.modqueue.return_value = [mock_post]

        client = RedditClient(
            client_id="test_id",
            client_secret="test_secret",
            username="test_user",
            password="test_pass",
            user_agent="TestBot/1.0",
            subreddit="chubbyfire",
        )

        items = client.get_mod_queue(limit=10)

        assert len(items) == 1
        assert items[0].reddit_id == "t3_post1"

    @patch("src.reddit_client.praw.Reddit")
    def test_get_new_posts(self, mock_reddit_class):
        """Test fetching new posts."""
        mock_reddit = MagicMock()
        mock_reddit_class.return_value = mock_reddit

        mock_sub = MagicMock()
        mock_reddit.subreddit.return_value = mock_sub

        mock_post = MagicMock()
        mock_post.id = "newpost1"
        mock_post.title = "New Post"
        mock_post.selftext = "Content"
        mock_post.author.name = "poster"
        mock_post.author.link_karma = 500
        mock_post.author.comment_karma = 500
        mock_post.author.created_utc = 1600000000
        mock_post.url = "https://reddit.com/r/test/newpost1"
        mock_post.mod_reports = []
        mock_post.user_reports = []
        mock_post.created_utc = 1700000000

        mock_sub.new.return_value = [mock_post]

        client = RedditClient(
            client_id="test_id",
            client_secret="test_secret",
            username="test_user",
            password="test_pass",
            user_agent="TestBot/1.0",
            subreddit="chubbyfire",
        )

        posts = client.get_new_posts(limit=25)

        assert len(posts) == 1
        mock_sub.new.assert_called_once_with(limit=25)

    @patch("src.reddit_client.praw.Reddit")
    def test_get_removal_reasons(self, mock_reddit_class):
        """Test fetching subreddit removal reasons."""
        mock_reddit = MagicMock()
        mock_reddit_class.return_value = mock_reddit

        mock_sub = MagicMock()
        mock_reddit.subreddit.return_value = mock_sub

        mock_reason1 = MagicMock()
        mock_reason1.id = "r1"
        mock_reason1.title = "Spam"
        mock_reason1.message = "Spam removal message"

        mock_reason2 = MagicMock()
        mock_reason2.id = "r2"
        mock_reason2.title = "Off-topic"
        mock_reason2.message = "Off-topic removal message"

        mock_sub.mod.removal_reasons = [mock_reason1, mock_reason2]

        client = RedditClient(
            client_id="test_id",
            client_secret="test_secret",
            username="test_user",
            password="test_pass",
            user_agent="TestBot/1.0",
            subreddit="chubbyfire",
        )

        reasons = client.get_removal_reasons()

        assert len(reasons) == 2
        assert reasons[0].title == "Spam"
        assert reasons[1].title == "Off-topic"

    @patch("src.reddit_client.praw.Reddit")
    def test_approve_item(self, mock_reddit_class):
        """Test approving an item."""
        mock_reddit = MagicMock()
        mock_reddit_class.return_value = mock_reddit

        mock_submission = MagicMock()
        mock_reddit.submission.return_value = mock_submission

        client = RedditClient(
            client_id="test_id",
            client_secret="test_secret",
            username="test_user",
            password="test_pass",
            user_agent="TestBot/1.0",
            subreddit="chubbyfire",
        )

        client.approve("t3_abc123")

        mock_reddit.submission.assert_called_once_with(id="abc123")
        mock_submission.mod.approve.assert_called_once()

    @patch("src.reddit_client.praw.Reddit")
    def test_remove_item_with_reason(self, mock_reddit_class):
        """Test removing an item with a removal reason."""
        mock_reddit = MagicMock()
        mock_reddit_class.return_value = mock_reddit

        mock_submission = MagicMock()
        mock_reddit.submission.return_value = mock_submission

        client = RedditClient(
            client_id="test_id",
            client_secret="test_secret",
            username="test_user",
            password="test_pass",
            user_agent="TestBot/1.0",
            subreddit="chubbyfire",
        )

        client.remove("t3_abc123", reason_id="spam_reason")

        mock_reddit.submission.assert_called_once_with(id="abc123")
        mock_submission.mod.remove.assert_called_once_with(reason_id="spam_reason")

    @patch("src.reddit_client.praw.Reddit")
    def test_remove_comment(self, mock_reddit_class):
        """Test removing a comment."""
        mock_reddit = MagicMock()
        mock_reddit_class.return_value = mock_reddit

        mock_comment = MagicMock()
        mock_reddit.comment.return_value = mock_comment

        client = RedditClient(
            client_id="test_id",
            client_secret="test_secret",
            username="test_user",
            password="test_pass",
            user_agent="TestBot/1.0",
            subreddit="chubbyfire",
        )

        client.remove("t1_xyz789", reason_id="off_topic")

        mock_reddit.comment.assert_called_once_with(id="xyz789")
        mock_comment.mod.remove.assert_called_once()

    @patch("src.reddit_client.praw.Reddit")
    def test_get_subreddit_rules(self, mock_reddit_class):
        """Test fetching subreddit rules."""
        mock_reddit = MagicMock()
        mock_reddit_class.return_value = mock_reddit

        mock_sub = MagicMock()
        mock_reddit.subreddit.return_value = mock_sub

        # Mock rules as an iterable of rule objects
        mock_rule1 = MagicMock()
        mock_rule1.short_name = "Be civil"
        mock_rule1.description = "No insults"
        mock_rule2 = MagicMock()
        mock_rule2.short_name = "Stay on topic"
        mock_rule2.description = "FIRE related only"
        mock_sub.rules = [mock_rule1, mock_rule2]

        client = RedditClient(
            client_id="test_id",
            client_secret="test_secret",
            username="test_user",
            password="test_pass",
            user_agent="TestBot/1.0",
            subreddit="chubbyfire",
        )

        rules = client.get_subreddit_rules()

        assert len(rules) == 2
        assert rules[0]["short_name"] == "Be civil"
