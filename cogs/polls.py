from __future__ import annotations

import asyncio
import re
import time
from dataclasses import dataclass, field
from typing import Dict, List

import discord
from discord import app_commands
from discord.ext import commands

from .common import is_faculty, log_mod


@dataclass
class Poll:
    question: str
    options: List[str]
    duration_seconds: int
    allow_multiple: bool
    channel_id: int
    message_id: int | None = None
    votes: Dict[int, set[int]] = field(default_factory=dict)
    created_at: float = field(default_factory=time.time)
    closed: bool = False


ACTIVE_POLLS: Dict[int, Poll] = {}


def parse_duration(value: str) -> int | None:
    match = re.fullmatch(r"(\d+)\s*(m|min|mins|h|hr|hrs)", value.strip().lower())
    if not match:
        return None
    number = int(match.group(1))
    unit = match.group(2)
    return number * (60 if unit.startswith("m") else 3600)


def render_poll(poll: Poll) -> str:
    counts = [0 for _ in poll.options]
    for selected in poll.votes.values():
        for index in selected:
            if 0 <= index < len(counts):
                counts[index] += 1

    lines = [f"**{poll.question}**", ""]
    for index, option in enumerate(poll.options):
        lines.append(f"**{index + 1}.** {option} — **{counts[index]}** vote(s)")
    lines.append("")
    lines.append(
        f"Duration: {poll.duration_seconds // 60} minute(s) | "
        f"{'Multiple selections allowed' if poll.allow_multiple else 'One selection allowed'}"
    )
    return "\n".join(lines)


class PollView(discord.ui.View):
    def __init__(self, poll_id: int):
        super().__init__(timeout=None)
        self.poll_id = poll_id

    async def refresh(self, interaction: discord.Interaction) -> None:
        poll = ACTIVE_POLLS.get(self.poll_id)
        if not poll:
            await interaction.response.send_message("That poll is no longer active.", ephemeral=True)
            return

        await interaction.response.edit_message(content=render_poll(poll), view=self)

    @discord.ui.select(cls=discord.ui.Select, placeholder="Select option(s)", min_values=1, max_values=1)
    async def select_option(self, interaction: discord.Interaction, select: discord.ui.Select) -> None:
        poll = ACTIVE_POLLS.get(self.poll_id)
        if not poll:
            await interaction.response.send_message("That poll is no longer active.", ephemeral=True)
            return

        value = int(select.values[0])
        choices = poll.votes.setdefault(interaction.user.id, set())
        if poll.allow_multiple:
            if value in choices:
                choices.remove(value)
            else:
                choices.add(value)
        else:
            choices.clear()
            choices.add(value)

        await self.refresh(interaction)


class Polls(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.poll_counter = 0

    @app_commands.command(name="poll", description="Create a poll. Example duration: 30m or 2h.")
    async def poll(
        self,
        interaction: discord.Interaction,
        question: str,
        options: str,
        duration: str = "30m",
        multiple_selection: bool = False,
    ) -> None:
        duration_seconds = parse_duration(duration)
        if duration_seconds is None or duration_seconds < 60 or duration_seconds > 7 * 24 * 3600:
            await interaction.response.send_message("Duration must be like `30m` or `2h`, between 1 minute and 7 days.", ephemeral=True)
            return

        option_list = [o.strip() for o in options.split("|") if o.strip()]
        if not 2 <= len(option_list) <= 10:
            await interaction.response.send_message("Provide 2–10 options separated by `|`.", ephemeral=True)
            return

        self.poll_counter += 1
        poll_id = self.poll_counter
        poll = Poll(
            question=question.strip(),
            options=option_list,
            duration_seconds=duration_seconds,
            allow_multiple=multiple_selection,
            channel_id=interaction.channel_id,
        )
        ACTIVE_POLLS[poll_id] = poll

        embed = discord.Embed(description=render_poll(poll), color=discord.Color.blurple())
        view = PollButtons(poll_id)
        await interaction.response.send_message(embed=embed, view=view)
        message = await interaction.original_response()
        poll.message_id = message.id

        asyncio.create_task(self.expire_poll(poll_id))

    async def expire_poll(self, poll_id: int) -> None:
        poll = ACTIVE_POLLS.get(poll_id)
        if not poll:
            return
        await asyncio.sleep(poll.duration_seconds)
        poll = ACTIVE_POLLS.pop(poll_id, None)
        if not poll:
            return

        channel = self.bot.get_channel(poll.channel_id)
        if isinstance(channel, discord.TextChannel) and poll.message_id:
            try:
                message = await channel.fetch_message(poll.message_id)
                await message.edit(
                    content="**Poll closed.**\n\n" + render_poll(poll),
                    view=None,
                )
            except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                pass

    @app_commands.command(name="poll_results", description="Show the results of an active poll.")
    async def poll_results(self, interaction: discord.Interaction) -> None:
        polls = [p for p in ACTIVE_POLLS.values() if p.channel_id == interaction.channel_id]
        if not polls:
            await interaction.response.send_message("No active polls in this channel.", ephemeral=True)
            return
        await interaction.response.send_message("\n\n".join(render_poll(p) for p in polls), ephemeral=True)

    @app_commands.command(name="end_poll", description="End an active poll in this channel.")
    async def end_poll(self, interaction: discord.Interaction) -> None:
        if not isinstance(interaction.user, discord.Member) or not is_faculty(interaction.user):
            await interaction.response.send_message("Faculty/Moderator only.", ephemeral=True)
            return

        polls = [pid for pid, p in ACTIVE_POLLS.items() if p.channel_id == interaction.channel_id]
        if not polls:
            await interaction.response.send_message("No active polls in this channel.", ephemeral=True)
            return

        pid = polls[0]
        poll = ACTIVE_POLLS.pop(pid)
        channel = interaction.channel
        if isinstance(channel, discord.TextChannel) and poll.message_id:
            try:
                message = await channel.fetch_message(poll.message_id)
                await message.edit(content="**Poll ended early.**\n\n" + render_poll(poll), view=None)
            except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                pass

        await interaction.response.send_message("Poll ended.", ephemeral=True)
        await log_mod(interaction.guild, f"📊 Poll ended by {interaction.user.mention}.")


class PollButtons(discord.ui.View):
    def __init__(self, poll_id: int):
        super().__init__(timeout=None)
        self.poll_id = poll_id

        poll = ACTIVE_POLLS[poll_id]
        for index, option in enumerate(poll.options):
            button = discord.ui.Button(
                label=f"{index + 1}. {option[:75]}",
                style=discord.ButtonStyle.primary,
                custom_id=f"em:poll:{poll_id}:{index}",
            )
            button.callback = self.make_callback(index)
            self.add_item(button)

    def make_callback(self, index: int):
        async def callback(interaction: discord.Interaction):
            poll = ACTIVE_POLLS.get(self.poll_id)
            if not poll:
                await interaction.response.send_message("That poll is closed.", ephemeral=True)
                return

            choices = poll.votes.setdefault(interaction.user.id, set())
            if poll.allow_multiple:
                if index in choices:
                    choices.remove(index)
                else:
                    choices.add(index)
            else:
                choices.clear()
                choices.add(index)

            embed = discord.Embed(description=render_poll(poll), color=discord.Color.blurple())
            await interaction.response.edit_message(embed=embed, view=self)

        return callback


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Polls(bot))
