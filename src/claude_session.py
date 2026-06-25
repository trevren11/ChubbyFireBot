"""Claude session spawner for moderation decisions."""

import re
import subprocess
from dataclasses import dataclass
from typing import Optional

from src.reddit_client import RedditItem, RemovalReason
from src.decision_logger import Decision


@dataclass
class ModerationDecision:
    """Result of a Claude moderation decision."""

    action: str  # "approve", "remove", "flag"
    confidence: float
    reason: str
    removal_reason_id: Optional[str] = None

    @classmethod
    def parse(cls, output: str) -> "ModerationDecision":
        """Parse a moderation decision from Claude output."""
        # Default values for error cases
        action = "flag"
        confidence = 0.3
        reason = "Could not parse Claude output"
        removal_reason_id = None

        # Try to extract DECISION
        decision_match = re.search(r"DECISION:\s*(\w+)", output, re.IGNORECASE)
        if decision_match:
            action = decision_match.group(1).lower()
            if action not in ("approve", "remove", "flag"):
                action = "flag"

        # Try to extract CONFIDENCE
        confidence_match = re.search(r"CONFIDENCE:\s*([\d.]+)", output, re.IGNORECASE)
        if confidence_match:
            try:
                confidence = float(confidence_match.group(1))
                # Normalize if given as percentage
                if confidence > 1:
                    confidence = confidence / 100
                confidence = max(0, min(1, confidence))
            except ValueError:
                pass

        # Try to extract REASON
        reason_match = re.search(r"REASON:\s*(.+?)(?=\n[A-Z_]+:|$)", output, re.IGNORECASE | re.DOTALL)
        if reason_match:
            reason = reason_match.group(1).strip()

        # Try to extract REMOVAL_REASON_ID
        reason_id_match = re.search(r"REMOVAL_REASON_ID:\s*(\S+)", output, re.IGNORECASE)
        if reason_id_match:
            removal_reason_id = reason_id_match.group(1).strip()

        return cls(
            action=action,
            confidence=confidence,
            reason=reason,
            removal_reason_id=removal_reason_id,
        )


@dataclass
class ModerationContext:
    """Context provided to Claude for making a moderation decision."""

    item: RedditItem
    subreddit_rules: list[dict]
    removal_reasons: list[RemovalReason]
    recent_decisions: list[Decision]

    def to_prompt(self) -> str:
        """Convert context to a prompt string for Claude."""
        parts = []

        # Content being reviewed
        parts.append("## Content to Review")
        parts.append(f"**Type:** {self.item.content_type}")
        if self.item.title:
            parts.append(f"**Title:** {self.item.title}")
        parts.append(f"**Author:** u/{self.item.author}")
        parts.append(f"**Author Karma:** {self.item.author_karma:,}")
        parts.append(f"**Account Age:** {self.item.account_age_days} days")
        parts.append(f"**URL:** {self.item.url}")
        parts.append("")
        parts.append("**Content:**")
        parts.append("```")
        parts.append(self.item.body[:2000] if self.item.body else "[No text content]")
        parts.append("```")
        parts.append("")

        # Reports if any
        if self.item.reports:
            parts.append("## Reports")
            for report in self.item.reports:
                if report.get("type") == "user":
                    parts.append(f"- User report: {report['reason']} (x{report.get('count', 1)})")
                else:
                    parts.append(f"- Mod report: {report['reason']} (by {report.get('by', 'mod')})")
            parts.append("")

        # Subreddit rules
        if self.subreddit_rules:
            parts.append("## Subreddit Rules")
            for i, rule in enumerate(self.subreddit_rules, 1):
                parts.append(f"{i}. **{rule.get('short_name', 'Rule')}**: {rule.get('description', '')}")
            parts.append("")

        # Available removal reasons
        if self.removal_reasons:
            parts.append("## Available Removal Reasons")
            for reason in self.removal_reasons:
                parts.append(f"- **{reason.title}** (ID: `{reason.id}`)")
            parts.append("")

        # Recent decisions for context
        if self.recent_decisions:
            parts.append("## Recent Similar Decisions")
            for decision in self.recent_decisions[:5]:
                parts.append(f"- {decision.action.upper()}: {decision.reason[:100]}")
            parts.append("")

        return "\n".join(parts)


def build_prompt(
    item: RedditItem,
    subreddit_rules: list[dict],
    removal_reasons: list[RemovalReason],
    recent_decisions: list[Decision],
) -> str:
    """Build the full prompt for Claude including instructions."""
    context = ModerationContext(
        item=item,
        subreddit_rules=subreddit_rules,
        removal_reasons=removal_reasons,
        recent_decisions=recent_decisions,
    )

    instructions = """You are a moderator for r/chubbyfire, a subreddit for people pursuing "chubbyFIRE"
(Financial Independence, Retire Early with a target of $2.5M-$5M in assets).

Your task is to review the content below and make a moderation decision.

## Decision Guidelines

1. **APPROVE** if:
   - Content is relevant to FIRE, financial independence, retirement planning
   - Tone is civil and constructive
   - No spam, self-promotion, or rule violations
   - Confidence should be 0.85+ for auto-approve

2. **REMOVE** if:
   - Clear spam or self-promotion
   - Off-topic content unrelated to FIRE
   - Harassment, insults, or incivility
   - Clear rule violations
   - Confidence should be 0.85+ for auto-remove
   - Select an appropriate removal_reason_id

3. **FLAG** for human review if:
   - Borderline cases
   - You're uncertain
   - Content is controversial but might be valid
   - Confidence below 0.7

## Response Format

You MUST end your response with these fields (exactly as shown):

DECISION: [approve|remove|flag]
CONFIDENCE: [0.0-1.0]
REASON: [Brief explanation]
REMOVAL_REASON_ID: [ID from available reasons, only if removing]

---

"""

    return instructions + context.to_prompt()


class ClaudeSession:
    """Spawns Claude sessions for moderation decisions."""

    def __init__(self, timeout: int = 60):
        """Initialize the session spawner."""
        self.timeout = timeout

    def get_decision(
        self,
        item: RedditItem,
        subreddit_rules: list[dict],
        removal_reasons: list[RemovalReason],
        recent_decisions: list[Decision],
    ) -> ModerationDecision:
        """Get a moderation decision from Claude."""
        prompt = build_prompt(
            item=item,
            subreddit_rules=subreddit_rules,
            removal_reasons=removal_reasons,
            recent_decisions=recent_decisions,
        )

        try:
            result = subprocess.run(
                ["claude", "-p", prompt],
                capture_output=True,
                text=True,
                timeout=self.timeout,
            )

            if result.returncode != 0:
                # Claude CLI failed, flag for review
                return ModerationDecision(
                    action="flag",
                    confidence=0.3,
                    reason=f"Claude CLI error: {result.stderr or 'unknown error'}",
                )

            return ModerationDecision.parse(result.stdout)

        except subprocess.TimeoutExpired:
            return ModerationDecision(
                action="flag",
                confidence=0.3,
                reason="Claude session timed out",
            )
        except FileNotFoundError:
            return ModerationDecision(
                action="flag",
                confidence=0.3,
                reason="Claude CLI not found",
            )
        except Exception as e:
            return ModerationDecision(
                action="flag",
                confidence=0.3,
                reason=f"Error: {str(e)}",
            )
