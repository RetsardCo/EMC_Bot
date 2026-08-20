import discord
from discord import app_commands
from discord.ext import commands

class Admin(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="nick", description="Change a member's nickname.")
    @app_commands.describe(member="Member whose nickname you want to change", nickname="New nickname")
    @app_commands.checks.has_permissions(manage_nicknames=True)
    async def nick(self, interaction: discord.Interaction, member: discord.Member, nickname: str):
        try:
            old_nick = member.nick or member.name
            await member.edit(nick=nickname[:32], reason=f"Manual nickname change by {interaction.user}")
            await interaction.response.send_message(f"✏️ Changed **{old_nick}** → **{nickname[:32]}**")
        except discord.Forbidden:
            await interaction.response.send_message("I can't change that member's nickname. Check my role position and permissions.", ephemeral=True)

    @app_commands.command(name="serverinfo", description="Show basic information about the server.")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def serverinfo(self, interaction: discord.Interaction):
        guild = interaction.guild
        if guild is None:
            await interaction.response.send_message("This command can only be used in a server.", ephemeral=True)
            return

        embed = discord.Embed(title=guild.name, color=discord.Color.blurple())
        embed.add_field(name="Members", value=str(guild.member_count), inline=True)
        embed.add_field(name="Channels", value=str(len(guild.channels)), inline=True)
        embed.add_field(name="Roles", value=str(len(guild.roles)), inline=True)
        if guild.owner:
            embed.add_field(name="Owner", value=guild.owner.mention, inline=True)
        embed.set_thumbnail(url=guild.icon.url if guild.icon else discord.Embed.Empty)
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="announce", description="Send an announcement to a selected channel.")
    @app_commands.describe(channel="Channel where the announcement will be posted", message="Announcement text")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def announce(self, interaction: discord.Interaction, channel: discord.TextChannel, message: str):
        embed = discord.Embed(
            title="📢 Announcement",
            description=message,
            color=discord.Color.gold(),
        )
        embed.set_footer(text=f"Posted by {interaction.user}")

        try:
            await channel.send(embed=embed)
            await interaction.response.send_message(f"Announcement posted in {channel.mention}.", ephemeral=True)
        except discord.Forbidden:
            await interaction.response.send_message("I don't have permission to send messages in that channel.", ephemeral=True)

async def setup(bot: commands.Bot):
    await bot.add_cog(Admin(bot))
