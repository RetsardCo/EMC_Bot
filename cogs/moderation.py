from datetime import timedelta

import discord
from discord import app_commands
from discord.ext import commands

from .common import is_staff, log_mod


def staff_only():
    async def predicate(interaction: discord.Interaction) -> bool:
        member = interaction.user
        return isinstance(member, discord.Member) and is_staff(member)

    return app_commands.check(predicate)


class Moderation(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="timeout", description="Timeout a member.")
    @app_commands.describe(
        member="Member",
        minutes="Minutes",
        reason="Reason",
    )
    @app_commands.checks.has_permissions(moderate_members=True)
    @staff_only()
    async def timeout(
        self,
        interaction: discord.Interaction,
        member: discord.Member,
        minutes: app_commands.Range[int, 1, 40320],
        reason: str = "No reason provided",
    ) -> None:
        try:
            await member.timeout(
                timedelta(minutes=minutes),
                reason=reason,
            )
            await log_mod(
                interaction.guild,
                (
                    f"⏱️ {member.mention} timed out for {minutes}m "
                    f"by {interaction.user.mention}. Reason: {reason}"
                ),
            )
            await interaction.response.send_message(
                f"{member.mention} was timed out for **{minutes} minute(s)**.",
                ephemeral=True,
            )
        except discord.Forbidden:
            await interaction.response.send_message(
                "I can't timeout that member. Check role hierarchy and permissions.",
                ephemeral=True,
            )
        except discord.HTTPException:
            await interaction.response.send_message(
                "Discord rejected the timeout request.",
                ephemeral=True,
            )

    @app_commands.command(name="kick", description="Kick a member.")
    @app_commands.describe(member="Member", reason="Reason")
    @app_commands.checks.has_permissions(kick_members=True)
    @staff_only()
    async def kick(
        self,
        interaction: discord.Interaction,
        member: discord.Member,
        reason: str = "No reason provided",
    ) -> None:
        try:
            await member.kick(reason=reason)
            await log_mod(
                interaction.guild,
                f"👢 {member} kicked by {interaction.user.mention}. Reason: {reason}",
            )
            await interaction.response.send_message(
                f"{member} was kicked.",
                ephemeral=True,
            )
        except discord.Forbidden:
            await interaction.response.send_message(
                "I can't kick that member. Check role hierarchy and permissions.",
                ephemeral=True,
            )
        except discord.HTTPException:
            await interaction.response.send_message(
                "Discord rejected the kick request.",
                ephemeral=True,
            )

    @app_commands.command(name="ban", description="Ban a member.")
    @app_commands.describe(
        member="Member",
        reason="Reason",
        delete_days="Days of messages to delete (0-7)",
    )
    @app_commands.checks.has_permissions(ban_members=True)
    @staff_only()
    async def ban(
        self,
        interaction: discord.Interaction,
        member: discord.Member,
        reason: str = "No reason provided",
        delete_days: app_commands.Range[int, 0, 7] = 0,
    ) -> None:
        try:
            await member.ban(
                reason=reason,
                delete_message_days=delete_days,
            )
            await log_mod(
                interaction.guild,
                f"🔨 {member} banned by {interaction.user.mention}. Reason: {reason}",
            )
            await interaction.response.send_message(
                f"{member} was banned.",
                ephemeral=True,
            )
        except discord.Forbidden:
            await interaction.response.send_message(
                "I can't ban that member. Check role hierarchy and permissions.",
                ephemeral=True,
            )
        except discord.HTTPException:
            await interaction.response.send_message(
                "Discord rejected the ban request.",
                ephemeral=True,
            )

    @app_commands.command(
        name="purge",
        description="Delete recent messages.",
    )
    @app_commands.describe(amount="Number of messages to delete (1-100)")
    @app_commands.checks.has_permissions(manage_messages=True)
    @staff_only()
    async def purge(
        self,
        interaction: discord.Interaction,
        amount: app_commands.Range[int, 1, 100],
    ) -> None:
        channel = interaction.channel

        if not isinstance(channel, discord.TextChannel):
            await interaction.response.send_message(
                "Use this in a text channel.",
                ephemeral=True,
            )
            return

        await interaction.response.defer(ephemeral=True)

        try:
            deleted = await channel.purge(limit=amount)
            await log_mod(
                interaction.guild,
                (
                    f"🧹 {interaction.user.mention} deleted "
                    f"{len(deleted)} messages in {channel.mention}."
                ),
            )
            await interaction.followup.send(
                f"Deleted **{len(deleted)} message(s)**.",
                ephemeral=True,
            )
        except discord.Forbidden:
            await interaction.followup.send(
                "I don't have permission to delete those messages.",
                ephemeral=True,
            )
        except discord.HTTPException:
            await interaction.followup.send(
                "Discord rejected the purge request.",
                ephemeral=True,
            )


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Moderation(bot))
