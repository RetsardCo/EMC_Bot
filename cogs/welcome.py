from __future__ import annotations

import logging
import random

import discord
from discord.ext import commands

from .common import (
    INTRO_COMPLETE_CHANNEL_ID,
    UNINTRODUCED_ROLE_NAME,
    WELCOME_CHANNEL_ID,
    add_role_if_missing,
    get_text_channel,
)

logger = logging.getLogger("em-bot.welcome")

WELCOME_HEADLINES = (
    "✨ Hey, {name}, congratulations on joining the official BSEMC Discord server!",
    "🎉 Congrats, {name}, on joining the official BSEMC Discord server!",
    "🚀 Welcome aboard, {name}! You're now part of the official BSEMC Discord server!",
    "🌟 Great to have you here, {name}! Welcome to the official BSEMC Discord server!",
    "👋 Hey, {name}! Congratulations on joining the official BSEMC Discord server!",
)


class Welcome(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    async def _resolve_welcome_channel(
        self,
        member: discord.Member,
    ) -> discord.TextChannel | None:
        """
        Resolve the welcome channel in this order:

        1. Explicit WELCOME_CHANNEL_ID from .env, when configured.
        2. A text channel named exactly "welcome".
        3. Common welcome-channel names such as "welcome-channel".
        4. The server system channel.

        This means WELCOME_CHANNEL_ID can safely remain 0/blank when the
        server has a #welcome channel.
        """
        # 1. Explicit channel ID wins when configured.
        if WELCOME_CHANNEL_ID:
            channel = await get_text_channel(
                member.guild,
                WELCOME_CHANNEL_ID,
            )
            if channel is not None:
                logger.info(
                    "Using configured welcome channel #%s (%s).",
                    channel.name,
                    channel.id,
                )
                return channel

            logger.warning(
                "Configured WELCOME_CHANNEL_ID=%s was not found/usable in guild %s.",
                WELCOME_CHANNEL_ID,
                member.guild.id,
            )

        # 2. Exact #welcome match.
        normalized_names = {
            "welcome",
            "welcome-channel",
            "welcome_channel",
            "welcomes",
        }

        for channel in member.guild.text_channels:
            name = channel.name.casefold().strip()

            if name in normalized_names:
                logger.info(
                    "Auto-detected welcome channel #%s (%s).",
                    channel.name,
                    channel.id,
                )
                return channel

        # 3. Fuzzy fallback for channels containing "welcome".
        for channel in member.guild.text_channels:
            name = channel.name.casefold().strip()

            if "welcome" in name:
                logger.info(
                    "Auto-detected welcome channel by name #%s (%s).",
                    channel.name,
                    channel.id,
                )
                return channel

        # 4. Server system channel.
        system_channel = member.guild.system_channel
        if isinstance(system_channel, discord.TextChannel):
            logger.warning(
                "No #welcome channel found. Falling back to system channel "
                "#%s (%s).",
                system_channel.name,
                system_channel.id,
            )
            return system_channel

        logger.error(
            "No usable welcome channel found in guild %s (%s). "
            "Set WELCOME_CHANNEL_ID or create a #welcome channel.",
            member.guild.name,
            member.guild.id,
        )
        return None

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member) -> None:
        if member.bot:
            logger.info(
                "Ignoring bot member join: %s (%s)",
                member,
                member.id,
            )
            return

        logger.info(
            "WELCOME EVENT: %s (%s) joined %s (%s).",
            member,
            member.id,
            member.guild.name,
            member.guild.id,
        )

        try:
            added = await add_role_if_missing(
                member,
                UNINTRODUCED_ROLE_NAME,
            )
            logger.info(
                "WELCOME ROLE: attempted Unintroduced for %s; result=%s.",
                member,
                added,
            )
        except Exception:
            logger.exception(
                "Failed to add %s role to %s.",
                UNINTRODUCED_ROLE_NAME,
                member,
            )

        channel = await self._resolve_welcome_channel(member)
        if channel is None:
            return

        embed = discord.Embed(
            title=random.choice(WELCOME_HEADLINES).format(
                name=member.display_name,
            ),
            description=(
                "Please complete the steps below to get started.\n\n"
                "**1. Set up your profile**\n\n"
                "Type **/setup** and complete the form.\n\n"
                "**2. Students**\n\n"
                "Enter your full name, specialization, and year. "
                "EM Bot will set your nickname and assign your BISCAST, "
                "Student, and DAT/GD year roles.\n\n"
                "**3. Verified faculty**\n\n"
                "If you were manually given the **!Faculty** role, use **/setup** "
                "to complete the Faculty form.\n\n"
                "**4. After setup**\n\n"
                "Once your introduction is complete, you can explore and "
                "participate normally in the server."
            ),
            color=discord.Color.blurple(),
        )

        try:
            embed.set_thumbnail(
                url=member.display_avatar.url,
            )

            sent = await channel.send(
                content=member.mention,
                embed=embed,
            )

            logger.info(
                "WELCOME SENT: message=%s channel=%s (%s) member=%s.",
                sent.id,
                channel.name,
                channel.id,
                member.id,
            )

        except discord.Forbidden:
            logger.exception(
                "WELCOME FAILED: missing permission to send in #%s (%s) "
                "for member %s (%s).",
                channel.name,
                channel.id,
                member,
                member.id,
            )
        except discord.HTTPException:
            logger.exception(
                "WELCOME FAILED: Discord HTTP error sending in #%s (%s) "
                "for member %s (%s).",
                channel.name,
                channel.id,
                member,
                member.id,
            )
        except Exception:
            logger.exception(
                "WELCOME FAILED: unexpected error for member %s (%s).",
                member,
                member.id,
            )

    async def send_introduction_complete_welcome(
        self,
        member: discord.Member,
        nickname: str,
    ) -> None:
        channel = await get_text_channel(
            member.guild,
            INTRO_COMPLETE_CHANNEL_ID,
        )
        if not channel:
            logger.warning(
                "INTRO COMPLETE: channel %s unavailable in guild %s.",
                INTRO_COMPLETE_CHANNEL_ID,
                member.guild.id,
            )
            return

        embed = discord.Embed(
            title="Welcome to BSEMC!",
            description=(
                f"Welcome, {member.mention}!\n\n"
                "Your introduction is complete, and you can now explore and participate "
                "in the server.\n\n"
                f"**Nickname:** `{nickname}`"
            ),
            color=discord.Color.green(),
        )

        try:
            await channel.send(
                embed=embed,
            )
        except Exception:
            logger.exception(
                "Failed to send introduction-complete welcome for %s (%s).",
                member,
                member.id,
            )


    @commands.hybrid_command(
        name="welcome_test",
        description="Staff: test the automatic welcome channel.",
    )
    @commands.has_permissions(manage_guild=True)
    async def welcome_test(
        self,
        ctx: commands.Context,
    ) -> None:
        if not ctx.guild or not isinstance(ctx.author, discord.Member):
            await ctx.send(
                "This command can only be used inside a server.",
                ephemeral=True,
            )
            return

        channel = await self._resolve_welcome_channel(ctx.guild.get_member(ctx.author.id) or ctx.author)

        if channel is None:
            await ctx.send(
                "1. No welcome channel could be detected.\n\n"
                "2. Create a `#welcome` channel or set `WELCOME_CHANNEL_ID` in `.env`.",
                ephemeral=True,
            )
            return

        if not channel.permissions_for(ctx.guild.me).send_messages:
            await ctx.send(
                f"1. I found `{channel.name}`, but I do not have **Send Messages** permission there.\n\n"
                f"2. Channel ID: `{channel.id}`",
                ephemeral=True,
            )
            return

        embed = discord.Embed(
            title=random.choice(WELCOME_HEADLINES).format(
                name=ctx.author.display_name,
            ),
            description=(
                "This is a **welcome-system test**.\n\n"
                "The automatic welcome channel detection is working."
            ),
            color=discord.Color.blurple(),
        )
        embed.set_thumbnail(
            url=ctx.author.display_avatar.url,
        )

        try:
            message = await channel.send(
                content=ctx.author.mention,
                embed=embed,
            )
        except discord.Forbidden:
            logger.exception(
                "WELCOME TEST FAILED: permission denied in #%s (%s).",
                channel.name,
                channel.id,
            )
            await ctx.send(
                f"1. Permission denied in `{channel.name}`.\n\n"
                f"2. Channel ID: `{channel.id}`",
                ephemeral=True,
            )
            return
        except discord.HTTPException as error:
            logger.exception(
                "WELCOME TEST FAILED: Discord HTTP error: %s",
                error,
            )
            await ctx.send(
                f"1. Discord rejected the message: `{error}`.",
                ephemeral=True,
            )
            return

        await ctx.send(
            f"1. Welcome channel detected: `{channel.name}`.\n\n"
            f"2. Test message sent successfully.\n\n"
            f"3. Message ID: `{message.id}`.",
            ephemeral=True,
        )



async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Welcome(bot))
