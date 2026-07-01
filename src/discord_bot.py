"""Discord bot for moderation notifications and interactions."""

import json
import os
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Optional

import discord
from discord import ButtonStyle, Embed, Interaction
from discord.ext import commands
from discord.ui import Button, View

from src.reddit_client import RedditItem, RemovalReason


def _author_history_field(author: str, decision_logger=None) -> Optional[dict]:
    """Build a mod history embed field for an author, or None if first time."""
    if not decision_logger:
        return None
    past = decision_logger.get_by_author(author)
    if not past:
        return None
    posts = sum(1 for d in past if d.content_type == "post")
    comments = sum(1 for d in past if d.content_type == "comment")
    approved = sum(1 for d in past if d.action == "approve")
    removed = sum(1 for d in past if d.action == "remove")
    flagged = sum(1 for d in past if d.action == "flag")
    parts = []
    if posts:
        parts.append(f"{posts} post{'s' if posts != 1 else ''}")
    if comments:
        parts.append(f"{comments} comment{'s' if comments != 1 else ''}")
    summary = " · ".join(parts) + " seen"
    actions = []
    if approved:
        actions.append(f"{approved} approved")
    if removed:
        actions.append(f"{removed} removed")
    if flagged:
        actions.append(f"{flagged} flagged")
    if actions:
        summary += " — " + ", ".join(actions)
    return {"name": "Mod History", "value": summary, "inline": False}


def send_bot_message(
    item: RedditItem,
    bot_decision: str,
    confidence: float,
    reason: str,
    dry_run: bool = False,
    decision_logger=None,
    auto_actioned: bool = False,
    prior_decision=None,
) -> bool:
    """Send notification via Discord bot REST API (for cron jobs)."""
    bot_token = os.getenv("DISCORD_BOT_TOKEN")
    channel_id = os.getenv("DISCORD_CHANNEL_ID")

    if not bot_token or not channel_id:
        print("Missing DISCORD_BOT_TOKEN or DISCORD_CHANNEL_ID")
        return False

    # Build embed
    dry_prefix = "[DRY RUN] " if dry_run else ""
    if auto_actioned and bot_decision == "remove":
        action_prefix = "[AUTO-REMOVED] "
    elif auto_actioned and bot_decision == "approve":
        action_prefix = "[AUTO-APPROVED] "
    else:
        action_prefix = f"[{item.content_type.upper()}] "
    title = item.title[:200] if item.title else "Comment"

    colors = {"approve": 0x00FF00, "remove": 0xFF0000, "flag": 0xFFFF00}
    color = colors.get(bot_decision, 0x0000FF)

    description = f"**Author:** u/{item.author} ({item.author_karma:,} karma, {item.account_age_days}d old)"
    if not auto_actioned:
        description += f"\n\n>>> {item.body[:3800] if item.body else '_No content_'}"

    fields = [
        {"name": "Decision", "value": f"**{bot_decision.upper()}** ({confidence:.0%})", "inline": True},
        {"name": "Reason", "value": reason[:256], "inline": True},
    ]
    if prior_decision:
        fields.append({
            "name": "⚠️ Previously Actioned",
            "value": f"**{prior_decision.action.upper()}**ed ({prior_decision.confidence:.0%}) — {prior_decision.reason[:150]}",
            "inline": False,
        })
    history_field = _author_history_field(item.author, decision_logger)
    if history_field:
        fields.append(history_field)

    embed = {
        "title": f"{dry_prefix}{action_prefix}{title}",
        "description": description,
        "color": color,
        "url": item.url,
        "fields": fields,
        "footer": {"text": f"ID: {item.reddit_id}"},
    }

    # Only include buttons if human review is needed
    payload_data: dict = {"embeds": [embed]}
    if not auto_actioned:
        payload_data["components"] = [{"type": 1, "components": [
            {"type": 2, "style": 3, "label": "✅ Approve", "custom_id": f"approve_{item.reddit_id}"},
            {"type": 2, "style": 4, "label": "❌ Remove", "custom_id": f"remove_{item.reddit_id}"},
        ]}]

    payload = json.dumps(payload_data).encode("utf-8")

    try:
        req = urllib.request.Request(
            f"https://discord.com/api/v10/channels/{channel_id}/messages",
            data=payload,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bot {bot_token}",
                "User-Agent": "DiscordBot (https://github.com/Rapptz/discord.py, 2.3.2)",
            },
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            return resp.status == 200
    except Exception as e:
        print(f"Discord bot API error: {e}")
        return False


class ModerationEmbed:
    """Builder for moderation notification embeds."""

    @staticmethod
    def create(
        item: RedditItem,
        bot_decision: str,
        confidence: float,
        reason: str,
        dry_run: bool = False,
        decision_logger=None,
        auto_actioned: bool = False,
        prior_decision=None,
    ) -> Embed:
        """Create an embed for a moderation decision."""
        # Title based on content type and whether bot already acted
        if auto_actioned and bot_decision == "remove":
            prefix = "[AUTO-REMOVED]"
        elif auto_actioned and bot_decision == "approve":
            prefix = "[AUTO-APPROVED]"
        elif item.content_type == "post":
            prefix = "[POST]"
        else:
            prefix = "[COMMENT]"

        base_title = item.title[:200] if item.title else "Review Needed"
        title = f"{prefix} {base_title}"

        if dry_run:
            title = f"[DRY RUN] {title}"

        # Color based on decision
        colors = {
            "approve": discord.Color.green(),
            "remove": discord.Color.red(),
            "flag": discord.Color.yellow(),
        }
        color = colors.get(bot_decision, discord.Color.blue())

        # Build description
        karma_str = f"{item.author_karma:,}"
        description_parts = [
            f"**Author:** u/{item.author} ({karma_str} karma, {item.account_age_days}d old)",
        ]

        if item.reports:
            report_strs = []
            for r in item.reports[:3]:  # Limit to 3 reports
                if r.get("type") == "user":
                    report_strs.append(f"{r['reason']} (x{r.get('count', 1)})")
                else:
                    report_strs.append(f"{r['reason']} [mod]")
            description_parts.append(f"**Reports:** {', '.join(report_strs)}")

        # For auto-actioned items, skip the body — just show author line
        if not auto_actioned:
            description_parts.append("")
            content = item.body or ""
            description_parts.append(f">>> {content}" if content else "_No text content_")

        description = "\n".join(description_parts)

        # Discord embed description hard limit is 4096 chars
        if len(description) > 4096:
            description = description[:4093] + "..."

        embed = Embed(
            title=title,
            description=description,
            color=color,
            url=item.url,
            timestamp=datetime.now(timezone.utc),
        )

        # Add decision field
        confidence_pct = f"{confidence * 100:.0f}%"
        decision_text = f"**{bot_decision.upper()}** ({confidence_pct} confidence)"
        embed.add_field(name="Bot Decision", value=decision_text, inline=True)
        embed.add_field(name="Reason", value=reason[:256], inline=True)

        if prior_decision:
            embed.add_field(
                name="⚠️ Previously Actioned",
                value=f"**{prior_decision.action.upper()}**ed ({prior_decision.confidence:.0%}) — {prior_decision.reason[:150]}",
                inline=False,
            )

        history_field = _author_history_field(item.author, decision_logger)
        if history_field:
            embed.add_field(name=history_field["name"], value=history_field["value"], inline=False)

        embed.set_footer(text=f"ID: {item.reddit_id}")

        return embed


class MessageTracker:
    """Tracks Discord message IDs to Reddit item IDs."""

    def __init__(self, file_path: Path):
        """Initialize the tracker with a file path."""
        self.file_path = Path(file_path)
        self._mappings: dict[str, dict] = {}
        self._load()

    def _load(self) -> None:
        """Load mappings from disk."""
        if self.file_path.exists():
            with open(self.file_path) as f:
                self._mappings = json.load(f)

    def _save(self) -> None:
        """Save mappings to disk."""
        self.file_path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.file_path, "w") as f:
            json.dump(self._mappings, f)

    def save(self, discord_id: str, reddit_id: str) -> None:
        """Save a Discord message ID to Reddit item ID mapping."""
        self._mappings[discord_id] = {
            "reddit_id": reddit_id,
            "created": datetime.now(timezone.utc).isoformat(),
        }
        self._save()

    def get_reddit_id(self, discord_id: str) -> Optional[str]:
        """Get the Reddit ID for a Discord message ID."""
        mapping = self._mappings.get(discord_id)
        return mapping["reddit_id"] if mapping else None

    def delete(self, discord_id: str) -> None:
        """Delete a mapping."""
        if discord_id in self._mappings:
            del self._mappings[discord_id]
            self._save()


class ActionButton:
    """Factory for action buttons."""

    @staticmethod
    def approve() -> Button:
        """Create an approve button."""
        return Button(
            label="Approve",
            style=ButtonStyle.success,
            custom_id="approve",
        )

    @staticmethod
    def remove(reason: RemovalReason) -> Button:
        """Create a remove button for a specific reason."""
        # Truncate label if needed
        label = f"Remove: {reason.title}"
        if len(label) > 80:
            label = label[:77] + "..."

        return Button(
            label=label,
            style=ButtonStyle.danger,
            custom_id=f"remove:{reason.id}",
        )


class ModerationView(View):
    """View containing moderation action buttons."""

    def __init__(
        self,
        removal_reasons: list[RemovalReason],
        on_approve: Callable[[Interaction], None],
        on_remove: Callable[[Interaction, str], None],
        timeout: float = 86400,  # 24 hours
    ):
        """Initialize the view with buttons."""
        super().__init__(timeout=timeout)
        self.on_approve_callback = on_approve
        self.on_remove_callback = on_remove

        # Add approve button
        approve_btn = ActionButton.approve()
        approve_btn.callback = self._handle_approve
        self.add_item(approve_btn)

        # Add remove buttons for each reason (up to 4 to fit Discord limits)
        for reason in removal_reasons[:4]:
            remove_btn = ActionButton.remove(reason)
            remove_btn.callback = self._make_remove_handler(reason.id)
            self.add_item(remove_btn)

    async def _handle_approve(self, interaction: Interaction) -> None:
        """Handle approve button click."""
        await self.on_approve_callback(interaction)

    def _make_remove_handler(self, reason_id: str):
        """Create a remove handler for a specific reason."""

        async def handler(interaction: Interaction) -> None:
            await self.on_remove_callback(interaction, reason_id)

        return handler


class DiscordBot:
    """Discord bot for moderation notifications."""

    def __init__(
        self,
        token: str,
        channel_id: int,
        data_dir: Path,
    ):
        """Initialize the Discord bot."""
        self.token = token
        self.channel_id = channel_id
        self.data_dir = Path(data_dir)

        intents = discord.Intents.default()
        intents.message_content = True

        self._bot = commands.Bot(command_prefix="!", intents=intents)
        self.tracker = MessageTracker(self.data_dir / "discord_messages.json")

        # Callbacks for actions (set by the main app)
        self._approve_handler: Optional[Callable] = None
        self._remove_handler: Optional[Callable] = None

    def set_action_handlers(
        self,
        on_approve: Callable[[str], None],
        on_remove: Callable[[str, str], None],
    ) -> None:
        """Set handlers for approve and remove actions."""
        self._approve_handler = on_approve
        self._remove_handler = on_remove

    async def handle_approve(self, interaction: Interaction) -> None:
        """Handle an approve action from Discord."""
        message_id = str(interaction.message.id)
        reddit_id = self.tracker.get_reddit_id(message_id)

        if reddit_id and self._approve_handler:
            self._approve_handler(reddit_id)
            await interaction.response.send_message(
                f"Approved {reddit_id}",
                ephemeral=True,
            )
            # Update the embed to show it was handled
            embed = interaction.message.embeds[0]
            embed.color = discord.Color.green()
            embed.title = f"[APPROVED] {embed.title}"
            await interaction.message.edit(embed=embed, view=None)
        else:
            await interaction.response.send_message(
                "Could not find Reddit item for this message",
                ephemeral=True,
            )

    async def handle_remove(self, interaction: Interaction, reason_id: str) -> None:
        """Handle a remove action from Discord."""
        message_id = str(interaction.message.id)
        reddit_id = self.tracker.get_reddit_id(message_id)

        if reddit_id and self._remove_handler:
            self._remove_handler(reddit_id, reason_id)
            await interaction.response.send_message(
                f"Removed {reddit_id} with reason {reason_id}",
                ephemeral=True,
            )
            # Update the embed to show it was handled
            embed = interaction.message.embeds[0]
            embed.color = discord.Color.red()
            embed.title = f"[REMOVED] {embed.title}"
            await interaction.message.edit(embed=embed, view=None)
        else:
            await interaction.response.send_message(
                "Could not find Reddit item for this message",
                ephemeral=True,
            )

    async def send_moderation_message(
        self,
        item: RedditItem,
        bot_decision: str,
        confidence: float,
        reason: str,
        removal_reasons: list[RemovalReason],
        dry_run: bool = False,
        decision_logger=None,
        auto_actioned: bool = False,
        prior_decision=None,
    ) -> str:
        """Send a moderation message to Discord and return the message ID."""
        channel = self._bot.get_channel(self.channel_id)
        if not channel:
            raise ValueError(f"Channel {self.channel_id} not found")

        embed = ModerationEmbed.create(
            item=item,
            bot_decision=bot_decision,
            confidence=confidence,
            reason=reason,
            dry_run=dry_run,
            decision_logger=decision_logger,
            auto_actioned=auto_actioned,
            prior_decision=prior_decision,
        )

        if auto_actioned:
            message = await channel.send(embed=embed)
        else:
            view = ModerationView(
                removal_reasons=removal_reasons,
                on_approve=self.handle_approve,
                on_remove=self.handle_remove,
            )
            message = await channel.send(embed=embed, view=view)

        # Track the mapping
        self.tracker.save(str(message.id), item.reddit_id)

        return str(message.id)

    async def start(self) -> None:
        """Start the Discord bot."""
        await self._bot.start(self.token)

    async def close(self) -> None:
        """Close the Discord bot."""
        await self._bot.close()
