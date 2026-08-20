from datetime import timedelta

import discord
from discord import app_commands
from discord.ext import commands

class Moderation(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="timeout", description="Timeout a member for a specified number of minutes.")
    @app_commands.describe(member="Member to timeout", minutes="Timeout duration in minutes", reason="Reason")
    @app_commands.checks.has_permissions(moderate_members=True)
    async def timeout(self, interaction: discord.Interaction, member: discord.Member, minutes: app_commands.Range[int, 1, 40320], reason: str = "No reason provided"):
        try:
            await member.timeout(timedelta(minutes=minutes), reason=reason)
            await interaction.response.send_message(f"⏱️ {member.mention} has been timed out for **{minutes} minute(s)**.\nReason: {reason}")
        except discord.Forbidden:
            await interaction.response.send_message("I can't timeout that member. Check my role position and permissions.", ephemeral=True)

    @app_commands.command(name="kick", description="Kick a member from the server.")
    @app_commands.describe(member="Member to kick", reason="Reason")
    @app_commands.checks.has_permissions(kick_members=True)
    async def kick(self, interaction: discord.Interaction, member: discord.Member, reason: str = "No reason provided"):
        try:
            await member.kick(reason=reason)
            await interaction.response.send_message(f"👢 **{member}** was kicked.\nReason: {reason}")
        except discord.Forbidden:
            await interaction.response.send_message("I can't kick that member. Check my role position and permissions.", ephemeral=True)

    @app_commands.command(name="ban", description="Ban a member from the server.")
    @app_commands.describe(member="Member to ban", reason="Reason", delete_days="Days of messages to delete (0-7)")
    @app_commands.checks.has_permissions(ban_members=True)
    async def ban(self, interaction: discord.Interaction, member: discord.Member, reason: str = "No reason provided", delete_days: app_commands.Range[int, 0, 7] = 0):
        try:
            await member.ban(reason=reason, delete_message_days=delete_days)
            await interaction.response.send_message(f"🔨 **{member}** was banned.\nReason: {reason}")
        except discord.Forbidden:
            await interaction.response.send_message("I can't ban that member. Check my role position and permissions.", ephemeral=True)

    @app_commands.command(name="purge", description="Delete recent messages from this channel.")
    @app_commands.describe(amount="Number of messages to delete (1-100)")
    @app_commands.checks.has_permissions(manage_messages=True)
    async def purge(self, interaction: discord.Interaction, amount: app_commands.Range[int, 1, 100]):
        channel = interaction.channel
        if not isinstance(channel, discord.TextChannel):
            await interaction.response.send_message("Use this command in a text channel.", ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True)
        deleted = await channel.purge(limit=amount)
        await interaction.followup.send(f"🧹 Deleted **{len(deleted)}** message(s).", ephemeral=True)

async def setup(bot: commands.Bot):
    await bot.add_cog(Moderation(bot))
