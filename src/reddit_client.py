"""Reddit client wrapper using PRAW."""

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

import praw
from praw.models import Comment, Submission


@dataclass
class RedditItem:
    """Represents a Reddit post or comment for moderation."""

    reddit_id: str  # t3_xxx for posts, t1_xxx for comments
    content_type: str  # "post" or "comment"
    title: Optional[str]
    body: str
    author: str
    author_karma: int
    account_age_days: int
    url: str
    reports: list[dict]
    created_utc: float

    @classmethod
    def from_submission(cls, submission: Submission) -> "RedditItem":
        """Create RedditItem from a Reddit submission (post)."""
        now = datetime.now(timezone.utc).timestamp()
        account_age = int((now - submission.author.created_utc) / 86400) if submission.author else 0

        reports = []
        for report in submission.mod_reports:
            reports.append({"reason": report[0], "by": report[1], "type": "mod"})
        for report in submission.user_reports:
            reports.append({"reason": report[0], "count": report[1], "type": "user"})

        return cls(
            reddit_id=f"t3_{submission.id}",
            content_type="post",
            title=submission.title,
            body=submission.selftext,
            author=submission.author.name if submission.author else "[deleted]",
            author_karma=(
                submission.author.link_karma + submission.author.comment_karma
                if submission.author
                else 0
            ),
            account_age_days=account_age,
            url=submission.url,
            reports=reports,
            created_utc=submission.created_utc,
        )

    @classmethod
    def from_comment(cls, comment: Comment) -> "RedditItem":
        """Create RedditItem from a Reddit comment."""
        now = datetime.now(timezone.utc).timestamp()
        account_age = int((now - comment.author.created_utc) / 86400) if comment.author else 0

        reports = []
        for report in comment.mod_reports:
            reports.append({"reason": report[0], "by": report[1], "type": "mod"})
        for report in comment.user_reports:
            reports.append({"reason": report[0], "count": report[1], "type": "user"})

        return cls(
            reddit_id=f"t1_{comment.id}",
            content_type="comment",
            title=None,
            body=comment.body,
            author=comment.author.name if comment.author else "[deleted]",
            author_karma=(
                comment.author.link_karma + comment.author.comment_karma
                if comment.author
                else 0
            ),
            account_age_days=account_age,
            url=f"https://reddit.com{comment.permalink}",
            reports=reports,
            created_utc=comment.created_utc,
        )


@dataclass
class RemovalReason:
    """Represents a subreddit removal reason."""

    id: str
    title: str
    message: str

    @classmethod
    def from_reddit(cls, reason) -> "RemovalReason":
        """Create RemovalReason from Reddit API object."""
        return cls(
            id=reason.id,
            title=reason.title,
            message=reason.message,
        )


class RedditClient:
    """Wrapper around PRAW for Reddit API operations."""

    def __init__(
        self,
        client_id: str,
        client_secret: str,
        username: str,
        password: str,
        user_agent: str,
        subreddit: str,
    ):
        """Initialize the Reddit client."""
        self.reddit = praw.Reddit(
            client_id=client_id,
            client_secret=client_secret,
            username=username,
            password=password,
            user_agent=user_agent,
        )
        self.subreddit_name = subreddit
        self._subreddit = None

    @property
    def subreddit(self):
        """Get the subreddit object (lazy loaded)."""
        if self._subreddit is None:
            self._subreddit = self.reddit.subreddit(self.subreddit_name)
        return self._subreddit

    def get_mod_queue(self, limit: int = 100) -> list[RedditItem]:
        """Fetch items from the mod queue."""
        items = []
        for item in self.subreddit.mod.modqueue(limit=limit):
            if hasattr(item, "title"):
                # It's a submission
                items.append(RedditItem.from_submission(item))
            else:
                # It's a comment
                items.append(RedditItem.from_comment(item))
        return items

    def get_new_posts(self, limit: int = 25) -> list[RedditItem]:
        """Fetch new posts from the subreddit."""
        items = []
        for submission in self.subreddit.new(limit=limit):
            items.append(RedditItem.from_submission(submission))
        return items

    def get_removal_reasons(self) -> list[RemovalReason]:
        """Fetch the subreddit's configured removal reasons."""
        reasons = []
        for reason in self.subreddit.mod.removal_reasons:
            reasons.append(RemovalReason.from_reddit(reason))
        return reasons

    def get_subreddit_rules(self) -> list[dict]:
        """Fetch the subreddit rules."""
        rules = []
        for rule in self.subreddit.rules:
            rules.append({
                "short_name": rule.short_name,
                "description": rule.description,
            })
        return rules

    def approve(self, reddit_id: str) -> None:
        """Approve a post or comment."""
        item = self._get_item(reddit_id)
        item.mod.approve()

    def remove(self, reddit_id: str, reason_id: Optional[str] = None) -> None:
        """Remove a post or comment with optional removal reason."""
        item = self._get_item(reddit_id)
        if reason_id:
            item.mod.remove(reason_id=reason_id)
        else:
            item.mod.remove()

    def _get_item(self, reddit_id: str):
        """Get a Reddit item (submission or comment) by full ID."""
        prefix, item_id = reddit_id.split("_", 1)
        if prefix == "t3":
            return self.reddit.submission(id=item_id)
        elif prefix == "t1":
            return self.reddit.comment(id=item_id)
        else:
            raise ValueError(f"Unknown Reddit ID prefix: {prefix}")
