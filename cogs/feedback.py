from __future__ import annotations

import os

import discord
from discord import app_commands
from discord.ext import commands

FEEDBACK_CHANNEL_ID = int(
    os.getenv("FEEDBACK_CHANNEL_ID", "0")
)


class Feedback(commands.Cog):
    def __init__(
        self,
        bot: commands.Bot,
    ) -> None:
        self.bot = bot

    @app_commands.command(
        name="feedback",
        description="Send feedback or a suggestion to the staff team.",
    )
    @app_commands.describe(
        message="Your feedback, suggestion, or report.",
    )
    async def feedback(
        self,
        interaction: discord.Interaction,
        message: str,
    ) -> None:
        if not interaction.guild:
            await interaction.response.send_message(
                "1. Feedback can only be submitted inside the server.",
                ephemeral=True,
            )
            return

        if not FEEDBACK_CHANNEL_ID:
            await interaction.response.send_message(
                "1. The feedback system is not configured yet.\n\n"
                "2. Please contact a Moderator or EMC Faculty member.",
                ephemeral=True,
            )
            return

        channel = interaction.guild.get_channel(
            FEEDBACK_CHANNEL_ID
        )

        if not isinstance(
            channel,
            discord.TextChannel,
        ):
            await interaction.response.send_message(
                "1. The configured feedback channel could not be found.\n\n"
                "2. Please contact a Moderator or EMC Faculty member.",
                ephemeral=True,
            )
            return

        clean_message = message.strip()
        if not clean_message:
            await interaction.response.send_message(
                "1. Please provide feedback or a suggestion.",
                ephemeral=True,
            )
            return

        if len(clean_message) > 4000:
            await interaction.response.send_message(
                "1. Your feedback is too long.\n\n"
                "2. Keep it under 4000 characters.",
                ephemeral=True,
            )
            return

        embed = discord.Embed(
            title="💡 New Feedback",
            description=clean_message,
            color=discord.Color.blurple(),
            timestamp=discord.utils.utcnow(),
        )
        embed.add_field(
            name="Submitted by",
            value=interaction.user.mention,
            inline=True,
        )
        embed.add_field(
            name="User ID",
            value=str(interaction.user.id),
            inline=True,
        )

        try:
            await channel.send(
                embed=embed,
            )
        except discord.Forbidden:
            await interaction.response.send_message(
                "1. EM Bot cannot post to the configured feedback channel.",
                ephemeral=True,
            )
            return
        except discord.HTTPException:
            await interaction.response.send_message(
                "1. Discord rejected the feedback message.",
                ephemeral=True,
            )
            return

        await interaction.response.send_message(
            "1. Your feedback has been sent to the staff team.\n\n"
            "2. Thank you for helping improve the server.",
            ephemeral=True,
        )


async def setup(
    bot: commands.Bot,
) -> None:
    await bot.add_cog(
        Feedback(bot)
    )
