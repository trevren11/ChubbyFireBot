"""Claude session spawner for moderation decisions via Taskling API."""

import base64
import json
import os
import re
import time
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Optional
from urllib.error import URLError

from src.reddit_client import RedditItem, RemovalReason
from src.decision_logger import Decision


# Taskling API endpoint
TASKLING_API_URL = "http://localhost:2525/api/chat/send"
# Working directory for Claude sessions
WORKING_DIR = "/Users/trenshaw/code/tasks/chubbyfire/ChubbyFireBot-chubbyfire-automated-moderating"
# Chat state directory
CHAT_STATE_DIR = Path.home() / ".taskling" / "chat-state"


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


def get_chat_state_path(mr_path: str, agent_index: int = 0) -> Path:
    """Get the chat state file path for a given MR path and agent index."""
    key = f"{mr_path}:{agent_index}"
    encoded = base64.urlsafe_b64encode(key.encode()).decode().rstrip("=")
    return CHAT_STATE_DIR / f"{encoded}.json"


def extract_text_from_blocks(blocks: list) -> str:
    """Extract text content from assistant message blocks."""
    texts = []
    for block in blocks:
        if block.get("type") == "text":
            texts.append(block.get("content", ""))
    return "\n".join(texts)


class ClaudeSession:
    """Spawns Claude sessions via Taskling API for moderation decisions."""

    def __init__(
        self,
        timeout: int = 120,
        api_url: str = TASKLING_API_URL,
        poll_interval: float = 2.0,
    ):
        """Initialize the session spawner."""
        self.timeout = timeout
        self.api_url = api_url
        self.poll_interval = poll_interval

    def _get_chat_state(self, mr_path: str, agent_index: int = 0) -> Optional[dict]:
        """Read the current chat state from disk."""
        state_path = get_chat_state_path(mr_path, agent_index)
        if not state_path.exists():
            return None
        try:
            with open(state_path) as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            return None

    def _wait_for_response(
        self, mr_path: str, initial_message_count: int, agent_index: int = 0
    ) -> Optional[str]:
        """Poll chat state until we get a complete response with DECISION field or timeout."""
        start_time = time.time()
        poll_count = 0
        last_text_len = 0

        while time.time() - start_time < self.timeout:
            poll_count += 1
            state = self._get_chat_state(mr_path, agent_index)
            if state and state.get("messages"):
                messages = state["messages"]
                current_count = len(messages)
                # Check if we have new messages and the last assistant message has content
                if current_count > initial_message_count:
                    last_msg = messages[-1]
                    role = last_msg.get("role")
                    blocks = last_msg.get("blocks", [])
                    if role == "assistant" and blocks:
                        # Check if there's actual text content (not just tool calls)
                        text = extract_text_from_blocks(blocks)
                        if text.strip():
                            # Wait until we see the DECISION field (Claude is still streaming)
                            if "DECISION:" in text.upper():
                                return text
                            # If text is still growing, keep polling
                            if len(text) != last_text_len:
                                last_text_len = len(text)
            time.sleep(self.poll_interval)

        return None

    def get_decision(
        self,
        item: RedditItem,
        subreddit_rules: list[dict],
        removal_reasons: list[RemovalReason],
        recent_decisions: list[Decision],
    ) -> ModerationDecision:
        """Get a moderation decision from Claude via Taskling API."""
        prompt = build_prompt(
            item=item,
            subreddit_rules=subreddit_rules,
            removal_reasons=removal_reasons,
            recent_decisions=recent_decisions,
        )

        try:
            # Use a unique agent index for each request to avoid state conflicts
            # (Each post gets its own fresh session)
            import random
            request_agent_index = random.randint(100, 999)

            # Get initial message count to know when response arrives
            initial_state = self._get_chat_state(WORKING_DIR, request_agent_index)
            initial_count = len(initial_state.get("messages", [])) if initial_state else 0

            # Build request payload for Taskling API with unique agent index
            payload = json.dumps({
                "mrPath": WORKING_DIR,
                "message": prompt,
                "agentIndex": request_agent_index,
            }).encode("utf-8")

            request = urllib.request.Request(
                self.api_url,
                data=payload,
                headers={"Content-Type": "application/json"},
                method="POST",
            )

            with urllib.request.urlopen(request, timeout=30) as response:
                result = json.loads(response.read().decode("utf-8"))

            # Check for API errors
            if not result.get("success"):
                return ModerationDecision(
                    action="flag",
                    confidence=0.3,
                    reason=f"Taskling API error: {result.get('error', 'unknown error')}",
                )

            # Poll for the response using the unique agent index
            claude_response = self._wait_for_response(
                WORKING_DIR, initial_count, request_agent_index
            )

            if not claude_response:
                return ModerationDecision(
                    action="flag",
                    confidence=0.3,
                    reason="Claude session timed out waiting for response",
                )

            return ModerationDecision.parse(claude_response)

        except URLError as e:
            return ModerationDecision(
                action="flag",
                confidence=0.3,
                reason=f"Connection error to Taskling API: {str(e)}",
            )
        except TimeoutError:
            return ModerationDecision(
                action="flag",
                confidence=0.3,
                reason="Claude session timed out",
            )
        except Exception as e:
            return ModerationDecision(
                action="flag",
                confidence=0.3,
                reason=f"Error: {str(e)}",
            )
