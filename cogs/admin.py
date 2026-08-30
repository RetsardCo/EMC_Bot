from __future__ import annotations

import discord
from discord import app_commands
from discord.ext import commands

from .common import is_staff


def staff_only():
    async def predicate(
        interaction: discord.Interaction,
    ) -> bool:
        member = interaction.user
        return (
            isinstance(member, discord.Member)
            and is_staff(member)
        )

    return app_commands.check(predicate)


class Admin(commands.Cog):
    def __init__(
        self,
        bot: commands.Bot,
    ) -> None:
        self.bot = bot

    @app_commands.command(
        name="nick",
        description="Manually change a member's nickname.",
    )
    @app_commands.checks.has_permissions(
        manage_nicknames=True
    )
    @staff_only()
    async def nick(
        self,
        interaction: discord.Interaction,
        member: discord.Member,
        nickname: str,
    ) -> None:
        nickname = nickname.strip()[:32]

        if not nickname:
            await interaction.response.send_message(
                "Please provide a nickname.",
                ephemeral=True,
            )
            return

        await interaction.response.defer(ephemeral=True)

        try:
            await member.edit(
                nick=nickname,
                reason=(
                    f"Manual nickname change by "
                    f"{interaction.user}"
                ),
            )
            await interaction.followup.send(
                f"Changed **{member}** to `{nickname}`.",
                ephemeral=True,
            )
        except discord.Forbidden:
            await interaction.followup.send(
                "I can't change that nickname. Check my role position and Manage Nicknames permission.",
                ephemeral=True,
            )
        except discord.HTTPException:
            await interaction.followup.send(
                "Discord rejected that nickname change.",
                ephemeral=True,
            )

    @app_commands.command(
        name="announce",
        description="Post an announcement.",
    )
    @staff_only()
    async def announce(
        self,
        interaction: discord.Interaction,
        channel: discord.TextChannel,
        message: str,
    ) -> None:
        embed = discord.Embed(
            title="Announcement",
            description=message,
            color=discord.Color.gold(),
        )
        embed.set_footer(
            text=f"Posted by {interaction.user.display_name}"
        )

        await interaction.response.defer(ephemeral=True)

        try:
            await channel.send(embed=embed)
            await interaction.followup.send(
                f"Announcement posted in {channel.mention}.",
                ephemeral=True,
            )
        except discord.Forbidden:
            await interaction.followup.send(
                "I can't send messages in that channel.",
                ephemeral=True,
            )
        except discord.HTTPException:
            await interaction.followup.send(
                "Discord rejected the announcement.",
                ephemeral=True,
            )


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Admin(bot))
