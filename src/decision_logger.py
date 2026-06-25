"""Decision logger for storing moderation decisions in JSONL format."""

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional


@dataclass
class Decision:
    """Represents a moderation decision."""

    reddit_id: str
    content_type: str  # "post" or "comment"
    author: str
    action: str  # "approve", "remove", "flag"
    reason: str
    confidence: float
    decided_by: str  # "bot" or "human"
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    removal_reason_id: Optional[str] = None

    def to_dict(self) -> dict:
        """Convert decision to dictionary for JSON serialization."""
        return {
            "reddit_id": self.reddit_id,
            "content_type": self.content_type,
            "author": self.author,
            "action": self.action,
            "reason": self.reason,
            "confidence": self.confidence,
            "decided_by": self.decided_by,
            "timestamp": self.timestamp,
            "removal_reason_id": self.removal_reason_id,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Decision":
        """Create Decision from dictionary."""
        return cls(
            reddit_id=data["reddit_id"],
            content_type=data["content_type"],
            author=data["author"],
            action=data["action"],
            reason=data["reason"],
            confidence=data["confidence"],
            decided_by=data["decided_by"],
            timestamp=data.get("timestamp", datetime.now(timezone.utc).isoformat()),
            removal_reason_id=data.get("removal_reason_id"),
        )


class DecisionLogger:
    """Logs moderation decisions to a JSONL file."""

    def __init__(self, log_path: Path):
        """Initialize the logger with a path to the JSONL file."""
        self.log_path = Path(log_path)
        self._ensure_file_exists()

    def _ensure_file_exists(self) -> None:
        """Create the log file if it doesn't exist."""
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        if not self.log_path.exists():
            self.log_path.touch()

    def log(self, decision: Decision) -> None:
        """Append a decision to the log file."""
        with open(self.log_path, "a") as f:
            f.write(json.dumps(decision.to_dict()) + "\n")

    def get_recent(self, limit: int = 10) -> list[Decision]:
        """Get the most recent decisions, newest first."""
        decisions = self._read_all()
        decisions.reverse()  # Most recent first
        return decisions[:limit]

    def get_by_id(self, reddit_id: str) -> Optional[Decision]:
        """Find a decision by Reddit ID."""
        for decision in self._read_all():
            if decision.reddit_id == reddit_id:
                return decision
        return None

    def get_by_author(self, author: str) -> list[Decision]:
        """Get all decisions for a specific author."""
        return [d for d in self._read_all() if d.author == author]

    def count_actions(self) -> dict[str, int]:
        """Count decisions by action type."""
        counts: dict[str, int] = {}
        for decision in self._read_all():
            counts[decision.action] = counts.get(decision.action, 0) + 1
        return counts

    def _read_all(self) -> list[Decision]:
        """Read all decisions from the log file."""
        decisions = []
        if not self.log_path.exists():
            return decisions

        with open(self.log_path) as f:
            for line in f:
                line = line.strip()
                if line:
                    data = json.loads(line)
                    decisions.append(Decision.from_dict(data))
        return decisions
